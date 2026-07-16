结论：当前 `HEAD 4bf87621` 的 NL2AGENT 仍存在明显坏味道，其中若干已经属于可触发的安全性、状态一致性和可恢复性缺陷，而不只是代码风格问题。只读审计发现 4 项 P1、5 项 P2，以及若干维护性问题。

## P1：优先修复

### 1. 服务端没有建立可靠的“用户—会话—草稿”绑定

这是最严重的问题。

- 会话启动时明确使用 `user_id` 创建草稿和会话：[nl2agent_session_service.py:65](/home/sil/nexent/backend/services/nl2agent_session_service.py:65)。
- 后续所谓 `_get_owned_draft` 实际只检查 `agent_id`、租户和 `draft_` 名称前缀，不检查 `created_by`、用户组权限或 conversation：[nl2agent_service.py:296](/home/sil/nexent/backend/services/nl2agent_service.py:296)。
- 底层查询同样只按租户和 agent ID 查询：[agent_db.py:14](/home/sil/nexent/backend/database/agent_db.py:14)。
- 多个接口取得当前用户后直接丢弃，只向服务传 `tenant_id`，例如状态读取、需求确认：[nl2agent_app.py:381](/home/sil/nexent/backend/apps/nl2agent_app.py:381)、[nl2agent_app.py:415](/home/sil/nexent/backend/apps/nl2agent_app.py:415)。
- `/agent/run` 允许客户端独立提交 `conversation_id` 和 `draft_agent_id`：[model.py:312](/home/sil/nexent/backend/consts/model.py:312)。Redis 状态虽然保存了权威 `conversation_id`，[nl2agent_workflow.py:106](/home/sil/nexent/backend/agents/nl2agent_workflow.py:106)，运行时却只按传入的 draft 加载状态，没有比较 conversation：[create_agent_info.py:827](/home/sil/nexent/backend/agents/create_agent_info.py:827)。
- 更糟的是，在保存消息前，用户文本就可能按任意 `draft_agent_id` 修改需求状态：[agent_service.py:3040](/home/sil/nexent/backend/services/agent_service.py:3040)。

影响：

- 同租户用户只要猜到递增的草稿 ID，就可能读取、修改、绑定资源甚至发布别人的草稿。
- 合法用户也可能因陈旧映射把 conversation A 的消息写入 draft B。
- 目前前端防串话只能降低误操作，不能构成安全边界。

建议：所有 NL2AGENT 操作统一校验 `created_by`/编辑权限，并从服务端根据 `(tenant_id, user_id, conversation_id)` 解析唯一 draft；客户端提交的 `draft_agent_id` 只能作为一致性断言，不能作为权威来源。

### 2. 搜索工具不校验当前阶段，可导致前端永久阻塞

三个 SDK 搜索工具只检查“需求已确认”，不检查当前允许动作。例如本地搜索：[search_local_resources_tool.py:133](/home/sil/nexent/sdk/nexent/core/tools/nl2agent/search_local_resources_tool.py:133)，MCP 搜索：[search_web_mcps_tool.py:341](/home/sil/nexent/sdk/nexent/core/tools/nl2agent/search_web_mcps_tool.py:341)。

搜索结果随后直接写入可信批次，写入函数自身也不验证 stage：[nl2agent_session_catalog.py:680](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:680)。但真正注册卡片时，服务端又会按状态机拒绝错序动作：[nl2agent_session_catalog.py:270](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:270)。

系统提示词还规定“新鲜搜索 Observation 优先于当前状态并必须渲染”，放大了错序路径：[nl2agent_system_prompt_en.yaml:21](/home/sil/nexent/backend/prompts/nl2agent_system_prompt_en.yaml:21)。

前端注册失败后使用 `retainInputBlockOnError: true`：

- 本地卡：[LocalResourcesCard.tsx:101](/home/sil/nexent/frontend/components/nl2agent/LocalResourcesCard.tsx:101)
- 在线卡：[index.tsx:52](/home/sil/nexent/frontend/components/nl2agent/index.tsx:52)
- 生命周期确实保留 blocker：[useNl2AgentCardLifecycle.ts:81](/home/sil/nexent/frontend/components/nl2agent/useNl2AgentCardLifecycle.ts:81)

因此一旦 LLM 在错误阶段调用搜索工具，卡片会被渲染，但注册永久返回 workflow conflict；输入框保持阻塞，界面只提供永远不会成功的 Retry。

建议：搜索工具写入可信结果前执行服务端 `assert_workflow_action_allowed`；对确定不可重试的 409/状态冲突立即释放输入 blocker，并触发卡片失败恢复流程。

### 3. Apply/Skip 和 MCP Bind/Skip 存在 TOCTOU 并发竞争

Facade 先检查当前允许动作，再进入真正的数据库/Redis操作：[nl2agent_service.py:703](/home/sil/nexent/backend/services/nl2agent_service.py:703)。检查和修改不是同一个 CAS 事务。

