# NL2AGENT 代码走读

> 最近复核：2026-07-16
>
> 维护规则：按当前真实调用路径维护，不绑定易失效的 commit、revision 或变更文件计数。

本文是《[NL2AGENT 对话式智能体构建设计](./nl2agent-design)》的代码级 companion。设计文档解释“为什么这样设计”和“对外表现是什么”，本文解释“代码从哪里进入、如何流动、在哪里写数据、出错时停在哪里”。

---

## 1. 建议阅读顺序

第一次阅读当前实现，建议按以下顺序：

1. `backend/agents/nl2agent_workflow.py`：先理解唯一阶段评估器。
2. `backend/agents/nl2agent_session_catalog.py`：理解 Redis v2 State、CAS 和 Catalog。
3. `backend/services/nl2agent_session_service.py`：理解一次构建会话如何产生 Draft 和 Conversation。
4. `backend/agents/create_agent_info.py`：理解 State/Catalog 如何进入 Prompt 与 SDK Tool。
5. `sdk/nexent/core/tools/nl2agent/`：理解三种搜索到底执行了什么。
6. `backend/prompts/nl2agent_system_prompt_{zh,en}.yaml`：理解模型如何消费 `current_stage`。
7. `frontend/components/nl2agent/cardValidation.ts` 与 `index.tsx`：理解 fenced JSON 如何变成 Card。
8. `frontend/app/[locale]/chat/streaming/chatStreamFinalMessage.tsx`：理解最终消息验收和 Card Delivery。
9. 六个专用 Backend Service：理解用户动作如何落数据库和 Redis。
10. `frontend/components/nl2agent/FinalizeCard.tsx` 与 Publication Service：理解最终提交。

---

## 2. 变更地图

当前实现可以按职责分为十组：

| 分组 | 代表文件 | 作用 |
|---|---|---|
| State / Workflow | `nl2agent_workflow.py`、`nl2agent_session_catalog.py` | v2 schema、CAS、阶段计算、批次和回执 |
| Backend API | `nl2agent_app.py`、`consts/model.py` | 17 个 Session action endpoint 与严格请求模型 |
| Backend Services | `nl2agent_*_service.py` | Session、Catalog、资源、MCP、Workflow、Publication |
| Agent Runtime | `create_agent_info.py`、`agent_service.py` | Draft ID、Current Session、per-run Tool context |
| Prompt | 双语 YAML、prompt utils/service | 确定性状态机和 seed 字段 |
| SDK | `tools/nl2agent/`、`nexent_agent.py` | 三个 builtin search tools 与共享搜索算法 |
| Frontend | `components/nl2agent/`、chat streaming | 入口、Card、校验、回执、自动续跑 |
| Contract | `contracts/`、生成脚本 | Canonical Card Schema 与 NL2AGENT OpenAPI |
| 既有基础设施扩展 | database、MCP、Skill、Conversation | 共享事务、直接返回 MCP ID、批量查询、消息校验 |
| Tests / Docs | `test/...`、Vitest、三份设计审查文档 | 状态向量、交互、契约和回归覆盖 |

---

## 3. Config Service 启动和 Seed

### 3.1 调用链

```text
backend/apps/config_app.py startup
  ├─ sync prompt templates
  └─ services.nl2agent_service.seed_nl2agent_default_agent()
       ├─ database.tool_db: ensure 3 builtin definitions
       ├─ load backend/agents/default_agents/nl2agent.json
       ├─ create/update internal Agent(name="nl2agent")
       └─ bind exactly 3 builtin tools
```

Runtime Service 的 `backend/apps/runtime_app.py` 只 include `nl2agent_app.router`，不会调用 seed。这个边界避免多个 Runtime worker 并发创建默认 Agent。

### 3.2 三个 Tool 的定义

`backend/database/tool_db.py` 中的 `NL2AGENT_BUILTIN_TOOL_DEFINITIONS` 是 Backend Catalog 的来源。实际只有：

- `NL2AgentSearchLocalResourcesTool`
- `NL2AgentSearchWebMcpsTool`
- `NL2AgentSearchWebSkillsTool`

它们的 `source="builtin"`、`category="nl2agent"`。`backend/agents/default_agents/nl2agent.json` 用相同 class name 绑定 Runner。

SDK 的 `sdk/nexent/core/agents/nexent_agent.py::create_builtin_tool` 对这三个 class name 分支构造独立实例。不存在 apply、install 或 finalize builtin 分支。

### 3.3 Prompt Seed 字段

`backend/utils/prompt_template_utils.py` 注册两个 YAML 路径：

- `backend/prompts/nl2agent_system_prompt_zh.yaml`
- `backend/prompts/nl2agent_system_prompt_en.yaml`

`get_nl2agent_system_prompt()` 返回运行用 system prompt；`get_nl2agent_seed_config()` 提取默认 display name、description、greeting 等 seed 字段。`backend/services/prompt_service.py` 把 YAML 作为 Prompt Template 同步对象处理。

---

## 4. Agent Builder 入口到 Session Start

### 4.1 Frontend 入口

两个入口文件都新增 Agent Builder 操作：

- `frontend/app/[locale]/agents/components/AgentManageComp.tsx`
- `frontend/app/[locale]/agents/components/AgentSelectorHeader.tsx`

它们调用 `frontend/services/nl2agentService.ts::startNl2AgentSession()`。成功后把 Runner、Draft 和 Conversation 的一次性 handoff 信息写入 sessionStorage，然后导航到聊天页。

### 4.2 HTTP 入口

```text
POST /nl2agent/session/start
  backend/apps/nl2agent_app.py::start_session_api
    → backend/services/nl2agent_service.py::start_session
      → backend/services/nl2agent_session_service.py::start_session
```

facade 通过 `_session_initialization_dependencies()` 把数据库、Catalog、Redis 和日志依赖显式注入专用 Service，便于测试失败点。

### 4.3 Catalog 前置加载

`nl2agent_session_service.start_session()` 先验证默认 Runner，然后调用：

```text
nl2agent_catalog_service.load_session_catalogs()
  ├─ list_all_tools() → local_tools
  ├─ SkillManager / DB → local_skills
  ├─ Registry service(search=None, limit=100, cursor=...) → registry_results
  ├─ Community service(search=None, limit=100, cursor=...) → community_results
  └─ get_official_skills_with_status() → official_skills
```

