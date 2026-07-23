# NL2AGENT 当前实现：相对 develop 的变更设计与代码量分析

> 分析快照：2026-07-23
>
> 当前分支：`dyx/nl2a-branch-lite`
>
> 当前提交：`56c0a79b7`
>
> 本地 develop 基线：`d1db1cf49`

本文替换原有的 v3 切换说明，回答四个问题：

1. `develop` 中原来没有什么，当前分支新增或修改了什么；
2. 当前 NL2AGENT 为什么采用这套状态、消息、动作和安装设计；
3. 代码量集中在哪些层、哪些文件，以及测试和生成代码占比；
4. 合入 `develop` 前还需要收敛哪些风险。

文中“当前实现”指 `56c0a79b7` 的最终代码树，而不是中间提交曾经存在、随后又被删除的 v1/v2 协议。

## 1. 结论摘要

本地 `develop@d1db1cf49` 中没有 NL2AGENT 路由、Session 表、Action 合同、Card 合同、SDK 搜索工具或前端 Builder 组件。当前分支实际引入的是一条完整的“自然语言生成 Agent 草稿”产品链路，而不是单一页面功能。

最终架构可概括为：

- PostgreSQL 保存 Session、workflow、catalog snapshot、Action receipt 和 installation operation，是业务状态权威源；
- LLM 只负责需求整理、搜索决策和生成受约束卡片，不直接提交可信资源 ID、URL、租户信息或凭据；
- SDK 搜索工具把结果先写成服务端 recommendation proof，卡片与后续 Action 必须再次匹配该 proof；
- 所有卡片写操作统一进入一个 Action Dispatcher，并使用 `action_id + expected_revision` 实现幂等和并发控制；
- Assistant 最终答案先完整缓冲，再由后端解析卡片、CAS 更新 workflow、保存消息，最后只发送一个结构化 SSE 事件；
- MCP、Web Skill 和 MCP Tool binding 使用可恢复的 lease/checkpoint runner，外部 I/O 不持有数据库事务；
- 前端嵌入 Agent 配置页，历史卡片从 message metadata 恢复，completed Session 默认只读，可显式进入 revision mode；
- `finalize` 只更新 version 0 的 Draft Agent 并完成 Session，不创建发布版本，也不提交 Agent Repository 审核。

从代码量看，NL2AGENT 专属最终净差异为 183 个文件、`+43,277/-1,284` 行。其中测试新增 13,251 行，生成合同新增 8,805 行；两者合计占新增行的 51.0%。可执行及部署代码新增 20,603 行，复杂度主要集中在后端状态与资源编排。

## 2. 基线、分叉和统计口径

### 2.1 Git 基线

| 项目 | 提交 | 关系 |
| --- | --- | --- |
| 本地 `develop` | `d1db1cf49` | 当前 HEAD 的直接祖先 |
| 当前 NL2AGENT HEAD | `56c0a79b7` | 相对本地 develop 前进 35 个提交 |
| `origin/develop` | `f0a4165f4` | 已与当前分支分叉 |
| 当前分支与 `origin/develop` 的共同祖先 | `c7a7ae505` | 远端三点比较的基线 |

当前仓库状态下：

- `develop...HEAD` 为 `0/35`，即本地 develop 没有独有提交，当前分支有 35 个提交；
- `origin/develop...HEAD` 为 `3/30`，即远端 develop 有 3 个当前分支尚未包含的提交，当前分支有 30 个 NL2AGENT 专属提交；
- 因此合并前必须先处理远端 develop 的 3 个新提交，并重新运行统计、测试与冲突审查。

### 2.2 两套差异口径

本文同时保留两套统计，避免把同步带入的共享基础改造误算成 NL2AGENT 本体。

| 口径 | Git 范围 | 提交数 | 文件 | 新增 | 删除 | 变更行 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 共享基础变更 | `develop..c7a7ae505` | 5 | 194 | 11,883 | 12,692 | 24,575 |
| NL2AGENT 专属最终差异 | `c7a7ae505..HEAD` | 30 | 183 | 43,277 | 1,284 | 44,561 |
| 分支相对本地 develop 的全部净差异 | `develop...HEAD` | 35 | 344 | 55,106 | 13,922 | 69,028 |

共享基础的 5 个提交分别涉及旧聊天 Markdown 兼容、Planning Agent、主 Agent 过滤、ContextItems/上下文运行时重构和通知中心。NL2AGENT 直接复用了新的上下文注入与聊天渲染能力，但通知中心的大部分代码不是 NL2AGENT 核心。

文件数和变更行不能把前两行简单相加，因为同一文件可能在两个阶段都被修改，最终 diff 会折叠中间增删。

统计采用 `git diff --numstat` 的物理行数：包含测试、文档、JSON Schema 和生成 TypeScript，不等同于逻辑 LOC 或圈复杂度。

## 3. 相对 develop 的能力变更地图

| 领域 | develop 基线 | 当前实现 |
| --- | --- | --- |
| 产品入口 | 无对话式 Agent Builder | Agent 配置页内嵌 Builder Chat，支持创建、恢复、只读和继续调整 |
| Agent 运行 | 普通 `/agent/run` 流式输出 | 增加 `draft_agent_id` 和受验证 Action Context；NL2AGENT 使用完整答案缓冲与单事件输出 |
| Session | 无 NL2AGENT 状态 | Draft、Builder Conversation、workflow 和 catalog snapshot 单事务创建 |
| Workflow | 无专用状态机 | workflow schema v3，10 个阶段、revision CAS、revision mode |
| 写操作 | 各业务接口自行处理 | 11 种动作统一进入 `POST .../actions` |
| 消息 | 普通文本和 unit | 增加 `message_type`、`message_metadata`、Action receipt 和 Card Envelope |
| 搜索 | 无 Builder 搜索工具 | SDK 内置本地 Tool/Skill、Web MCP、Web Skill 三个搜索工具 |
| 推荐可信度 | LLM 文本不可验证 | 搜索结果先持久化为 proof，卡片和动作逐次校验资源集合及 catalog hash |
| MCP | 通用 MCP 管理能力 | 增加 NL2AGENT 推荐解析、配置、远程/容器安装、发现、绑定和跳过流程 |
| Web Skill | 通用 Skill 安装能力 | 增加可信目录解析、配置脱敏、可恢复安装和 Draft 绑定 |
| 长任务 | 无 NL2AGENT 持久化执行状态 | operation ID、fingerprint、lease、heartbeat、checkpoint、retry 和 replay |
| 前端卡片 | 无 NL2AGENT 合同 | 7 类结构化卡片、Registry 渲染、历史恢复和统一 Action lifecycle |
| 合同治理 | 手写前后端类型 | Pydantic -> OpenAPI/JSON Schema -> 生成 TypeScript |
| 数据库 | 无相关表和消息元数据 | 2 张 NL2AGENT 表、2 个消息字段及 fresh-init/migration 同步 |
| 运维 | 无切换检查 | v3 cutover guard、保留策略、结构化指标和回滚约束 |

