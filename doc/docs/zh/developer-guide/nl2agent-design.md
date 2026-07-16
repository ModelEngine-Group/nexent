# NL2AGENT 对话式智能体构建设计

> 文档快照：2026-07-16
>
> 对比基线：Jujutsu revision `lvnqqsqn`（Git commit `4e7d9fe1`）
>
> 当前实现：Git commit `604151c6`；其上的工作副本 `@` 在编写本文前为空
>
> 扫描范围：Backend、SDK、Frontend、Prompt、Contract、测试与开发文档，共 106 个变更文件，约 22,500 行新增、643 行删除

本文描述当前代码已经实现的行为，不把未落地的规划、已删除的兼容逻辑或历史测试会话的恢复方案写成现有能力。模块级调用链和函数入口见《[NL2AGENT 代码走读](./nl2agent-code-walkthrough)》，重构状态与仍存问题见《[NL2AGENT 代码坏味道审查](./nl2agent-code-smell-review)》。

---

## 1. 背景、目标与边界

### 1.1 解决的问题

传统 Agent 创建页要求用户先理解模型、Tool、Skill、MCP、提示词和运行参数。NL2AGENT 将创建过程改造成受后端状态机约束的对话流程：模型负责澄清和生成方案，用户在结构化卡片中完成具有副作用的选择，Backend 以数据库和 Redis 的持久化状态决定能否进入下一阶段。

### 1.2 当前能力

当前实现支持：

1. 收集目标、受众或场景、主要输入、期望输出和关键约束五项需求。
2. 生成只读需求摘要，由用户通过按钮确认；聊天中的“确认”“继续”不会确认需求。
3. 仅从平台实时可用 LLM 列表选择一个主模型和最多四个有序备用模型。
4. 搜索租户本地 Tool 与 Skill，用户可选择应用推荐项或明确跳过。
5. 搜索官方 Registry 和 Community Marketplace 的 MCP 推荐，卡片内完成配置、安装、健康检查、工具发现、绑定或跳过。
6. 搜索部署环境 official Skill ZIP Catalog 中尚未安装的 Skill，并由用户逐项安装。
7. 用一个会话级“完成配置”动作结束 MCP 与 online Skill 审查。
8. 由 NL2AGENT 生成显示名称建议，用户可修改并保存；内部变量名由 Backend 生成。
9. 从权威持久化状态解析模型和资源名称，展示最终审核卡并由用户显式提交。
10. 卡片操作成功后通过隐藏普通 user message 自动继续现有 `/agent/run`，无需用户输入“请继续”。
11. 对截断、无效或缺失卡片进行交付回执，前两次自动重新生成，之后提供手动恢复。

### 1.3 明确不做的事情

- 不为已删除的 `NL2AgentApplyLocalResourcesTool` 等旧 action tools 增加兼容。
- 不为未完成的历史 NL2AGENT 测试 Session 迁移 Redis v1 状态。
- 不新增数据库表、列或迁移脚本；复用 Agent、Conversation、ToolInstance、SkillInstance 和 MCP 表。
- SDK 不访问 Redis、不读取环境变量，也不持有跨 Agent Run 的搜索缓存。
- 模型不能自行安装、绑定、跳过或发布；所有副作用都由用户操作卡片触发 HTTP API。
- “online Skill 搜索”不是实时公网检索，而是搜索 Backend 启动环境可访问的 official Skill ZIP Catalog。

---

## 2. 核心术语与身份

| 术语 | 含义 | 权威标识 |
|---|---|---|
| NL2AGENT Runner | Config Service seed 的内部默认 Agent，数据库内部名为 `nl2agent`，负责执行构建对话 | `nl2agent_agent_id` |
| Draft Agent | 每次 Session Start 新建的待配置 Agent，初始内部名为 `draft_<uuid8>` | `draft_agent_id` |
| Conversation | 本次构建流程使用的聊天会话 | `conversation_id` |
| Session State | Redis 中严格校验的 v2 工作流状态，决定当前阶段和允许动作 | tenant + draft |
| Session Catalog | Session Start 时加载并写入 Redis 的搜索候选快照 | tenant + draft |
| Card Delivery | 对最新完整 assistant 消息中卡片是否成功交付的回执 | conversation + message + card type |
| Persisted Binding | 数据库中启用的 ToolInstance、SkillInstance、模型选择和 MCP 记录 | tenant + draft |

Runner 和 Draft 是两个不同 Agent。对话由 Runner 执行，但模型选择、资源绑定、身份和最终配置都写入 Draft。Frontend 维护 `conversation_id → draft_agent_id` 映射，不能使用全局“最近一次 Draft ID”替代该映射。

---

## 3. 总体架构

```text
Config Service
  └─ seed nl2agent runner + exactly 3 builtin search tools

Frontend Agent Builder Entry
  └─ POST /nl2agent/session/start
       ├─ Backend validates seeded runner and loads catalogs
       ├─ PostgreSQL creates Draft Agent + Conversation
       ├─ Redis creates v2 State + Session Catalog
       └─ Frontend stores conversation → draft mapping

Existing Chat /agent/run + SSE
  ├─ Backend injects structured Current Session summary
  ├─ Backend constructs exactly 3 per-run SDK search-tool instances
  ├─ YAML system prompt chooses one action from workflow summary
  └─ Final assistant message emits fenced NL2AGENT card JSON

Frontend Card Runtime
  ├─ Ajv validates canonical card schema
  ├─ React card mounts and registers recommendation batch if required
  ├─ Card Delivery receipt confirms rendered/failed
  ├─ User action calls /nl2agent/session/{draft}/...
  └─ Successful stage action injects hidden user text and calls /agent/run again

Backend Sources of Truth
  ├─ PostgreSQL: Draft, model selection, bound Tool/Skill, MCP and final proposal
  └─ Redis: workflow confirmation state, catalogs, recommendation batches,
             MCP workflow projection and card delivery receipts
```

