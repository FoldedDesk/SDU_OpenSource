"""FastAPI 工厂、统一响应和本地演示页面。""" # 模块说明。
import logging  # 记录服务端故障类型。
from contextlib import asynccontextmanager  # 管理启动时的数据库初始化。
from pathlib import Path  # 支持测试隔离数据库。
from typing import Annotated  # 声明 FastAPI 依赖。

from fastapi import Depends, FastAPI, Query, Request  # 接口框架。
from fastapi.exceptions import RequestValidationError  # 统一处理参数错误。
from fastapi.responses import JSONResponse, RedirectResponse  # 返回页面入口和统一 JSON。
from fastapi.security import HTTPAuthorizationCredentials  # 类型化 Bearer 凭证。
from fastapi.staticfiles import StaticFiles  # 本地 CSS 与 JavaScript。
from starlette.exceptions import HTTPException  # 统一 404 和 405。

from app.core import (  # 导入统一契约和配置。
    ROOT,  # 仓库资源路径。
    Account,  # 不含凭证的身份。
    DomainError,  # 统一业务异常。
    HandoffInput,  # 人工分派字段。
    ResolutionInput,  # 人工处理备注。
    authenticate,  # 服务端身份映射。
    bearer,  # Bearer 凭证解析器。
    envelope,  # 统一响应结构。
    load_config,  # YAML 配置读取。
    require_role,  # 显式岗位权限校验。
)  # 公共契约导入结束。
from app.service import STAFF, Service  # 业务服务与岗位白名单。
from app.store import Store  # 本地事务存储。


