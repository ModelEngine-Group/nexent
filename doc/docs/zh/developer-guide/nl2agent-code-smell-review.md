结论：NL2Agent feature 存在明显坏味道，其中 3 个属于真实生产路径故障。当前测试全部通过，但关键依赖被错误类型的 Mock 掩盖，因此“测试通过”不能证明功能可用。

## P0：阻断真实运行

1. 启动会话时漏掉 `await`，真实 `/session/start` 会失败

- [`list_all_tools()`](/home/sil/nexent/backend/services/tool_configuration_service.py:492) 是异步函数。
- 它被注入 NL2Agent catalog 服务：[nl2agent_service.py](/home/sil/nexent/backend/services/nl2agent_service.py:248)。
- 依赖类型却被声明为同步 `Callable`：[nl2agent_catalog_service.py](/home/sil/nexent/backend/services/nl2agent_catalog_service.py:25)。
- 调用时没有 `await`，随后直接迭代 coroutine：[nl2agent_catalog_service.py](/home/sil/nexent/backend/services/nl2agent_catalog_service.py:94)。

实际结果是 `TypeError: 'coroutine' object is not iterable`，并被包装成 “NL2AGENT local Tool catalog unavailable”。因此真实 session start 会在写入会话前稳定失败。

测试未发现它，是因为 fixture 用同步 `MagicMock` 替代了真实异步函数：[test_nl2agent_service.py](/home/sil/nexent/test/backend/services/test_nl2agent_service.py:470)。

2. Community MCP catalog 同样漏掉 `await`

- 真实函数是异步的：[mcp_management_service.py](/home/sil/nexent/backend/services/mcp_management_service.py:33)。
- 调用处没有 `await`：[nl2agent_catalog_service.py](/home/sil/nexent/backend/services/nl2agent_catalog_service.py:147)。
- 由于 coroutine 不属于 `dict`，代码会静默把结果转成空列表。

即使修复第一个启动阻断，Community MCP 也永远不会进入可搜索目录，并伴随未等待 coroutine 警告。相应测试仍使用同步 `MagicMock`：[test_nl2agent_service.py](/home/sil/nexent/test/backend/services/test_nl2agent_service.py:485)。

3. MCP 重试路径错误地 `await` 同步数据库函数

- `update_mcp_service()` 是同步函数：[remote_mcp_service.py](/home/sil/nexent/backend/services/remote_mcp_service.py:510)。
- NL2Agent 依赖却被声明为返回 `Awaitable`：[nl2agent_mcp_service.py](/home/sil/nexent/backend/services/nl2agent_mcp_service.py:34)。
- 实际调用使用了 `await`：[nl2agent_mcp_service.py](/home/sil/nexent/backend/services/nl2agent_mcp_service.py:427)。

已有 remote MCP 记录的重试/恢复流程会先完成数据库更新，然后执行 `await None` 报错，最终工作流被标记为失败。测试使用 `AsyncMock`，再次把生产签名错误隐藏了：[test_nl2agent_service.py](/home/sil/nexent/test/backend/services/test_nl2agent_service.py:1523)。

这三个问题反映的是同一类系统性坏味道：依赖注入大量依赖 `Callable[..., Any]`，没有在类型层面约束同步/异步边界。

## P1：高风险功能与一致性问题

4. `chat`/`llm` 模型类型规范不一致

平台模型接口会把旧类型 `chat` 映射成前端看到的 `llm`：[model_management_service.py](/home/sil/nexent/backend/services/model_management_service.py:710)。

NL2Agent seed 又明确接受 `chat` 和 `llm`：[nl2agent_seed_service.py](/home/sil/nexent/backend/services/nl2agent_seed_service.py:106)，但最终模型选择只接受原始类型 `llm`：[nl2agent_service.py](/home/sil/nexent/backend/services/nl2agent_service.py:379)。

结果是：旧 `chat` 模型可以出现在可选列表中，却会在选择或发布时被拒绝。测试甚至分别固化了这两个互相冲突的行为：[test_nl2agent_service.py](/home/sil/nexent/test/backend/services/test_nl2agent_service.py:3325)。

5. 本地资源推荐存在 Redis 先提交、数据库后验证的问题

[`register_local_resource_recommendations()`](/home/sil/nexent/backend/services/nl2agent_resource_service.py:250) 先把推荐批次写入 Redis、推进工作流，之后才从数据库检查工具是否仍存在。

