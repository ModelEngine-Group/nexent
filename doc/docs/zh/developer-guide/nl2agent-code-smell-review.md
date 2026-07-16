# NL2AGENT 代码坏味道审查

## 1. 审查范围

本文记录当前工作区相对 Jujutsu revision `lvnqqsqn` 的 NL2AGENT 代码审查结果。

- 对比基线：`lvnqqsqn`（Git commit `4e7d9fe1`）
- 审查对象：当前工作区中的 Backend、SDK、Frontend、双语 Prompt、测试与文档改动
- 变更规模：约 74 个文件、1.6 万行新增代码
- 审查重点：状态一致性、并发安全、事务边界、错误处理、接口契约、前端副作用与测试有效性

当前版本已经将 NL2AGENT 从简单 Agent 扩展为跨 Backend、SDK、Redis、Prompt 和 Frontend 的完整工作流。主要风险并非单纯来自代码规模，而是工作流状态和副作用分散在多个层级，部分实现已存在明确的数据一致性缺陷。

## 1.1 分阶段整改进度（2026-07-15）

| 审查项 | 当前状态 | 已实施行为 |
|---|---|---|
| 2.1 Redis 整对象覆盖 | 已解决 | v2 State 增加 `revision`，所有修改统一使用 `WATCH/MULTI` CAS，冲突最多重试 5 次。 |
| 2.2 Card Delivery 时序 | 已解决 | 回执使用数据库 `message_id`，校验 Conversation、assistant、completed 和最新完成消息。 |
| 2.3 失败回滚过大 | 已解决 | `failed` 回执只记录失败原因和次数，不再删除业务状态。 |
| 2.4 前端全局回执集合 | 已解决 | 改为 conversation/draft/message 作用域 coordinator，API 成功后才标记完成。 |
| 2.5 Apply All 假成功 | 已解决 | Tool/Skill 使用共享 SQLAlchemy Session，全有或全无；Redis 失败可幂等对账。 |
| 2.6 MCP 幂等与补偿 | 已解决 | 稳定 installation key、Redis 安装锁、直接返回 `mcp_id`，支持发现阶段恢复及容器补偿。 |
| 2.7 Session 初始化补偿 | 已解决 | 先验证 Catalog，再在一个数据库事务创建 draft/Conversation，Redis 与数据库失败双向补偿。 |
| 3.1 状态机重复 | 已解决 | Backend Workflow Evaluator 统一输出 `current_stage`、`expected_card_types`、`allowed_actions`；Prompt 只消费摘要。 |
| 3.2 God Service | 进行中 | Publication 与 Local Resource Binding 已拆为专用 Service；Session/Catalog/MCP 仍待完成物理拆分。 |
| 3.3 Catalog 故障伪装为空 | 已解决 | 合法空目录与加载失败分离；加载失败返回带上下文的 503 领域错误。 |
| 3.4 异常字符串映射 | 已解决 | 使用固定 ErrorCode 的领域异常；App 不再按错误文案匹配状态码。 |
| 3.5 Finalize 失效参数 | 已解决 | 请求体只保留 proposal、Prompt 和受支持 runtime 字段，额外旧字段直接拒绝。 |
| 4.1 SDK 全局搜索缓存 | 已解决 | 删除 `_search_cache`；每次 Agent Run 使用 Backend 注入的不可变 Catalog 重新计算。 |
| 4.2 SDK 误导状态 | 已解决 | 删除 applied/config/searched 等实例状态。 |
| 5.1/5.2 多套 Schema 与重复解析 | 已解决 | 增加 canonical JSON Schema；Frontend 用 Ajv 一次解析生成 typed card AST。 |
| 5.3 卡片副作用重复 | 已解决 | 模型、需求、本地资源、MCP、Skill、身份与联网完成统一使用 conversation/draft/card scoped `useNl2AgentCardLifecycle`。 |
| 5.4 前端真实交互测试 | 部分解决 | 已加入 Vitest、jsdom、React Testing Library，并覆盖统一生命周期的 busy、continuation、失败重试和输入阻塞；仍需补齐完整 API 与会话切换用例。 |

