"""业务边界回归：客户隔离、四类兜底、人工签核、幂等与持久化。""" # 测试目的。
import json  # 验证接口不泄露内部关联。
from concurrent.futures import ThreadPoolExecutor  # 验证并发分派去重。
from datetime import timedelta  # 演练交接超时。
from urllib.parse import urljoin  # 按浏览器规则解析页面资源路径。

import pytest  # 测试夹具和参数化。
from fastapi.testclient import TestClient  # 使用真实 ASGI 路由回归。

from app.main import create_app  # 每个测试使用隔离数据库。
from app.seed import now_utc  # 固定带时区的时间。


def headers(actor: str = "support") -> dict:  # 测试公开合成凭证。
    """输入演示身份，返回认证头；不涉及真实账号。""" # 中文契约。
    return {"Authorization": f"Bearer demo-{actor}"}  # 与演示 YAML 配置保持一致。


@pytest.fixture  # 为每个测试隔离持久化文件。
def client(tmp_path):  # 创建完整生命周期客户端。
    """输入临时目录，产生应用客户端；测试结束关闭生命周期。""" # 中文契约。
    with TestClient(create_app(tmp_path / "test.sqlite3")) as test_client:  # 真实启动并初始化种子。
        yield test_client  # 不污染本地演示数据。


def get(client, path: str, actor: str = "support") -> dict:  # 简化成功响应读取。
    """输入客户端、路径和身份，返回 data；接口非 200 时断言失败。""" # 中文契约。
    response = client.get(path, headers=headers(actor))  # 使用实际认证路径。
    assert response.status_code == 200, response.text  # 保留失败诊断。
    assert response.json()["ok"] is True  # 验证统一成功格式。
    return response.json()["data"]  # 返回业务对象。


def dispatch(client, case_id: str = "RET-1002", assignee: str = "inspector", actor: str = "support"):  # 构造有效分派。
    """输入单号、责任人和发起人，返回响应；便于验证业务状态。""" # 中文契约。
    return client.post(f"/api/returns/{case_id}/handoffs", headers=headers(actor),  # 使用实际分派接口。
                       json={"assignee_id": assignee, "unresolved_items": "核对包裹与订单件数，不修改原记录"})  # 明确待办。


def test_health_ui_and_openapi(client):  # 验证可运行入口。
    """输入测试客户端，验证健康、静态资源和 OpenAPI；失败直接断言。""" # 中文契约。
    assert client.get("/api/health").json()["data"]["mode"] == "synthetic_demo"  # 运行模式明确。
    page = client.get("/")  # 跟随页面入口到实际静态目录。
    assert "归序" in page.text  # 有可演示工作台。
    assert client.get(urljoin(str(page.url), "./app.js")).status_code == 200  # 浏览器按页面地址解析后能加载脚本。
    css = client.get(urljoin(str(page.url), "./style.css"))  # 复现根目录直接打开时的资源解析。
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")  # 样式路径与响应类型均正确。
    assert client.get("/docs").status_code == 200  # 标准 FastAPI 交互文档。
    paths = client.get("/openapi.json").json()["paths"]  # 校验 API 路由集合。
    assert not any("refund" in path or "penalty" in path for path in paths)  # 根本没有资产变更接口。


@pytest.mark.parametrize("path,method,status,code", [  # 不同错误也必须统一格式。
    ("/api/me", "get", 401, "UNAUTHENTICATED"),  # 缺失认证。
    ("/api/returns/RET-1001/refund", "post", 404, "HTTP_404"),  # 不提供退款接口。
    ("/api/health", "post", 405, "HTTP_405"),  # HTTP 方法错误。
])  # 参数定义结束。
def test_uniform_errors(client, path, method, status, code):  # 统一失败契约。
    """输入路径与预期错误，验证状态码和响应结构；不执行真实业务操作。""" # 中文契约。
    response = getattr(client, method)(path)  # 故意使用无认证或不存在接口。
    assert response.status_code == status  # 保持正确 HTTP 语义。
    assert response.json() == {"ok": False, "data": None, "error": {"code": code, "msg": response.json()["error"]["msg"]}}  # 固定三段结构。


