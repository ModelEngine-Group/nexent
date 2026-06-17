# W5：结构化智能体执行事件日志

## 目标

创建一个仅追加、类型化、可重放的执行事件日志，作为智能体运行的持久事实源，同时通过兼容性投影保持当前对话 UI 不变。

## 范围与非目标

W5 存储已发生的事实：运行、模型动作、工具调用/结果、运行产物（Artifact）、错误、回答、ContextItem 生命周期、Working Memory 更新和记忆决策。P1 决定每个消费者看到什么。W5 还持久化 `compression.snapshot` 事件以加速恢复。隐藏/私有思维链明确不在要求范围内，默认不持久化。本设计不支持分支和分叉执行历史。

## 核心实体

| 实体 | 必需职责 |
| --- | --- |
| `agent_session` | 租户/用户所有权、状态、生命周期元数据和下一个事件序号 |
| `agent_event_index` | 有序事件信封及运行/步骤关系 |
| `agent_event_data` | 类型化、Schema 版本化的事件载荷 |
| `agent_artifact` | 存储在内联事件之外的大型或二进制输出 |
| `compression.snapshot` | 事件边界恢复记录，作为 W5 事件类型存储 |

### 表设计

#### `agent_session`

| 字段 | 含义 |
| --- | --- |
| `agent_session_id UUID` | 全局唯一的持久智能体会话标识符；与现有 CAS/JWT 认证 `session_id` 不同。 |
| `tenant_id` | 不可变的租户安全与数据隔离所有者，从可信请求上下文中派生。 |
| `user_id` | 租户内不可变的单用户所有者，从可信请求上下文中派生。 |
| `conversation_id NULL` | 兼容性投影引用的现有 Nexent 对话；存在时在租户/用户所有权范围内唯一。 |
| `next_event_seq BIGINT` | 在原子追加期间分配的下一个序号。 |
| 生命周期字段 | 状态、创建/更新时间戳、保留策略和策略元数据。 |

#### `agent_event_index`

| 字段 | 含义 |
| --- | --- |
| `event_id UUID` | 全局唯一事件标识符。UUID 值永远不决定重放顺序。 |
| `agent_session_id UUID` | 所属智能体会话；租户和用户通过 `agent_session` 解析。 |
| `event_seq BIGINT` | 会话内单调递增序号，也是唯一的重放顺序。 |
| `run_id BIGINT` | 会话作用域标识符，表示一次用户触发的执行。 |
| `step_id BIGINT NULL` | 运行作用域标识符，将同一逻辑执行步骤的事件分组。 |
| `parent_event_id UUID NULL` | 直接因果父事件，例如工具结果对应的工具调用事件。 |
| `idempotency_key` | 调用方生成的键，防止重试时重复追加。 |
| `created_at` | 后端分配的事件创建时间戳，用于审计而非排序。 |

必需约束：

- 主键：`event_id`。
- 唯一重放位置：`(agent_session_id, event_seq)`。
- 唯一重试身份：`(agent_session_id, idempotency_key)`。
- 引用的 `parent_event_id` 必须属于同一会话。
- `run_id` 在会话内递增；`step_id` 在运行内递增。

#### `agent_event_data`

| 字段 | 含义 |
| --- | --- |
| `event_id UUID` | 主键及指向 `agent_event_index` 的外键。 |
| `event_type` | 选择载荷 Schema 的稳定注册键。 |
| `schema_version` | 用于验证和解释 `detail` 的 Schema 版本。 |
| `detail JSON/JSONB` | 经过必需脱敏后的已验证事件载荷。 |
| 策略字段 | 脱敏状态、策略版本及其他载荷治理元数据。 |

索引与数据的分离使重放扫描和关系查询保持轻量。两行必须原子插入，因此已索引的事件永远不会缺少其类型化载荷。大型或二进制载荷存储在 `agent_artifact` 中，并从 `detail` 引用。在此事务之前，可信 P5 治理边界必须返回完整的 `GovernedPayload`。分类或脱敏失败不能回退到原始事件持久化；只允许追加一个不含被拒绝载荷的、已脱敏的原因码失败事件。

### 与当前 Nexent 对话的兼容性

