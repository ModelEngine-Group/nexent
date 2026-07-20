# NL2AGENT 对话式智能体构建设计

> 实现快照：`5375990a0336644b84ddb4307c8d3d4199f1976b`
>
> 对比基线：`4e7d9fe15c78d85c732beb9fe06ac8d439e99327`
>
> 最近复核：2026-07-20

本文描述当前分支已经实现的 NL2AGENT 能力。历史 gap 方案、阶段性代码审查和已删除兼容逻辑不作为当前行为依据；发生行为变更时，应同步更新本文、Canonical Contract 和对应测试。

---

## 1. 背景、目标与边界

传统 Agent 创建页要求用户预先理解模型、Tool、Skill、MCP、Prompt 和运行参数。NL2AGENT 将这一过程改造成受后端确定性工作流约束的对话：

1. LLM 负责澄清需求、调用只读搜索工具并生成结构化方案。
2. Frontend 用 Card 展示平台中的真实模型和资源。
3. 用户只通过 Card 执行确认、安装、绑定和提交等副作用。
4. Backend 以 PostgreSQL 持久化状态决定当前阶段、允许动作和最终可提交内容。

当前能力包括：

- 收集目标、受众或场景、主要输入、期望输出、关键约束五项需求。
- 生成只读需求摘要并要求用户点击确认；聊天中的“确认”不产生确认副作用。
- 选择一个主 LLM 和最多四个有序 fallback。
- 搜索并配置租户本地 Tool 与 Skill。
- 搜索 Registry、Community Marketplace MCP 和 official Skill Catalog。
- 在 Card 中完成 MCP 配置、安装、健康检查、工具发现与绑定。
- 安装 official Skill；`resource_missing` 项可从 official ZIP 恢复后绑定。
- 保存 Agent display name，并由 Backend 生成唯一 internal name。
- 从持久化模型和资源生成最终审核信息，写入完整 Draft 配置。
- 在刷新、切换会话或浏览器内存状态丢失后恢复 active Session。
- 对无效、截断、缺失或未成功挂载的 Card 做交付回执与有限自动重试。

明确边界：

- Finalize 完成的是 `version_no=0` Draft，返回 `draft_ready`，不自动创建发布版本。
- LLM 不能直接确认需求、保存模型、安装资源、绑定工具或 Finalize。
- SDK 不读环境变量、不访问 Redis，也不持有跨 Agent Run 的进程级搜索状态。
- online Skill 搜索针对部署环境的 official Skill Catalog，不是任意公网搜索。
- Redis 不是工作流权威存储；Redis 丢失不应丢失已经提交的 Session。
- 已删除的旧 action tools 不提供兼容入口。

---

## 2. 基线变更规模

统计范围固定为基线 `4e7d9fe15c78d85c732beb9fe06ac8d439e99327` 到功能快照 `5375990a0336644b84ddb4307c8d3d4199f1976b`。统计时工作区干净，因此不包含本文重写自身，结果可通过 `git diff --numstat <baseline> <snapshot>` 复算。

### 2.1 全量差异

| 指标 | 数值 |
|---|---:|
| 提交数 | 178 |
| 变更文件 | 177 |
| 新增 / 修改 / 删除文件 | 105 / 71 / 1 |
| 新增行 | 42,236 |
| 删除行 | 1,400 |
| 总增删量 | 43,636 |

### 2.2 业务代码与测试代码

代码分类规则：

- 测试代码：`test/**`、Frontend `__tests__/**`、`frontend/vitest.config.ts` 和 `frontend/vitest.setup.ts`。
- 业务代码：Backend、SDK、Frontend、Contracts、Deploy/SQL 和运维脚本，排除上述测试路径。
- 文档、SVG 资产、`.gitignore` 和本地工具元数据不计入代码小计。

| 类别 | 文件 | 新增 | 删除 | 总增删量 | 代码占比 |
|---|---:|---:|---:|---:|---:|
| 业务代码 | 114 | 25,569 | 1,354 | 26,923 | 65.2% |
| 测试代码 | 52 | 14,354 | 37 | 14,391 | 34.8% |
| **代码小计** | **166** | **39,923** | **1,391** | **41,314** | **100%** |

业务代码分布：

| 子系统 | 文件 | 总增删量 |
|---|---:|---:|
| Backend | 47 | 11,219 |
| Frontend | 41 | 9,569 |
| Canonical Contracts | 2 | 3,983 |
| SDK | 11 | 1,220 |
| Deploy / 运维 | 13 | 932 |