## 4. 设计目标、边界与权威关系

### 4.1 目标

NL2AGENT 的目标是把自然语言需求转化为一个可继续手工编辑的 Draft Agent，覆盖：

- 五项需求确认；
- 主模型和最多四个 fallback 模型选择；
- 本地 Tool/Skill 推荐与绑定；
- 在线 MCP/Skill 搜索、安装与配置；
- Agent 显示名称；
- 描述、Prompt、欢迎语、示例问题和运行参数的最终确认。

### 4.2 非目标

当前实现明确不负责：

- 自动创建 Agent 发布版本；
- 自动提交 Agent Repository 审核；
- 让 LLM 直接决定数据库主键、租户、用户、凭据或任意 MCP URL；
- 在 active Session 中静默刷新目录；
- 兼容旧 v2 workflow、旧 card delivery/registration API 或前端 fence 解析；
- 用浏览器状态、LocalStorage 或 Redis 恢复业务 workflow。

### 4.3 权威源

权威关系从高到低为：

1. PostgreSQL 中的 Session、Draft 配置、Action receipt 和 installation operation；
2. 后端 Pydantic workflow/Card/Action 合同和阶段评估器；
3. SDK 搜索工具写入的 trusted recommendation proof；
4. 前端只读 Session projection 和 message metadata；
5. LLM 输出及浏览器临时状态。

逻辑上的完整 Session 身份为：

```text
tenant_id + user_id + runner_agent_id + draft_agent_id + conversation_id
```

HTTP 与 Agent Run 边界会校验租户、用户、Draft、Conversation 和 Builder runner。结构化消息原子落库以及安装 operation 也使用完整身份。需要注意的是，部分内部 workflow CAS helper 目前仍只以 `tenant_id + draft_agent_id` 查询，依赖调用前的 owner 校验；这与“所有持久化写入都直接使用完整身份”的理想目标尚有差距，见第 19 节。

## 5. 总体架构和端到端链路

```text
Agent 配置页
  |
  |-- POST /nl2agent/session/start
  |     `-- Draft Agent + Builder Conversation + v3 Session + Catalog Snapshot
  |
  |-- POST /agent/run
  |     |-- 校验完整 Session/Runner/Conversation 身份
  |     |-- 注入 YAML System Prompt + Current Session JSON
  |     |-- SDK 搜索工具可写入 trusted recommendation batch
  |     |-- 缓冲完整 final_answer
  |     |-- 后端解析 fence、验证卡片和搜索 proof
  |     |-- 单事务：workflow CAS + assistant message + metadata + final unit
  |     `-- 仅发送一个 nl2agent_message SSE
  |
  `-- POST /nl2agent/session/{draft_agent_id}/actions
        |-- Action ID/fingerprint/revision/stage/proof 校验
        |-- 写入或重放用户 Action receipt
        |-- 调用模型、本地资源、MCP、Skill、Identity 或 Finalize 服务
        `-- 下一轮 /agent/run 携带受验证 Action Context
```

### 5.1 Session 启动

`backend/services/nl2agent_session_service.py` 先完成外部目录加载，再在一个数据库事务中：

1. 创建 `draft_<8 hex>` Draft Agent；
2. 创建标题为 `NL2AGENT - <draft>` 的 Builder Conversation；
3. 初始化 workflow schema v3、revision 0；
4. 保存不可变 catalog version/hash 和规范化目录；
5. 保存完整 Session 身份。

如果事务内任一步失败，Draft、Conversation 和 Session 一起回滚。Builder Agent 不存在时会按租户自动 seed，并校验三个内置搜索工具是否就绪。

### 5.2 普通用户文本

用户直接输入文本时，后端先用规则处理需求确认或 revision intent，再保存用户消息。随后创建 Agent Run，将当前 workflow projection 作为 System Prompt 的 `Current Session` JSON 注入。

### 5.3 卡片 Action 后续轮次

卡片点击首先调用统一 Action API。Action 成功后，前端把 Action receipt 转成 `nl2agent_action_context`，再向 `/agent/run` 追加一个视觉上的用户 Action 消息。

后端会重新读取该 Action receipt，验证 action ID、动作类型、显示文本和 workflow revision；验证成功后，传给模型的 query 会被替换为内部 JSON 指令，且不会重复保存用户消息。因此模型不能通过伪造前端 display text 越过已持久化动作结果。

## 6. Session 与数据库设计

### 6.1 `nl2agent_session_t`

核心字段：

| 字段 | 作用 |
| --- | --- |
| `tenant_id/user_id` | Session owner |
| `runner_agent_id` | 租户内 NL2AGENT Builder |
| `draft_agent_id` | 正在生成的 version 0 Agent |
| `conversation_id` | 隐藏 Builder Conversation |
| `status` | `active/completed/abandoned` |
| `workflow_schema_version` | 当前只接受 3 |
| `workflow_revision` | 乐观锁 revision |
| `session_catalogs` | version/hash 和 5 类目录 |
| `workflow_state` | v3 状态机 JSONB |

数据库约束包括：

- `(tenant_id, draft_agent_id)` 唯一；
- `(tenant_id, conversation_id)` 唯一；
- status 枚举检查；
- `workflow_state.revision == workflow_revision` 检查；
- 每租户只允许一个未删除的 `name = 'nl2agent'` Builder Agent。

