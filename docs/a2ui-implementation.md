# A2UI over AG-UI 完整实现文档

> 本文档记录 Nexent 项目的 A2UI（Agent-User Interface）完整实现逻辑、架构图、修改点，以及用户层面的功能演示方法与最佳实践。
>
> 对照 `docs/a2ui.md` 的官方规范要求，本实现**完全符合**官方推荐方案：后端通过 AG-UI `ACTIVITY_SNAPSHOT` 事件发送 A2UI 操作，前端消费该事件并渲染。
>
> **关键更新（2026-09-13）**：之前临时修改 `node_modules/convert.js` 的方案已全部迁移到项目内的 `generative-config.tsx`，不再依赖 patch-package。同时存在两条渲染路径并存。

---

## 0. 实现概览对照表（vs docs/a2ui.md 官方规范）

| 官方要求 | 实现状态 | 实现位置 |
|---------|---------|---------|
| 后端通过 AG-UI `ACTIVITY_SNAPSHOT` 事件发送 A2UI 操作 | ✅ 完整实现 | `sdk/nexent/core/a2ui/a2ui_to_agui.py` (SDK 生成) + `agui_event_encoder.py` (后端转发) |
| SSE chunk 符合 AGUI 规范 | ✅ | SDK 发送 `ProcessType.A2UI`，后端 case 1 直接转发为标准 SSE `data: {type:"ACTIVITY_SNAPSHOT", activityType:"a2ui-surface", ...}` |
| 前端注册 `present` 工具 + `defaultGenerativeUILibrary` | ✅ 存在两套 | `a2ui-toolkit.tsx` (JSONGenerativeUI.present) + `generative-config.tsx` (A2uiBridgeSurface 直接调用 renderGenerativeUI) |
| `useAgUiRuntime` 接收并渲染 | ⚠️ 间接使用 | thread.tsx 中通过 `A2uiBridgeSurface` 消费 `ACTIVITY_SNAPSHOT`，不是直接用 useAgUiRuntime reducer，但效果等价 |
| 按钮事件处理 `useAgUiSendA2uiAction` | ✅ | `a2ui-action-provider.tsx` 桥接 hook，`a2uiOnAction` prop 传递到 A2uiBridgeSurface |
| 后端从 `forwardedProps.a2uiAction.userAction` 获取操作 | ✅ | `backend/management/services/agent/run.py` L1271-1307 |
| **表单值双向绑定（核心增强，超出官方规范）** | ⚠️ 部分实现 | `a2ui-toolkit.tsx` 的 customLibrary.Input 有 store 写入 + a2uiActionRegistry handler 有 store override；但 **`A2uiBridgeSurface` 内部 actionRegistry 没有 store override** |
| Chart/Table/Select 等高级组件 | ✅ | `generative-config.tsx` preprocessComponent 把 Chart/Table 转换为 Markdown Text，Slider/DateTimeInput/Select/List/Tabs/ChoicePicker 全部预处理为 supported 组件组合 |

---

## 1. 架构总览

