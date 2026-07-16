# NL2AGENT 对话式智能体构建助手设计文档

> 版本：v2.0
>
> 对应实现：`96f8b800`（Jujutsu change `pznswxmy`）
>
> 对比基线：`4e7d9fe1`（Jujutsu change `lvnqqsqn`）
>
> 最后更新：2026-07-14

---

## 1. 概述

### 1.1 背景

传统智能体创建流程依赖用户直接填写业务描述、模型、提示词和资源配置。用户需要预先理解平台中的模型、工具、技能和 MCP，面对空白表单时缺少引导，也容易把推荐资源误认为已经安装或绑定。

NL2AGENT 在既有 Agent、Conversation、ToolInstance、SkillInstance 和 MCP 基础设施上增加一套对话式构建流程，引导用户完成需求澄清、模型选择、资源审查、MCP 安装、身份确认和最终方案生成。

NL2AGENT 本身是平台内部默认智能体，数据库名称为 `nl2agent`。每次构建会话创建独立的草稿 Agent，所有用户确认和资源绑定均作用于该草稿。

### 1.2 当前能力

1. 通过多轮对话理解目标、场景、输入、输出和约束。
2. 强制用户从平台当前可用 LLM 中选择一个主模型，并可配置最多四个有序备用模型。
3. 搜索租户本地 Tool 和 Skill，以推荐批次卡片让用户全部应用或明确跳过。
4. 搜索官方 Registry、社区 Marketplace 中的 MCP，支持在聊天卡片内完成配置、安装、健康检查、工具发现和选择性绑定。
5. 搜索并安装在线 Skill。
6. 根据需求自动生成 Agent 显示名称，由用户在身份卡片中检查、修改并保存。
7. 模型、本地资源、联网资源和身份卡片确认后自动触发下一轮生成，无需用户手工输入“请继续”。
8. 从数据库和 Redis 加载权威草稿状态，完成最终审核和草稿配置。

### 1.3 设计原则

- **复用既有运行链路**：聊天继续使用 `POST /agent/run` 和现有 SSE 流式执行链路。
- **显式阶段确认**：模型、资源、MCP、身份和最终配置均有明确的进入条件与完成状态。
- **持久化状态优先**：数据库和 Redis 是发布时的权威来源，不能使用 LLM 生成的资源 ID 或安装状态替代。
- **最小可调用工具集**：运行时只注册三个 NL2AGENT 搜索工具；应用、安装、绑定和最终配置通过用户操作卡片调用后端 API。
- **租户和草稿隔离**：Catalog、缓存、工作流状态和资源实例均按 tenant/draft 作用域隔离。
- **用户显式授权**：安装 MCP、提交凭据、绑定工具、跳过资源和最终发布必须由用户操作卡片确认。
- **不兼容已删除旧工具**：不为历史测试 Agent 或已移除的 NL2AGENT action tools 增加运行时兼容逻辑。

---

