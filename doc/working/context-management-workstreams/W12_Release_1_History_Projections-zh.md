# W12：Release 1 历史投影

## 目标

在 W5 执行事件日志之上构建 `HistoryProjector` 的 Release 1 子集：`chat_projection`、`resume_projection` 和 `model_context_projection`。

W12 是从 P1 拆分出的实施切片。它为 Release 1 提供有界、特定目的的视图，无需等待工作记忆、记忆候选、记忆和完整审计投影。W5 保持持久的真实来源；W12 投影是可重建的派生视图。

当更丰富的 W5 事件可以持久化而不增加活动模型上下文（除非 W13/W10 明确选择相应的 `ContextItem`）时，W12 即成功。

## 为什么这个工作流是必要的

W5 使执行历史持久化，但持久性本身并不足够。如果后续智能体运行、生命周期 API 和最终模型请求直接读取原始 W5 事件，Nexent 将要么用操作细节淹没提示，要么继续依赖无法支持可靠恢复的旧 UI 转录路径。

W12 是使 W5 在 Release 1 中有用的最小投影层：

- 它保护提示大小。丰富的 W5 事件可以包括工具调用、可见进度、重试、错误、快照和生命周期标记。只有有界的模型上下文视图应该成为 W13/W10 的候选。
- 它保留聊天兼容性。当前 UI 行为仍然需要用户可见的消息、单元、来源和附件形状，同时持久事件日志成为权威。
- 它支持重启和工作器交接。后续运行需要活动目标、约束、待处理动作、已完成工具状态和模糊效果阻塞器，而不仅仅是之前的助手最终答案。
- 它为 W13 和 W10 提供稳定的工作单元。策略选择和最终适配需要带来源谱系、权威提示、生命周期状态和最小保真度的类型化 `ContextItem`，而非临时的 `{role, content}` 字符串。
- 它控制 P1 范围。有用的 Release 1 切片可以交付，无需等待工作记忆、记忆候选、记忆和完整审计投影。

没有 W12，W5 风险成为仅审计日志：对存储有价值，但无法直接用于有界上下文组装、生命周期恢复或模型分发。

## 当前代码库差距

当前代码库有几个隐式、特定目的的历史路径，但没有单一的后端拥有的投影层。

### 当前行为

- 聊天持久化在对话表中存储用户提示、助手最终答案、流式助手单元、搜索来源和图像。
- 前端随每个智能体请求发送回对话历史。
- 后端运行准备将那个扁平历史转换为模型消息和合成 SDK 历史对象。
- SDK 主要从最终答案文本重建助手轮次，而非从类型化执行事件的持久序列。
- 上下文组装和压缩在运行时结构和摘要历史上操作，而非从 W5 事件的规范投影。
- 记忆构建和 UI 历史各自使用相同用户对话的自己的临时视图。

### 与 W12 目标的差距

| W12 目标 | 当前差距 |
| --- | --- |
| W5 事件日志是聊天、恢复和模型上下文视图的来源 | 当前运行输入仍然依赖调用者提供的历史和兼容性对话记录。 |
| `chat_projection` 从 W5 事件重建用户可见历史 | 当前聊天历史直接存储为 UI 导向的行，而非从类型化执行事件派生。 |
| `resume_projection` 在重启后暴露活动任务状态 | 当前历史缺少持久运行/步骤/工具状态、待处理动作状态和模糊效果阻塞器。 |
| `model_context_projection` 发出有界的 `ContextItem` | 当前模型上下文从扁平消息、摘要、记忆结果和运行时组件组装，没有稳定的投影契约。 |
| 投影决策带原因编码且可重放 | 当前包含/排除行为分散在前端历史加载、后端转换、ContextManager 策略和记忆代码中。 |
| 原始执行历史可以增长而不增长提示大小 | 当前更丰富的持久化风险要么被模型上下文忽略，要么在没有清晰有界视图的情况下注入。 |

### 如果不修复的实际后果

- 重启恢复只能从可见聊天历史近似状态。
- 工具调用/结果连续性无法可靠重建。
- W7 生命周期 API 没有稳定的派生视图来检查、恢复或重置。
- W13 无法在类型化上下文候选上做出确定性策略决策。
- W10 无法从确切的有资格历史/上下文条目集保证最终适配。
- 添加更多 W5 事件细节可能增加存储价值但不增加智能体可靠性。

## 范围与非目标

W12 负责：

- 按会话顺序读取已授权的 W5 事件。
- 为恢复和模型上下文视图应用活动谱系语义。
- 从 W5 事件生成当前聊天兼容性记录。
- 为重启、工作器交接和后续轮次生成可恢复状态记录。
- 为 W13 策略选择和 W10 最终适配生成有界的 `ContextItem` 候选。
- 发出带原因编码的投影决策。

W12 不负责：

