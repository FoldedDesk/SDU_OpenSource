"""单品类合成快照；不是实际客户资料或已经核实的业务基线。""" # 模块说明。
import re  # 从仓库文档提取原始事实编号。
from datetime import datetime, timedelta, timezone  # 为回放样例生成固定入库时间。

from app.core import ROOT  # 定位仓库文档。


def now_utc() -> datetime:  # 统一事件时间。
    """无入参，返回带 UTC 时区的当前时间；不访问外部系统。""" # 中文契约。
    return datetime.now(timezone.utc)  # 避免本机时区造成时长偏差。


def evidence_catalog() -> list[dict]:  # 提取训练材料中的原始访谈。
    """无入参，返回带事实编号和来源的陈述；文档缺失时启动失败。""" # 中文契约。
    path = ROOT / "docs/ecommerce-returns-fde-training.md"  # 原始事实编号以该文档开头为准。
    pattern = r"^- \[ecommerce-returns / (ecommerce-returns-f\d+)\] ([^：]+)：(.+)$"  # 只解析原始访谈行。
    matches = re.findall(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)  # 不读取后文错误转述编号。
    return [dict(id=key, speaker=speaker, statement=statement, source=str(path.relative_to(ROOT)),  # 保留原始证据。
                 verification="访谈陈述，待制度/日志/单据/观察核实") for key, speaker, statement in matches]  # 区分证据等级。


def sample_data(config: dict, now: datetime) -> tuple[list[dict], list[dict]]:  # 生成首次启动样本。
    """输入配置与入库基准时间，返回退货单和包裹；仅首次初始化使用。""" # 中文契约。
    cases = []  # 收集单品类样例。
    scenarios = [  # 每个异常分支均有可点选样本。
        ("1001", "签收待验收", "customer-a", "waiting", "藏青色衬衫"),  # 主业务痛点。
        ("1002", "混装且件数不符", "customer-a", "mixed", "针织开衫"),  # 四类兜底之一。
        ("1003", "开箱依据缺失", "customer-b", "missing", "棉质长裤"),  # 四类兜底之二。
        ("1004", "两份规则版本冲突", "customer-a", "conflict", "羊毛围巾"),  # 四类兜底之三。
        ("1005", "WMS 不可用", "customer-b", "offline", "连帽卫衣"),  # 四类兜底之四。
        ("1006", "退款已到账", "customer-a", "completed", "基础款 T 恤"),  # 正常完整时间线。
        ("1007", "快照超过更新周期", "customer-a", "stale", "牛仔外套"),  # 不作实时承诺。
        ("1008", "原始时间字段待修复", "customer-b", "dirty", "运动短裤"),  # 数据质量隔离。
        ("1009", "混装包裹中的另一订单", "customer-b", "mixed", "条纹衬衫"),  # 演示跨客户多对多关系。
    ]  # 样例定义结束。
    for number, label, customer, scenario, product in scenarios:  # 按合成场景构建只读资料。
        def at(hours: int) -> str:  # 生成相对基准时间。
            """输入距基准的小时数，返回 ISO 时间；无外部依赖。""" # 中文契约。
            return (now - timedelta(hours=hours)).isoformat()  # 入库后时间不随重启刷新。
        completed = scenario == "completed"  # 仅完成样例拥有完整业务节点。
        events = {"applied": at(96), "shipped": at(80), "received": at(48),  # 区分申请、寄回和签收。
                  "inspected": at(30) if completed else None,  # 签收不会自动填入验收时间。
                  "refund_approved": at(20) if completed else None,  # 只是原始系统审批快照。
                  "refund_paid": at(8) if completed else None,  # 到账独立于审批。
                  "notified": at(7) if completed else None}  # 通知也有独立时间。
        if scenario == "dirty":  # 构造非法业务时序。
            events["received"] = at(120)  # 签收早于申请，必须进入修复队列。
        snapshot_at = at(25 if scenario == "stale" else 1)  # 过期样例超过 12 小时。
        versions = [config["rules"]["version"]]  # 默认单一规则版本。
        if scenario == "conflict":  # 保留两个版本，禁止擅自选宽松条款。
            versions.append("demo-2026.11-v2-pending")  # 合成冲突规则，等待风险核对。
        documents = [  # 五类原始资料均保留独立编号和版本。
            {"id": f"{number}-{kind}", "kind": kind, "version": "snapshot-v1",  # 资料版本可重建。
             "recorded_at": snapshot_at, "summary": summary}  # 最后同步时间明确展示。
            for kind, summary in [("application", "OMS 退货申请，申请 1 件"),  # 订单来源。
                                  ("logistics", "物流回执：仓库已签收"),  # 物流来源。
                                  ("unboxing", "WMS 开箱记录，等待人工核对"),  # 现场来源。
                                  ("inspection", "质检通过" if completed else "尚无验收结论"),  # 不捏造验收。
                                  ("refund", "退款已到账" if completed else "未发起退款")]  # 不作到账承诺。
            if not (scenario == "missing" and kind == "unboxing")  # 缺失资料保留缺失状态。
        ]  # 资料集合结束。
        cases.append({"id": f"RET-{number}", "order_id": f"ORD-{number}", "customer_id": customer,  # 主业务编号。
                      "scenario": scenario, "scenario_label": label, "product": product,  # 合成演示标签。
                      "category": config["pilot"]["category"], "source_version": "snapshot-v1",  # 数据适用范围。
                      "snapshot_at": snapshot_at, "systems": {"OMS": True, "WMS": scenario != "offline",  # 系统可用性。
                      "客服台": True}, "requested_quantity": 1, "events": events,  # 不覆盖原始件数与事件。
                      "rule_versions": versions, "documents": documents})  # 只读快照内容。
    packages = [{"id": "PKG-MIX-01", "return_ids": ["RET-1002", "RET-1009"], "returned_quantity": 3},  # 多单同包。
                {"id": "PKG-MIX-02", "return_ids": ["RET-1002"], "returned_quantity": 1}]  # 同单多包。
    packages.extend({"id": f"PKG-{case['id'][4:]}", "return_ids": [case["id"]],  # 普通一对一包裹。
                     "returned_quantity": 1} for case in cases if case["scenario"] != "mixed")  # 不重复构造混装包裹。
    quantities = {case["id"]: case["requested_quantity"] for case in cases}  # 从原申请读取件数。
    for package in packages:  # 保留包裹总件数与申请总件数的独立口径。
        package["requested_quantity_total"] = sum(quantities[key] for key in package["return_ids"])  # 不推断每件的订单归属。
    return cases, packages  # 返回可入库的合成快照。
