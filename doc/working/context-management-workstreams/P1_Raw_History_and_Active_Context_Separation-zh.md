# P1：原始历史与活动上下文分离

**状态：** 完整范围已推迟。Release 1 子集（`chat_projection`、`resume_projection` 和 `model_context_projection`）已拆分到 `W12_Release_1_History_Projections.md`。本 P1 文档现代表 W12 之外的更广投影套件。

## 目标

从 W5 执行事件构建确定性、版本化、用途特定的投影。W5 事件日志保持为持久事实源；P1 生成聊天 UI、智能体恢复、模型请求、Working Memory、长期记忆和审计所需的不同视图，而不将全部持久历史发送给每个消费者。

当向 W5 添加更多工具细节、生命周期事件和审计元数据不会自动增加模型 Prompt 大小或改变当前聊天行为时，P1 即为成功。

## 范围与非目标

P1 负责：

- 读取已授权的、按会话排序的 W5 事件范围。
- 应用恢复/重置生命周期语义确定活动状态谱系。
- 将事件转换为可重建的、用途特定的记录和 `ContextItem`。
- 用稳定的原因码解释每次包含、转换和排除。
- 在迁移期间提供后端拥有的聊天和可恢复历史视图。

P1 不负责：

- 追加或变更 W5 事件。
- 决定最终 Token 预算或表示升级；P3 和 W10 负责选择。
- 生成压缩表示；W8 和 W6 负责归约和压缩。
- 持久化恢复压缩快照；W5 负责压缩快照。
- 持久化长期记忆；P3 和记忆服务决定并执行写入。

## 源与派生状态不变量

1. W5 事件是事实源。投影和物化缓存是一次性的。
2. 事件按 `event_seq` 升序读取；UUID 和时间戳永远不定义顺序。
3. 投影器永不更改源事件或对已授权审计隐藏事件。
4. 相同的事件前缀、投影器版本、策略版本和授权作用域产生相同的投影和指纹。
5. `model_context_projection` 不是完整的模型 Prompt。它向 P3/W10 提供符合条件的历史/上下文候选，用于策略选择和最终适配。
6. 恢复/重置通过生命周期事件更改活动状态谱系，而 `audit_projection` 继续暴露完整的已授权事件序列。
7. 隐藏/私有思维链既不需要也不重建。

## 术语

| 术语 | 含义 |
| --- | --- |
| 原始历史 | 按 `event_seq` 排序的已授权 W5 事件。 |
| 活动状态谱系 | 应用恢复/重置生命周期语义后当前生效的事件。 |
| 投影 | 为一个声明用途对原始历史进行可重建的转换。 |
| 投影记录 | 用途特定的输出记录，例如一条聊天消息或一个恢复动作。 |
| `ContextItem` | 稳定的类型化候选，可被选择或归约用于模型上下文。 |
| 物化投影 | 可选的缓存投影，始终可从 W5 重建。 |

## 投影请求与结果契约

创建一个共享的 `HistoryProjector` 服务。公共调用者在投影前解析 `ContextIdentity` 和授权；内部执行使用已解析的 W5 `agent_session_id`。

```text
project(
  identity,
  agent_session_id,
  through_event_seq,
  purpose,
  projection_version,
  policy_version,
  authorization_scope,
  options
) -> ProjectionResult
```

请求规则：

- `through_event_seq` 是包含的。省略表示最新的已提交事件。
- `purpose` 是封闭注册表值，不是任意调用方文本。
- `projection_version` 标识转换行为和 Schema。
- `policy_version` 控制治理/过滤行为，不控制源事件解析。
- `authorization_scope` 由可信后端代码解析。
- `options` 使用类型化的每用途 Schema，不能绕过授权或策略。

`ProjectionResult` 必须包含：