每个已完成阶段均以独立 Jujutsu commit 提交，并通过对应 Backend、SDK 或 Frontend 聚焦测试。

## 2. 高风险正确性问题

### 2.1 Redis Session State 使用非原子整对象覆盖

位置：`backend/agents/nl2agent_session_catalog.py`

大部分 Session State 操作采用以下流程：

1. 从 Redis 读取完整 JSON。
2. 在进程内修改部分字段。
3. 使用 `SETEX` 覆盖完整 JSON。

该模式没有使用 Redis Transaction、`WATCH/MULTI`、Lua、CAS、锁或版本号。模型、MCP、Skill、卡片回执和自动续跑并发发生时，不同请求可能基于同一个旧快照写回，造成后写请求覆盖先写请求。

典型场景是 MCP 与 Skill 卡片几乎同时注册，最终 Session State 可能只保留其中一个在线推荐批次。

建议：将状态拆分为 Redis Hash，或引入带版本号的 CAS/Lua 原子更新机制，并为并发更新增加冲突重试。

### 2.2 Card Delivery 缺少可靠的时序与过期保护

位置：

- `backend/agents/nl2agent_session_catalog.py::record_card_delivery`
- `backend/services/nl2agent_service.py::report_card_delivery`

当前实现只保存每种卡片最后一条回执。幂等判断仅比较当前保存的 `message_key`、`status` 和 `card_key`，没有保存 Agent Run ID、消息序号或单调版本。

因此，延迟到达的历史回执仍可能被当成新事件处理：

- 旧的 `failed` 回执可能回滚新卡片状态。
- 旧的 `rendered` 回执可能清零新一轮失败次数。
- 历史消息可能影响当前未完成阶段。

后端目前只检查卡片类型是否符合当前阶段，无法证明回执属于当前最新 Agent Run。

建议：为每轮生成分配稳定的 delivery generation/run ID，并只接受当前 generation 的回执；服务端同时校验消息序号或版本单调递增。

### 2.3 卡片失败回滚范围过大

位置：`backend/agents/nl2agent_session_catalog.py::_rollback_failed_card`

该函数接收 `card_key`，但回滚时没有使用它：

- 本地资源卡失败会删除全部 `recommendations_ready` 批次。
- MCP 或 Skill 卡失败会删除对应类型的全部未完成在线批次。

这意味着一张截断或无效卡片可能清除同阶段其他已经正确生成的推荐批次。函数参数给出了“精确回滚”的接口表象，但实际行为是范围回滚。

建议：使用 `card_key` 或 `recommendation_batch_id` 精确删除对应批次；无法确认归属时拒绝回滚，而不是扩大清理范围。

### 2.4 前端回执 API 失败后可能永久无法重试

位置：`frontend/app/[locale]/chat/streaming/chatStreamFinalMessage.tsx`

前端使用模块级全局集合 `processedCardDeliveryMessages` 记录已经处理的消息，并在回执 API 成功之前就写入集合。

如果 API 因网络或服务故障失败：

- 消息已经被标记为已处理。
- React 重渲染不会再次提交回执。
- 当前错误状态不一定提供有效的回执重试入口。
- 全局集合没有容量限制和清理机制，长期运行存在内存增长。

建议：只在回执成功后标记完成；失败状态应可重试。记录应放入 conversation/draft 级 coordinator，并在会话释放时清理。

### 2.5 Apply All 在资源绑定失败后仍标记批次为 applied

位置：`backend/services/nl2agent_service.py::apply_local_resources_batch`

Tool 和 Skill 绑定分别使用宽泛异常捕获，单项失败后继续处理。循环结束后，无论成功数量如何，都会调用 `resolve_recommendation_batch(..., "applied", ...)`。

