# NL2AGENT 代码坏味道审查与修复闭环

> 原始只读审计日期：2026-07-16
>
> 修复复核日期：2026-07-16
>
> 当前状态：原始审计的 15 项发现均已闭环；本文不绑定易失效的绝对行号或本机路径。

## 1. 复核结论

原始审计确认了 3 个真实生产路径故障、4 个高风险一致性问题和 8 个协议/可维护性问题。修复按可独立验证的阶段完成，每个阶段均在验证通过后单独提交，未推送。

修复遵循以下不变量：

- 用户可见的合法交互流程、按钮语义和自动续跑行为保持不变。
- 数据库负责 Draft、模型、资源绑定和最终配置；Redis 负责工作流投影、Catalog、批次、安装状态和回执。
- 所有副作用仍由用户操作 Card 触发，模型不能自行安装、绑定、跳过或发布。
- Card JSON 先通过 canonical schema 与 trusted Draft ID 校验，再进入强类型渲染。
- 新测试直接覆盖真实同步/异步签名、错误类别、分页、事务顺序和渲染数据边界，不再用错误类型的 Mock 固化错误行为。

## 2. 原始发现逐项闭环

### P0：阻断真实运行

1. 启动会话漏掉 `await`

- 状态：已修复。
- 修复：Catalog 依赖显式声明为异步返回值，`list_all_tools()` 在消费前等待完成；测试 fixture 改用 `AsyncMock` 并断言 await 参数。
- 提交：`3112a80f` `🐛 Bugfix: Align NL2AGENT async dependencies`。

2. Community MCP Catalog 漏掉 `await`

- 状态：已修复。
- 修复：Community provider 使用异步契约并等待结果；测试覆盖真实异步返回和 Catalog 内容。
- 提交：`3112a80f`。

3. MCP 重试路径错误地等待同步数据库函数

- 状态：已修复。
- 修复：`update_mcp_service()` 依赖恢复为同步签名并同步调用；测试使用 `MagicMock`，覆盖已有 MCP 记录的重试路径。
- 提交：`3112a80f`。

### P1：高风险功能与一致性问题

4. `chat`/`llm` 模型类型规范不一致

- 状态：已修复。
- 修复：seed、模型选择和最终发布共同使用 `is_llm_model_type()`；旧 `chat` 与规范化 `llm` 采用同一准入规则。
- 提交：`2652ee22` `🐛 Bugfix: Validate NL2AGENT model configuration`。

5. 本地资源推荐先写 Redis、后验证数据库

- 状态：已修复。
- 修复：注册批次前先批量查询并验证 Tool/Skill；验证成功后才推进 Redis 工作流。Skill 查询由逐项读取改为 tenant-scoped 批量查询。
- 提交：`8c6945ee` `🐛 Bugfix: Preserve NL2AGENT workflow consistency`。

6. 发布绕过模型输出 token 上限

- 状态：已修复。
- 修复：最终发布重新读取并验证主模型记录，在写 Draft 前检查 `requested_output_tokens <= max_output_tokens`；缺失或不可用模型同样阻断发布。
- 提交：`2652ee22`。

7. Verification 配置协议漂移

- 状态：已修复。
- 修复：Card Schema、双语 Prompt、Pydantic request、SDK `AgentVerificationConfig` 和 Final Review UI 对齐真实字段；删除无效 `mode`，Pydantic 禁止额外字段，最终审核展示 verification 决策。
- 提交：`de2ebfb7` `🐛 Bugfix: Align NL2AGENT verification contract`。

### P2：协议、状态机及可维护性问题

8. Card Schema、HTTP 模型和前端类型存在三份真相

- 状态：已闭环为可自动验证的契约链。
- 修复：17 个 endpoint 全部声明成功 `response_model`；OpenAPI 和 TypeScript 由脚本生成，导出器固定读取仓库内 SDK 源码而不受已安装版本漂移影响；前端 service 使用生成的 request/response/Session State 类型；Card 限制与 HTTP Pydantic 限制对齐。
- 防回归：contract test 比较 requirements、batch ID、final review 的 min/max、数量和 `extra="forbid"` 约束，并验证每个 endpoint 的 200 response 都引用具名 NL2AGENT schema。
- 提交：`e24ca715`、`ecb39068`。

9. 外部 MCP 只搜索前 30 条快照，单源失败阻断 Session

- 状态：已修复。
- 修复：Registry 与 Community 均以 100 条为页大小沿 cursor 拉取全部页，重复 cursor 安全终止；两者并发加载并分别 fail-soft，单个外部市场失败不再阻断本地资源 Session。
- 提交：`fe79ce9a` `🐛 Bugfix: Load complete NL2AGENT MCP catalogs`。

10. Card AST 依赖 `any`、强制断言和死回调

- 状态：已修复。
- 修复：删除 `WebMcpCard.onInstall` 从 Chat 到 Card 的整条无效透传和伪测试；建立按九种 fence language 判别的 payload 联合类型；Renderer 通过 switch 自然收窄，不再分散 `as WebMcpCardItem`、`as WebSkillCardItem` 或双重断言。
- 额外修复：拒绝单数 tag 携带列表 payload、复数 tag 携带单项 payload；`skill_name` 可稳定归一化为显示名和推荐 key。
- 提交：`bba15b41`、`7455ccd6`。