MCP Catalog 在写 Redis 前经过 `redact_mcp_marketplace_metadata()`。official Skill 只保留 `installable`；`installed` 和 `resource_missing` 不进入推荐，其中 `resource_missing` 在 Draft ID 可用后记录 tenant/draft/name warning。

本地 Tool、租户 Skill 和 official Skill provider 异常会转换为 `Nl2AgentCatalogUnavailableError`。Registry 与 Community 并发加载、分别捕获异常；其中一个市场不可用时记录告警并使用空结果，不阻断 Session。空列表本身不报错。

### 4.4 数据库与 Redis 初始化

Service 使用 caller-owned SQLAlchemy Session：

```text
database transaction
  ├─ agent_db.create_agent(..., db_session=session)
  └─ conversation_db.create_conversation(..., db_session=session)

before transaction exits
  ├─ initialize_nl2agent_session_state(tenant, draft, conversation)
  └─ set_nl2agent_session_catalogs(tenant, draft, catalogs)
```

`agent_db.create_agent` 和 `conversation_db.create_conversation` 是为这条共享事务链路扩展的：不传 Session 时保持既有自管理事务，传入时不自行提交。

Redis 失败抛出后，数据库 context rollback；若 State 已写而 Catalog 失败，则清理两个 Key。若数据库最终 commit 失败，异常处理也会删除已写 Redis。

### 4.5 Frontend 建立 Conversation 映射

`frontend/app/[locale]/chat/internal/chatInterface.tsx` 消费 handoff，并持久化：

```text
nl2agent_draft_by_conversation[conversation_id] = draft_agent_id
```

`frontend/lib/chat/nl2agentDraftContext.ts` 提供两个解析器：

- `resolveNl2AgentDraftAgentId()`：按 active Conversation 找 Draft，只在 Conversation 一致时使用 handoff fallback。
- `resolveNl2AgentCardAgentId()`：合并 payload ID、nested item IDs 和 trusted conversation ID，发现冲突就返回 mismatch。

这段代码修复了 Conversation 切换时错误复用另一个 Draft 的问题。

---

## 5. Redis v2 State 与 Workflow Evaluator

### 5.1 严格 State Model

`backend/agents/nl2agent_workflow.py` 定义：

- `RequirementsReview`
- `RecommendationBatch`
- `OnlineRecommendationBatch`
- `McpWorkflow`
- `CardDelivery`
- `Nl2AgentWorkflowState`
- `WorkflowSummary`

`Nl2AgentWorkflowState` 固定 `schema_version=2`，包含单调 `revision` 和正整数 `conversation_id`。除本地批次和 MCP workflow 为容纳稳定业务投影允许额外项外，核心状态使用严格字段约束。

### 5.2 State Repository

`backend/agents/nl2agent_session_catalog.py` 同时承载 State 与 Catalog repository。

读取链路：

```text
get_nl2agent_session_state()
  → Redis GET
  → _parse_session_state()
  → Nl2AgentWorkflowState.model_validate()
  → state_to_dict()
```

缺 Key、旧 schema 或 malformed JSON 都抛出领域错误。代码不创建临时空对象继续运行。

写入链路统一经过 `_mutate_session_state()`：

```text
for attempt in 1..5
  WATCH key
  GET + strict parse
  mutator(state)
  state.revision += 1
  MULTI
  SET key json EX 24h
  EXEC
```

Watch 冲突会重新读取最新状态再运行 mutator，而不是重放旧序列化结果。

Catalog 对应 `mutate_nl2agent_session_catalogs()`，也使用 WATCH/MULTI，但没有 State revision。

### 5.3 状态评估顺序

`evaluate_workflow()` 是纯函数。它按以下短路顺序返回第一个未完成阶段：

```text
requirements collecting
→ requirements confirmation
→ model selection
→ local search
→ local review
→ online search (MCP and Skill independently missing)
→ online review / unresolved MCP
→ identity
→ final review
```

它同时调用 `_card_was_rendered()` 判断当前所需 Card 是否已有成功回执。未渲染时 `expected_card_types` 包含 Card；渲染后阶段不变，但期望 Card 为空并只保留用户动作。

`get_workflow_summary()` 是其他 Backend 模块读取阶段的唯一入口。Frontend Session State 也直接消费 summary，不重新实现完整阶段判断。

---

## 6. 一次 `/agent/run` 如何获得 NL2AGENT 上下文

### 6.1 请求字段传播

`backend/consts/model.py::AgentRequest` 增加可选 `draft_agent_id`。Frontend 在 NL2AGENT Conversation 中每次发送消息都携带它。

`backend/services/agent_service.py` 的运行链路把该 ID传入 `create_agent_run_info` / `create_agent_config`，最终到 `backend/agents/create_agent_info.py`。

### 6.2 需求修改预处理

在用户消息保存和 Prompt 构造之前，`agent_service.py` 检查正整数 Draft ID，然后调用：

```text
nl2agent_service.process_requirements_revision_text()
  → nl2agent_workflow_service.process_requirements_revision_text()
    → session_catalog.apply_requirements_revision_text()
```

该函数只在实际 Runner 名为 `nl2agent`、当前 requirements 状态为 `awaiting_confirmation` 时生效。`classify_requirements_message_intent()` 对 NFKC、大小写、空白和标点归一化后的中英文文本识别修改/否定；确认类文字返回 `confirmation_requires_button`，不写 confirmed。

因此本轮修改可以在同一次 Agent Run 的 Current Session 中体现为 `collecting`。

### 6.3 构造 Current Session

`create_agent_info.py` 的关键函数：

- `_load_nl2agent_system_prompt(language)`
- `_is_nl2agent_model_selection_confirmed(draft_agent_info)`
- `_build_nl2agent_current_session(...)`

执行逻辑：

1. 只有 `agent_info["name"] == "nl2agent"` 才启用专用 Prompt。
2. 用 tenant/draft 严格加载 Redis State。
3. 加载 Draft 数据库记录。
4. 从 Draft 持久化 `business_logic_model_id/model_ids` 计算模型是否真正已选，并投影到本次评估对象。
5. 调用 `evaluate_workflow()`。
6. 构造不含资源 ID 和 Secret 的摘要 JSON。
7. 追加到 YAML system prompt，注明它是 Agent Run 开始时快照。