写入 Redis 的还是请求中的资源 ID，而不是实际成功绑定的资源 ID。因此可能出现：

- 所有资源绑定均失败。
- 批次状态仍为 `applied`。
- 状态机继续进入下一阶段。
- 最终 Agent 实际没有绑定任何推荐资源。

建议：使用数据库事务保证整批原子应用，或者明确支持部分成功，并仅持久化成功资源；完全失败时不得解决该批次。

### 2.6 MCP 安装缺少幂等与补偿

位置：`backend/services/nl2agent_service.py::_install_recommended_mcp`

MCP 安装串联执行创建、健康检查、记录查询、工具发现、工具写入、Redis workflow 更新和推荐移除。中间步骤失败后没有补偿逻辑。

可能结果包括：

- MCP 已经创建，但 workflow 被记录为 `failed`。
- 重试时重复创建 MCP。
- 通过名称查询 MCP 记录时命中旧记录或同名记录。
- 工具发现部分成功，Session State 却没有对应状态。

建议：使用 `recommendation_id + option_id + draft_agent_id` 作为幂等键；服务返回新建 MCP 的稳定 ID，避免按名称反查；为外部创建步骤设计补偿或可恢复的 saga 状态。

### 2.7 Session 创建缺少整体事务或补偿

位置：`backend/services/nl2agent_service.py::start_session`

Session 创建依次执行 draft Agent 创建、Conversation 创建、Catalog 加载和 Redis 写入。后续失败不会删除前面已经创建的数据，重复重试可能积累孤立 draft 和 Conversation。

建议：数据库内操作使用事务；Redis 或远端目录失败时执行明确补偿，或者将 Session 标记为初始化失败并允许幂等恢复。

## 3. 架构与维护性问题

### 3.1 状态机在多个层级重复实现

同一套 NL2AGENT 阶段判断至少存在于：

1. 英文 System Prompt。
2. 中文 System Prompt。
3. `backend/agents/create_agent_info.py` 的 Current Session 摘要。
4. `backend/services/nl2agent_service.py` 的 Card Delivery 阶段校验。
5. `frontend/app/[locale]/chat/streaming/chatStreamFinalMessage.tsx` 的缺失卡片推断。

阶段调整必须同步维护五处实现。当前前端使用“期望卡片集合”，后端使用“唯一当前阶段”，二者语义已经存在漂移风险。

建议：由 Backend 统一计算 typed workflow summary，包括 `current_stage`、`expected_card_types` 和阶段完成条件。Frontend 只消费结果，Prompt 只根据同一份结构化摘要行动。

### 3.2 `nl2agent_service.py` 成为 God Service

位置：`backend/services/nl2agent_service.py`

该文件接近 2000 行，同时承担：

- 默认 Agent seed。
- Session 创建。
- Catalog 装载和脱敏。
- 模型验证。
- MCP 安装和工具发现。
- 本地资源绑定。
- 需求、身份和卡片回执。
- Web Skill 安装。
- Finalization。

职责过多导致异常策略、事务边界和返回类型难以保持一致，也使单元测试大量依赖内部 mock。

建议拆分为：

- Session workflow service。
- Catalog/search service。
- Resource binding service。
- MCP installation service。
- Agent publication service。

### 3.3 启动 Session 时宽泛捕获异常并伪装为空目录

位置：`backend/services/nl2agent_service.py::start_session`

Tool、Skill、Registry、Community 和官方 Skill 加载失败后，大多只记录 warning 并继续使用空数组。数据库、网络或解析故障因此会被用户看到成“没有找到资源”，而不是初始化失败。

此外，默认 NL2AGENT Agent 查询发生任意异常时都可能触发重新 seed，真实数据库故障也可能被误判为 Agent 不存在。

建议区分合法空目录、远端目录不可用、数据库/Redis 故障以及默认 Agent 不存在，并使用明确领域异常终止不完整初始化。