测试代码分布：

| 子系统 | 文件 | 总增删量 |
|---|---:|---:|
| Backend | 31 | 10,756 |
| Frontend | 14 | 2,188 |
| SDK | 4 | 997 |
| Contract | 2 | 309 |
| Deploy | 1 | 141 |

另外有 9 个文档/资产文件、2,314 行增删，以及 2 个仓库元数据文件、8 行增删。业务代码主口径包含生成契约；若排除 `contracts/nl2agent-openapi.json`、生成的 Frontend API 类型和 Frontend Schema 副本共 6,026 行，则手写及运维业务代码为 111 个文件、20,897 行增删。

---

## 3. 核心身份与权威边界

| 对象 | 含义 | 权威标识 |
|---|---|---|
| NL2AGENT Runner | 每个 tenant 的内部 Builder Agent，内部名为 `nl2agent` | `runner_agent_id` / `nl2agent_agent_id` |
| Draft Agent | 本次构建的 `version_no=0` Agent | `draft_agent_id` |
| Conversation | Runner 执行构建对话所使用的会话 | `conversation_id` |
| Durable Session | 绑定 tenant、user、Runner、Draft 和 Conversation 的生命周期记录 | `session_id` |
| Workflow State | 决定阶段和允许动作的 v2 状态 | tenant + draft + revision |
| Catalog Snapshot | Session Start 时获取的只读资源快照 | tenant + SHA-256 snapshot ID |
| Card Delivery | 最新完整 assistant 消息中某类 Card 的交付结果 | message + card type + card key |

Runner 与 Draft 是两个不同 Agent：

- `/agent/run` 实际运行持久化在 Session 中的 Runner。
- 模型、Tool、Skill、身份和最终 Prompt 都写入 Draft。
- Backend 按 tenant、user、Conversation、Draft 和 persisted Runner 联合验证一次运行。
- Frontend 切换会话时使用 Backend 返回的 persisted Runner ID，不按名称猜测当前 Runner。
- 普通 Agent 列表默认隐藏 Runner 和 `draft_*` Agent。

---

## 4. 总体架构

```text
Config Service / Session Provisioning
  └─ seed or repair one tenant-scoped Runner + exactly 3 search tools

Frontend Agent Builder
  └─ POST /nl2agent/session/start
       ├─ load bounded resource catalogs
       ├─ transaction: Draft + Conversation + durable Session + Catalog Snapshot
       └─ best-effort warm Redis projections

Existing Chat /agent/run + SSE
  ├─ authorize persisted Runner/Draft/Conversation ownership
  ├─ preprocess requirement revisions
  ├─ inject Current Session workflow summary
  ├─ construct 3 per-run SDK search-tool instances
  └─ validate the final NL2AGENT card answer

Final Assistant Message
  └─ Frontend Ajv validation + React Card mount
       ├─ register recommendation/requirements payload
       ├─ report rendered or failed delivery
       └─ user action -> /nl2agent API -> optional hidden continuation

PostgreSQL
  ├─ authoritative workflow state and lifecycle
  ├─ immutable content-addressed catalogs
  └─ persisted Draft/model/resource bindings

Redis
  ├─ disposable 24-hour state/catalog projections
  └─ token-owned installation locks
```

Backend 分层：

| 层 | 职责 |
|---|---|
| `backend/apps/nl2agent_app.py` | 鉴权、请求解析、调用 Service、结构化错误映射 |
| `backend/services/nl2agent_service.py` | Facade 与依赖装配 |
| Session / Lifecycle Services | Session 创建、恢复、放弃、终态和保留期 |
| Catalog / Resource / MCP Services | Catalog 加载、本地绑定、Skill 安装、MCP Saga |
| Workflow / Summary / Publication Services | 状态动作、Card 回执、投影、Finalize |
| `backend/agents/nl2agent_*` | Workflow 模型、CAS repository 和 Catalog 投影 |
| `backend/database/nl2agent_session_db.py` | Durable Session 与 Catalog Snapshot repository |
| `sdk/nexent/core/tools/nl2agent/` | 三个纯 SDK 搜索工具和共享评分内核 |

---

## 5. 持久化与一致性

### 5.1 PostgreSQL 权威数据