### 3.1 Backend 服务边界

| 模块 | 当前职责 |
|---|---|
| `backend/services/nl2agent_session_service.py` | Session 初始化、Catalog 前置加载、数据库与 Redis 补偿 |
| `backend/services/nl2agent_catalog_service.py` | 本地、MCP、official Skill Catalog 加载、脱敏和 Skill 安装后刷新 |
| `backend/services/nl2agent_resource_service.py` | 本地推荐批次注册、事务性 Apply、Skip |
| `backend/services/nl2agent_mcp_service.py` | MCP 规范化、配置校验、安装锁、可恢复安装、发现、绑定与跳过 |
| `backend/services/nl2agent_workflow_service.py` | 需求、在线批次、Card Delivery、Session State、身份 |
| `backend/services/nl2agent_publication_service.py` | 发布前门禁、权威引用校验和 Draft 最终更新 |
| `backend/services/nl2agent_service.py` | 兼容 facade、依赖装配、seed、模型选择与展示投影等共享辅助逻辑 |

`nl2agent_service.py` 尚未完全退化为薄 facade；它仍承载 seed、模型校验、内部名称生成和 Session State 展示信息解析。这是当前实现边界，而不是文档遗漏。

### 3.2 SDK 运行时边界

运行时只注册三个 builtin tool：

- `NL2AgentSearchLocalResourcesTool` → `nl2agent_search_local_resources`
- `NL2AgentSearchWebMcpsTool` → `nl2agent_search_web_mcps`
- `NL2AgentSearchWebSkillsTool` → `nl2agent_search_web_skills`

每个实例拥有独立的 `Nl2AgentContext`。上下文包含 tenant、user、Runner/Draft ID、语言、`requirements_confirmed` 和该工具需要的 Catalog。它不是 module-level global，因此构造某个工具不会覆盖另一个工具的状态；当前 dataclass 和内部 List 并未使用 frozen/深拷贝强制不可变，搜索实现只是按只读快照使用它们。

Skill 是模型执行说明，Card 是最终回复协议；二者都不是 Python 函数。`nl2agent_finalize_proposal` 未注册为 runtime tool，也不会被调用。

---

## 4. 权威数据与一致性模型

### 4.1 PostgreSQL 中的权威数据

不新增 schema，复用现有表：

- Agent：Draft 的显示名称、内部名称、主模型、模型顺序、提示词和运行参数。
- Conversation：Session 对应会话及消息归属。
- ToolInstance：Draft 已启用的本地 Tool 或 MCP Tool。
- SkillInstance：Draft 已启用的本地 Skill 或已安装 official Skill。
- MCP：已创建的远程或容器 MCP、连接配置和 Registry provenance。

最终审核和最终提交不信任 LLM payload 中的模型或资源引用。Backend 重新读取上述持久化记录并解析名称、来源和有效性。

### 4.2 Redis Key

| 用途 | Key 形式 | TTL |
|---|---|---|
| Session Catalog | `nl2agent:session_catalog:{tenant_id}:{draft_agent_id}` | 24 小时 |
| Workflow State | `nl2agent:session_state:{tenant_id}:{draft_agent_id}` | 24 小时 |
| MCP 安装锁 | `nl2agent:mcp_installation_lock:{tenant_id}:{draft_agent_id}:{installation_key}` | 5 分钟 |

Session State 每次成功更新都会刷新 TTL。Catalog 也在 CAS 更新时刷新 TTL。

### 4.3 v2 Workflow State

核心结构如下：

```json
{
  "schema_version": 2,
  "revision": 17,
  "conversation_id": 301,
  "requirements_review": {
    "status": "collecting|awaiting_confirmation|confirmed",
    "summary": {
      "goal": "...",
      "audience_or_scenario": "...",
      "primary_input": "...",
      "expected_output": "...",
      "key_constraints": "..."
    },
    "fingerprint": "sha256..."
  },
  "model_selection_confirmed": true,
  "recommendation_batches": {},
  "online_recommendation_batches": {},
  "online_configuration_confirmed": false,
  "mcp_workflows": {},
  "identity_confirmed": false,
  "card_delivery": {}
}
```

State 使用 Pydantic 严格模型验证。Key 缺失、schema 不是 v2 或 JSON/字段损坏会产生明确的初始化/工作流错误，不会回退为空状态。历史未完成 Session 不自动迁移。

### 4.4 原子更新

所有 State 修改经过同一 CAS mutator：

1. `WATCH` State Key。
2. 读取并严格解析 v2 State。
3. 在内存中执行单一 mutator。
4. `MULTI` 写回完整 JSON，`revision + 1` 并刷新 TTL。
5. 冲突最多重试 5 次；耗尽后返回 `AGENTSPACE_NL2AGENT_STATE_CONFLICT`。

