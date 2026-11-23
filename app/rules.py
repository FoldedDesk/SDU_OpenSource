"""可复现状态解释；只输出事实、依据和人工待办，不执行退款。""" # 模块说明。
from datetime import datetime, timedelta  # 计算快照年龄和节点等待。

from app.seed import now_utc  # 使用有时区的时间。

STAGES = [("applied", "退货申请"), ("shipped", "寄回"), ("received", "仓库签收"),  # 明确前三个节点。
          ("inspected", "商品验收"), ("refund_approved", "退款审批"), ("notified", "客户通知")]  # 不把签收当验收。


def assess(case: dict, packages: list[dict], config: dict, now: datetime | None = None) -> dict:  # 解释快照。
    """输入原始资料、包裹和配置，返回解释与兜底原因；不修改输入或外部状态。""" # 中文契约。
    now = now or now_utc()  # 支持固定时钟回归。
    events, reasons = case["events"], []  # 所有异常分别保留。
    snapshot_at = datetime.fromisoformat(case["snapshot_at"])  # 原始快照必须带时区。
    stale = now - snapshot_at > timedelta(hours=config["pilot"]["snapshot_max_age_hours"])  # 超一个周期待刷新。
    offline = not all(case["systems"].values())  # 任一关键系统不可用均停止自动推荐。
    refs = {"ecommerce-returns-f10", "ecommerce-returns-f31", "ecommerce-returns-f52"}  # 状态解释基本依据。

    def flag(code: str, message: str, fields: list[str], owner: str, facts: list[str]) -> None:  # 收集兜底。
        """输入异常和责任人，追加结构化原因及依据；不产生业务结论。""" # 中文契约。
        reasons.append(dict(code=code, message=message, pending_fields=fields, suggested_owner_id=owner))  # 必须明确接手人。
        refs.update(f"ecommerce-returns-{fact}" for fact in facts)  # 使用原始文档事实编号。

    if any(len(pkg["return_ids"]) > 1 for pkg in packages):  # 共享包裹不能自动推断每单归属。
        flag("MIXED_PACKAGE", "多订单混装，逐单件数与申请的对应关系待核对",  # 混装不直接推导数量错误。
             ["包裹与售后单对应关系", "实际退回件数", "件数差异原因"], "support", ["f11", "f15", "f33", "f44"])  # 售后核对。
    if any(pkg["returned_quantity"] != pkg["requested_quantity_total"] for pkg in packages):  # 必须有原始数量依据才判断不一致。
        flag("QUANTITY_MISMATCH", "包裹退回总件数与关联申请总件数不一致，不能自动归责",  # 仅指出可见数值差异。
             ["包裹退回件数", "关联申请总件数", "逐件订单归属"], "support", ["f11", "f15", "f44"])  # 保留人工复核。
    required = {"application", "logistics", "unboxing", "inspection", "refund"}  # 访谈明确五类资料。
    missing = sorted(required - {doc["kind"] for doc in case["documents"]})  # 保留资料缺口。
    if missing:  # 资料不全时不输出确定结论。
        flag("MISSING_EVIDENCE", "原始依据缺失，需要补件后人工核对", missing, "support", ["f21", "f44"])  # 进入补件待办。
    if case["rule_versions"] != [config["rules"]["version"]]:  # 不擅自融合冲突规则。
        flag("RULE_CONFLICT", "存在冲突或未确认规则版本，两个版本一并交风险专员",  # 保留两个版本。
             ["适用规则版本", "规则生效范围"], "risk", ["f24", "f44"])  # 风险角色核定。
    if str(config["rules"]["effective_from"]) > snapshot_at.date().isoformat():  # 未生效规则不能套用旧资料。
        flag("RULE_NOT_EFFECTIVE", "配置规则在该快照日期尚未生效", ["规则生效日期"], "risk", ["f24", "f44"])  # 转人工。
    if offline:  # 不可用时继续显示上一份只读快照。
        flag("SYSTEM_UNAVAILABLE", "关键系统不可用，暂未更新；沿用带时间戳的只读快照",  # 明确故障原因。
             [name for name, available in case["systems"].items() if not available], "engineer", ["f35", "f44"])  # 指定系统接手人。
    if stale:  # 旧资料不能作实时承诺。
        flag("STALE_SNAPSHOT", "快照超过更新周期，待刷新；不能承诺实时进度",  # 明确数据时效。
             ["最后同步时间"], "engineer", ["f34", "f35"])  # 只读查询仍可继续。
    times = [datetime.fromisoformat(events[key]) for key, _ in STAGES if events.get(key)]  # 获取业务节点顺序。
    invalid = times != sorted(times) or snapshot_at > now + timedelta(minutes=1) or any(at > snapshot_at for at in times)  # 异常时序隔离。
    if any(events.get(STAGES[index][0]) and not events.get(STAGES[index - 1][0]) for index in range(1, len(STAGES))):  # 节点缺少前置资料。
        invalid = True  # 不把缺失节点当成已完整验收。
    if any(not doc.get("id") or not doc.get("version") or not doc.get("recorded_at") for doc in case["documents"]):  # 原始资料必须有编号时间与版本。
        invalid = True  # 不合格资料排除自动推荐。
    if events.get("refund_paid") and not (events.get("inspected") and events.get("refund_approved")):  # 财务状态也需前置依据。
        invalid = True  # 防止把未验收退款资料当正常样本。
    if invalid:  # 有歧义的资料不进入自动推荐。
        flag("DATA_QUALITY", "原记录时间顺序或前置依据异常，进入人工修复队列",  # 不覆盖源记录。
             ["主编号", "事件时间", "版本字段"], "engineer", ["f33", "f45"])  # 记录修复责任人。
    if invalid:  # 脏数据不能继续推导客户状态。
        stage, message = "data_review", "原始资料待核对，当前处理状态需由售后人工确认。"  # 保守解释。
    elif events.get("refund_paid"):  # 仅原始到账回执可说明财务完成。
        stage, message = "refunded", "快照显示退款已到账；具体入账请以原支付渠道为准。"  # 不执行任何资产操作。
    elif events.get("refund_approved"):  # 审批与到账保持区分。
        stage, message = "refund_approved", "退款审批已完成，快照尚未显示到账。"  # 不承诺到账日期。
    elif events.get("inspected"):  # 仅质检节点存在时说明验收完成。
        stage, message = "inspected", "商品已验收，后续退款仍须授权人员审核。"  # 人工签核不可省略。
    elif events.get("received"):  # 最重要的状态解释分支。
        stage, message = "waiting_inspection", "仓库已签收，商品尚未验收；签收不代表验收通过或退款完成。"  # 明确业务口径。
    elif events.get("shipped"):  # 物流阶段独立说明。
        stage, message = "in_transit", "退货已寄回，快照尚未显示仓库签收。"  # 不推测签收时间。
    else:  # 尚无物流节点。
        stage, message = "applied", "退货申请已记录，等待寄回资料。"  # 仅说明已知事实。
    if reasons:  # 先呈现事实，再提醒人工处理。
        message += " 该单需要人工核对，暂不承诺退款时间或处理结果。"  # 禁止异常情况下作对外承诺。
    timeline = [dict(key=key, label=label, at=events.get(key), completed=bool(events.get(key)))  # 独立展示六节点。
                for key, label in STAGES]  # 签收不会补齐验收节点。
    wait = None  # 未签收或脏数据时不能算等待时长。
    if events.get("received") and not invalid:  # 区分已完成时长与仍在排队的积压时长。
        end = datetime.fromisoformat(events["inspected"]) if events.get("inspected") else now  # 未完成样本单列。
        wait = round((end - datetime.fromisoformat(events["received"])).total_seconds() / 3600, 2)  # 小时口径。
    return dict(stage=stage, explanation=message, timeline=timeline, reasons=reasons,  # 返回可检查的解释。
                needs_human=bool(reasons), eligible_for_automatic_suggestion=not bool(reasons),  # 四类兜底优先阻断。
                snapshot_stale=stale, source_unavailable=offline, snapshot_at=case["snapshot_at"],  # 时效透明。
                rule_versions=case["rule_versions"], source_version=case["source_version"],  # 保留所有规则版本。
                evidence_refs=sorted(refs), engine="evidence_rules", wait_hours=wait,  # 明确非真实模型评估。
                completion=dict(service_received=events.get("received"), warehouse_inspected=events.get("inspected"),  # 三种完成口径。
                                finance_paid=events.get("refund_paid")),  # 到账独立统计。
                allowed_actions=["解释状态", "提示缺口", "人工分派"], forbidden_actions=["自动退款", "认定欺诈", "处罚账号"])  # 固定动作边界。