数据库模型选择在这里覆盖 Redis 的投影，避免 Redis flag 与 Draft 字段不一致时模型被错误放行。

### 6.4 构造三个 Tool 实例

同一个函数随后调用 `get_nl2agent_session_catalogs(tenant, draft)`，并为三个 `ToolConfig` 注入：

- Runner `agent_id`
- `draft_agent_id`
- tenant/user/language
- `requirements_confirmed`
- 五类 Catalog 数组

SDK `NexentAgent.create_builtin_tool()` 根据 class name 创建三个不同对象。每个对象通过 `create_nl2agent_context()` 保存各自上下文，后续构造不会覆盖前一个对象。当前实现不对 Catalog List 做深拷贝，也没有 frozen dataclass；隔离来自“不再使用 module-level global”，搜索代码约定只读这些引用。

---

## 7. 双语 Prompt 如何驱动唯一动作

两个 YAML 都包含 `agent_info`、`prompt_segments` 和 `system_prompt: |-`。实际 system prompt 按以下规则运行：

1. 本步骤有新的搜索 Observation：先输出对应结果 Card，不再次搜索。
2. 没有 Fresh Observation：只执行 Current Session `allowed_actions` 指定的第一个未完成动作。
3. 需求五项缺哪项就只问哪一项。
4. Card 未交付时输出紧凑、闭合的 fenced JSON；Card 已交付则只提示用户操作现有 Card。
5. 模型不能命名平台 LLM；选择项只来自 Frontend Card。
6. 只允许三个确切工具名出现在 `<code>` 调用中。
7. Card tag 只在最终回复中使用，不能作为工具调用。
8. `[[NL2AGENT_AUTO_CONTINUE]]` 与 `[[NL2AGENT_CARD_RETRY]]` 只触发重新读取状态。

Prompt 中直接给出 Requirements、Model、Identity 和 Final Card schema 示例；Local/MCP/Skill Card 要求复制真实 Observation，不能重建 ID 或安装 option。

---

## 8. SDK 共享搜索内核

### 8.1 `Nl2AgentContext`

`sdk/nexent/core/tools/nl2agent/_context.py::Nl2AgentContext` 保存：

- `agent_id` 与 `draft_agent_id`
- tenant、user、language
- `requirements_confirmed`
- local tools/skills、registry/community MCP、official skills

`target_agent_id` 优先 Draft；缺 Draft 才回退 Runner。三个搜索工具先检查 tenant、Draft/context 和 requirements gate，失败时返回 JSON error，不执行检索。

### 8.2 Token 和 canonical query

`normalize_search_keywords(query)`：

1. NFKC + casefold。
2. regex 提取 ASCII 字母数字串或连续 CJK 串。
3. 删除 stop words。
4. 按首次出现顺序去重。

`canonical_search_query(query)` 再排序 token，用单元分隔符连接，使“PPT docx”和“docx，ppt”产生同一 canonical key。

### 8.3 `_score_candidates()`

候选先转换为 searchable name 和 metadata。对每个关键词：

- name 与 metadata 分别计算 `_keyword_similarity()`；
- metadata 得分乘 `0.9`；
- 记录达到阈值 `0.62` 的 matched keyword；
- 无关键词达标则过滤；
- 最终 `0.85 * best + 0.15 * coverage`。

输出在候选上增加 `score` 和基于 matched keywords 的 `reason`，按 score 降序、名称稳定排序。

SDK 没有 `_search_cache`。Catalog 变化后下一次 Agent Run 重新构造实例并重新计算。

---

## 9. 本地搜索调用链

```text
model emits:
<code>
result = nl2agent_search_local_resources(query="...")
print(result)
</code>

SDK NL2AgentSearchLocalResourcesTool.forward()
  → get_search_local_resources_tool(context)
    → _rank_local_resources(local_tools, local_skills, query)
      → _score_candidates()
      → _deduplicate_local_items()
      → merge and max 5
    → _recommendation_batch_id()
    → JSON {agent_id, recommendation_batch_id, tools, skills}
```

Tool 与 Skill 分别按 ID 和规范化名称去重，再合并排序。同分 Tool 优先。批次哈希包含 Draft、canonical query 和去重后的资源 ID；空结果也形成稳定批次。

模型在 Fresh Observation 后输出 `nl2agent-local-resources` Card。Frontend 真实挂载后调用 register API，只有成功后 Apply/Skip 按钮启用并提交 rendered receipt。

---

## 10. MCP 搜索与规范化调用链

```text
NL2AgentSearchWebMcpsTool.forward(query)
  → registry candidates first
  │   └─ normalize_mcp_candidate("registry", raw)
  → community candidates second
      └─ normalize_mcp_candidate("community", raw)
  → fuzzy score name + description
  → deduplicate recommendation_id + normalized name
  → max 5
  → online_recommendation_batch_id("mcp", ...)
  → JSON {agent_id, recommendation_batch_id, items}
```

### 10.1 Registry 解析

`normalize_mcp_candidate()` 读取 `raw.server`：

- `remotes` 生成 remote option；
- URL template 变量成为 field；
- headers 成为 header field；
- `packages` 保留 runtime、identifier、runtimeArguments、packageArguments、environment 和 transport。

npm/npx 与 pypi/uvx package 支持 container 安装。若 package transport 自带非 stdio URL，可形成 remote option。

### 10.2 Community 解析

Community 先尝试嵌套 `registryJson`，然后应用 `serverUrl`、`transportType`、`configJson` 覆盖。显式 URL 优先形成 remote；container 缺元数据时补出必填 port、environment/config JSON 字段。无法安全构建时返回 unsupported option，而不是生成危险默认命令。

### 10.3 Secret 清理

`_normalize_fields()` 根据 `isSecret` 和字段名识别 Secret，清空 default。Backend Session Catalog 在更早阶段也递归清空 header/env/token/password 等默认值，形成双重边界。

---

## 11. online Skill 搜索调用链