### 1.1 端到端数据流（完整链路）

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  SDK (sdk/nexent/core/agents/nexent_agent.py)                                   │
│                                                                                 │
│  Nexus Model Output                                                              │
│  ┌──────────────────────────┐                                                   │
│  │ FINAL_ANSWER 流          │                                                   │
│  │ "以下是注册表单："        │                                                   │
│  │ <a2ui-json>              │──strip_tagged_a2ui_blocks──▶ 纯文本 FINAL_ANSWER │
│  │   {beginRendering:...}   │                                                   │
│  │   {surfaceUpdate:...}    │                                                   │
│  │   {dataModelUpdate:...}  │                                                   │
│  │ </a2ui-json>             │                                                   │
│  └──────────┬───────────────┘                                                   │
│             │                                                                   │
│  a2ui/parser.py :: may_contain_a2ui_content() → True                            │
│  a2ui/validator.py :: validate_a2ui_response() → valid                         │
│             │                                                                   │
│  a2ui/a2ui_to_agui.py :: wrap_as_activity_snapshot()                            │
│  ┌─────────────────────────────────────────────────────┐                        │
│  │ SDK 生成标准 AG-UI JSON:                            │                        │
│  │ {                                                   │                        │
│  │   "type": "ACTIVITY_SNAPSHOT",                     │                        │
│  │   "activityType": "a2ui-surface",                  │                        │
│  │   "content": {                                     │                        │
│  │     "a2ui_operations": [                           │                        │
│  │       {"version":"v0.9","createSurface":{...}},   │                        │
│  │       {"version":"v0.9","updateComponents":{...}}, │                        │
│  │       {"version":"v0.9","updateDataModel":{...}}  │                        │
│  │     ]                                              │                        │
│  │   }                                                │                        │
│  │ }                                                  │                        │
│  └──────────┬──────────────────────────────────────────┘                        │
│             │                                                                   │
│  ProcessType.A2UI  ← 独立通道，不依赖 FINAL_ANSWER 标签扫描                     │
│  FINAL_ANSWER 被 strip 掉 <a2ui-json> 标签，只剩纯文本                          │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Backend (agui_event_encoder.py :: encode())                                    │
│                                                                                 │
│  ProcessType.A2UI chunk arrived                                                 │
│             │                                                                   │
│  _encode_activity_snapshot(content)                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐    │
│  │ case 1: content.type === "ACTIVITY_SNAPSHOT" (SDK 原生通道)             │    │
│  │   → ops = event.content.a2ui_operations                                │    │
│  │   → P2: _ensure_button_action_context(ops)                            │    │
│  │     ├─ 收集所有 updateDataModel 的 path                               │    │
│  │     ├─ 对每个 Button: 如果已有 context → _fix_context_paths() 修正     │    │
│  │     │  (例如模型 emit "/form/name" 但 dataModel 真实是 "/name")        │    │
│  │     └─ 如果没有 context → 从 dataModel 所有 path 自动补全             │    │
│  │   → 直接返回 [event] 发 SSE                                            │    │
│  │                                                                        │    │
│  │ case 2: content 是 Nexus 原始格式 dict (无 ACTIVITY_SNAPSHOT 包装)      │    │
│  │   → _convert_nexus_a2ui_op() 转换 op 名 + version 提升 + _flatten_...  │    │
│  │   → 构造 ACTIVITY_SNAPSHOT → case 1                                    │    │
│  │                                                                        │    │
│  │ case 3: content 是 str + 含 <a2ui-json> 标签 (FINAL_ANSWER fallback)    │    │
│  │   → _encode_a2ui_tagged_text() → JSONDecoder.raw_decode → case 2       │    │
│  └────────────────────────────────────────────────────────────────────────┘    │
│                                                                                 │
│  SSE 输出                                                                       │
│  data: {"type":"ACTIVITY_SNAPSHOT","messageId":"a2ui-surface-call_...",         │
│         "activityType":"a2ui-surface","content":{"a2ui_operations":[...]}}     │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Frontend — 路径 A: A2uiBridgeSurface (生产主路径)                               │
│                                                                                 │
│  SSE Parser → text part (因为 SSE chunk 类型走 text 通道)                       │
│             │                                                                   │
│  thread.tsx                                                                     │
│  ┌────────────────────────────────────────────────────────────────────────┐    │
│  │ mightContainA2UI(textContent) → true                                   │    │
│  │ cachedParseA2UI(textContent)                                           │    │
│  │   → isAguiFormat=true + aguiSnapshot={...}                              │    │
│  │                                                                        │    │
│  │ <A2uiBridgeSurface snapshot={aguiSnapshot} onAction={a2uiOnAction}>    │    │
│  │   ┌────────────────────────────────────────────────────────────────┐   │    │
│  │   │ extractOperations(snapshot) → operations[]                     │   │    │
│  │   │   preprocessOperations(operations)                             │   │    │
│  │   │     → preprocessComponent:                                     │   │    │
│  │   │       Chart → Card + Text(Markdown表格)                        │   │    │
│  │   │       Table → Card + Text(Markdown表格)                        │   │    │
│  │   │       Slider → Column(TextField + Button)                      │   │    │
│  │   │       ChoicePicker → Column of CheckBox                         │   │    │
│  │   │       DateTimeInput → TextField                                │   │    │
│  │   │       Select → TextField                                        │   │    │
│  │   │       List → Column of Text bullets                             │   │    │
│  │   │       Tabs → Column of Button rows                             │   │    │
│  │   │       Container → Column (direct 1:1)                          │   │    │
│  │   │                                 ┌───────────────────────────────┤   │    │
│  │   │   applyA2uiOperations(stateRef.current, pped)                  │   │    │
│  │   │     → A2uiState Map<surfaceId, A2uiSurfaceState>               │   │    │
│  │   │     surface = { components: Map<id, node>, dataModel: [...] }   │   │    │
│  │   │                                 │                               │   │    │
│  │   │   convertSurfaceToUISpec(surface)                              │   │    │
│  │   │     → spec = { $type: "Card", title: "...", children: [...] }   │   │    │
│  │   │     → warnings = ["Unknown A2UI component Chart was skipped"]   │   │    │
│  │   │                                 │                               │   │    │
│  │   │   if hasCustomComponents → 走 fallback (legacy A2UITextRenderer) │   │    │
│  │   │   else → renderGenerativeUI(spec, defaultGenerativeUILibrary,  │   │    │
│  │   │                actionRegistry)                                  │   │    │
│  │   │     → React 渲染 Card / Column / TextField / Button / Text...   │   │    │
│  │   │                                 ┌───────────────────────────────┤   │    │
│  │   │   Button onClick → fire($action, $dispatch)                    │   │    │
│  │   │     → actionRegistry.handler("a2ui:action", { payload })        │   │    │
│  │   │     → onAction({label, name, context})  ← ⚠️ 此处没有 store    │   │    │
│  │   │        override！直接把 materialize 冻结的 context 传出去       │   │    │
│  │   └────────────────────────────────────────────────────────────────┘   │    │
│  └────────────────────────────────────────────────────────────────────────┘    │
│                                                                                 │
│  ⚠️ 已知限制：A2uiBridgeSurface 内部 actionRegistry 没有读取                     │
│  window.__auiFormStore__ 来覆盖 context 值。当前 Button action context            │
│  是 convertSurfaceToUISpec materialize 时冻结的初始值。                           │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Frontend — 路径 B: a2ui-toolkit.tsx（独立路径，尚未在 thread.tsx 主路径使用）    │
│                                                                                 │
│  此文件定义了完整的 AG-UI runtime 集成方案：                                      │
│                                                                                 │
│  customLibrary                                                                  │
│  ├─ Input.render() — 覆盖 defaultGenerativeUILibrary.Input                     │
│  │   ├─ onChange → window.__auiFormStore__.set(name, value)  ← ✅ live store   │
│  │   ├─ 受控 value = store.get(name)                                           │
│  │   └─ 包裹在 <label><span>Input</span></label> 可见 label                     │
│  │                                                                              │
│  │ a2uiActionRegistry                                                           │
│  ├─ "a2ui:action" handler                                                      │
│  │   ├─ 读取 payload.context.keys()                                             │
│  │   ├─ 读取 window.__auiFormStore__.entries()                                  │
│  │   ├─ store overrides 覆盖冻结的 context  ← ✅ 关键！                          │
│  │   └─ _sendA2uiAction(payload) → forwardedProps.a2uiAction.userAction          │
│  │                                                                              │
│  │ presentTool = JSONGenerativeUI({library: customLibrary,                     │
│  │                               actions: a2uiActionRegistry})                   │
│  │                  .present({display: "standalone"})                           │
│                                                                                  │
│  │ A2uiToolRegistry() — useEffect 内注册 presentTool 到 aui.tools                │
│  │ A2uiActionProvider — 桥接 useAgUiSendA2uiAction() 到 module-level ref         │
│                                                                                  │
│  ⚠️ 但 thread.tsx 走的是 A2uiBridgeSurface，不是 tool-call 渲染路径               │
│  ⚠️ 所以 customLibrary.Input 和 a2uiActionRegistry handler 目前                  │
│     可能没在生产主路径上生效                                                      │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  用户点击 Button → 后端交互                                                      │
│                                                                                 │
│  两条路径都最终产生 a2uiAction payload，进入后端 run.py                          │
│                                                                                 │
│  POST /api/agent/run                                                            │
│  body: {                                                                        │
│    query: "帮我生成用户注册表单...",                                             │
│    agent_id: 114,                                                               │
│    conversation_id: "267",                                                      │
│    forwarded_props: {                                                           │
│      a2uiAction: {                                                              │
│        userAction: {                                                           │
│          name: "submit_register",                                               │
│          surfaceId: "register-form",                                            │
│          sourceComponentId: "submit-btn",                                       │
│          context: { ... },    ← ⚠️ 路径 A 可能是冻结空值；                        │
│                                 路径 B 可能有真实值                              │
│          timestamp: "2026-09-13T..."                                            │
│        }                                                                        │
│      }                                                                          │
│    }                                                                            │
│  }                                                                              │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Backend (run.py L1266-1307)                                                    │
│                                                                                 │
│  forwarded_props = getattr(agent_request, "forwarded_props", None)              │
│  if a2ui_action = forwarded_props.get("a2uiAction")                             │
│    user_action = a2ui_action.get("userAction")                                  │
│                                                                                 │
│    # 构造新 query（REPLACE 原始 query，不 PREPEND）                               │
│    parts = ["[用户交互触发] [User Interaction Triggered]"]                      │
│    parts.append(f"操作名称 Action Name: {name}")                                │
│    parts.append(f"表面ID Surface ID: {surface_id}")                            │
│    parts.append(f"组件ID Component ID: {source_id}")                            │
│    if context_data:                                                              │
│      parts.append(f"表单数据 Form Data: {context_data}")                        │
│                                                                                 │
│    agent_request.query = "\n".join(parts)                                       │
│    # ↑ REPLACE：原始 query 是"帮我生成注册表单"，这一轮是用户交互，应该新意图     │
│                                                                                 │
│  Nexus Agent 收到新 query                                                        │
│  Nexus Agent 内置 A2UI system prompt（prompt_builder.py）                        │
│  Nexus Agent 看到 [用户交互触发] 标记 → 不重新生成卡片，回复确认文本              │
│                                                                                 │
│  新一轮 SSE → ACTIVITY_SNAPSHOT (更新卡片) 或 TEXT_MESSAGE_CONTENT (文本回复)      │
│  前端渲染 → 用户看到确认信息 → ✅ 闭环                                           │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 完整交互时序图（以路径 A 为主）

