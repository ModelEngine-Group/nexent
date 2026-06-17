# W7：完整会话生命周期 API

## 目标

在不可变执行历史之上，暴露持久化、经授权、可审计的会话操作，包括 compact、flush_snapshot、restore、reset 和上下文检查。

## API 表面

W7 负责经授权的生命周期编排以及公共/后端 API 行为。它不重写 W4 历史、不实现 W6 内部逻辑、也不定义压缩算法；它协调这些服务并记录其结果。

提供后端 API 及对应的 SDK 方法：

| 操作 | 必需行为 |
| --- | --- |
| `compact` | 创建受治理的压缩表示，可选使用聚焦指令 |
| `flush_snapshot` | 将内存状态作为 `compression.snapshot` 事件刷写到 W4 |
| `restore` | 追加生命周期事件，使某个 compression.snapshot 成为新的活动派生状态基线，不删除后续历史 |
| `reset_context` | 重置选定的派生状态，不删除源历史 |
| `inspect_context` | 返回经授权的条目、表示、预算和决策原因 |
| `resolve_ambiguous_effect` | 为一个被阻塞的工具调用记录显式的 `retry`、`skip` 或 `confirm_completed` 决策 |

新增经授权的 Working Memory 检查/编辑和记忆决策检查操作。编辑以追加事件方式执行，不重写源历史。每个操作在提供幂等键时具备幂等性，并发出前置/后置生命周期事件。

## 行为规则

- 初始生命周期 API 仅操作 W3 单一所有者会话。W7 不暴露任何会话共享、成员管理或所有权转移操作。
- 共享智能体、租户共享记忆和管理员/运维能力不改变会话所有权。任何独立的经授权运维操作均须显式审计，且作用域限于该操作本身。
- 初始版本允许每个持久化会话有一个活动运行。`restore`、`reset_context`、手动 `compact`、Working Memory 编辑及其他变更型生命周期操作在运行活动期间返回 `operation_conflicts_with_active_run`。
- 等待或取消运行并不会使冲突操作变为安全，直到该运行达到已提交的终态/恢复态并清除 W4 `active_run_id`。
- 如果父会话存在待处理的子智能体会话（通过 `parent_session_id` 关联且尚未达到已提交终态的子智能体会话），变更型生命周期操作返回 `operation_conflicts_with_active_subagent`。这与活动运行检查不同：父运行可能在异步子智能体仍在运行时完成当前执行步骤，从而产生一个 `active_run_id` 已清除但子智能体结果尚未写回的窗口。
- 只读 `inspect_context` 可并发执行。作为活动运行一部分执行的运行时内部压缩不属于 W7 手动生命周期变更。
- Restore 和 reset 不能静默销毁脏状态；必须先向 W4 追加 `compression.snapshot` 事件。
- Restore 和 reset 通过新的生命周期事件变更派生活动状态；不删除或重写后续源事件。
- `restore.applied` 事件记录所恢复的覆盖 `event_seq`，并可引用一个 `compression.snapshot` 事件。当 compression.snapshot 不可用时，Projector 可从 W4 重建源前缀，然后应用 restore 事件之后的事件；恢复边界与 restore 事件之间的事件保持可审计但处于非活动状态。
- 手动压缩指令是不受信任的用户输入，受 W8/W11 治理。
- 检查响应脱敏敏感载荷，不暴露隐藏的推理链。
- Inspect、restore 和 resume 响应暴露会话 `replay_status`。`partial_after_erasure` 会话绝不能被报告为完全可重放。
- Restore/resume 仅在投影和策略检查确认安全时才可从重建的剩余状态继续。否则以 `recovery_unsafe_after_erasure` 失败。
- 生命周期 Hook 有截止时间，不能使操作处于半提交状态。
- Resume、restore 和 reset 不得自动调用已提交 W4 历史中仅有开始事件而无终态结果的工具调用。会话保持阻塞状态，直到经授权的用户或运维记录 `retry`、`skip` 或 `confirm_completed`。`retry` 响应必须警告可能产生重复的外部副作用。
- `retry` 允许新的关联工具调用尝试；`skip` 跳过未解决的调用继续执行；`confirm_completed` 记录操作者的断言并继续执行而不调用工具。每个选择都是仅追加的 W4 事件。