本地资源路径：

- Apply 先提交数据库，再更新 Redis：[nl2agent_resource_service.py:200](/home/sil/nexent/backend/services/nl2agent_resource_service.py:200)、[nl2agent_resource_service.py:246](/home/sil/nexent/backend/services/nl2agent_resource_service.py:246)。
- Skip 直接更新 Redis：[nl2agent_resource_service.py:361](/home/sil/nexent/backend/services/nl2agent_resource_service.py:361)。
- `resolve_recommendation_batch` 不要求原状态必须为 `recommendations_ready`，允许 `applied ↔ skipped` 覆盖：[nl2agent_session_catalog.py:716](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:716)。

两个请求并发通过前置检查后，可能出现“数据库已绑定资源、Redis 最终显示 skipped”，或者相反。

MCP 的 bind/skip 也有相同竞争：两者独立做 action check，[nl2agent_service.py:649](/home/sil/nexent/backend/services/nl2agent_service.py:649)，而状态更新函数允许任意状态覆盖：[nl2agent_session_catalog.py:493](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:493)。

建议：CAS 更新必须同时断言预期 revision 和预期状态；使用明确的状态迁移表和幂等 operation ID。数据库与 Redis 跨存储操作需要 reservation/saga/outbox，而不是普通前置检查。

### 4. Builder seed 会静默留下不可用实例

函数文档声称“创建或修复 builder 并绑定内置工具”，但已有 builder 分支只修字段，然后直接返回，完全不检查工具绑定：[nl2agent_seed_service.py:210](/home/sil/nexent/backend/services/nl2agent_seed_service.py:210)。

新建 builder 时，每个工具绑定失败也只记录日志，最终仍然返回成功并输出“Seeded”日志：[nl2agent_seed_service.py:244](/home/sil/nexent/backend/services/nl2agent_seed_service.py:244)。

会话启动时的修复又捕获所有异常后继续创建会话：[nl2agent_session_service.py:149](/home/sil/nexent/backend/services/nl2agent_session_service.py:149)。

影响：数据库中存在 `nl2agent` agent，但搜索工具可能缺失；启动和会话创建看似成功，真正聊天时才失败。当前 seed 测试只覆盖新建成功路径：[test_nl2agent_seed_service.py:75](/home/sil/nexent/test/backend/services/test_nl2agent_seed_service.py:75)。

建议：每次 seed 都幂等 upsert 所有内置工具绑定；任一必需工具失败应使 seed/readiness 失败，并增加“已有 builder 缺失绑定”“部分绑定失败”的测试。

## P2：重要一致性与生命周期问题

### 5. MCP 绑定未验证“本次发现的工具集合”

绑定接口仅验证工具属于当前租户、来源为 MCP、`usage` 等于 MCP 名称：[nl2agent_mcp_service.py:767](/home/sil/nexent/backend/services/nl2agent_mcp_service.py:767)。

它没有：

- 要求 workflow 当前为 `connected`；
- 要求 `tool_ids ⊆ discovered_tool_ids`；
- 阻止已 `binding_skipped` 或 `tools_bound` 的 workflow 再次绑定。

相比之下 skip 路径至少检查了 `status == connected`：[nl2agent_mcp_service.py:841](/home/sil/nexent/backend/services/nl2agent_mcp_service.py:841)。

这允许直接 API 请求绑定同名 MCP 下、但并非本次 discovery 得到的工具，并加剧 bind/skip 并发问题。

### 6. Redis 24 小时 TTL 会分裂，且没有恢复/清理机制

workflow state 和 catalog 是两个独立 Redis key，共用 24 小时 TTL：[nl2agent_session_catalog.py:42](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:42)。

- 普通读取不会续期：[nl2agent_session_catalog.py:210](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:210)、[nl2agent_session_catalog.py:844](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:844)。
- 修改 state 只续 state：[nl2agent_session_catalog.py:228](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:228)。
- 修改 catalog 只续 catalog：[nl2agent_session_catalog.py:803](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:803)。

例如第 23 小时确认需求会把 state 延长到第 47 小时，但 catalog 仍在第 24 小时失效，活跃会话随后无法搜索。

此外：

- 前端 conversation→draft 映射只保存在 `localStorage`：[chatInterface.tsx:72](</home/sil/nexent/frontend/app/[locale]/chat/internal/chatInterface.tsx:72>)。
- 换浏览器、清空存储后无法从服务端恢复：[nl2agentDraftContext.ts:27](/home/sil/nexent/frontend/lib/chat/nl2agentDraftContext.ts:27)。
- Redis 删除函数仅用于初始化失败补偿：[nl2agent_session_catalog.py:896](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:896)。
- 没有 abandon API 或过期草稿清理任务；废弃 `draft_*` 会永久留在数据库，只是被列表隐藏：[agent_service.py:2379](/home/sil/nexent/backend/services/agent_service.py:2379)。