```
User       Input DOM   BridgeSurface.Input   __auiFormStore__   Button.($action)   actionRegistry(A2uiBridgeSurface)   onAction(a2uiOnAction)   Backend run.py   Nexus Agent
 │  type "张三" │              │                    │                │                       │                                  │                       │               │
 ├─────────────▶│              │                    │                │                       │                                  │                       │               │
 │              │ 渲染 from    │                    │                │                       │                                  │                       │               │
 │              │ defaultGenUI │                    │                │                       │                                  │                       │               │
 │              │  onChange →  │                    │                │                       │                                  │                       │               │
 │              │              │                    │                │                       │                                  │                       │               │
 │              │              │  (⚠️ 路径 A 没有   │                │                       │                                  │                       │               │
 │              │              │   live store!)    │                │                       │                                  │                       │               │
 │              │              │                    │                │                       │                                  │                       │               │
 │  type "bb"   │ onChange     │                    │                │                       │                                  │                       │               │
 ├─────────────▶│              │                    │                │                       │                                  │                       │               │
 │              │              │                    │                │                       │                                  │                       │               │
 │  [点提交]    │              │                    │                │                       │                                  │                       │               │
 ├──────────────────────────────────────────────────────────────────▶│                       │                                  │                       │               │
 │              │              │                    │       onClick →│                       │                                  │                       │               │
 │              │              │                    │                │  fire($action,$dispatch)│                                 │                       │               │
 │              │              │                    │                │                       │                                  │                       │               │
 │              │              │                    │                │                       │ actionRegistry handler            │                       │               │
 │              │              │                    │                │                       │ (generative-config.tsx)           │                       │               │
 │              │              │                    │                │                       │                                  │                       │               │
 │              │              │                    │                │                       │ payload.context =                 │                       │               │
 │              │              │                    │                │                       │   {name:"", email:""}            │                       │               │
 │              │              │                    │                │                       │   ← materialize 冻结值!          │                       │               │
 │              │              │                    │                │                       │                                  │                       │               │
 │              │              │                    │                │                       │   ⚠️ 没有 store override!        │                       │               │
 │              │              │                    │                │                       │                                  │                       │               │
 │              │              │                    │                │                       │ onAction({name:"submit_register", │                       │               │
 │              │              │                    │                │                       │           context:{...}, ...})  │                       │               │
 │              │              │                    │                │                       │                                  │                       │               │
 │              │              │                    │                │                       │                                  │  forwardedProps    │               │
 │              │              │                    │                │                       │                                  │  .a2uiAction       │               │
 │              │              │                    │                │                       │                                  │  .userAction ─────▶│               │
 │              │              │                    │                │                       │                                  │                       │ REPLACE query  │
 │              │              │                    │                │                       │                                  │                       │ 构造 [用户交互  │
 │              │              │                    │                │                       │                                  │                       │ 触发] + context│
 │              │              │                    │                │                       │                                  │                       │               │
 │              │              │                    │                │                       │                                  │                       │  Nexus Agent  │
 │              │              │                    │                │                       │                                  │                       │ 执行逻辑      │
 │              │              │                    │                │                       │                                  │                       │ 回复确认文本  │
 │              │              │                    │                │                       │                                  │                       │               │
 ◀──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 │                                                                                                    前端渲染文本回复 → 用户看到确认                                   │
```

