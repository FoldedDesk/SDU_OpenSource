"""SQLite 持久化；业务快照只读，协同与审计在同一事务中写入。""" # 模块说明。
import json  # 序列化版本化资料。
import sqlite3  # 使用标准库，避免额外数据库中间件。
from contextlib import contextmanager  # 确保连接提交、回滚和关闭。
from pathlib import Path  # 定位数据库目录。

from app.seed import now_utc, sample_data  # 初始化本地合成数据。


def encode(value: object) -> str:  # 统一 JSON 序列化。
    """输入可序列化对象，返回保留中文的 JSON；非法对象抛出 TypeError。""" # 中文契约。
    return json.dumps(value, ensure_ascii=False, sort_keys=True)  # 使摘要和审计可复现。


class Store:  # 每次操作独立连接，可用于 FastAPI 工作线程。
    """管理本地数据库；不保存外部系统账号或客户个人信息。""" # 类型说明。

    def __init__(self, path: Path):  # 保存数据库路径。
        """输入数据库路径，初始化目录；无写权限时直接失败。""" # 中文契约。
        self.path = path  # 后续连接共用持久化文件。
        path.parent.mkdir(parents=True, exist_ok=True)  # 创建本地数据目录。

    @contextmanager  # 管理原子写入和连接生命周期。
    def connection(self):  # 提供串行化写事务。
        """无入参，产生 SQLite 连接；异常时回滚，结束时关闭。""" # 中文契约。
        conn = sqlite3.connect(self.path, timeout=10)  # 连接仅在当前线程使用。
        conn.row_factory = sqlite3.Row  # 使用具名字段。
        conn.execute("PRAGMA foreign_keys = ON")  # 禁止失去关联的协同记录。
        try:  # 保证任意异常都能释放连接。
            conn.execute("BEGIN IMMEDIATE")  # 在读取状态前加写锁，避免重复分派和重复接手。
            yield conn  # 业务操作共享同一事务。
            conn.commit()  # 状态与审计同时提交。
        except BaseException:  # 包括取消操作也必须回滚。
            conn.rollback()  # 不留下没有审计的半条状态。
            raise  # 原样向上抛出失败。
        finally:  # 无论成功失败都释放资源。
            conn.close()  # 不保留跨线程连接。

    def initialize(self, config: dict) -> None:  # 初始化表和首次样本。
        """输入配置，建表并幂等填充样本；已有快照不随重启改写。""" # 中文契约。
        statements = [  # 使用 JSON 保存不可变业务快照和版本化建议。
            "CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, payload TEXT NOT NULL)",  # 业务只读快照。
            "CREATE TABLE IF NOT EXISTS packages (id TEXT PRIMARY KEY, payload TEXT NOT NULL)",  # 原包裹记录。
            "CREATE TABLE IF NOT EXISTS case_packages (case_id TEXT REFERENCES cases(id), package_id TEXT REFERENCES packages(id), PRIMARY KEY(case_id, package_id))",  # 显式多对多。
            "CREATE TABLE IF NOT EXISTS recommendations (id TEXT PRIMARY KEY, case_id TEXT REFERENCES cases(id), fingerprint TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)",  # 相同依据的建议去重。
            "CREATE TABLE IF NOT EXISTS handoffs (id TEXT PRIMARY KEY, case_id TEXT REFERENCES cases(id), recommendation_id TEXT REFERENCES recommendations(id), sender_id TEXT NOT NULL, assignee_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, accepted_at TEXT, resolved_at TEXT)",  # 人工交接状态。
            "CREATE UNIQUE INDEX IF NOT EXISTS one_open_handoff ON handoffs(case_id) WHERE status IN ('pending', 'accepted')",  # 并发请求也只能有一个未结交接。
            "CREATE TABLE IF NOT EXISTS audits (id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, actor_id TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)",  # 追加审计流水。
        ]  # 表结构定义结束。
        with self.connection() as conn:  # 初始化也采用单个事务。
            for statement in statements:  # 逐条建表，避免 executescript 隐式提交。
                conn.execute(statement)  # 保证首次并发启动安全。
            if conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]:  # 已初始化时保持原始时间戳。
                return  # 重启不把旧快照伪装成新快照。
            cases, packages = sample_data(config, now_utc())  # 只在空库生成合成记录。
            conn.executemany("INSERT INTO cases VALUES (?, ?)", [(case["id"], encode(case)) for case in cases])  # 入库退货快照。
            conn.executemany("INSERT INTO packages VALUES (?, ?)", [(pkg["id"], encode(pkg)) for pkg in packages])  # 入库包裹。
            links = [(case_id, pkg["id"]) for pkg in packages for case_id in pkg["return_ids"]]  # 展开多对多关系。
            conn.executemany("INSERT INTO case_packages VALUES (?, ?)", links)  # 保留原关联，不靠猜测自动归单。

    def cases(self) -> list[dict]:  # 读取授权前的本地快照。
        """无入参，返回全部合成快照；权限过滤由业务服务负责。""" # 中文契约。
        with self.connection() as conn:  # 及时关闭读取连接。
            rows = conn.execute("SELECT payload FROM cases ORDER BY id").fetchall()  # 确定返回顺序。
            return [json.loads(row["payload"]) for row in rows]  # 不向调用方暴露可变数据库对象。

    def packages(self, case_id: str) -> list[dict]:  # 显式读取多对多关联。
        """输入退货单号，返回相关原始包裹；不存在时返回空列表。""" # 中文契约。
        with self.connection() as conn:  # 为关联查询创建短连接。
            rows = conn.execute("SELECT p.payload FROM packages p JOIN case_packages c ON p.id=c.package_id WHERE c.case_id=? ORDER BY p.id", (case_id,)).fetchall()  # 使用参数绑定。
            return [json.loads(row["payload"]) for row in rows]  # 返回未覆盖的原始包裹。

    def audit(self, conn, case_id: str | None, actor_id: str, action: str, payload: dict) -> None:  # 追加结构化日志。
        """输入当前事务和审计字段，追加日志；失败时随业务事务回滚。""" # 中文契约。
        conn.execute("INSERT INTO audits(case_id, actor_id, action, payload, created_at) VALUES (?, ?, ?, ?, ?)",  # 审计不保存 token。
                     (case_id, actor_id, action, encode(payload), now_utc().isoformat()))  # 与人工动作同事务提交。