11. Requirements 意图识别会把否定句误判为修改

- 状态：已修复。
- 修复：在修改 marker 前识别中英文“无需修改/没有修改/no change”等否定表达；测试覆盖确认、否定、明确修改和同指纹恢复。
- 提交：`8c6945ee`。

12. Identity 保存存在数据库与 Redis 双写窗口

- 状态：已修复。
- 修复：数据库 display name 更新与 Redis identity 确认在同一个 caller-owned 数据库事务边界内执行；Redis 失败导致数据库回滚，测试断言事务退出异常和身份状态未确认。
- 提交：`8c6945ee`。

13. 错误语义被压扁为统一 409

- 状态：已修复。
- 修复：结构化区分请求/配置错误 `030206/400`、工作流冲突 `030202/409`、内部持久化失败 `030207/500`、外部安装/连接失败 `030208/502`；已有 Draft、stale Card、CAS 和 Catalog 错误原样透传。
- 防回归：App 边界测试断言 error code 与 HTTP status；Service 测试直接断言校验、内部操作和外部服务异常子类。
- 提交：`69299730` `🐛 Bugfix: Preserve NL2AGENT error semantics`。

14. 高圈复杂度与职责过载

- 状态：NL2AGENT 专用生产代码范围已清零 Ruff `C901`。
- 修复：Publication 拆分为模型、工作流、proposal、资源、更新构建与持久化职责；Skill 安装拆分 name/ID 路径；MCP/Tool 字段验证下沉；Session 启动拆出 builder 解析、seed 校验和补偿；权威 evaluator 拆分为事实投影与阶段决策。
- 说明：通用 Agent Runtime 的 `create_agent_info.py` 仍含历史复杂函数，但它不是 NL2AGENT feature 新增的专用职责，本轮未以跨 feature 重写扩大变更范围。
- 提交：`9ba91745` `♻️ Refactor: Reduce NL2AGENT service complexity`，以及最终文档/契约提交中的 evaluator 拆分。

15. 设计文档和代码走读已过期

- 状态：已修复。
- 修复：设计与走读不再绑定 commit/revision/文件计数；同步全量 MCP 分页、外部源故障隔离、online Skill 绑定、强类型共享 AST、生成响应类型和新错误码；删除已经解决的限制与重复文件索引。
- 本文改为按原始 15 项维护修复状态、提交和防回归证据，不再使用绝对本机路径和易漂移行号。

## 3. 分阶段提交记录

| 阶段 | Commit | 主题 |
|---:|---|---|
| 1 | `3112a80f` | 同步/异步依赖契约 |
| 2 | `2652ee22` | 模型类型与输出上限 |
| 3 | `de2ebfb7` | Verification 契约 |
| 4 | `8c6945ee` | 工作流与事务一致性 |
| 5 | `e24ca715` | Card/API 限制与失效字段 |
| 6 | `ecb39068` | API response model 与生成类型 |
| 7 | `fe79ce9a` | MCP 全量分页与故障隔离 |
| 8 | `bba15b41` | 删除死回调链 |
| 9 | `7455ccd6` | 强类型 Card payload AST |
| 10 | `9ba91745` | 服务圈复杂度治理 |
| 11 | `69299730` | 结构化错误语义 |
| 12 | 当前文档提交 | 契约门、文档同步与最终验证 |

## 4. 保留的架构约束

以下是明确的架构约束，不作为未修复坏味道：

- `nl2agent_service.py` 仍是依赖装配 facade，并保留 seed、模型投影与共享展示解析；副作用编排已位于六个专用 Service。
- Workflow State 公开 `revision`，Session Catalog 使用 WATCH/MULTI CAS 但不公开 revision。
- Canonical Card payload 允许省略 `agent_id`，以 trusted Conversation Draft ID 为准；payload ID 存在时必须完全一致。
- Frontend Final Review 的门禁用于即时 UX，Backend Publication 始终执行完整权威校验。
- official Skill 的 `resource_missing` 只过滤并告警，尚无自动修复入口。
- `Nl2AgentContext` 为实例级隔离，但不是 frozen/deep-copy 强制不可变。

## 5. 最终验证矩阵

最终验证全部使用 miniconda `nexent` 环境：

- 后端、SDK、Contract 定向测试：`204 passed`；
- 前端完整 Vitest：`56 passed`；
- 前端 TypeScript type-check：通过；
- OpenAPI/Card Contract 同步检查：通过；
- NL2AGENT 生产代码与定向测试 Ruff 标准规则：通过；
- NL2AGENT 专用生产代码 Ruff `C901`：无命中；
- NL2AGENT 相关 Prettier check：通过；
- `git diff --check`：通过；最终提交后工作区应为空。

ESLint 仍受仓库级旧式 Next/ESLint 配置限制：直接运行 ESLint 9 会要求 flat config。该限制不是 NL2AGENT feature 引入，不在本轮扩大为全仓工具链迁移。