def test_invalid_token_and_validation(client):  # 验证无效凭证和参数。
    """输入客户端，验证认证与参数校验；不得回显凭证或原始请求体。""" # 中文契约。
    response = client.get("/api/me", headers={"Authorization": "Bearer unknown-private-value"})  # 无效身份。
    assert response.status_code == 401 and "unknown-private-value" not in response.text  # 不回显凭证。
    response = client.get("/api/returns?only_exceptions=wrong", headers=headers())  # 非布尔筛选值。
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"  # 统一校验错误。
    response = client.post("/api/returns/RET-1002/handoffs", headers=headers(),  # 客户端不能夹带角色或退款动作。
                           json={"assignee_id": "risk", "unresolved_items": "核对资料", "role": "manager", "refund": True})  # 越权字段。
    assert response.status_code == 422  # extra=forbid 阻止隐式操作。


def test_received_is_not_inspected(client):  # 覆盖核心状态解释。
    """输入客户端，核对签收与验收、退款的独立节点；失败断言。""" # 中文契约。
    item = get(client, "/api/returns/RET-1001")  # 正常签收待验收样本。
    result = item["assessment"]  # 只读解释。
    assert result["stage"] == "waiting_inspection"  # 不把签收当完成。
    assert result["completion"]["service_received"] is not None  # 到仓口径已完成。
    assert result["completion"]["warehouse_inspected"] is None  # 验收口径未完成。
    assert result["completion"]["finance_paid"] is None  # 财务口径未完成。
    assert result["timeline"][2]["completed"] is True and result["timeline"][3]["completed"] is False  # 时间线不造节点。
    assert result["eligible_for_automatic_suggestion"] is True  # 正常资料可解释。
    assert "不代表验收通过或退款完成" in result["explanation"]  # 客服得到明确可用说明。


@pytest.mark.parametrize("number,code", [("1002", "MIXED_PACKAGE"), ("1003", "MISSING_EVIDENCE"),  # 混装和缺件。
                                       ("1004", "RULE_CONFLICT"), ("1005", "SYSTEM_UNAVAILABLE"),  # 规则和故障。
                                       ("1007", "STALE_SNAPSHOT"), ("1008", "DATA_QUALITY")])  # 时效和数据质量。
def test_all_fallbacks(client, number, code):  # 验证各异常独立触发。
    """输入样例与异常码，验证待确认字段、责任人和禁用自动推荐。""" # 中文契约。
    result = get(client, f"/api/returns/RET-{number}")["assessment"]  # 回放对应样例。
    assert result["needs_human"] is True and result["eligible_for_automatic_suggestion"] is False  # 必须转人工。
    reason = next(reason for reason in result["reasons"] if reason["code"] == code)  # 查找指定触发。
    assert reason["pending_fields"] and reason["suggested_owner_id"]  # 不只给模糊提醒。
    assert "退款时间" in result["explanation"]  # 不对外承诺结果。
    assert result["source_version"] == "snapshot-v1" and result["evidence_refs"]  # 保留资料与事实版本。


def test_offline_and_stale_keep_original_snapshot(client):  # 故障不中断只读查询。
    """输入客户端，核对故障时保留原快照时间；不得伪装为实时更新。""" # 中文契约。
    first = get(client, "/api/returns/RET-1005")  # WMS 故障样本。
    second = get(client, "/api/returns/RET-1005")  # 重复查询。
    assert first["case"]["snapshot_at"] == second["case"]["snapshot_at"]  # 读取不能更新时间。
    assert first["assessment"]["source_unavailable"] is True  # 显式标记故障。
    assert "暂未更新" in first["assessment"]["reasons"][0]["message"]  # 展示只读兜底说明。
    assert get(client, "/api/returns/RET-1007")["assessment"]["snapshot_stale"] is True  # 过期独立判断。