| 字段 | 含义 |
| --- | --- |
| `agent_session_id` | 投影的 W5 会话。 |
| `through_event_seq` | 考虑的最后一个源序号。 |
| `active_baseline_seq` | 由最新适用的恢复/重置生命周期事件选择的 Checkpoint/事件基线。 |
| `purpose` | 投影注册键。 |
| `projection_version` | 转换实现/Schema 版本。 |
| `policy_version` | 使用的治理策略版本。 |
| `records` | 有序的类型化投影记录。 |
| `context_items` | 稳定的候选项，对于不产生它们的投影为空。 |
| `source_ranges` | 消耗的源事件范围，包括相关时排除的非活动范围。 |
| `decisions` | 包含、排除、脱敏、分组和转换决策及原因码。 |
| `token_estimates` | 按记录/项和总计的可选估计；永不视为最终 W10 计数。 |
| `fingerprint` | 源范围、相关事件内容、版本和选项的规范摘要。 |
| `replay_status` | `complete` 或 `partial_after_erasure`；投影永不隐藏源证据的丢失。 |

必需失败类型：

- `identity_not_found`
- `access_denied`
- `invalid_event_range`
- `unsupported_event_schema`
- `unsupported_projection_version`
- `invalid_projection_options`
- `artifact_unavailable`
- `projection_invariant_violation`

## 共享投影管线

每个投影运行相同的有序阶段：

1. **解析身份与边界：** 授权 `ContextIdentity`，解析 `agent_session_id`，验证 `through_event_seq`。
2. **读取规范事件：** 流式读取按 `event_seq` 排序的 W5 索引/数据行；W5 规范读取器验证事件 Schema，将直接前一版本升级到当前内部表示，并验证父/会话关系。
3. **应用治理：** 执行 P5 脱敏、删除、保留和授权。
4. **解析活动谱系：** 对表示当前状态的投影解释 `restore.applied`、`reset.applied` 及相关生命周期事件。
5. **按用途转换：** 使用注册的投影器实现进行分组、选择和转换事件。
6. **构建 `ContextItem`：** 需要时产生稳定的类型化候选和源来源，不选择最终 Prompt 表示。
7. **记录决策：** 为每个排除、转换、非活动或策略拒绝的源记录发出稳定的原因码。
8. **指纹与返回：** 规范化结果输入并计算摘要。

### 活动谱系规则

- `audit_projection` 读取所有已授权事件并忽略活动谱系排除。
- `chat_projection` 默认显示用户可见的线性转录。恢复/重置生命周期标记可作为元数据显示，但先前的可见消息保持可见，除非产品策略显式隐藏它们。
- 恢复、模型上下文和 Working Memory 投影应用活动谱系。
- `restore.applied` 事件记录恢复覆盖的 `event_seq`，并可引用 W5 `compression.snapshot` 事件。当前状态从通过该序号的活动源前缀重建，然后应用恢复事件之后的事件。Checkpoint 可以加速重建但永远不是必需的。恢复边界和恢复事件之间的事件保持为审计历史，但以 `inactive_after_restore` 原因从活动状态中排除。
- `reset.applied` 事件声明哪些派生状态类别重置。后续事件重建这些类别；未受影响的类别保持活动。

## 最小事件到投影映射

事件分类 ADR 必须为每个已注册的 W5 事件类型定义映射规则。初始注册表必须至少覆盖：

| 事件类型或族 | 聊天 | 恢复 | 模型上下文 | Working Memory | 记忆候选 | 审计 |
| --- | --- | --- | --- | --- | --- | --- |
| `user.input` | 用户消息 | 活动目标/输入 | 近期轮次候选 | 目标/约束证据 | 可能的显式事实 | 完整已授权事件 |
| `run.started` | 通常隐藏 | 运行/配置状态 | 仅在需要时提供智能体/配置元数据 | 活动运行状态 | 排除 | 完整已授权事件 |
| 模型动作/可见进度 | 策略可见单元 | 动作状态 | 近期完整步骤候选 | 打开/已完成动作 | 通常排除 | 完整已授权事件 |
| `tool.call.*` | 通常隐藏 | 待处理/已完成工具动作 | 相关时与结果配对 | 工具状态 | 排除 | 完整已授权事件 |
| `tool.result.*` | 可选可见单元/来源 | 结果状态和指针 | 配对结果摘要/指针 | 工具状态/证据 | 符合条件时为已验证证据候选 | 完整已授权事件 |
| `run.failed` / 取消 / 重试 | 可选状态 | 恢复/重试状态 | 仅在相关时包含 | 阻塞/工具状态 | 排除 | 完整已授权事件 |
| `final.answer` | 助手消息 | 已完成结果 | 近期轮次候选 | 目标/动作完成证据 | 仅可能的显式事实 | 完整已授权事件 |
| Working Memory 更新/编辑 | 隐藏 | 活动状态 | 结构化候选 | 应用类型化更新 | 排除 | 完整已授权事件 |
| 记忆候选/决策/写入 | 隐藏 | 通常排除 | 仅当相关且被策略检索时 | 可选决策状态 | 候选/决策记录 | 完整已授权事件 |
| 运行产物（Artifact）事件 | 附件/引用 | 运行产物状态 | 已授权指针/摘要 | 实体/证据引用 | 可能的已验证证据 | 完整已授权事件 |
| `restore.applied` / `reset.applied` | 可选生命周期标记 | 应用谱系/状态变更 | 应用谱系/状态变更 | 应用谱系/状态变更 | 相关时应用谱系 | 完整已授权事件 |
| 删除/脱敏/墓碑 | 按策略隐藏或标记 | 移除/失效受影响状态 | 移除/失效受影响候选 | 移除/失效受影响字段 | 移除/失效候选 | 保留已授权证明元数据 |

