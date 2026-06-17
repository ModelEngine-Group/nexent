# W8：渐进式组件缩减

## 目标

在 Token 压力下通过将每个组件渐进式缩减到允许的最低表示来保留关键能力，而非整体丢弃。

## 表示模型

W8 负责允许的低保真表示和缩减校验。它不决定策略优先级、最终 Prompt 成员、运行产物（Artifact）授权或压缩调度；P3、W10、P4 和 W6 负责这些决策。

每个 P1 `ContextItem` 可拥有版本化表示：

| 表示 | 用途 |
| --- | --- |
| `full` | 预算允许时的完整内容 |
| `compressed` | 语义缩减的内容 |
| `structured` | 正确行为所需的最少类型化字段 |
| `pointer` | 可解析的引用加上足以决定是否加载的元数据 |

每个条目声明最低保真不变量。Reducer 只能产生允许的表示，且必须拒绝违反不变量的降级。表示生成记录源指纹、从源 `ContextItem` 继承的可查询源事件血缘、生成器版本、Token 计数、丢失元数据和过期状态。

## 组件 Reducer

- 工具：保留名称、用途和最小 Schema；按需加载完整 Schema。
- 技能：缩短描述，保留可能匹配的项，推迟加载完整指令。
- 记忆/知识：全局重排序、去重、摘要、封顶并保留归属。
- Working Memory：始终保留活动目标、显式约束、已确认决策和未解决的工作。
- 智能体定义：保留路由元数据；仅在选择后加载完整卡片。
- 系统指令：保留强制安全和行为段落。
- 历史/观察：保留近期完整步骤和工具调用/结果完整性。

## Reducer 契约

```text
reduce(context_item, target_representation, budget, policy_version) -> ReductionResult
```

`ReductionResult` 包含表示、源指纹、Token 计数、生成器/版本、允许性结果、丢失元数据和稳定决策。必需失败包括 `unsupported_item_type`、`minimum_fidelity_violation`、`reducer_failed`、`representation_stale`、`pointer_unresolvable` 和 `target_budget_impossible`。

Reducer 不选择哪些条目进入 Prompt；P3/W10 请求允许的表示。语义 Reducer 仅通过 W6/W10 治理路径调用模型。每个强制条目类型必须存在确定性的 structured/pointer 降级方案。

缩减结果的校验分为两层。结构校验（阻塞提交）：Schema 有效性、源事件引用存在性、强制 ContextItem 存在性（条目可降级但不能消失）、工具调用/结果配对完整性，以及表示层级不低于条目声明的最低保真。W8 的 `minimum_fidelity_violation` 仅检查表示层级，不检查内容语义。语义质量（度量，不阻塞提交）：信息保留率、约束/决策/目标覆盖率和语义等价性路由到 W9 SLO 度量。语义证明系统或基于 LLM 的自动语义等价校验作为提交门控明确不在范围内。**发现：** CM-018。

## 子智能体 Reducer 独立性

子智能体会话基于自身的智能体配置使用其 Reducer 链。父智能体的 Reducer 不适用于子智能体的内部上下文缩减。当子智能体向父智能体返回最终答案时，父智能体的 P3/W8 管线治理该结果在父上下文中的表示方式。

## 表示生命周期

- 表示仅对其源指纹和生成器/策略版本有效。
- 更新或删除源内容通过 P2/P5 使后代失效。
- 物理源擦除使每个受影响的表示作为整体失效；Reducer 不尝试从生成文本中进行字段级删除。
- 缓存的表示是不可变的；重新生成创建新版本。
- 丢失元数据标识被省略的类别及其是否可恢复。

## 必需交付物与阶段

- 交付表示 Schema/存储、Reducer 注册表/接口、允许性校验器、按组件类型的 Reducer、Pointer 集成、检查和指标。
- 分阶段交付：确定性 structured/pointer 形式、语义 compressed 形式、P3/W10 集成，最后基于度量需求进行预计算/缓存。

## 实施计划

1. 定义 Reducer 接口、表示 Schema、允许性检查和原因码。
2. 为每个组件类型新增确定性 Reducer。
3. 按需为确定性 Reducer（structured、pointer）生成低保真形式。在创建或实质性更新时缓存语义 Reducer（compressed）的低保真形式，因为重新生成涉及 LLM 调用。
4. 将表示选择集成到 P3 策略和 W10 最终适配管线。
5. 与 P4 一起新增 Pointer 解析和故障处理。
6. 发出缩减决策、丢失内容元数据、生成成本和过期状态。
7. 新增运维对表示链的检查。

## 代码触点

- `sdk/nexent/core/agents/agent_model.py`
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_config.py`
- P1 context-item/projector 模块
- 工具、技能、知识、记忆和智能体定义装配路径

## 测试与完成定义

- 每个组件的超大 fixture 保留其强制最低表示。
- 测试拒绝无效降级和过期表示。
- 往返 Pointer 测试在经授权时恢复完整内容。
- 质量测试度量保留的约束、决策、工具能力和归属。
- 确定性和 Token 核算测试覆盖每个 Reducer。
- 性能基线测试度量每个组件类型的 Reducer 延迟（较低优先级，在功能实现稳定后进行）。
- W8 在每个支持的组件类型具备允许的缩减链、没有强制最低表示被静默丢弃、且 W10 能消费 Reducer 输出时视为完成。