`nl2agent_session_t` 保存 tenant、user、Runner、Draft、Conversation、生命周期、workflow schema/revision/state、Catalog Snapshot 外键和审计字段。`nl2agent_catalog_snapshot_t` 按 tenant + SHA-256 digest 保存不可变 Catalog；内容相同的 Session 共享一份快照。

Agent、Conversation、ToolInstance、SkillInstance、MCP 和模型选择继续使用既有业务表。每个 tenant 通过 partial unique index 最多保留一个未删除的 `nl2agent` Runner。

### 5.2 Redis 可丢弃投影

```text
nl2agent:session_state:{tenant}:{draft}
nl2agent:session_catalog:{tenant}:{draft}
nl2agent:catalog_snapshot:{tenant}:{snapshot_id}
nl2agent:mcp_installation_lock:{tenant}:{draft}:{installation_key}
```

State 和 Catalog Cache TTL 为 24 小时。Workflow 读取以数据库为准并 best-effort 刷新 Cache；Catalog 优先使用 Cache，缺失或 Redis 不可用时从数据库快照恢复。Redis 提交失败不会反转数据库事务；Redis 仍是安装锁的运行依赖。

### 5.3 Workflow CAS

每次状态变更从数据库读取 active Session，用严格 Pydantic v2 State 解析，执行 mutator 并重新验证。实际变更使 revision 恰好加一，再以旧 revision 条件更新；冲突时重读最新状态，最多重试五次。无变化不增加 revision，terminal Session 立即拒绝。

### 5.4 跨聚合副作用

- Session Start 在一个事务内创建 Draft、Conversation、Session 和 Catalog Snapshot，提交后才暖 Cache。
- Local Apply 先预留 operation，再用一个事务写全部 Tool/Skill binding；提交后按 operation ID 对账。
- MCP/Skill 安装使用稳定 key、token-owned lock 和 heartbeat，重复请求可恢复。
- Finalize 在同一事务中更新 Draft 并把 Session 从 active 改为 completed。
- 模型、资源和身份等步骤依靠预留、幂等写和补偿恢复，不承诺跨所有表的一次全局事务。

---

## 6. Session 生命周期与恢复

### 6.1 初始化

Session Start 先查找 tenant Runner，缺失时幂等 provision，再校验 Prompt、模型和三个 builtin search tools。Backend 加载有界 Catalog，随后在事务内创建 `draft_<uuid8>`、Conversation、Workflow State、Catalog Snapshot 和 active Session，提交后 best-effort 写 Redis，最终返回 Runner、Draft、Conversation ID 和 Draft name。

本地 Tool/Skill 或 official Skill provider 失败会阻断创建。Registry 与 Community 独立 fail-soft；合法空 Catalog 允许创建 Session。

### 6.2 恢复与发现

sessionStorage 只负责首次页面 handoff。进入或切换 Conversation 后，Frontend 调用 `GET /nl2agent/session/by-conversation/{conversation_id}`，按 tenant + user 恢复 active Session，再通过 `/state` 恢复阶段、Card 回执、模型、资源和交互状态。`GET /nl2agent/sessions` 默认列出 50 个、最多 100 个 active Session。

### 6.3 终态与清理

- Finalize 成功后 Session 为 `completed`，Draft 保留为 `draft_ready`。
- 显式放弃或删除对应 Conversation 后 Session 为 `abandoned`，并清理 Redis 投影。
- terminal Session 不允许 `/agent/run` 或状态变更。

active、abandoned、completed 默认各保留 30 天，批量上限默认 100：active 超期先转 abandoned；abandoned 超期软删除 Draft、Conversation、消息和资源 binding；completed 超期清理 Session 与无引用 Catalog Snapshot，但保留 Draft。清理由 Session Start opportunistic 触发。

---

## 7. 确定性工作流

Workflow State 固定为 schema version 2，旧 schema 不自动迁移。

| 阶段 | 进入条件 | 允许动作 | 期望 Card |
|---|---|---|---|
| `requirements_collecting` | 需求未形成可确认摘要 | 澄清或生成摘要 | 五项齐全后 `requirements_summary` |
| `requirements_confirmation` | 摘要待确认 | 确认或修改 | 未 rendered 时为 `requirements_summary` |
| `model_selection` | 需求已确认、模型未确认 | 保存模型 | `model_selection` |
| `local_resource_search` | 本地批次不存在 | 搜索本地资源 | `local_resources` |
| `local_resource_review` | 本地批次待处理 | Apply 或 Skip | 未 rendered 时为 `local_resources` |
| `online_resource_search` | MCP 或 Skill 批次缺失 | 搜索缺失目录 | `web_mcp` / `web_skill` |
| `online_resource_review` | 两类批次已注册但未完成 | 配置或完成 online 阶段 | 未 rendered 的 online Card |
| `agent_identity` | online 完成、身份未确认 | 保存身份 | `agent_identity` |
| `final_review` | 前置门禁全部完成 | Finalize | `final_review` |

