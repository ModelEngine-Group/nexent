# W13：统一上下文与记忆策略

## 目标

用经过验证、版本化的策略引擎替换分散、部分执行的上下文和记忆行为，该引擎用于上下文选择、记忆操作、投影消费者、降维器和模型请求。

W13 是从 P3 提升的实施工作流。它安排在 W5/W12 之后，因为它需要持久事件和有界的 `ContextItem` 输入；安排在 W8/W10 之前，因为降维器和最终适配需要可执行的策略决策。

当上下文和记忆行为由服务器解析的策略决策决定，而非分散的提示文本、重复的辅助逻辑或调用者提供的断言时，W13 即成功。

## 范围与非目标

W13 负责：

- `ContextPolicy` 和嵌套的 `MemoryPolicy` 模式。
- 策略合并、验证、版本化和解析。
- 确定性的权威和冲突决策。
- 基于 W12 `ContextItem` 的上下文选择决策。
- 记忆读/写/更新/删除权限决策。
- 通过单一策略服务路由自动记忆流和记忆工具。
- 稳定的决策原因码和检查数据。
- 在可信模型调度和受管持久化边界检测旁路。

W13 不负责：

- 序列化最终提供商载荷或执行最终令牌计数。W10 负责最终组装和适配。
- 生成低保真表示。W8 负责降维器。
- 持久化 W5 事件或长期记忆。W5 和记忆服务执行批准的写入。
- 实施完整的 P5 治理、删除传播、编辑、保留或时间记忆生命周期。
- 实施 P4 工件卸载。
- 解决所有可能的冲突本体。Release 1 支持有限的、明确的冲突集。

## 依赖关系

| 依赖 | 所需契约 |
| --- | --- |
| W4 | 可信身份和所有权解析。 |
| W5 | 持久事件/会话身份和源引用。 |
| W12 | `ContextItem` 候选和投影元数据。 |
| W2 | 选择规划期间使用的安全输入预算。 |
| W7 | 暴露策略决策的检查表面和生命周期操作。 |
| W8 | 消费策略决策用于表示降级和升级请求。 |
| W10 | 在调度前消费选定的候选并拒绝过期/缺失的策略决策。 |

P5 保持延期。W13 必须为 P5 元数据定义扩展点，而不要求 P5 在 Release 1 中完成。

## 策略域

定义包含嵌套 `MemoryPolicy` 的 `ContextPolicy`。

`ContextPolicy` 涵盖：

- 组件注入标志。
- 强制状态和最低保真度。
- 总预算和每组件预算。
- 允许的表示层级。
- 确定性的选择和降级规则。
- 每令牌效用评分输入。
- 权威层级和冲突行为。
- Release 1 中可用的范围和隐私约束。

`MemoryPolicy` 涵盖：

- 检索范围。
- 全局重排序和去重行为。
- 记忆写入目标和资格。
- 更新和不写入规则。
- 支持时的确认要求。
- 检索记忆的冲突处理。

无效策略在配置或运行准备期间被拒绝，而非在实时模型调度期间。

## 权威契约

W13 在提示组装之前按以下顺序用代码解析支持的冲突：

1. 系统安全和平台策略。
2. 授权租户策略。
3. 明确的当前用户指令或纠正。
4. 可用时的已确认工作记忆或活跃任务状态。
5. 近期已验证的 W5 事件和工具结果。
6. 有效检索的长期记忆。
7. 压缩摘要。
8. 未验证的智能体推断。

相关性不授予权威。检索内容保持归属且低于权威指令。冲突和排除发出原因码决策。

Release 1 冲突规则：

- 跨层级冲突按上述权威顺序解决。
- 同层级冲突使用更高特异性。
- 如果特异性相等，更近的证据胜出。
- 不可比较的冲突返回 `authority_conflict_unresolved`。
- 不可解决的记忆冲突从提示注入中排除。
- 所有未解决的冲突通过 W7 检查和 W9 指标可见。

## 选择契约

选择分两阶段运行：

1. 以最低可接受表示安装每个强制项。
2. 在可接受升级上确定性地花费剩余预算。

总预算和每组件预算是硬约束。如果强制最小值无法适配，选择以 `mandatory_budget_impossible` 失败；W10 可随后拒绝调度或仅应用其明确允许的紧急行为。

W13 选择产生决策，而非最终消息。

## 策略服务契约

```text
resolve_policy(identity, agent_config, request_overrides) -> ResolvedPolicy
select_context(resolved_policy, context_items, safe_input_budget) -> SelectionDecision
decide_memory_operation(resolved_policy, candidate_or_query) -> MemoryDecision
validate_policy_decision(operation, decision, identity, resource, policy_version) -> ValidationResult
```

`ResolvedPolicy` 包含不可变的合并规则、来源、版本、验证报告和指纹。

`SelectionDecision` 包含：

- 选定和排除的 `ContextItem` ID。
- 每选定项所需的表示层级。
- 预算分配和剩余预算。
- 冲突决策。
- 强制最小值失败。
- 稳定原因码。
- 策略版本和决策指纹。

`MemoryDecision` 包含：

- 操作类型：检索、写入、更新、删除、不写入、需确认。
- 允许的范围和目标。
- 排除的候选或查询结果。
- 冲突和权威决策。
- 适用时的所需确认详情。
- 稳定原因码。

