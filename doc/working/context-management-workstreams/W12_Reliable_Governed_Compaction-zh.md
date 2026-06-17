# W12：可靠的受治理压缩

## 目标

将语义压缩建设为有界、可观测、独立治理的服务，不能导致主智能体运行崩溃或无限期延迟。

## 当前状态与差距分析

`sdk/nexent/core/agents/agent_context.py` 中的当前实现提供了功能可用但不完整的压缩系统。本节将当前能力与 W12 要求进行对照以识别差距。

### 当前架构

```
CoreAgent._step_stream()
  → ContextManager.compress_if_needed(model, memory, ...)
    → [Trigger: _effective_tokens > token_threshold]
    → [Two-phase: Previous (60%) + Current (40%)]
    → [Compression path: L1 Full → L2 Trimmed → L3 Hard truncation]
    → [Error handling: context-length retry (1 attempt) → fallback to L3]
    → [Cache: PreviousSummaryCache / CurrentSummaryCache with anchor fingerprint]
```

### 当前优势（已与 W12 对齐）

| 能力 | 当前实现 | W12 对齐度 |
|------|---------|-----------|
| 确定性降级 | L3 硬截断（无 LLM 调用） | ✅ W9 确定性降级 |
| 增量压缩 | 缓存有效路径仅压缩新内容 | ✅ 减少 LLM 调用 |
| 缓存机制 | 锚点指纹匹配 | ⚠️ 部分（非 W6 风格） |
| 成本追踪 | `CompressionCallRecord`（输入/输出 Token、字符数、缓存命中） | ⚠️ 无延迟测量 |
| 两阶段压缩 | Previous/Current 分离 | ✅ 避免单次过载 |

### 关键差距

| W12 要求 | 当前状态 | 差距严重度 |
|---------|---------|-----------|
| 独立压缩模型 | ❌ 使用主执行模型 | 严重 |
| CompactionPolicy 策略对象 | ❌ 无策略对象 | 严重 |
| W1/W2 容量设置 | ❌ 直接使用 `token_threshold` | 严重 |
| 截止时间/超时 | ❌ 无超时机制 | 严重 |
| 取消传播 | ❌ 无取消机制 | 严重 |
| Provider 感知重试限制 | ❌ 仅在上下文长度错误时重试（1 次） | 严重 |
| 限流处理 | ❌ 无限流处理 | 严重 |
| 并发限制 | ❌ 无并发控制 | 严重 |
| Circuit Breaker | ❌ 无 Circuit Breaker | 严重 |
| 单次操作成本上限 | ❌ 无成本上限 | 严重 |
| 单会话成本上限 | ❌ 无成本上限 | 严重 |
| 摘要 Prompt/Schema 版本化 | ✅ 已有 `summary_system_prompt` 和 `summary_json_schema` | 部分 |
| 校验规则 | ⚠️ 仅 JSON 解析，无 Schema 校验 | 部分 |
| W15 最终适配集成 | ❌ 未集成 | 严重 |
| 无效/无进展摘要拒绝 | ❌ 无进展检查 | 严重 |
| 无限重试循环防护 | ⚠️ 仅在上下文长度错误时重试 1 次 | 部分 |
| 执行状态机 | ❌ 无状态机 | 严重 |
| W4 生命周期事件持久化 | ❌ 未持久化 | 严重 |
| 来源指纹重新验证 | ⚠️ 使用锚点指纹，非 W6 风格 | 部分 |
| 结构校验（CM-018、CM-021） | ❌ 无结构校验 | 严重 |
| 语义质量度量（W13） | ❌ 无度量 | 严重 |

### 迁移策略

当前 `ContextManager` 类是主要重构目标。W12 应：

1. 将 `_generate_summary` 和 `_do_generate_summary` 提取为专用压缩服务，具备超时、取消和 Circuit Breaker。
2. 用 W1/W2 容量快照替换直接使用 `token_threshold`。
3. 向 `ContextManagerConfig` 添加 `CompactionPolicy` 配置对象。
4. 对所有压缩模型调用集成 W15 最终适配。
5. 在压缩管道周围添加执行状态机。
6. 将压缩结果持久化为 W4 `compression.snapshot` 事件。

## 压缩策略

W12 负责语义压缩执行、校验、有界重试、降级和操作生命周期。它不定义上下文权威、表示可接受性或压缩快照真实性；W8、W9 和 W6 提供这些契约。

定义版本化的 `CompactionPolicy`，包含：

- 主压缩模型和降级压缩模型。
- 压缩调用的 W1/W2 容量和预留设置。
- 截止时间、取消传播和 Provider 感知重试限制。
- 限流处理、并发限制和 Circuit Breaker 阈值。
- 单次操作和单会话成本上限。
- 摘要 Prompt/Schema 版本和校验规则。
- 语义压缩不可用时的确定性降级行为。

主执行模型不隐式作为压缩模型。所有压缩调用通过 W15 最终适配。无效或无进展的摘要被拒绝，不能触发无限重试循环。

### 压缩触发条件

W12 执行压缩但不定义何时触发。触发条件由 W2 `CapacityReservePolicy.soft_limit_ratio` 定义。当前实现使用两阶段阈值：

- Previous 阶段：`prev_tokens > token_threshold * 0.6`
- Current 阶段：`curr_tokens > token_threshold * 0.4`

