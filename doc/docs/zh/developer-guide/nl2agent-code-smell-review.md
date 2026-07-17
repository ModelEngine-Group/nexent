# NL2AGENT 代码坏味道复核报告

复核日期：2026-07-17

复核分支：`dyx/nl2a`

复核范围：NL2AGENT backend、SDK、frontend、数据库迁移与相关测试

## 结论

原报告确认的 16 条问题中：

- 15 条已修复并通过针对性回归；
- 1 条 P3 结构性坏味道仅部分缓解，仍需继续拆分巨型 facade 与长参数函数；
- 原条件性卡片协议注入风险已修复；
- 未发现新的 P0、P1 或 P2 级安全/功能缺陷；
- 当前未再复现租户 Builder 启动失败、鉴权错误映射、草稿状态漂移、Redis 写依赖、陈旧缓存、无界 workflow、安装锁异常覆盖、snapshot 永久增长或 pytest collection 污染。

因此，NL2AGENT 当前没有已知的高、中严重度坏味道；唯一明确剩余项是低严重度的模块与参数规模问题。

## 原问题逐项复核

| 编号 | 原问题 | 状态 | 修复与验证证据 |
|---|---|---|---|
| 1 | 自定义租户无法启动 Agent Builder | 已修复 | session start 在租户缺少 Builder 时按当前 `tenant_id` 惰性 provision；数据库增加 active `nl2agent` 租户唯一部分索引，并发 loser 会重新查询并修复 winner。多租户真实调用与 seed 竞争测试通过。 |
| 2 | 浏览器草稿缓存成为权威状态 | 已修复 | 删除 NL2AGENT conversation→draft 的 `localStorage` 映射；发送前通过服务端 session discovery 重新验证，404 会清除过期 handoff；删除 conversation 会按 owner/tenant abandon 对应 session。 |
| 3 | 16 个 API 鉴权失败返回 500 | 已修复 | 所有 NL2AGENT endpoint 统一通过 `_current_user()` 映射 `UnauthorizedError` 为 401；真实 ASGI 鉴权回归通过。 |
| 4 | Active Session 不淘汰且入口可双击创建孤儿 | 已修复 | 前端两个 Builder 入口均增加 ref/state mutex；后端增加 active、abandoned、completed 三类留存策略，删除 conversation 时同步 abandon，清理采用有界批次与 `skip_locked`。 |
| 5 | Redis 是创建和修改路径硬依赖 | 已修复 | 初始 workflow 由数据库事务持久化；事务提交后才 best-effort 预热 Redis。workflow 修改只使用数据库 revision CAS，Redis 不可用不再阻止创建或改变已提交结果。 |
| 6 | 数据库提交后 Redis 最长保留 24 小时旧状态 | 已修复 | workflow 读取始终加载数据库权威 revision，再修复 disposable cache；测试覆盖 Redis 中 revision 0、数据库 revision 2 时必须返回并回写 revision 2。 |
| 7 | 本地 Catalog 无界加载且 Skill N+1 | 已修复 | Tool/Skill provider 查询边界统一限制为 2,000；Skill 使用专用轻量投影，只查询 ID、名称、描述、标签，不再逐条加载 tool relation。单查询与 limit 测试通过。 |
| 8 | 请求集合与 Workflow 无容量边界、整数不严格 | 已修复 | NL2AGENT 请求 ID 使用 strict positive integer，布尔值不再解析为 `1`；list/dict/string 增加长度上限。每次 workflow mutator 后重新执行完整 schema/capacity 校验，再允许 revision CAS。 |
| 9 | MCP/Skill 锁释放掩盖结果，Skill 无续约 | 已修复 | 两类 release 均被保护，失败只记录告警，不覆盖成功结果或原异常；MCP 使用 asyncio heartbeat，Skill 使用独立 daemon heartbeat 续租，丢失 ownership 时拒绝正常完成。 |
| 10 | Catalog Snapshot 没有 GC | 已修复 | abandoned 清理和 completed retention 均会释放 session 引用，并仅软删除无存活引用的候选 snapshot；内容哈希再次出现时使用 `ON CONFLICT DO UPDATE` 原子恢复 snapshot。 |
| 11 | 默认 Builder seed check-then-create 竞争 | 已修复 | ORM、增量迁移与 fresh init 均包含 `uq_nl2agent_builder_tenant_active`；迁移先软删除历史重复 Builder，再建唯一索引；并发创建失败方重新查询 winner。 |
| 12 | 生产模块暴露测试专用全局 API | 已修复 | 删除生产 `clear_session_cache()`/`clear_nl2agent_session_catalogs`；删除绕过阶段校验的公开 `record_trusted_search_batch()`。测试清理和搜索 proof seam 仅保留在测试代码或私有函数。 |
| 13 | 前端错误类型不统一 | 已修复 | NL2AGENT HTTP 失败统一抛出 `Nl2AgentRequestError`，保留 status、error code 与 details；并发 session start 使用单一 pending promise 合并。 |
| 14 | 模块和依赖对象继续膨胀 | 部分缓解，仍存在 | `PublicationDependencies` 已拆为 draft/workflow/model/resource/persistence，`McpInstallationDependencies` 已拆为 session/lock/provider/discovery；但 `nl2agent_session_catalog.py` 仍为 1,207 行，`nl2agent_service.py` 为 983 行，相关代码仍有 30 个 PLR0913 命中。该项仍是唯一确认的 P3 坏味道。 |
| 15 | NL2AGENT 边界入口未通过格式门禁 | 已修复 | Builder 两个入口、chat 集成、service、draft context 与 NL2AGENT components 均通过 ESLint 和 Prettier；同时清理入口文件原有 unused/`any` 问题。 |
| 16 | Python 测试依赖逐文件子进程隔离 | 已修复 | `test_create_agent_info.py` 在 collection 后恢复 `sys.modules`，每个 test 仅临时安装 stub；数据库测试改用稳定的 top-level import。将该文件置于首位时，17 个 NL2AGENT 文件在同一标准 pytest 进程 454/454 通过。 |