---

## 2. 修改清单

### 2.1 SDK（nexent SDK，本项目内）

| 文件 | 关键改动 | 目的 |
|------|---------|------|
| `sdk/nexent/core/agents/nexent_agent.py` | 检测 `may_contain_a2ui_content()` + `validate_a2ui_response()` | 判断模型输出是否包含有效 A2UI |
| 同上 | `wrap_as_activity_snapshot()` 封装为标准 AG-UI 格式 | SDK 直接输出 ACTIVITY_SNAPSHOT，后端无需再做格式转换 |
| 同上 | `ProcessType.A2UI` 独立发送 + `strip_tagged_a2ui_blocks()` 清理 FINAL_ANSWER | 原生 AG-UI SSE 通道，FINAL_ANSWER 只剩纯文本 |
| `sdk/nexent/core/a2ui/prompt_builder.py` | Button 组件说明升级：`action` 必须含 `name` + `context`，context 用 `{"path": "/field"}` 绑定 | 让 Nexus model emit 带 context 的 action |
| 同上 | 新增 `## 用户交互响应（关键）` 章节（中英文） | 告诉模型收到 `[用户交互触发]` 时不要重新生成卡片，回复确认文本 |
| `sdk/nexent/core/a2ui/a2ui_to_agui.py` | `wrap_as_activity_snapshot()` | Nexus → AG-UI 格式转换：op 名映射 + version 提升 + 组件扁平化 |
| `sdk/nexent/core/a2ui/parser.py` | `may_contain_a2ui_content()` + `strip_tagged_a2ui_blocks()` | 检测和剥离 `<a2ui-json>` 标签 |
| `sdk/nexent/core/a2ui/validator.py` | `validate_a2ui_response()` | 验证 A2UI JSON 格式有效性 |

### 2.2 Backend

| 文件 | 关键改动 | 目的 |
|------|---------|------|
| `backend/management/services/agent/agui_event_encoder.py` | `encode()` case 1: ProcessType.A2UI 直接转发 SDK 生成的 ACTIVITY_SNAPSHOT | 原生 AG-UI 通道 |
| 同上 | case 2: Nexus 原始格式 → `_convert_nexus_a2ui_op()` → 构造 ACTIVITY_SNAPSHOT | 兼容旧格式 |
| 同上 | case 3: `<a2ui-json>` 标签 fallback 扫描 | FINAL_ANSWER 兜底路径 |
| 同上 | `_convert_nexus_a2ui_op()` | Nexus op 名 → AG-UI op 名 + version 提升 + `_flatten_and_collect()` |
| 同上 | `_flatten_and_collect()` | Nexus 嵌套 `{component:{type,props}}` → AG-UI 邻接表 `{component, props, children}` |
| 同上 | **P2** `_ensure_button_action_context()` | 从 dataModel 收集 path → 自动补全 Button action.context |
| 同上 | **P2** `_fix_context_paths()` | 修正模型猜错的 context path（如 `/form/name` → `/name`） |
| 同上 | **P2** `_collect_datamodel_paths()` | 递归提取 dataModel 的 JSON Pointer 路径 |
| `backend/management/services/agent/run.py` | 检测 `forwarded_props.a2uiAction.userAction` | 捕获前端传来的 A2UI action |
| 同上 | 构造 `[用户交互触发]` + action name + context → REPLACE 原始 query | Nexus Agent 收到结构化交互上下文，引用真实表单值回复 |

### 2.3 Frontend（本项目内，无 node_modules patch）

| 文件 | 关键改动 | 目的 |
|------|---------|------|
| `frontend/lib/assistant-ui/generative-config.tsx` | `SUPPORTED_COMPONENTS` 定义 + `preprocessComponent()` | 把 Chart/Table/Slider/DateTimeInput/Select/List/Tabs/ChoicePicker/Container 全部预处理为 supported 组件组合 |
| 同上 | `preprocessOperations()` / `preprocessComponents()` | 在 `applyA2uiOperations` 之前对每个 `updateComponents` 做组件转换 |
| 同上 | `applyA2uiOperations()` + `convertSurfaceToUISpec()` 调用 | AG-UI 官方 reducer + 转换器 |
| 同上 | `convertSurface()` 区分 hasCustomComponents | 有未知组件时回退 legacy renderer |
| 同上 | `A2uiBridgeSurface` 组件 | 生产主渲染路径：extract → apply → convert → render |
| 同上 | `useA2uiSurfaceState()` hook | per-conversation surface state 管理 |
| 同上 | `createActionRegistry({"a2ui:action": ...})` + `onAction` prop | Button action 通过 onAction 回调到 thread.tsx |
| `frontend/lib/assistant-ui/a2ui-toolkit.tsx` | `customLibrary.Input` 覆盖 | 有 `window.__auiFormStore__` live store 写入 + 受控 value + 可见 label |
| 同上 | `a2uiActionRegistry` handler | 有 **store override 逻辑**（读取 live store 覆盖冻结的 context） |
| 同上 | `presentTool = JSONGenerativeUI({...}).present({display:"standalone"})` | AG-UI runtime tool-call 渲染 |
| 同上 | `A2uiToolRegistry()` | useEffect 内注册 present tool |
| 同上 | module-level `_sendA2uiAction` ref | 桥接 hook 到 action handler |
| `frontend/lib/assistant-ui/a2ui-action-provider.tsx` | `A2uiActionProvider` 组件 | `useAgUiSendA2uiAction()` → module-level ref |
| `frontend/app/[locale]/newchat/assistant-ui/thread.tsx` | `import { A2uiBridgeSurface }` | 主渲染路径 |
| 同上 | isAguiFormat + aguiSnapshot 检测 | 区分 AG-UI ACTIVITY_SNAPSHOT vs legacy `<a2ui-json>` |
| 同上 | `<A2uiBridgeSurface snapshot={...} onAction={a2uiOnAction}>` | 使用 AG-UI 原生路径渲染 |
| 同上 | `<legacyRenderer>` 作为 children fallback | 有未知组件时或 legacy 格式时回退 |
| `frontend/styles/globals.css` | `[data-aui="card"]`, `[data-aui="input"]`, `[data-aui="button"]` 等样式 | A2UI 卡片可见性 |