- 添加、修改或删除 W5 事件。
- 实现完整的 P1 投影套件。
- 构建 `working_memory_projection`、`memory_candidate_projection`、`memory_projection` 或完整的 `audit_projection`。
- 决定最终提示成员资格、排序、预算或表示升级。W13 和 W10 负责这些决策。
- 生成缩减或压缩表示。W8 和 W6 负责缩减和压缩。
- 持久化长期记忆。W13 和记忆服务决定并执行记忆操作。
- 实现完整的 P2 缓存验证或 P5 治理。

## 依赖关系

| 依赖 | 所需契约 |
| --- | --- |
| W4 | `ContextIdentity(tenant_id, user_id, conversation_id)` 授权和所有权解析。 |
| W5 | `agent_session`、有序的 `agent_event_index`、类型化的 `agent_event_data`、规范事件读取器和 `compression.snapshot` 事件类型。 |
| W7 | 消费 W12 恢复/模型上下文投影用于恢复、重置、检查和恢复行为。 |
| W13 | 消费 W12 `ContextItem` 用于策略选择和记忆操作决策。 |
| W10 | 消费 W12/W13 选定的上下文候选用于最终适配和提供商分发。 |

P1 完整投影保持推迟，直到 W12 稳定且相关消费者需要它们。

## 投影注册表

Release 1 支持恰好三种投影目的：

| 目的 | 消费者 | 输出 |
| --- | --- | --- |
| `chat_projection` | 当前对话 API 和聊天 UI | 与现有响应形状兼容的用户可见消息/单元/来源记录。 |
| `resume_projection` | 重启、工作器交接或后续用户轮次后的运行准备 | 活动目标、约束、待处理/已完成动作、工具状态、生命周期状态和模糊效果阻塞器。 |
| `model_context_projection` | W13 和 W10 | 有界的 `ContextItem` 候选和可选的令牌估算。 |

不支持的目的以 `unsupported_projection_purpose` 失败；它们不会回退到原始历史。

## 投影请求与结果契约

可信的后端调用者在调用投影器之前解析 W4 身份和 W5 `agent_session_id`。客户端无法通过提供内部 ID 来授权投影。

```text
project_release1(
  identity,
  agent_session_id,
  through_event_seq,
  purpose,
  projection_version,
  authorization_scope,
  options
) -> ProjectionResult
```

请求规则：

- `through_event_seq` 是包含性的。省略表示最新的已提交事件。
- `purpose` 必须是三个 Release 1 注册表值之一。
- `projection_version` 标识转换行为和模式。
- `authorization_scope` 由后端代码解析，无法通过选项扩展。
- `options` 按投影类型化，无法绕过活动谱系或授权规则。

`ProjectionResult` 包含：

| 字段 | 含义 |
| --- | --- |
| `agent_session_id` | 投影的 W5 会话。 |
| `through_event_seq` | 考虑的最后来源序列。 |
| `active_baseline_seq` | 恢复/重置语义后的活动状态基线，当适用时。 |
| `purpose` | 投影注册表值。 |
| `projection_version` | 投影器实现/模式版本。 |
| `records` | 聊天/恢复目的的有序类型化输出记录。 |
| `context_items` | 模型上下文目的的稳定候选；聊天目的为空，除非兼容性代码需要。 |
| `source_ranges` | 读取的来源事件范围和排除的非活动范围。 |
| `decisions` | 包含、排除、分组、转换和修订决策，带稳定原因编码。 |
| `token_estimates` | 仅可选估算；W10 执行最终令牌计数。 |
| `fingerprint` | 来源范围、相关事件内容、投影版本和选项的规范摘要。 |
| `replay_status` | `complete` 或 `partial_after_erasure`。 |

必需失败：

- `identity_not_found`
- `access_denied`
- `session_not_found`
- `invalid_event_range`
- `unsupported_event_schema`
- `unsupported_projection_purpose`
- `unsupported_projection_version`
- `invalid_projection_options`
- `artifact_unavailable`
- `projection_invariant_violation`

## 共享投影管线

每个 W12 投影运行相同的有序阶段：

1. 解析 W4 身份和 W5 `agent_session_id`。
2. 验证 `through_event_seq`。
3. 通过规范读取器按升序 `event_seq` 读取 W5 事件。
4. 应用当前版本中可用的最小授权和修订状态。
5. 为恢复和模型上下文投影解析活动谱系。
6. 按目的转换事件。
7. 当目的需要时构建 `ContextItem`。
8. 记录带原因编码的决策。
9. 计算指纹并返回类型化结果。

W12 仅消费 W5 规范当前形式事件。事件模式上溯保持为 W5 责任。

## 活动谱系规则

- `chat_projection` 默认保留用户可见的线性历史。恢复/重置生命周期标记可以作为元数据暴露，但历史可见消息保持可见，除非后续产品策略明确隐藏它们。
- `resume_projection` 和 `model_context_projection` 应用活动谱系。
- `restore.applied` 事件使恢复的覆盖序列成为活动基线。该恢复序列与恢复事件之间的事件保持为来源历史，但以 `inactive_after_restore` 从活动状态排除。
- `reset.applied` 事件重置声明的派生状态类别。后续事件重建这些类别；未受影响的类别保持活动。
- 标记为 `partial_after_erasure` 的会话必须在每个投影中暴露该重放状态。

