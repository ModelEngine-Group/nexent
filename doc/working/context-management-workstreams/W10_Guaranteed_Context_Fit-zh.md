# W10：保证上下文适配

## 目标

将请求适配设为强制性运行时不变量：每次序列化后的主模型和压缩模型请求在发往 Provider 前，都必须处于 W2 安全输入预算范围内。

## 当前状态与范围

`sdk/nexent/core/agents/agent_context.py` 可以在压缩后发出警告，但仍会返回超大的上下文。W10 用确定性的 `ContextFitPipeline` 取代这种尽力而为的行为。它负责最终装配和紧急降级；更丰富的组件 Reducer 和 Artifact 转存通过 W8 和 P4 引入。初始网关不依赖这些更丰富的阶段：先交付硬性适配，后续工作流可以在不削弱或替换该不变量的前提下提升保留质量。

### 当前调度路径分析

所有生产模型调用已汇聚到单一咽喉点：`openai_llm.py:186`（`self.client.chat.completions.create(stream=True)`）。九条调用路径经过该咽喉点：智能体主循环、最大步数处理器、VLM 图像/音频/视频分析、长上下文分析，以及三条压缩路径。

但存在两条绕过该咽喉点的生产路径：

| 编号 | 文件 | 问题 |
|----|------|-------|
| B1 | `backend/utils/llm_utils.py:100` | 系统 Prompt 生成手动构造 completion kwargs 并直接调用 `client.chat.completions.create`，绕过了 `OpenAIModel.__call__` |
| B2 | `backend/services/conversation_management_service.py:282` | 标题生成调用 `llm.generate(messages)`，路由到 smolagents 父类 `generate` 方法，绕过了 nexent 的 `__call__` 覆写 |

非生产的直接调用（`openai_llm.py:350` 和 `openai_vlm.py:72` 中的健康检查，`eval_utils.py:169` 中的基准测试代码）风险较低，不在绕过消除的范围内。

## Pipeline 契约

输入：容量快照、安全输入预算、策略版本、必需 `ContextItem` 最小集、可选表示，以及完整的近期 tool-call/result 对。

输出：序列化后的 Provider 请求、Token 计量、选定的表示 ID、裁剪/降级决策，以及适配状态。Pipeline 必须返回一个适配的请求，或者一个类型化的 `mandatory_context_overflow` 失败。绝不能调度未经验证的请求。

生产调度要求具备 W1 快照且硬容量已知。硬容量未知时以 `provider_capability_unknown` 失败；W10 不能通过猜测总窗口来声称保证适配。当精确计数行为未知但硬容量已知时，W10 依据已包含强制 10% 不确定性储备的 W2 预算进行验证，并记录该计数为估算值而非精确值。

确定性阶段：

1. 移除过期、无效或非必需的条目。
2. 使用已有的有界摘要、指针或低保真表示。
3. 移除或确定性地截断可选内容，同时保留完整的 tool-call/result 对。
4. 执行显式紧急截断并发出上下文丢失事件。

P3-W6 后续可增加策略引导选择、渐进式组件裁剪、Artifact 转存和受治理的压缩作为质量增强阶段。这些阶段不能成为硬性适配或调度安全的前置条件。

选择分两阶段进行：先安装每个必需的最小表示，再按确定性策略效用将剩余 Token 用于更高保真度的升级。

## 网关接口与失败契约

```text
fit_and_serialize(request_intent, capacity_snapshot, budget_snapshot, context_items,
                  policy_version) -> FitResult
```

`FitResult` 包含最终 Provider 载荷、经验证的序列化计数、选定的表示、阶段决策、丢失元数据、稳定前缀指纹、完整 Prompt 指纹、W1 容量指纹、W2 预算指纹和状态。必需失败类型包括 `mandatory_context_overflow`、`serialization_failed`、`tokenizer_unavailable`、`provider_capability_unknown`、`invalid_representation` 和 `provider_limit_inconsistent`，以及 `capacity_snapshot_mismatch` 和 `budget_snapshot_mismatch`。

每个阶段都是确定性的、幂等的、可独立测试的，且无法调度请求。每次实质性变更后，规范化序列化和计数重新执行。Provider 溢出触发一次请求级限制修正和最多一次重试。

## 最终装配与缓存元数据边界

W3 提供确定性的 `CachePartitionPlan`，包含分区分配、排序规则和允许的 Provider 缓存指令。W10 独立拥有最终 Provider 载荷装配、规范化序列化、Token 计数、适配验证，以及基于该精确最终载荷计算的稳定前缀/完整 Prompt 指纹。

可信调度边界将 W10 的 `FitResult` 载荷原样发送。它可以添加仅传输层的认证、追踪和重试元数据，但不能修改 Prompt 内容或缓存指令。W3 绝不对预适配载荷做指纹计算或调度请求。

## 可信模型调度边界

生产 Provider 凭据和调度能力仅对可信服务端调度路径可用。调度前即刻要求：已授权的 W4 身份、不可变的 P3 策略决策、服务端解析或验证的 W2 预算快照，以及精确的最终 W10 `FitResult`。SDK/客户端断言和普通内部调用方不受信任，不能将载荷标记为已授权、受治理或已适配。