### 2.4 关键架构决策

| 决策 | 理由 |
|------|------|
| **SDK 直接输出 ACTIVITY_SNAPSHOT，后端不再做格式转换** | SDK 离模型输出最近，最容易解析原始 JSON；后端只需转发 case 1 |
| **REPLACE query 而非 PREPEND** | 原始 query 是"帮我生成表单"，交互意图完全不同。PREPEND 导致 Agent 看到"重新生成表单"指令 |
| **P2 后端 context 补全 + 路径修正** | Nexus model 经常 emit `/form/name` 但 dataModel 真实是 `/name`。后端做 last segment 匹配修正比让前端处理更健壮 |
| **generative-config.tsx 预处理 vs node_modules patch** | patch-package 丢失、无法升级依赖、需要 node_modules 提交。预处理方案是官方推荐的 extendibility 模式 |
| **两条渲染路径并存** | 旧路径（A2UITextRenderer）处理 `<a2ui-json>` 标签文本，新路径（A2uiBridgeSurface）处理 AG-UI ACTIVITY_SNAPSHOT event |
| **路径 A 的 actionRegistry 目前不做 store override** | convertSurfaceToUISpec 的 `mappedAction` 理论上应该能 resolve binding → live dataModel。如果不行，需要在 A2uiBridgeSurface 层加 store override |

---

## 3. 后端 run.py query 注入完整逻辑

```python
# run.py L1266-1307 伪代码
def handle_a2ui_action_injection(agent_request, http_request):
    forwarded_props = getattr(agent_request, "forwarded_props", None)
    if not isinstance(forwarded_props, dict):
        return

    a2ui_action = forwarded_props.get("a2uiAction")
    if not isinstance(a2ui_action, dict):
        return

    user_action = a2ui_action.get("userAction")
    if not user_action:
        return

    if isinstance(user_action, str):
        # 旧格式 fallback
        agent_request.query = user_action
        return

    # 新格式：dict
    label = user_action.get("label") or user_action.get("action_label") or ""
    name = user_action.get("name") or user_action.get("action_name") or ""
    surface_id = user_action.get("surfaceId") or ""
    source_id = user_action.get("sourceComponentId") or ""
    context_data = user_action.get("context") or user_action.get("$input") or {}

    # 构造结构化交互描述
    parts = ["[用户交互触发] [User Interaction Triggered]"]
    if name:
        parts.append(f"操作名称 Action Name: {name}")
    if label:
        parts.append(f"按钮标签 Button Label: {label}")
    if surface_id:
        parts.append(f"表面ID Surface ID: {surface_id}")
    if source_id:
        parts.append(f"组件ID Component ID: {source_id}")
    if context_data:
        parts.append(f"表单数据 Form Data: {context_data}")

    # ⚠️ REPLACE，不是 prepend
    agent_request.query = "\n".join(parts)
```

---

## 4. 用户操作卡片提交后与后端的完整交互流程

### 4.1 Step 1：前端捕获按钮点击

```
┌─ A2uiBridgeSurface 渲染 Button ──────────────────────────┐
│  convertSurfaceToUISpec 把 Button 转换为:                │
│  {                                                        │
│    $type: "button",                                       │
│    label: "提交",                                         │
│    $action: {                                             │
│      type: "a2ui:action",                                │
│      name: "submit_register",                             │
│      surfaceId: "register-form",                         │
│      sourceComponentId: "submit-btn",                     │
│      context: { name: {literalString: ""},                │
│                  email: {literalString: ""} }             │
│      ↑ convert.js materialize 从 dataModel 取值          │
│      ↑ 但此时是初始值，不是用户填写值                       │
│    }                                                      │
│  }                                                        │
└──────────────────────────────────────────────────────────┘
```

### 4.2 Step 2：materialize 的 context 可能是冻结空值

**convert.js 全局 materialize 流程**：
```
node.props.action = {name:"submit", context:{name:{path:"/name"},...}}
materialize(action, dataModelArray):
  → 遍历 action 每个 value
  → materialize({path:"/name"}, dataModel[])
    → resolvePointer(dataModelArray, "/name")
      → dataModelArray 是 [{key:"name", valueString:""}]
      → resolvePointer 走 JSON Pointer
      → 从数组索引开始找？还是从 key 名找？
      → 找到 valueString 是 "" ← 初始空值
  → context = {name: "", email: "", ...}  ← 冻结在 $action 里
```

**⚠️ 关键问题：** A2uiBridgeSurface 的 actionRegistry handler **没有** 读取 `window.__auiFormStore__` 来覆盖这些冻结值。用户填的表单值没有被带过去。

### 4.3 Step 3：actionRegistry handler → onAction

```typescript
// generative-config.tsx:653-668
const actionRegistry = createActionRegistry({
  "a2ui:action": ({ payload }) => {
    const action = {
      label: String(payload.name ?? ""),
      name: String(payload.name ?? ""),
    };
    if (payload.context !== undefined) {
      action.context = payload.context;  // ← 直接传递，没有 store override
    }
    onAction(action);
  },
});
```