### 11.1 Backend 候选生成

`backend/services/skill_service.py::get_official_skills_with_status()` 扫描 official Skill 目录。每项元数据按 tenant DB、global official DB、ZIP `SKILL.md` 的优先级补齐。

返回项同时提供 `skill_id`、`skill_name`、兼容 `name`、description、tags、source 和 status。ZIP 或 metadata 解析失败记录日志并用空 description/tags，单项异常不终止整个目录。

`nl2agent_catalog_service.load_session_catalogs()` 只保存 installable；installed 静默过滤，resource_missing 过滤并记录 warning。

### 11.2 SDK 排序

```text
NL2AgentSearchWebSkillsTool.forward(query)
  → _rank_web_skills(official_skills, query)
    → defensive status == installable
    → name = skill_name or name
    → _score_candidates(name, description, tags)
    → dedupe skill_id + normalized name
    → max 5
  → online_recommendation_batch_id("skill", ...)
```

结果仍是 Catalog 搜索，不进行网络请求。

### 11.3 安装后刷新

```text
POST install-web-skill
  → nl2agent_service.install_web_skill()
    → nl2agent_catalog_service.install_web_skill()
      → validate tenant/draft + trusted catalog candidate
      → existing SkillManager install chain
      → _remove_installed_skill() via catalog CAS
```

HTTP 请求体只提供 Skill ID/name；Backend 必须在当前 Draft Catalog 中解析到 installable 项。安装完成后，Backend 解析 tenant Skill ID、创建或更新 Draft `SkillInstance`，最后从 Session Catalog 删除推荐；任一步失败都不会把推荐错误地标记为完成。

---

## 12. Fenced JSON 到 React Card

### 12.1 Canonical Schema

`contracts/nl2agent-card.schema.json` 使用 Draft-07 `$defs` 定义七类 Card。`frontend/contracts/generated/nl2agent-card.schema.json` 是同步副本。

`frontend/components/nl2agent/cardValidation.ts`：

- `LANGUAGE_TO_TYPE` 把 fence tag 映射为 CardType；
- `REGISTRATION_CARD_TYPES` 包含 requirements/local/MCP/Skill；
- Ajv 为每个 `$defs` 编译 validator；
- `parseNl2AgentCard()` 解析单个 fence 内容和 trusted ID；
- `validateNl2AgentCards()` 扫描完整消息，检查闭合 fence、重复 Card 和失败原因。

Parser 产生按九种 fence language 判别的 `ValidatedNl2AgentCard` 联合 AST，其中含强类型 payload、card type、card key 和 `requiresRegistration`。`nl2agent-search-*` 不在 tag 映射中；online 单数/复数 tag 与 payload 形态不匹配会被拒绝。

Final Message Delivery 调用 `validateNl2AgentCards()` 一次，并把得到的 `nl2AgentCards` 直接传给 Renderer。Renderer 优先消费该 AST；只有不经过 Final Message 边界的独立 Markdown 场景才调用单卡 fallback parser。

### 12.2 Renderer 分发

`frontend/components/common/markdownRenderer.tsx` 在 code renderer 看到 `nl2agent-*` 时：

- 非 interactive mode：只显示生成中占位。
- interactive mode：调用 `tryRenderNl2AgentCard()`。

`frontend/components/nl2agent/index.tsx::tryRenderNl2AgentCard()` 复用 parser，然后分发到：

- `RequirementsSummaryCard`
- `ModelSelectionCard`
- `LocalResourcesCard`
- `OnlineRecommendationGroup` + `WebMcpCard`
- `OnlineRecommendationGroup` + `WebSkillCard`
- `AgentIdentityCard`
- `FinalizeCard`

`OnlineRecommendationGroup` 负责一次汇总 Card 中多个 MCP/Skill item 的共同外壳和批次注册。

### 12.3 流式与最终消息

`chatStreamMain.tsx` 和 `taskWindow.tsx` 把流式/Task Window Renderer 设为 placeholder。只有 `chatStreamFinalMessage.tsx` 在 `message.isComplete`、非 streaming 时传 interactive。

即使流式片段临时构成合法 JSON，也不会挂载 Card 或写 Redis。

---

## 13. Card Delivery 调用链

### 13.1 Frontend 判定

`ChatStreamFinalMessageInner` 保存 `sawActiveStreamRef`。回执只在以下条件同时满足时发生：

- Workflow Provider active；
- 非 readOnly；
- 是最新消息；
- 已观察到当前 active stream，或显式启用 recovery；
- 消息 complete 且非 streaming；
- 有正整数 Draft ID；
- 有数据库数字 `message.message_id`。

Requirements/Local/MCP/Skill 由 Card 注册成功后的 `onNl2AgentCardRegistered` 回调提交 `rendered`。其余 Card 在 final-message effect 中立即提交。

### 13.2 Backend 验证

```text
POST /session/{draft}/card-delivery
  → nl2agent_app.report_card_delivery_api
    → nl2agent_service.report_card_delivery
      → nl2agent_workflow_service.report_card_delivery
        ├─ get owned Draft
        ├─ load v2 State / conversation_id
        ├─ conversation_db.get_message(message_id)
        ├─ validate role == assistant and status == completed
        ├─ conversation_db.get_latest_assistant_message_id()
        ├─ evaluate current expected Card
        └─ session_catalog.record_card_delivery() CAS
```

如果同一回执已存，Service 在阶段已经推进后仍允许返回幂等结果；其他历史消息或不符合当前阶段的 Card 返回 `Nl2AgentStaleCardError`。

### 13.3 缺失 Card 检测

Final-message effect 先验证实际 Card，然后调用 `getNl2AgentSessionState()` 取得 `expected_card_types`。如果当前阶段期望某 Card 而完整消息未发出，则生成 `missing_card` failure。

其他 failure 为 truncated fence、invalid JSON 或 invalid schema。双卡同轮时 validator 能定位具体失败类型，成功的那一类可先注册和回执，缺失类在下一轮重试。

### 13.4 Retry

Backend `record_card_delivery()` 对同类型连续失败计数；failed 不动业务状态。Service 返回固定 `NL2AGENT_CARD_RETRY_INJECTION_TEXT`。Frontend：

