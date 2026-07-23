# NL2AGENT 完整设计方案

> 文档状态：与当前 NL2AGENT 实现同步的设计说明。
> 适用范围：当前仓库中的 NL2AGENT 会话、工作流、卡片、资源搜索、外部安装和 Draft Finalize 全链路。
> 维护原则：新增阶段、卡片、持久化字段、资源类型或外部副作用时，必须同时更新本文、契约、迁移脚本和对应测试。

## 1. 目标、范围与非目标

### 1.1 目标

NL2AGENT 是嵌入 Agent 配置页的对话式 Agent Builder。用户用自然语言描述目标，系统通过受控的多轮对话完成：

1. 需求收集和显式确认；
2. LLM 模型选择；
3. 当前租户中可用 Tool 和 Skill 的搜索、审查和绑定；
4. 官方或社区 MCP、Skill 的在线搜索、配置、安装和绑定；
5. Agent 身份和提示词生成；
6. 最终检查并写入 Draft Agent。

会话必须支持刷新恢复、历史只读展示、并发写入保护、外部安装重试和安全失败。Finalize 只完成 Draft 配置，不创建发布版本。

### 1.2 非目标

- NL2AGENT 不替代普通聊天，不出现在普通 Agent 列表和普通 Conversation 历史列表中。
- LLM 不直接写入 Agent、Tool、Skill 或 MCP 数据库。
- LLM 不决定任意资源 ID、租户 ID、用户 ID、凭据或 MCP URL。
- NL2AGENT 不在 Finalize 阶段创建 Agent version 或发布版本。
- 浏览器 LocalStorage、Redis 或前端内存不是会话状态的权威来源。

### 1.3 设计原则

| 原则 | 约束 |
|---|---|
| PostgreSQL 权威 | Session、工作流、目录快照和安装操作均以 PostgreSQL 为准 |
| 显式阶段门禁 | 只有当前阶段允许的动作和卡片可以推进工作流 |
| 可信推荐 | 资源卡片必须匹配 SDK 搜索工具产生的 recommendation batch |
| 最小信任输入 | 前端动作只提交用户选择，后端重新读取并验证权威状态 |
| 外部 I/O 与事务分离 | 数据库连接不跨越网络、容器或市场安装调用 |
| 幂等和可恢复 | 重复请求、超时、进程崩溃和 lease 接管都必须有确定结果 |
| 租户隔离 | 所有读取、写入和外部操作都绑定完整的会话身份 |
| 契约先行 | 卡片 Schema、OpenAPI、Pydantic 和 TypeScript 类型保持同步 |

## 2. 系统架构

### 2.1 端到端数据流