@pytest.mark.parametrize("actor,allowed,denied", [("customer-a", "1002", "1009"), ("customer-b", "1009", "1002")])  # 共享包裹客户。
def test_customer_row_and_field_isolation(client, actor, allowed, denied):  # 防止包裹关联泄露。
    """输入客户身份和相邻订单，验证列表、详情、统计与内部资料隔离。""" # 中文契约。
    items = get(client, "/api/returns", actor)  # 先过滤客户归属。
    assert all("customer_id" not in item["case"] and "packages" not in item for item in items)  # 最小字段投影。
    item = get(client, f"/api/returns/RET-{allowed}", actor)  # 本人混装订单可看状态。
    text = json.dumps(item)  # 检查整个响应而不是特定字段。
    assert f"RET-{denied}" not in text and f"ORD-{denied}" not in text  # 不泄露共享包裹的其他业务编号。
    assert "documents" not in text and "evidence_refs" not in text and "rule_versions" not in text  # 不暴露内部资料。
    response = client.get(f"/api/returns/RET-{denied}", headers=headers(actor))  # 枚举别人订单。
    assert response.status_code == 404  # 不泄露资源存在性。
    dashboard = get(client, "/api/dashboard", actor)  # 统计也需行级隔离。
    assert dashboard["total"] == len(items)  # 分母仅为本人可见单据。
    for path in ("/api/evidence", "/api/handoffs", f"/api/returns/RET-{allowed}/audit"):  # 其他读取路径。
        assert client.get(path, headers=headers(actor)).status_code == 403  # 客户不得绕道读取内部资料。
    assert client.post(f"/api/returns/RET-{allowed}/recommendations", headers=headers(actor)).status_code == 403  # 客户无内部写权限。


def test_many_to_many_and_unique_metric_denominator(client):  # 验证显式多对多。
    """输入客户端，核对共享包裹、同单多包和指标分母；不重复计成功。""" # 中文契约。
    first = get(client, "/api/returns/RET-1002")  # 两个包裹对应一个售后单。
    assert len(first["packages"]) == 2  # 同单多包。
    assert set(first["packages"][0]["return_ids"]) == {"RET-1002", "RET-1009"}  # 同包多单。
    assert get(client, "/api/dashboard")["total"] == 9  # 按售后单而不是包裹关联计数。
    assert get(client, "/api/dashboard")["refunded"] == 1  # 财务完成单只有一个。
    assert len(get(client, "/api/returns?q=ORD-1002")) == 1  # 搜索准确命中。
    assert len(get(client, "/api/returns?only_exceptions=true")) == 7  # 异常样本包括同包另一单。


def test_evidence_uses_original_fact_ids_and_recommendations_are_idempotent(client):  # 原始依据留痕。
    """输入客户端，验证事实编号、建议复用与审计完整；不输出凭证。""" # 中文契约。
    evidence = get(client, "/api/evidence")  # 原始访谈行。
    assert len(evidence) == 36 and all("待" in row["verification"] for row in evidence)  # 不是已验证制度。
    response = client.post("/api/returns/RET-1002/recommendations", headers=headers())  # 保存首次解释。
    item = response.json()["data"]  # 取得版本化建议。
    again = client.post("/api/returns/RET-1002/recommendations", headers=headers()).json()["data"]  # 网络重试。
    assert item["id"] == again["id"]  # 同版本解释复用编号。
    assert set(item["result"]["evidence_refs"]) <= {row["id"] for row in evidence}  # 无虚构事实编号。
    assert item["original_records"]["case"]["id"] == "RET-1002"  # 可重建原记录。
    audit = get(client, "/api/returns/RET-1002/audit", "risk")  # 授权读取审计。
    assert len(audit) == 1 and "token" not in json.dumps(audit)  # 重试不重复日志，不记录凭证。


def test_handoff_requires_actual_assignee_and_preserves_snapshot(client):  # 完整人工闭环。
    """输入客户端，验证分派、本人接手、本人处理、审计与业务资料不变。""" # 中文契约。
    original = get(client, "/api/returns/RET-1002")["case"]  # 保存源资料。
    created = dispatch(client).json()["data"]  # 工单员分派质检员。
    handoff_id = created["id"]  # 保存待办编号。
    assert created["status"] == "pending" and not created["sender_task_complete"]  # 发消息不等于接手。
    assert created["accepted_at"] is None and created["context"]["trigger_reasons"]  # 不伪造确认。
    assert dispatch(client).json()["data"]["id"] == handoff_id  # 重试复用未结待办。
    assert dispatch(client, assignee="risk").status_code == 409  # 不覆盖原责任人。
    assert client.post(f"/api/handoffs/{handoff_id}/accept", headers=headers("manager")).status_code == 403  # 经理不能代签。
    assert client.post(f"/api/handoffs/{handoff_id}/resolve", headers=headers("inspector"), json={"note": "先完成"}).status_code == 409  # 不能跳过接手。
    accepted = client.post(f"/api/handoffs/{handoff_id}/accept", headers=headers("inspector")).json()["data"]  # 本人确认。
    assert accepted["sender_task_complete"] and accepted["accepted_at"]  # 此刻才结束发送方待办。
    note = "已核对原单，件数差异交售后继续调查，未变更退款"  # 人工备注不等于业务判责。
    resolved = client.post(f"/api/handoffs/{handoff_id}/resolve", headers=headers("inspector"), json={"note": note}).json()["data"]  # 本人处理。
    assert resolved["status"] == "resolved" and resolved["resolved_at"]  # 保存处理完成时间。
    assert resolved["context"]["signatory"] == "inspector" and resolved["context"]["human_modifications"][0]["note"] == note  # 人工改动可审计。
    assert get(client, "/api/returns/RET-1002")["case"] == original  # 原始件数、验收、退款不被覆盖。
    assert get(client, "/api/returns/RET-1002")["assessment"]["needs_human"] is True  # 关闭协同不篡改异常源数据。
    actions = [row["action"] for row in get(client, "/api/returns/RET-1002/audit", "risk")]  # 重建完整链路。
    assert actions == ["recommendation.created", "handoff.created", "handoff.accepted", "handoff.resolved"]  # 留痕顺序完整。


