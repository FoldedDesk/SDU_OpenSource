"""独立自测脚本；使用临时库，不改动正在演示的工作区。""" # 模块说明。
import sys  # 允许直接从仓库根目录运行脚本。
from pathlib import Path  # 定位应用导入根目录。
from tempfile import TemporaryDirectory  # 为验证隔离数据库。

from fastapi.testclient import TestClient  # 通过真实路由执行最小闭环。

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 兼容 python scripts/verify_demo.py。
from app.main import create_app  # noqa: E402  # 路径设置后加载应用。


def verify() -> None:  # 提供可直接运行的自测入口。
    """无入参，验证正常、异常、权限及人工交接；失败断言并返回非零状态。""" # 中文契约。
    with TemporaryDirectory(prefix="sdu-returns-verify-") as temp:  # 不污染已有快照和审计。
        with TestClient(create_app(Path(temp) / "verify.sqlite3")) as client:  # 启动完整应用生命周期。
            support = {"Authorization": "Bearer demo-support"}  # 公开合成岗位。
            risk = {"Authorization": "Bearer demo-risk"}  # 指定专业接手人。
            customer = {"Authorization": "Bearer demo-customer-b"}  # 校验客户访问边界。
            assert client.get("/api/health").json()["ok"]  # 服务可用。
            normal = client.get("/api/returns/RET-1001", headers=support).json()["data"]  # 主状态样例。
            assert normal["assessment"]["stage"] == "waiting_inspection"  # 签收不是验收。
            assert client.get("/api/returns/RET-1001", headers=customer).status_code == 404  # 客户不能读取他人订单。
            created = client.post("/api/returns/RET-1004/handoffs", headers=support,  # 规则冲突转风险。
                                  json={"assignee_id": "risk", "unresolved_items": "核对两份规则的生效范围"}).json()["data"]  # 保留未解决字段。
            assert not created["sender_task_complete"]  # 尚未确认接手。
            path = f"/api/handoffs/{created['id']}"  # 交接独立编号。
            assert client.post(f"{path}/accept", headers=support).status_code == 403  # 发起人不能代签。
            accepted = client.post(f"{path}/accept", headers=risk).json()["data"]  # 实际人员确认。
            assert accepted["sender_task_complete"] and accepted["accepted_at"]  # 确认后才结束原待办。
            resolved = client.post(f"{path}/resolve", headers=risk, json={"note": "保留两个版本，已记录待确认事项，无退款操作"}).json()["data"]  # 只写人工备注。
            assert resolved["status"] == "resolved"  # 人工协同完成。
            audit = client.get("/api/returns/RET-1004/audit", headers=risk).json()["data"]  # 重建建议与签核。
            assert len(audit) == 4  # 建议、发起、接手、处理完整。
            assert client.post("/api/returns/RET-1004/refund", headers=risk).status_code == 404  # 没有资产执行接口。
            print("PASS：状态解释、规则冲突转人工、客户隔离、本人签核、审计链路和零退款执行")  # 简洁验证结论。


if __name__ == "__main__":  # 支持直接运行。
    verify()  # 失败会以断言异常退出。