Catalog 删除已安装 MCP/Skill 推荐也使用 `WATCH/MULTI`，但 Catalog 本身没有 `revision` 字段。

---

## 5. 确定性工作流

`backend/agents/nl2agent_workflow.py::evaluate_workflow` 是 Backend、Prompt 和 Frontend 消费的权威阶段评估器。它从持久化 State 生成：

- `current_stage`
- `expected_card_types`
- `allowed_actions`
- requirements/model/local/online/identity 摘要
- `unresolved_mcp_count`

### 5.1 阶段表

| 优先级 | `current_stage` | 进入条件 | 期望卡片 | 允许动作 / 完成条件 |
|---:|---|---|---|---|
| 1 | `requirements_collecting` | 五项需求未形成已注册摘要 | 无；模型每轮只问第一个缺失项 | 生成完整摘要后输出 `requirements_summary` |
| 2 | `requirements_confirmation` | 摘要已注册，状态为 `awaiting_confirmation` | 未成功交付时为 `requirements_summary` | 用户在卡片点击确认；聊天确认无效 |
| 3 | `model_selection` | requirements 已确认，模型未确认 | 未成功交付时为 `model_selection` | 保存一个主模型和最多四个 fallback |
| 4 | `local_resource_search` | 模型已确认，本地批次不存在 | `local_resources` | 调用一次本地搜索并交付结果卡 |
| 5 | `local_resource_review` | 存在 `recommendations_ready` 批次 | 已交付后为空 | Apply 所选推荐或 Skip；所有批次均 resolved |
| 6 | `online_resource_search` | 本地完成，但 MCP 或 Skill 批次缺失 | 缺哪类就期望哪类 Card | 每类最多调用一次搜索；空结果也注册批次 |
| 7 | `online_resource_review` | 两类批次已存在但未全局完成，或 MCP 未解决 | 卡已交付后为空 | MCP connected 必须 bind/skip；然后点击会话级完成配置 |
| 8 | `agent_identity` | online 完成但身份未确认 | 未成功交付时为 `agent_identity` | 保存 display name，Redis 记录确认 |
| 9 | `final_review` | 前述关卡全部完成 | 未成功交付时为 `final_review` | 用户显式提交；不自动发布 |

对于处在“等待用户操作”的卡片，只有 `card_delivery` 中存在成功 `rendered` 回执，Evaluator 才会把该 Card 从 `expected_card_types` 中移除。模型尝试输出 Card 不等于 Card 已展示。

### 5.2 Fresh Observation 优先级

Current Session 是一次 Agent Run 开始时的快照。调用搜索工具后，Redis 批次尚未由前端注册，因此快照仍可能显示批次缺失。双语 Prompt 明确规定：

1. 本步骤出现新的搜索 Observation 时，优先把该 Observation 原样封装成对应卡片。
2. 不得因为旧快照仍显示缺失而再次调用搜索工具。
3. Card 最终消息验收和批次注册成功后，下一轮才会看到更新后的状态。

---

## 6. Session 初始化

### 6.1 启动职责

Config Service 是唯一 seed 入口。启动时先同步 Prompt Template，再 seed：

- 名为 `nl2agent` 的内部默认 Runner；
- category 为 `nl2agent` 的三个 builtin search tools；
- Runner 与三个 Tool 的绑定。

Runtime Service 不再 lazy seed，只挂载 NL2AGENT Router。若默认 Runner 不存在，Session Start 明确提示先重启 Config Service。

### 6.2 初始化顺序与补偿

`start_nl2agent_session` 的顺序为：

1. 验证 seed 的 Runner 存在。
2. 加载并验证全部 Catalog；合法空 Catalog 与加载异常区分。
3. 在一个数据库事务中创建 Draft Agent 和 Conversation 并取得 ID。
4. 初始化 Redis v2 State，写入权威 `conversation_id`。
5. 写入 tenant/draft Session Catalog。
6. 提交数据库事务并返回 Runner、Draft、Conversation ID。

Catalog 失败发生在创建数据库对象之前。Redis 写入失败会使数据库事务回滚并清理已写 Redis；数据库最终提交失败也会删除刚写入的 Redis Keys。该流程不通过后台补偿任务异步修复。

### 6.3 Catalog 内容

Session Catalog 包含：

- `local_tools`
- `local_skills`
- `registry_mcps`
- `community_mcps`
- `official_skills`

Registry、Community、official Skill 或本地 Catalog 的 provider 异常返回 503；合法空数组仍允许创建 Session 并在后续显示空结果卡。

---

## 7. Agent Run 与 Prompt 上下文

### 7.1 Draft ID 传播

Frontend 在 `/agent/run` 请求中传递 `draft_agent_id`。Backend 只有在当前 Runner 的内部名为 `nl2agent` 时才构造 NL2AGENT 专用上下文。

在保存本轮用户消息、构造 Prompt 和运行模型之前，Backend 会检查需求修改意图：明确的修改、否定或纠正表达可把 `awaiting_confirmation` 恢复为 `collecting`；“确认”“yes”“继续”等文字不会确认需求。隐藏自动续跑消息不会改写需求状态。

### 7.2 Current Session 摘要

Backend 不把完整 Redis JSON 交给模型解释，而是注入结构化摘要，例如：