### 6.2 `nl2agent_installation_operation_t`

该表保存 MCP、Web Skill 和 MCP binding 的可恢复执行状态：

- 服务端派生的 `operation_id`；
- Session 完整身份；
- secret-free `installation_key`；
- request SHA-256 fingerprint；
- `pending/running/completed/failed`；
- checkpoint、attempt、lease owner/expiry；
- 脱敏 result/error。

唯一键 `(tenant_id, draft_agent_id, installation_key)` 防止同一资源被并发创建多个 operation。

### 6.3 Conversation 消息扩展

`conversation_message_t` 新增：

- `message_type`：`chat`、`nl2agent_action`、`nl2agent_card`；
- `message_metadata JSONB`：保存 Action receipt 或 Card Envelope。

这使历史恢复不再依赖重新解析 Markdown，也不需要额外 card delivery 表。

### 6.4 生命周期与清理

当前行为：

- `active` 超过 `NL2AGENT_ACTIVE_RETENTION_DAYS`，在下一次 Session start 时机会性转为 `abandoned`；
- `abandoned` 超过 `NL2AGENT_ABANDONED_RETENTION_DAYS`，分批软删除 Session、Draft、资源实例和 Conversation 数据；
- `completed` 作为 Agent 的可恢复编辑历史，不按年龄清理；删除 Agent 时再联动删除；
- 默认 active/abandoned 均为 30 天，批大小默认 100、最大 500。

代码中仍定义了 `NL2AGENT_COMPLETED_RETENTION_DAYS` 和 completed cleanup repository helper，但生命周期服务没有使用它们；同时清理只在 Session start 触发，没有独立调度器。这是需要收敛的配置与运维语义。

## 7. Workflow v3 状态机

合同源为 `backend/agents/nl2agent_workflow.py`，`WORKFLOW_SCHEMA_VERSION = 3`。旧版本不会自动转换，解析非 v3 数据时直接失败关闭。

### 7.1 核心状态

| 状态 | 含义 |
| --- | --- |
| `revision` | 每次有效 workflow mutation 或 Assistant message finalize 单调递增 |
| `revision_mode` | completed/final-review Session 重新编辑时的路由模式 |
| `requirements_review` | `collecting/awaiting_confirmation/confirmed` 和五项摘要 |
| `model_selection_confirmed` | 模型选择是否已写入 Draft 并确认 |
| `recommendations` | local/MCP/Skill 搜索 proof 及处理状态 |
| `mcp_workflows` | MCP 安装、发现和绑定业务结果 |
| `online_configuration_confirmed` | 在线资源是否整体完成 |
| `identity_confirmed` | 显示名称是否确认 |

### 7.2 阶段决策

| 阶段 | 期望卡片 | 允许的逻辑动作 |
| --- | --- | --- |
| `requirements_collecting` | 无；五项齐全时可生成 requirements 卡 | 澄清、生成摘要 |
| `requirements_confirmation` | 不重复生成卡 | 确认或修改需求 |
| `model_selection` | `model_selection` | 选择模型 |
| `local_resource_search` | `local_resources` | 搜索本地资源 |
| `local_resource_review` | 未展示时要求 local 卡，已展示后为空 | 应用或跳过 |
| `online_resource_search` | 尚未注册的 `web_mcp/web_skill` | 搜索在线资源，或继续配置已有结果 |
| `online_resource_review` | 尚未展示的在线卡 | 安装/绑定/跳过、整体完成配置 |
| `agent_identity` | `agent_identity` | 保存显示名称 |
| `final_review` | `final_review` | finalize Draft |
| `revision_routing` | 无固定期望 | 按用户修改意图路由到任一配置域 |

`evaluate_workflow()` 是前端状态、System Prompt 和后端阶段校验共享的唯一决策器，避免在多个服务中复制阶段判断。

### 7.3 Recommendation 状态

`RecommendationBatch` 保存：

- `resource_type = local/mcp/skill`；
- `searched -> presented -> applying -> applied`，或 `skipped/completed`；
- catalog version/hash；
- 精确 Tool ID、Skill ID 或在线 item key 集合；
- 本地应用选择和 operation ID。

搜索工具写 proof 时会先检查当前阶段是否允许搜索。Assistant message 原子落库时，卡片对应 batch 从 `searched` 变为 `presented`。本地绑定采用 reservation，在线批次在用户点击“完成配置”时统一变为 `completed`。

### 7.4 MCP 业务状态

每个 recommendation 的状态为：

```text
configuration_required -> installing -> connected
                                      -> tools_bound
                                      -> binding_skipped
                                      -> failed
```

`connected` 仍是未完成状态，必须绑定已发现 Tool 或显式跳过后，才能结束在线配置和 finalize。

## 8. Catalog Snapshot 与 Recommendation Proof

### 8.1 目录组成

每个新 Session 固化五类目录：

1. `tool_catalog`：tenant 内 `local/mcp/langchain` Tool，不含 builtin；
2. `skill_catalog`：tenant 已安装 Skill；
3. `registry_results`：官方 MCP Registry；
4. `community_results`：社区 MCP；
5. `official_skills`：可安装或资源缺失、可恢复的官方 Skill。

本地 Tool/Skill 或官方 Skill 目录读取失败会阻止 Session 启动。Registry 和 Community MCP 采用降级策略，单个 provider 失败时保存空目录并记录 warning。

目录加载有明确预算：每个 marketplace 最多 20 页、2,000 项、5 MiB、15 秒；本地 Tool 和 Skill 各最多 2,000 项。

### 8.2 规范化和内容寻址

Session version 格式为 `catalog_<32 hex>`。计算 hash 前：

- 字符串执行 NFKC 和 trim；
- 字典键稳定排序；
- 顶层目录项按规范 JSON 排序；
- 嵌套数组保留业务顺序；
- 整体计算 SHA-256。

后端读取快照时会重新计算 hash。内容、version 或 hash 任一不匹配都拒绝继续。

### 8.3 Proof 绑定