## API 与操作契约

每个变更请求包含 `conversation_id`、幂等键、相关的预期生命周期或 Working Memory 版本，以及类型化操作选项。后端解析 W3 身份和 W4 `agent_session_id`；客户端不通过提供内部 ID 进行自我授权。

响应包含操作 ID、生命周期状态、已提交的 W4 事件 ID/序列、compression.snapshot/版本引用和类型化警告。必需错误包括 `access_denied`、`session_not_found`、`version_conflict`、`dirty_state_flush_failed`、`snapshot_invalid`、`operation_in_progress`、`hook_failed` 和 `operation_timeout`。活动运行冲突返回 `operation_conflicts_with_active_run`。不支持的共享或所有权转移请求返回 `shared_conversation_unsupported` 或 `ownership_transfer_unsupported`；普通的非所有者访问继续返回不泄露信息的 `access_denied`/`session_not_found`。未解决的工具副作用状态返回 `ambiguous_effect_resolution_required`。擦除相关响应可能返回 `partial_after_erasure` 警告状态或 `recovery_unsafe_after_erasure`。

## 生命周期状态机

变更操作经历 `requested`、`validating`、`flushing`、`applying`、`committed` 或 `failed`。状态转换和前置/后置 Hook 结果追加 W4 事件。使用相同幂等键重试返回已有操作。检查为只读操作，可并发执行。变更型生命周期操作按智能体会话串行化，在活动运行存在时被拒绝，而非排队或应用。

## 必需交付物与阶段

- 交付 API/SDK Schema、生命周期服务/状态机、操作存储、授权矩阵、Hook、W4/W6 集成、UI/运维控制和运维手册。
- 分阶段交付：inspect/flush_snapshot、resolve_ambiguous_effect、restore/reset、Working Memory 编辑、compact，最后在契约和失败路径稳定后交付前端控制。

## 实施计划

1. 定义请求/响应/错误 Schema 和授权矩阵。
2. 新增生命周期服务，编排 W4 事件、压缩快照和 W6 校验。
3. 对每个变更型生命周期操作强制执行 W4 单活动运行检查。
4. 先实现 flush_snapshot 和 inspect，然后实现 resolve_ambiguous_effect，再实现 restore/reset，最后实现 compact。
5. 新增 `resolve_ambiguous_effect`，包含授权、幂等性和持久化 W4 事件。
6. 新增 Working Memory 编辑操作，包含乐观版本检查。
7. 新增前置/后置 Hook 和类型化生命周期事件。
8. 仅在 API 契约稳定后新增前端/运维控制。
9. 发布 SDK 示例和运维手册。

## 代码触点

- 新增会话生命周期服务和数据库模块
- `backend/apps/conversation_management_app.py`
- `backend/services/conversation_management_service.py`
- `backend/agents/agent_run_manager.py`
- 新增 SDK 会话客户端方法
- 子智能体会话查询（用于调试和冲突检查）
- 监控/运维 UI

## 测试与完成定义

- Restore 能复现 compression.snapshot 的有效活动上下文视图。
- 擦除测试暴露 `partial_after_erasure`，不复用已失效的派生状态，并在无法安全重建时拒绝 restore/resume。
- Reset 保留不可变事件并处理脏状态写回。
- 活动运行冲突测试证明 restore、reset、手动 compact 和 Working Memory 变更在活动运行达到已提交终态/恢复态之前被拒绝。
- 子智能体冲突测试证明当父会话存在待处理的子智能体会话时，即使父运行的 `active_run_id` 已清除，变更型生命周期操作仍以 `operation_conflicts_with_active_subagent` 被拒绝。
- 工具启动后崩溃测试证明 resume 被阻塞、不自动调用工具，且每个显式解决选择都是持久化的、经授权的和幂等的。
- 授权、脱敏、幂等性、并发和 Hook 失败测试通过。
- 单一所有者测试证明没有生命周期 API 会共享或转移会话，共享资源不授予会话访问权，经审计的运维操作不改变所有权。
- 检查能解释包含、排除、缩减、预算和来源决策。
- W7 在所有生命周期操作具备持久化、经授权、可重放、可观测且可通过后端 API 和 SDK 使用时视为完成。