```json
{
  "schema_version": 2,
  "revision": 17,
  "draft_agent_id": 54,
  "current_stage": "online_resource_search",
  "expected_card_types": ["web_mcp", "web_skill"],
  "allowed_actions": ["search_web_mcp", "search_web_skill"],
  "requirements_review": {
    "status": "confirmed",
    "summary": {
      "goal": "...",
      "audience_or_scenario": "...",
      "primary_input": "...",
      "expected_output": "...",
      "key_constraints": "..."
    }
  },
  "model_selection_confirmed": true,
  "local_review_status": "complete",
  "online_review": {
    "mcp_batch_registered": false,
    "skill_batch_registered": false,
    "configuration_confirmed": false
  },
  "unresolved_mcp_count": 0,
  "identity_confirmed": false
}
```

摘要不向模型暴露所选模型 ID、Tool/Skill/MCP ID、凭据或资源配置。

### 7.3 双语 Prompt 约束

英文和中文 YAML 使用同一章节顺序与状态协议：

- 先处理 Fresh Observation，否则只执行 `allowed_actions` 中的一个动作。
- 需求收集每轮只问第一个缺失项；五项必须来自用户明确表达。
- 模型阶段只输出说明和模型选择卡，不命名、推荐或比较任何模型。
- 搜索调用必须放入字面量 `<code>...</code>`，不能把调用表达式直接打印给用户。
- 同一资源类型在一次审查中最多搜索一次；MCP 与 Skill 都缺失时在同一 code block 各调用一次。
- Card 是 fenced JSON 最终回复，不通过代码解释器执行。
- MCP 所有配置，包括非 Secret 和 Secret，都在 Card 中填写；聊天不收集凭据。
- 身份阶段由模型自行提出 display name，但不能生成 internal name。
- Final Card 只包含描述、Prompt、示例和受支持的 runtime options，不包含身份、模型或资源引用。

---

## 8. 搜索设计

### 8.1 统一关键词规范化

三个工具共享 `sdk/nexent/core/tools/nl2agent/_context.py` 中的规范化和评分：

1. Unicode NFKC。
2. `casefold` 大小写归一化。
3. 将 ASCII 字母数字串和连续 CJK 文本切为 token。
4. 删除中英文常见连接词、空值和重复词，保留首次出现顺序。
5. 将 token 排序后生成与顺序无关的 canonical query key。

当前 CJK token 化保留“连续中文片段”为一个 token，并不会进一步做语言学分词。

### 8.2 模糊评分

每个关键词独立匹配：

- name 权重最高；
- description 与 tags 合并为 metadata，乘以 `0.9`；
- 子串命中得分为 `1.0`；
- 长度不超过 3 的 token 不进行 fuzzy；
- fuzzy 优先 RapidFuzz `partial_ratio`，缺失时回退 `SequenceMatcher`；
- 最低候选阈值为 `0.62`；
- 总分为 `0.85 × 最佳命中 + 0.15 × 关键词覆盖率`。

采用 OR 语义：命中任一关键词即可成为候选，多关键词命中通过 coverage 加分。结果 `reason` 记录实际命中关键词。弱相关项允许被全部过滤，空结果是合法结果。

### 8.3 本地 Tool 与 Skill

本地工具输入为完整需求提炼出的原子关键词字符串。搜索过程：

1. 分别评分 `local_tools` 和 `local_skills`。
2. 先按稳定 ID 去重，再按规范化名称去重。
3. 合并两个类型并按得分排序；同分时 Tool 排在 Skill 前。
4. Tool + Skill 合计最多返回 5 条。

结果包含稳定 `recommendation_batch_id`：

```text
local_<sha256(draft id + canonical query + sorted result ids)[:24]>
```

等价关键词集合和相同结果产生稳定批次；SDK 不缓存结果。

### 8.4 MCP 搜索到底搜索什么

MCP 候选来自 Session Start 时 Backend 拉取的两个来源：

1. official Registry：调用现有 Registry service，`search=None, limit=30`。
2. Community Marketplace：调用现有 Community service，`search=None, limit=30`。

SDK 不直接访问互联网。它在注入的快照上搜索规范化后的 MCP 名称和描述。当前 normalizer 不把 tags 保留到评分候选，因此 MCP tags 实际不参与评分。

Registry 候选先于 Community 处理；按 `recommendation_id` 和规范化名称去重，所以同名重复项优先 official Registry。最终最多返回 5 条。

每条推荐携带稳定 `recommendation_id`、来源、描述和规范化安装选项。批次 ID 由 Draft、资源类型、canonical query 和去重后的 item keys 生成，空结果也有批次 ID。

### 8.5 online Skill 搜索到底搜索什么

online Skill 候选来自部署环境的 official Skill ZIP 目录，而非实时公网搜索。Backend 的 Catalog 加载顺序为：

1. 当前 tenant 的 Skill 元数据；
2. 全局 official Skill 元数据；
3. ZIP 内 `SKILL.md` 元数据。

最终候选同时提供 `skill_id`、`skill_name`、兼容 `name`、description、tags、source 和 status。写入 Session Catalog 前：

- 只保留 `status="installable"`；
- 过滤 `installed`，避免重复推荐；
- 过滤 `resource_missing`，并以 tenant/draft/Skill 名称记录 warning。

