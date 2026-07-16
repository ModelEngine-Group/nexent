## 审查结论

相对 `lvnqqsqn`（Git `4e7d9fe1`），当前父 revision `wosmrprl / 604151c6` 共修改 106 个文件，约新增 22,500 行、删除 643 行。NL2AGENT 已经形成较完整的 Backend、SDK、Prompt、Frontend、Redis 状态机与测试体系，但当前版本仍存在明显坏味道，其中至少有：

- 1 个严重租户隔离问题
- 10 余个高优先级状态一致性或功能缺陷
- 多个中低优先级协议、可维护性和测试盲区

基于静态证据，当前实现还不适合直接视为“重构完成”。

## P0：租户隔离

### 1. 可以通过伪造本地推荐批次绑定其他租户的 Tool

证据链：

1. 本地推荐注册接口直接接受前端提交的 `tool_ids`，没有验证这些 ID 是否来自本次搜索或当前租户 Catalog。[nl2agent_session_catalog.py](D:/dev/nexent/backend/agents/nl2agent_session_catalog.py:559)
2. Apply 时只检查 ID 是否属于这个由前端注册的批次。[nl2agent_resource_service.py](D:/dev/nexent/backend/services/nl2agent_resource_service.py:49)
3. `query_tools_by_ids()` 只按 `tool_id` 和删除标记查询，没有 `author == tenant_id` 条件。[tool_db.py](D:/dev/nexent/backend/database/tool_db.py:136)
4. 查询到其他租户的 Tool 后，会用当前租户 ID 创建 ToolInstance。[nl2agent_resource_service.py](D:/dev/nexent/backend/services/nl2agent_resource_service.py:86)
5. Finalization 的资源解析同样没有重新验证 ToolInfo 的 `author`。[nl2agent_service.py](D:/dev/nexent/backend/services/nl2agent_service.py:599)

因此，知道或猜到其他租户 Tool ID 的用户可以构造自己的推荐批次，再把该 Tool 绑定到自己的 Agent。

建议优先修复：

- 所有本地 Tool 查询必须增加 tenant 条件。
- 注册批次时校验 Tool 属于当前 Session Catalog。
- 最好由 Backend/Runtime 保存可信搜索结果令牌，前端只提交令牌而不是自行声明结果集合。
- Publication 再次验证 ToolInfo 租户归属。

## P1：高优先级问题

### 2. Card Delivery 只验证消息元数据，不验证消息里真的存在有效卡片

回执请求只有 `message_id`、`card_type`、状态和可选 `card_key`。[model.py](D:/dev/nexent/backend/consts/model.py:495)

Backend 只检查：

- 消息属于 Conversation
- role 是 assistant
- status 是 completed
- 是最新 assistant 消息
- card type 当前被期待

但没有读取或验证消息正文。[nl2agent_workflow_service.py](D:/dev/nexent/backend/services/nl2agent_workflow_service.py:69)

这意味着错误前端或构造请求可以把一个根本没有卡片、JSON 已截断或 schema 错误的消息标记成 `rendered`。之后 `_card_was_rendered()` 会使状态机停止重新生成卡片，仍可能复现“状态认为卡片完成但用户没有可用卡片”的原始问题。

前端 Ajv 校验不能代替服务端权威验收。

### 3. Backend 的“必须完成资源搜索”门禁可以被空批次绕过

在线批次注册只验证草稿归属，然后存储前端提供的 batch ID、类型和 item keys。[nl2agent_workflow_service.py](D:/dev/nexent/backend/services/nl2agent_workflow_service.py:48)

完成在线配置只要求：

- 存在一个 `mcp` 批次
- 存在一个 `skill` 批次
- 没有 unresolved MCP

空的、自行构造的批次也满足条件。[nl2agent_session_catalog.py](D:/dev/nexent/backend/agents/nl2agent_session_catalog.py:521)

本地批次同样由前端声明 Tool/Skill ID。[nl2agent_session_catalog.py](D:/dev/nexent/backend/agents/nl2agent_session_catalog.py:559)

因此可以不执行三个搜索工具，直接注册假批次并通过 Finalization 门禁。当前所谓“Backend 强制搜索审查”实际只是“Backend 强制客户端声明已审查”。

### 4. MCP 与 Skill 同轮渲染存在注册/回执竞态，并可能永久锁住输入框