Evaluator 只根据持久化 State 计算 `current_stage`、`expected_card_types` 和 `allowed_actions`。LLM 的文字、工具调用意图或 Card 尝试都不能直接推进阶段。

等待 Card 的阶段只有在持久化 `rendered` 回执后才认为 Card 已交付。需求发生修改时，旧摘要 fingerprint 和对应 Card Delivery 周期一起失效，必须重新注册并交付新摘要。

---

## 8. Agent Run 与双语 Prompt

`AgentRequest` 增加可选 `draft_agent_id`。只有当前 Agent 是 persisted NL2AGENT Runner 时，Backend 才：

- 校验 active Session 的 tenant、user、Runner、Draft 和 Conversation；
- 在保存本轮消息和运行模型前识别需求修改；
- 加载 Workflow State、持久化 Draft 和 Session Catalog；
- 注入精简的 Current Session；
- 构造三个 per-run 搜索工具；
- 对最终答案执行 Backend Card Contract 校验。

Current Session 只暴露模型决策需要的阶段、允许动作、需求摘要、批次状态和未解决 MCP 数量，不暴露 Secret、资源配置或可由 LLM 伪造的持久化 ID 集合。

英文和中文 YAML 保持相同章节、阶段和 Card 示例。Prompt 使用 `|-` 多行系统文本、稳定标题层级、平行列表和语言内一致术语。项目执行器要求字面量 `<code>...</code>` 才执行工具，因此这是对通用“Prompt 中避免 HTML tag”规则的有意协议例外。

Prompt 的关键约束：

1. 只执行 `allowed_actions` 中的一个动作。
2. 只有当前轮成功且动作被允许的搜索 Observation 才可优先输出。
3. 含 `error` 的 Observation 不是结果 Card。
4. 工具 Observation 必须原样复制，不能增删、重排或改写候选。
5. `[[NL2AGENT_AUTO_CONTINUE]]` 和 `[[NL2AGENT_CARD_RETRY]]` 只触发重新读状态。
6. 状态缺失或矛盾时 fail closed，不猜测。

---

## 9. 搜索与可信结果

### 9.1 共享规范化和评分

三个 SDK 工具共享：

1. Unicode NFKC 和 `casefold`。
2. ASCII token 提取；连续 CJK 文本使用 jieba 分词。
3. 删除中英文 stop words 和重复词。
4. 排序 token 得到与输入顺序无关的 Canonical Query。
5. 名称、description 以及候选中实际存在的 tags/labels 参与匹配。
6. 名称权重最高，metadata 相似度乘 0.9。
7. 长度不超过 3 的 token 不做 fuzzy。
8. RapidFuzz 不可用时回退 SequenceMatcher。
9. 最低单关键词分数 0.62，结果采用 OR 匹配和 coverage 加权。

本地搜索 Prompt 使用 2–6 个原子能力关键词；MCP 和 official Skill 使用 1–3 个英文索引词。中文需求会转换为英文 online query，同时保留 `docx`、`pdf` 等准确格式。

### 9.2 本地资源

- Catalog 包含来源为 local、MCP 或 LangChain 的 Tool，以及 tenant 已有 Skill。
- Tool 与 Skill 分别评分后按稳定 ID、规范化名称去重。
- 两类合计最多返回 5 条。
- 结果带 `recommendation_batch_id`、Tool/Skill ID、分数和原因。
- Tool 参数 Schema 在注册后由 Backend 重新读取并脱敏，Card 可收集声明过的配置。

### 9.3 MCP

- Registry 和 Community 每页 100 条，最多 20 页、2,000 条、5 MiB、15 秒。
- SDK 只搜索 Session Catalog，不直接访问市场或互联网。
- Registry 优先于 Community；按稳定 recommendation ID 和名称去重，最多返回 5 条。
- normalizer 将 remote、package、container、environment、header、JSON、port 和模板变量统一为 install options。
- 无法安全推导的字段必须由用户在 Card 中填写，不从 LLM 猜测。