SDK 搜索返回值不能自行声明可信 snapshot identity。后端 callback 在写 recommendation batch 时绑定当前 Session 的 version/hash。后续三个位置都会重新校验：

- Assistant card parser：卡片中的资源集合必须与 proof 完全一致；
- Action Dispatcher：batch 必须属于当前 workflow 且匹配 snapshot；
- 资源服务：应用或安装前再次验证 ID/item key 属于 batch。

目录变化时必须新建 Session；active Session 不隐式刷新，保证用户看到的推荐与执行时依据一致。

## 9. SDK 搜索工具设计

当前 Builder 仅暴露三个内置工具：

- `nl2agent_search_local_resources`；
- `nl2agent_search_web_mcps`；
- `nl2agent_search_web_skills`。

后端在创建 AgentConfig 时注入 tenant、user、draft、language、确认状态、不可变目录和 proof recorder。SDK 本身不读取环境变量，也不调用后端 HTTP 服务。

搜索实现具有以下约束：

- query 经过 NFKC、casefold、停用词过滤，中文使用 jieba 分词；
- 名称与 metadata 独立模糊匹配，最低关键词分数 0.62；
- 关键词采用 OR 语义，并将覆盖率纳入综合分；
- 本地 Tool/Skill 合并排序后最多返回 5 项；
- Web MCP/Web Skill 各最多返回 5 项；
- batch ID 由 Draft、规范化 query 和精确结果集合哈希生成；
- proof 持久化失败时工具只返回 error，不允许模型继续渲染可信卡片。

Web MCP 工具还把 Registry/Community 元数据统一成 remote、container 或 unsupported 安装选项，并显式标注配置字段、类型、是否必填和是否 secret。

## 10. 统一 Action Dispatcher

所有业务写操作进入：

```http
POST /nl2agent/session/{draft_agent_id}/actions
```

请求示例：

```json
{
  "action": "apply_local_resources",
  "action_id": "uuid",
  "expected_revision": 18,
  "display_text": "已应用本地资源",
  "payload": {
    "recommendation_batch_id": "local_xxx",
    "tool_ids": [1],
    "skill_ids": [2],
    "tool_config_values": {}
  }
}
```

支持 11 种 Action：

- `confirm_requirements`；
- `save_model_selection`；
- `apply_local_resources`；
- `skip_local_resources`；
- `install_mcp`；
- `bind_mcp_tools`；
- `skip_mcp_tools`；
- `install_web_skill`；
- `complete_online_configuration`；
- `save_identity`；
- `finalize`。

### 10.1 校验顺序

Dispatcher 的顺序为：

1. owner-scoped Session 查询；
2. 查找同一 `action_id` 的历史 receipt；
3. 校验 Session 为 active；
4. 校验 `expected_revision`；
5. 校验当前阶段允许该动作；
6. 对资源 Action 校验 recommendation proof 和 catalog snapshot；
7. 使用 PostgreSQL advisory lock 创建唯一用户 Action 消息；
8. 执行业务服务；
9. 把 receipt 更新为 applied/failed，并保存脱敏结果或错误码。

### 10.2 幂等语义

Action fingerprint 是除 `action_id` 外的完整请求规范 JSON 的 SHA-256，因此包含 action、revision、display text 和 payload。

- 同一 ID、同一 fingerprint、已成功：返回 `replayed`，不重复执行业务；
- 同一 ID、不同 fingerprint：409；
- 同一 ID、failed：可重新 claim；
- 同一 ID、pending：返回 `pending`；
- 首次执行成功：返回 `applied`。

Action 用户消息只创建一次，历史中可读 display text 与服务端 receipt 一一对应。

### 10.3 Payload 信任边界

Action 使用严格 discriminated Pydantic union。客户端不能提交：

- tenant/user/runner/conversation 身份；
- installation operation ID；
- 任意 MCP URL；
- 任意 Skill 来源；
- 不属于 recommendation batch 的 Tool/Skill/MCP。

客户端只提交 card 允许的选择和配置值，后端从 Session catalog 和数据库重新解析真实资源。

## 11. Card 合同、消息持久化和 SSE

### 11.1 合同源

`backend/consts/nl2agent_card.py` 定义 7 类卡片：

- requirements summary；
- model selection；
- local resources；
- web MCP；
- web Skill；
- agent identity；
- final review。

Pydantic 合同生成：

- `contracts/nl2agent-card.schema.json`；
- `contracts/nl2agent-openapi.json`；
- `frontend/contracts/generated/nl2agent-card.schema.json`；
- `frontend/contracts/generated/nl2agent-api.ts`。

### 11.2 模型输出格式

模型仍输出 `nl2agent-*` fenced JSON，但它只是“模型到后端”的内部序列化格式。浏览器不解析 fence，也不会在历史中重放它们。

后端 parser 只处理完整 final answer，并检查：

- fence 完整、语言标签受支持、JSON 合法；
- payload 严格类型和长度；
- Draft ID 一致；
- card type/key 不重复；
- recommendation card 的 ID/key 集合与 trusted proof 完全一致；
- 当前阶段允许且包含精确要求的卡片类型。

Envelope 为：

```json
{
  "schema_version": 1,
  "draft_agent_id": 123,
  "workflow_revision": 19,
  "cards": [
    {
      "card_type": "local_resources",
      "card_key": "local_xxx",
      "payload": {}
    }
  ]
}
```

Card Envelope 不包含 catalog version/hash。前端如需展示该标识，从只读 Session state 中 recommendation batch 读取，不能把它作为 Action 输入。

### 11.3 原子 finalize

每一条 NL2AGENT Assistant 答案都执行一个事务：

1. 用完整 Session 身份读取 active row；
2. 读取当前 revision；
3. 解析完整答案并校验卡片/proof；
4. 应用 requirements、presentation 或 revision-mode transition；
5. revision 加一；
6. 按完整身份执行 workflow CAS；
7. 保存一条 `message_type = nl2agent_card` 的 Assistant message；
8. 把 Envelope 写入 `message_metadata.nl2agent_card`；
9. 只把剥离 fence 的展示文本写入 message content 和一个 final-answer unit。