未知的已注册事件类型绝不能被静默忽略。投影器必须处理该类型、用已注册原因显式排除它，或以 `unsupported_event_schema` 失败。

P1 投影器仅消耗 W5 规范当前形式事件，永不独立实现事件 Schema 升级器。超出批准的 `current + previous` 兼容窗口的 W5 事件以 `unsupported_event_schema` 失败；P1 不猜测、静默排除或重写它们。

### 投影实现优先级

并非所有投影在 Release 1 中都是必需的。按消费者依赖关系确定优先级：

- **Release 1 必需：** `chat_projection`（UI 兼容性）、`resume_projection`（重启恢复）、`model_context_projection`（P3/W10 输入）。
- **Release 1 可选：** `working_memory_projection`（如果压缩快照直接携带 Working Memory 可延迟）、`memory_candidate_projection`（依赖 P3 Memory Policy Engine）、`audit_projection`（可在核心投影稳定后实现）。
- **延迟：** `memory_projection`（兼容性流程，低优先级）。

## 必需投影

### `chat_projection`

**消费者：** 现有对话 API 和聊天 UI。

**产出：** 有序的用户可见消息记录和附件/引用引用。

包含：

- 持久运行接受的用户输入。
- 助手最终回答。
- 当前 UI 策略支持的显式用户可见进度单元。
- UI 所需的反馈、标题、删除和生命周期元数据。

默认排除：

- 内部工具参数/结果。
- 重试簿记、Checkpoint、策略决策和私有运维元数据。
- 隐藏/私有推理。

必需兼容性映射：

- 从已提交事件顺序派生 `message_index` 和 `unit_index`，永不从调用方历史长度派生。
- 在 UI 迁移之前保持当前消息/单元/来源响应形状。
- 使用源 `event_id` 使投影写入幂等。

### `resume_projection`

**消费者：** 重启后的运行准备、Worker 交接或后续用户轮次。

**产出：** 足以继续未完成工作的类型化记录，无需将每个原始观察重放到模型中。

包含：

- 最新活动的用户目标和已接受的显式约束。
- 已完成和待处理的动作。
- 工具调用/结果状态，包括中断、模糊、已解决和可重试的操作。
- 已确认的决策、未解决的问题、相关运行产物（Artifact）和生命周期状态。
- 可用时最新的兼容 Checkpoint 引用。

未解决的 `ambiguous_effect` 是阻塞性恢复记录。投影不得将关联的工具调用表示为可安全重试或已完成。在 W5 解决事件之后，它投影显式的 `retry`、`skip` 或 `confirm_completed` 决策及其执行者。

排除：

- 已取代/非活动状态。
- 不影响继续的已完成低价值细节。
- 当存在已治理的运行产物（Artifact）指针或摘要时的原始大输出。

### `model_context_projection`

**消费者：** P3 策略选择和 W10 最终适配装配，用于下一次模型请求。

**产出：** 有序的符合条件的 `ContextItem` 候选，不是最终序列化的 Prompt。

包含：

- 近期完整的用户/助手轮次。
- 活动目标、约束、决策、未解决项和必需的工具状态。
- 仍然相关时完整的工具调用/结果对。
- 已授权的运行产物（Artifact）指针和已有效的压缩表示。

