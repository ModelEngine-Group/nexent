# W2：输出与安全容量预留

## 目标

推导并执行每次请求的安全输入预算，为模型输出、Provider 帧开销、推理行为和 Token 估算误差保留空间。

## 依赖与范围

W2 依赖 W1 的容量快照和 Tokenizer 契约。它负责预算计算和预留策略，不负责组件选择或截断；W10、P3 和 W8 消费生成的预算。SDK/客户端计算仅供参考；可信的服务端模型调度边界负责解析或验证用于生产调度的 W2 快照。

## 预算契约

每次请求：

```text
provider_input_limit =
  min(max_input_tokens, context_window_tokens - requested_output_tokens)
  仅使用已定义的限制

safe_input_budget =
  provider_input_limit
  - uncertainty_reserve

uncertainty_reserve =
  context_window_tokens * 10%
  当任何必需的 Tokenizer、推理窗口或 Provider 开销行为未知时；
  否则使用已批准的 Profile 特定预留
```

10% 的基数是 W1 模型配置或已批准能力 Profile 提供的已解析 `context_window_tokens`。当需要 10% 规则但 `context_window_tokens` 缺失时，W2 不会从 `max_input_tokens` 猜测，而是以 `uncertainty_reserve_basis_unknown` 失败。因此，独立输入上限模型只有在已批准 Profile 提供特定预留并验证了相关行为时，才能在没有 `context_window_tokens` 的情况下运行。

`requested_output_tokens` 受 `max_output_tokens` 约束；默认值为 `default_output_reserve_tokens`，可按智能体或请求覆盖。所有预留决策及其来源均包含在请求遥测中。

## 策略模型

引入经过校验的 `CapacityReservePolicy`，包含 Provider 默认值和有界的运维覆盖：

- 输出预留：预期最大回答大小。
- 不确定性预留：当任何必需的 Tokenizer、推理窗口或 Provider 开销行为未知时，为 `context_window_tokens` 的 10%。
- 已批准的 Profile 特定预留：仅当相关行为在所选 W1 能力 Profile 中已验证时，才可替代 10% 不确定性预留。
- 软限制比率：开始主动压缩的触发点。

无效或负的剩余预算在模型调用之前即配置失败。在第一版中，请求不能降低已配置的默认输出预留。请求可以将 `requested_output_tokens` 增加到 `max_output_tokens`，这会缩窄可用输入预算。降低默认预留需要走现有的授权模型/智能体配置更新路径，并必须记录该决策。请求/运维覆盖不能减少必需的 10% 不确定性预留。

10% 不确定性预留是 `requested_output_tokens` 之外的额外部分，不替代输出容量。硬容量必须已知才能计算。第一版不单独配置未知的推理、Provider 开销和估算误差预留。

## 输入输出契约

```text
calculate_safe_input_budget(capacity_snapshot, reserve_policy, request_overrides)
  -> SafeInputBudgetSnapshot
```

`CapacityReservePolicy` 是不可变/冻结的 SDK 模型，包含 `soft_limit_ratio`（`(0, 1]` 区间的小数）和可选的非负 `approved_profile_reserve_tokens`。`request_overrides` 仅包含可选的正数 `requested_output_tokens`。

`SafeInputBudgetSnapshot` 是不可变/冻结的，包含 W1 容量指纹、Provider 硬输入上限、请求输出、不确定性或已批准 Profile 特定预留、软和硬输入限制、来源、警告及其自身的确定性指纹。类型化失败包括 `invalid_reserve_policy`、`requested_output_exceeds_capacity`、`uncertainty_reserve_basis_unknown`、`reserve_exceeds_capacity` 和 `no_safe_input_capacity`。

## 解析、交付物和阶段

- 请求覆盖收窄限制，除非策略显式允许扩展；未定义的 Provider 限制从 `min(...)` 中省略，绝不视为零。
- 在第一版中，请求覆盖只能增加输出预留，从而收窄输入容量。现有的授权模型/智能体配置可以降低已配置的默认值；不引入新的覆盖权限系统。
- 交付经过校验的策略 Schema、纯函数计算器、统一的 10% 未知能力预留、已批准 Profile 特定预留支持、配置/UI 字段和预留遥测。
- 分阶段实施：仅观察对比、软限制整形、通过 W10 执行硬预算/输出上限强制，最后移除直接的 `token_threshold` 决策。
- 所有调用方消费同一快照；禁止本地重新计算预留。
- 调用方提供的预算快照、预留值和输出上限不可信，不能授权或扩展生产模型调用。

## 实施计划

1. 在上下文/模型配置中添加预留策略字段和校验。
2. 使用 W1 容量快照实现纯函数 `SafeInputBudgetCalculator`。
3. 在上下文组装开始前解析每次请求的输出额度。
4. 用计算出的软和硬输入预算替代 `token_threshold` 用法。
5. 一致地将请求输出 Token 数传递给 Provider 调用。
6. 将预算快照发送到日志、链路追踪和监控。
7. 当统一的 10% 不确定性预留生效时，向运维发出警告。
8. 要求可信的服务端调度路径解析或验证不可变预算快照，并拒绝调用方扩展的限制。

## W2 到 W10 的交接

- W2 从不可变的 W1 快照计算恰好一个 `SafeInputBudgetSnapshot`。
- W2 快照记录 W1 指纹、所选请求输出、预留明细、硬输入预算、软输入预算及其自身指纹。
- W10 拒绝 W1 指纹、Provider/模型标识或请求输出与活动 W1 快照不匹配的 W2 快照。
- W10 可以减少所选输入内容，但不能增加 W2 硬输入预算或独立重新计算预留。
- 可信调度验证最终 W10 结果引用活动的 W1 和 W2 指纹。

## 代码触点

- `sdk/nexent/core/agents/summary_config.py`
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/nexent_agent.py`
- `sdk/nexent/core/models/openai_llm.py`
- `sdk/nexent/core/utils/token_estimation.py`
- `backend/agents/create_agent_info.py`
- `backend/utils/monitoring.py`
- 智能体/模型配置 API 和前端表单

## 测试

- 针对合计窗口、独立输入上限、已知 Profile、未入目录的配置模型、缺失不确定性预留基数和统一 10% 不确定性预留的表驱动单元测试。
- 属性测试断言 `safe_input_budget + all reserves` 绝不超过硬限制。
- 测试证明请求输出与 10% 不确定性预留分开预留，且覆盖不能减少该预留。
- 集成测试验证长回答任务保留请求输出额度。
- 回归测试证明压缩在软限制而非硬边界处开始。
- 遥测测试验证每次请求记录预留值和来源。
- 负面集成测试证明 SDK/客户端提供的或本地重新计算的预算不能扩展生产调度处强制执行的限制。

## 上线与完成标准

先以仅观察模式发布，将计算出的预算与当前 Prompt 大小进行比较。然后执行软限制，再执行硬预算拒绝。当每次请求报告预留明细、Provider 输出上限与预留额度匹配、没有上下文构建器能消费预留容量、且没有调用方提供的预算能削弱服务端强制执行时，W2 即完成。