SDK 再做一次 status 防御过滤，使用 `skill_name or name`、description 和 tags 评分，按 Skill ID 与规范化名称去重，最多返回 5 条。安装成功后 Backend 使用 Catalog CAS 删除同 ID 或同名推荐；下一次 Agent Run 重建工具实例，自然读取更新后的 Catalog。

---

## 9. MCP 安装选项与可恢复 Saga

### 9.1 统一安装模型

`normalize_mcp_candidate` 将 Registry 和 Community 数据归一为相同语义：

- 远程 URL 或 URL 模板；
- transport；
- package runtime、package、runtime arguments 和 package arguments；
- environment、headers、变量、JSON、port 和 container 配置；
- 每个字段的 key、label、description、type、default、required、secret、choices；
- 无法安全构造选项时的 `unsupported_reason`。

Registry 读取嵌套 `server.remotes` 与 `server.packages`。Community 优先利用嵌套 `registryJson`，再用 `serverUrl`、`transportType` 和 `configJson` 显式覆盖。元数据不足时会生成必须由用户填写的 URL 或 container 字段，而不是猜测。

Secret 根据声明和字段名启发式识别。Secret default 会在写入搜索响应、Redis 或 API 响应前清空；用户值只通过安装请求进入现有 credential/MCP 保存链路。

### 9.2 安装流程

稳定安装键为：

```text
sha256(draft_agent_id + recommendation_id + option_id)
```

它不包含用户配置或 Secret，并写入 MCP `registry_json.nl2agent_installation_key`。流程为：

1. 只从当前 tenant/draft Redis Catalog 解析 `recommendation_id` 和 `option_id`，不信任 LLM/客户端提交的 URL、命令或包。
2. 使用 `SET NX EX` 获取 5 分钟分布式安装锁。
3. 把 workflow 设为 `installing`。
4. 只合并用户提交的 `config_values.fields`，按 option 声明验证 required、JSON、number、URL、choice、port 和未解析模板变量。
5. 按 installation key 查找已有 MCP，支持幂等重试。
6. 创建或复用 remote/container MCP；内部创建接口直接返回 `mcp_id`。
7. 执行健康检查和工具发现，upsert MCP Tool Catalog。
8. workflow 设为 `connected`，记录发现的稳定 Tool ID，但不记录 Secret。
9. 从 Session Catalog 删除已安装推荐。
10. 释放安装锁。

### 9.3 失败与恢复

- 并发安装因锁冲突被拒绝，不会创建重复 MCP。
- 容器已启动但数据库持久化失败时立即停止并删除容器。
- 工具发现失败时保留已创建 MCP，workflow 记录 `failed + mcp_id`；Retry 从健康检查/发现恢复。
- Redis workflow 更新失败时可根据数据库中的 installation provenance 恢复，不依赖按名称反查。
- 安装成功只表示 `connected`，不会自动绑定工具。
- 用户必须至少绑定一个发现工具，或显式 `skip-tools`，才能解决该 MCP。

---

## 10. 各交互阶段

### 10.1 需求摘要

五项摘要 Card 渲染时调用 register API。Backend 对文本做 NFKC 和空白规范化，并对规范化、排序后的 JSON 计算 SHA-256 fingerprint。

- 相同摘要重复注册幂等。
- 不同摘要注册会替换当前 fingerprint，状态回到 `awaiting_confirmation`。
- 历史 Card 携带旧 fingerprint 时得到 `is_current=false`，不能覆盖或确认新版摘要。
- Confirm API 必须携带与 Redis 当前值完全一致的 fingerprint。
- 相同 fingerprint 的重复确认幂等。

### 10.2 模型选择

Card 调用现有 `/model/llm_list`，Frontend 只显示 `connect_status === "available"` 的项；Backend 仍执行最终 tenant、存在性、模型类型、连接状态、重复和数量校验。

保存后：

- `business_logic_model_id = primary_model_id`
- `model_ids = [primary_model_id, ...fallback_model_ids]`
- 最多 5 个模型，不能重复
- Redis `model_selection_confirmed=true`

Finalization 会再次验证模型仍存在、仍为 LLM 且仍 available。

### 10.3 本地资源 Apply / Skip

Card 注册成功前操作按钮禁用。Apply 可选择推荐批次的 Tool/Skill 子集，语义为全有或全无：

1. 验证 Draft 归属、批次状态和所选 ID 均属于推荐结果。
2. 在写入前查询并验证所有资源。
3. ToolInstance 与 SkillInstance 使用同一个 SQLAlchemy Session。
4. 任一失败导致数据库事务整体回滚。
5. 数据库成功后把 Redis 批次标记 `applied`，只记录实际成功绑定的 ID。

若数据库提交成功而 Redis 更新失败，客户端重试时持久化实例 upsert 保持幂等，再完成批次对账。完全失败不返回自动续跑文本。Skip 将指定批次标记 `skipped`。

### 10.4 online 审查

MCP 与 Skill Card 分别注册自己的 online batch。只有两类批次都存在时，会话级“完成配置”按钮才可能启用；两类空结果批次也算已展示。

按钮还要求没有处于 `installing` 或 `connected` 的未解决 MCP。未尝试安装、安装失败的推荐可以统一放弃；已连接 MCP 必须 bind 或 skip。完成 API 将当前全部 online batches 标为 completed，并设置 `online_configuration_confirmed=true`。

### 10.5 身份