规则：

- 永不拆分必需的工具调用/结果对。
- 标记强制/最低保真元数据，但让 P3 决定策略优先级。
- 不自动包含所有聊天或审计记录。
- 增加原始事件细节不得增加此投影，除非转换规则有意产生新候选。

### `working_memory_projection`

**消费者：** 智能体运行时、W5 压缩快照、W7 检查/编辑和 P3。

**产出：** 一个版本化的结构化状态对象加源链接的 `ContextItem`。

最小状态 Schema：

| 类别 | 必需内容 |
| --- | --- |
| `goal` | 当前显式任务目标和状态。 |
| `constraints` | 活动的显式约束及其权威/来源。 |
| `decisions` | 已确认的决策、理由摘要和取代状态。 |
| `open_items` | 未解决的问题、阻塞和计划动作。 |
| `entities` | 活动的文件、资源、标识符和相关状态。 |
| `tool_state` | 待处理、模糊、显式已解决、已完成、失败和可重试的工具操作。 |

规则：

- 状态从事件和显式 W7 编辑事件派生，永不静默变更。
- 冲突更新按权威、生命周期和事件顺序确定性解决。
- 每个字段链接到源事件 ID 并暴露最后更新序号。

### `memory_candidate_projection`

**消费者：** P3 Memory Policy Engine。

**产出：** 已脱敏的候选事实/更正/证据供审查；永不直接写入长期记忆。

仅包含：

- 显式陈述或确认的稳定用户事实/偏好。
- 更正和取代关系。
- 策略允许的工具派生已验证证据。

每个候选包含源事件、置信度/证据类型、提议作用域、保留分类、敏感性分类和拒绝/确认要求。

### `memory_projection`

**消费者：** 需要事件派生记忆的记忆检查和兼容性流程。

**产出：** 从 W5 记忆决策/写入事件派生的策略批准记忆记录。它不执行从外部记忆存储的检索，也不绕过 P3 生命周期过滤。

### `audit_projection`

**消费者：** 已授权运维、调试、合规和 W9 证据。

**产出：** 完整的已授权事件记录加投影/治理决策。

规则：

- 保持规范事件顺序和非活动谱系事件。
- 按 P5 脱敏或拒绝载荷；审计访问不是自动完全访问。
- 为不可用、已删除或物理脱敏的细节包含稳定的原因码。

## `ContextItem` 契约

并非所有投影都产生完整的 `ContextItem` 对象。仅 `model_context_projection` 和 `working_memory_projection` 产生具有所有字段的完整 `ContextItem` 候选。其他投影（`chat_projection`、`resume_projection`、`audit_projection`）产生更简单的用途特定记录结构，不含完整 `ContextItem` Schema。

使用稳定的项标识，使项可以被选择、归约、Checkpoint、检查和重建，而不依赖数组位置。

```text
ContextItem {
  context_item_id,
  agent_session_id,
  item_type,
  scope,
  source_event_ids,
  source_event_range,
  content_or_reference,
  provenance,
  authority_tier,
  lifecycle_status,
  mandatory,
  minimum_fidelity,
  dirty_state,
  recompute_cost,
  last_updated_event_seq,
  schema_version
}
```

规则：

- `context_item_id` 在可行时对逻辑项是确定性的。
- 源来源是强制的；没有可解析来源的项无效。
- 项包含规范语义内容或已治理引用，不包含 UI 格式。
- `full`、`compressed`、`structured` 和 `pointer` 等表示是链接到项的独立 W8 记录。
- P1 可以标记项为强制或从源语义声明最低保真，但 P3 验证并解析最终策略。

## 存储与物化

从按需 W5 投影加 `compression.snapshot` 加速开始。在性能分析之前不要为每个投影创建数据库表。

仅在测量的延迟/负载要求证明合理时才物化：

- `chat_projection` 可通过 W5 兼容性投影器物化到现有对话表中。
- `working_memory_projection` 持久化在 W5 `compression.snapshot` 事件中，在缺失或无效时从 W5 重建。
- 其他投影默认为按需或短生命周期缓存。

每个物化结果存储 `agent_session_id`、`through_event_seq`、`projection_version`、`policy_version`、指纹、创建时间和失效状态。缓存命中仅通过 P2 验证接受。

