"use strict"; // 禁止隐式全局变量。
const state = { accounts: [], actor: null, tab: "returns", selected: null, items: [], generation: 0 }; // 本地演示视图状态。
const stages = { waiting_inspection: "待验收", inspected: "已验收", refund_approved: "待到账", refunded: "已到账", data_review: "资料待修复", in_transit: "寄回中", applied: "已申请" }; // 统一显示状态。
const kinds = { application: "退货申请 · OMS", logistics: "物流回执", unboxing: "开箱记录 · WMS", inspection: "质检结果 · WMS", refund: "退款状态 · OMS" }; // 原始资料名称。
let toastTimer; // 管理反馈自动关闭。
let searchTimer; // 搜索防抖。
/** 输入 CSS 选择器，返回元素；缺失元素由浏览器抛出后续错误。 */ // 中文函数契约。
function $(selector) { return document.querySelector(selector); } // 页面元素查询。
/** 输入任意文本，返回 HTML 转义内容；防止资料或备注作为标签执行。 */ // 中文函数契约。
function esc(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char])); } // 所有动态 HTML 均转义。
/** 输入 ISO 时间，返回上海时区短日期；空值返回未完成。 */ // 中文函数契约。
function date(value) { return value ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }) : "未完成"; } // 节点独立时间。
/** 输入提示与错误标志，显示反馈；无业务副作用。 */ // 中文函数契约。
function toast(message, error = false) { clearTimeout(toastTimer); $("#toast").textContent = message; $("#toast").className = error ? "error" : ""; $("#toast").hidden = false; toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 5000); } // 不把错误插入 HTML。
/** 输入 API 路径与可选请求体，返回 data；HTTP 或业务失败抛出说明。 */ // 中文函数契约。
async function api(path, body) { // 统一发送服务端校验的演示凭证。
  const response = await fetch(path, { method: body === undefined ? "GET" : "POST", headers: { "Content-Type": "application/json", ...(state.actor ? { Authorization: `Bearer ${state.actor.token}` } : {}) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) }); // 凭证只用于本机合成演示。
  const payload = await response.json(); // 所有业务 API 使用统一响应。
  if (!response.ok || !payload.ok) throw new Error(payload.error?.msg || "请求失败"); // 将业务失败交给统一反馈。
  return payload.data; // 页面不依赖 HTTP 层的其他字段。
} // API 请求结束。
/** 输入一次异步操作，统一提示失败；结束时恢复按钮。 */ // 中文函数契约。
async function run(task, button) { // 包装用户触发动作。
  if (button) button.disabled = true; // 避免同一按钮重复提交。
  try { await task(); } catch (error) { toast(error.message, true); } finally { if (button) button.disabled = false; } // 错误可见并可重试。
} // 动作包装结束。
/** 输入单据详情，返回经过转义的列表按钮；不修改资料。 */ // 中文函数契约。
function caseRow(item) { // 为每条授权售后单生成选择器。
  const c = item.case, a = item.assessment; // 取角色投影后的资料。
  return `<button class="case ${c.id === state.selected ? "selected" : ""}" data-case="${esc(c.id)}"><div class="case-line"><span class="case-id">${esc(c.id)}</span><span class="badge ${a.needs_human ? "warn" : a.stage === "refunded" ? "good" : ""}">${a.needs_human ? "需人工核对" : esc(stages[a.stage])}</span></div><div class="case-product">${esc(c.product)}</div><div class="case-meta">${esc(c.order_id)} · ${esc(c.scenario_label || stages[a.stage])}</div></button>`; // 键盘可激活，无原始 HTML 注入。
} // 列表项结束。
/** 输入授权详情，更新主视图；客户界面不显示原资料或分派控件。 */ // 中文函数契约。
function renderDetail(item) { // 展示六节点、版本与人工待办。
  const c = item.case, a = item.assessment, staff = state.actor.role !== "customer"; // 权限展示仅作辅助，后端仍做校验。
  const canDispatch = ["support", "manager", "supervisor"].includes(state.actor.role); // 显示已授权分派入口。
  const owners = state.accounts.filter(person => person.role !== "customer" && person.id !== state.actor.id); // 禁止自己接手自己的交接。
  const recommended = a.reasons?.find(reason => reason.suggested_owner_id === "risk")?.suggested_owner_id || a.reasons?.[0]?.suggested_owner_id; // 专业冲突优先交风险。
  const facts = (a.reasons || []).map(reason => `<div class="reason">${esc(reason.message)}<small>待确认：${esc(reason.pending_fields.join("、"))} · 建议接手：${esc(state.accounts.find(person => person.id === reason.suggested_owner_id)?.name)}</small></div>`).join(""); // 结构化兜底原因。
  const sources = staff ? Object.entries(kinds).map(([kind, label]) => { const doc = c.documents.find(source => source.kind === kind); return `<div class="source ${doc ? "" : "missing"}">${esc(label)}<span>${doc ? `${esc(doc.summary)}<br>${esc(doc.version)} · ${date(doc.recorded_at)}` : "资料缺失 · 等待补件"}</span></div>`; }).join("") : ""; // 缺件不补造记录。
  const pkg = staff ? item.packages.map(packageItem => `${packageItem.id} ↔ ${packageItem.return_ids.join(" / ")}（退回 ${packageItem.returned_quantity} 件）`).join("；") : ""; // 共享包裹仅内部可见。
  $("#detail").innerHTML = `<div class="detail-heading"><div><h2>${esc(c.product)}</h2><div class="detail-meta">${esc(c.id)} / ${esc(c.order_id)} / ${esc(c.category)}</div></div><span class="badge ${a.needs_human ? "warn" : "good"}">${esc(stages[a.stage])}</span></div><div class="explanation"><strong>${a.source_unavailable || a.snapshot_stale ? "暂未更新 · 上一份只读快照" : "当前状态解释"}</strong>${esc(a.explanation)}</div><div class="timeline">${a.timeline.map(step => `<div class="step ${step.completed ? "done" : ""}">${esc(step.label)}<small>${date(step.at)}</small></div>`).join("")}</div><div class="source-meta">最后同步 ${date(a.snapshot_at)} · ${staff ? `资料 ${esc(a.source_version)} · 规则 ${esc(a.rule_versions.join(" / "))}` : "本人订单只读视图"}</div>${staff ? `<h3>${a.needs_human ? "需要人工核对" : "状态依据完整"}</h3>${facts || '<p class="helper">当前未触发兜底条件；退款仍由外部原流程的授权人员处理。</p>'}<h3>原始资料与版本</h3><div class="sources">${sources}</div><div class="helper">${esc(pkg)}</div><div class="actions"><button class="button" id="recommend">保存本次解释与依据</button>${["manager", "risk"].includes(state.actor.role) ? '<button class="button secondary" id="audit">查看审计链路</button>' : ""}</div><div id="saved-result" class="helper"></div><div id="audit-output"></div>${canDispatch ? `<form id="handoff-form" class="handoff-form"><h3>发起人工交接</h3><textarea name="unresolved_items" placeholder="说明未解决事项与需要核对的字段" minlength="2" maxlength="1000" required aria-label="未解决事项">${esc(a.reasons?.map(reason => reason.message).join("；") || "请核对当前排期与下一步处理责任人")}</textarea><div class="form-grid"><select name="assignee_id" aria-label="具体接手人">${owners.map(person => `<option value="${esc(person.id)}" ${person.id === recommended ? "selected" : ""}>${esc(person.name)} · ${esc(person.label)}</option>`).join("")}</select><button class="button" type="submit">发起交接 →</button></div><p class="helper">指定人员确认接手后，发送方待办才结束。处理备注不改变原始验收和退款状态。</p></form>` : ""}` : `<h3>完成口径</h3><div class="helper">到仓：${date(a.completion.service_received)}<br>验收：${date(a.completion.warehouse_inspected)}<br>退款到账：${date(a.completion.finance_paid)}</div>`}`; // 所有业务字段均转义。
  if (staff) $("#recommend").onclick = event => run(async () => { const rec = await api(`/api/returns/${c.id}/recommendations`, {}); if (state.selected === c.id) $("#saved-result").textContent = `${rec.id} · 已保存资料版本、事实引用和解释结果；相同依据重复请求复用记录。`; toast("解释与原始依据已留痕"); }, event.currentTarget); // 保存可重放建议。
  if ($("#audit")) $("#audit").onclick = event => run(async () => { const rows = await api(`/api/returns/${c.id}/audit`); if (state.selected === c.id) { const pre = document.createElement("pre"); pre.textContent = JSON.stringify(rows, null, 2); $("#audit-output").replaceChildren(pre); } }, event.currentTarget); // 审计作为文本显示。
  if ($("#handoff-form")) $("#handoff-form").onsubmit = event => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); run(async () => { const handoff = await api(`/api/returns/${c.id}/handoffs`, data); toast(`交接 ${handoff.id} 已创建，等待 ${handoff.assignee.name} 确认接手`); }, event.currentTarget.querySelector("button")); }; // 发起不等于接手。
} // 详情渲染结束。
/** 无入参，刷新当前身份列表和统计；旧请求结果不覆盖新身份。 */ // 中文函数契约。
async function refreshReturns() { // 查询授权列表与分母。
  const generation = state.generation; // 标记本次身份版本。
  const params = new URLSearchParams({ q: $("#search").value, only_exceptions: $("#exceptions").checked }); // 发送筛选条件。
  const [items, dashboard] = await Promise.all([api(`/api/returns?${params}`), api("/api/dashboard")]); // 独立读取并行执行。
  if (generation !== state.generation) return; // 身份切换后忽略旧响应。
  state.items = items; // 只缓存当前授权数据。
  if (!items.some(item => item.case.id === state.selected)) state.selected = items[0]?.case.id || null; // 搜索后选择可见单据。
  $("#case-count").textContent = items.length; // 显示筛选结果数量。
  $("#case-list").innerHTML = items.map(caseRow).join("") || '<div class="empty">没有符合条件的退货单</div>'; // 明确空状态。
  const metrics = [["可见退货单", dashboard.total, "唯一售后单 · 合成样本"], ["签收待验收", dashboard.waiting_inspection, "签收与验收分别记录"], ["需人工核对", dashboard.needs_human, "含缺件、冲突、故障与歧义"], ["退款已到账", dashboard.refunded, "仅展示原始到账回执"]]; // 不伪造收益或准确率。
  $("#metrics").innerHTML = metrics.map(([label, value, note]) => `<div class="metric"><div class="metric-label">${esc(label)}<span>↗</span></div><strong>${value.toString().padStart(2, "0")}</strong><small>${esc(note)}</small></div>`).join(""); // 权限过滤后的统计。
  const item = items.find(item => item.case.id === state.selected); // 取得当前选中详情。
  if (item) renderDetail(item); else $("#detail").innerHTML = '<div class="empty">选择一笔退货查看进度与依据</div>'; // 不残留其他客户详情。
} // 刷新列表结束。
/** 无入参，读取内部交接队列；请求失败由动作包装器显示。 */ // 中文函数契约。
async function renderHandoffs() { // 展示明确责任人和真实确认时间。
  const generation = state.generation, rows = await api("/api/handoffs"); // 保护身份切换中的异步响应。
  if (generation !== state.generation) return; // 不渲染旧身份读取结果。
  const labels = { pending: "待确认接手", accepted: "已接手 · 处理中", resolved: "已处理" }; // 协同状态独立于退款状态。
  $("#handoff-list").innerHTML = rows.map(row => `<article class="handoff-card"><div class="case-line"><h2>${esc(row.case_id)} <span class="muted">→ ${esc(row.assignee.name)} · ${esc(row.assignee.label)}</span></h2><span class="badge ${row.status === "resolved" ? "good" : "warn"}">${labels[row.status]}${row.overdue ? " · 超时升级运营经理" : ""}</span></div><p>${esc(row.context.unresolved_items)}</p><div class="helper">发起 ${date(row.created_at)} / 接手 ${date(row.accepted_at)} / 处理完成 ${date(row.resolved_at)}<br>资料 ${esc(row.context.source_version)} · 发送方待办${row.sender_task_complete ? "已结束" : "未结束"} · ${esc(row.id)}</div>${row.context.human_modifications.map(change => `<p>人工处理：${esc(change.note)} <span class="muted">/ ${esc(change.actor_id)} · ${date(change.at)}</span></p>`).join("")}${row.assignee_id === state.actor.id && row.status === "pending" ? `<div class="actions"><button class="button" data-accept="${esc(row.id)}">确认接手</button></div>` : ""}${row.assignee_id === state.actor.id && row.status === "accepted" ? `<form data-resolve="${esc(row.id)}"><textarea name="note" minlength="2" maxlength="1000" required placeholder="记录人工核对结果与下一步，不变更原始退款状态" aria-label="人工处理备注"></textarea><button class="button">记录处理完成</button></form>` : ""}</article>`).join("") || '<div class="empty">暂无交接。在退货详情中选择接手人，发起第一条人工交接。</div>'; // 人工签核不替代原系统业务动作。
} // 交接渲染结束。
/** 无入参，渲染原始访谈台账；只用于授权内部身份。 */ // 中文函数契约。
async function renderEvidence() { // 证据保留原始编号和待核实等级。
  const generation = state.generation, rows = await api("/api/evidence"); // 后端校验读取权限。
  if (generation !== state.generation) return; // 忽略角色切换前的响应。
  $("#evidence-list").innerHTML = rows.map(row => `<article class="evidence-card"><div class="case-line"><code>${esc(row.id)}</code><span class="muted">${esc(row.speaker)}</span></div><p>${esc(row.statement)}</p><small>${esc(row.verification)}</small></article>`).join(""); // 不把访谈陈述当已验证事实。
} // 台账渲染结束。
/** 无入参，刷新当前标签；认证或网络失败交给调用者。 */ // 中文函数契约。
async function refresh() { await refreshReturns(); if (state.tab === "handoffs") await renderHandoffs(); if (state.tab === "evidence") await renderEvidence(); } // 三个标签共用统计。
/** 输入标签名，切换授权视图；客户强制回到本人订单。 */ // 中文函数契约。
async function switchTab(tab) { // 标签只控制显示，不能绕过服务端权限。
  state.tab = state.actor.role === "customer" ? "returns" : tab; // 客户没有内部台账入口。
  document.querySelectorAll("[data-tab]").forEach(button => button.classList.toggle("active", button.dataset.tab === state.tab)); // 导航高亮。
  for (const name of ["returns", "handoffs", "evidence"]) $(`#${name}-panel`).hidden = state.tab !== name; // 切换区域。
  await refresh(); // 获取当前身份的最新视图。
} // 标签切换结束。
/** 无入参，加载公开合成身份并绑定事件；失败显示可见错误。 */ // 中文函数契约。
async function boot() { // 仅为本地演示提供身份切换。
  const data = await api("/api/demo/accounts"); // 明确不是生产账号登录。
  state.accounts = data.accounts; // 公开配置中的演示夹具。
  $("#account").innerHTML = state.accounts.map(person => `<option value="${esc(person.id)}">${esc(person.name)} · ${esc(person.label)}</option>`).join(""); // 展示中文岗位。
  state.actor = state.accounts[0]; // 默认进入售后工单员视图。
  $("#account").onchange = () => run(async () => { state.generation++; state.actor = state.accounts.find(person => person.id === $("#account").value); state.selected = null; $("#search").value = ""; $("#exceptions").checked = false; $("#detail").replaceChildren(); $("#case-list").replaceChildren(); $("#handoff-list").replaceChildren(); $("#evidence-list").replaceChildren(); document.querySelectorAll(".internal").forEach(node => { node.hidden = state.actor.role === "customer"; }); await switchTab("returns"); }); // 切换身份先清空内部资料。
  $("#case-list").onclick = event => { const row = event.target.closest("[data-case]"); if (!row) return; state.selected = row.dataset.case; $("#case-list").innerHTML = state.items.map(caseRow).join(""); renderDetail(state.items.find(item => item.case.id === state.selected)); }; // 选择已授权列表项。
  document.querySelectorAll("[data-tab]").forEach(button => { button.onclick = () => run(() => switchTab(button.dataset.tab)); }); // 标签导航。
  $("#refresh").onclick = event => run(refresh, event.currentTarget); // 手动刷新快照视图，不伪造同步。
  $("#search").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => run(refreshReturns), 180); }; // 搜索防抖。
  $("#exceptions").onchange = () => run(refreshReturns); // 异常过滤。
  $("#handoff-list").onclick = event => { const button = event.target.closest("[data-accept]"); if (button) run(async () => { await api(`/api/handoffs/${button.dataset.accept}/accept`, {}); toast("已确认接手，发送方待办已结束"); await renderHandoffs(); }, button); }; // 实际接手人亲自确认。
  $("#handoff-list").onsubmit = event => { const form = event.target.closest("[data-resolve]"); if (!form) return; event.preventDefault(); run(async () => { await api(`/api/handoffs/${form.dataset.resolve}/resolve`, Object.fromEntries(new FormData(form))); toast("人工处理记录已保存，原始业务快照保持只读"); await renderHandoffs(); }, form.querySelector("button")); }; // 保存人工改动与签核。
  await refresh(); // 首次加载列表和详情。
} // 初始化结束。
if (location.protocol === "file:") { // 本地文件可以展示样式，但浏览器不能通过文件协议调用 FastAPI。
  $("#page-subtitle").textContent = "样式预览已加载。启动项目根目录的 start.command 后，请通过本地服务地址使用完整功能。"; // 说明需要服务入口。
  $("#detail").innerHTML = '<div class="empty"><h2>请从 FastAPI 服务打开工作台</h2><p>双击项目根目录的 start.command 启动服务，再访问启动日志中的地址。</p><p>默认地址：<a href="http://127.0.0.1:8000/">http://127.0.0.1:8000/</a></p></div>'; // 默认地址作为打开入口，端口调整以启动日志为准。
  $("#refresh").hidden = true; // 文件预览不能刷新接口数据。
  $("#search").disabled = true; // 避免没有服务时产生无响应的筛选操作。
  $("#exceptions").disabled = true; // 文件模式不发起 API 请求。
  document.querySelectorAll(".internal").forEach(node => { node.hidden = true; }); // 仅呈现文件预览和启动说明。
} else { // HTTP 服务页面使用正常业务接口。
  run(boot); // 初始化失败给出明确反馈。
} // 按实际打开方式选择入口。