Prompt 要求 MCP 和 Skill 都缺失时，在一轮中输出两张卡。状态机在只注册其中一类后，会立即只期待另一类。[nl2agent_workflow.py](D:/dev/nexent/backend/agents/nl2agent_workflow.py:182)

前端每张在线卡分别执行：

1. 注册批次。
2. `setRegistered(true)`。
3. 上报 rendered receipt。

[index.tsx](D:/dev/nexent/frontend/components/nl2agent/index.tsx:44)

如果 MCP 先注册，其回执到达时 Backend 已经只期待 Skill，MCP 回执会被当成 stale card 拒绝。[nl2agent_workflow_service.py](D:/dev/nexent/backend/services/nl2agent_workflow_service.py:99)

更严重的是：

- `registered` 已被提前设为 true。
- “Retry registration”再次调用时会因为 `registered` 为 true 直接返回。
- `retainInputBlockOnError=true` 会继续阻塞输入。

本地卡片也有“先设 registered，再上报回执”的同类不可重试问题。[LocalResourcesCard.tsx](D:/dev/nexent/frontend/components/nl2agent/LocalResourcesCard.tsx:85)

### 5. `[[NL2AGENT_CARD_RETRY]]` 在发送链路中没有被当成自动续跑

公共判断函数同时识别两个隐藏前缀。[nl2agentContinuation.ts](D:/dev/nexent/frontend/lib/chat/nl2agentContinuation.ts:1)

但真正发送消息时只检查：

```ts
autoContinueText?.startsWith(NL2AGENT_AUTO_CONTINUE_PREFIX)
```

[chatInterface.tsx](D:/dev/nexent/frontend/app/[locale]/chat/internal/chatInterface.tsx:425)

所以 Card Retry 会被当成普通发送：

- 输入框为空时直接返回，不触发 Agent Run。
- 输入框非空时可能发送用户输入，而不是 retry text。
- Conversation/draft 防串线检查也不会执行。
- 上层可能把这个“什么都没做”的返回当作续跑成功。

现有测试只验证辅助判断函数识别该前缀，没有覆盖 `handleSend` 集成路径。[nl2agentCards.test.tsx](D:/dev/nexent/frontend/components/nl2agent/__tests__/nl2agentCards.test.tsx:616)

### 6. Prompt 在需求摘要阶段存在直接矛盾

全局规则要求：

> 只生成 `expected_card_types` 中的卡片。

[nl2agent_system_prompt_zh.yaml](D:/dev/nexent/backend/prompts/nl2agent_system_prompt_zh.yaml:24)

但 `requirements_collecting` 又要求五项齐全后输出需求摘要卡。[nl2agent_system_prompt_zh.yaml](D:/dev/nexent/backend/prompts/nl2agent_system_prompt_zh.yaml:29)

与此同时，Evaluator 在 `requirements_collecting` 阶段把 `expected_card_types` 留空。[nl2agent_workflow.py](D:/dev/nexent/backend/agents/nl2agent_workflow.py:160)

所以需求齐全时，摘要卡同时“必须输出”和“禁止输出”。英文 Prompt 存在同样问题。

现有 Prompt 测试主要断言关键词存在，不能发现语义矛盾。[test_prompt_template_utils.py](D:/dev/nexent/test/backend/utils/test_prompt_template_utils.py:199)

### 7. NL2AGENT YAML Prompt 加载失败时会静默退化为普通 Agent Prompt

Prompt 加载捕获所有异常，记录 warning 后返回 `None`。[create_agent_info.py](D:/dev/nexent/backend/agents/create_agent_info.py:190)

返回 `None` 后：

- 不加载 workflow state。
- 不注入 Current Session。
- 使用数据库中的普通 `prompt_template["system_prompt"]`。

[create_agent_info.py](D:/dev/nexent/backend/agents/create_agent_info.py:821)  
[create_agent_info.py](D:/dev/nexent/backend/agents/create_agent_info.py:1024)

这会让 NL2AGENT 再次退化为普通聊天助手，却不会产生明确初始化错误。对于强状态机 Agent，应当 fail closed，而不是 fail open。

### 8. 模型保存存在数据库与 Redis 分裂

模型选择先更新数据库，然后设置 Redis `model_selection_confirmed`。[nl2agent_service.py](D:/dev/nexent/backend/services/nl2agent_service.py:448)

如果 Redis 更新失败：