def current_actor(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Account:  # 注入身份。
    """输入请求与解析后的凭证，返回服务端身份；无效认证返回 401。""" # 中文契约。
    return authenticate(request, credentials)  # 不信任请求中的用户编号或角色。


Actor = Annotated[Account, Depends(current_actor)]  # 所有业务路由使用相同认证依赖。


def create_app(database_path: Path | None = None, config_path: Path | None = None) -> FastAPI:  # 构造可测试应用。
    """输入可选隔离数据库与配置路径，返回应用；非法配置或初始化失败时终止启动。""" # 中文契约。
    config = load_config(config_path)  # 配置统一来自 YAML。
    database = database_path or ROOT / config["app"]["database"]  # 测试使用临时文件，演示使用持久化库。
    store = Store(database)  # 创建独立连接的存储实例。

    @asynccontextmanager  # 替代已弃用的启动装饰器。
    async def lifespan(application: FastAPI):  # 初始化本地资源。
        """输入应用，初始化幂等样例；失败则不提供部分可用的服务。""" # 中文契约。
        store.initialize(config)  # 重启不覆盖快照或交接。
        application.state.service = Service(store, config)  # 证据和业务服务统一就绪。
        yield  # 无需保留持久化数据库连接。

    application = FastAPI(title=config["app"]["title"], version="0.1.0", lifespan=lifespan,  # OpenAPI 元信息。
                          description="基于仓库 docs 的本地合成回放。规则解释、异常转人工、交接确认和审计；不连接真实 OMS/WMS，不执行退款。")  # 明确实现范围。
    application.state.config = config  # 身份映射由服务端维护。
    application.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")  # 所有前端资源本地提供。

    @application.exception_handler(DomainError)  # 业务错误统一响应。
    async def domain_error(request: Request, exc: DomainError):  # 处理可公开的业务失败。
        """输入请求与业务异常，返回统一 JSON 和原状态码；不暴露凭证。""" # 中文契约。
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None  # 遵循认证响应约定。
        return JSONResponse(envelope(code=exc.code, message=exc.message), status_code=exc.status, headers=headers)  # 保留业务错误码。

    @application.exception_handler(RequestValidationError)  # 请求校验也遵循统一结构。
    async def validation_error(request: Request, exc: RequestValidationError):  # 不回显输入的敏感内容。
        """输入校验异常，返回 422；仅暴露字段位置与错误描述。""" # 中文契约。
        issues = [{"field": ".".join(map(str, issue["loc"])), "message": issue["msg"]} for issue in exc.errors()]  # 去掉原始输入。
        return JSONResponse(envelope(issues, code="VALIDATION_ERROR", message="请求字段不符合接口约定"), status_code=422)  # 统一参数错误。

    @application.exception_handler(HTTPException)  # 包括无退款接口的 404。
    async def http_error(request: Request, exc: HTTPException):  # 统一框架错误。
        """输入 HTTP 异常，返回统一错误 JSON；保留框架状态码与响应头。""" # 中文契约。
        return JSONResponse(envelope(code=f"HTTP_{exc.status_code}", message=str(exc.detail)),  # 路由不存在也不返回另一套格式。
                            status_code=exc.status_code, headers=exc.headers)  # 兼容标准 HTTP 语义。

    @application.exception_handler(Exception)  # 防止内部异常泄露 SQL 或环境信息。
    async def server_error(request: Request, exc: Exception):  # 兜底未处理错误。
        """输入未知异常，记录类型并返回 500；不回显内部细节或请求内容。""" # 中文契约。
        logging.getLogger(__name__).error("请求失败，异常类型：%s", type(exc).__name__)  # 不记录 token、请求体或个人信息。
        return JSONResponse(envelope(code="INTERNAL_ERROR", message="服务暂不可用，请稍后重试"), status_code=500)  # 统一服务错误。

    @application.get("/", include_in_schema=False)  # 本地演示入口。
    def index():  # 进入与 CSS、脚本同目录的静态工作台。
        """无业务输入，重定向到工作台；浏览器按页面目录解析本地资源。""" # 中文契约。
        return RedirectResponse("/static/index.html")  # 根入口与直接打开静态页共用正确的相对资源路径。

    @application.get("/api/health", tags=["系统"])  # 启动自检。
    def health():  # 不暴露数据库路径或身份配置。
        """无入参，返回服务状态；数据库在 lifespan 中已经初始化。""" # 中文契约。
        return envelope(dict(status="ok", mode="synthetic_demo", engine=config["app"]["engine"]))  # 明确合成运行模式。

    @application.get("/api/demo/accounts", tags=["演示身份"])  # 本地公开合成账户。
    def demo_accounts():  # 这些凭证只是公开演示夹具。
        """无入参，返回配置中的公开演示身份；只用于本机合成资料演示。""" # 中文契约。
        return envelope(dict(notice="公开合成演示账户，非生产认证", accounts=config["accounts"]))  # 不涉及真实用户密钥。

    @application.get("/api/me", tags=["演示身份"])  # 验证身份。
    def me(actor: Actor):  # 返回不含 token 的公开字段。
        """输入认证身份，返回公开用户资料；认证失败返回 401。""" # 中文契约。
        return envelope(actor.model_dump())  # 后端固定角色。

    @application.get("/api/dashboard", tags=["状态视图"])  # 小型回放指标。
    def dashboard(request: Request, actor: Actor):  # 统计授权数据。
        """输入身份，返回按唯一售后单统计的演示指标；越权数据不计入分母。""" # 中文契约。
        return envelope(request.app.state.service.dashboard(actor))  # 不伪造收益或准确率。

    @application.get("/api/returns", tags=["状态视图"])  # 状态查询列表。
    def returns(request: Request, actor: Actor, q: Annotated[str, Query(max_length=100)] = "", only_exceptions: bool = False):  # 限制输入长度。
        """输入搜索词、异常开关和身份，返回授权售后单；客户仅看本人。""" # 中文契约。
        return envelope(request.app.state.service.list_cases(actor, q, only_exceptions))  # 统一返回格式。

    @application.get("/api/returns/{case_id}", tags=["状态视图"])  # 单据详情。
    def detail(case_id: str, request: Request, actor: Actor):  # 查询只读原记录。
        """输入单号与身份，返回角色投影；无权或不存在返回 404。""" # 中文契约。
        return envelope(request.app.state.service.detail(case_id, actor))  # 包裹信息对客户进行最小字段投影。

    @application.post("/api/returns/{case_id}/recommendations", tags=["解释与证据"])  # 生成可追踪解释。
    def recommend(case_id: str, request: Request, actor: Actor):  # 不执行资产操作。
        """输入单号与员工身份，保存或复用带事实引用的建议；客户返回 403。""" # 中文契约。
        return envelope(request.app.state.service.recommend(case_id, actor))  # 旧快照和异常进入人工路径。

    @application.get("/api/evidence", tags=["解释与证据"])  # 核查原始事实编号。
    def evidence(request: Request, actor: Actor):  # 只允许授权内部岗位读取。
        """输入员工身份，返回原始访谈台账；客户返回 403。""" # 中文契约。
        require_role(actor, STAFF)  # 不将内部访谈台账暴露给客户。
        return envelope(request.app.state.service.evidence)  # 每项标明陈述与待核实等级。

    @application.post("/api/returns/{case_id}/handoffs", tags=["人工交接"])  # 发起人工分派。
    def create_handoff(case_id: str, body: HandoffInput, request: Request, actor: Actor):  # 仅接受明确待办字段。
        """输入单号、接手人与未解决事项，返回待确认交接；非法分派返回 403/422。""" # 中文契约。
        return envelope(request.app.state.service.create_handoff(case_id, body, actor))  # 不自行替代实际接手确认。

    @application.get("/api/handoffs", tags=["人工交接"])  # 查看责任人队列。
    def handoffs(request: Request, actor: Actor):  # 提供确认和处理时间。
        """输入员工身份，返回交接状态与演示升级标记；客户返回 403。""" # 中文契约。
        return envelope(request.app.state.service.list_handoffs(actor))  # 每项有明确接手人。

    @application.post("/api/handoffs/{handoff_id}/accept", tags=["人工交接"])  # 确认接手。
    def accept(handoff_id: str, request: Request, actor: Actor):  # 不接受客户端签名或确认时间。
        """输入待办编号和实际接手人，确认接手；其他人返回 403。""" # 中文契约。
        return envelope(request.app.state.service.transition(handoff_id, actor))  # 服务端写入签核人与时间。

    @application.post("/api/handoffs/{handoff_id}/resolve", tags=["人工交接"])  # 追加人工处理记录。
    def resolve(handoff_id: str, body: ResolutionInput, request: Request, actor: Actor):  # 不更新业务验收或退款。
        """输入待办、备注与接手人，完成协同记录；未接手返回 409。""" # 中文契约。
        return envelope(request.app.state.service.transition(handoff_id, actor, body.note))  # 原资料保持不变。

    @application.get("/api/returns/{case_id}/audit", tags=["审计"])  # 重建事实到人工动作链。
    def audit(case_id: str, request: Request, actor: Actor):  # 限定日志读取角色。
        """输入单号与身份，返回版本化审计；非运营或风险岗位返回 403。""" # 中文契约。
        return envelope(request.app.state.service.audit_trail(case_id, actor))  # 日志不记录认证凭证。

    return application  # 测试可创建多个隔离应用。


app = create_app()  # 为 Uvicorn 提供标准 ASGI 入口。