现有整数 `conversation_id` 仍是公共聊天标识符，当前对话 API 无需暴露 `agent_session_id`。W5 为每个有所有权的 Nexent 对话恰好创建一个内部 `agent_session`，并在 `conversation_id` 存在时对 `(tenant_id, user_id, conversation_id)` 强制唯一性。没有对话的调试或北向运行可以接收独立的不可复用智能体会话。现有对话在首次 W5 支持的运行时惰性接收会话，或通过迁移作业接收。

初始版本永不更改 `agent_session` 的所有者，也不将多个用户附加到同一会话。共享和所有权转移请求由 W4/W7 拒绝；共享智能体或租户共享记忆不授予 W5 历史的访问权限。

当前对话表在迁移期间保持为兼容性投影：

- 用户输入和助手输出先追加到 W5，然后投影到 `conversation_message_t`、`conversation_message_unit_t` 及源表。
- 现有 `message_index` 和 `unit_index` 仍为 UI 排序字段；它们不替代 W5 `event_seq`。
- 现有的评价更新、标题更改和软删除仍受支持，但必须追加相应的类型化事件，使投影和审计状态一致。
- `agent_id`、模型配置和智能体版本是存储在类型化 `run.started` 载荷中的运行属性，因为所选智能体可能在不同运行之间不同。

主要迁移冲突在于权威性：当前保存路径直接写入对话表，而目标设计使 W5 成为事实源。对于每个需要兼容性投影的事件，W5 事件行及其投影发件箱行在同一关系事务中创建。异步投影器是幂等的，因此事件提交可能暂时不在兼容性视图中，但永远不会丢失修复该视图所需的持久工作项。

其他当前机制冲突及所需解决方案：

| 当前 Nexent 行为 | W5 迁移要求 |
| --- | --- |
| 对话行标识其创建者，但不存储显式 `tenant_id`。 | 回填并强制每个 `agent_session` 的租户所有权；绝不仅从 `conversation_id` 推断所有权。 |
| `AgentRequest.conversation_id` 对调试和北向路径是可选的。 | 创建独立的智能体会话，或显式将运行分类为非持久；不要将其静默追加到另一个对话。 |
| 用户和助手消息异步且直接保存到对话表。 | 在生命周期边界同步追加类型化事件，然后通过持久重试异步投影聊天行。 |
| 活动运行由 `user_id:conversation_id` 注册，因此并发运行会覆盖前一个注册条目。 | 初始持久会话范围允许每个 `agent_session` 恰好一个活动运行。第二个运行被拒绝，直到第一个达到已提交的终态或恢复状态。 |
| UI `message_index` 从请求历史计算，并发运行下可能冲突。 | 从已提交的 W5 事件派生兼容性消息顺序，而非调用方历史长度。 |
| 对话行支持评价更新、标题更改和软删除。 | 保持为投影，同时追加相应的反馈、元数据变更和删除/墓碑事件。 |

### 身份与重放契约

`tenant_id` 和 `user_id` 仅在 `agent_session` 上存储一次，不在每个事件上重复。`run_id` 和 `step_id` 是整数逻辑标识符而非全局唯一身份；它们的完整作用域分别是 `(agent_session_id, run_id)` 和 `(agent_session_id, run_id, step_id)`。事件通过连接索引和数据行、按 `agent_session_id` 过滤并按 `event_seq` 排序来重放。UUID 时间戳、数据库行顺序、`run_id` 和 `step_id` 绝不能替代 `event_seq`。

### 初始活动运行契约

初始版本允许每个持久 `agent_session` 恰好一个活动运行。`agent_session` 存储或引用当前 `active_run_id`；运行启动和终态变更与相应的 W5 生命周期事件一起事务性地更新它。

当 `active_run_id` 存在时，第二个运行和冲突的 W7 生命周期变更被拒绝。已取消、中断或崩溃的运行必须首先达到已提交的终态/恢复状态，然后才能清除活动运行标记。这有意避免了并发同会话变更，且不需要 Fencing Token。

### 仅追加契约

`agent_event_index` 和 `agent_event_data` 在其共享追加事务提交后不可变。普通应用角色可以插入和读取事件行，但不能更新或删除它们。更正、重试、取消和逻辑脱敏由新的类型化事件表示。`agent_session.next_event_seq` 和会话生命周期字段是可变的协调状态，不属于仅追加事件历史。P5 治理的法律删除或物理脱敏是唯一特权例外；它必须发出可审计的墓碑/证明记录，并使受影响的派生状态失效。所属 `agent_session` 被标记为 `partial_after_erasure`；系统不能再声称对该会话具有完整的确定性重放能力。当策略允许时，事件索引和非敏感信封元数据可以保留，但被擦除的载荷内容不得复制到证明中。