### 3.4 HTTP 状态码依赖异常字符串

位置：`backend/apps/nl2agent_app.py::_session_http_error`

当前代码通过英文错误文本中的关键词判断返回 404 或 409。这种方式容易受文案修改影响，也不符合项目定义的 Service 领域异常到 App HTTP 状态映射规范。

建议增加明确的领域异常类型，例如：

- `Nl2AgentDraftNotFound`
- `Nl2AgentWorkflowConflict`
- `Nl2AgentCatalogUnavailable`
- `Nl2AgentStaleCard`

### 3.5 Finalization 接口保留大量失效参数

位置：

- `backend/consts/model.py::FinalizeAgentRequest`
- `backend/services/nl2agent_service.py::finalize_agent`
- `frontend/components/nl2agent/FinalizeCard.tsx`

接口仍接受模型 ID、Tool ID、Skill ID、名称和资源配置等参数，但当前实现规定这些字段必须被忽略，发布时以数据库和 Redis 的持久化状态为准。

注释仍称 proposal 来自 `nl2agent_finalize_proposal` Skill，与当前由模型直接输出 final card 的流程不一致。

建议删除无效输入字段，或拆分为严格的 proposal 类型，仅允许业务描述、Prompt、Greeting、示例问题和运行参数。

## 4. SDK 与缓存问题

### 4.1 搜索缓存是非线程安全的进程内全局状态

位置：`sdk/nexent/core/tools/nl2agent/_context.py`

SDK 使用模块级字典 `_search_cache` 保存搜索结果：

- 没有锁，并发访问不安全。
- 不同 runtime worker 的结果不一致。
- 进程重启即丢失。
- 删除策略不是可靠 LRU。
- MCP 和本地搜索缓存缺少 Catalog 指纹。

MCP 安装后 Backend 虽然从 Redis Catalog 删除推荐，SDK 仍可能在 TTL 内返回安装前的缓存结果。

建议将 tenant/draft 级搜索缓存迁移到 Redis，并把 Catalog fingerprint 纳入所有搜索缓存键。

### 4.2 `Nl2AgentContext` 包含未生效或误导性的状态

位置：`sdk/nexent/core/tools/nl2agent/_context.py::Nl2AgentContext`

`applied_tool_ids`、`applied_skill_ids`、`applied_mcp_names`、Tool/Skill configs 和 `_searched_queries` 没有从 Backend 权威状态可靠恢复，也没有完整参与搜索过滤或 Agent 构建。

由于 Tool instance 会重建，这些字段会给维护者造成“SDK 会记住已应用资源”的错误印象。

建议删除无效状态，所有已应用和已安装信息统一来自 Backend 注入的不可变 Session Catalog。

## 5. Frontend 质量问题

### 5.1 卡片协议存在多套手写 Schema

同一套卡片协议同时存在于：

- 双语 Prompt YAML 示例。
- SDK 搜索 JSON。
- Backend Pydantic 类型。
- Frontend TypeScript interface。
- `frontend/components/nl2agent/cardValidation.ts` 手写运行时校验。

核心实现中仍存在大量 `Dict[str, Any]`、`Record<string, any>` 和手工字段判断，协议变更很容易只更新部分层级。

建议以 Backend schema/OpenAPI 为源生成 TypeScript 类型，并为卡片建立一套统一、可版本化的 JSON Schema。

### 5.2 卡片被重复解析和校验

最终消息会先执行整条消息的卡片校验，Markdown Renderer 处理 fenced block 时再次校验，随后又调用 `JSON.parse`。同一 payload 可能被解析两到三次，错误语义也可能在整体校验与单卡渲染间产生差异。

建议共享一次解析结果，以 typed card AST 传递给 renderer 和 delivery coordinator。

### 5.3 卡片组件重复实现异步工作流

模型、本地资源、MCP、Skill、需求和身份卡分别维护 loading、register、retry、workflow busy、continuation 和 blockers。