每个持久化的派生对象必须暴露可查询的源谱系。对稀疏或选择的输入使用显式 `source_event_ids`，对完整连续范围使用 `source_event_range`。简单的反向引用表或索引范围查找即可；不需要全局谱系图和字段级词语归因。

压缩和摘要验证使用两层方法。结构验证（阻塞提交）：每个压缩结果必须包含 `source_event_range` 或 `source_event_ids`（复用 CM-002 谱系契约），引用的源事件必须存在且未被删除，强制 ContextItem 在压缩后必须有相应表示（层级可降级但不能消失），且 Schema 必须有效。语义覆盖（度量，不阻塞提交）：关键决策/约束/目标保留率和源到摘要信息丢失分类路由到 W9 SLO 度量。**发现：** CM-021。

当源事件被物理擦除或不可逆脱敏时，每个谱系包含该事件的持久化派生对象整体失效。在安全时从剩余已授权历史重建。如果无法安全重建，将对象返回为不可用，而不是保留或编辑旧派生内容。

## 运行时集成

### 新的持久运行

1. W5 追加 `user.input` 和 `run.started`。
2. P1 通过已提交的头部构建恢复/Working Memory/模型上下文候选。
3. P3/W10 选择、归约和适配最终模型请求。
4. 运行时事件追加到 W5。
5. P1 聊天投影更新兼容性表；W5 在配置的边界追加 `compression.snapshot` 事件。

### 恢复或 Worker 重启

1. W5 定位该会话最新的 `compression.snapshot` 事件。
2. P1 加载快照载荷（摘要、Working Memory、Token 计量）并重放快照覆盖范围之后到请求事件头部的事件。
3. P1 返回重建的 Working Memory、恢复状态和模型上下文候选。
4. 运行时继续，不信任前端提供的历史。

### 无状态或非持久运行

无状态请求可以使用调用方提供的历史，但必须显式分类。它们不静默修改持久智能体会话或成为权威历史。

## 当前聊天历史迁移

当前 `AgentRequest.history` 由调用方提供，在每次运行前扁平化为 role/content。分阶段迁移：

1. **观察：** 在影子模式下构建 `chat_projection`，并与现有对话表和调用方历史比较。发出原因码不匹配，不改变行为。
2. **投影：** 先追加 W5 事件，然后通过兼容性投影器填充当前对话表。现有读取 API 仍使用当前表。
3. **权威后端历史：** 运行准备读取后端投影。除已验证的回退外，持久会话忽略调用方历史。
4. **投影原生读取：** 对话 API 可直接读取 `chat_projection`；遗留表保持为可选的物化兼容性视图。

永不将调用方提供的历史作为重复源事件追加。W5 之前的历史对话行可以使用显式迁移事件一次性导入，或作为具有已记录边界的遗留前缀保留。

## 稳定决策原因码

至少定义：

- `included_by_projection_rule`
- `excluded_for_purpose`
- `inactive_after_restore`
- `reset_category_inactive`
- `superseded_by_later_event`
- `policy_denied`
- `redacted`
- `deleted_or_expired`
- `replaced_by_artifact_pointer`
- `collapsed_into_group`
- `legacy_history_mismatch`
- `unsupported_event_schema`

## 必需交付物

- 投影请求/结果和每用途记录 Schema。
- 投影注册表和事件到投影映射注册表。
- 已授权的规范 W5 事件读取器。
- 恢复/重置活动谱系解析器。
- 确定性指纹和决策原因实现。
- 七个必需投影器实现。
- `ContextItem` Schema 和构建器。
- 聊天影子比较器和不匹配仪表板。
- 持久运行准备的后端历史适配器。
- 黄金固件、重放固件和迁移固件。

## 实施计划

### 阶段 1：契约与共享读取器

1. 批准投影请求/结果、记录、决策和 `ContextItem` Schema。
2. 定义投影和原因码注册表及其 Schema/版本演进规则。
3. 集成已授权的 W5 规范事件范围读取器；不在投影器中重复 W5 事件升级器。
4. 实现恢复/重置生命周期事件的活动谱系解析器。
5. 实现确定性指纹和共享不变量检查。

### 阶段 2：聊天兼容性