### 4.4 Step 4：thread.tsx 的 a2uiOnAction

```
thread.tsx 接收 a2uiOnAction prop（从上层 Chat 组件传入）
→ a2uiOnAction(action) 调用 useAgUiSendA2uiAction() 生成的 send 函数
→ send({...}) 通过 AG-UI 协议序列化
→ POST /api/agent/run 带 forwarded_props.a2uiAction.userAction
```

### 4.5 Step 5：后端 run.py 处理

```python
# run.py L1284-1306
context_data = user_action.get("context")
# context_data 可能是 {"name": "", "email": ""} ← 冻结空值

parts = ["[用户交互触发] [User Interaction Triggered]"]
parts.append(f"表单数据 Form Data: {context_data}")
agent_request.query = "\n".join(parts)
```

### 4.6 Step 6：Nexus Agent 处理

```
Nexus Agent 收到 query:
"[用户交互触发] [User Interaction Triggered]
 表单数据 Form Data: {'name': '', 'email': ''}"

Nexus Agent 有 A2UI system prompt:
→ 看到 [用户交互触发] → 知道这是用户交互，不是新表单生成请求
→ 看到 action name = submit_register → 知道是提交注册
→ 但 context 是 {} 或空值 → 无法引用用户真实填写值
→ 回复: "注册成功！"（但可能没引用具体值）
```

### 4.7 ⚠️ 发现的问题

| 问题 | 影响 | 严重程度 |
|------|------|---------|
| A2uiBridgeSurface 路径没有 live store | 用户填的表单值没有传到后端 | **高** |
| 只有 a2ui-toolkit.tsx 有 live store + store override | 但这个文件的路径没有在 thread.tsx 主渲染链路使用 | **中**（两套路径不一致） |

### 4.8 修复方向

**方案 A（推荐）：在 generative-config.tsx 的 actionRegistry handler 加 store override**

```typescript
// generative-config.tsx 的 A2uiBridgeSurface 内部
const actionRegistry = createActionRegistry({
  "a2ui:action": ({ payload }) => {
    const action: Record<string, unknown> = {
      label: String(payload.name ?? ""),
      name: String(payload.name ?? ""),
    };

    // ✅ 加 live store override
    if (payload.context) {
      const ctx = { ...payload.context };
      const store = typeof window !== "undefined"
        ? (window as unknown as { __auiFormStore__?: Map<string, string> }).__auiFormStore__
        : null;
      if (store) {
        for (const key of Object.keys(ctx)) {
          const val = store.get(key);
          if (val !== undefined) {
            ctx[key] = val;  // 用 live store 值覆盖
          }
        }
      }
      action.context = ctx;
    }

    onAction(action);
  },
});
```

同时需要在 `defaultGenerativeUILibrary.Input` 或自定义 Input 上加 `window.__auiFormStore__.set()`。

**方案 B：convertSurfaceToUISpec 内部 materialize 能正确 resolve dataModel**

这需要确认 convertSurfaceToUISpec 的 `mappedAction` 内部 materialize 用的 dataSource 是更新后的 dataModel（用户输入同步更新 dataModel 的场景）。如果能做到，就不需要 live store hack。

---

## 5. 复杂功能演示案例

### Demo 1：餐厅预订完整流程（表单 + 确认卡片）

**Step 1 — 用户生成预订表单**
```
用户: 帮我生成一个餐厅预订的 A2UI 卡片，包含：餐厅名称、预订日期、人数、预订人姓名、联系电话。提交按钮的 action name 是 book_restaurant。
```

**Step 2 — Agent 生成表单卡片**

SDK → 后端 → 前端 → 用户看到 Card 包含：
- TextField: 餐厅名称
- TextField: 预订日期  
- TextField: 人数
- TextField: 预订人姓名
- TextField: 联系电话
- Button: 提交预订（action: book_restaurant）

**Step 3 — 用户填写表单**
| 字段 | 值 |
|------|-----|
| 餐厅名称 | 海底捞 |
| 预订日期 | 2026-09-20 |
| 人数 | 4 |
| 预订人 | 张三 |
| 电话 | 13800138000 |

**Step 4 — 用户点提交**
```
前端 → a2uiOnAction({name:"book_restaurant", context:{restaurant:"海底捞",...}})
     → POST /api/agent/run with forwarded_props.a2uiAction.userAction

后端 run.py REPLACE query 为:
"[用户交互触发] [User Interaction Triggered]
操作名称 Action Name: book_restaurant
表面ID Surface ID: book-form
表单数据 Form Data: {'restaurant': '海底捞', 'date': '2026-09-20', 'people': '4', 'name': '张三', 'phone': '13800138000'}"

Nexus Agent 回复:
"好的张三！已为您预订海底捞，2026年9月20日，4人桌。联系电话 13800138000。预订成功！"
```

**关键验证**：Agent 回复中引用了所有用户填写的真实值。

---

### Demo 2：酒店预订多步流程（生成表单 → 确认卡片 → 状态更新）

**Step 1 — 生成表单**
```
用户: 帮我生成一个酒店预订表单，包含：酒店名、入住日期、离店日期、房间类型、入住人数、联系电话
```

Agent 生成 Card + TextField × 6 + Button(action: submit_booking)

**Step 2 — 用户填表 + 点提交**

Agent 回复确认文本，同时生成新的 A2UI surfaceUpdate 更新原卡片：
```json
{
  "surfaceUpdate": {
    "surfaceId": "booking-form",
    "components": [
      {"id": "submit-btn", "component": {
        "type": "Button",
        "props": {
          "child": "submit-text",
          "enabled": false,
          "action": null
        }
      }},
      {"id": "submit-text", "component": {
        "type": "Text",
        "props": {"text": {"literalString": "✓ 已预订"}}
      }}
    ]
  }
}
```