- 数据库已经保存模型。
- API 返回失败。
- Redis 仍表示模型未确认。
- Runtime 又会根据数据库重新推导 `model_selection_confirmed=true`。[create_agent_info.py](D:/dev/nexent/backend/agents/create_agent_info.py:135)
- Session State API 的 `current_stage` 却来自 Redis Evaluator。[nl2agent_workflow_service.py](D:/dev/nexent/backend/services/nl2agent_workflow_service.py:252)

于是 Runtime、前端和 Redis 会对当前阶段产生不同判断。测试只覆盖正常保存，没有覆盖数据库成功、Redis 失败的窗口。[test_nl2agent_service.py](D:/dev/nexent/test/backend/services/test_nl2agent_service.py:495)

### 9. MCP 重试会忽略用户修正后的 URL、Header、凭据或容器配置

远程 MCP 在找到已有 `mcp_id` 后直接返回，不更新记录。[nl2agent_mcp_service.py](D:/dev/nexent/backend/services/nl2agent_mcp_service.py:320)

```python
if existing_mcp_id is not None:
    return existing_mcp_id
```

容器安装也一样。[nl2agent_mcp_service.py](D:/dev/nexent/backend/services/nl2agent_mcp_service.py:387)

场景：

1. 第一次配置错误，MCP 记录已创建，但健康检查或发现失败。
2. 用户在卡片中修正 URL、Token 或容器参数。
3. Retry 找到旧 `mcp_id`，完全跳过配置更新。
4. 新 Header 可能只临时用于本次 discovery，数据库仍保留旧配置。
5. 后续 Runtime 继续使用错误的持久化配置。

当前 idempotency key 也不包含配置指纹，因此无法区分真正的配置修订。

### 10. 多 MCP Tool 绑定不是事务，Skip 后可能仍保留部分 Tool

`bind_mcp_tools()` 逐个调用独立的 ToolInstance 写入，最后才更新 Redis workflow。[nl2agent_mcp_service.py](D:/dev/nexent/backend/services/nl2agent_mcp_service.py:635)

若第二个 Tool 失败：

- 第一个 Tool 已提交。
- Redis 状态仍然是 `connected`。
- 用户随后可以点击 Skip。
- Skip 只写 `binding_skipped` 和空 `bound_tool_ids`，不会删除已经写入的 ToolInstance。[nl2agent_mcp_service.py](D:/dev/nexent/backend/services/nl2agent_mcp_service.py:693)
- Finalization 会读取该部分绑定的 Tool。

因此持久化资源与 workflow 状态可能互相矛盾。现有测试只绑定单个 Tool，没有覆盖中途失败。[test_nl2agent_service.py](D:/dev/nexent/test/backend/services/test_nl2agent_service.py:758)

### 11. 本地 Tool 的配置参数实际上总被清空

`ToolInfo.params` 的定义是 `List`。[model.py](D:/dev/nexent/backend/consts/model.py:760)

Catalog 也保存该列表。[nl2agent_catalog_service.py](D:/dev/nexent/backend/services/nl2agent_catalog_service.py:92)

但 Apply 时要求它必须是 dict，否则替换成 `{}`。[nl2agent_resource_service.py](D:/dev/nexent/backend/services/nl2agent_resource_service.py:86)

所以所有本地 ToolInstance 最终基本都会保存空参数。需要 API Key、模型、知识库或其他配置的 Tool 会被“成功绑定”，但运行时不可用。

当前本地卡也没有资源配置步骤。Skill 的 `config_schema` 同样只参与 Catalog 传递，没有配置落地流程。

### 12. 在线 Skill 只安装到租户，没有绑定到草稿 Agent

Backend 安装流程只执行租户级 Skill 安装并从 Catalog 删除推荐。[nl2agent_catalog_service.py](D:/dev/nexent/backend/services/nl2agent_catalog_service.py:251)

Frontend 成功后仅把本地状态设为 `installed`。[WebSkillCard.tsx](D:/dev/nexent/frontend/components/nl2agent/WebSkillCard.tsx:47)

没有：

- SkillInstance 绑定接口
- Bind 按钮
- 安装后自动绑定
- Workflow 中的 Skill binding 状态

而 Publication 只读取草稿中已启用的 SkillInstance。[nl2agent_publication_service.py](D:/dev/nexent/backend/services/nl2agent_publication_service.py:95)

因此用户安装在线 Skill 后，最终生成的 Agent 实际不会使用该 Skill。

### 13. Backend 没有统一执行 `allowed_actions` 门禁，历史卡仍可修改后续状态