- retry count 1、2：`continueWithText()` 自动发隐藏消息；
- 第 3 次起：保存 manual retry text，显示重新生成按钮；
- receipt API 失败：`failCardDelivery()`，显示重试回执；不触发模型。

`useNl2AgentCardLifecycle()` 和 Provider 内的 scoped `Map` 保证 claim → API → complete/fail 顺序。`scopeKey` 变化时清空 Map，不存在跨会话模块级 processed set。

---

## 14. 需求摘要和确认

### 14.1 注册

`RequirementsSummaryCard` 挂载后通过 lifecycle 执行：

```text
registerRequirementsSummary()
  → POST requirements/register
    → workflow_service.register_requirements_review()
      → register_requirements_summary() CAS
```

Repository 对五字段 NFKC/trim，使用排序 JSON 的 SHA-256 作为 fingerprint。响应含 `status`、规范化 summary、fingerprint 和 `is_current`。

历史 Card 重挂时，旧 fingerprint 不能覆盖当前摘要。`resolveRequirementsCardState()` 把它显示为 superseded，不阻塞当前输入，也不显示 Confirm。

### 14.2 按钮确认

Confirm 点击：

```text
confirmRequirementsSummary(fingerprint)
  → POST requirements/confirm
    → confirm_requirements_review()
      → confirm_requirements_summary() CAS
      → fixed chat_injection_text
```

成功后 Card 显示 confirmed、刷新 State，并调用 `continueWithText()`。组件重新挂载看到已 confirmed 不会再次续跑。

---

## 15. 模型选择

`ModelSelectionCard` 首先调用 `getAvailablePlatformLlms()`，底层复用 `/model/llm_list`。它在客户端筛选 available，显示 primary 和有序 fallback。

保存链路：

```text
PUT /session/{draft}/models
  → nl2agent_service.select_models()
    ├─ _get_owned_draft()
    ├─ assert_requirements_confirmed()
    ├─ _validate_available_llm_ids()
    ├─ update Agent business_logic_model_id/model_ids
    └─ set_model_selection_confirmed() CAS
```

`_validate_available_llm_ids()` 区分不存在、非 LLM、不可用、跨 tenant/名称缺失、重复和超过五个。成功响应包含固定续跑文本，Card 自动进入下一轮。

State API 和 Finalization 使用 `_resolve_model_summaries()` 再解析 `display_name/model_name` 与 role，不相信 Card 中的 label。

---

## 16. 本地 Apply All 的事务路径

```text
POST apply-local-resources
  → nl2agent_service.apply_local_resources_batch()
    → nl2agent_resource_service.apply_local_resources()
      ├─ validate owned Draft
      ├─ load batch and selected subset
      ├─ query all Tool / Skill candidates
      ├─ open one SQLAlchemy transaction
      │   ├─ tool_db.create_or_update_tool_by_tool_info(db_session=session)
      │   └─ skill_db.create_or_update_skill_by_skill_info(db_session=session)
      ├─ commit all instances
      └─ resolve_recommendation_batch(status="applied") via Redis CAS
```

Tool/Skill DB helpers因本功能增加可选 caller-owned Session。传入时不自行 commit，任一异常使整个 Apply 回滚。

Redis 在数据库之后更新。若 Redis 失败，API 返回失败且没有续跑文本；重试会 upsert 相同实例，再将批次完成。Skip 直接通过 `resolve_recommendation_batch(status="skipped")` 解决批次。

---

## 17. MCP 安装 Saga 代码路径

### 17.1 Facade 和依赖

```text
POST mcp/install
  → nl2agent_service.install_recommended_mcp()
    → _mcp_installation_dependencies()
    → nl2agent_mcp_service.install_recommended_mcp()
```

`McpInstallationDependencies` 注入 Catalog getter/mutator、workflow updater、MCP DB 查询、remote/container 创建、discovery、Tool upsert、锁和容器删除函数。

### 17.2 Trusted recommendation

`_resolve_recommendation()` 只遍历当前 tenant/draft 的 `registry_mcps + community_mcps`。找到 recommendation 后再次调用 SDK `normalize_mcp_candidate()`，再按 `option_id` 选择。请求不能直接提供 server URL、command 或 package。

`installation_key()` 对 Draft、recommendation、option 做 SHA-256。Repository 使用该 key 获取分布式锁；DB 使用 `registry_json` 内相同 key 查找已创建记录。

### 17.3 `_perform_recommended_mcp_install()`

核心步骤：

1. workflow → installing。
2. `_validate_configuration()` 遍历 option fields，只接受 `config_values.fields`。
3. 若已有同 installation key MCP，直接进入 discovery/resume。
4. remote 走 `_install_remote()`：解析 URL variables、header 和 token，拒绝未替换 `{...}`。
5. container 走 `_install_container()`：解析 port、config JSON、env 或 package config。
6. `_build_package_config()` 将 npm/npx 映射为 npx，将 pypi/uvx 映射为 uvx，并保留声明的参数。
7. `_discover_and_complete()` 做健康检查/工具发现，调用 `upsert_discovered_mcp_tools()`。
8. workflow → connected，记录 mcp_id 和 discovered Tool IDs。
9. Catalog CAS 删除该 recommendation。

`backend/services/remote_mcp_service.py::add_mcp_service()` 和 `add_container_mcp_service()` 为此改为返回创建后的稳定 `mcp_id`，不再按名称反查。

### 17.4 容器补偿

Container 创建已经发生、但 MCP 数据库持久化失败时，`_install_container()` 捕获异常并调用删除/停止容器依赖。发现失败发生在 MCP 已持久化之后，因此不删除 MCP，而把 workflow 标为 failed 且保留 mcp_id。

### 17.5 Binding

```text
POST mcp/{mcp_id}/bind-tools
  → nl2agent_mcp_service.bind_mcp_tools()
    ├─ find workflow by mcp_id
    ├─ require connected
    ├─ validate selected IDs ⊆ discovered IDs
    ├─ validate Tool tenant/source=mcp/usage provenance
    ├─ create ToolInstance(s)
    └─ workflow → tools_bound + bound ids
```

Skip endpoint只允许 connected workflow，设置 `binding_skipped`。online 完成时 `assert_mcp_workflows_resolved()` 会拒绝 installing 和 connected。