即使本轮没有卡片，仍会保存一个 cards 为空的结构化消息，并推进 revision。任一步失败都会回滚，不产生半条消息或半个 workflow transition。

### 11.4 SSE

NL2AGENT 不逐 token 展示。Agent Run 完成后只发送：

```text
type = nl2agent_message
content = 已持久化 message_id/content/type/metadata/status
```

前端用服务端 message ID 替换临时消息，从 metadata 读取 Envelope，再通过 Card Registry 渲染。普通 Agent 保持原有流式协议。

## 12. 资源应用与可恢复安装

### 12.1 本地 Tool/Skill

本地应用先校验所选 ID 是 recommendation batch 的子集，再从数据库重新加载资源和参数 schema。Tool 配置字段执行类型、choice、required 和 secret 规则。

在一个数据库事务中：

1. 以 operation hash 将 batch 从 presented 预留为 applying；
2. upsert ToolInstance 和 SkillInstance；
3. 将 batch 标记 applied；
4. 完成 revision transition。

失败时整个事务回滚，对外语义为“没有资源被应用”。

### 12.2 Durable Installation Runner

MCP、Web Skill 和 MCP Tool binding 共用 runner：

- operation ID 由完整 Session 身份、resource type 和 installation key 派生；
- PostgreSQL advisory lock 与 row lock 序列化 claim；
- 默认 lease 5 分钟、heartbeat 60 秒；
- stale lease 可 takeover；
- completed operation 可 replay；
- checkpoint 支持外部副作用后的恢复；
- provider I/O 在短数据库事务外运行；
- 失败只持久化固定 error code/message。

凭据可能参与 request fingerprint 的哈希输入，但不会以明文进入 fingerprint、checkpoint、result、error、日志或响应。checkpoint/result 还会按敏感 key 递归脱敏。

### 12.3 MCP 安装

MCP 流程支持：

- Registry remote；
- Registry package 转换为 npx/uvx container config；
- Community remote；
- Community container；
- unsupported metadata 的明确拒绝。

安装完成后会重新读取 MCP record，安全连接、发现 Tool、写入 Tool catalog，并把 workflow 标为 connected。用户随后必须选择 Tool 绑定或跳过。

### 12.4 Web Skill 安装

Skill 只能从 Session 中的 official catalog 解析。配置 schema 和默认值由服务端重新读取，secret 默认值返回 `null`，未知字段或类型不匹配直接拒绝。

文件安装、Skill record 解析、配置绑定均写 checkpoint，支持失败后继续。`resource_missing` 的官方 Skill 会从本地目录排除，但保留为在线可恢复项。

## 13. MCP 网络安全

`backend/services/nl2agent_mcp_url_security.py` 是 NL2AGENT 远程 MCP 的统一网络策略入口。

安全检查包括：

- 只允许 HTTP/HTTPS；
- URL 不允许内嵌用户名或密码；
- 端口必须为 1-65535；
- 拒绝 loopback、link-local、unspecified、multicast、reserved；
- 显式拒绝常见云 metadata 地址；
- 连接前解析 DNS 并固定允许的 IP；
- 保留原始 Host/SNI，但 TCP 只连接已验证 IP；
- 每次 redirect 都重新解析和验证；
- `trust_env = false`，调用方不能覆盖 transport、proxy 或 verify。

当前默认值存在部署路径差异：

- 裸后端进程在未设置环境变量时，`const.py` 默认 `NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS=true`；
- Docker 和 K8s 生成配置时默认注入 `false`；
- 因而正式部署通常是 public-only，本地直接启动则可能允许 private network。

这个差异应在合入前统一，否则同一版本会因启动方式不同产生不同 SSRF 边界。

## 14. Frontend 设计

### 14.1 配置页嵌入

启动 Builder 后，Agent 配置页变为三列：

- Builder Chat；
- Agent Config；
- Agent Info。

active Session 期间右侧手工配置被禁用，避免用户表单与 Builder 同时写 Draft。Action 成功后会重新加载 Agent 和 Session projection。

### 14.2 Session 恢复

页面通过 `draft_agent_id` 查询 Session，不依赖 LocalStorage。Chat history 通过原 Conversation 加载：

- `nl2agent_action` 恢复成只读用户 Action 消息；
- `nl2agent_card` 从 metadata 恢复 Envelope；
- completed Session 禁止输入并显示“继续调整”；
- resume 后进入 revision mode。

### 14.3 Card Registry 与 lifecycle

`cardRegistry.tsx` 是 card type 到 React 组件的唯一映射。所有卡片通过 `useNl2AgentCardLifecycle` 获得一致行为：

- 使用 `crypto.randomUUID()` 创建 action ID；
- 从权威 Session state 读取 expected revision；
- 同一组件内失败重试复用 action ID；
- action 期间锁定输入；
- 成功后刷新 Session state；
- 除安装中间步骤和 finalize 外，默认自动发起下一轮 Agent Run。

MCP 安装、Tool binding、Skill 安装可以在同一在线资源阶段多次发生；`OnlineConfigurationBar` 负责会话级“完成配置”。

### 14.4 历史和 Markdown

通用 Markdown renderer 不再识别 NL2AGENT fence。结构化卡片只来自 `message_type + message_metadata`，因此：

- 历史加载不会重新注册卡片；
- 不会报告 delivery；
- 不会自动执行 Action；
- 普通 Markdown code fence 与 Builder 卡片协议解耦。

## 15. Finalize、completed 与 revision mode

`finalize` 在一个事务中：

1. 校验需求、本地资源、MCP、在线配置和身份都已完成；
2. 重新校验当前模型仍可用；
3. 重新解析已绑定 Tool/Skill，拒绝悬空引用；
4. 合并最终卡片中的描述、Prompt 和运行参数；
5. 更新 Draft Agent 的 version 0；
6. 将 Session 从 active 改为 completed。

返回 `status = draft_ready`。这里的 service/function 名称仍使用 `publish_agent`，部分前端文案也使用 Publish，但实际上没有创建 Agent version，也没有市场发布副作用。