### 9.4 official Skill

- official Catalog 同时保留 `installable` 和 `resource_missing` 项。
- `resource_missing` 项从本地 Skill 搜索中排除，但可在 online Card 中通过 official ZIP 恢复。
- 已安装项通过持久化 installation result 投影为 `installed`，后续搜索不再推荐。
- 结果按 ID 和规范化名称去重，最多返回 5 条。

### 9.5 Trusted Search Proof

搜索工具返回结果前，必须通过注入的 Backend callback 持久化 batch ID、resource type，以及完整排序后的 Tool IDs、Skill IDs 或 online item keys。

持久化失败时工具返回 error，不生成可操作 Card。Backend 最终答案校验、Card 注册和 Card Delivery 都会核对这份 proof；模型或客户端删除、替换、过滤或添加资源都会被拒绝，包括伪造的空批次。

---

## 10. 业务阶段与副作用

### 10.1 需求摘要

- 五项内容做 NFKC 和空白规范化。
- 对排序后的 Canonical JSON 计算 SHA-256 fingerprint。
- 相同摘要重复注册幂等；不同摘要替换当前摘要并重新进入待确认。
- Confirm 必须携带当前 fingerprint；历史 Card 不能确认新摘要。
- 明确修改、否定或纠正可把状态恢复为 collecting；“确认”“yes”“继续”不会确认。

### 10.2 模型选择

- Frontend 只展示平台 API 中 available 的 LLM。
- Backend 再验证 tenant、存在性、LLM 类型、连接状态、重复和数量。
- `business_logic_model_id` 保存 primary，`model_ids` 保存 primary + ordered fallbacks。
- 总数最多 5 个；Finalize 时再次验证模型仍可用。
- `requested_output_tokens` 不得超过 primary model 能力。

### 10.3 本地 Apply / Skip

- Card 注册前按钮不可执行。
- 用户可选择推荐批次中的 Tool/Skill，并为 Tool 填写声明过的参数。
- Backend 拒绝未知字段、错误类型、非法 choice、缺失 required 和未选 Tool 的配置。
- Secret default 不下发；持久化摘要只返回“已配置”而不回显值。
- Apply 对本次选中项全有或全无；数据库提交失败时不保留部分 binding。
- operation fingerprint 包含批次、资源和配置，用于并发与重试对账。
- Skip 只解决指定批次。

### 10.4 MCP 安装与绑定

安装流程：

1. 从 trusted Session Catalog 解析 recommendation 和 option。
2. 获取 recommendation 级 5 分钟锁；不同 option 不能并发安装同一推荐。
3. heartbeat 每 60 秒续租并验证 token 所有权。
4. 只接受 option 声明过的 `config_values.fields`。
5. 创建或复用带 installation provenance 的 MCP。
6. 执行健康检查、工具发现并 upsert Tool Catalog。
7. 标记 `connected`，但不自动绑定。
8. 用户至少绑定一个已发现 Tool，或显式 skip-tools。

容器在数据库写失败后立即补偿删除。工具发现失败可保留已创建 MCP 并从该步骤恢复。绑定使用独立 operation reservation，重复请求不会创建重复 ToolInstance。

### 10.5 online Skill 与完成栏

- Skill 安装按 canonical ID/name 生成稳定 installation key。
- 同一项并发安装被锁拒绝；完成结果可幂等返回。
- 安装成功后解析 tenant Skill 并立即绑定 Draft。
- MCP 和 Skill 两类 batch 都注册后才可完成 online 配置。
- `installing`、`connected` 或 `binding` MCP 尚未解决时不能完成。
- 未安装或失败的推荐可统一放弃；已 connected MCP 必须 bind 或 skip。

### 10.6 身份与 Finalize

- LLM 根据已确认需求建议 2–50 字符 display name，用户可修改。
- Backend 保持 Draft 的 `draft_*` internal name，直到 Finalize。
- Finalize 时规范化为 snake_case；空值或数字开头使用 `agent_{id}`，冲突时追加 Draft ID。
- Final Card 的 proposal 只允许描述、Prompt、示例和受支持运行参数。
- 身份、模型、Tool、Skill、MCP 和配置始终取持久化状态；旧的模型/资源字段和未知字段被拒绝。
- 提交前重新解析所有模型和 enabled resource reference；悬空、跨 tenant 或不可用引用阻断提交。

---

## 11. Card Contract 与交付

### 11.1 七类逻辑 Card

