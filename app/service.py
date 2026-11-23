"""权限过滤、建议留痕与必须由实际接手人确认的交接闭环。""" # 模块说明。
import hashlib  # 为同一版本建议生成幂等摘要。
import json  # 解析持久化协同资料。
from datetime import datetime, timedelta  # 计算交接等待与演示超时。
from uuid import uuid4  # 分配协同记录编号。

from app.core import Account, DomainError, HandoffInput, require_role  # 使用服务端身份和校验。
from app.rules import assess  # 只读规则解释。
from app.seed import evidence_catalog, now_utc  # 原始事实和统一时间。
from app.store import Store, encode  # 事务与稳定序列化。

STAFF = {"support", "inspector", "manager", "engineer", "risk", "supervisor"}  # 已授权演示岗位。
DISPATCHERS = {"support", "manager", "supervisor"}  # 演示分派权限，真实授权待确认。


class Service:  # 封装可回归的业务行为。
    """操作合成快照与协同记录；任何接口都不执行退款或外部通知。""" # 类型说明。

    def __init__(self, store: Store, config: dict):  # 绑定服务配置。
        """输入存储与配置，构造服务；文档解析失败时启动失败。""" # 中文契约。
        self.store, self.config = store, config  # 不保存客户端可修改的权限。
        self.evidence = evidence_catalog()  # 加载原始访谈证据编号。
        self.accounts = {item["id"]: Account.model_validate(item) for item in config["accounts"]}  # 排除凭证。

    def visible_cases(self, actor: Account) -> list[dict]:  # 查询前按客户归属过滤。
        """输入身份，返回可见快照；客户仅得到本人售后单。""" # 中文契约。
        if actor.role != "customer":  # 内部身份仍须属于显式授权岗位。
            require_role(actor, STAFF)  # 防止未知配置角色扩大读取权限。
        return [case for case in self.store.cases() if actor.role != "customer" or case["customer_id"] == actor.id]  # 后端行级隔离。

    def get_case(self, case_id: str, actor: Account) -> dict:  # 防止直接枚举越权主编号。
        """输入业务编号与身份，返回可见原记录；无权或不存在统一返回 404。""" # 中文契约。
        for case in self.visible_cases(actor):  # 不向客户泄露别人的单号是否存在。
            if case["id"] == case_id:  # 仅匹配授权集合。
                return case  # 原始资料不在此处改写。
        raise DomainError(404, "NOT_FOUND", "未找到可访问的退货单")  # 统一隐藏越权资源。

    def detail(self, case_id: str, actor: Account) -> dict:  # 构造角色适配视图。
        """输入编号与身份，返回状态详情；客户投影移除内部资料和关联订单。""" # 中文契约。
        case = self.get_case(case_id, actor)  # 先确认订单访问权限。
        packages = self.store.packages(case_id)  # 包裹可能关联其他客户，不能直接返回给客户。
        result = assess(case, packages, self.config)  # 统一解释逻辑。
        if actor.role == "customer":  # 客户视图严格按允许字段构造。
            public_case = {key: case[key] for key in ("id", "order_id", "product", "category", "snapshot_at")}  # 不返回内部归属和资料。
            public_result = {key: result[key] for key in ("stage", "explanation", "timeline", "needs_human",  # 仅返回本人进度。
                             "snapshot_stale", "source_unavailable", "snapshot_at", "completion")}  # 不泄露其他订单及内部责任人。
            return dict(case=public_case, assessment=public_result)  # 所有关联读取复用此投影。
        return dict(case=case, packages=packages, assessment=result)  # 已授权员工可核查原始依据。

    def list_cases(self, actor: Account, query: str = "", only_exceptions: bool = False) -> list[dict]:  # 列表筛选。
        """输入身份、搜索词和异常开关，返回授权列表；不执行状态变更。""" # 中文契约。
        items = []  # 收集授权列表投影。
        for case in self.visible_cases(actor):  # 先做权限过滤再做统计或搜索。
            item = self.detail(case["id"], actor)  # 避免列表成为另一条泄露路径。
            text = " ".join(str(value) for value in item["case"].values()).lower()  # 在授权字段中搜索。
            if query.lower() not in text or (only_exceptions and not item["assessment"]["needs_human"]):  # 筛选条件。
                continue  # 不返回不符合条件的记录。
            items.append(item)  # 同一售后单只返回一次。
        return items  # 返回完整小型演示集合。

    def recommend(self, case_id: str, actor: Account) -> dict:  # 保存可复现建议。
        """输入业务编号与员工身份，返回版本化建议；相同资料与风险状态复用记录。""" # 中文契约。
        require_role(actor, STAFF)  # 客户不能产生内部建议或审计写入。
        detail = self.detail(case_id, actor)  # 获得原记录与规则结果。
        result = detail["assessment"]  # 建议不具备执行权限。
        identity = dict(case=detail["case"], packages=detail["packages"], rules=self.config["rules"],  # 原始版本参与幂等判断。
                        reasons=[reason["code"] for reason in result["reasons"]], engine="evidence_rules-v1")  # 过期状态变化可生成新建议。
        fingerprint = hashlib.sha256(encode(identity).encode()).hexdigest()  # 不使用浮动等待时长作为幂等依据。
        with self.store.connection() as conn:  # 查询与插入在单个写事务中进行。
            existing = conn.execute("SELECT payload FROM recommendations WHERE fingerprint=?", (fingerprint,)).fetchone()  # 重复请求复用建议。
            if existing:  # 网络重试不新增待办或审计。
                return json.loads(existing["payload"])  # 返回第一次保存的完整依据。
            item = dict(id=f"REC-{uuid4().hex[:12]}", case_id=case_id, created_at=now_utc().isoformat(),  # 唯一建议编号。
                        created_by=actor.id, result=result, original_records={"case": detail["case"],  # 不覆盖原始快照。
                        "packages": detail["packages"]}, evidence=[fact for fact in self.evidence  # 同时保存事实原文。
                        if fact["id"] in result["evidence_refs"]], human_modifications=[], signatory=None)  # 未经确认不伪造签核。
            conn.execute("INSERT INTO recommendations VALUES (?, ?, ?, ?, ?)",  # 原子保存建议。
                         (item["id"], case_id, fingerprint, encode(item), item["created_at"]))  # 原始依据与输出一起保存。
            self.store.audit(conn, case_id, actor.id, "recommendation.created", item)  # 审计能重建解释上下文。
            return item  # 返回可供人工核对的建议。

    def handoff_view(self, row) -> dict:  # 统一待办展示口径。
        """输入数据库行，返回交接字段和动态超时信息；不修改状态。""" # 中文契约。
        item = dict(row)  # 转换 SQLite 行。
        item["context"] = json.loads(item.pop("payload"))  # 恢复未解决事项和版本上下文。
        age = now_utc() - datetime.fromisoformat(item["created_at"])  # 从发起时间计算真实等待。
        item["overdue"] = item["status"] == "pending" and age > timedelta(hours=self.config["pilot"]["handoff_sla_hours"])  # 演示升级规则。
        item["escalate_to"] = "manager" if item["overdue"] else None  # 明确下一责任人，不发送外部消息。
        item["sender_task_complete"] = item["accepted_at"] is not None  # 只有接手确认后才结束发送方待办。
        item["assignee"] = self.accounts[item["assignee_id"]].model_dump()  # 仅公开身份字段。
        return item  # 保留发起、接手和处理完成三个时间。

    def create_handoff(self, case_id: str, body: HandoffInput, actor: Account) -> dict:  # 创建人工分派。
        """输入单号、接手人与未解决事项，返回交接；无权或责任人不合规返回 403/422。""" # 中文契约。
        require_role(actor, DISPATCHERS)  # 只有演示中授权的分派岗位能够创建交接。
        detail = self.detail(case_id, actor)  # 先检查主记录访问权限。
        assignee = self.accounts.get(body.assignee_id)  # 接手人必须是配置中的具体人员。
        if not assignee or assignee.role not in STAFF or assignee.id == actor.id:  # 禁止客户接手或自己确认自己。
            raise DomainError(422, "INVALID_ASSIGNEE", "请选择其他已授权内部人员作为接手人")  # 不创建无效待办。
        risk_codes = {"RULE_CONFLICT", "RULE_NOT_EFFECTIVE"}  # 专业规则冲突需要风险角色签核。
        if any(reason["code"] in risk_codes for reason in detail["assessment"]["reasons"]) and assignee.role != "risk":  # 普通工单员不得替代专业签核。
            raise DomainError(422, "RISK_REVIEW_REQUIRED", "规则冲突必须分派给交易风险专员")  # 不能选择更宽松的审批路径。
        rec = self.recommend(case_id, actor)  # 先保存对应资料版本与事实引用。
        with self.store.connection() as conn:  # 并发请求也在同一锁下去重。
            existing = conn.execute("SELECT * FROM handoffs WHERE case_id=? AND status IN ('pending','accepted')", (case_id,)).fetchone()  # 同一单只有一个未结交接。
            if existing:  # 刷新或重试不能重复制造待办。
                if existing["assignee_id"] != assignee.id or json.loads(existing["payload"])["unresolved_items"] != body.unresolved_items:  # 不静默丢弃新责任人或新事项。
                    raise DomainError(409, "OPEN_HANDOFF", "该单已有未完成交接，请先由接手人处理")  # 保留原责任归属。
                return self.handoff_view(existing)  # 相同接手人返回原待办。
            context = dict(source_version=detail["case"]["source_version"], rule_versions=detail["case"]["rule_versions"],  # 交接带版本。
                           processing_state=detail["assessment"]["stage"], unresolved_items=body.unresolved_items,  # 交接带未解决事项。
                           trigger_reasons=detail["assessment"]["reasons"], evidence_refs=detail["assessment"]["evidence_refs"],  # 明确触发原因。
                           human_modifications=[], signatory=None)  # 后续人工改动追加保留。
            handoff_id, created = f"HOF-{uuid4().hex[:12]}", now_utc().isoformat()  # 发起时间与编号。
            conn.execute("INSERT INTO handoffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",  # 初始状态只能待确认。
                         (handoff_id, case_id, rec["id"], actor.id, assignee.id, "pending", encode(context), created, None, None))  # 不伪造接手时间。
            self.store.audit(conn, case_id, actor.id, "handoff.created", dict(id=handoff_id, assignee_id=assignee.id, **context))  # 审计分派依据。
            return self.handoff_view(conn.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone())  # 返回持久化结果。

    def list_handoffs(self, actor: Account) -> list[dict]:  # 查询内部协同队列。
        """输入身份，返回内部待办；客户无权读取他人的协同信息。""" # 中文契约。
        require_role(actor, STAFF)  # 客户仅能读取本人订单公共进度。
        with self.store.connection() as conn:  # 统一读取持久化状态。
            return [self.handoff_view(row) for row in conn.execute("SELECT * FROM handoffs ORDER BY created_at DESC").fetchall()]  # 明确责任人与超时。

    def transition(self, handoff_id: str, actor: Account, note: str | None = None) -> dict:  # 接手或处理完成。
        """输入待办、身份和可选备注；仅指定接手人可确认，非法状态返回 409。""" # 中文契约。
        require_role(actor, STAFF)  # 先检查岗位。
        with self.store.connection() as conn:  # 状态检查和变更必须原子执行。
            row = conn.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone()  # 读取锁定状态。
            if not row:  # 处理不存在的待办。
                raise DomainError(404, "NOT_FOUND", "未找到交接记录")  # 统一错误结构。
            if row["assignee_id"] != actor.id:  # 管理员也不能借用实际接手人的签名。
                raise DomainError(403, "ASSIGNEE_ONLY", "只有指定接手人能确认或完成该交接")  # 严格人工签核边界。
            expected, target = ("accepted", "resolved") if note is not None else ("pending", "accepted")  # 固定合法状态机。
            if row["status"] == target:  # 同一动作重试不重复写入。
                if note is not None and json.loads(row["payload"])["human_modifications"][-1]["note"] != note:  # 不静默丢弃新的人工说明。
                    raise DomainError(409, "ALREADY_RESOLVED", "该交接已有处理记录，不能覆盖原人工备注")  # 后续事项应另建交接。
                return self.handoff_view(row)  # 保留原确认时间与人工记录。
            if row["status"] != expected:  # 未接手不能直接完成。
                raise DomainError(409, "INVALID_TRANSITION", "请按待确认 → 已接手 → 已处理的顺序操作")  # 阻止跳过人工确认。
            context, at = json.loads(row["payload"]), now_utc().isoformat()  # 使用服务端确认时间。
            context["signatory"] = actor.id  # 记录实际签核身份。
            if note is not None:  # 人工处理仅追加协同备注。
                context["human_modifications"].append(dict(actor_id=actor.id, note=note, at=at))  # 不覆盖源资料或退款状态。
            accepted = row["accepted_at"] or at  # 接手确认时间一经写入不改变。
            resolved = at if note is not None else None  # 处理完成时间单独保存。
            conn.execute("UPDATE handoffs SET status=?, payload=?, accepted_at=?, resolved_at=? WHERE id=?",  # 只更新协同表。
                         (target, encode(context), accepted, resolved, handoff_id))  # 原始快照保持只读。
            self.store.audit(conn, row["case_id"], actor.id, f"handoff.{target}",  # 状态与签核同步审计。
                             dict(id=handoff_id, source_version=context["source_version"], signatory=actor.id, note=note, at=at))  # 保留实际改动。
            return self.handoff_view(conn.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone())  # 返回更新结果。

    def audit_trail(self, case_id: str, actor: Account) -> list[dict]:  # 重建单次协同链路。
        """输入单号与身份，返回时间有序审计；仅运营经理和风险专员可读取。""" # 中文契约。
        require_role(actor, {"manager", "risk"})  # 不扩大原始资料和签核日志的可见范围。
        self.get_case(case_id, actor)  # 先验证业务资料存在。
        with self.store.connection() as conn:  # 获取追加流水。
            rows = conn.execute("SELECT * FROM audits WHERE case_id=? ORDER BY id", (case_id,)).fetchall()  # 按事务顺序重建。
            return [dict(id=row["id"], case_id=row["case_id"], actor_id=row["actor_id"], action=row["action"],  # 不含凭证。
                         payload=json.loads(row["payload"]), created_at=row["created_at"]) for row in rows]  # 保留版本与人工改动。

    def dashboard(self, actor: Account) -> dict:  # 单品类演示指标。
        """输入身份，返回授权范围统计与口径；不宣称业务收益或模型准确率。""" # 中文契约。
        items = self.list_cases(actor)  # 权限过滤先于汇总。
        return dict(total=len(items), needs_human=sum(item["assessment"]["needs_human"] for item in items),  # 按唯一售后单计数。
                    waiting_inspection=sum(item["assessment"]["stage"] == "waiting_inspection" for item in items),  # 签收待验收独立统计。
                    refunded=sum(item["assessment"]["stage"] == "refunded" for item in items),  # 财务完成口径。
                    observed_at=now_utc().isoformat(), sample_type="本地合成回放样本，不代表业务验收",  # 明确样本来源。
                    metric_definition="分母为当前身份可见的唯一售后单；包裹多对多不重复计数。",  # 固定分母。
                    targets={"status_accuracy": "99%（访谈目标，尚无真实评估结果）",  # 禁止伪造准确率。
                             "refund_days": "6 → 3 天（访谈口径，待样本验证）",  # 不将目标当实际收益。
                             "inquiry_ratio": "42% → 20%（访谈口径，待样本验证）"})  # 保留待核事项。