~~~text
Agent 配置页
    │
    ├─ start session
    │      └─ Draft Agent + Builder Conversation + PostgreSQL Session
    │
    └─ Nl2AgentEmbeddedChat
             │
             ├─ 复用 NewChat 流式运行时和历史适配器
             ├─ /agent/run 执行 nl2agent runner
             ├─ SDK 搜索工具读取 Session catalog
             ├─ LLM 输出 NL2AGENT fenced JSON card
             ├─ 前端解析、校验并渲染 Card
             └─ Card action / delivery → /nl2agent/session/*
                                      │
                                      ├─ stage 校验
                                      ├─ recommendation proof 校验
                                      ├─ PostgreSQL revision CAS
                                      └─ 外部安装 operation
                                                 │
                                                 ├─ MCP/Skill adapter
                                                 ├─ lease / heartbeat
                                                 ├─ checkpoint / replay
                                                 └─ Draft resource binding
                                      │
                                      └─ Finalize → Draft Agent 持久化
~~~

### 2.2 分层和实现位置

| 层 | 责任 | 主要实现位置 |
|---|---|---|
| HTTP 边界 | 鉴权、参数解析、响应模型、异常映射 | backend/apps/nl2agent_app.py |
| 运行时编排 | 组装依赖、校验 Draft、调用领域服务 | backend/services/nl2agent_runtime_service.py |
| Session 生命周期 | 创建、解析、恢复、放弃、保留和清理 | backend/services/nl2agent_session_service.py、backend/services/nl2agent_session_lifecycle_service.py |
| 工作流模型 | 状态 Schema、阶段选择、允许动作 | backend/agents/nl2agent_workflow.py |
| 工作流目录 | 状态转移、推荐 proof、卡片 delivery、安装状态 | backend/agents/nl2agent_session_catalog.py |
| Session 存储 | JSONB 解析、revision CAS、目录读取 | backend/agents/nl2agent_session_store.py |
| 数据库 Repository | Session、安装 operation、Conversation 元数据 | backend/database/nl2agent_session_db.py、backend/database/nl2agent_installation_db.py、backend/database/conversation_db.py |
| 本地资源 | Tool/Skill 推荐和绑定 | backend/services/nl2agent_resource_service.py |
| 在线目录 | MCP/Skill 目录规范化、配置和安装 | backend/services/nl2agent_catalog_service.py |
| MCP 外部操作 | 连接、发现工具、安装、绑定 | backend/services/nl2agent_mcp_service.py |
| Finalize | 最终校验和 Draft 写入 | backend/services/nl2agent_publication_service.py |
| 安全 | MCP URL、DNS、重定向和网络固定 | backend/services/nl2agent_mcp_url_security.py |
| SDK 工具 | 本地、MCP、Skill 搜索及可信结果回调 | sdk/nexent/core/tools/nl2agent/ |
| 卡片契约 | JSON Schema、服务端和前端校验 | contracts/nl2agent-card.schema.json、backend/utils/nl2agent_card_validation.py、frontend/components/nl2agent/cardValidation.ts |
| 前端协调 | Session 状态、卡片生命周期、自动续聊和重试 | frontend/components/nl2agent/Nl2AgentWorkflowContext.tsx |

## 3. 核心对象和不变量

### 3.1 对象定义

| 对象 | 含义 | 稳定标识 |
|---|---|---|
| Builder Agent | 每个租户提供的内部 nl2agent runner | tenant_id + runner_agent_id |
| Draft Agent | 用户正在生成的目标 Agent | tenant_id + draft_agent_id |
| Builder Conversation | 只服务于一次 Builder session 的隐藏对话 | tenant_id + conversation_id |
| NL2AGENT Session | Draft、runner、Conversation、目录和工作流的持久绑定 | tenant_id + draft_agent_id |
| Recommendation Batch | 一次搜索结果及其可应用资源集合 | recommendation_batch_id |
| Installation Operation | 一次外部 MCP/Skill 安装的幂等操作 | operation_id + installation_key |
| Card Delivery | 某条完整 assistant message 中某类卡片的显示结果 | message_id + card_type + card_key |

Session 的完整身份由以下五个字段组成，任何跨租户或跨 Draft 的读取都必须同时匹配：

~~~text
tenant_id
user_id
runner_agent_id
draft_agent_id
conversation_id
~~~

### 3.2 必须保持的不变量

1. 同一租户的一个 Draft Agent 至多有一个未删除 Session。
2. Session 的 draft_agent_id、runner_agent_id、conversation_id 必须互相绑定，不能由请求体覆盖。
3. workflow_state.revision 必须等于表列 workflow_revision。
4. 只有 status=active 的 Session 可以执行工作流写操作。
5. 已完成或只读 Session 可以读取卡片和状态，但不能执行副作用动作。
6. 所有推荐资源必须来自当前 Session 的不可变目录或可信搜索批次。
7. 外部 I/O 不得持有数据库事务连接。
8. operation 完成后重复请求只能重放相同结果，不能创建重复资源。
9. 凭据、Authorization header、secret 字段和原始敏感配置不能进入目录、日志、响应或 operation result。
10. Finalize 前必须重新验证模型、资源、工作流和 Draft 所有权。

## 4. Agent Builder 和 Session 生命周期

### 4.1 Builder Agent 初始化

Builder Agent 的默认定义位于：

- backend/agents/default_agents/nl2agent.json
- backend/prompts/nl2agent_system_prompt_zh.yaml
- backend/prompts/nl2agent_system_prompt_en.yaml

初始化和租户级补全由 backend/services/nl2agent_seed_service.py 负责。默认内置工具必须是以下三个：

| Tool 名称 | SDK 实现 | 作用 |
|---|---|---|
| nl2agent_search_local_resources | sdk/nexent/core/tools/nl2agent/search_local_resources_tool.py | 搜索租户内 Tool 和 Skill |
| nl2agent_search_web_mcps | sdk/nexent/core/tools/nl2agent/search_web_mcps_tool.py | 搜索注册表和社区 MCP |
| nl2agent_search_web_skills | sdk/nexent/core/tools/nl2agent/search_web_skills_tool.py | 搜索官方或在线 Skill |

seed_nl2agent_builtin_tools 位于 backend/database/tool_db.py。Builder Agent 缺失或不完整时，start session 会先补齐其模型、提示词和内置工具。

### 4.2 启动 Session

HTTP 入口为 POST /nl2agent/session/start，实现在 backend/apps/nl2agent_app.py；业务入口为 backend/services/nl2agent_runtime_service.py 的 start_session；事务编排在 backend/services/nl2agent_session_service.py。

启动步骤：

1. 从鉴权上下文获取 user_id、tenant_id、language。
2. 有界执行过期 Session 清理，不因清理失败阻断新会话。
3. 查找或创建当前租户的 Builder Agent。
4. 读取并规范化本次 Session 的目录快照。
5. 在一个数据库事务内创建：
   - Draft Agent；
   - 隐藏 Builder Conversation；
   - 初始 Nl2AgentWorkflowState；
   - nl2agent_session_t。
6. 事务提交后返回 runner agent、Draft agent 和 conversation 标识。
7. 前端使用返回的 conversation_id 打开嵌入式聊天。

Session 创建失败时，session service 执行补偿删除和审计日志；目录加载和外部市场读取不在创建事务中执行。

### 4.3 配置页恢复

配置页通过 GET /nl2agent/session/by-agent/{draft_agent_id} 查询 Session。浏览器丢失 conversation ID 时，可以通过 GET /nl2agent/session/by-conversation/{conversation_id} 恢复。

恢复逻辑位于：

- backend/services/nl2agent_session_lifecycle_service.py
- backend/database/nl2agent_session_db.py
- frontend/services/nl2agentService.ts
- frontend/app/[locale]/agents/page.tsx

恢复只返回公开 Session 摘要，不把完整 workflow_state 或 catalog 直接暴露给列表接口。真正的状态读取由 GET /nl2agent/session/{agent_id}/state 完成，并再次执行租户和用户所有权检查。

### 4.4 完成、恢复编辑和放弃

- Finalize 成功后 Session 状态为 completed，聊天记录保留为只读历史。
- POST /nl2agent/session/{agent_id}/resume 只允许从 final_review 恢复，进入 revision_mode。
- revision_mode 下，用户修改意图会被路由到对应卡片类别，不重新创建 Builder Conversation。
- POST /nl2agent/session/{agent_id}/abandon 将 active Session 标记为 abandoned。
- 删除 Conversation 时，conversation_management_service 会先调用 abandon_session_by_conversation。
- 删除 Draft 时，agent_service 会软删除关联 Session 和隐藏 Conversation。

实现位置：

- backend/services/nl2agent_session_lifecycle_service.py
- backend/services/conversation_management_service.py
- backend/services/agent_service.py
- backend/database/nl2agent_session_db.py

### 4.5 清理和保留

cleanup_expired_sessions 位于 backend/services/nl2agent_session_lifecycle_service.py，由 Session start 机会性调用，也可以由部署任务调用。

保留策略由 backend/consts/const.py 控制：

- NL2AGENT_ACTIVE_RETENTION_DAYS：长期未更新 active Session 的处理期限；
- NL2AGENT_ABANDONED_RETENTION_DAYS：abandoned Session 清理期限；
- NL2AGENT_CLEANUP_BATCH_SIZE：单次清理上限。

completed Session 属于 Draft 的生成历史，不按年龄单独清理，随 Draft Agent 删除。

## 5. 数据模型和数据库迁移

### 5.1 nl2agent_session_t

表定义位于 deploy/sql/migrations/v2.4.0_0722_add_nl2agent.sql，并同步到 deploy/sql/init.sql。

| 列 | 说明 |
|---|---|
| session_id | 数据库主键 |
| tenant_id / user_id | 所有权和审计主体 |
| runner_agent_id | 内部 Builder Agent |
| draft_agent_id | 目标 Draft Agent |
| conversation_id | 隐藏 Builder Conversation |
| status | active、completed、abandoned |
| workflow_schema_version | 状态 Schema 版本 |
| workflow_revision | CAS revision |
| session_catalogs | 不可变目录 JSONB |
| workflow_state | Pydantic 状态 JSONB |
| create_time / update_time | 生命周期时间 |
| created_by / updated_by | 审计字段 |
| delete_flag | 软删除标识 |

数据库约束：

- tenant_id + draft_agent_id 唯一；
- tenant_id + conversation_id 唯一；
- status 只能是 active、completed、abandoned；
- workflow_state.revision 必须等于 workflow_revision；
- tenant_id 上对活动 nl2agent Builder 建立部分唯一索引。

Repository 实现位于 backend/database/nl2agent_session_db.py，状态解析和 CAS 包装位于 backend/agents/nl2agent_session_store.py。

### 5.2 nl2agent_installation_operation_t

| 列 | 说明 |
|---|---|
| operation_id | 操作主键 |
| tenant_id / user_id | 操作所有权 |
| runner_agent_id / draft_agent_id / conversation_id | 完整 Session 身份 |
| installation_key | 同一资源的幂等键 |
| request_fingerprint | 配置请求指纹 |
| resource_type | mcp 或 skill |
| status | pending、running、completed、failed |
| checkpoint | 不含秘密的中间进度 |
| attempt | 重试次数 |
| lease_owner / lease_expires_at | worker 租约 |
| result | 脱敏结果引用 |
| error | 脱敏错误结构 |
| create_time / update_time / audit fields | 审计和软删除 |

Repository 位于 backend/database/nl2agent_installation_db.py。相同 tenant、Draft、installation_key 的请求使用 PostgreSQL advisory transaction lock 和行锁完成 claim、重放或接管。

### 5.3 Conversation 消息元数据

conversation_message_t 新增：

- message_type：默认为 chat，用户动作使用 nl2agent_action；
- message_metadata：保存结构化动作和恢复所需的非秘密元数据。

实现位置：

- deploy/sql/migrations/v2.4.0_0722_add_conversation_message_metadata.sql
- deploy/sql/init.sql
- backend/database/db_models.py
- backend/database/conversation_db.py
- backend/services/conversation_management_service.py
- frontend/app/[locale]/newchat/adapter/conversation-thread-list-adapter.tsx

普通历史列表会过滤或特殊展示 nl2agent_action，避免把内部动作误当作普通用户聊天。

### 5.4 迁移行为

NL2AGENT 迁移会：

1. 软删除旧 Session 绑定的内部 Conversation 和消息；
2. 删除旧的 catalog 表和旧安装表；
3. 创建新的权威 Session 和 installation operation 表；
4. 清理同租户重复的 nl2agent Builder；
5. 创建活动 Builder 的租户级唯一索引。

迁移测试位于 deploy/tests/test_sql_migrations.sh 和 test/deploy/test_local_sql_migrations.py。

## 6. 工作流状态机

### 6.1 状态 Schema

模型和阶段定义位于 backend/agents/nl2agent_workflow.py，当前 WORKFLOW_SCHEMA_VERSION 为 2。

| 字段 | 含义 |
|---|---|
| schema_version | 拒绝旧版本或未知版本 |
| revision | 工作流写入版本 |
| revision_mode | 是否处于定向修订路由 |
| conversation_id | 当前 Builder Conversation |
| requirements_review | 需求摘要、状态和 fingerprint |
| model_selection_confirmed | 是否完成主模型选择 |
| recommendations | local、mcp、skill 批次及应用状态 |
| identity_confirmed | 是否完成显示名称确认 |
| mcp_workflows | 每个 MCP 的安装和工具绑定状态 |
| online_installations | 在线资源 operation 引用 |
| online_configuration_confirmed | 在线资源配置是否完成 |
| card_delivery | 各卡片类型的最新渲染回执 |

集合字段默认上限为 100，card_delivery 上限为 7。Pydantic 使用 extra=forbid，非法字段和旧状态不会静默迁移。

### 6.2 阶段和门禁

| 阶段 | 期望卡片 | 允许的主要动作 | 进入下一阶段的条件 |
|---|---|---|---|
| requirements_collecting | 无或需求摘要 | clarify_requirements、render_requirements_summary | 五项需求事实齐全并展示摘要 |
| requirements_confirmation | requirements_summary | confirm_requirements、revise_requirements | 用户通过卡片确认并匹配 fingerprint |
| model_selection | model_selection | select_models | 主模型存在且属于可用 LLM |
| local_resource_search | local_resources | search_local_resources | 本地搜索批次已可信注册 |
| local_resource_review | local_resources | apply_local_resources、skip_local_resources | 批次已应用或明确跳过 |
| online_resource_search | web_mcp、web_skill 中缺失项 | search_online_resources | 需要的在线目录批次全部注册 |
| online_resource_review | web_mcp、web_skill | configure_online_resources、complete_online_configuration | MCP/Skill 已配置，MCP 工具无未决绑定 |
| agent_identity | agent_identity | save_identity | 显示名称已保存 |
| final_review | final_review | publish_agent | Finalize 所需所有前置检查通过 |
| revision_routing | 用户指定的一个卡片类别 | 需求、模型、本地、在线、身份或最终审查动作 | 当前修改完成并重新进入对应阶段 |

阶段计算由 evaluate_workflow 和 _select_stage 完成。业务层先调用 assert_workflow_action_allowed，再调用具体领域服务。

### 6.3 状态写入和 CAS

所有状态修改必须遵循以下步骤：

~~~text
1. 按完整 Session 身份读取数据库行
2. 校验 status=active 和 schema_version
3. 解析 Pydantic workflow_state
4. 计算当前阶段和允许动作
5. 执行一个纯内存 mutator
6. 再次执行 Pydantic 校验和容量校验
7. revision 加一
8. UPDATE ... WHERE tenant_id/draft_agent_id AND workflow_revision=expected_revision
9. 影响行数为 0 时重新读取并有限重试
~~~

实现位置：

- backend/agents/nl2agent_session_store.py 的 mutate_session_state；
- backend/database/nl2agent_session_db.py 的 update_nl2agent_workflow_state；
- backend/agents/nl2agent_session_catalog.py 的各类 mutate 函数。

CAS 重试次数由 CAS_MAX_RETRIES 控制。超过上限时抛出 Nl2AgentStateConflictError，由 HTTP 层映射为工作流冲突。

### 6.4 需求修订语义

需求字段固定为：

- goal
- audience_or_scenario
- primary_input
- expected_output
- key_constraints

register_requirements_summary 会做 Unicode 规范化、空白归一化和 SHA-256 fingerprint。聊天文本只负责解释用户意图，真正确认必须使用 requirements/confirm endpoint 和当前 fingerprint。

意图分类和修订合并位于 backend/agents/nl2agent_session_catalog.py。

## 7. 运行时、Prompt 和 SDK 工具

### 7.1 运行时组装

普通聊天仍通过 POST /agent/run 执行，不创建专用聊天 endpoint。backend/services/agent_service.py 在 AgentRequest 中识别有效 draft_agent_id，并将其传递给 backend/agents/create_agent_info.py。

create_agent_info.py 负责：

1. 解析当前 Draft 的模型和模型容量；
2. 加载 NL2AGENT system prompt；
3. 读取完整 Session 状态和目录；
4. 创建 Nl2AgentContext；
5. 注入可信搜索结果回调；
6. 将当前阶段、允许卡片和允许动作放入模型上下文；
7. 对远程 MCP 连接应用 NL2AGENT 安全 client factory。

runtime facade 的依赖组装位于 backend/services/nl2agent_runtime_service.py。

### 7.2 Prompt 规则

Prompt 文件位于 backend/prompts/nl2agent_system_prompt_zh.yaml 和 backend/prompts/nl2agent_system_prompt_en.yaml，加载辅助函数位于 backend/utils/prompt_template_utils.py。

Prompt 必须要求模型：

- 使用当前 Session 的 draft_agent_id；
- 只执行 allowed_actions 中的工具动作；
- 只输出 expected_card_types 允许的卡片；
- 等待显式需求确认和资源应用动作；
- 原样复制搜索工具 Observation，不重建推荐数组；
- 不在聊天中收集 MCP secret、header、JSON 或容器配置；
- 在卡片无法验证时停止猜测并要求重新加载或重试。

### 7.3 SDK 搜索上下文

共享上下文位于 sdk/nexent/core/tools/nl2agent/_context.py，包含：

- agent_id、draft_agent_id、tenant_id、user_id、language；
- requirements_confirmed；
- tool_catalog、skill_catalog；
- registry_results、community_results、official_skills；
- record_search_result 回调。

搜索工具不能直接访问数据库或环境变量，所有目录和配置由 Backend 通过参数注入，符合 SDK 不读取环境变量的约束。

### 7.4 三个搜索工具

| 工具 | 实现 | 搜索范围 | 持久化结果 |
|---|---|---|---|
| local resources | search_local_resources_tool.py | 当前租户 Tool、Skill 和本地 MCP 工具 | local recommendation batch |
| web MCP | search_web_mcps_tool.py | Registry、Community MCP | mcp recommendation batch |
| web Skill | search_web_skills_tool.py | Official/online Skill | skill recommendation batch |

搜索工具负责关键词规范化、去重、评分和 batch ID 生成；Backend 的 session catalog 负责把结果写入权威工作流状态。

## 8. Catalog、推荐和信任证明

### 8.1 Session catalog

catalog 加载位于 backend/services/nl2agent_catalog_service.py，保存字段由 backend/agents/nl2agent_session_store.py 的 CATALOG_KEYS 定义：

- tool_catalog
- skill_catalog
- registry_results
- community_results
- official_skills

市场数据进入 Session 前必须经过规范化和敏感字段脱敏。MCP 元数据脱敏函数位于 nl2agent_catalog_service.py，Tool 默认参数脱敏位于 nl2agent_resource_service.py。

### 8.2 推荐批次

RecommendationBatch 记录：

- resource_type：local、mcp、skill；
- status：searched、presented、applying、applied、skipped、completed；
- tool_ids、skill_ids 或 item_keys；
- applied_tool_ids、applied_skill_ids；
- 相关 operation_id。

批次的注册、解析、应用锁和完成状态由 backend/agents/nl2agent_session_catalog.py 管理。

### 8.3 可信 proof 校验

服务端在以下位置重新核对卡片内容：

- backend/utils/nl2agent_card_validation.py：Schema、Draft ID、卡片数量、批次资源集合；
- backend/services/nl2agent_workflow_service.py：在线批次注册和卡片 delivery；
- backend/services/nl2agent_summary_service.py：最终资源引用和来源；
- backend/services/nl2agent_resource_service.py：本地资源应用前的租户和参数校验。

对本地卡片，tool_ids 和 skill_ids 必须与批次完全相等；对 MCP/Skill 卡片，item_keys 必须与批次完全相等。卡片不能增删、替换或重排成另一组资源后直接应用。

## 9. 卡片协议和消息交付

### 9.1 卡片标签映射

共享 Schema 位于 contracts/nl2agent-card.schema.json，前端同步副本位于 frontend/contracts/generated/nl2agent-card.schema.json。

| Fence 标签 | 逻辑类型 | 前端组件 | 是否需要 delivery |
|---|---|---|---|
| nl2agent-requirements-summary | requirements_summary | RequirementsSummaryCard.tsx | 是 |
| nl2agent-model-selection | model_selection | ModelSelectionCard.tsx | 否 |
| nl2agent-local-resources | local_resources | LocalResourcesCard.tsx | 是 |
| nl2agent-web-mcp | web_mcp 单项 | WebMcpCard.tsx | 是 |
| nl2agent-web-mcps | web_mcp 列表 | WebMcpCard.tsx | 是 |
| nl2agent-web-skill | web_skill 单项 | WebSkillCard.tsx | 是 |
| nl2agent-web-skills | web_skill 列表 | WebSkillCard.tsx | 是 |
| nl2agent-agent-identity | agent_identity | AgentIdentityCard.tsx | 否 |
| nl2agent-finalize | final_review | FinalizeCard.tsx | 否 |

单数和复数在线标签是协议兼容别名，最终仍映射到 7 个逻辑卡片类型。

### 9.2 Schema 和身份校验

前端使用 AJV，后端使用 jsonschema Draft 7。校验内容包括：

- JSON 是否为对象；
- 卡片类型是否与 fence 标签一致；
- required、类型、长度和 additionalProperties；
- agent_id 是否缺失或与当前 Draft 不一致；
- 单卡标签不能携带 items，列表标签必须携带 items；
- 同一 assistant message 不得重复输出同一逻辑卡片；
- 在线和本地结果必须带 recommendation_batch_id；
- 推荐内容必须匹配 trusted search batch。

当调用方已有 Session-scoped trustedDraftAgentId 时，卡片可以不重复携带 agent_id，由当前 Session 注入；如果显式携带，则所有 agent_id 必须一致。

### 9.3 流式渲染和 delivery

前端实现：

- frontend/components/nl2agent/Nl2AgentFenceRenderer.tsx：识别完成状态、消息 ID、最新消息和只读状态；
- frontend/components/nl2agent/cardValidation.ts：解析和 AJV 校验；
- frontend/components/nl2agent/index.tsx：语言标签到卡片组件的注册表；
- frontend/components/nl2agent/Nl2AgentWorkflowContext.tsx：delivery claim、成功/失败记录和 continuation；
- frontend/components/nl2agent/finalMessageCardDelivery.ts：历史消息中的可交互卡片判定。

流式阶段只显示占位卡片。只有同时满足以下条件才允许副作用：

1. assistant message 已完成；
2. 消息是当前会话最新 assistant message；
3. 消息 ID 已解析为持久化 message_id；
4. Session 是 active；
5. 卡片 Draft ID 和当前 scope 一致；
6. 当前卡片未被 delivery claim 过。

后端 POST /nl2agent/session/{agent_id}/card-delivery 会再次检查：

- message_id 是否属于当前 Conversation；
- message 是否已完整持久化；
- 是否为最新合法 assistant message；
- message 中是否恰好有一张对应卡片；
- 卡片是否通过服务端 Schema 和 batch proof。

### 9.4 用户动作和自动续聊

卡片动作使用 frontend/lib/chat/nl2agentContinuation.ts 定义的 action 类型。用户动作会作为 message_type=nl2agent_action 的结构化消息保存，并同时带有 displayText，便于历史恢复。

成功的卡片动作返回 chat_injection_text，前端由 WorkflowProvider 自动追加隐藏 continuation。失败的卡片渲染返回 retry instruction，最多执行有限次数的自动重试。

以下哨兵文本必须在实时流和历史恢复中被过滤或特殊处理：

- [[NL2AGENT_AUTO_CONTINUE]]
- [[NL2AGENT_CARD_RETRY]]

哨兵只表示“重新读取权威状态”，不表示阶段已经完成，模型必须重新读取 Current Session。

### 9.5 历史和只读视图

已完成 Session、旧消息、分享页和普通 Conversation 历史只能显示卡片摘要，不允许：

- 自动注册推荐批次；
- 自动安装 MCP/Skill；
- 修改 Session；
- 触发 continuation；
- 发送 secret 或表单配置。

历史过滤和动作消息适配位于 frontend/app/[locale]/newchat/adapter/conversation-thread-list-adapter.tsx。

## 10. 各资源工作流

### 10.1 模型选择

入口：PUT /nl2agent/session/{agent_id}/models。

后端：

- 请求模型：backend/consts/model.py 的 Nl2AgentModelSelectionRequest；
- 编排：backend/services/nl2agent_runtime_service.py 的 select_models；
- 可用模型校验：backend/services/nl2agent_summary_service.py；
- Draft 模型字段写入：backend/database/agent_db.py；
- 状态标记：backend/agents/nl2agent_session_catalog.py。

Finalize 时会再次检查 primary model 是否存在于 model_ids，且仍属于当前租户可用 LLM。

### 10.2 本地 Tool/Skill

流程：

1. 当前阶段允许 search_local_resources；
2. SDK 从 Session catalog 搜索，写入 local recommendation batch；
3. LLM 原样输出 local resources 卡片；
4. 前端注册卡片并等待用户“全部应用”或“跳过”；
5. 后端确认 batch proof、租户资源、静态配置字段和 secret；
6. 在 Draft 上绑定 Tool/Skill；
7. 标记 batch applied 或 skipped。

实现位置：

- SDK：sdk/nexent/core/tools/nl2agent/search_local_resources_tool.py；
- 业务：backend/services/nl2agent_resource_service.py；
- 状态：backend/agents/nl2agent_session_catalog.py；
- 前端：frontend/components/nl2agent/LocalResourcesCard.tsx。

Tool 参数只允许静态配置字段；敏感默认值使用掩码，不把现有 secret 回显到卡片或响应。

### 10.3 在线推荐

在线推荐卡片先由 SDK 搜索产生，再由前端通过 POST /nl2agent/session/{agent_id}/online-recommendations/register 注册卡片中的 batch 和 item keys。

实现位置：

- SDK：search_web_mcps_tool.py、search_web_skills_tool.py；
- 注册：backend/services/nl2agent_workflow_service.py；
- 编排：backend/services/nl2agent_runtime_service.py；
- 前端：frontend/components/nl2agent/index.tsx 的 OnlineRecommendationGroup。

MCP 和 Skill 可以分别搜索；如果两个目录都缺失，Prompt 要求在同一工具步骤中各执行一次搜索，但分别输出各自卡片。

### 10.4 MCP 安装和工具绑定

MCP 卡片可以包含多个 install_options：

- remote：远程 HTTP/SSE 或 streamable HTTP；
- container：通过 MCP 管理服务创建容器；
- unsupported：展示原因但禁止安装。

安装入口为 POST /nl2agent/session/{agent_id}/mcp/install，绑定入口为：

- POST /nl2agent/session/{agent_id}/mcp/{mcp_id}/bind-tools；
- POST /nl2agent/session/{agent_id}/mcp/{mcp_id}/skip-tools。

实现位置：

- backend/services/nl2agent_mcp_service.py；
- backend/services/remote_mcp_service.py；
- backend/services/tool_configuration_service.py；
- backend/database/remote_mcp_db.py；
- frontend/components/nl2agent/WebMcpCard.tsx；
- frontend/components/nl2agent/WebMcpInstallConfiguration.tsx。

MCP 安装完成后，系统可以发现远程工具并将选定工具绑定到 Draft。未处理的 installing、connected、binding 工作流会阻止 online configuration complete 和 Finalize。

### 10.5 Web Skill 安装

Skill 配置入口为 GET /nl2agent/session/{agent_id}/web-skill/configuration，安装入口为 POST /nl2agent/session/{agent_id}/install-web-skill。

实现位置：

- backend/services/nl2agent_catalog_service.py；
- backend/services/skill_service.py；
- backend/database/skill_db.py；
- frontend/components/nl2agent/WebSkillCard.tsx；
- frontend/components/nl2agent/WebSkillConfigurationModal.tsx。

配置 Schema 由后端返回；前端只收集 schema 声明的字段，并对 password、authorization、api_key、secret、token 等字段强制掩码处理。

### 10.6 在线配置完成

会话级按钮调用 POST /nl2agent/session/{agent_id}/online-configuration/complete。后端必须确认：

- MCP 和 Skill 搜索批次已注册；
- 所有已选 MCP 安装 operation 已完成或明确跳过工具绑定；
- 所有必要配置已提交；
- 没有未决 mcp_workflows；
- Session 仍为 active。

实现位置：backend/services/nl2agent_workflow_service.py 的 confirm_online_resource_configuration。

## 11. Durable Installation Operation

### 11.1 操作状态

~~~text
不存在
  │ claim
  ▼
running ── heartbeat ── running
  │
  ├─ 外部调用成功 → checkpoint → completed
  ├─ 可恢复中断   → release lease → running（下一 worker 接管）
  └─ 不可恢复错误 → failed
~~~

### 11.2 Claim 和幂等

claim_installation_operation 的规则：

1. 按完整 Session 身份和 installation_key 查找操作；
2. fingerprint 不同则拒绝复用旧 key；
3. completed 直接返回已有 result；
4. 其他 worker 持有未过期 lease 时抛出冲突；
5. lease 过期时递增 attempt 并接管；
6. 新操作创建 running row。

### 11.3 外部 I/O 边界

安装流程必须遵循：

~~~text
短事务：claim lease
事务外：连接市场、容器、MCP server、发现工具、安装 Skill
短事务：写 checkpoint 或 completed/failed
~~~

MCP 的 lease/heartbeat 和安装逻辑位于 backend/services/nl2agent_mcp_service.py。Skill 的对应逻辑位于 backend/services/nl2agent_catalog_service.py。数据库操作由 backend/database/nl2agent_installation_db.py 负责。

### 11.4 结果和错误

operation result 只能返回：

- 资源 ID；
- 服务记录 ID；
- 发现的 Tool ID；
- 非秘密配置状态；
- 可重复读取的公开结果引用。

错误必须使用领域错误码和脱敏文本，不允许写入 token、header、密码、完整环境变量或原始配置 JSON。

## 12. Finalize 和 Draft 持久化

Finalize 入口为 POST /nl2agent/session/{agent_id}/finalize，HTTP 层位于 backend/apps/nl2agent_app.py，编排位于 backend/services/nl2agent_runtime_service.py，核心逻辑位于 backend/services/nl2agent_publication_service.py。

### 12.1 Finalize 前置条件

publication service 必须按顺序检查：

1. Draft 属于当前 tenant 和 user；
2. Session active 且 conversation 绑定一致；
3. requirements 已确认；
4. primary model 和 model_ids 有效；
5. 本地资源审查已完成；
6. MCP workflow 没有未决状态；
7. 在线配置已完成；
8. identity 已确认；
9. Draft 上已持久化的 Tool/Skill 引用仍有效；
10. final card 的必填 Prompt 字段完整；
11. requested_output_tokens 不超过模型上限。

### 12.2 持久化事务

同一数据库事务内：

1. 根据当前 Draft 和 FinalReview payload 生成内部 name；
2. 写入 description、business_description、duty_prompt、constraint_prompt、few_shots_prompt；
3. 写入 greeting_message、example_questions、max_steps 等运行参数；
4. 写入 verification_config 和 context manager 设置；
5. 将 Session 标记为 completed。

Finalize 不创建 Agent version，不发布 Agent。返回状态为 draft_ready，随后配置页重新读取 Draft 并恢复手工编辑。

## 13. HTTP API 设计

Router 位于 backend/apps/nl2agent_app.py，前缀为 /nl2agent，所有请求先通过 get_current_user_info 鉴权，再将异常映射为统一 AppException。

### 13.1 Session 和生命周期

| 方法和路径 | Handler | 业务实现 |
|---|---|---|
| GET /sessions | list_sessions_api | session_lifecycle_service.list_active_sessions |
| GET /session/by-conversation/{conversation_id} | resolve_session_api | resolve_session |
| GET /session/by-agent/{draft_agent_id} | resolve_session_by_agent_api | resolve_session_by_agent |
| POST /session/start | start_session_api | runtime_service.start_session → session_service.start_session |
| POST /session/{agent_id}/resume | resume_session_api | runtime_service.resume_session → lifecycle_service.resume_session |
| POST /session/{agent_id}/abandon | abandon_session_api | lifecycle_service.abandon_session |
| GET /session/{agent_id}/state | get_session_state_api | runtime_service.get_session_state → workflow_service.get_session_state |

### 13.2 模型、本地资源和需求

| 方法和路径 | Handler | 业务实现 |
|---|---|---|
| PUT /session/{agent_id}/models | select_models_api | runtime_service.select_models |
| POST /session/{agent_id}/requirements/register | register_requirements_api | workflow_service.register_requirements_review |
| POST /session/{agent_id}/requirements/confirm | confirm_requirements_api | workflow_service.confirm_requirements_review |
| POST /session/{agent_id}/local-resources/register | register_local_resources_api | resource_service.register_local_recommendations |
| POST /session/{agent_id}/local-resources/skip | skip_local_resources_api | resource_service.skip_local_recommendations |
| POST /session/{agent_id}/apply-local-resources | apply_local_resources_api | resource_service.apply_local_resources |

### 13.3 卡片、在线推荐和配置

| 方法和路径 | Handler | 业务实现 |
|---|---|---|
| POST /session/{agent_id}/card-delivery | report_card_delivery_api | workflow_service.report_card_delivery |
| POST /session/{agent_id}/online-recommendations/register | register_online_recommendations_api | workflow_service.register_online_resource_recommendations |
| POST /session/{agent_id}/online-configuration/complete | complete_online_configuration_api | workflow_service.confirm_online_resource_configuration |
| PUT /session/{agent_id}/identity | save_agent_identity_api | workflow_service.save_agent_identity |
| GET /session/{agent_id}/web-skill/configuration | get_web_skill_configuration_api | catalog_service.get_web_skill_configuration |
| POST /session/{agent_id}/install-web-skill | install_web_skill_api | catalog_service.install_web_skill |

### 13.4 MCP 和 Finalize

| 方法和路径 | Handler | 业务实现 |
|---|---|---|
| POST /session/{agent_id}/mcp/install | install_recommended_mcp_api | mcp_service.install_recommended_mcp |
| POST /session/{agent_id}/mcp/{mcp_id}/bind-tools | bind_mcp_tools_api | mcp_service.bind_mcp_tools |
| POST /session/{agent_id}/mcp/{mcp_id}/skip-tools | skip_mcp_tools_api | mcp_service.skip_mcp_tool_binding |
| POST /session/{agent_id}/finalize | finalize_agent_api | publication_service.publish_agent |

请求模型位于 backend/consts/model.py，响应模型位于 backend/consts/nl2agent_response.py。具体请求模型共 13 个，另有一个严格请求基类；响应模型覆盖 Session、Card、Recommendation、MCP、Skill 和 Finalize。

对话本身继续使用现有 Agent 运行接口，不新增 NL2AGENT 专用聊天接口。

## 14. 前端设计

### 14.1 配置页挂载

主要挂载位置：

- frontend/app/[locale]/agents/page.tsx：Session 发现、三列布局和 Draft 刷新；
- frontend/app/[locale]/agents/components/AgentSelectorHeader.tsx：Builder 入口和状态；
- frontend/components/nl2agent/Nl2AgentEmbeddedChat.tsx：固定 conversation 的 Assistant Runtime；
- frontend/app/[locale]/newchat/assistant-ui/thread.tsx：复用消息 Thread；
- frontend/app/[locale]/newchat/adapter/remote-chat-model-adapter.ts：复用远程流式请求；
- frontend/app/[locale]/newchat/adapter/conversation-thread-list-adapter.tsx：历史恢复；
- frontend/app/[locale]/newchat/adapter/attachment-adapter.ts：附件能力复用。

生成期间配置面板只读；FinalReview 应用成功后调用配置刷新回调。

### 14.2 唯一 Session coordinator

frontend/components/nl2agent/Nl2AgentWorkflowContext.tsx 的 Nl2AgentWorkflowProvider 是 Session-scoped 唯一协调器，负责：

- scopeKey 和 Draft ID 校验；
- active/editable/read-only 状态；
- Session state 读取和刷新；
- 输入锁和并发动作计数；
- card delivery claim、成功和失败状态；
- 自动 continuation 和有限重试；
- operation 状态变化通知；
- resume completed Session；
- 在线批次注册；
- 对历史和实时消息的副作用隔离。

卡片组件不应该直接读取全局用户或任意 Draft，只能通过 provider 和明确的 API service 调用。

### 14.3 卡片组件

| 组件 | 责任 |
|---|---|
| RequirementsSummaryCard | 需求摘要展示、fingerprint 注册和确认/修改 |
| ModelSelectionCard | 从平台模型列表选择主模型和 fallback |
| LocalResourcesCard | 本地 Tool/Skill 选择、配置和批量应用 |
| WebMcpCard | MCP 推荐、安装选项、配置和工具绑定 |
| WebMcpInstallConfiguration | MCP 字段 Schema 表单和 secret 处理 |
| WebSkillCard | Skill 推荐和安装动作 |
| WebSkillConfigurationModal | Skill 配置 Schema 表单 |
| AgentIdentityCard | 显示名称保存 |
| FinalizeCard | 最终 Prompt 和运行参数审查 |
| OnlineConfigurationBar | Session 级在线配置完成 |
| ActionCard | 通用动作按钮、阻塞和错误展示 |

卡片注册表和语言映射位于 frontend/components/nl2agent/index.tsx。

### 14.4 API 和类型

- frontend/services/nl2agentService.ts：所有 NL2AGENT HTTP 调用和前端 response projection；
- frontend/components/nl2agent/cardPayloadTypes.ts：卡片 Payload 适配；
- frontend/components/nl2agent/webMcpTypes.ts：MCP 展示类型；
- frontend/contracts/generated/nl2agent-api.ts：OpenAPI 生成类型；
- frontend/contracts/generated/nl2agent-card.schema.json：Schema 同步副本。

契约生成：

1. backend/scripts/export_nl2agent_openapi.py 生成 contracts/nl2agent-openapi.json；
2. frontend/scripts/sync-nl2agent-contracts.mjs 同步 Schema 和 OpenAPI；
3. frontend package.json 的 contracts:generate / contracts:check 校验生成结果。

## 15. 安全、鉴权和错误处理

### 15.1 鉴权和租户隔离

HTTP 层通过 utils.auth_utils.get_current_user_info 获取 user_id、tenant_id、language。所有 service 读取都必须带 tenant_id，Session 操作还必须带 user_id 和完整身份。

Draft、Conversation、Tool、Skill、MCP 的 ID 只作为候选输入，后端必须重新查询并验证所有权，不能依赖前端传来的 tenant_id。

### 15.2 卡片和推荐边界

卡片校验分两层：

- 前端校验用于防止无效 UI 和错误提交；
- 后端校验用于授权、状态推进和副作用保护。

前端校验通过不代表动作被授权。真正的授权条件是当前 Session、最新持久化消息、当前阶段和可信 batch 同时成立。

### 15.3 Secret 处理

secret 字段只允许在明确的配置请求中短暂出现：

- 不写入 Session catalog；
- 不写入 workflow_state；
- 不写入日志；
- 不写入 operation result；
- 不在卡片历史中回显；
- 返回配置时只返回 configured/masked 状态。

Tool 和 Skill 的 secret 判定、默认值脱敏分别位于 nl2agent_resource_service.py 和 nl2agent_catalog_service.py。

### 15.4 远程 MCP 网络安全

backend/services/nl2agent_mcp_url_security.py 负责：

- 只接受 HTTP/HTTPS；
- 禁止 URL 用户名和密码；
- 解析 IDNA hostname；
- 解析并过滤非公开地址；
- 固定 DNS 解析结果；
- 拒绝 redirect 到其他 host/port；
- 禁止 Unix socket；
- 禁止代理环境变量影响连接。

当前实现注意事项：build_pinned_httpx_client_factory 的默认参数允许 private network，而 create_agent_info.py 的当前调用未显式传入 NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS。部署如果依赖该开关，必须先统一默认值和调用方，否则配置语义可能与实际网络策略不一致。

### 15.5 异常映射

领域服务抛出：

- Nl2AgentValidationError；
- Nl2AgentExternalServiceError；
- Nl2AgentOperationError；
- Nl2AgentWorkflowConflictError；
- Nl2AgentStateConflictError；
- Nl2AgentDraftNotFoundError。

HTTP 层在 backend/apps/nl2agent_app.py 统一映射到 backend/consts/error_code.py 的 NL2AGENT 错误码。服务层不应通过解析异常文本决定 HTTP 状态。

## 16. 测试和验收

### 16.1 后端测试

| 范围 | 测试位置 |
|---|---|
| 工作流阶段、推荐 proof、CAS | test/backend/agents/test_nl2agent_session_catalog.py |
| Session CRUD、revision、状态 | test/backend/database/test_nl2agent_session_db.py |
| Installation lease、checkpoint、replay | test/backend/database/test_nl2agent_installation_db.py |
| 目录和 Skill 安装 | test/backend/services/test_nl2agent_catalog_service.py |
| MCP 安装、发现、绑定 | test/backend/services/test_nl2agent_mcp_service.py |
| MCP URL、DNS、redirect 安全 | test/backend/services/test_nl2agent_mcp_url_security.py |
| 本地资源应用和 secret | test/backend/services/test_nl2agent_resource_service.py |
| Session 启动、恢复、放弃、清理 | test/backend/services/test_nl2agent_session_lifecycle_service.py、test_nl2agent_session_persistence.py |
| Finalize 前置条件和 Draft 写入 | test/backend/services/test_nl2agent_publication_service.py |
| 卡片服务端 Schema | test/backend/utils/test_nl2agent_card_validation.py |
| HTTP 异常和错误码 | test/backend/apps/test_nl2agent_app_errors.py |

### 16.2 前端测试

重点覆盖：

- cardValidation.vitest.test.ts：Schema、fence、Draft ID 和批次；
- cardLifecycle.vitest.test.tsx：claim、重复渲染、失败重试；
- registrationLifecycle.vitest.test.tsx：在线批次注册；
- persistedCardState.vitest.test.tsx：历史状态恢复；
- completedSessionResume.vitest.test.tsx：completed → revision_mode；
- localResourceConfig.vitest.test.tsx：Tool 参数和 secret；
- webSkillConfiguration.vitest.test.tsx：Skill Schema 配置；
- embeddedNewChat.vitest.test.ts：嵌入式聊天和标签映射；
- newchat/adapter/__tests__/nl2agent-user-action-history.vitest.test.ts：动作消息历史过滤。

### 16.3 Contract 和 Migration

- test/contracts/test_nl2agent_card_contract.py；
- test/contracts/test_nl2agent_session_contract.py；
- deploy/tests/test_sql_migrations.sh；
- test/deploy/test_local_sql_migrations.py。

### 16.4 合并验收条件

新增或修改 NL2AGENT 功能必须满足：

1. frontend contract:check 通过；
2. OpenAPI 快照与 Router 一致；
3. 新增数据库字段同时更新 migration 和 deploy/sql/init.sql；
4. 所有状态转移都有冲突、重复请求和非法阶段测试；
5. 外部 I/O 测试使用 mock，不让数据库事务跨网络；
6. 日志和响应中没有 secret；
7. 前端只读历史不会触发任何 mutation；
8. git diff --check 通过。

## 17. 当前实现限制和后续演进

### 17.1 当前已知技术债

以下代码是迁移兼容残留，不应继续扩展：

- backend/agents/nl2agent_session_store.py 中的 no-op cache hooks；
- 仍提及 Redis 的旧模块注释和依赖名称；
- runtime_service 的 compatibility facade；
- 前端手写 cardPayloadTypes 与 Schema 重复；
- 全量 catalog snapshot 带来的 JSONB 体积；
- Markdown fence 在后端和前端重复解析；
- standalone frontend/components/common/markdownHeadings.tsx 与 markdownRenderer.tsx 的重复实现。

### 17.2 结构化 Card Event 演进方向

当前数据库已经有 message_type 和 message_metadata，可逐步将卡片从 Markdown fence 迁移为结构化消息：

~~~text
LLM final answer
  → 后端一次提取和 Schema 校验
  → conversation_message.message_type=nl2agent_card
  → message_metadata 保存 card_type、card_key、payload 摘要
  → SSE 发送结构化 card event
  → 前端只做 CardRegistry 渲染
~~~

迁移期间必须继续兼容历史 fence 消息，直到所有活动 Session 和历史查询都能读取结构化 card event。

### 17.3 新增卡片的变更清单

新增一种卡片类型时，必须同时修改：

1. contracts/nl2agent-card.schema.json；
2. backend/utils/nl2agent_card_validation.py 的标签和类型映射；
3. backend/agents/nl2agent_workflow.py 的 CardType、阶段和 delivery；
4. backend/prompts/nl2agent_system_prompt_zh.yaml 和 en.yaml；
5. frontend/components/nl2agent/cardValidation.ts；
6. frontend/components/nl2agent/index.tsx；
7. 对应 React Card 组件和 API action；
8. OpenAPI/Pydantic request/response；
9. 服务端 trusted proof 和最终校验；
10. 后端、前端和 contract 测试；
11. OpenAPI 和前端生成契约。

### 17.4 新增数据库字段或表的变更清单

必须同时修改：

1. deploy/sql/migrations/ 中的版本迁移；
2. deploy/sql/init.sql；
3. backend/database/db_models.py；
4. Repository 和 service；
5. 生成的 OpenAPI 或响应模型（如果对外暴露）；
6. migration、数据库和生命周期测试；
7. 本文数据模型和恢复语义。

## 18. 实现位置索引

| 设计点 | 首要文件 |
|---|---|
| Builder 默认定义 | backend/agents/default_agents/nl2agent.json |
| 中英文 Prompt | backend/prompts/nl2agent_system_prompt_zh.yaml、backend/prompts/nl2agent_system_prompt_en.yaml |
| 工作流状态和阶段 | backend/agents/nl2agent_workflow.py |
| 状态转移和 proof | backend/agents/nl2agent_session_catalog.py |
| PostgreSQL Session | backend/agents/nl2agent_session_store.py、backend/database/nl2agent_session_db.py |
| 安装 operation | backend/database/nl2agent_installation_db.py |
| Session 创建 | backend/services/nl2agent_session_service.py |
| Session 恢复和清理 | backend/services/nl2agent_session_lifecycle_service.py |
| API 边界 | backend/apps/nl2agent_app.py |
| 运行时 facade | backend/services/nl2agent_runtime_service.py |
| 本地资源 | backend/services/nl2agent_resource_service.py |
| 在线目录和 Skill | backend/services/nl2agent_catalog_service.py |
| MCP 安装和绑定 | backend/services/nl2agent_mcp_service.py |
| MCP 网络安全 | backend/services/nl2agent_mcp_url_security.py |
| Finalize | backend/services/nl2agent_publication_service.py |
| 服务端卡片校验 | backend/utils/nl2agent_card_validation.py |
| SDK 搜索上下文 | sdk/nexent/core/tools/nl2agent/_context.py |
| SDK 本地搜索 | sdk/nexent/core/tools/nl2agent/search_local_resources_tool.py |
| SDK MCP 搜索 | sdk/nexent/core/tools/nl2agent/search_web_mcps_tool.py |
| SDK Skill 搜索 | sdk/nexent/core/tools/nl2agent/search_web_skills_tool.py |
| 嵌入式聊天 | frontend/components/nl2agent/Nl2AgentEmbeddedChat.tsx |
| 前端 Session coordinator | frontend/components/nl2agent/Nl2AgentWorkflowContext.tsx |
| Fence 解析和注册表 | frontend/components/nl2agent/Nl2AgentFenceRenderer.tsx、frontend/components/nl2agent/index.tsx |
| 卡片 Schema 校验 | frontend/components/nl2agent/cardValidation.ts |
| API client | frontend/services/nl2agentService.ts |
| 源卡片契约 | contracts/nl2agent-card.schema.json |
| OpenAPI 导出 | backend/scripts/export_nl2agent_openapi.py |
| 前端契约同步 | frontend/scripts/sync-nl2agent-contracts.mjs |
| 数据库迁移 | deploy/sql/migrations/v2.4.0_0722_add_nl2agent.sql、deploy/sql/migrations/v2.4.0_0722_add_conversation_message_metadata.sql |