completed Session 的聊天和卡片只读。resume 只允许 owner 操作，并要求：

- Draft 和 Conversation 仍存在；
- catalog snapshot 仍能通过 hash 校验；
- completed workflow 位于 final-review；
- CAS 成功把 Session 重新设为 active、`revision_mode=true`、revision 加一。

revision mode 的 Prompt 要求每次只修改一个配置域。当前后端只检查“卡片类型属于 allowed set”和“不重复”，尚未强制最多一类卡片；因此这一规则目前主要由 Prompt 而不是服务端保证。

## 16. HTTP API 与错误语义

当前 NL2AGENT 路由共 9 个：

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/nl2agent/sessions` | 当前用户 active Sessions |
| GET | `/nl2agent/session/by-conversation/{conversation_id}` | 按 Conversation 恢复 |
| GET | `/nl2agent/session/by-agent/{draft_agent_id}` | 按 Draft 恢复 |
| POST | `/nl2agent/session/start` | 创建 Draft/Conversation/Session |
| POST | `/nl2agent/session/{draft_agent_id}/resume` | 继续调整 |
| POST | `/nl2agent/session/{draft_agent_id}/abandon` | 放弃 active Session |
| GET | `/nl2agent/session/{draft_agent_id}/state` | 权威只读 projection |
| GET | `/nl2agent/session/{draft_agent_id}/web-skill/configuration` | 可信且脱敏的 Skill 配置 |
| POST | `/nl2agent/session/{draft_agent_id}/actions` | 统一业务写入口 |

Action endpoint 的稳定语义为：

| HTTP | 含义 |
| --- | --- |
| 401 | 未认证 |
| 403 | owner/tenant/Draft 不可访问 |
| 409 | revision、阶段、Session、Action fingerprint 或 recommendation proof 冲突 |
| 422 | Action payload 不符合严格合同 |
| 502 | provider/连接类失败 |
| 503 | Action 内部持久化或 durable operation 暂不可用 |

生命周期接口使用 App error code 映射，其中 invalid request 通常为 400、operation failure 通常为 500。当前不同接口对同一异常类别的 400/422、500/503 语义并不完全一致。

## 17. 可观测性、切换与回滚

### 17.1 指标

NL2AGENT 记录低基数、无敏感标签的计数器：

- Action success/replayed/pending/conflict/failure；
- workflow CAS conflict；
- installation retry/takeover/conflict/provider failure/heartbeat failure/replay/success；
- card parse success/failure；
- atomic message finalize success/conflict/failure；
- structured SSE sent/failure/stopped。

标签不包含 tenant/user ID、URL、payload、catalog 内容、错误文本、header、token 或 secret。

### 17.2 v3 切换

`deploy/sql/migrations/v2.4.0_0722_add_nl2agent.sql` 是不兼容重建：

- 先软删除旧 NL2AGENT Conversation/message；
- drop 旧 installation/session/catalog snapshot 表；
- 创建当前两张表和唯一索引；
- 清理重复 Builder Agent；
- 不把旧 workflow 转为 v3。

fresh deploy 的 `deploy/sql/init.sql` 已同步更新。部署前应备份数据库并运行：

```bash
source backend/.venv/bin/activate
python backend/scripts/check_nl2agent_cutover.py
```

检查会阻止非 v3 active Session、无效 catalog hash、遗留 `card_delivery/online_installations` 和未绑定 v3 Session 的 Builder Conversation。

如果检查明确给出旧 Session 和 Builder Conversation ID，应先停止 NL2AGENT 写流量并备份 PostgreSQL。先以只读模式预览精确清理目标，不修改数据：

```bash
python backend/scripts/cleanup_nl2agent_cutover.py --session-ids 4 5 --conversation-ids 12 13
```

确认一一映射和行数后，再执行带保护的软删除事务并重新运行切换检查：

```bash
python backend/scripts/cleanup_nl2agent_cutover.py --session-ids 4 5 --conversation-ids 12 13 --apply --confirm SOFT_DELETE_LEGACY_NL2AGENT
python backend/scripts/check_nl2agent_cutover.py
```

清理脚本会在 serializable 单事务中重新校验并锁定精确目标，拒绝健康 v3 Session 和普通 Conversation。它只软删除 Session、installation operation 和内部 Conversation/message/unit/source 图，保留 Draft Agent 及其资源绑定。

### 17.3 回滚

- 没有创建 v3 Session 时，可以停流量后回退应用；
- 一旦产生 v3 Session，旧二进制不能安全读取，必须同时恢复切换前数据库快照和应用版本；
- 不应仅回滚代码，也不应 force-push 已发布历史。

## 18. 代码量分布

### 18.1 NL2AGENT 专属文件状态

| 状态 | 文件 | 新增 | 删除 | 变更行 |
| --- | ---: | ---: | ---: | ---: |
| 新增文件 | 113 | 38,604 | 0 | 38,604 |
| 修改现有文件 | 70 | 4,673 | 1,284 | 5,957 |
| 合计 | 183 | 43,277 | 1,284 | 44,561 |

没有最终删除或重命名文件；中间协议的大量删除已被 30 个提交折叠进最终净差异。

### 18.2 按代码层分布

| 层 | 文件 | 新增 | 删除 | 变更行 | 新增占比 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Backend runtime | 55 | 13,181 | 515 | 13,696 | 30.5% |
| Tests | 50 | 13,251 | 19 | 13,270 | 30.6% |
| Generated contracts | 4 | 8,805 | 0 | 8,805 | 20.3% |
| Frontend runtime | 50 | 5,967 | 737 | 6,704 | 13.8% |
| SDK runtime | 11 | 1,256 | 9 | 1,265 | 2.9% |
| Documentation | 4 | 618 | 3 | 621 | 1.4% |
| Deployment/database | 9 | 199 | 1 | 200 | 0.5% |

这里把 `test/`、前端 `__tests__`/`*.test.*` 和 deploy tests 统一归入 Tests；根 contracts 和 frontend generated contracts 统一归入 Generated contracts。

可执行及部署代码合计新增 20,603 行、删除 1,262 行。Tests + Generated contracts 合计新增 22,056 行，占全部新增的 51.0%。这说明分支体量很大，但约一半是验证和合同派生，不是手写运行时代码。

### 18.3 按文件类型分布

| 类型 | 文件 | 新增 | 删除 | 新增占比 |
| --- | ---: | ---: | ---: | ---: |
| Python | 98 | 25,808 | 540 | 59.6% |
| JSON | 7 | 6,977 | 49 | 16.1% |
| TSX | 27 | 4,635 | 582 | 10.7% |
| TypeScript | 19 | 3,120 | 106 | 7.2% |
| TSX tests | 6 | 1,173 | 0 | 2.7% |
| Markdown | 4 | 618 | 3 | 1.4% |
| TS tests | 6 | 405 | 0 | 0.9% |
| YAML | 4 | 210 | 0 | 0.5% |
| SQL | 3 | 183 | 0 | 0.4% |
| Other/Shell/TOML/Dockerfile | 9 | 148 | 4 | 0.3% |

Python 占新增的 59.6%，符合后端状态、服务、数据库和 pytest 为主要复杂度来源的事实。JSON 的高占比主要来自 OpenAPI 和 Card Schema，而不是手写配置。

### 18.4 最大手写代码热点

| 文件 | 新增/删除 | 主要责任 |
| --- | ---: | --- |
| `backend/services/nl2agent_runtime_service.py` | `+1066/-0` | 生产依赖组装和 Facade |
| `backend/agents/nl2agent_session_catalog.py` | `+929/-0` | workflow mutation、proof、资源完成规则 |
| `backend/services/nl2agent_mcp_service.py` | `+897/-0` | MCP 解析、安装、发现和绑定 |
| `backend/services/nl2agent_catalog_service.py` | `+734/-0` | 目录加载、脱敏和 Web Skill 安装 |
| `frontend/components/nl2agent/FinalizeCard.tsx` | `+704/-0` | 最终配置审查和 Draft finalize |
| `backend/services/nl2agent_action_service.py` | `+531/-0` | 统一 Action、幂等和 proof 校验 |
| `frontend/components/nl2agent/LocalResourcesCard.tsx` | `+513/-0` | 本地资源选择与配置 |
| `backend/database/nl2agent_session_db.py` | `+509/-0` | Session repository、CAS 和清理 |
| `backend/consts/model.py` | `+507/-159` | Action 请求合同和 AgentRequest 扩展 |
| `sdk/.../search_web_mcps_tool.py` | `+460/-0` | MCP metadata 归一化和搜索 |
| `backend/consts/nl2agent_card.py` | `+424/-0` | Card/Envelope Pydantic 合同 |
| `frontend/components/nl2agent/WebMcpCard.tsx` | `+412/-0` | MCP 安装和 Tool binding UI |

这 12 个热点新增 7,686 行，占手写可执行/部署新增代码的 37.3%。前三个后端编排文件合计接近 2,900 行，是后续拆分和代码审查的首要区域。

### 18.5 测试与生成代码

50 个测试文件的净差异为 `+13,251/-19`：

- `test/` 下 37 个 Python 文件：`+11,666/-17`；
- 前端 12 个 Vitest 文件：`+1,578/-0`；
- deploy migration test 1 个：`+7/-2`。

主要覆盖 Session/CAS、Action 幂等、catalog proof、Card parser、installation runner、MCP SSRF、publication、历史恢复、前端卡片 lifecycle 和 SQL migration。

4 个生成合同文件共新增 8,805 行：OpenAPI 3,769 行、生成 API TypeScript 2,020 行、Card Schema 在根目录和前端各 1,508 行。

## 19. 代码审查发现的风险与建议方案

### 19.1 合入前优先处理

| 优先级 | 发现 | 建议设计 |
| --- | --- | --- |
| P0 | `origin/develop` 已有 3 个分支独有提交 | 先 merge/rebase，重点审查 sandbox/Skill 生命周期与 NL2AGENT MCP/Skill 安装交叉点，再重跑全部统计和测试 |
| P0 | MCP private-network 默认值在裸进程为 true、Docker/K8s 为 false | 将 `const.py` 默认统一为 false；若需要私网，要求部署显式开启并记录安全审计 |
| P0 | 多数 workflow mutation 仍使用 tenant + draft CAS | 将 `mutate_session_state`、proof 写入和资源 transition 改为接收 `Nl2AgentSessionIdentity`，删除 compatibility snapshot lookup |
| P0 | Action receipt 的 `pending` 没有 lease/超时回收 | 为 receipt 增加 claim owner/expiry 或基于 message update_time 的 stale reclaim；重放前先查询领域状态并安全对账 |
| P0 | revision mode 的“每轮只处理一个配置域”未由后端强制 | 在 `_validate_card_stage` 中限制 revision mode 最多一个 card type，并为 text-only 路由和多卡拒绝补测试 |

### 19.2 下一阶段收敛

| 优先级 | 发现 | 建议设计 |
| --- | --- | --- |
| P1 | `finalize/publish_agent/Review & Publish` 名称与 `draft_ready` 行为不一致 | 若仍只更新 Draft，统一改名为 finalize/apply；若需要发布，则显式调用版本创建流程并拆分权限 |
| P1 | completed retention 常量/helper 未使用，清理仅在 start 时触发 | 删除死配置或实现独立定时清理；为 active/abandoned/completed 分别定义可观测保留策略 |
| P1 | `Nl2AgentStaleCardError`、030203、Redis CAS docstring 等旧协议残留 | 删除无调用的旧异常和前端 helper，更新错误文案，避免运维误判当前协议 |
| P1 | catalog snapshot 可能接近多个 MiB，completed Session 无限期保留 | 增加 snapshot 大小指标和数据库告警；规模增长后迁移到按 hash 去重的 catalog snapshot 表 |
| P1 | 前端仍有中英文硬编码混用 | 把 Completed banner、OnlineConfigurationBar、Builder greeting 和配置页提示全部迁入 locale 文件 |
| P1 | 生命周期和 Action endpoint 的 400/422、500/503 不完全一致 | 为 NL2AGENT 建立统一 domain exception -> HTTP mapping，并在 OpenAPI/测试中固化 |
| P2 | `run_blocking_installation` 在取消时可能等待 provider thread `join()` | 采用可取消 provider client、受限线程池或非阻塞回收，避免取消请求阻塞 event loop |

### 19.3 推荐实施顺序

1. **Merge gate**：同步 `origin/develop`、统一网络默认、补全完整身份 CAS、Action stale reclaim、revision 单卡校验；
2. **Protocol cleanup**：移除 stale-card/Redis/旧 retention 残留，统一 finalize 和 HTTP 语义；
3. **Operational hardening**：独立清理调度、snapshot 大小指标、安装取消与超时；
4. **UX completion**：完整 i18n、端到端浏览器用例和故障恢复提示；
5. **Scale path**：catalog 去重存储、operation 对账任务和跨 Pod 恢复演练。

## 20. 合并与验收清单

### 20.1 合同和静态检查

```bash
cd frontend
npm run contracts:check
npm run type-check
npm run lint
npm run format:check
```

### 20.2 前端测试

```bash
cd frontend
npm run test
```

至少确认 Card lifecycle、历史恢复、completed resume、local config、Web Skill config 和 verification presentation。

### 20.3 后端与 SDK 测试

```bash
source backend/.venv/bin/activate
pytest test/backend/agents/test_nl2agent_session_catalog.py -v
pytest test/backend/apps/test_nl2agent_app_errors.py -v
pytest test/backend/services/test_nl2agent_action_service.py -v
pytest test/backend/services/test_nl2agent_installation_runner.py -v
pytest test/backend/services/test_nl2agent_mcp_service.py -v
pytest test/backend/utils/test_nl2agent_card_validation.py -v
pytest test/sdk/core/tools/test_nl2agent_search_tools.py -v
pytest test/contracts -v
```

### 20.4 数据库和切换

```bash
source backend/.venv/bin/activate
pytest test/deploy/test_local_sql_migrations.py -v
bash deploy/tests/test_sql_migrations.sh
python backend/scripts/check_nl2agent_cutover.py
python backend/scripts/cleanup_nl2agent_cutover.py --help
```

### 20.5 必测业务场景

- Session start 的全事务回滚；
- 同一 Action replay、不同 fingerprint 冲突和并发 revision 冲突；
- 空搜索结果卡；
- catalog hash 变化后的 Action 拒绝；
- 本地 Tool secret 配置不回显；
- MCP remote redirect/DNS rebinding/metadata endpoint 拒绝；
- MCP/Skill 安装失败、retry、lease takeover 和 completed replay；
- Assistant message 与 workflow 的原子回滚；
- 单一 `nl2agent_message` SSE 与历史消息完全一致；
- completed 只读、resume、revision、再次 finalize；
- tenant/user/runner/draft/conversation 任一不匹配时失败关闭；
- finalize 后只有 Draft ready，没有意外版本发布或市场副作用。

## 21. 主要实现位置

| 责任 | 文件 |
| --- | --- |
| HTTP 和错误映射 | `backend/apps/nl2agent_app.py` |
| 生产 Facade/依赖组装 | `backend/services/nl2agent_runtime_service.py` |
| Session 初始化 | `backend/services/nl2agent_session_service.py` |
| 生命周期 | `backend/services/nl2agent_session_lifecycle_service.py` |
| Workflow 合同与评估 | `backend/agents/nl2agent_workflow.py` |
| Workflow mutation/proof | `backend/agents/nl2agent_session_catalog.py` |
| PostgreSQL Session/CAS | `backend/database/nl2agent_session_db.py` |
| Action Dispatcher | `backend/services/nl2agent_action_service.py` |
| Card 合同/parser | `backend/consts/nl2agent_card.py`, `backend/utils/nl2agent_card_validation.py` |
| Assistant message 原子落库 | `backend/services/nl2agent_message_service.py` |
| Catalog snapshot/hash | `backend/utils/nl2agent_catalog_snapshot.py` |
| Catalog 与 Web Skill | `backend/services/nl2agent_catalog_service.py` |
| 本地资源 | `backend/services/nl2agent_resource_service.py` |
| MCP | `backend/services/nl2agent_mcp_service.py` |
| Durable runner | `backend/services/nl2agent_installation_runner.py` |
| MCP URL 安全 | `backend/services/nl2agent_mcp_url_security.py` |
| Finalize | `backend/services/nl2agent_publication_service.py` |
| Session projection | `backend/services/nl2agent_workflow_service.py`, `backend/services/nl2agent_summary_service.py` |
| SDK 搜索工具 | `sdk/nexent/core/tools/nl2agent/` |
| 前端工作流 | `frontend/components/nl2agent/Nl2AgentWorkflowContext.tsx` |
| Card Registry | `frontend/components/nl2agent/cardRegistry.tsx` |
| 前端 Action lifecycle | `frontend/components/nl2agent/useNl2AgentCardLifecycle.ts` |
| Chat/SSE 适配 | `frontend/app/[locale]/newchat/adapter/remote-chat-model-adapter.ts` |
| 合同生成 | `backend/scripts/export_nl2agent_openapi.py`, `frontend/scripts/sync-nl2agent-contracts.mjs` |
| v3 切换检查/清理 | `backend/scripts/check_nl2agent_cutover.py`, `backend/scripts/cleanup_nl2agent_cutover.py` |

## 22. 最终评价

相对 develop，当前 NL2AGENT 已完成从“LLM 输出 UI 文本”到“数据库权威、合同驱动、可恢复执行”的架构跃迁。最有价值的设计是把模型输出、用户动作和外部安装都置于服务端 proof、revision 和持久化 receipt 之后；这显著降低了重复执行、跨 Session 资源引用、历史无法恢复和前端解析漂移的风险。

当前合入风险不在功能缺失，而在跨层体量和少数尚未完全落地的强约束：完整身份 CAS、pending Action 恢复、revision 单卡门禁和网络默认一致性。先完成这些 P0 收敛，再处理命名、保留策略、旧协议残留和 i18n，当前方案即可形成较清晰的长期维护边界。