## 2. 总体架构

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Frontend                                                            │
│                                                                     │
│ Agent Builder 入口                                                   │
│      │                                                              │
│      ├─ POST /nl2agent/session/start                                │
│      └─ 保存 conversation_id → draft_agent_id 映射                   │
│                                                                     │
│ Chat / SSE                                                          │
│      │                                                              │
│      ├─ MarkdownRenderer                                            │
│      └─ NL2AGENT Cards                                              │
│         ├─ ModelSelectionCard                                       │
│         ├─ LocalResourcesCard                                       │
│         ├─ WebMcpCard                                               │
│         ├─ WebSkillCard                                             │
│         ├─ OnlineConfigurationBar（会话级完成配置）                  │
│         ├─ AgentIdentityCard                                        │
│         └─ FinalizeCard                                             │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTP / SSE
┌───────────────────────────────▼─────────────────────────────────────┐
│ Backend                                                             │
│                                                                     │
│ config service                                                      │
│      └─ Seed NL2AGENT 默认 Agent 和三个 builtin tools               │
│                                                                     │
│ runtime service                                                     │
│      ├─ /agent/run：既有聊天执行链路                                │
│      └─ /nl2agent/*：会话、模型、资源、MCP、身份、最终配置 API       │
│                                                                     │
│ nl2agent_service                                                    │
│      ├─ 校验租户与草稿所有权                                        │
│      ├─ 读写 Agent / ToolInstance / SkillInstance / MCP             │
│      └─ 读写 Redis Catalog 和工作流状态                              │
└───────────────────┬────────────────────────────┬────────────────────┘
                    │                            │
             ┌──────▼──────┐              ┌──────▼──────┐
             │ PostgreSQL  │              │ Redis       │
             │ Agent/资源  │              │ Catalog/状态│
             └─────────────┘              └─────────────┘
                    │
┌───────────────────▼────────────────────────────────────────────────┐
│ SDK Runtime                                                         │
│                                                                     │
│ NL2AgentSearchLocalResourcesTool                                    │
│ NL2AgentSearchWebMcpsTool                                           │
│ NL2AgentSearchWebSkillsTool                                         │
│                                                                     │
│ 每个 Tool 实例持有独立 Nl2AgentContext，不共享可变全局会话上下文     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心对象与状态

### 3.1 NL2AGENT 默认智能体

NL2AGENT 默认智能体是一条 `name="nl2agent"` 的内部 Agent 记录。它只负责运行构建对话，不是最终产物。

当前默认 Agent 只绑定三个 builtin tools：

| class_name | 运行时名称 | 职责 |
|---|---|---|
| `NL2AgentSearchLocalResourcesTool` | `nl2agent_search_local_resources` | 搜索当前租户本地 Tool 和 Skill |
| `NL2AgentSearchWebMcpsTool` | `nl2agent_search_web_mcps` | 搜索 Registry 和社区 MCP |
| `NL2AgentSearchWebSkillsTool` | `nl2agent_search_web_skills` | 搜索在线 Skill |

默认 NL2AGENT 和 `draft_*` Agent 不出现在普通 Agent 列表中。

### 3.2 草稿 Agent

每次调用 session start 都会创建独立草稿：

- 内部名称初始为 `draft_<uuid>`。
- 使用 `version_no=0` 保存草稿字段和资源实例。
- 草稿 ID 通过 `draft_agent_id` 传入运行链路和三个 SDK Tool。
- 最终配置时才根据持久化显示名称生成正式内部名称。

名称语义严格区分：

- `display_name`：用户可见标题，可在身份卡片中编辑。
- `name`：内部变量标识符，由后端生成，用户和 LLM 均不能指定。

内部名称必须满足：

```regex
^[A-Za-z_][A-Za-z0-9_]*$
```

生成策略：

1. 将可转换的 ASCII 显示名称规范化为 snake_case。
2. 冲突时追加 Agent ID。
3. 无法生成有效标识符时使用 `agent_{agent_id}`。
4. 最终长度不超过 50 个字符。

### 3.3 Redis Catalog

session start 拉取资源目录后写入 Redis：

```text
nl2agent:session_catalog:{tenant_id}:{draft_agent_id}
```

Catalog 包含：

```json
{
  "tool_catalog": [],
  "skill_catalog": [],
  "registry_results": [],
  "community_results": [],
  "official_skills": []
}
```

Catalog TTL 为 24 小时。SDK Tool 的构造数据来自该 Catalog，因此 session start 和 agent execution 可以运行在不同 worker。

Catalog 缺失、格式错误或 tenant/draft 标识不完整时必须显式报错并记录上下文，不能静默替换为空目录。

### 3.4 Redis 工作流状态

工作流状态使用独立 key：

```text
nl2agent:session_state:{tenant_id}:{draft_agent_id}
```

基础结构：

```json
{
  "requirements_review": {
    "status": "collecting",
    "summary": null,
    "fingerprint": ""
  },
  "recommendation_batches": {},
  "identity_confirmed": false,
  "mcp_workflows": {},
  "online_recommendation_batches": {},
  "online_configuration_confirmed": false
}
```

本地推荐批次状态：

- `recommendations_ready`
- `applied`
- `skipped`

MCP 工作流状态：

- `configuration_required`
- `installing`
- `connected`
- `tools_bound`
- `binding_skipped`
- `failed`

Redis 中不得保存用户提交的 secret 值。

联网推荐批次按 `recommendation_batch_id` 保存，记录 `resource_type`、去重后的结果键和 `recommendations_ready`/`completed` 状态。MCP 或 Skill 卡片实际渲染时幂等注册批次；出现新的批次会把 `online_configuration_confirmed` 重置为 `false`。当前流程强制审查 MCP 和在线 Skill 两个目录；即使搜索结果为空，也必须分别注册空结果批次后才能完成联网配置。

---

## 4. 对话构建流程

### 4.1 启动会话

1. 用户在 Agent 管理页点击 Agent Builder。
2. 前端调用 `POST /nl2agent/session/start`。
3. 后端确保当前租户存在 NL2AGENT 默认 Agent 和三个 builtin tools。
4. 后端创建草稿 Agent 和 Conversation。
5. 后端加载 Tool、Skill、Registry MCP、Community MCP 和在线 Skill Catalog。
6. Catalog 按 tenant/draft 写入 Redis。
7. 前端保存 Conversation 到 draft ID 的映射，并进入聊天。

主要返回字段：

```json
{
  "nl2agent_agent_id": 1,
  "draft_agent_id": 52,
  "conversation_id": 100,
  "draft_name": "draft_ab12cd34"
}
```

### 4.2 需求澄清

需求关卡要求用户明确提供并确认五项事实：

- Agent 目标
- 使用者或使用场景
- 主要输入；明确无输入的任务记为“无”
- 期望输出
- 关键约束；明确无特殊约束时记为“无”

五项内容必须来自用户明确表达，NL2AGENT 不得根据常识或上下文自行补全。`collecting` 状态下每轮只询问第一个缺失项；五项齐全后输出只读 `nl2agent-requirements-summary` 卡片并停止，不得同时选择模型或搜索资源。

摘要卡实际渲染后调用 `POST /nl2agent/session/{id}/requirements/register`。后端规范化字段并生成稳定 fingerprint。当前摘要返回 `is_current=true`；被新版替代的历史卡返回 `is_current=false`，不能覆盖 Redis 状态，也不显示确认按钮。注册失败时卡片显示错误和 Retry，同时阻止用户继续输入。

用户只能点击摘要卡中的“确认需求”按钮完成确认。按钮调用 `POST /nl2agent/session/{id}/requirements/confirm` 并携带当前 fingerprint；后端拒绝过期 fingerprint，相同版本重复确认保持幂等。确认成功后写入 `confirmed`，返回固定自动续跑文本并进入模型选择。

用户仍可在聊天框中说明修改。`/agent/run` 在保存消息和构造 Prompt 前只识别修改或否定意图，并将状态恢复为 `collecting`；“确认需求”“可以继续”“yes”等文字不再确认需求。修订后的新摘要必须产生不同 fingerprint，旧摘要重新挂载不能恢复、覆盖或确认当前版本。

模型选择、三个搜索工具和最终配置均以后端持久化的 `requirements_review.status=confirmed` 为前置条件。未完成的历史测试会话不做兼容恢复。

### 4.3 模型选择

NL2AGENT 不得说出、推荐、比较或编造模型。模型选项只能来自平台实时模型列表。

前端模型卡调用现有 `/model/llm_list`，只展示 `connect_status="available"` 的 LLM。用户必须选择：

- 一个主模型
- 零到四个有序备用模型

保存时后端再次校验：

- 模型属于当前租户
- 模型存在且类型为 LLM
- 当前连接状态可用
- 不存在重复 ID
- 总数不超过五个

保存结果写入草稿：

```text
business_logic_model_id = primary_model_id
model_ids = [primary_model_id, ...fallback_model_ids]
```

最终配置前会再次校验可用性；已删除或变为不可用的模型会阻止继续。

### 4.4 本地资源搜索和审查

模型确认后必须进行至少一次本地资源搜索。NL2AGENT 将完整需求提取为一组去重的原子关键词，并在一次调用中传入：

```html
<code>
result = nl2agent_search_local_resources(query="docx presentation generation")
print(result)
</code>
```

SDK 返回稳定批次 ID：

```json
{
  "agent_id": 52,
  "recommendation_batch_id": "local_...",
  "tools": [],
  "skills": []
}
```

前端卡片实际渲染后调用 register API。用户可以：

- Apply All：绑定卡片中的 Tool 和 Skill，并将批次标记为 `applied`。
- Continue Without Resources：将批次标记为 `skipped`。

推荐 ID 只表示候选，不表示已经选择。最终阶段只读取数据库中启用的 ToolInstance 和 SkillInstance。

### 4.5 在线 MCP 搜索、配置和绑定

本地资源审查完成后，NL2AGENT 必须调用一次 MCP 搜索，即使本地资源已经足够。当前实现不是在 Tool 每次执行时携带用户关键词实时请求 Marketplace，而是在 session start 时预取候选目录：

| 来源 | 预取调用 | 当前上限 |
|---|---|---:|
| 官方 Registry | `list_registry_mcp_services(search=None, limit=30)` | 30 |
| Community Marketplace | `list_community_mcp_services(search=None, limit=30)` | 30 |

经过敏感信息清理后，两组数据分别保存为 Redis Catalog 中的 `registry_results` 和 `community_results`。`nl2agent_search_web_mcps` 实际在该会话快照中执行关键词匹配，因此搜索范围是两个来源默认排序下各自前 30 条，而不是整个远程 Marketplace。

Registry 和 Community 数据会统一规范化为安全的推荐与安装结构：

- Remote URL 或 URL template
- Transport 类型
- URL variables
- Headers
- Environment variables
- Package/runtime
- Runtime arguments
- Package arguments
- Port 和 container configuration

字段元数据包含：

```text
name / label / description / type / required / secret / default / placeholder
```

当前 MCP 评分实际匹配规范化后的：

- `name`
- `description`
- `tags`（如果候选存在）

目前规范化 MCP 候选没有保留 Marketplace tags，因此生产数据主要按 MCP 名称和描述匹配。URL、transport、package identifier、环境变量、header、runtime arguments 和 container configuration 只用于安装配置，不参与搜索评分。

搜索前按 `recommendation_id` 和规范化名称去重；Registry 与 Community 同名时保留先进入候选集的 Registry 记录。评分后最多返回 5 条。

流程：

1. MCP 搜索返回 `recommendation_id` 和安装选项，并立即渲染汇总卡片。
2. URL、变量、Header、环境变量、JSON、端口、容器配置和凭据全部在 MCP 卡片内填写；NL2AGENT 不在聊天中逐项询问配置。
3. Secret 只能由用户在 MCP 卡片中填写，不得进入聊天、Prompt、Redis、日志或搜索响应。
4. 用户选择安装选项并确认安装。
5. 后端从 Redis Catalog 解析 recommendation，不信任 LLM 提供的 URL、命令或 package。
6. 后端校验配置、安装 MCP、执行健康检查并发现工具。
7. 卡片展示发现的工具。
8. 用户选择绑定部分工具，或者显式跳过绑定。

已安装但仅处于 `connected` 的 MCP 仍然未解决，必须进入 `tools_bound` 或 `binding_skipped` 才能最终配置。

### 4.6 在线 Skill

当前“在线 Skill”不是在搜索时访问外部 Skill Marketplace，而是调用 `get_official_skills_with_status(tenant_id)` 扫描部署环境中的 official skills ZIP 目录：

1. 枚举目录中的 `.zip` 文件，文件名作为 Skill 名称。
2. 查询当前租户是否已经存在同名 Skill。
3. 检查已安装 Skill 的本地资源目录是否存在。
4. 按“当前租户数据库记录 → 全局官方数据库记录 → ZIP 内 `SKILL.md`”的优先级补充 description 和 tags。
5. ZIP 或元数据解析失败时记录警告并使用空 description/tags，不中断整个目录加载。

候选结构为：

```json
{
  "skill_id": 10,
  "skill_name": "document-parser",
  "name": "document-parser",
  "description": "Parse common document formats.",
  "tags": ["document", "parser"],
  "source": "official",
  "status": "installable"
}
```

状态包括：

- `installable`
- `installed`
- `resource_missing`

session start 只把 `status="installable"` 的候选保存到 Redis `official_skills`。`installed` 会被完全过滤，避免重复推荐；`resource_missing` 也会被过滤，并记录包含 tenant、draft 和 Skill 名称的 warning。当前流程不会把缺失资源误报为已修复，也不提供自动修复能力。

后续 `nl2agent_search_web_skills` 只在这份会话快照中评分，并再次防御性过滤非 `installable` 状态。SDK 使用 `skill_name or name` 统一名称字段，名称、description 和 tags 都参与 OR fuzzy 匹配。评分后按 Skill ID 和规范化名称去重，最多返回 5 条。

安装成功后，后端从对应 tenant/draft 的 Redis `official_skills` 中移除同 ID 或同规范化名称的候选。SDK 不保存进程内搜索缓存；下一次 Agent Run 会从更新后的 Redis Catalog 构造新的不可变搜索工具实例，因此不会复用安装前结果。

安装结果进入当前租户的 Skill catalog；需要作为草稿资源使用时，仍应通过对应资源绑定流程形成 SkillInstance。在线 Skill 搜索的是当前部署已经提供的官方 Skill ZIP 包，不会发现 ZIP 目录之外的新 Skill。

### 4.7 Agent 身份确认

资源审查完成后，NL2AGENT 根据已确认需求自动生成简洁的 `display_name`，并预填身份卡片。不得要求用户在聊天中构思名称。

用户可以在卡片中修改并保存。保存后：

- `display_name` 写入草稿 Agent。
- Redis 设置 `identity_confirmed=true`。
- 后端返回只读的内部名称预览。

草稿数据库名称在此阶段仍保持 `draft_*`。

### 4.8 卡片确认后的自动续跑

需求摘要按钮确认、模型选择保存、本地资源 Apply/Skip、联网资源全局完成以及身份保存成功后，对应后端接口返回固定的 `chat_injection_text`：

```text
[[NL2AGENT_AUTO_CONTINUE]]
The previous card action completed successfully. Re-read the authoritative Current Session state and continue naturally from the next incomplete stage. Do not ask the user to type continue.
```

该文本不包含用户输入、模型或资源 ID、凭据以及下一阶段指令。后端只返回文本，不调用 `/agent/run`、不选择下一阶段，也不主动执行搜索或生成卡片。

前端使用 Conversation/draft 级 continuation coordinator 处理成功响应：

1. 校验当前 Conversation 和 draft 与发起卡片操作时一致。
2. 防止重复或并发续跑。
3. 将回调文本作为普通 user message 加入现有历史，并调用既有 `/agent/run` 流式链路。
4. 保留前缀消息正常持久化并参与消息索引，但聊天气泡和分享选择中隐藏。
5. 自动运行失败时保留同一回调文本，由全局 Retry continuation 操作重试；不要求用户输入“请继续”。

卡片重新挂载、历史会话恢复或读取到已保存状态不会触发续跑。只有用户本次操作的 API 成功返回回调文本时才会注入。

联网资源采用会话级全局确认，而不是每个推荐卡片分别推进：

- MCP 和 Skill 搜索响应都包含稳定的 `recommendation_batch_id`，空结果也形成批次。
- 所有已注册批次在输入区上方只显示一个“完成配置”栏，并汇总 MCP/Skill 批次数量。
- 缺少 MCP 或 Skill 任一批次时，“完成配置”按钮禁用并显示仍待展示的目录。
- 单项安装、绑定、跳过或失败只刷新权威状态，不自动触发下一轮。
- 存在 `installing` 或 `connected` MCP 时禁用完成操作；`connected` MCP 必须先绑定工具或显式跳过。
- 未尝试、未安装或安装失败的推荐允许通过全局完成操作统一放弃。
- 只有 MCP 和 Skill 两类批次都存在时，全局完成才把所有批次标记为 `completed`，设置 `online_configuration_confirmed=true`，然后返回固定回调文本。

每次自动续跑时，NL2AGENT 都重新读取注入到 system prompt 的 Current Session。回调文本只是新一轮生成的触发器，模型必须自行选择第一个未完成阶段，不能把文本本身当作状态成功证明。

### 4.9 卡片交付验收与自动恢复

卡片输出分为生成、最终消息校验、真实挂载与注册、用户操作完成四个阶段。流式回答和 Task Window 只显示“正在生成卡片”占位，不解析 JSON、不挂载组件，也不写入 Redis。只有完整的 assistant 最终消息才能进入严格校验；历史消息、只读或分享模式不会触发回滚和自动续跑。

前端统一校验七类卡片：需求摘要、模型选择、本地资源、MCP、在线 Skill、身份和最终审核。校验内容包括闭合 fence、合法 JSON、可信 conversation draft ID、单类卡片唯一性以及各类 schema。空的本地、MCP 或 Skill 搜索结果仍是有效卡片，但必须携带稳定批次 ID；非空资源必须包含名称和稳定资源标识，MCP 还必须包含可识别的安装选项。

最终卡片成功挂载后，需要注册批次的卡片先完成原有注册 API，再向 `POST /nl2agent/session/{id}/card-delivery` 回报 `rendered`。注册失败属于 API 故障，卡片显示“重试注册”并禁用操作按钮，不要求模型重新生成。输出截断、JSON/schema 错误或卡片缺失则回报 `failed`，后端只清理当前尚未确认的交付状态：

- 需求摘要恢复为 `collecting`，但已确认需求不清除。
- 本地资源只删除 `recommendations_ready` 批次，已 Apply/Skip 批次保留。
- MCP 或 Skill 只删除对应类型的未完成在线批次，并重置联网全局确认；安装、发现、绑定和显式跳过状态保留。
- 模型、身份和最终审核没有“已展示”批次可清理；已经保存的模型和身份永不回滚。

Redis `card_delivery` 按卡片类型记录最后 `message_key`、`card_key`、状态、失败原因和连续重试次数。同一消息回调幂等，不重复计数；成功交付把该类型计数清零。前两次生成失败由后端返回固定 `[[NL2AGENT_CARD_RETRY]]` 隐藏文本，前端通过既有 `/agent/run` 自动重试；第三次起停止自动调用并显示“重新生成卡片”按钮。回调只清理无效状态并提供文本，不选择下一阶段、不执行 Tool。

运行时不把完整 Redis JSON 交给模型解释，而是注入不含模型、Tool、Skill 或 MCP ID 的阶段摘要：

```json
{
  "draft_agent_id": 54,
  "requirements_review": {
    "status": "collecting|awaiting_confirmation|confirmed",
    "summary": {
      "goal": "...",
      "audience_or_scenario": "...",
      "primary_input": "...",
      "expected_output": "...",
      "key_constraints": "..."
    }
  },
  "model_selection_confirmed": true,
  "local_review_status": "missing|pending|complete",
  "online_review": {
    "mcp_batch_registered": false,
    "skill_batch_registered": false,
    "configuration_confirmed": false
  },
  "unresolved_mcp_count": 0,
  "identity_confirmed": false
}
```

该摘要是本次 Agent Run 开始时的快照。若本轮工具执行刚产生新 Observation，模型必须优先把 Observation 原样渲染为卡片，不能因为快照中的批次尚未注册而重复搜索。

### 4.10 最终审核和配置

满足以下条件后，NL2AGENT 直接输出 `nl2agent-finalize` 卡片，不调用 Skill 名称或不存在的 finalize Tool：

- 模型选择有效
- 需求摘要已经由用户通过当前摘要卡按钮确认
- 至少一张本地资源卡已经注册
- 所有推荐批次已经 applied 或 skipped
- 所有已安装 MCP 已经绑定工具或显式跳过
- MCP 和在线 Skill 两类推荐批次均已注册，包括空结果批次
- `online_configuration_confirmed=true`
- 身份已经确认

最终 proposal 必须包含：

- `business_description`
- `duty_prompt`
- `greeting_message`

可以包含描述、约束、few shots、示例问题和运行参数，但不得包含或编造身份、模型、Tool、Skill、MCP ID 或资源配置。

FinalizeCard 会先读取权威 session state：

- 加载中显示 loading。
- 加载失败显示后端错误和 Retry。
- 身份未确认或 proposal 不完整时禁用操作。
- 显示名称、内部名称、模型和资源只使用持久化状态。
- 模型按主模型、备用模型顺序显示平台名称，不显示模型 ID。
- 资源按来源分成“本地资源”和“联网资源”，每个 Tool/Skill 名称独占一行。`source=mcp` 的 Tool 和 `source=official` 的 Skill 归入联网资源，其余归入本地资源。
- Session State 无法解析任何持久化模型或资源引用时返回 `invalid_references`；卡片显示引用类型和 ID 用于排查，并禁用发布。
- 描述和 Prompt 字段使用 proposal。

后端最终生成正式内部名称、保存 proposal 字段，并保留数据库中现有的启用资源实例。发布前再次按 tenant 解析模型、Tool 和 Skill；失效引用返回 409，且校验必须发生在草稿更新之前，避免产生部分更新。成功时返回状态 `draft_ready`，随后进入既有 Agent 配置和版本发布流程。

---

## 5. 后端 API

所有接口前缀为 `/nl2agent`，聊天本身继续使用既有 `/agent/run`。

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/session/start` | 创建 NL2AGENT 会话、草稿和 Redis Catalog |
| POST | `/session/{id}/requirements/register` | 幂等注册已渲染的五项需求摘要 |
| POST | `/session/{id}/requirements/confirm` | 使用当前 fingerprint 确认需求并返回自动续跑文本 |
| POST | `/session/{id}/card-delivery` | 回报最终卡片渲染结果、幂等记录重试并安全回滚未确认阶段 |
| PUT | `/session/{id}/models` | 保存主模型和备用模型 |
| POST | `/session/{id}/local-resources/register` | 注册已经渲染的本地推荐批次 |
| POST | `/session/{id}/apply-local-resources` | 应用指定批次中的本地资源 |
| POST | `/session/{id}/local-resources/skip` | 显式跳过指定批次 |
| POST | `/session/{id}/online-recommendations/register` | 幂等注册已渲染的 MCP/Skill 推荐批次 |
| POST | `/session/{id}/online-configuration/complete` | 全局完成当前联网资源审查并返回自动续跑文本 |
| POST | `/session/{id}/mcp/install` | 安装 Redis 推荐目录中的 MCP |
| POST | `/session/{id}/mcp/{mcp_id}/bind-tools` | 绑定用户选择的 MCP tools |
| POST | `/session/{id}/mcp/{mcp_id}/skip-tools` | 显式跳过 MCP tool binding |
| POST | `/session/{id}/install-web-skill` | 安装在线 Skill |
| PUT | `/session/{id}/identity` | 保存显示名称并确认身份 |
| GET | `/session/{id}/state` | 读取权威草稿、模型/资源展示名称、失效引用和工作流状态 |
| POST | `/session/{id}/finalize` | 校验状态并完成草稿配置 |

### 5.1 关键请求结构

模型选择：

```json
{
  "primary_model_id": 1,
  "fallback_model_ids": [2, 3]
}
```

本地资源应用：

```json
{
  "recommendation_batch_id": "local_...",
  "tool_ids": [10, 11],
  "skill_ids": [20]
}
```

联网推荐注册：

```json
{
  "recommendation_batch_id": "online_...",
  "resource_type": "mcp",
  "item_keys": ["registry:example"]
}
```

模型、本地资源、联网全局完成和身份接口的成功响应包含固定的可选字段：

```json
{
  "agent_id": 54,
  "chat_injection_text": "[[NL2AGENT_AUTO_CONTINUE]]\nThe previous card action completed successfully..."
}
```

MCP 安装：

```json
{
  "recommendation_id": "registry:example",
  "option_id": "remote-0",
  "config_values": {
    "region": "cn"
  }
}
```

MCP 工具绑定：

```json
{
  "tool_ids": [101, 102]
}
```

身份保存：

```json
{
  "display_name": "文档演示生成助手"
}
```

### 5.2 鉴权和错误语义

每个操作都从认证信息获取 user/tenant，并校验草稿所有权。

- 草稿不存在：404
- 工作流未完成或状态冲突：409
- 非预期数据库、Redis 或安装错误：500，并记录 tenant/draft 上下文

---

## 6. SDK 搜索工具设计

### 6.1 独立上下文

每个 Tool 实例持有独立 `Nl2AgentContext`，包含：

- `agent_id`
- `draft_agent_id`
- `tenant_id`
- `user_id`
- `language`
- 本地 Tool/Skill catalog
- Registry/Community MCP catalog
- 在线 Skill catalog
- 已应用资源状态

构造一个 Tool 不得覆盖其他 Tool 的状态。SDK 不读取环境变量，所有上下文由 backend metadata 注入。

### 6.2 统一关键词匹配

三个搜索工具共用以下处理：

1. Unicode NFKC 归一化。
2. 大小写归一化。
3. 按空格、中英文标点和中英文边界提取原子关键词。
4. 删除空值、重复词和常见连接词。
5. 每个关键词分别匹配名称、描述和标签。
6. 使用 OR 语义，任一关键词达到阈值即可进入候选。
7. 多关键词命中获得更高排名。
8. 过滤弱相关结果，允许返回空结果。
9. `reason` 记录实际命中的关键词。

评分公式为：

```text
0.85 × 最佳关键词分数 + 0.15 × 关键词覆盖率
```

名称直接匹配权重最高，description/tags 匹配乘以 `0.9`，最低候选阈值为 `0.62`。长度不超过三个字符的关键词只允许精确子串匹配，避免 `ppt` 模糊命中 `http`。

上述是共享评分器的能力。当前各目录实际可搜索字段如下：

| 搜索类型 | 当前实际评分字段 | 不参与评分的字段 |
|---|---|---|
| MCP | `name`、`description` | URL、transport、package、headers、env、arguments、container config |
| 在线 Skill | `skill_name or name`、`description`、`tags` | 安装配置、ZIP 正文和其他未规范化元数据 |

结果限制和去重：

- 本地 Tool 和 Skill 统一排序，合计最多 5 条。
- 在线 MCP 最多 5 条，按 recommendation ID 和规范化名称去重；Registry 优先于同名 Community 记录。
- 在线 Skill 最多 5 条，按 Skill ID 和规范化名称去重。

### 6.3 搜索缓存

SDK 搜索缓存按以下维度隔离：

```text
tenant_id + draft_agent_id + tool_name + canonical_keyword_set
```

关键词集合与顺序、大小写和分隔符无关，因此 `DOCX PPT` 与 `ppt, docx` 使用同一缓存。缓存 TTL 为 10 分钟，MCP 搜索在 Tool 实例重建后也可复用同一会话缓存。

本地 `recommendation_batch_id` 由 draft ID、canonical query 和结果资源 ID 生成，等价查询产生稳定批次 ID。

---

## 7. Prompt 状态机与执行协议

中英文 YAML Prompt 定义一致的阶段顺序和卡片协议。

### 7.1 唯一下一动作

模型必须从上到下判断并只执行第一个匹配动作：

1. 本轮存在新搜索 Observation：原样输出对应结果卡，不再次搜索。
2. `requirements_review.status=collecting`：按目标、使用者/场景、主要输入、期望输出、关键约束顺序，只询问第一个缺失项；五项齐全时只输出需求摘要卡。
3. `requirements_review.status=awaiting_confirmation`：不重复摘要卡，只要求用户点击现有卡片中的确认按钮，或在聊天中说明修改；聊天文字不能完成确认。
4. `requirements_review.status=confirmed` 但模型未确认：只输出固定说明和模型选择卡。
5. 模型已确认但本地审查缺失：调用一次本地搜索。
6. 本地卡已展示但未 Apply/Skip：只提示处理现有卡片。
7. 本地审查完成但在线目录不完整：同时搜索缺失的 MCP/Skill 目录；两类都缺失时在同一 `<code>` 块各调用一次。
8. 两类在线批次已展示但未全局完成：只提示使用会话级“完成配置”。
9. 在线配置完成但身份未确认：生成显示名称并输出身份卡。
10. 身份已确认：直接输出 final review 卡，不自动发布。
11. 状态不一致：提示重新加载，不猜测阶段或生成卡片。

新 Observation 的卡片渲染优先级高于运行开始时的 Current Session 快照。工具调用与结果卡必须处于不同模型步骤，避免调用时序、重复搜索和伪造 Observation。

### 7.2 可执行 Tool 与卡片的区别

下划线名称是可执行 Tool：

```text
nl2agent_search_local_resources
nl2agent_search_web_mcps
nl2agent_search_web_skills
```

连字符名称是前端卡片：

```text
nl2agent-requirements-summary
nl2agent-model-selection
nl2agent-local-resources
nl2agent-web-mcps
nl2agent-web-skills
nl2agent-agent-identity
nl2agent-finalize
```

不存在 `nl2agent-search-*` 卡片。Skill 名称是执行说明，不是 Python 函数。

### 7.3 工具执行协议

运行时只执行字面量 `<code>...</code>` 中的调用。工具调用步骤必须只包含一个执行块，并始终保存、打印结果：

```html
<code>
result = nl2agent_search_web_mcps(query="docx parser extraction")
print(result)
</code>
```

模型必须等待真实 Observation，下一步才能把返回 JSON 原样放入对应卡片。不得把工具调用显示为普通 Markdown、行内代码或伪卡片。

一次资源审查中，每种搜索工具最多调用一次。所有相关关键词必须合并到一个 query；只有用户明确修改需求或搜索方向后才能再次搜索。

### 7.4 模型和最终方案约束

- 不得命名、推荐、比较或编造 LLM。
- 不得根据对话文字推断模型已保存，只读取注入的 current session state。
- 不得声称 MCP 安装或工具绑定成功，除非对应 API 已确认。
- 不得在聊天中请求 MCP URL、变量、Header、环境变量、JSON、端口、容器配置或 secret；全部由 MCP 卡片收集。
- 不得调用 `nl2agent_finalize_proposal(...)` 或任何 Skill 名称。
- 最终卡片是回复内容，不通过代码解释器执行。

---

## 8. 前端设计

### 8.1 Conversation 级 draft ID

前端维护 `conversation_id → draft_agent_id` 映射。运行 Agent、渲染流式消息、最终消息、任务窗口和 Markdown 卡片时都使用当前 Conversation 对应的 draft ID。

卡片 ID 解析规则：

1. Payload 有 ID 时使用 Payload ID。
2. Payload 缺失 ID 时使用可信 Conversation draft ID。
3. 两者冲突时拒绝渲染并显示 mismatch 错误。
4. 普通或历史 Conversation 没有映射时不得猜测 ID。

### 8.2 卡片组件

| 卡片 | 主要职责 |
|---|---|
| `RequirementsSummaryCard` | 只读展示五项需求，注册并按 fingerprint 确认；过期卡禁用确认，失败时 Retry |
| `ModelSelectionCard` | 加载平台可用 LLM，保存主模型和备用模型 |
| `LocalResourcesCard` | 注册推荐批次，Apply All 或 Continue Without Resources |
| `WebMcpCard` | 展示配置字段，安装、重试、发现和绑定 MCP tools |
| `WebSkillCard` | 安装在线 Skill |
| `OnlineConfigurationBar` | 会话级汇总联网批次，校验 MCP 已解决并显式完成配置 |
| `AgentIdentityCard` | 展示预填名称，允许修改并保存身份 |
| `FinalizeCard` | 加载权威状态，展示最终审核并完成草稿配置 |

### 8.3 MCP 卡片字段

根据 option schema 动态渲染：

- text
- secret
- number
- URL
- JSON

安装按钮启用前检查：

- 所有必填值已填写
- JSON 语法正确
- Port 在有效范围内
- URL template 不存在未解析变量
- 安装选项不是 unsupported

安装失败后保留用户输入并显示后端错误，允许修改后重试。

### 8.4 FinalizeCard

FinalizeCard 不信任 proposal 中的身份、模型和资源字段：

- 身份、内部名称、模型、Tool、Skill 和 MCP 状态来自 session-state API。
- 描述、提示词、欢迎语、示例问题和运行参数来自 proposal。
- state 加载失败时显示错误和 Retry，并禁用最终操作。
- `identity_confirmed=false` 或必要 proposal 字段为空时禁用最终操作。

### 8.5 Markdown 路由

`MarkdownRenderer` 识别 `nl2agent-*` fenced language，并交给 `tryRenderNl2AgentCard`。解析失败或 ID 不合法时渲染明确错误，不影响普通 Markdown、代码块和 Mermaid。

---

## 9. 权威数据与安全边界

| 数据 | 权威来源 |
|---|---|
| 五项需求摘要与确认状态 | Redis `requirements_review` |
| 主模型和备用模型 | 草稿 Agent 数据库字段 |
| Agent 显示名称 | 草稿 Agent `display_name` |
| 内部名称 | 后端根据持久化显示名称生成 |
| 本地 Tool/Skill 推荐状态 | Redis recommendation batches |
| 已绑定 Tool | 启用的 ToolInstance |
| 已绑定 Skill | 启用的 SkillInstance |
| MCP 安装和绑定状态 | Redis workflow + MCP/Tool 数据库记录 |
| MCP recommendation 和安装参数 | Redis session Catalog |
| Agent 描述和 Prompt | Finalize proposal，经后端字段校验后保存 |

安全规则：

- 所有资源操作校验 tenant 和 draft ownership。
- MCP 安装不接受 LLM 自由构造的 URL、命令或 package。
- Secret 不出现在搜索结果、Redis、日志和 API 响应中。
- Finalize 忽略 LLM 提供的模型和资源 ID。
- Finalize 重新校验模型当前可用性。
- 数据库或 Redis 非预期异常不能被解释为“无数据”或“名称可用”。

---

## 10. 数据库、部署与兼容性

### 10.1 数据库

当前方案没有新增数据库表或字段，也没有 SQL migration。复用：

- Agent 和 AgentVersion
- Conversation
- Tool catalog 和 ToolInstance
- Skill catalog 和 SkillInstance
- Model 配置
- MCP 服务与发现工具记录

### 10.2 启动顺序

配置服务负责启动 Seed，runtime 使用 Seed 后的 Agent 和 Tool catalog。部署或更新后推荐顺序：

1. 启动或重启 config service。
2. 确认日志中三个 NL2AGENT builtin tools 和默认 Agent Seed 成功。
3. 启动或重启 runtime service。
4. 使用新的 NL2AGENT Conversation 验证。

### 10.3 兼容性

- 不支持已删除的 `NL2AgentApplyLocalResourcesTool` 等旧 builtin tools。
- 不对旧测试 Agent 自动做 legacy reconciliation。
- 历史 Conversation 如果没有 conversation/draft 映射，不得猜测草稿 ID。
- Finalize request 只接受描述、Prompt、欢迎语、示例问题和受支持的 runtime options；旧的身份、模型和资源字段直接拒绝。

---

## 11. 关键文件

### Backend

- `backend/apps/nl2agent_app.py`
- `backend/services/nl2agent_service.py`
- `backend/agents/nl2agent_session_catalog.py`
- `backend/agents/create_agent_info.py`
- `backend/agents/default_agents/nl2agent.json`
- `backend/database/tool_db.py`
- `backend/prompts/nl2agent_system_prompt_en.yaml`
- `backend/prompts/nl2agent_system_prompt_zh.yaml`

### SDK

- `sdk/nexent/core/tools/nl2agent/_context.py`
- `sdk/nexent/core/tools/nl2agent/search_local_resources_tool.py`
- `sdk/nexent/core/tools/nl2agent/search_web_mcps_tool.py`
- `sdk/nexent/core/tools/nl2agent/search_web_skills_tool.py`
- `sdk/nexent/core/agents/nexent_agent.py`

### Frontend

- `frontend/services/nl2agentService.ts`
- `frontend/lib/chat/nl2agentDraftContext.ts`
- `frontend/lib/chat/nl2agentContinuation.ts`
- `frontend/components/nl2agent/`
- `frontend/components/common/markdownRenderer.tsx`
- `frontend/app/[locale]/chat/internal/chatInterface.tsx`

### Tests

- `test/backend/services/test_nl2agent_service.py`
- `test/backend/agents/test_nl2agent_session_catalog.py`
- `test/backend/utils/test_prompt_template_utils.py`
- `test/sdk/core/tools/test_nl2agent_search_tools.py`
- `frontend/components/nl2agent/__tests__/nl2agentCards.test.tsx`

---

## 12. 验证清单

### Seed 与会话

- [ ] 每个目标租户存在三个 `category='nl2agent'` builtin Tool catalog rows。
- [ ] 默认 `nl2agent` Agent 只绑定三个搜索工具。
- [ ] session start 返回 NL2AGENT Agent ID、draft ID 和 Conversation ID。
- [ ] Catalog 已按 tenant/draft 写入 Redis。
- [ ] 普通 Agent 列表不展示默认 NL2AGENT 和 `draft_*` Agent。

### 模型

- [ ] 模型卡只展示平台当前可用 LLM。
- [ ] 不存在、非 LLM、不可用、重复或跨租户模型均无法保存。
- [ ] 最终配置时模型变为不可用会被拒绝。

### 需求确认

- [ ] 五项需求缺少任一项时，每轮只询问第一个缺失项。
- [ ] 五项齐全后只输出只读需求摘要卡，不提前选择模型或搜索。
- [ ] 摘要注册幂等，历史卡不能覆盖新版摘要。
- [ ] 只有当前 fingerprint 对应卡片的确认按钮可以写入 `confirmed`。
- [ ] “确认需求”“可以继续”“yes”等聊天文字不会确认需求。
- [ ] 明确修改或否定表达会返回 `collecting` 并生成新版摘要。
- [ ] 摘要注册失败时可以 Retry，且注册成功前不能提交确认消息。
- [ ] 未确认需求不能保存模型、调用三个搜索工具或最终配置。

### 本地资源

- [ ] 搜索按原子关键词 OR 模糊匹配并过滤弱结果。
- [ ] Tool 和 Skill 合计最多返回 5 条。
- [ ] 卡片渲染后 recommendation batch 只注册一次。
- [ ] Apply All 和 Skip 只解决指定批次。
- [ ] 未展示卡片或存在未解决批次时无法最终配置。

### MCP

- [ ] Registry 和 Community 数据规范化为统一安装 option。
- [ ] Secret 默认值不会进入响应、Redis 或日志。
- [ ] 缺少必填配置、非法 JSON/Port、未解析 URL template 会被拒绝。
- [ ] 安装、健康检查和工具发现成功后显示稳定 tool ID。
- [ ] 用户可以选择性绑定或显式跳过。
- [ ] `connected` 状态会阻止最终配置。

### 身份与最终配置

- [ ] NL2AGENT 自动生成并预填显示名称。
- [ ] 用户保存身份后 Redis 记录 `identity_confirmed=true`。
- [ ] 内部名称由后端生成并处理冲突、纯中文和数字开头情况。
- [ ] FinalizeCard 加载失败时显示 Retry 且不能继续。
- [ ] 最终配置忽略 proposal 中伪造的身份、模型和资源 ID。
- [ ] 最终配置只使用启用的 ToolInstance 和 SkillInstance。

### 会话隔离与卡片

- [ ] Conversation 切换时使用各自映射的 draft ID。
- [ ] Payload ID 与 Conversation draft ID 冲突时拒绝卡片。
- [ ] `nl2agent-search-*` 伪卡片不会被当成结果卡片。
- [ ] 三个搜索工具每种资源审查只调用一次并输出一张合并卡片。
- [ ] 模型、本地资源、联网全局完成和身份保存后自动注入隐藏 user message 并续跑。
- [ ] 隐藏续跑消息正常持久化，但不显示气泡且不进入分享选择。
- [ ] 卡片重挂载和状态恢复不会重复续跑，Conversation 切换不会跨会话注入。
- [ ] 自动续跑失败可用原文本重试，不要求用户输入“请继续”。
- [ ] MCP/Skill 联网批次只显示一个全局完成栏，新批次会重置完成状态。
- [ ] 单项联网操作不会自动续跑，未解决的 `connected` MCP 会禁用全局完成。

---

## 13. 已知限制与后续事项

1. Redis Catalog 和工作流状态 TTL 为 24 小时，超时的未完成会话需要重新开始或增加产品级恢复策略。
2. SDK 不再保存进程内搜索缓存；每次 Agent Run 通过 Backend 注入的不可变 Catalog 重新构建搜索工具并计算结果。
3. 放弃的 `draft_*` Agent 仍可能累积，后续可增加显式丢弃操作或定时清理策略。
4. 在线 Skill 安装和草稿 SkillInstance 绑定是不同概念，交互上应继续明确区分“已安装到租户”和“已应用到当前草稿”。
5. 最终配置返回 `draft_ready`，正式版本发布继续复用平台既有评审和发布流程，不自动发布。
6. 已删除过时的 `nl2agent_finalize_proposal` Skill 及生成脚本；最终方案由模型直接输出 `nl2agent-finalize` 卡片，发布仍由用户显式触发。
7. MCP 搜索只覆盖 session start 时获取的 Registry 和 Community 各前 30 条，用户查询不会实时下推到远程 Marketplace；默认排序之外的 MCP 可能无法被发现。
8. 在线 Skill 搜索实际扫描 official ZIP 目录，不是远程互联网检索；目录之外的 Skill 不会成为候选。
9. `resource_missing` Skill 当前只会被过滤并记录上下文 warning，不提供重新安装或资源修复按钮；修复能力不在当前范围。

## 14. v2 工作流、契约与服务边界

### 14.1 Redis v2 State

Session State 使用 `schema_version=2`、单调 `revision` 和权威 `conversation_id`。所有 mutation 通过统一 Repository 执行 Redis `WATCH/MULTI` CAS；旧 schema、损坏 JSON 或缺失状态会返回初始化错误，不会替换为空状态。

Backend 的纯函数 Workflow Evaluator 是阶段判断的唯一来源，输出：

- `current_stage`
- `expected_card_types`
- `allowed_actions`
- 需求、模型、本地审查、联网审查、MCP 和身份摘要

System Prompt 不再复制 Redis 字段组合规则，只根据上述摘要选择唯一动作；Fresh Observation 只在渲染本轮真实搜索结果时优先于运行开始快照。

### 14.2 Card Delivery

Card Delivery 请求使用数据库整数 `message_id`。Backend 仅接受属于当前 Session Conversation、角色为 assistant、状态为 completed 且是最新完成 assistant 消息的回执。失败回执不修改需求、推荐批次或资源绑定等业务状态。

Frontend 使用 conversation/draft/message 作用域记录 `pending/succeeded/failed`，只有 API 成功后才标记完成；历史、分享、只读消息和组件重挂载不会提交回执或自动续跑。

### 14.3 Canonical Card Contract

七类卡片共用 `contracts/nl2agent-card.schema.json`：

- Requirements Summary
- Model Selection
- Local Resources
- Web MCP
- Web Skill
- Agent Identity
- Final Review

Frontend 通过 `contracts:generate` 同步 Schema，并由 `contracts:check` 检查漂移。Ajv 负责一次解析和 schema 校验，生成的 card AST 同时提供 payload、可信 conversation draft ID、card type、card key 和注册要求；renderer 不再二次 `JSON.parse`。

### 14.4 当前服务拆分

- `nl2agent_publication_service.py`：发布前权威模型/资源/身份校验及 draft 更新。
- `nl2agent_resource_service.py`：本地资源批次注册、原子 Apply All 与 Skip。
- `nl2agent_catalog_service.py`：加载 Tool、Skill、Registry MCP、Community MCP 与官方 Skill Catalog，并在写入 Session 前统一脱敏。
- `nl2agent_workflow_service.py`：在线审查、Card Delivery、需求确认、Session State 投影与身份确认。
- `nl2agent_mcp_service.py`：MCP 发现后的 Tool provenance 校验、绑定与显式跳过。
- `nl2agent_service.py`：当前仍作为兼容 facade，并暂时承载 Session 初始化、MCP 安装和 Skill 流程；这些职责会继续拆分。

所有 HTTP 错误通过结构化领域异常和固定 ErrorCode 映射，包括 draft not found、workflow conflict、stale card、state conflict 和 catalog unavailable，不再依赖英文错误字符串。

### 13.1 在线 Skill 搜索实现保证

- [x] Skill 名称中的关键词能够参与精确和模糊匹配。
- [x] Skill description 和 tags 参与匹配。
- [x] Backend Catalog 同时提供 `name` 和 `skill_name`，SDK 使用统一回退规则。
- [x] 已安装 Skill 不会被当作新的可安装推荐重复展示。
- [x] `resource_missing` 不会与 `installable` 混淆，并会产生 tenant/draft 上下文 warning。
- [x] 名称、描述、tags、状态过滤、元数据容错和安装后缓存失效均有聚焦测试覆盖。