如果工具在搜索后被删除：

- Redis 已经进入 recommendation review 状态；
- API 返回失败；
- 前端仍保留 `registered=false`；
- Apply 和 Skip 均不可用：[LocalResourcesCard.tsx](/home/sil/nexent/frontend/components/nl2agent/LocalResourcesCard.tsx:444)。

允许重试，但每次都会遇到相同的数据库缺失，当前交互无法继续。这是典型的部分提交和验证顺序倒置。

6. NL2Agent 发布绕过模型输出 token 上限

正常 Agent 保存流程会检查 `requested_output_tokens` 是否超过模型能力：[agent_service.py](/home/sil/nexent/backend/services/agent_service.py:1506)。

NL2Agent publication 直接调用底层 `update_agent`：[nl2agent_service.py](/home/sil/nexent/backend/services/nl2agent_service.py:952)，只校验 token 至少为 1：[nl2agent_publication_service.py](/home/sil/nexent/backend/services/nl2agent_publication_service.py:129)。

因此 LLM 生成的超大值可以成功发布，但运行时容量解析器随后会拒绝它：[capacity_resolver.py](/home/sil/nexent/sdk/nexent/core/models/capacity_resolver.py:287)。这会产生“发布成功、所有运行失败”的 Agent。

7. Verification 配置协议已经漂移

Card Schema 和中英文提示词输出：

```json
{"enabled": false, "mode": "basic"}
```

证据：

- [nl2agent-card.schema.json](/home/sil/nexent/contracts/nl2agent-card.schema.json:226)
- [nl2agent_system_prompt_en.yaml](/home/sil/nexent/backend/prompts/nl2agent_system_prompt_en.yaml:87)
- [FinalizeCard.tsx](/home/sil/nexent/frontend/components/nl2agent/FinalizeCard.tsx:17)

但真实 `AgentVerificationConfig` 没有 `mode` 字段，而是 `strictness`、`fail_policy` 等：[agent_model.py](/home/sil/nexent/sdk/nexent/core/agents/agent_model.py:150)。

在 `nexent` 环境实测，Pydantic 会静默丢弃 `mode`。同时 FinalizeCard 没有展示 verification 配置，意味着提示词默认关闭验证，却没有让用户明确审阅该决定。

## P2：协议、状态机及可维护性坏味道

8. Card Schema、HTTP 模型和前端类型存在三份真相

例如 Card Schema 对 requirements、ID 数量、字符串长度和 `max_steps` 的限制，比后端请求模型宽松：

- [Card Schema](/home/sil/nexent/contracts/nl2agent-card.schema.json:10)
- [后端请求模型](/home/sil/nexent/backend/consts/model.py:458)
- [最终发布模型](/home/sil/nexent/backend/consts/model.py:555)

因此卡片可能通过 Ajv 验证并渲染，自动注册或发布时才收到 422。

NL2Agent endpoints 还普遍没有声明 `response_model`：[nl2agent_app.py](/home/sil/nexent/backend/apps/nl2agent_app.py:78)，导致生成的前端响应类型是 `unknown`，前端不得不在 [nl2agentService.ts](/home/sil/nexent/frontend/services/nl2agentService.ts:21) 手工维护重复接口。

9. 外部 MCP 搜索只是“前 30 条快照内搜索”

启动时 Registry 和 Community catalog 都固定 `limit=30`：[nl2agent_catalog_service.py](/home/sil/nexent/backend/services/nl2agent_catalog_service.py:129)。SDK 随后只在注入的快照中搜索，而没有调用服务端搜索能力。

因此第 31 条以后的 MCP 永远不可发现。并且任何一个外部 catalog 不可用都会让整个 session start 失败，即使用户只需要本地工具；这是较强的可用性耦合。

10. 前端所谓 typed card AST 仍大量依赖 `any` 和强制断言

核心 payload 类型仍是 `Record<string, any>`：[cardValidation.ts](/home/sil/nexent/frontend/components/nl2agent/cardValidation.ts:17)，renderer 根据 `language` 强制转换 payload：[index.tsx](/home/sil/nexent/frontend/components/nl2agent/index.tsx:244)。

`WebMcpCard.onInstall` 还形成了死回调链：