Canonical Schema 位于 `contracts/nl2agent-card.schema.json`：

1. `nl2agent-requirements-summary`
2. `nl2agent-model-selection`
3. `nl2agent-local-resources`
4. `nl2agent-web-mcp` / `nl2agent-web-mcps`
5. `nl2agent-web-skill` / `nl2agent-web-skills`
6. `nl2agent-agent-identity`
7. `nl2agent-finalize`

逻辑上是七类 Card；MCP 和 Skill 各允许单数/复数 fence，因此 Frontend 共识别九个 Card language tag。`nl2agent-search-*` 是工具调用标签，不渲染为 Card。

Payload `agent_id` 可选，以支持 Conversation-scoped trusted Draft fallback；若存在则必须与当前 Draft 完全相同。两边都没有可信 ID、ID 冲突、附加字段、Schema 不匹配或同类 Card 重复时拒绝渲染。

### 11.2 流式与最终消息

- SSE 和 Task Window 在生成期只显示“正在生成 Card”占位。
- 只有完整 final assistant message 才进行一次完整 Card AST 解析。
- Backend 在消息持久化前验证 fence、JSON、Schema、Draft ID、唯一性和 trusted proof。
- Frontend 用 Ajv 再校验并挂载 React Card。
- 历史消息、只读/分享模式、非最新消息和组件重挂载不触发副作用。

### 11.3 Delivery Receipt

`POST /session/{draft}/card-delivery` 使用数据库数字 `message_id`。Backend 验证 Session 主体、Conversation、assistant/completed 状态、最新 completed assistant message、当前 expected card、Schema、Draft、card key 和 trusted proof。

Requirements、Local、MCP 和 Skill Card 需要完成业务注册或与注册状态一致，再记录 rendered。回执本身按 message、type、status 和 card key 幂等。

### 11.4 失败与恢复

失败原因限定为 `truncated_fence`、`invalid_json`、`invalid_schema`、`missing_card`。失败只更新 Delivery，不删除已确认业务状态。前两次返回 `[[NL2AGENT_CARD_RETRY]]` 并允许自动重跑；第三次起停止自动执行并提供手动重新生成。

回执 API 自身失败只显示“重试回执”，不会误计为模型 Card 失败。Card Delivery 持久化在 Durable Workflow State，因此刷新后不会重复消费已成功交付的 Card。

---

## 12. Frontend 交互与自动继续

Agent 管理页和 Agent Selector Header 都提供 Builder 入口。`Nl2AgentWorkflowProvider` 以 Conversation + Draft 为 scope，管理 active Session、Backend State、action/registration/Delivery/continuation 并发、聊天输入 blocker、状态刷新和显式重试。

`useNl2AgentSessionRecovery` 在切换 Conversation 时从 Backend 恢复 Session，缓存已确认的普通 Conversation，并避免把一个 Draft 复用到另一个 Conversation。

以下动作成功后返回固定 `chat_injection_text` 并通过现有 `/agent/run` 自动继续：

- 确认需求；
- 保存模型；
- Apply 或 Skip 本地资源；
- 完成 online 配置；
- 保存身份；
- Card 自动重试。

这些消息进入正常历史和 message index，但 Frontend 不显示 user bubble，也不参与分享。MCP/Skill 单项安装、MCP bind/skip 和失败不会自动进入下一阶段；用户在统一完成栏结束 online review。

刷新后 Card 根据 `/state` 返回的 persisted selection、batch、installation、binding、Delivery 和参数摘要恢复展示。Secret 只恢复“是否已配置”，不恢复值。

---

## 13. Public API

所有专用接口位于 `/nl2agent`：