模型根据已确认需求自行建议 display name，Card 允许用户修改并保存。保存只更新 Draft 的显示名称并把 Redis `identity_confirmed=true`；Draft 数据库内部名仍保持 `draft_*`。

内部名预览由 Backend 生成：

1. NFKD 转 ASCII，非字母数字替换并规范为 snake_case。
2. 若结果为空或数字开头，使用 `agent_{agent_id}`。
3. 限制 50 字符，满足 `^[A-Za-z_][A-Za-z0-9_]*$`。
4. 若另一个 Agent 已使用候选名，追加 Draft ID 后缀。

查询返回精确 `ValueError("agent not found")` 时表示名称可用；其他数据库异常继续抛出。

### 10.6 最终审核与提交

Final Card 的 LLM proposal 只允许描述和 Prompt 内容：

- `business_description`
- `description`
- `duty_prompt`
- `constraint_prompt`
- `few_shots_prompt`
- `greeting_message`
- `example_questions`
- `prompt_template_id`
- 现有受支持 runtime options

Request model `extra="forbid"`，旧的 name/display name、模型 ID、Tool/Skill/Sub-agent ID、知识库和资源配置字段会被拒绝。

审核 Card 从 Session State 显示：

- 主模型名称与逐行 fallback 名称；
- 本地 Tool/Skill 名称；
- online MCP Tool/official Skill 名称；
- Backend 解析的 display/internal name；
- 无法解析的引用类型和 ID。

模型名称使用 `display_name`，回退 `model_name`；Tool 使用 `origin_name`，回退 `name`；Skill 使用持久化名称。正常行不显示数字 ID，只有 `invalid_references` 用 ID 排查。

提交前 Backend 再次检查 requirements、模型、本地 review、两类 online batch、MCP resolved、identity、proposal 必填字段和全部持久化引用。所有校验发生在更新 Draft 前，避免失败留下部分字段。成功响应当前使用 `status="draft_ready"`。

---

## 11. Card Contract、渲染和交付验收

### 11.1 七类 Card

Canonical Schema 位于 `contracts/nl2agent-card.schema.json`，覆盖：

1. `nl2agent-requirements-summary`
2. `nl2agent-model-selection`
3. `nl2agent-local-resources`
4. `nl2agent-web-mcp` / `nl2agent-web-mcps`
5. `nl2agent-web-skill` / `nl2agent-web-skills`
6. `nl2agent-agent-identity`
7. `nl2agent-finalize`

Schema 对 payload `agent_id` 保持可选，因为 Frontend 允许使用 conversation-scoped trusted draft ID；若 payload ID 存在则必须与 trusted ID 一致。两边都没有有效 ID，或存在冲突时，Card 拒绝渲染。

搜索调用标签 `nl2agent-search-local-resources`、`nl2agent-search-web-mcps` 等不是 Card tag，Frontend 明确不渲染它们。

### 11.2 流式门禁

- SSE 流式输出和 Task Window 只显示“正在生成卡片”占位。
- 只有完整 final assistant message 才进入 Ajv 解析和 React 挂载。
- 必须存在闭合 fence、有效 JSON、对应 schema、唯一同类型 Card 和可信 Draft ID。
- Local/MCP/Skill 空结果合法，但批次 ID 和必须字段不能缺失。
- 历史消息、分享模式、只读模式、非最新消息和组件重挂载不提交回执，也不自动继续。

### 11.3 Rendered 回执

Card Delivery 请求使用数据库数字 `message_id`。Backend 验证：

- 消息属于 State 保存的 Conversation；
- role 是 assistant；
-状态是 completed；
- 是当前 Conversation 最新 completed assistant message；
- `card_type` 属于当前 `expected_card_types`。

需要批次注册的 Requirements、Local、MCP、Skill Card，必须在 schema 校验、真实挂载和注册成功后回执 `rendered`。Model、Identity、Final Card 可在挂载后直接回执。

相同 `message_id + card_type + status + card_key` 幂等；过期消息返回 stale-card 409。

### 11.4 Failed 回执和恢复

失败原因限定为：

- `truncated_fence`
- `invalid_json`
- `invalid_schema`
- `missing_card`

`failed` 只记录原因和连续次数，不删除需求摘要、推荐批次或其他业务状态。前两次失败返回 `auto_retry_allowed=true` 和 `[[NL2AGENT_CARD_RETRY]]` 隐藏文本；Frontend 通过现有 `/agent/run` 自动重试。第三次起停止自动运行并显示“重新生成卡片”。

回执 API 本身失败时显示“重试回执”，不会把 API 故障误当成模型输出故障，也不会生成新 Card。

---

## 12. Frontend 会话与自动继续

### 12.1 入口和 Draft 映射

Agent 管理页和 Agent Selector Header 都提供 Agent Builder 入口。Session Start 响应暂存于 sessionStorage，进入聊天页后建立持久到当前浏览器 Session 的：

```text
conversation_id → draft_agent_id
```

解析优先使用 Conversation 映射；一次性 handoff 只在 active conversation 与 handoff conversation 一致时回退。切换会话不会复用另一个会话的 Draft ID。

### 12.2 Workflow Provider

`Nl2AgentWorkflowContext` 以 conversation/draft 为 scope，统一管理：

