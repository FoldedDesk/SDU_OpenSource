"""配置、响应与基于服务端身份的演示权限。""" # 模块用途。
from pathlib import Path  # 处理仓库相对路径。
from typing import Any  # 表达统一响应中的结构化数据。

import yaml  # 读取配置文件。
from fastapi import Request  # 获取当前应用的配置。
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # 解析 Bearer 凭证。
from pydantic import BaseModel, ConfigDict, Field  # 校验请求与公开身份。

ROOT = Path(__file__).resolve().parent.parent  # 以仓库根目录定位资源。
bearer = HTTPBearer(auto_error=False)  # 将缺失认证交给统一错误处理。


class DomainError(Exception):  # 定义可安全公开的业务错误。
    """保存状态码和业务错误；由应用统一转换为 JSON。""" # 类型说明。

    def __init__(self, status: int, code: str, message: str):  # 初始化业务错误。
        """入参为状态码、错误码和说明；保存错误；不吞掉异常。""" # 中文契约。
        super().__init__(message)  # 保留标准异常信息。
        self.status, self.code, self.message = status, code, message  # 保存公开错误字段。


class Account(BaseModel):  # 身份中不包含凭证。
    """公开身份；输入服务端配置，非法字段由 Pydantic 拒绝。""" # 类型契约。
    model_config = ConfigDict(extra="ignore")  # 不向下游传播配置中的 token。
    id: str  # 服务端用户编号。
    name: str  # 合成角色姓名。
    role: str  # 服务端固定岗位。
    label: str  # 岗位中文名称。


class HandoffInput(BaseModel):  # 分派请求禁止客户端覆盖业务状态。
    """接收人工交接所需字段；缺失或越界字段返回 422。""" # 类型契约。
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)  # 阻止夹带退款或角色字段。
    assignee_id: str = Field(min_length=1, max_length=60)  # 必须指定具体接手人。
    unresolved_items: str = Field(min_length=2, max_length=1000)  # 明确未解决事项。


class ResolutionInput(BaseModel):  # 人工处理只写协同记录。
    """接收处理备注；无效备注返回 422，不修改外部业务资料。""" # 类型契约。
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)  # 拒绝隐含业务操作。
    note: str = Field(min_length=2, max_length=1000)  # 记录人工核对结果或下一步。


def load_config(path: Path | None = None) -> dict:  # 读取统一配置。
    """输入可选 YAML 路径，返回配置；缺失文件或非法配置直接启动失败。""" # 中文契约。
    config = yaml.safe_load((path or ROOT / "config.yaml").read_text(encoding="utf-8"))  # 不执行 YAML 对象。
    if config["app"]["engine"] != "evidence_rules":  # 原型仅提供明确声明的规则引擎。
        raise ValueError("demo 只支持 evidence_rules 引擎")  # 避免误称已连接真实模型。
    ids = [account["id"] for account in config["accounts"]]  # 检查身份编号唯一。
    tokens = [account["token"] for account in config["accounts"]]  # 检查演示凭证唯一。
    if len(ids) != len(set(ids)) or len(tokens) != len(set(tokens)):  # 防止身份歧义。
        raise ValueError("演示身份编号和凭证必须唯一")  # 明确拒绝错误配置。
    return config  # 返回配置内容。


def envelope(data: Any = None, *, code: str = "", message: str = "") -> dict:  # 统一业务响应。
    """输入业务数据或错误信息，返回 ok/data/error 结构；不执行副作用。""" # 中文契约。
    return {"ok": not bool(code), "data": data, "error": {"code": code, "msg": message}}  # 固定响应契约。


def authenticate(request: Request, credentials: HTTPAuthorizationCredentials | None) -> Account:  # 解析身份。
    """输入请求与凭证，返回配置中的身份；凭证无效返回 401。""" # 中文契约。
    if credentials and credentials.scheme.lower() == "bearer":  # 权限只依赖服务端凭证映射。
        for account in request.app.state.config["accounts"]:  # 从配置查找身份，不信任客户端角色。
            if account["token"] == credentials.credentials:  # 演示凭证对应唯一配置身份。
                return Account.model_validate(account)  # 丢弃 token，避免进入审计或响应。
    raise DomainError(401, "UNAUTHENTICATED", "请使用 config.yaml 中的本地演示凭证")  # 统一拒绝未认证访问。


def require_role(account: Account, roles: set[str]) -> None:  # 显式保护写入边界。
    """输入身份与允许岗位；成功无返回，岗位不符时抛出 403。""" # 中文契约。
    if account.role not in roles:  # 人工分派与审计权限必须由后端卡住。
        raise DomainError(403, "FORBIDDEN", "当前岗位无权执行此操作")  # 不允许客户端切换角色越权。