大量分散的 `useEffect` 和 `useState` 容易造成：

- 重复提交。
- 组件卸载后状态更新。
- busy 计数不平衡。
- 跨 conversation/draft 状态污染。
- 自动续跑多次或完全不触发。

建议建立统一的 card lifecycle reducer 或 mutation hook，并把 conversation/draft/message scope 作为强制 key。

状态：已解决。`useNl2AgentCardLifecycle` 统一管理操作互斥、busy 计数、错误与重试、输入 blocker、状态刷新、隐藏续跑和 Card Delivery scope；各卡片只保留自身数据和展示状态。注册失败可按卡片策略保持输入阻塞，成功重试或卸载时统一释放。

### 5.4 前端测试没有覆盖真实交互副作用

位置：`frontend/components/nl2agent/__tests__/nl2agentCards.test.tsx`

现有测试主要检查 React element 和辅助函数，没有完整挂载组件、执行 effect、模拟 API、会话切换和用户点击。Frontend 也没有标准的 `test` script 纳入常规检查链路。

因此以下关键路径缺少有效回归保护：

- 卡片注册竞态。
- Card Delivery 失败重试。
- 自动续跑。
- 历史消息重新挂载。
- conversation/draft 切换。
- workflow busy 和 blocker 清理。

建议使用 React Testing Library 配合请求 mock，补充 DOM 级交互测试，并纳入 `check-all` 或 CI。

## 6. 其他坏味道

### 6.1 Seed 职责重复

Config Service 启动时执行默认 NL2AGENT seed，Session 启动时又尝试 lazy seed。两条路径会掩盖启动阶段错误，并使 Runtime 承担配置初始化职责。

建议只保留 Config Service seed；Runtime 发现默认 Agent 缺失时返回明确初始化错误。

### 6.2 本地个人配置混入功能变更

`.claude/settings.local.json` 包含个人机器的命令权限，与 NL2AGENT 产品功能无关，不应纳入正式功能提交。

### 6.3 测试大量依赖内部 Mock

Backend 测试数量较多，但许多测试直接 mock Service 内部函数。重构内部结构时测试会大面积失效，同时仍不能证明 Redis、数据库和跨层状态流的一致性。

建议保留精细单元测试，同时增加少量真实 Redis/数据库边界的集成测试，重点验证并发更新、幂等和失败恢复。

## 7. 建议整改顺序

### P0：先修复明确正确性缺陷

1. Apply All 假成功。
2. 历史 Card Delivery 回执覆盖当前状态。
3. 前端回执失败后不可重试。
4. 回滚范围没有按 `card_key` 隔离。
5. MCP 重试导致重复安装。

### P1：建立一致的状态和事务边界

1. 将 Redis Session State 更新改为原子操作。
2. 后端统一生成 `current_stage` 和 `expected_card_types`。
3. 为 Session 创建、资源绑定和 MCP 安装建立事务或补偿策略。
4. 使用领域异常替代异常字符串匹配。

### P2：降低维护成本

1. 拆分 `nl2agent_service.py`。
2. 统一生成卡片和 API 类型。
3. 删除过时 Finalize 参数和 SDK 死状态。
4. 将搜索缓存迁移到 Redis 并加入 Catalog fingerprint。
5. 建立统一前端卡片生命周期管理和真实交互测试。

## 8. 总结

当前版本最核心的代码坏味道可以概括为：

> Redis 被当作可整对象覆盖的 JSON 文档；同一状态机跨多个层级重复实现；Frontend 依赖模块级全局变量协调副作用；跨系统安装和绑定流程缺少可靠的事务、幂等与补偿边界。

这些问题已经不只是代码风格或可读性问题，而是会导致状态丢失、阶段误判、重复安装、假成功和流程无法恢复。整改时应先解决数据正确性和并发安全，再进行模块拆分与类型统一。