- 进行中的 Card action 计数；
- 聊天输入 blocker；
- continuation 并发与 retry；
- Card Delivery 的 conversation/draft scoped `Map`（pending/succeeded/failed）；
- Session State 刷新通知。

模块级全局 `processed messages` 集合已经删除。只有 API 成功后回执才标为 completed；失败可重试。

### 12.3 隐藏普通消息

以下阶段操作成功返回固定 `chat_injection_text`：

- 需求按钮确认；
- 模型保存；
- 本地 Apply/Skip；
- online 全局完成；
- 身份保存。

Frontend 将文本作为普通 user message 持久化并再次调用 `/agent/run`。两个保留前缀为：

- `[[NL2AGENT_AUTO_CONTINUE]]`
- `[[NL2AGENT_CARD_RETRY]]`

这类消息计入正常历史和 message index，但不显示气泡、不参与分享；其后的 assistant 回复和工具过程正常显示。Backend 文本只触发模型重新读取权威状态，不指定下一阶段、不调用搜索工具。

单个 MCP/Skill 安装、MCP bind/skip 和失败不会自动进入下一轮；用户在统一 online 完成栏结束整个 online 阶段。

### 12.4 Card Lifecycle

`useNl2AgentCardLifecycle` 为各 Card 统一处理 action、busy、blocker、retry、continuation 和 unmount cleanup。Card 组件仍负责自己的展示和业务输入，例如模型下拉、MCP 动态字段、资源勾选。

Card Parser 使用 Ajv 和 canonical schema 产生 typed Card AST。Markdown Renderer 与 Final Message Delivery 都调用这一共享 parser，因而不再各自维护不同 schema；但两条调用路径当前仍会分别解析一次同一消息，并没有把一个 AST 实例从 Renderer 传给 Delivery Coordinator。

---

## 13. Public API

所有路径均位于 `/nl2agent` Router 下。

| 方法 | 路径 | 主要作用 | 成功后自动继续 |
|---|---|---|---|
| POST | `/session/start` | 创建 Draft、Conversation、State 与 Catalog | 否 |
| POST | `/session/{id}/requirements/register` | 注册五项摘要和 fingerprint | 否 |
| POST | `/session/{id}/requirements/confirm` | 按钮确认当前 fingerprint | 是 |
| POST | `/session/{id}/card-delivery` | 记录 rendered/failed 回执 | failed 前两次可重试 |
| PUT | `/session/{id}/models` | 保存主模型与 fallback | 是 |
| POST | `/session/{id}/local-resources/register` | 注册本地推荐批次 | 否 |
| POST | `/session/{id}/apply-local-resources` | 事务性绑定所选本地资源 | 是 |
| POST | `/session/{id}/local-resources/skip` | 跳过指定本地批次 | 是 |
| POST | `/session/{id}/online-recommendations/register` | 注册 MCP/Skill online batch | 否 |
| POST | `/session/{id}/mcp/install` | 安装、检查并发现 MCP Tools | 否 |
| POST | `/session/{id}/mcp/{mcp_id}/bind-tools` | 绑定选中 MCP Tools | 否 |
| POST | `/session/{id}/mcp/{mcp_id}/skip-tools` | 显式跳过已连接 MCP 工具绑定 | 否 |
| POST | `/session/{id}/install-web-skill` | 安装 official Skill 并刷新 Catalog | 否 |
| POST | `/session/{id}/online-configuration/complete` | 结束两类 online 审查 | 是 |
| GET | `/session/{id}/state` | 读取 Workflow 摘要、身份、模型、资源和失效引用 | 否 |
| PUT | `/session/{id}/identity` | 保存 display name 并确认身份 | 是 |
| POST | `/session/{id}/finalize` | 校验权威状态并写入最终 Draft 方案 | 否 |

`/agent/run` 请求结构保持不变，只兼容增加可选 `draft_agent_id`；所有 Card 操作使用上述专用 API。

### 13.1 结构化错误

| ErrorCode | HTTP | 含义 |
|---|---:|---|
| `030201` | 404 | Draft 不存在或不属于 tenant |
| `030202` | 409 | 当前工作流不允许该动作 |
| `030203` | 409 | Card 回执来自历史/过期消息 |
| `030204` | 409 | Redis CAS 冲突重试耗尽 |
| `030205` | 503 | Session Catalog provider 不可用 |

大部分 NL2AGENT App 入口透传结构化 `AppException`。当前 `session/start`、Apply Local 和 Install Web Skill 的部分异常路径仍保留直接映射为 HTTP 500 的旧写法，这是现存接口一致性限制。

---

## 14. 安全与隔离

### 14.1 Tenant / Draft 隔离

- 每个 API 在变更前验证 Draft 属于当前 tenant。
- Redis State、Catalog 和安装锁都包含 tenant/draft。
- Card payload ID 必须与 Conversation 映射得到的 trusted Draft ID 一致。
- MCP 推荐和 option 必须从当前 tenant/draft Catalog 解析。
- Tool/Skill/MCP 绑定校验资源 provenance 和 tenant。
- Skill 名称解析使用 tenant-scoped 批量查询，避免跨 tenant 泄漏。

### 14.2 Secret 边界

Secret 不进入：

- Prompt / Current Session；
- SDK 搜索结果；
- Redis Session Catalog 的 default；
- Redis MCP workflow；
- installation key；
-日志；
- API 成功响应和测试快照。