## 事件分类

为用户输入、运行生命周期、模型动作、工具调用、工具结果、运行产物（Artifact）、错误/重试/取消、最终回答、Working Memory 更新、记忆候选/写入/冲突决策、ContextItem 创建/表示/召回/驱逐/恢复、写回阶段/验证/提交/拒绝、`compression.snapshot` 和生命周期边界定义稳定的注册表。`run.started` 载荷存储不可变的模型、智能体和配置快照，以便在没有专用运行表的情况下重放该运行。载荷 Schema 使用类型化模型和稳定的原因码。

### `compression.snapshot` 事件类型

`compression.snapshot` 事件将上下文压缩结果作为执行事件日志中的持久事件捕获。它取代了原先独立的 Checkpoint 子系统（W7），并作为重启、故障转移和 Worker 交接的恢复加速点。

载荷 Schema：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `summary_text` | string | 覆盖此快照之前事件的压缩历史摘要 |
| `working_memory` | 结构化对象 | 当前 Working Memory 状态（目标、约束、决策、待解决项、实体、工具状态） |
| `covered_event_range` | `{start_seq, end_seq}` | 此快照覆盖的包含性事件序号范围 |
| `token_accounting` | `{summary_tokens, working_memory_tokens, recent_events_tokens}` | 快照时刻的 Token 计数 |
| `selected_representations` | 列表 | 快照时刻活跃的 ContextItem 表示引用 |
| `policy_version` | string | 用于压缩的上下文/记忆策略版本 |
| `model_version` | string | 用于压缩的模型 ID 和版本 |
| `schema_version` | string | 遵循 CM-005 事件 Schema 兼容契约 |
| `projection_version` | string | 快照时刻活跃的 P1 投影版本 |
| `creation_reason` | enum | `periodic`、`lifecycle_boundary`、`manual_compact`、`dirty_state_flush` |

`compression.snapshot` 事件像其他 W5 事件一样追加。提交后不可变。后续压缩产生新的 `compression.snapshot` 事件，覆盖扩展范围；旧快照作为审计历史保留在事件日志中，但在恢复目的上被最新快照取代。

如果快照载荷超过内联事件大小限制，大字段（例如 Working Memory）作为 P4 运行产物（Artifact）存储并通过指针引用。

### 从压缩快照恢复

Worker 重启、故障转移和负载均衡器路由变更使用以下恢复流程：

1. **查找最新的 `compression.snapshot` 事件**：查询 `agent_event_data` 获取该会话最近的 `compression.snapshot` 类型事件。
2. **加载其载荷**：摘要文本、Working Memory、Token 计量和覆盖的事件范围。
3. **重放快照之后的事件**：读取所有 `event_seq` 大于快照 `covered_event_range.end_seq` 的 W5 事件并应用它们以重建当前状态。
4. **从重建的状态恢复执行**。

如果不存在 `compression.snapshot`（例如首次运行，或所有快照已被擦除），恢复从头重放整个事件日志。这始终正确但对长会话较慢。

恢复永不将进行中的工具调用视为已完成或自动重新调用。未解决的 `ambiguous_effect` 状态阻止继续，直到 W7 记录显式解决方案。

受物理擦除影响的 `compression.snapshot` 整体失效。恢复回退到前一个快照或完整事件重放。如果无法安全重建，恢复以 `recovery_unsafe_after_erasure` 显式失败。

### 脏状态刷写

脏上下文状态（内存中的 Working Memory、待处理的压缩结果）必须在 Worker 交接、关闭、重置、恢复、驱逐或压缩可能丢弃唯一的内存副本之前，作为 `compression.snapshot` 事件提交。刷写失败阻止破坏性生命周期操作并返回类型化故障。

### 初始事件 Schema 兼容契约

CM-005 按能力声明生效：此契约不阻止初始单版本实现或部署，但在首次生产事件 Schema 升级之前是必需的。

对于每种事件类型，W5 注册表声明一个启用的写入版本，并支持读取当前版本及其直接前一版本。W5 规范事件读取器拥有简单的前一到当前升级器，并向 P1、重放、投影和审计消费者返回当前内部表示。存储的事件保持不可变；消费者不实现自己的事件升级器。