1. 基于黄金 W5 固件实现 `chat_projection`。
2. 构建与当前对话表和 `AgentRequest.history` 的影子比较。
3. 使用源事件幂等性集成 W5 兼容性投影器。
4. 定义/导入 W5 前遗留历史边界。
5. 仅在不匹配目标通过后切换兼容性写入。"零语义不匹配"意味着：消息顺序相同、消息内容相同、附件/引用引用匹配、搜索来源匹配。允许的差异：`message_index` 派生来源（事件顺序 vs. 历史长度）和任何显式批准的 UI 行为变更。

### 阶段 3：可恢复运行时状态

1. 实现 `working_memory_projection` 及其冲突/取代规则。
2. 实现 `resume_projection`，包括中断的工具/运行处理。
3. 集成 W5 `compression.snapshot` 加载/重放：加载快照后，调用 P2 `validate_derived_state(snapshot, current_events)` 确认有效性，然后使用快照载荷进行状态重建。
4. 将持久运行准备改为使用后端投影而非调用方历史。
5. 验证重启和跨 Worker 继续。

### 阶段 4：上下文与记忆候选

1. 实现产生 `ContextItem` 候选的 `model_context_projection`。
2. 将候选输出与 P3/W8/W10 集成，不重复策略逻辑。
3. 实现 `memory_candidate_projection` 和 `memory_projection`。
4. 实现已授权的 `audit_projection`。
5. 仅为测量的瓶颈添加物化。
6. 性能测试度量 100、1000 和 10000 事件会话的投影延迟，以在生产部署前建立基线。

## 代码触点

- 新后端投影注册表（投影注册、原因码注册表、事件到投影映射）、事件读取器、谱系解析器和投影器模块
- W5 事件日志仓储和兼容性投影器
- W5 压缩快照事件和 P2 验证器
- `backend/services/conversation_management_service.py`
- `backend/services/agent_service.py`
- `backend/agents/create_agent_info.py`
- `backend/agents/agent_run_manager.py`
- `backend/database/conversation_db.py`
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_cache.py`
- `sdk/nexent/memory/`

## 测试

- 黄金事件固件验证每个投影和决策原因。
- 确定性测试复现字节等价的规范结果和指纹。
- 恢复/重置固件证明正确的活动谱系，同时审计保留完整历史。
- 当前和直接前一 W5 事件版本固件产生相同的规范投影器输入；W5 兼容窗口外的版本显式失败而非被静默丢弃。
- 授权/脱敏测试证明投影不能泄露租户或受限数据。
- 聊天影子测试比较投影消息、单元、附件和来源与当前 UI 行为。
- 遗留历史迁移测试防止重复消息并定义迁移边界。
- 重启和跨 Worker 测试重建相同的 Working Memory 和恢复状态。
- 中断工具调用测试保持状态和必需的调用/结果关系。
- 模糊效果固件证明恢复保持阻塞，直到存在显式持久解决事件。
- Prompt 增长测试证明额外的审计/工具细节不自动增加 `model_context_projection`。
- 缓存重建测试在删除或损坏后从 W5 复现物化结果。
- 擦除谱系测试通过源事件定位受影响的持久化投影、Working Memory、摘要、Checkpoint 和记忆候选；使每个整体对象失效；并将重建结果标记为 `partial_after_erasure`。

## 完成定义

P1 在以下条件满足时完成：

- 每个必需投影具有已批准的类型化 Schema、版本、确定性实现、黄金固件和稳定的原因码。
- 每个已注册的 W5 事件类型对每个必需投影具有显式映射或排除规则；没有事件类型被静默丢弃。
- W5 支持的 `chat_projection` 对批准的兼容性固件产生零语义消息/顺序/附件/来源不匹配。任何有意更改的 UI 行为被单独批准和版本化。
- 持久运行准备和重启恢复使用后端投影而非信任调用方提供的历史。
- Working Memory 和恢复状态仅从 W5 重建，可选地由有效的 W5 `compression.snapshot` 事件加速。
- P3/W10 接收有界的 `ContextItem` 候选而非原始完整历史。
- 审计可以重建完整的已授权事件序列，包括非活动的恢复/重置历史。
- 所有物化投影是一次性的，且可证明可从 W5 重建。
- 确定性、授权、恢复/重置谱系、重启和迁移测试套件通过，无已知投影不变量违反。