Secret 只在 MCP Card 密码输入框收集，并提交到现有 credential/MCP 配置保存路径。失败后 Card 保留可编辑输入状态，但后端不会回显已存 Secret。

### 14.3 不信任 LLM 引用

- Model Card 选项来自 live platform API。
- MCP URL、命令、包和 option 从 Redis recommendation 解析。
- Finalize 忽略并拒绝旧模型/资源/身份字段。
-最终资源集来自 enabled ToolInstance 和 SkillInstance。

---

## 15. Contract 生成与测试

### 15.1 Contract 单一来源

- Card：`contracts/nl2agent-card.schema.json`
- HTTP：FastAPI OpenAPI 中 `/nl2agent` 路径及递归依赖 schema
- Frontend 生成物：
  - `frontend/contracts/generated/nl2agent-card.schema.json`
  - `frontend/contracts/generated/nl2agent-api.ts`

`frontend/scripts/sync-nl2agent-contracts.mjs` 复制 Card Schema、调用 Backend 导出脚本、执行 `openapi-typescript` 和 Prettier。`npm run contracts:check` 通过临时生成与仓库文件比较检测漂移。

### 15.2 测试分层

| 层 | 重点覆盖 |
|---|---|
| Redis/Workflow | v2 解析、CAS 并发、revision、阶段向量、需求 fingerprint、批次和 MCP 状态 |
| Backend Service/API | Session 补偿、模型门禁、本地原子 Apply、MCP Saga、Card Delivery、Finalize |
| SDK | 三工具构造隔离、关键词规范化、评分、去重、空结果、批次稳定性 |
| Prompt | 双语 YAML 加载、阶段一致、只允许三个 callable、Card 协议与 retry 前缀 |
| Contract | Prompt 示例与 SDK 结果符合 canonical Schema、OpenAPI 生成物不漂移 |
| Frontend | Ajv parser、Card lifecycle、busy/blocker、continuation、卡片状态与会话隔离 |

Frontend 已加入 Vitest、React Testing Library 和 jsdom。`npm run check-all` 的顺序为 contract check、test、type-check、lint、format check 和 build。

---

## 16. 部署与运维

本次实现没有数据库迁移。Backend、Frontend 和 Runtime SDK 需要作为同一版本部署，因为 Card Contract、State v2 和工具上下文必须一致。

部署前由用户手工清理未完成测试 Session 的：

- `nl2agent:session_state:*`
- `nl2agent:session_catalog:*`

不删除已发布普通 Agent、现有 MCP 或已安装 Skill。

启动顺序：

1. 先启动或重启 Config Service，让它 seed 默认 Runner 和三个 builtin tools。
2. 确认 seed 无错误。
3. 再启动或重启 Runtime Service。
4. 更新 Frontend。
5. 创建新的 Agent Builder Session 验证，不复用未完成旧测试会话。

---

## 17. 当前实现限制

以下是本次全量扫描确认的当前行为，后续改进时应避免被文档掩盖：

1. `nl2agent_service.py` 仍有约千行，虽然已拆出六个专用 Service，但 seed、模型投影和若干辅助逻辑仍集中在 facade。
2. Session Catalog 的 CAS 更新没有像 Workflow State 一样公开 `revision`。
3. MCP normalizer 当前未把 tags 带入评分候选，所以 MCP 搜索实际按 name + description 匹配。
4. 资源分组只把 `source == "official"` 的 Skill 识别为 online；若持久化 source 使用中文“官方”，最终卡可能误归为 local。
5. Frontend Model Card 客户端按 available 过滤，但模型类型的最终过滤主要依赖 Backend；Backend seed 模型候选和保存校验对 `chat`/`llm` 的处理口径并不完全相同。
6. 部分 Card UI 文案仍为硬编码英文，尚未全部收敛到中英文 i18n。
7. Frontend 已生成 API request 类型，但较复杂的 response 和 Session State 仍有手写 TypeScript interface。
8. Canonical Card Schema 为兼容可信 Conversation Draft ID，允许 payload 不含 `agent_id`，并普遍允许附加字段；更严格的 ID 冲突和唯一卡片检查在 Frontend parser 中完成。
9. `FinalizeCard` 的客户端 `canPublish` 主要检查身份、proposal 和 invalid references；完整 workflow 门禁由 Backend Finalization 兜底。
10. `backend/database/tool_db.py` 中仍有一处旧注释写“6 tools”，实际定义和 seed 均为 3 个。
11. NL2AGENT Router 的异常映射尚未在所有入口完全统一。
12. official Skill 的 `resource_missing` 当前只过滤并告警，没有重新安装或修复入口。
13. online Skill Card 当前只安装租户 Skill 并从 Session Catalog 删除推荐，不会创建 Draft `SkillInstance`；因此它不会仅凭“Installed”状态自动出现在最终持久化资源列表中。
14. Frontend 已统一 Card parser/schema，但 Renderer 和 Final Message Delivery 仍各自调用 parser，尚未跨组件共享同一个 AST 实例。
15. `Nl2AgentContext` 已做到每 Tool 实例隔离，但 dataclass 不是 frozen，Catalog List 也未深拷贝；“只读”目前依赖搜索代码不修改输入，而不是类型系统强制。

这些限制不影响本文描述的主流程，但属于维护和后续重构时必须考虑的真实实现约束。