def test_role_boundaries_and_risk_signoff(client):  # 专业签核不能被普通岗位替代。
    """输入客户端，验证分派岗位、接手人及规则冲突风险审批约束。""" # 中文契约。
    assert dispatch(client, actor="engineer").status_code == 403  # 系统工程师无分派审批权。
    assert dispatch(client, assignee="customer-a").status_code == 422  # 客户不能成为内部接手人。
    assert dispatch(client, assignee="support").status_code == 422  # 不允许自己分派自己确认。
    assert dispatch(client, case_id="RET-1004", assignee="inspector").status_code == 422  # 冲突必须交风险。
    item = dispatch(client, case_id="RET-1004", assignee="risk").json()["data"]  # 专业审核有效路径。
    assert len(item["context"]["rule_versions"]) == 2  # 两份规则都保留。
    assert item["context"]["source_version"] and item["context"]["unresolved_items"]  # 必填交接上下文。


def test_concurrent_dispatch_deduplicates(client):  # 数据库级别避免重复待办。
    """输入客户端，同时提交四次分派，验证只产生一个待办及一条创建审计。""" # 中文契约。
    with ThreadPoolExecutor(max_workers=4) as pool:  # 模拟重连后的并发重试。
        responses = list(pool.map(lambda _: dispatch(client), range(4)))  # 共享合成业务编号。
    assert all(response.status_code == 200 for response in responses)  # 幂等请求均成功。
    assert len({response.json()["data"]["id"] for response in responses}) == 1  # 不重复生成工单。
    audit = get(client, "/api/returns/RET-1002/audit", "manager")  # 查看真实持久化次数。
    assert [row["action"] for row in audit].count("handoff.created") == 1  # 只写一次创建事件。


def test_overdue_handoff_has_explicit_escalation_owner(client):  # 超时明确下一责任人。
    """输入客户端，构造超过演示 SLA 的待确认记录，验证升级标记。""" # 中文契约。
    item = dispatch(client).json()["data"]  # 创建尚未接手待办。
    store = client.app.state.service.store  # 使用测试隔离存储。
    with store.connection() as conn:  # 模拟时间推移，而非等待数小时。
        conn.execute("UPDATE handoffs SET created_at=? WHERE id=?", ((now_utc() - timedelta(hours=5)).isoformat(), item["id"]))  # 仅测试夹具改时间。
    row = get(client, "/api/handoffs")[0]  # 重新读取动态升级状态。
    assert row["overdue"] is True and row["escalate_to"] == "manager"  # 不只写已转交。


def test_restart_preserves_snapshot_and_handoff(tmp_path):  # 重启不丢资料。
    """输入临时目录，启动两次应用，验证快照时间、建议和交接持久化。""" # 中文契约。
    database = tmp_path / "persistent.sqlite3"  # 两次应用共享一个本地文件。
    with TestClient(create_app(database)) as first:  # 首次运行。
        snapshot = get(first, "/api/returns/RET-1002")["case"]  # 原始时间与资料。
        handoff_id = dispatch(first).json()["data"]["id"]  # 创建持久化交接。
    with TestClient(create_app(database)) as second:  # 模拟服务重启。
        assert get(second, "/api/returns/RET-1002")["case"] == snapshot  # 不把旧快照更新时间刷新。
        assert get(second, "/api/handoffs")[0]["id"] == handoff_id  # 协同记录保留。