例如模型选择接口只要求需求已确认，没有要求当前阶段确实是 `model_selection`。[nl2agent_service.py](D:/dev/nexent/backend/services/nl2agent_service.py:456)

身份、MCP 安装和 Skill 安装也主要只验证草稿归属及资源 provenance，不验证当前 `allowed_actions`。

Frontend 对所有完整历史消息继续使用 interactive 卡片模式，只是禁止其重新注册。[chatStreamFinalMessage.tsx](D:/dev/nexent/frontend/app/[locale]/chat/streaming/chatStreamFinalMessage.tsx:518)

`ModelSelectionCard` 的 `saved` 只是组件本地状态，历史卡重新挂载后又会恢复为可保存状态。[ModelSelectionCard.tsx](D:/dev/nexent/frontend/components/nl2agent/ModelSelectionCard.tsx:11)

多标签页或点击历史卡可以：

- 修改已经完成阶段的模型。
- 不重置后续本地、联网、身份确认状态。
- 使最终摘要与早先选择依据不再一致。

## P2：中优先级坏味道

### 14. LLM 生成并控制 `prompt_template_id`

双语 Prompt 的最终卡示例硬编码 `prompt_template_id: 1`。[nl2agent_system_prompt_zh.yaml](D:/dev/nexent/backend/prompts/nl2agent_system_prompt_zh.yaml:87)

Publication 没有查询模板是否存在或是否属于允许范围，直接写入 Agent。[nl2agent_publication_service.py](D:/dev/nexent/backend/services/nl2agent_publication_service.py:133)

这和“持久化状态是权威来源、模型不得编造 ID”的设计原则冲突。建议从 LLM proposal 删除该字段，或只允许服务端选择/验证模板。

### 15. MCP 安装锁固定 5 分钟且没有续租

锁 TTL 为 300 秒。[nl2agent_session_catalog.py](D:/dev/nexent/backend/agents/nl2agent_session_catalog.py:43)

拉取容器镜像、启动容器、健康检查和 Tool discovery 完全可能超过 5 分钟。锁过期后第二个 Worker 可开始相同安装，造成重复容器或重复 MCP 记录。需要 heartbeat/续租或数据库级唯一约束。

### 16. Official Skill 的 ID/名称验证使用 OR，允许不一致组合

只要 `skill_id` 或 `skill_name` 任一匹配 Catalog 就通过。[nl2agent_catalog_service.py](D:/dev/nexent/backend/services/nl2agent_catalog_service.py:192)

随后如果请求中有 `skill_name`，实际安装的是请求名称，而不是刚刚解析出的可信 Catalog 项。[nl2agent_catalog_service.py](D:/dev/nexent/backend/services/nl2agent_catalog_service.py:270)

应该解析出一个 canonical Skill 项，后续只使用该项的 ID/名称；请求同时提供二者时必须一致。

### 17. 中文“原子关键词拆分”名不副实

正则把连续中文整体作为一个 token。[`_context.py`](D:/dev/nexent/sdk/nexent/core/tools/nl2agent/_context.py:39)

例如“读取文档生成演示文稿”不会拆成“读取、文档、生成、演示文稿”，除非模型主动插入空格。当前正确性依赖 Prompt，而不是搜索模块本身。

另外 MCP normalization 丢弃了 tags，因此虽然通用评分器支持 tags，MCP 实际只按名称和描述搜索。[search_web_mcps_tool.py](D:/dev/nexent/sdk/nexent/core/tools/nl2agent/search_web_mcps_tool.py:245)

### 18. 搜索结果向模型和 Redis传递了过多配置结构

本地 Tool Catalog 保留完整 `params`，Skill Catalog 保留完整 `config_schema`。[nl2agent_catalog_service.py](D:/dev/nexent/backend/services/nl2agent_catalog_service.py:92)

评分器通过 `{**candidate}` 把完整候选返回给 Tool Observation。[`_context.py`](D:/dev/nexent/sdk/nexent/core/tools/nl2agent/_context.py:147)

这些字段当前卡片不使用，Apply 也会重新查询数据库。结果是：

- 增加 Redis、模型上下文和卡片 JSON 体积。
- 增大卡片被截断概率。
- 把 Catalog 内部结构耦合到 Prompt。
- 形成未来配置值泄漏风险。

目前没有证据表明这里已经包含真实 secret，所以不应描述成已发生凭据泄漏。