超出声明的 `current + previous` 读取窗口的事件以 `unsupported_event_schema` 显式失败。初始契约不承诺任意历史兼容性、旧事件的数据库重写、反向/降级转换或独立 Schema 演进平台。

任何升级不得移除对仍存在于保留持久事件中的 Schema 版本的读取器支持。如果后续升级会将保留事件移出 `current + previous` 窗口，则在启用其写入器之前需要显式批准的迁移或扩展读取窗口；此初始契约不设计该机制。

首次生产 Schema 升级使用两阶段部署：

1. 部署同时接受前一版本和新事件版本的读取器，而写入器继续发出前一版本。
2. 仅在无法读取新版本的实例不再服务后，才启用新写入器版本。

在新版本写入开始后，仅允许回滚到能读取新版本的发布。无法读取新版本的发布不得接收流量。

### 模糊工具效果护栏

对于初始版本，任何已提交的 `tool.call.started` 事件如果没有已提交的终态工具结果事件，在恢复期间被分类为 `ambiguous_effect`。此保守规则不需要工具副作用分类，即使工具可能是只读的也适用。

模糊工具调用在恢复期间不得自动调用。W5 记录显式的操作员/用户解决事件，选择 `retry`、`skip` 或 `confirm_completed`，包括执行者、时间戳和可选理由。只有该解决方案才允许运行继续。选择 `retry` 是对可能重复外部效果的显式接受。

自动效果协调、外部系统状态查询和跨工具事务协调不在 W5 初始范围内。

## 事件写入器接口与失败

```text
append_event(identity, agent_session_id, run_id, step_id, parent_event_id,
             event_type, schema_version, detail, idempotency_key) -> AppendResult
```

`AppendResult` 包含 `event_id`、已提交的 `event_seq`、重复状态和投影发件箱状态。必需失败包括 `session_not_found`、`identity_not_authorized`、`event_schema_invalid`、`parent_session_mismatch`、`payload_too_large`、`governance_processing_failed`、`sequence_conflict` 和 `append_storage_failed`。重试相同的幂等键返回原始已提交结果。
为会话启动第二个运行返回 `active_run_conflict`。
后端注册表（而非不可信调用方）选择启用的写入器 `schema_version`；请求其他版本的追加返回 `event_schema_invalid`。

## 必需交付物与阶段

- 交付 Schema/事件注册表、迁移、追加仓储/服务、运行产物（Artifact）集成、投影发件箱、兼容性投影器、重放读取器和运维工具。
- 分阶段实施：Schema/追加基础、影子事件发出、兼容性投影、事件优先权威切换，然后移除直接转录写入。
- 每个阶段需要迁移报告，覆盖缺失会话、重复消息、未匹配工具对和投影延迟。

## 写入路径

后端拥有事件创建。一个事务验证并脱敏类型化载荷，原子分配会话的下一个 `event_seq`，插入 `agent_event_index` 和 `agent_event_data`，推进 `next_event_seq`，并创建每个必需的兼容性投影发件箱行。如果任何必需的发件箱插入失败，整个追加事务回滚。并发写入器使用行锁或乐观 CAS 操作会话序号。

已提交的 W5 事件立即可权威读取；兼容性视图可能延迟直到其发件箱工作完成。发件箱使用 `(event_id, projection_type)` 作为幂等键，记录待处理、已完成或失败重试状态，以及有界错误元数据和尝试时间戳。投影器重试和未完成行的运维重放必须幂等。失败的投影永不丢失源事件或其修复工作项。

这是路径特定的同数据库事务和异步修复契约。它不需要通用 Saga 引擎、分布式事务或无关存储路径的共享修复框架。

初始实现保持简单的每会话序号分配和规范化索引/数据连接。它记录追加延迟、会话序号锁等待、每会话事件数和重放延迟。仅当代表性 CM-009 工作负载测量超过批准阈值时才考虑批处理、分区、物化或独立序号服务；此优化不阻止初始生产实现。

## 实施计划

1. 在首次生产 Schema 升级之前批准架构决策记录（ADR）：
   - **1a. 事件分类与 Schema ADR：** 定义事件类型（user.input、run.started、run.completed、tool.call.started、tool.call.completed、final.answer、error、cancellation、Working Memory update、memory decision、compression.snapshot、lifecycle boundary 等）、每种事件类型的载荷 Schema 和 Schema 版本化策略。
   - **1b. 排序与幂等 ADR：** 定义 event_seq 作为唯一排序机制、idempotency_key 使用和唯一性约束、run_id 和 step_id 作用域规则，以及并发写入器冲突解决。
   - **1c. 事件 Schema 演进 ADR：** 定义 current + previous 版本支持策略、升级器实现要求和部署/回滚程序。