| 方法 | 路径 | 作用 | 自动继续 |
|---|---|---|---|
| GET | `/sessions` | 列出当前用户 active Sessions | 否 |
| GET | `/session/by-conversation/{conversation_id}` | 按 Conversation 恢复 Session | 否 |
| POST | `/session/start` | 创建 Draft、Conversation 和 Durable Session | 否 |
| POST | `/session/{agent_id}/abandon` | 显式终止 active Session | 否 |
| POST | `/session/{agent_id}/requirements/register` | 注册需求摘要与 fingerprint | 否 |
| POST | `/session/{agent_id}/requirements/confirm` | 确认当前摘要 | 是 |
| PUT | `/session/{agent_id}/models` | 保存 primary 和 fallback LLM | 是 |
| POST | `/session/{agent_id}/local-resources/register` | 注册可信本地批次 | 否 |
| POST | `/session/{agent_id}/apply-local-resources` | 配置并绑定本地资源 | 是 |
| POST | `/session/{agent_id}/local-resources/skip` | 跳过本地批次 | 是 |
| POST | `/session/{agent_id}/online-recommendations/register` | 注册 MCP/Skill 批次 | 否 |
| POST | `/session/{agent_id}/mcp/install` | 安装、检查和发现 MCP Tool | 否 |
| POST | `/session/{agent_id}/mcp/{mcp_id}/bind-tools` | 绑定 MCP Tool | 否 |
| POST | `/session/{agent_id}/mcp/{mcp_id}/skip-tools` | 跳过 MCP Tool 绑定 | 否 |
| POST | `/session/{agent_id}/install-web-skill` | 安装/恢复 official Skill 并绑定 | 否 |
| POST | `/session/{agent_id}/online-configuration/complete` | 完成 online review | 是 |
| GET | `/session/{agent_id}/state` | 返回可恢复 Workflow 和资源投影 | 否 |
| PUT | `/session/{agent_id}/identity` | 保存 display name | 是 |
| POST | `/session/{agent_id}/card-delivery` | 记录 Card rendered/failed | failed 前两次 |
| POST | `/session/{agent_id}/finalize` | 写入完整 Draft 并完成 Session | 否 |

既有 `/agent/run` 增加可选 `draft_agent_id`，用于绑定 Runner Run 与 Durable Session。所有 NL2AGENT Request model 使用 `extra="forbid"`、严格正整数和集合容量限制。

结构化错误：

| ErrorCode | HTTP | 含义 |
|---|---:|---|
| `030201` | 404 | Draft/Session 不存在、非 active 或不属于当前主体 |
| `030202` | 409 | 当前 Workflow 不允许该动作 |
| `030203` | 409 | Card 来自过期消息或旧状态 |
| `030204` | 409 | Workflow CAS 冲突重试耗尽 |
| `030205` | 503 | 必需 Catalog provider 不可用 |
| `030206` | 400 | 请求、配置或引用不合法 |
| `030207` | 500 | 内部数据库或持久化操作失败 |
| `030208` | 502 | 外部安装、连接或发现失败 |

---

## 14. 安全与隔离

### 14.1 身份与租户

- 所有 API 在业务变更前验证 tenant + user + active Session。
- Agent Run 额外验证 persisted Runner、Draft 和 Conversation。
- 对不存在、终态和他人 Session 使用相同不可见语义。
- Tool/Skill/MCP 查询与 binding 均 tenant scoped。
- Recommendation、option、resource ID 必须来自当前 Session 的 trusted snapshot/proof。

### 14.2 Secret

Secret 不进入 Prompt、Current Session、SDK 搜索默认值、Durable Catalog/Workflow、installation key、日志、成功响应和 Final Review 可见值。Secret 只从密码型 Card 字段进入既有 credential/MCP 或 ToolInstance 保存链路；Backend 可返回 `configured=true`，但值始终为 null。

### 14.3 MCP 网络

- remote URL 只允许 HTTP/HTTPS，不允许 URL 内嵌 credentials。
- 默认拒绝 private、loopback、link-local 和其他非 global 地址；仅通过 `NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS` 集中配置允许时放开。
- 连接前解析全部地址并固定到验证过的 DNS 快照，防止 DNS rebinding。
- pinned transport 保留原始 Host/SNI，TLS 使用系统可信链并保持 `verify=true`。
- 禁止 proxy、`trust_env` 和 Unix socket；redirect 到其他 host/port 会失败。

### 14.4 容量与并发

- Workflow collection 每类最多 100 项。
- 本地 Catalog 各最多 2,000 条。
- Marketplace 有页数、条数、字节和超时预算。
- Card、Request、字段长度、数组和 map 都有 Contract 上限。
- 安装与 binding 使用 token-owned reservation/lock，释放和续租都检查所有权。

---

## 15. Contract 与生成链路

单一来源：

- Card：`contracts/nl2agent-card.schema.json`。
- HTTP：FastAPI `/nl2agent` routes、Pydantic Request/Response 和递归依赖 Schema。
- Workflow：Backend Pydantic state model。

生成物：

- `contracts/nl2agent-openapi.json`
- `frontend/contracts/generated/nl2agent-card.schema.json`
- `frontend/contracts/generated/nl2agent-api.ts`