W12 应以 W2 软限制比率作为主要触发条件，两阶段阈值作为压缩服务内部的实现细节。

### 降级模型选择策略

当主压缩模型失败时，W12 在降级到确定性 W9 硬裁剪之前使用降级模型。降级模型选择：

1. 如果主模型因 `provider_unavailable` 或 `rate_limited` 失败，使用 `CompactionPolicy` 中配置的降级模型。
2. 如果降级模型也失败，使用确定性 W9 硬裁剪。
3. 降级模型应比主模型更便宜/更快（例如更小的 Context Window、更低的每 Token 成本、更快的响应时间）。
4. 降级模型在 `CompactionPolicy.fallback_model` 中配置，并在策略解析时验证。

运行时内部压缩可作为活动运行的一部分执行。用户/运维者手动压缩请求是 W7 生命周期变更操作，在任何运行活动期间被拒绝。初始版本不支持并发手动压缩或同会话生命周期变更，因此不需要 Fencing Token。

## 执行状态机

使用显式状态，如请求中、运行中、成功、可重试失败、降级运行中、确定性降级、已取消和失败。通过 W4 持久化生命周期事件和压缩结果。成功结果必须在提交前校验 Schema、Token 缩减、必需信息保留和来源覆盖。

## 服务契约

```text
request_compaction(identity, agent_session_id, source_range, policy_version,
                   requested_target) -> CompactionOperation
get_compaction_status(operation_id) -> CompactionStatus
```

操作记录来源范围/指纹、模型/Prompt/Schema 版本、截止时间、尝试次数、成本、状态、输出表示、校验和 W4 事件 ID。必需失败包括 `deadline_exceeded`、`cancelled`、`provider_unavailable`、`rate_limited`、`cost_limit_exceeded`、`summary_invalid`、`no_progress`、`source_changed` 和 `circuit_open`。

## 提交与降级规则

- 来源指纹在提交结果前重新验证。
- 成功需要 Schema 有效性、来源覆盖、最低保真保留和可度量的 Token 缩减。

压缩校验分为结构层和语义层。结构校验（阻断提交）：Schema 有效性、来源事件引用存在性（复用 CM-002 血缘契约）、必需 ContextItem 存在性、工具调用/结果配对完整性、可度量的 Token 缩减，以及表示层级不低于声明的最低保真。W12 的 `summary_invalid` 失败仅由结构校验触发。语义质量（度量，不阻断提交）：信息保留、约束/决策/目标覆盖和来源到摘要的等价性路由到 W13 SLO 度量。**发现：** CM-018、CM-021。

- 重试/降级计数和总截止时间有硬性上限。
- 确定性 W9 降级始终可用并记录显式损失元数据。
- 失败的压缩不能覆盖更新的 `compression.snapshot` 或无限期阻塞运行。

## 子智能体压缩独立性

子智能体会话可以使用自身的 `CompactionPolicy` 通过 W12 触发压缩。父智能体的压缩不影响子智能体会话。每个子智能体会话独立维护自身的压缩状态、缓存和成本核算。当子智能体会话产生 `compression.snapshot` 事件时，其作用域限于子智能体的 `agent_session`，不与父会话的压缩状态交互。

## 必需交付物与阶段

- 交付策略/Schema、操作存储/状态机、服务/执行器、校验器、模型适配器、重试/降级/Circuit Breaker、成本核算、W4 集成、检查接口、仪表板和运维手册。
- 分阶段实施：仅观察校验、隔离服务执行、有界降级、生命周期/API 集成，然后是自动压缩触发。

## 实施计划

1. 定义策略、状态机、失败分类和成本核算契约。
2. 将压缩执行提取到专用服务接口之后。
3. 添加超时、取消、有界重试、降级模型和 Circuit Breaker。
4. 校验摘要 Schema、来源覆盖和可度量进展：
   - Schema 有效性：摘要必须符合 `summary_json_schema`。
   - 来源覆盖：摘要必须通过 CM-002 血缘契约引用来源事件。
   - 可度量进展：压缩输出的 Token 数必须严格小于来源 Token 数。如果压缩产生相等或更大的 Token 数，以 `no_progress` 拒绝并触发确定性 W9 降级。
5. 使用 W9 表示实现确定性硬裁剪。
6. 持久化生命周期事件并通过 W7 检查接口暴露状态。
7. 添加延迟、重试、降级、失败、成本和缩减的仪表板。

## 代码触点

- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_config.py`
- `sdk/nexent/core/agents/summary_cache.py`
- 模型 Provider 和监控层
- W4 事件写入器和 W7 生命周期 Hook

## 测试与完成定义

- 故障注入覆盖超时、取消、限流、格式错误的摘要、Provider 中断、Circuit Breaker 打开、成本上限和无进展输出。
- 测试证明重试次数和延迟有界。
- 确定性降级始终适配并输出显式损失元数据。
- 重复或并发压缩尝试被拒绝或序列化，不能破坏检查点顺序。
- 手动压缩请求在会话运行活动期间以 `operation_conflicts_with_active_run` 被拒绝；运行时内部压缩仍由该运行拥有。
- 性能基线测试测量压缩触发延迟、压缩执行延迟（LLM 调用时长）和校验延迟（较低优先级，在功能实现稳定后进行）。
- W12 在压缩 Provider 降级不能导致运行失控、延迟、重试或支出失控，且每个结果均可持久化和可观测时视为完成。
