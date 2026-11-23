# 归序 · 退货验收与售后协同 Demo

基于 `docs/` 访谈与调研材料实现的 **FastAPI + SQLite** 本地原型。附中文工作台、Swagger 接口文档、9 个合成场景及独立验证脚本。无需模型密钥或外部数据库。

## 启动

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。在仓库根目录运行：

```bash
uv sync --locked
uv run python -m app
```

macOS 也可以双击仓库根目录的 `start.command` 启动。保持该终端窗口运行，通过下面的 HTTP 地址打开工作台。直接双击 `app/static/index.html` 只会显示带样式的启动提示，不会调用业务接口。

- 工作台：[http://127.0.0.1:8000](http://127.0.0.1:8000)
- 接口文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- OpenAPI：[http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

监听地址、端口、数据库、演示账号、规则版本和演示时限统一配置在 `config.yaml`。首次启动创建 `data/demo.sqlite3`，重启保留快照原时间、建议、交接和审计。

## 演示流程

1. 默认以唐映秋（售后工单员）进入。打开 `RET-1001`，查看“仓库已签收、商品尚未验收”，六个节点分别记录时间。
2. 打开 `RET-1004`，检查冲突的两份规则、待确认字段及事实引用，选择傅景并发起交接。此时发送方待办仍未结束。
3. 将顶部演示身份切换为傅景，进入“人工交接”，确认接手后再填写处理备注。接手与处理完成有独立时间和签核人。
4. 用傅景或顾明岚打开该单的“查看审计链路”，重建原记录、资料版本、解释依据与人工改动。
5. 切换客户甲或客户乙，验证仅显示本人订单。共享包裹关联到的其他客户单号、内部资料和台账不会返回。

| 售后单 | 场景 |
| --- | --- |
| RET-1001 | 已签收，尚未验收 |
| RET-1002 / RET-1009 | 跨订单混装与件数不符；同包多单、同单多包 |
| RET-1003 | 开箱依据缺失 |
| RET-1004 | 规则版本冲突，必须交交易风险专员 |
| RET-1005 | WMS 不可用，沿用只读快照并标记暂未更新 |
| RET-1006 | 原系统快照显示退款已到账 |
| RET-1007 | 快照超过更新周期，停止自动推荐 |
| RET-1008 | 原始时间字段异常，进入人工修复队列 |

关闭协同待办仅表示人工处理记录已完成；源记录仍有异常时，异常提示继续保留。原型不改写签收、验收或退款事实。

## 自测

```bash
uv run python scripts/verify_demo.py
uv run pytest -q
uv run ruff check .
```

独立验证脚本无需先启动服务，使用临时 SQLite 库，完整回放“状态解释 → 冲突转人工 → 本人确认接手 → 处理备注 → 审计”，同时验证客户隔离和不存在退款接口。

本次验证：22 项测试通过，独立验证脚本通过；Chrome 桌面与手机布局、页面发起交接/本人接手/填写处理记录、客户视图隔离均通过，未出现页面脚本异常。测试覆盖四类兜底、快照故障与过期、客户行级及字段级隔离、岗位限制、拒绝代签、状态跳转、并发去重和重启持久化。

## 接口

业务 JSON 统一为 `{"ok": true, "data": {}, "error": {"code": "", "msg": ""}}`；失败时 `ok=false` 并保留相应 HTTP 状态码。HTML、静态资源及标准 OpenAPI 文档使用其原生格式。

认证示例：`Authorization: Bearer demo-support`。演示凭证公开列在 `config.yaml`，Swagger 可通过 Authorize 输入凭证。接口演示：

```bash
curl -s http://127.0.0.1:8000/api/returns/RET-1001 \
  -H 'Authorization: Bearer demo-support'
```

| 接口 | 用途 / 权限 |
| --- | --- |
| `GET /api/health` | 健康检查，公开 |
| `GET /api/demo/accounts` | 公开合成身份，供本机演示切换 |
| `GET /api/me` | 当前身份 |
| `GET /api/dashboard` | 当前身份可见的唯一售后单统计 |
| `GET /api/returns?q=&only_exceptions=false` | 搜索与异常筛选；客户仅看本人 |
| `GET /api/returns/{id}` | 状态、时间线；内部岗位可看原资料与包裹关联 |
| `POST /api/returns/{id}/recommendations` | 保存解释、原始版本及事实引用；内部岗位 |
| `GET /api/evidence` | 原始访谈证据台账；内部岗位 |
| `POST /api/returns/{id}/handoffs` | `assignee_id` + `unresolved_items`；工单员、运营经理、服务主管 |
| `GET /api/handoffs` | 内部交接队列、确认时间与超时责任人 |
| `POST /api/handoffs/{id}/accept` | 只有指定接手人可确认 |
| `POST /api/handoffs/{id}/resolve` | `note`；指定接手人确认后才能完成 |
| `GET /api/returns/{id}/audit` | 只有运营经理和风险专员可读取审计 |

## 文档依据与演示约定

- [训练记录](docs/ecommerce-returns-fde-training.md)：以开头的原始 `ecommerce-returns-f00…f55` 事实编号为准，动态加载其中 36 条访谈，避免沿用报告中被评审指出有误的 f08/f09 等转述编号。
- [业务挖掘报告](docs/退货验收与售后协同-业务挖掘报告.md)：分别记录到仓、验收、到账；按唯一售后单统计。6→3 天、42%→20%、99% 均为待验证的访谈目标，不显示为 demo 实际收益或准确率。
- [现场调研报告](docs/退货验收与售后协同-现场调研报告.md)：四类异常、只读快照、客户订单隔离、接手确认及审计约束。
- [开发约定](docs/prompt.md)：采用统一配置和响应、中文函数说明与逐行代码注释。该文件中的旧开发待确认状态保留；本次按用户明确指定的 FastAPI 实现本地 demo。

本次新增文件：`app/`（接口、规则、SQLite、合成数据及工作台）、`config.yaml`、`pyproject.toml`、`uv.lock`、`tests/test_api.py`、`scripts/verify_demo.py`、本说明与 `.gitignore`。

当前约定：单品类“服饰”、每 12 小时判定快照过期、4 小时未确认接手标记升级运营经理。4 小时与具体岗位权限是演示假设，需业务确认。90 天是访谈中的评价记录暂定留存值，本 demo 不自动删除审计。

这是**规则解释引擎**，没有连接真实大模型、OMS/WMS、退款或消息系统。公开演示账号用于验证接口授权逻辑，不能用作生产登录。最常见的运行问题是端口占用（修改 `config.yaml`）和运行超过 12 小时后样例变为待刷新（符合原始快照时效规则）；首次安装需要能访问 Python 包源。