缺失、过期、不匹配或调用方展开的决策在 Provider 调度前以失败关闭。必需失败类型包括 `dispatch_not_authorized`、`policy_decision_invalid`、`budget_snapshot_invalid` 和 `fit_result_invalid`。绕过检测仍为诊断性质；直接的生产 Provider 调度路径被移除或拒绝，而非仅被监控。

可信路径验证 W2 快照引用了活跃的 W1 指纹，且最终 `FitResult` 同时引用了活跃的 W1 和 W2 指纹。它还验证 Provider/模型身份和请求的输出与最终 Provider 请求一致。W10 可以削减输入内容，但不能重新解析容量、重新计算储备或增加 W2 硬输入预算。

## 必需交付物与阶段

- 交付适配网关、规范化序列化器/计数器、阶段接口、类型化结果/事件、必需安装器、可选升级选择器、可信调度执行和绕过检测。
- 先交付独立的最小硬性适配网关。然后分阶段推进影子计数、压缩调用执行、主调用执行、P3-W6 质量阶段集成，以及删除/阻断所有直接 Provider 调度路径。

## 实施计划

1. 增加规范化 Provider 请求序列化器和 Tokenizer/计数验证步骤。
2. 定义类型化适配结果、故障码和裁剪/丢失事件载荷。
3. 在公共阶段接口后实现最小独立阶段。
4. 将所有主调用和压缩调用路由到统一的适配网关。
5. 增加基于 Provider 报告限制的单次 Provider 溢出恢复重试。
6. 当必需最小集无法适配时安全拒绝，并包含可操作的诊断信息。
7. 接受 W3 缓存分区计划，仅基于最终序列化载荷计算缓存元数据。
8. 接入 P3-W6 质量增强阶段，不削弱硬性不变量。
9. 消除生产调度绕过并将 Provider 凭据限制在可信路径：
   - **9a. 修复 B1**（`backend/utils/llm_utils.py:100`）：将手动 `_prepare_completion_kwargs` + 直接 `client.chat.completions.create` 替换为调用 `llm(messages)`，使其经过 `OpenAIModel.__call__`。这同时自动获得监控、observer 和 extra_body 集成。
   - **9b. 修复 B2**（`backend/services/conversation_management_service.py:282`）：将 `llm.generate(messages)` 替换为 `llm(messages)`，使其路由到可信的 `__call__` 路径，而非 smolagents 父类 `generate` 方法。
   - **9c. 凭据隔离**（架构层）：确保只有通过 W10 适配验证的请求才能访问生产 Provider API 密钥。可选方案包括在可信调度层注入凭据而非将其存储在 `OpenAIModel` 实例上，或在 `__call__` 中增加适配验证 Gate。这是一项更广泛的架构变更，需与 W10 网关实现同步设计。

## 代码触点

- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/agent_model.py`
- `sdk/nexent/core/agents/nexent_agent.py`
- `sdk/nexent/core/models/openai_llm.py` — 主要咽喉点（第 186 行）
- `sdk/nexent/core/utils/token_estimation.py`
- `sdk/nexent/monitor/agent_observability.py`
- `backend/utils/llm_utils.py` — 绕过 B1（步骤 9a）
- `backend/services/conversation_management_service.py` — 绕过 B2（步骤 9b）

## 测试

- 对任意条目组合、预算、表示和排序进行属性测试。
- 验证序列化后（而非预序列化）的 Token 计数符合硬预算。
- 证明硬容量未知时阻止生产调度，且精确计数行为未知时使用 W2 10% 不确定性储备而不声称精确 Token 计数。
- 测试仅必需条目溢出、紧急截断和稳定原因码。
- 测试每个裁剪阶段下 tool-call/result 对的完整性。
- 模拟 Provider 上下文长度错误，证明一次确定性重试且无循环。
- 证明最小网关在 P3-W6 集成可用前即可保证适配。
- 证明 W3 计划不能改变适配决策，且指纹与可信边界调度的精确最终载荷匹配。
- 运行多语言、多模态和大型 Schema 固件。Release 1 多模态固件仅覆盖文本模态；当某一模态进入产品范围时增加该模态专属固件。**发现：** CM-026。
- 负向集成测试证明 SDK/客户端和普通内部调用方在没有有效 W4、P3、W2 和 W10 决策时无法调度。
- 绕过消除测试证明所有生产 `chat.completions.create` 调用都经过单一咽喉点（`openai_llm.py:186`）。具体包括：
  - 系统 Prompt 生成（`llm_utils.py`）路由经过 `OpenAIModel.__call__`。
  - 标题生成（`conversation_management_service.py`）路由经过 `OpenAIModel.__call__`，且不调用 smolagents 父类 `generate` 方法。
  - 静态分析或代码库搜索确认咽喉点和健康检查例外之外不存在剩余的直接生产 Provider 调度路径。

## 发布与完成定义

先交付最小硬性适配网关、影子评估和故障遥测，然后在压缩调用上执行，最后在主调用上执行。之后再集成 P3-W6 质量阶段。保留临时 Kill Switch 仅用于诊断；它不得允许未经验证的生产调度。当所有模型调用路径使用可信服务端网关、直接生产 Provider 访问被拒绝、属性测试通过，且可预防的上下文长度 Provider 错误达到 W9 发布目标时，W10 即视为完成。