### 19. Redis 的幂等操作仍然每次增加 revision 并写回

统一 mutator 无论状态是否变化都会执行：

```python
state.revision += 1
```

[nl2agent_session_catalog.py](D:/dev/nexent/backend/agents/nl2agent_session_catalog.py:211)

重复注册和重复回执会制造无意义 revision、CAS 冲突、TTL 刷新和前端刷新。应让 mutator 返回 `changed`，真正变化时才写入。

### 20. API 异常映射不一致

部分接口通过结构化 `_session_http_error()` 返回 409/404/503；但 Session Start、Apply Local 和 Install Web Skill 仍把所有 `AgentRunException` 映射为 500。[nl2agent_app.py](D:/dev/nexent/backend/apps/nl2agent_app.py:154)

本地 register/skip 甚至没有本地异常映射。[nl2agent_app.py](D:/dev/nexent/backend/apps/nl2agent_app.py:216)

这会使前端无法区分：

- 用户操作冲突
- stale card
- Catalog 不可用
- 真正服务端故障

### 21. “Canonical Schema”仍过于宽松，且存在重复解析

Card Schema 大量使用 `additionalProperties: true`，MCP option 只强制 `option_id` 和 `type`。[nl2agent-card.schema.json](D:/dev/nexent/contracts/nl2agent-card.schema.json:61)

Frontend 已经通过 Ajv 做一次完整消息校验，但 Markdown Renderer 又对每张卡调用 `parseNl2AgentCard()` 重新解析。[chatStreamFinalMessage.tsx](D:/dev/nexent/frontend/app/[locale]/chat/streaming/chatStreamFinalMessage.tsx:108) [index.tsx](D:/dev/nexent/frontend/components/nl2agent/index.tsx:193)

因此“单次解析生成 typed AST”的目标尚未真正实现。

### 22. 核心文件仍然过大，测试也集中在单体文件

当前主要文件规模：

- `backend/services/nl2agent_service.py`：1161 行
- `test/backend/services/test_nl2agent_service.py`：2391 行
- `frontend/components/common/markdownRenderer.tsx`：1471 行
- `frontend/components/nl2agent/WebMcpCard.tsx`：519 行

虽然已拆出六个服务，但 facade 仍承担大量依赖装配、模型解析、资源展示、seed、兼容入口和错误转换。测试集中在巨型文件中，导致失败场景难以系统组织。

## 现有测试的主要盲区

静态扫描没有发现以下路径的测试：

- 本地 Tool 跨租户绑定。
- 伪造空 MCP/Skill 批次绕过搜索。
- Backend 回执与真实消息正文不一致。
- MCP/Skill 双卡并发注册与回执顺序。
- `CARD_RETRY` 到 `handleSend` 的完整集成链路。
- 模型数据库提交成功、Redis 更新失败。
- MCP 使用修正后的 URL、Token 或容器配置重试。
- 多 MCP Tool 绑定到一半失败并随后 Skip。
- 在线 Skill 安装后是否存在 SkillInstance。
- Prompt 规则之间的语义一致性。

当前 Prompt 测试主要是 substring assertions；Frontend 主测试也有大量直接检查 React element props 的浅层测试，而不是完整挂载后的并发 effect 和网络顺序。

## 已经做得较好的部分

本轮变更也包含一些明确改进：

- Redis workflow state 使用严格 v2 Pydantic 模型和 `WATCH/MULTI` CAS。
- Session 初始化具备数据库/Redis 补偿。
- 本地 Apply 的 Tool/Skill 数据库写入已共享事务。
- MCP recommendation 从可信 Redis Catalog 解析，并对 marketplace secret defaults 做了脱敏。
- Finalization 主要依赖数据库中的模型与资源，而不是 LLM 提交的 Tool/Skill ID。
- Frontend 已引入 Ajv、Vitest、RTL 和 jsdom，方向正确。

问题主要集中在“跨存储一致性、服务端可信边界、卡片副作用时序和缺少失败路径测试”。

## 验证边界

本次严格按只读要求执行：

- 没有修改文件。
- 没有启动或重启服务。
- 没有执行可能生成缓存、快照或构建产物的测试命令。
- 最终 `jj status` 为 clean。
- 结论来自 revision diff、源码调用链、Schema、Prompt 和现有测试的交叉静态分析。

并发竞态和外部 MCP 行为仍建议后续通过定向自动化测试复现，但上述多数问题已经能够从代码路径直接成立。