2. 添加数据库实体、索引、载荷大小限制和追加仓储。
3. 向每个代码路径添加会话解析和事件写入器：
   - **3a. 智能体主循环：** 在 `CoreAgent._run_stream` 中发出 `run.started`（包含模型/智能体/配置快照）和 `run.completed`/`run.failed` 事件。
   - **3b. 工具执行：** 在智能体步骤循环中每次工具调用前后发出 `tool.call.started` 和 `tool.call.completed` 事件。
   - **3c. 错误与取消：** 在异常时发出 `error` 事件，在 `stop_event` 触发时发出 `cancellation` 事件。
   - **3d. 回答生成：** 当智能体产生最终输出时发出 `final.answer` 事件。
4. 为 P1-P5 添加上下文/记忆生命周期事件 API。
5. 与 P5 一起实现持久化前脱敏和运行产物（Artifact）引用行为。
6. 构建到当前对话表的兼容性投影。
7. 分阶段将直接/异步对话保存迁移到事件优先投影：
   - **7a. 影子模式：** 同时写入 W5 事件和现有对话表；比较输出并记录不匹配，不改变行为。
   - **7b. 读取切换：** 从 W5 事件投影读取对话历史；保持双写以确保安全。
   - **7c. 写入切换：** W5 事件成为权威；对话表写入通过兼容性投影器异步进行。
   - **7d. 移除直接写入：** 移除到对话表的遗留直接写入路径；所有变更先经过 W5 事件追加。
8. 实现在进程重启后重建运行的重放工具。

## 代码触点

- `backend/database/db_models.py` 及新事件日志数据库模块（事件仓储用于索引/数据追加和重放，会话仓储用于 agent_session CRUD 和序号分配，投影发件箱用于兼容性投影工作项）
- `backend/agents/create_agent_info.py`
- `backend/apps/agent_app.py`
- `backend/services/conversation_management_service.py`
- `backend/database/conversation_db.py`
- `sdk/nexent/core/agents/nexent_agent.py`
- `sdk/nexent/core/agents/agent_context.py`
- 工具执行和观察者/监控路径

## 测试与完成定义

- 在首次生产事件 Schema 升级之前，Schema 契约测试证明当前和直接前一事件版本通过 W5 规范升级器读取，而窗口外的版本显式失败。
- 在启用新生产品写入器版本之前，读取器优先/写入器延迟部署和回滚测试证明：写入器不能在存在不兼容读取器时启用，没有保留事件版本丢失读取器支持，且回滚永不将流量路由到无法读取已提交新版本事件的发布。
- 原子排序、幂等追加、重试和并发写入器测试。
- 活动运行测试证明持久会话在第一个运行达到已提交的终态或恢复状态之前不能启动第二个运行。
- 约束测试证明事件序号唯一且父事件保持在会话内。
- 原子性测试证明索引和数据行不能部分提交。
- 事件/投影发件箱崩溃测试证明必需的发件箱行与其 W5 事件原子提交，投影延迟保持可见，且重试/运维重放幂等修复失败的兼容性视图。
- 重放测试在重启后重建已完成和中断的运行。
- 物理擦除测试仅保留允许的信封/证明元数据，将会话标记为 `partial_after_erasure`，并阻止完整重放声明。
- 工具调用边界崩溃测试将每个已启动但没有已提交终态结果的调用分类为 `ambiguous_effect`，阻止自动调用，且仅在持久 `retry`、`skip` 或 `confirm_completed` 解决事件后才继续。
- 代表性 CM-009 工作负载测试报告事件追加延迟、会话序号锁等待、每会话事件数和重放延迟，无需推测性批处理、分区或物化。
- 兼容性投影匹配现有 UI 行为。
- 迁移测试覆盖对话支持、调试/非对话和并发运行路径。
- 脱敏固件证明密钥和隐藏推理不存在。
- 性能基线测试在真实工作负载下测量事件追加延迟、会话序号锁竞争和投影延迟，以在生产部署前建立基准。
- W5 在所有生产运行路径发出类型化事件、重放具有足够的确定性以重建状态、模糊工具调用不能自动恢复、且没有 UI 转录被视为执行事实源时完成。