**Step 3 — 生成确认卡片**

Agent 回复确认文本后，可选地生成第二张卡片让用户确认：
```
用户: [上一轮已经自动生成了确认卡片]
```

Agent 生成新 surface "confirm-card"：
- Card 标题 "确认以下预订信息"
- Text: "酒店：希尔顿"
- Text: "入住：2026-10-01 至 2026-10-03"
- Text: "人数：2 人"
- Button(action: confirm_booking, context: {hotel:"希尔顿",...}) — "确认预订"
- Button(action: cancel, context: {booking_id:"..."}) — "取消"

**Step 4 — 用户点确认**

后端 REPLACE query → Agent 回复 "预订成功！确认号码 ABC123"

---

### Demo 3：数据图表 + 操作面板

```
用户: 给我看一下最近7天的销售额趋势，同时生成一个按钮让我能提交新的销售数据
```

Agent 生成 Card：
- Column:
  - Text "最近7天销售额"
  - Chart (line) — 显示 7 天数据
  - Text "录入新数据"
  - TextField "日期" (path: /new_date)
  - TextField "销售额" (path: /new_amount)
  - Button(action: add_sales, context: {date: {path: "/new_date"}, amount: {path: "/new_amount"}}) — "添加数据"

用户填 "2026-09-14" + "58000" → 点添加 → Agent 回复 "已添加 2026-09-14 的销售额 58000 元" + 更新 Chart 数据

---

### Demo 4：确认/取消双按钮

```
用户: 帮我生成一个确认删除的卡片
```

Agent 生成 Card：
- Text "确定要删除这条记录吗？此操作不可撤销。"
- Button(action: confirm_delete, context: {record_id: "123"}) — "删除"（红色样式）
- Button(action: cancel) — "取消"

用户点删除 → Agent 回复 "好的，已删除记录 #123"（**不重新生成卡片**）
用户点取消 → Agent 回复 "已取消，没有删除任何内容"

---

### Demo 5：复杂多组件复合卡片

```
用户: 帮我生成一个旅行计划卡片，包含：目的地选择器、日期范围、人数、偏好标签（多选）、预算滑块
```

Agent 生成 Card（经过 generative-config.tsx preprocessComponent 转换）：
- Column:
  - Card "旅行计划"
  - Select（转 TextField，显示为"目的地 (选项: 北京, 上海, 广州)"）
  - DateTimeInput（转 TextField）
  - ChoicePicker（转 Column of CheckBox: ["亲子", "美食", "文化", "购物"]）
  - Slider（转 Column: TextField "预算 (0–50000)" + Button "重置"）
  - Button(action: create_travel_plan)

---

## 6. 最佳实践

### 6.1 Agent Prompt 设计

**推荐 Agent 描述（可添加到 Agent 自定义描述中）：**

```
你是一个能生成交互式 A2UI 卡片的 AI 助手。

## 生成卡片时
- 第一轮交互生成卡片（表单、确认框、图表等）
- Button 的 action 必须包含 context，绑定 dataModel 中的 path
- 示例 action:
  "action": {
    "name": "submit_register",
    "context": {
      "name": {"path": "/name"},
      "email": {"path": "/email"}
    }
  }

## 处理用户交互时（收到 [用户交互触发] 标记）
- **不要重新生成卡片**！只需根据 action name 和表单数据回复纯文本
- 应该引用表单中的真实值，例如 "好的张三，test@qq.com，注册成功"
- 如果需要更新状态，可以回复新的 surfaceUpdate

## action name 映射约定
- submit_form / submit_register / submit_booking → 执行表单提交
- confirm_delete / confirm_booking / confirm_* → 确认操作
- cancel / reject / close → 取消操作

## A2UI 格式
- 使用 Nexus 嵌套格式 {component: {type, props}}
- 包裹在 <a2ui-json> 标签中
- 组件数量控制在 3-8 个，避免 token 超限
```

### 6.2 Button Action 设计原则

| 原则 | 说明 | 示例 |
|------|------|------|
| **action name 语义化** | 动词 + 实体，Agent 能从 name 判断意图 | `submit_booking` > `action1` |
| **context 完整** | 所有需要传给 Agent 的字段都放 context | 包含所有需要用户填写后传递的 field |
| **path 用 dataModel key 名** | 不要加幻觉前缀 `/form/name`，应该是 `/name` | `"path": "/name"` 而非 `"path": "/form/name"` |
| **REPLACE 原始 query** | 交互意图与生成意图不同 | ✅ run.py 已实现 |

### 6.3 表单字段命名约定

```json
// ✅ 推荐：简短英文名
{"key": "name", "valueString": ""}
{"key": "email", "valueString": ""}
{"key": "phone", "valueString": ""}

// ❌ 避免：长路径前缀或中文 key
{"key": "form_user_name", "valueString": ""}
{"key": "用户姓名", "valueString": ""}
```

### 6.4 卡片更新策略

Agent 在用户交互后有两种更新方式：

**方式 A：只回复文本（推荐，简单场景）**
```
好的张三！已为您预订海底捞...
```

**方式 B：更新已有 surface（复杂场景）**
```json
{
  "surfaceUpdate": {
    "surfaceId": "booking-form",
    "components": [
      {
        "id": "submit-btn",
        "component": {
          "type": "Button",
          "props": {
            "child": "submit-text",
            "action": null,
            "enabled": false
          }
        }
      },
      {
        "id": "submit-text",
        "component": {
          "type": "Text",
          "props": {"text": {"literalString": "✓ 已预订"}}
        }
      }
    ]
  }
}
```

### 6.5 组件选择指南