## 条件性卡片协议风险复核

原风险已修复。

SDK 的 NL2AGENT card parser 现在只接受位于独立完整行的结束围栏。Marketplace 名称或描述中的内联三反引号不会再提前截断卡片。回归测试使用包含三反引号标记的 JSON 字符串，能够完整提取 card body。

Prompt 仍要求复制真实 Observation JSON；解析边界不再依赖“遇到任意第一个三反引号即结束”的脆弱规则。

## 持久化与生命周期不变量

当前实现满足以下不变量：

1. 数据库 `workflow_revision` 是 workflow 的唯一权威版本；Redis 只是可丢弃投影。
2. workflow 写入使用数据库 CAS，revision 每次只允许增加 1。
3. terminal session 拒绝继续修改。
4. session 创建先提交 durable snapshot，随后 best-effort 预热缓存。
5. session discovery、draft ownership、conversation ownership 均按 tenant 和 user 隔离。
6. active、abandoned、completed session 均有有界 retention 路径。
7. catalog snapshot 只在没有非删除 session 引用时回收，并可按内容哈希恢复。
8. MCP/Skill 安装锁按 ownership token 释放和续租，release 失败不改变业务结果。

## 验证结果

### Backend

- backend `.venv` + `deploy/env/.env`：17 个相关文件同一 pytest 进程，**454/454 passed**。
- conda `nexent` + `deploy/env/.env`：同一组测试，**454/454 passed**。
- 两种入口当前解析到同一 Python 3.11 环境，因此属于调用入口复核，不视为两个独立运行时。
- 第 3 阶段持久化/生命周期专项：**52/52 passed**。
- 第 4 阶段容量/目录/锁专项：**99/99 passed**。
- Python Ruff 默认规则：本次修改的生产 NL2AGENT 文件通过。

### SDK

- `test/sdk/core/agents/test_nexent_agent.py`：**116/116 passed**。
- 包含 marketplace 内联三反引号的 card parser 回归通过。

### Frontend

- TypeScript type-check：通过。
- NL2AGENT Vitest：**7 files，61/61 passed**。
- NL2AGENT service、chat、两个 Builder 入口及相关 components ESLint：0 warning / 0 error。
- 对应文件 Prettier：通过。

### Repository

- `git diff --check`：通过。
- Builder 唯一索引在 ORM、增量迁移与 `deploy/sql/init.sql` 中一致。
- 未使用容器；测试仅使用 backend Python 环境、conda `nexent` 入口和 `deploy/env/.env` 环境变量。

## 修复提交

- `516dcaef` `🐛 Fix: Harden NL2AGENT tenant and auth boundaries`
- `9455aa21` `🐛 Fix: Make NL2AGENT session lifecycle authoritative`
- `38c16834` `🐛 Fix: Make NL2AGENT persistence database authoritative`
- `971d1d3b` `🐛 Fix: Bound NL2AGENT resources and installation races`
- `fab591f0` `♻️ Refactor: Isolate NL2AGENT responsibilities and tests`

## 剩余建议

后续只需继续处理第 14 条低严重度结构性债务：

1. 将 `nl2agent_session_catalog.py` 按 requirements、local recommendation、online installation、card delivery 拆成独立状态域模块。
2. 将 `nl2agent_service.py` 保持为薄 facade，把依赖组装下沉到 composition root。
3. 将长参数内部函数逐步改为不可变 command/value object；HTTP request model 不直接充当业务 command。
4. 为拆分设置循环依赖和文件规模门禁，避免只移动代码、不降低耦合。