- Props 声明了回调：[WebMcpCard.tsx](/home/sil/nexent/frontend/components/nl2agent/WebMcpCard.tsx:19)
- 组件实现没有解构或调用它：[WebMcpCard.tsx](/home/sil/nexent/frontend/components/nl2agent/WebMcpCard.tsx:76)
- 测试只检查 React element 上的 prop 并手动调用，没有挂载验证真实行为：[nl2agentCards.test.tsx](/home/sil/nexent/frontend/components/nl2agent/__tests__/nl2agentCards.test.tsx:194)

11. Requirements 意图识别使用简单子串，否定句会误判

[`classify_requirements_intent()`](/home/sil/nexent/backend/agents/nl2agent_session_catalog.py:318) 使用 `marker in normalized_text` 判断修改意图。

例如：

- “No change, looks good”
- “无需修改，可以继续”

分别包含 `change` 和 `修改`，会被分类成修改请求，重新进入 collecting。如果重新生成的 summary 指纹没有变化，状态还可能无法回到 awaiting confirmation。

12. Identity 保存存在数据库与 Redis 双写不一致窗口

[`save_identity()`](/home/sil/nexent/backend/services/nl2agent_workflow_service.py:321) 先更新数据库 display name，再确认 Redis workflow，没有共享事务或补偿。

Redis 失败时，API 报错且工作流仍停留在 identity，但数据库名称已经改变。重试通常能恢复，不过这是清晰的部分提交窗口。

13. 错误语义被压扁

[`_session_http_error()`](/home/sil/nexent/backend/apps/nl2agent_app.py:62) 将大量历史 `AgentRunException` 统一映射成 workflow conflict 409。

配置无效、MCP 连接失败、数据库保存失败可能得到相同状态码和错误类别，削弱客户端重试判断与服务端可观测性。

14. 复杂度和文件体积已经偏高

NL2Agent 相关主要大文件：

- `test_nl2agent_service.py`：3423 行
- `create_agent_info.py`：1684 行
- `nl2agent_service.py`：1000 行
- `nl2agent_session_catalog.py`：932 行
- `nl2agent_mcp_service.py`：845 行

Ruff 标准规则全部通过，但启用 `C901` 后发现 7 个高复杂度函数，其中 `evaluate_workflow` 复杂度为 21，`publish_agent` 为 13，`start_session` 为 12。复杂度和宽松的 `Callable[..., Any]` 共同降低了签名错误被静态发现的可能。

15. 设计文档已经不再代表当前实现

[NL2Agent 设计文档](/home/sil/nexent/doc/docs/zh/developer-guide/nl2agent-design.md:3) 仍称旧 revision 为“当前实现”，当前分支已经领先 23 个提交。旧 smell review 还包含过期行号和本机 Windows 路径；walkthrough 中也存在已经被代码改变的行为描述。

## 已确认做得较好的部分

- Redis workflow/catalog 更新采用 CAS，并刷新 TTL。
- 搜索结果批次绑定服务端可信结果，客户端不能任意伪造资源 ID。
- MCP 安装锁带 owner token 和 heartbeat。
- Tool/MCP catalog 对敏感配置进行了脱敏。
- Card delivery 会验证服务器持久化的最新 assistant message，而不是直接信任客户端。
- 多数 select/apply/bind 路径已有数据库事务或补偿逻辑。
- 中英文 YAML 提示词结构基本一致，示例卡片通过当前 canonical schema。

## 只读验证结果

全部使用 miniconda 的 `nexent` 环境：

- 后端、SDK、contracts 定向测试：`181 passed`
- 前端 NL2Agent Vitest：`51 passed`
- 前端 TypeScript type-check：通过
- contracts check：通过
- NL2Agent Prettier check：通过
- Ruff 标准检查：通过
- Ruff `C901`：发现 7 个复杂度问题
- 定向 ESLint 未能启动：仓库使用旧式 Next/ESLint 配置，而直接调用 ESLint 9 要求 flat config；这是验证限制，不计为 NL2Agent 缺陷
- 最终 `git status --short` 无输出，工作区未产生任何修改

建议修复优先级：先处理三个同步/异步契约错误并用真实函数签名测试覆盖；随后统一模型类型和 publication 校验；再收敛 Card Schema、Pydantic 模型、OpenAPI 与前端生成类型。此次仅执行了只读验证，没有修改、提交或推送。