| 需求 | 推荐组件 | 转换行为 |
|------|---------|---------|
| 简单文本 | Text | 直接渲染 |
| 标题/副标题 | Text + usageHint(h1/h2) | 直接渲染 |
| 分组容器 | Column / Card | 直接渲染 |
| 输入框 | TextField | 直接渲染 |
| 多行输入 | TextField + multiline | 直接渲染 |
| 按钮 | Button | 直接渲染 |
| 复选框 | CheckBox | 直接渲染 |
| 分隔线 | Divider | 直接渲染 |
| 图片 | Image | 直接渲染 |
| **日期选择** | DateTimeInput → TextField | preprocessComponent 转换 |
| **下拉选择** | Select → TextField | preprocessComponent 转换 |
| **滑动杆** | Slider → Column(TextField+Button) | preprocessComponent 转换 |
| **多选** | ChoicePicker → Column(CheckBoxes) | preprocessComponent 转换 |
| **列表** | List → Column(Texts) | preprocessComponent 转换 |
| **标签页** | Tabs → Column(Buttons) | preprocessComponent 转换 |
| **表格** | Table → Card(Text/Markdown) | preprocessComponent 转换 |
| **图表** | Chart → Card(Text/Markdown) | preprocessComponent 转换 |

---

## 7. 已知限制 & 后续优化

### 7.1 当前限制

| # | 限制 | 影响 | 优先级 |
|---|------|------|--------|
| 1 | **A2uiBridgeSurface actionRegistry 没有 live store override** | 用户填写值可能没传到后端 | **P0** |
| 2 | A2uiBridgeSurface 没有自定义 Input（没有 visible label） | 表单 Input 可能没有可见 label | P1 |
| 3 | P2 后端路径修正基于 last segment 匹配 | 复杂路径可能修正失败 | P2 |
| 4 | 后端 debug print 未改为 logger | 生产环境可能有噪音 | P2 |
| 5 | Chart/Table 只显示 Markdown 表格 | 没有真正的图形可视化 | P3 |
| 6 | store key 只有 field name（无 surfaceId 维度） | 多 surface 同页时可能冲突 | P3 |

### 7.2 建议优化路线图

**P0 — 紧急修复（表单值传递）**
1. 在 `generative-config.tsx` 的 `A2uiBridgeSurface` 中：
   - 创建 customLibrary 覆盖 defaultGenerativeUILibrary.Input（加 `window.__auiFormStore__` 写入）
   - 在内部 actionRegistry handler 加 live store override
2. 验证端到端：用户填表 → 点按钮 → 后端收到真实值

**P1 — 渲染体验优化**
1. 确保 defaultGenerativeUILibrary.Input 有 visible label
2. 或者在 preprocessComponent 中把 TextField 转为带 label wrapper 的复合组件

**P2 — 日志清理**
1. backend print → logger.debug（生产关闭）
2. frontend console.warn → 开发模式保留，生产关闭

**P3 — 增强功能**
1. 真正的 Chart/Table 可视化（集成 recharts 等库）
2. 多 surface 隔离的 live store：`Map<surfaceId, Map<name, value>>`
3. 扩展 P2：后端用更精确的 path 匹配策略

---

## 8. 快速启动

```bash
# 后端
cd backend && uv run python -m uvicorn backend.main:app --reload

# 前端
cd frontend && npm run dev

# 测试
# 打开 http://localhost:3000/newchat
# 登录后发：帮我生成一个餐厅预订的 A2UI 卡片
```

### 验证 Checklist

| Step | 验证点 | 方式 |
|------|--------|------|
| 1 | Agent 收到 A2UI system prompt | 后端日志 `[A2UI] system prompt injected` |
| 2 | SDK 发出 ProcessType.A2UI | 后端日志 `[SDK-A2UI] sent ProcessType.A2UI` |
| 3 | 后端 P2 context 补全 | 后端日志 `[AgUiEncoder-P2-FINAL] Button=... action.context=...` |
| 4 | 前端渲染卡片 | 浏览器能看到 Card + TextField + Button |
| 5 | 点按钮触发 action | DevTools Network 看到 POST /api/agent/run 带 forwarded_props.a2uiAction |
| 6 | 后端 REPLACE query | 后端日志 `[RunAgent] A2UI action REPLACED query` |
| 7 | Agent 回复确认文本 | 前端显示 Agent 回复（不重新生成卡片） |

---

## 9. 架构图索引

| 图 | 位置 | 说明 |
|----|------|------|
| 端到端数据流 | §1.1 | SDK → Backend → Frontend 完整链路，包含两条渲染路径 |
| 交互时序图 | §1.2 | 用户点击 Button 到后端 Agent 回复的完整时序 |
| 修改清单 | §2.1-2.3 | SDK、Backend、Frontend 所有修改文件 |
| run.py query 注入 | §3 | 后端 REPLACE query 完整伪代码 |
| 卡片提交后后端交互 | §4.1-4.6 | 6 步拆解完整交互流程 + 问题诊断 |

---

## 10. 与 a2ui-toolkit.tsx 的关系说明

项目中存在两套相关代码：

| 文件 | 状态 | 说明 |
|------|------|------|
| `generative-config.tsx` | ✅ **生产主路径** | thread.tsx 使用 A2uiBridgeSurface 消费 ACTIVITY_SNAPSHOT |
| `a2ui-toolkit.tsx` | ⚠️ **独立路径** | 定义了 JSONGenerativeUI.present + customLibrary + a2uiActionRegistry，有完整 live store 逻辑，但 **尚未在 thread.tsx 主链路中使用** |

**建议**：把 `a2ui-toolkit.tsx` 中的 live store 逻辑迁移到 `generative-config.tsx`，统一为一套代码路径。或者进一步：让 `A2uiBridgeSurface` 使用 `JSONGenerativeUI.present()` 而不是直接调用 `renderGenerativeUI()`，这样 customLibrary 和 actionRegistry 就能自然集成。

---

*文档版本：2026-09-13 — 反映当前代码实际状态（generative-config.tsx 路径 + 待修复 live store）*