---

## 18. Online 批次和统一完成栏

MCP/Skill 汇总 Card 注册时调用同一个 endpoint，request 中区分 `resource_type` 和稳定 item keys。

```text
register_online_resource_recommendations()
  → register_online_recommendation_batch() CAS
  → if new batch: online_configuration_confirmed = false
```

`frontend/components/nl2agent/OnlineConfigurationBar.tsx` 在挂载及 `workflow.stateVersion` 变化时读取 Session State，`getOnlineConfigurationBlockers()` 检查：

- 是否有 MCP batch；
- 是否有 Skill batch；
- unresolved MCP count 是否为 0；
- State load 是否成功；
- 当前是否有单项 Card action。

满足后点击：

```text
POST online-configuration/complete
  → complete_online_configuration() CAS
    ├─ require both resource types, empty batches valid
    ├─ require resolved MCP workflows
    ├─ mark batches completed
    └─ online_configuration_confirmed = true
```

成功返回续跑文本。单项 MCP/Skill action不返回或不消费全局续跑，避免每安装一个资源就触发一轮模型。

---

## 19. 身份保存和内部名

`AgentIdentityCard` 使用模型 Card payload 的 display name 作为建议，但加载 Session State 判断是否已保存。用户可在保存前编辑。

```text
PUT identity
  → workflow_service.save_agent_identity()
    ├─ validate owned Draft
    ├─ update Draft display_name only
    ├─ confirm_agent_identity() CAS
    └─ _generate_internal_agent_name() for preview
```

`_generate_internal_agent_name()` 位于 facade。它用 NFKD/ASCII、snake_case、regex 和长度限制生成候选。`search_agent_id_by_agent_name()` 的“可用”契约是抛出精确 `ValueError("agent not found")`；helper 只捕获这一种预期 not-found，数据库连接等其他异常继续传播。

真正 Finalization 时再次调用同一 helper 并把内部名写入 Draft。

---

## 20. Session State 投影

```text
GET /session/{draft}/state
  → workflow_service.get_session_state()
    ├─ get owned Draft
    ├─ get strict v2 State
    ├─ evaluate_workflow()
    ├─ resolve model summaries
    ├─ search enabled ToolInstance / SkillInstance
    ├─ resolve resource names and origins
    ├─ enrich MCP workflows with discovered Tool names
    └─ build invalid_references
```

响应既保留兼容 ID 字段，又增加显示字段：

- models：primary/fallback、display name、valid；
- tools：name、source、origin；
- skills：name、source、origin；
- invalid_references；
- schema/revision/current stage/expected cards/allowed actions；
- requirements/local/online/MCP/identity 状态。

解析单个失效引用不会让整个 State API 退化为加载失败；有效部分照常返回，Frontend 展示错误并禁用 Publish。

`_resolve_resource_summaries()` 对 Skill 使用 tenant-scoped 批量查询，避免 N+1 和跨 tenant 读取。

---

## 21. Final Review 与 Publication

### 21.1 Frontend

`FinalizeCard.tsx` 将两类数据合并：

- proposal Card：business description、Prompt、greeting、examples、runtime options；
- Session State：identity、模型、Local/Online resources、invalid references。

`groupFinalReviewResources()` 按 Backend `origin` 分组，`NameList` 使每个名称独立一行。`canPublishFinalReview()` 检查 identity confirmed、三个 proposal 必填项和 invalid references；加载失败或不完整时禁用按钮。

### 21.2 Request 类型

`backend/consts/model.py::Nl2AgentFinalizeRequest` 使用 `extra="forbid"`。Frontend `Nl2AgentFinalizePayload` 从 generated OpenAPI schema派生，并排除客户端不应提交的 `agent_id`。

### 21.3 Backend

```text
POST finalize
  → nl2agent_service.finalize_agent()
    → nl2agent_publication_service.publish_agent()
      ├─ owned Draft
      ├─ persisted primary/fallback model validation
      ├─ requirements confirmed
      ├─ local review complete
      ├─ both online batches + global complete
      ├─ all installed MCP resolved
      ├─ identity confirmed
      ├─ proposal required fields
      ├─ enabled Tool/Skill reference resolution
      ├─ reject invalid references
      ├─ generate internal name from persisted display name
      └─ update Draft once with final fields
```

所有门禁和引用解析在 Draft update 之前完成。LLM proposal 无法覆盖身份、模型、绑定或配置。成功返回当前 Draft 的 persisted model/tool/skill IDs 和 `status="draft_ready"`。

---

## 22. 自动续跑链路

### 22.1 Backend 文本

facade 定义两个固定模板：

- `NL2AGENT_AUTO_CONTINUE_INJECTION_TEXT`
- `NL2AGENT_CARD_RETRY_INJECTION_TEXT`

文本不拼接用户输入、资源 ID 或下一阶段指令，只要求重新读取 Current Session 自然继续。

### 22.2 Frontend 发送

`Nl2AgentWorkflowContext.continueWithText()`：

1. 验证 active conversation/draft scope 未变化。
2. 防止并发 continuation。
3. 把注入文本作为普通 user message 交给 Chat 的现有 send handler。
4. `/agent/run` 仍携带同一个 Draft ID。
5. 失败保留文本，`Nl2AgentContinuationError` 提供 retry。

`frontend/lib/chat/nl2agentContinuation.ts::isNl2AgentAutoContinueText()` 识别两个前缀。`chatInterface.tsx` 在渲染和分享选择中隐藏它们，但数据库历史和 message index 保留。

---

## 23. API、Schema 与生成代码

### 23.1 Backend Request Models

`backend/consts/model.py` 新增：

- `Nl2AgentApplyLocalResourcesRequest`
- `Nl2AgentRecommendationBatchRequest`
- `Nl2AgentRecommendationSkipRequest`
- `Nl2AgentOnlineRecommendationBatchRequest`
- `Nl2AgentRequirementsSummaryRequest`
- `Nl2AgentRequirementsConfirmRequest`
- `Nl2AgentCardDeliveryRequest`
- `Nl2AgentModelSelectionRequest`
- `Nl2AgentIdentityRequest`
- `Nl2AgentMcpInstallRequest`
- `Nl2AgentMcpBindToolsRequest`
- `Nl2AgentInstallWebSkillRequest`
- `Nl2AgentFinalizeRequest`