## 事件到投影映射

Release 1 必须覆盖至少这些 W5 事件族：

| 事件族 | 聊天投影 | 恢复投影 | 模型上下文投影 |
| --- | --- | --- | --- |
| `user.input` | 用户消息 | 活动目标和显式约束 | 近期用户轮次候选 |
| `run.started` | 通常隐藏 | 运行/配置状态 | 仅在需要时包含智能体/配置元数据 |
| 模型可见进度 | UI 策略支持时的用户可见单元 | 动作状态 | 近期完整步骤候选 |
| `tool.call.*` | 默认隐藏 | 待处理/已完成工具动作 | 与结果配对（当相关时） |
| `tool.result.*` | 可选可见来源/单元 | 结果状态和指针/摘要 | 配对结果摘要或指针 |
| `run.failed`、取消、重试 | 可选状态 | 恢复/重试状态和阻塞器 | 仅在相关时包含 |
| `final.answer` | 助手最终答案 | 已完成结果 | 近期轮次候选 |
| `compression.snapshot` | 默认隐藏 | 恢复加速参考 | 有界摘要候选 |
| `restore.applied`、`reset.applied` | 可选生命周期标记 | 活动谱系变更 | 活动谱系变更 |

未知的已注册事件类型绝不能被静默忽略。投影器必须处理该类型、以已注册原因显式排除它，或以 `unsupported_event_schema` 失败。

## ContextItem 契约

`model_context_projection` 发出 `ContextItem`，而非最终提示消息。

每个 `ContextItem` 包含：

- 稳定条目 ID。
- 条目类型和来源事件引用或连续来源范围。
- 所有权范围和授权标签。
- W13 的权威层级提示。
- 近期性和生命周期状态。
- 最小保真度要求。
- 可选重计算成本和令牌估算。
- 可选指针或摘要引用。

W12 可以为规划估算令牌计数，但 W10 保持提供商分发的最终令牌真实来源。

## 迁移与兼容性

- 现有对话 API 在引入 W12 时继续返回当前聊天响应形状。
- 兼容性投影写入按 W5 `event_id` 幂等。
- 调用者提供的 `AgentRequest.history` 被视为迁移兼容性输入，而非可恢复来源真实。
- 在推出期间，W12 可以在影子模式下运行，并将生成的聊天投影输出与当前对话表进行比较。
- 如果 W12 禁用，现有聊天持久化保持可用，但 W7 重启和 W10 模型上下文重建声明无法启用。

## 必需交付物与阶段

- 交付投影注册表、请求/响应模式、共享投影器管线、三个 Release 1 投影器、原因编码注册表、兼容性适配器、指标和检查钩子。
- 分阶段推出：影子 `chat_projection`、强制 `chat_projection`、`resume_projection`，然后是与 W13/W10 的 `model_context_projection` 集成。

## 实施计划

1. 定义 Release 1 投影模式和原因编码。
2. 实现共享 W5 事件读取器适配器和活动谱系解析器。
3. 在影子模式下实现 `chat_projection` 并与当前 UI 历史比较。
4. 使聊天兼容性输出从 W5 事件幂等。
5. 实现 `resume_projection`，包括模糊效果阻塞器。
6. 实现 `model_context_projection` 和 `ContextItem` 发射。
7. 将 W7 恢复/恢复/检查流程连接到 W12 投影。
8. 将 W13/W10 连接到消费 W12 `ContextItem`。
9. 添加投影延迟、事件计数、输出大小、排除原因和影子不匹配率的指标。

## 代码触点

- W5 事件日志仓库和规范读取器。
- 新历史投影服务/模块。
- `backend/services/conversation_management_service.py`
- 现有对话 API 兼容性代码。
- `backend/agents/create_agent_info.py`
- `sdk/nexent/core/agents/agent_context.py`
- W7 生命周期服务。
- W13 策略服务和 W10 适配管线集成点。

## 测试与完成定义

- `chat_projection` 从 W5 事件保留当前 UI 行为。
- `resume_projection` 在重启后重建活动延续状态。
- `model_context_projection` 为 W13/W10 发出有界的 `ContextItem` 候选。
- 恢复/重置谱系测试证明非活动事件从活动视图排除，但对已授权审计路径保持可用。
- 未知事件测试证明没有事件被静默忽略。
- 幂等性测试证明兼容性投影写入不重复记录。
- 授权测试证明非所有者读取被拒绝而不泄露会话存在。
- 影子模式测试将 W12 聊天输出与现有对话历史比较。
- 性能测试按事件计数和输出大小测量投影延迟。
- W12 在 W7 可以从 W5 事件恢复且 W10 可以接收有界模型上下文候选而不直接读取原始历史时完成。