必需失败：

- `policy_invalid`
- `override_not_permitted`
- `mandatory_budget_impossible`
- `authority_conflict_unresolved`
- `memory_operation_denied`
- `policy_decision_missing`
- `policy_decision_stale`
- `policy_decision_identity_mismatch`
- `policy_decision_resource_mismatch`

## 合并与旁路规则

- 合并优先级为平台、租户、智能体、用户配置，然后是允许的请求覆盖。
- 下层不能削弱更高层的安全、隐私或强制上下文规则。
- 选择和记忆决策对相同输入是纯函数和确定性的。
- 运行时调用者接收不可变决策，而非可变策略对象。
- 每个上下文策略、自动记忆流、`store_memory` 和 `search_memory` 路径必须调用 W13。
- SDK/客户端提供的策略决策不可信。
- 可信调度和受管持久化边界需要绑定到身份、资源、操作和策略版本的当前服务器解析决策。
- 缺失、过期或不匹配的决策失败关闭。

## 子智能体策略独立性

子智能体会话基于其智能体配置解析自己的 W13 策略。父智能体的策略不管理子智能体的内部上下文选择或记忆操作。当子智能体的最终答案进入父上下文时，父智能体的 W13 策略管理该结果如何被选择和表示。

## 代码库差距分析

当前集中化：

- `ContextManager` 处理压缩、组件注册、策略选择和系统提示组装。
- 组件预算和注入标志存在，但未在一个可信边界一致执行。

当前分散行为：

- 运行前的记忆搜索旁路 `ContextManager`。
- 记忆级别过滤在 `create_agent_info.py`、`store_memory_tool.py` 和 `search_memory_tool.py` 中重复。
- 运行结束的自动记忆写入在上下文策略路径之外。
- 冲突解决表达为提示指令而非执行代码。
- 一些观察和时间注入逻辑硬编码在智能体运行时路径中。

W13 应将此行为合并到单一策略服务之后，而非仅去重辅助函数。

## 必需交付物与阶段

- 交付策略模式、合并优先级、验证器、解析器、权威/冲突引擎、上下文选择引擎、记忆策略引擎、决策验证器、原因码注册表、指标和 W7 检查集成。
- 分阶段通过影子决策、上下文选择执行、记忆读执行、记忆写/确认执行和旁路移除。

## 实施计划

1. 定义策略模式、默认策略、合并优先级、验证和版本化。
2. 将重复的记忆级别过滤提取到共享的 W13 拥有辅助器。
3. 实施 `resolve_policy` 和确定性权威/冲突解决。
4. 基于 W12 `ContextItem` 和 W2 安全输入预算实施 `select_context`。
5. 通过 `select_context` 路由运行时上下文策略。
6. 通过 `decide_memory_operation` 路由 `search_memory` 工具和运行前记忆搜索。
7. 通过 `decide_memory_operation` 路由 `store_memory` 工具和运行结束自动记忆写入。
8. 发出策略决策事件/遥测并通过 W7 暴露授权检查。
9. 在 W10 调度和受管持久化边界执行策略决策验证。
10. 移除或使旁路路径的发布测试失败。

## 代码触点

- `sdk/nexent/core/agents/summary_config.py`
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/agent_model.py`
- `backend/agents/create_agent_info.py`
- `backend/services/agent_service.py`
- `sdk/nexent/core/tools/store_memory_tool.py`
- `sdk/nexent/core/tools/search_memory_tool.py`
- `sdk/nexent/memory/`
- `backend/services/memory_config_service.py`
- W12 投影器模块
- W7 生命周期检查服务
- W10 最终适配和调度边界

## 指标与原因码

必需指标：

- 策略解析延迟。
- 上下文选择延迟。
- 按组件类型的选定/排除项数量。
- 强制预算失败计数。
- 记忆操作允许/拒绝/确认计数。
- 按权威层级和解决原因的冲突计数。
- 旁路检测计数。
- 过期或不匹配策略决策拒绝计数。

必需原因码族：

- `selected_mandatory_minimum`
- `selected_budget_upgrade`
- `excluded_budget`
- `excluded_policy_disabled`
- `excluded_lower_authority`
- `authority_conflict_resolved`
- `authority_conflict_unresolved`
- `memory_operation_allowed`
- `memory_operation_denied`
- `confirmation_required`
- `policy_decision_stale`
- `policy_decision_missing`

## 测试与完成定义

- 矩阵测试覆盖 Release 1 支持的每个策略、注入标志、预算、权威层级、冲突、确认要求、范围和不写入分类。
- 确定性测试对相同输入和策略版本产生相同决策。
- 旁路测试证明每个上下文和记忆路径调用 W13。
- 负面集成测试证明调用者提供、过期或不匹配的决策不能授权调度或持久化。
- 无效策略固定在运行开始前以可操作错误失败。
- 记忆测试证明运行前搜索、工具搜索、工具写入和自动写入使用相同策略服务。
- W8 集成测试证明降维器从 W13 接收表示要求。
- W10 集成测试证明调度需要当前 W13 决策。
- 性能基线测试测量策略解析和上下文选择延迟。
- W13 完成当一个版本化策略解释并执行每个 Release 1 上下文选择和记忆操作路径，且旁路路径测试失败。