这些 model 的长度、数量、枚举和 extra 行为构成 HTTP 第一层校验；业务门禁仍在 Service。

### 23.2 Error Classes

`backend/consts/exceptions.py` 与 error code/message 文件增加五个领域错误。App 的 `_session_http_error()` 透传 `AppException` 并保留 cause/log context。

注意：`start_session_api`、`apply_local_resources_api` 和 `install_web_skill_api` 的部分分支仍沿用直接 HTTP 500 映射，阅读调用栈时不要假设所有 endpoint 已完全统一。

### 23.3 OpenAPI 生成

`backend/scripts/export_nl2agent_openapi.py` 从 FastAPI schema 中选出 `/nl2agent` paths，并递归收集引用组件，写入 `contracts/nl2agent-openapi.json`。

`frontend/scripts/sync-nl2agent-contracts.mjs`：

1. 复制 Card Schema。
2. 调用 Backend 导出脚本。
3. 运行 `openapi-typescript`。
4. Prettier 生成文件。
5. `--check` 模式用临时输出比对漂移。

`frontend/package.json` 增加 `test`、`contracts:generate`、`contracts:check`，并把 contract/test 放进 `check-all`。

---

## 24. 既有模块为 NL2AGENT 做的扩展

### 24.1 Database helpers

- `agent_db.create_agent(..., db_session=None)`：支持 Session Start 共享事务。
- `conversation_db.create_conversation(..., db_session=None)`：同上。
- `conversation_db.get_message()`、`get_latest_assistant_message_id()`：Card Delivery 验证。
- `tool_db.create_or_update_tool_by_tool_info(..., db_session=None)`：本地 Apply 共享事务。
- `skill_db.create_or_update_skill_by_skill_info(..., db_session=None)`：同上。
- `skill_db` 增加 tenant-scoped Skill 批量/全局查询辅助：Catalog 优先级与最终名称解析。
- `remote_mcp_db` 增加按 tenant + ID/installation provenance 读取能力。
- `tool_db.upsert_discovered_mcp_tools()`：MCP discovery 稳定 upsert。

### 24.2 Agent list

`backend/services/agent_service.py` 默认过滤 `name == "nl2agent"` 和 `draft_*`；`backend/apps/agent_app.py` 增加显式 `include_internal` 查询开关。内部 Runner 和 Draft 不污染普通 Agent 列表。

### 24.3 MCP UI 基础设施

`AddMcpServiceModal.tsx` 与 local section 的接口适配创建 API 返回 `mcp_id`。它们并非 NL2AGENT Card 主流程，但为“创建后直接获得稳定 ID”统一了既有 MCP UI 调用。

### 24.4 Frontend server

`frontend/server.js` 的调整配合生成/运行环境加载，不引入 NL2AGENT 业务状态。

---

## 25. 测试代码如何对应实现

### 25.1 Backend

- `test/backend/agents/test_nl2agent_session_catalog.py`：v2 schema、CAS、revision、需求、批次、MCP、Card Delivery repository。
- `test/backend/services/test_nl2agent_service.py`：Session、模型、本地 Apply、MCP saga、workflow、identity、state、finalization 的主体用例。
- `test/backend/apps/test_nl2agent_app_errors.py`：领域错误到 HTTP。
- `test/backend/agents/test_create_agent_info.py`：Current Session、Prompt 和 per-tool Catalog 注入。
- database/MCP/Skill 对应测试：共享 Session、返回 ID、official Skill metadata 和批量查询。
- `test/backend/utils/test_prompt_template_utils.py`：双语 YAML、状态文本、两个隐藏前缀、三个 callable。

### 25.2 SDK

- `test/sdk/core/tools/test_nl2agent_search_tools.py`：中英文 token、OR fuzzy、阈值、去重、最大 5、稳定 batch、MCP option、Skill status 和无缓存新实例。
- `test/sdk/core/agents/test_nexent_agent.py`：三个 class dispatch、独立实例和未知旧 tool 拒绝。
- `test/sdk/core/agents/test_run_agent.py`：Draft ID 传播的回归点。

### 25.3 Frontend

- `cardValidation.vitest.test.ts`：Ajv AST、ID fallback/mismatch、重复/截断。
- `cardLifecycle.vitest.test.tsx`：busy、blocker、action、continuation、失败 retry。
- `nl2agentCards.test.tsx`：七类 Card、模型状态、online blocker、MCP 字段、Finalize 名称分组和隐藏文本等。

Vitest 配置为 jsdom，setup 引入 jest-dom；React Testing Library 验证真实 mount/effect，而不是只测纯函数。

### 25.4 Contract

`test/contracts/test_nl2agent_card_contract.py` 让 Prompt 示例和搜索结果都经过 canonical schema，防止 Prompt、SDK 与 Frontend 各自演化出不同 JSON。

---

## 26. 排障路径

### 26.1 Session 无法启动

按顺序检查：

1. Config Service 是否 seed `nl2agent` Runner。
2. `NL2AGENT_BUILTIN_TOOL_DEFINITIONS` 是否只有且包含三个 class name。
3. Catalog provider 日志是否返回 503，而不是合法空数组。
4. Draft/Conversation 是否在同一事务创建。
5. Redis 是否同时存在 State 与 Catalog Key。

不要在 Runtime 增加 lazy seed；当前职责明确属于 Config Service。

### 26.2 Agent 不按阶段执行

检查：

1. `/state` 的 `current_stage`、`expected_card_types`、`allowed_actions`。
2. `/agent/run` 是否携带正确 Draft ID。
3. Runner 是否确为内部 `nl2agent`。
4. `create_agent_info.py` 注入的 revision 和 Current Session。
5. YAML 是否加载对应语言。
6. 是否存在 Fresh Observation 尚未渲染。

不要从聊天文案猜阶段；Evaluator summary 才是入口。

### 26.3 搜索返回 Catalog 不可用

检查 tenant/draft 的 Catalog Key，而不是 SDK 进程内变量。SDK 没有 Redis 连接和搜索 cache。State 存在但 Catalog 缺失是初始化不完整，应该报错，不应返回空推荐。