`frontend/scripts/sync-nl2agent-contracts.mjs` 复制 Card Schema、调用 Backend OpenAPI exporter、生成 TypeScript 并格式化。`npm run contracts:check` 在临时目录重建并比较，防止 Request、Response、Schema 和 Frontend 类型漂移。

---

## 16. 数据库迁移与部署

Fresh install schema 位于 `deploy/sql/init.sql`。升级脚本按顺序包括：

1. `v2.3.0_0716_add_nl2agent_session.sql`：Durable Session。
2. `v2.3.0_0717_index_nl2agent_session_cleanup.sql`：生命周期清理索引。
3. `v2.3.0_0717_share_nl2agent_catalog_snapshots.sql`：共享 Catalog Snapshot。
4. `v2.3.0_0717_unique_nl2agent_builder.sql`：tenant Runner 唯一约束。
5. `v2.3.0_0718_persist_nl2agent_runner.sql`：持久化 Runner ID 和回填。

Docker 与 Kubernetes 使用现有 checksum + advisory lock migration 机制。SQL 文件名是 migration ID；checksum 相同跳过，checksum 变化时重放幂等 SQL 并更新记录。

本地源码运行前必须执行：

```bash
python deploy/common/run_local_sql_migrations.py
```

本地 runner 会应用 init/migrations，并验证 `runner_agent_id` 列、v0718 migration 记录，以及不存在 runner 为空的 active Session。

根目录 `repair_nl2agent_tables.py` 是迁移接入期间留下的临时诊断/修复工具，不包含完整的当前 migration provenance，也不能替代 v0718 runner migration 和标准 schema guard；正常安装与升级只使用统一 migration runner。

部署时 Backend、SDK 和 Frontend 应使用同一 Contract 版本。无需手工删除 Redis Session Key；数据库快照会在 Cache miss 时恢复。

---

## 17. 测试策略

| 层 | 覆盖重点 |
|---|---|
| Workflow/Repository | 严格 v2 State、DB CAS、终态拒绝、Cache miss/Redis failure 恢复 |
| Session Lifecycle | owner 隔离、Conversation 恢复、列表、abandon、retention |
| Backend Services | 模型校验、本地配置、MCP Saga、Skill 恢复、Finalize 事务 |
| Card Delivery | Backend/Frontend Schema、trusted proof、最新消息、retry 和刷新恢复 |
| SDK | 分词、评分、稳定 batch、隔离 context、空结果、proof recorder |
| Contract | 七类 Card、20 个 typed API、Prompt 示例与边界一致 |
| Frontend | Card 行为、注册时序、busy/blocker、自动继续、会话切换 |
| Deploy | migration 顺序、checksum、advisory lock 和 schema guard |

主要门禁：

```bash
backend/.venv/bin/pytest \
  test/contracts/test_nl2agent_card_contract.py \
  test/contracts/test_nl2agent_session_contract.py \
  test/backend/services/test_nl2agent_session_persistence.py \
  test/backend/services/test_nl2agent_session_lifecycle_service.py \
  test/deploy/test_local_sql_migrations.py

npm --prefix frontend run contracts:check
```

完整 Frontend 门禁仍为 `npm run check-all`；完整 Backend/SDK 门禁仍由 `test/run_all_test.py` 执行。

---

## 18. 当前实现约束

以下约束不改变主流程，但维护时必须明确：

1. official Skill 的同步安装函数当前在 async Service 内执行，耗时 ZIP/文件操作可能占用 worker event loop。
2. 模型选择、本地 binding 和部分 Workflow 更新通过 reservation/补偿保证恢复，不是跨所有业务表的一次数据库事务。
3. Session 清理由 Session Start opportunistic 触发，没有独立定时调度器。
4. Redis 虽不是持久化权威源，但 MCP/Skill 分布式安装锁仍依赖 Redis 可用。
5. 部分 Card 业务文案仍为硬编码英文，尚未完全收敛到 i18n。
6. 资源最终分组依赖持久化 `source` 的规范值；非规范 source 可能影响 local/online 展示分组。
7. `Nl2AgentContext` 为 per-run 实例，但其 dataclass 和注入列表并未在类型层强制 immutable。
8. 临时 `repair_nl2agent_tables.py` 不是当前完整迁移路径，不应用于常规部署。

这些是当前代码的真实边界；历史审查文档只记录当时快照，不能替代本文和现行测试结果。