### 7. 身份保存仍有反向双写窗口

身份保存先在数据库事务内更新 Agent，然后修改 Redis：[nl2agent_workflow_service.py:327](/home/sil/nexent/backend/services/nl2agent_workflow_service.py:327)。

它覆盖了“Redis 失败时数据库回滚”，但未覆盖：

1. Redis `identity_confirmed=True` 成功；
2. `with get_db_session()` 退出时数据库 commit 失败；
3. Redis 没有补偿，仍显示身份已确认。

最终可能用旧数据库名称继续发布。现有测试只覆盖 Redis 在事务体内失败，没有覆盖事务退出/commit 失败。

### 8. Secret 字段命名兼容不一致，可能泄露默认凭据

本地 Tool 参数脱敏同时识别 `isSecret` 和 `is_secret`：[nl2agent_resource_service.py:31](/home/sil/nexent/backend/services/nl2agent_resource_service.py:31)。

但 Marketplace catalog 脱敏只识别 `isSecret`：[nl2agent_catalog_service.py:98](/home/sil/nexent/backend/services/nl2agent_catalog_service.py:98)，SDK MCP 字段规范化同样只识别 camelCase：[search_web_mcps_tool.py:45](/home/sil/nexent/sdk/nexent/core/tools/nl2agent/search_web_mcps_tool.py:45)。

如果上游返回 `is_secret: true` 且字段名未命中 token/password 正则，`value/default` 会进入 Redis，并随完整 catalog 注入工具 metadata：[create_agent_info.py:1082](/home/sil/nexent/backend/agents/create_agent_info.py:1082)。这是潜在凭据暴露路径。

### 9. Catalog 加载没有总量、页数或时间预算

Marketplace loader 使用 `while True` 拉取全部分页，只防重复 cursor，没有最大页数、最大条目数、字节数或总超时：[nl2agent_catalog_service.py:52](/home/sil/nexent/backend/services/nl2agent_catalog_service.py:52)。

随后完整 catalog：

- 每个会话单独复制到 Redis；
- 每次 Agent Run 都加载；
- 注入每个 NL2AGENT 搜索工具。

恶意或异常 provider 持续返回唯一 cursor 时，会导致会话启动长时间挂起或内存增长。即便 provider 正常，大租户也会有明显重复存储与反序列化成本。

## 条件性安全风险

远程 MCP URL 只验证 `http/https + netloc`：[nl2agent_mcp_service.py:345](/home/sil/nexent/backend/services/nl2agent_mcp_service.py:345)，然后后端直接发起健康检查连接：[remote_mcp_service.py:47](/home/sil/nexent/backend/services/remote_mcp_service.py:47)。

如果普通租户用户不应该访问服务端内网，这构成 SSRF/内网探测面，需要私网地址策略、DNS 重绑定防护或明确的网络 allowlist。若产品明确允许用户连接私有 MCP，则至少应把该能力视为高权限操作并审计。

## 较低优先级坏味道

- `get_session_state` 连续读取 Redis 两次，可能把 revision/resource state 与另一版本的 current stage 混合返回：[nl2agent_workflow_service.py:282](/home/sil/nexent/backend/services/nl2agent_workflow_service.py:282)。
- Facade 仍有 1016 行，并遗留不可达表达式：[nl2agent_service.py:1010](/home/sil/nexent/backend/services/nl2agent_service.py:1010)。
- 核心服务测试文件达到 3719 行，已经影响定位和职责边界。
- NL2AGENT 定向 Lint 仍发现生产代码两个 `any`：[FinalizeCard.tsx:174](/home/sil/nexent/frontend/components/nl2agent/FinalizeCard.tsx:174)。
- `localStorage` JSON 只捕获语法错误，不校验解析结果是否为对象；合法的 `"null"` 会让后续写映射抛异常。

## 只读验证结果

审计覆盖了 96 个包含 NL2AGENT 引用的文件，重点逐行检查了约 14K 行核心实现和 5K+ 行相关测试。工作区始终干净，没有修改任何文件。

- 前端 Vitest：`56 passed`
- TypeScript：`tsc --noEmit` 通过
- NL2AGENT Prettier：通过
- 后端独立可运行测试：`51 passed`
- Python NL2AGENT 文件 AST：19 个全部通过
- 定向前端 Lint：失败，2 个生产 `any`、1 个测试 `any`
- 其余后端测试收集被当前环境缺少 `smolagents` 阻断
- 契约检查被当前环境缺少 `mem0` 阻断
- `git status`、`git diff --check` 均为空

总体评价：现有实现的 Pydantic 状态模型、单 Redis key CAS、卡片 AST 校验、可信搜索批次和前端契约生成方向是好的；但“服务端权威身份绑定、跨存储事务、并发状态迁移、长期恢复”四个基础不变量还没有闭合。建议优先按 P1 的顺序处理，再补对应的并发、跨用户和 commit-failure 测试。