### 26.4 Card 被截断或不显示

检查：

1. assistant message 是否 complete 且有数据库 `message_id`。
2. fence 是否闭合，tag 是否为七类 Card tag。
3. Ajv failure reason。
4. trusted Draft ID 是否与 payload/nested IDs 冲突。
5. Card 是否是最新 assistant message。
6. register API 是否成功。
7. `/card-delivery` 是否 stale、workflow conflict 或 receipt API error。

failed receipt 不会删除业务状态。若是 register API 失败，应重试注册；若是 output failure，才使用 Card retry。

### 26.5 MCP 重复或卡住

检查：

1. installation key 是否相同。
2. Redis lock 是否还在 5 分钟 TTL 内。
3. DB MCP `registry_json.nl2agent_installation_key`。
4. workflow 是 installing、failed 还是 connected。
5. failed 是否已有 mcp_id；有则 Retry 应从 discovery 恢复。
6. connected 是否尚未 bind/skip，导致 online 完成按钮禁用。

不要按 MCP 名称做恢复判断。

### 26.6 Final Review 出现失效引用

`invalid_references` 是 Backend 对持久化引用的实时解析结果。根据其中类型和 ID 检查：

- 模型是否被删除、改为非 LLM 或不可用；
- Tool/Skill Catalog 行是否删除；
- ToolInstance/SkillInstance 是否仍 enabled；
- tenant 查询是否正确。

Frontend 不应以 proposal 中的名称覆盖错误。

---

## 27. 当前代码阅读时要注意的实现差异

1. Backend 已有六个专用 Service，但 facade 仍较大；遇到入口先从 facade 找依赖装配，再跳专用 Service。
2. State 有 `revision`，Catalog CAS 没有 revision；并发问题排查方式不同。
3. MCP 搜索当前只实际评分 name 和 description；不要因为共享 scorer 支持 tags 就误判 MCP tags 已接入。
4. official Skill 的持久化 source 若为中文“官方”，当前最终分组的精确 `official` 判断可能把它放到 local。
5. Model Card 客户端 available 过滤不是安全边界；Backend 才是最终校验。
6. Card Schema 的 `agent_id` 可选是有意支持 trusted Conversation fallback，不代表任意 Conversation 可以猜 Draft。
7. Request、response 和 Session State 类型都来自生成 OpenAPI；业务层只保留必要的窄化别名，不应再手写重复响应接口。
8. 部分 Card 文案仍硬编码英文；阅读 i18n 文件时不要假设所有 label 都已迁移。
9. Finalize 成功状态当前叫 `draft_ready`；代码没有把用户操作描述成自动发布后台任务。
10. online Skill 的“Installed”同时表示 tenant Skill 已解析并绑定到 Draft；绑定失败时 Card 保持可重试。
11. Final Message 只解析一次完整 Card AST；独立 Markdown 渲染仍保留单卡 fallback parser。
12. `Nl2AgentContext` 是实例级而非全局级，但没有通过 frozen/deep copy 强制不可变；后续新增工具逻辑时必须避免就地修改注入 Catalog。

---

## 28. 变更文件索引

### 28.1 Backend 新增

- `backend/agents/default_agents/nl2agent.json`
- `backend/agents/nl2agent_session_catalog.py`
- `backend/agents/nl2agent_workflow.py`
- `backend/apps/nl2agent_app.py`
- `backend/prompts/nl2agent_system_prompt_en.yaml`
- `backend/prompts/nl2agent_system_prompt_zh.yaml`
- `backend/scripts/export_nl2agent_openapi.py`
- `backend/services/nl2agent_catalog_service.py`
- `backend/services/nl2agent_mcp_service.py`
- `backend/services/nl2agent_publication_service.py`
- `backend/services/nl2agent_resource_service.py`
- `backend/services/nl2agent_service.py`
- `backend/services/nl2agent_session_service.py`
- `backend/services/nl2agent_workflow_service.py`

### 28.2 Backend 修改

- Agent runtime：`create_agent_info.py`、`agent_service.py`、`agent_app.py`
- Service startup：`config_app.py`、`runtime_app.py`
- Contracts/errors：`consts/model.py`、`error_code.py`、`error_message.py`、`exceptions.py`
- Database：`agent_db.py`、`conversation_db.py`、`remote_mcp_db.py`、`skill_db.py`、`tool_db.py`
- Existing services：`prompt_service.py`、`remote_mcp_service.py`、`skill_service.py`
- Prompt loader：`prompt_template_utils.py`
- Dependencies：`backend/pyproject.toml`

### 28.3 SDK

- 新目录：`sdk/nexent/core/tools/nl2agent/` 下 `__init__.py`、`_context.py` 和三个 search tool。
- 修改：`sdk/nexent/core/agents/nexent_agent.py`、Tool package export、`sdk/pyproject.toml`。

### 28.4 Frontend

- 入口和 Chat：AgentManage、AgentSelectorHeader、chatInterface、ChatStreamMain、FinalMessage、TaskWindow、MarkdownRenderer。
- Card：`frontend/components/nl2agent/` 下九个组件、parser、renderer、workflow context 和 lifecycle hook。
- Chat helpers：`nl2agentContinuation.ts`、`nl2agentDraftContext.ts`。
- API：`nl2agentService.ts`、`api.ts`、Conversation service、chat types。
- Contract：generated schema/API types 和同步脚本。
- Test runtime：Vitest config/setup、package scripts/dependencies。
- i18n：中英文 common JSON。
- MCP adjacent UI：AddMcpServiceModal 与 local section。

### 28.5 Contract、测试和文档

- Canonical artifacts：`contracts/nl2agent-card.schema.json`、`contracts/nl2agent-openapi.json`。
- Backend/SDK tests：State、Service、App errors、Database、Prompt、Agent construction、Search tools。
- Frontend tests：Card validation、Lifecycle、Card behavior。
- 文档及资产：设计、代码走读、坏味道审查、gap merge plan 和三个 SVG。

该索引覆盖相对基线的全部变更类别；生成文件和测试不是附属遗漏，而是当前 Card/API Contract 可复现性的一部分。
