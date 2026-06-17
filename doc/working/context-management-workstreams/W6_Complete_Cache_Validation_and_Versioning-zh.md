# W6：完整的缓存校验与版本化

## 目标

防止过期的摘要、Working Memory 和检索结果在任何相关历史、模型、策略、Schema、Prompt、恢复/重置或生命周期变更后被复用。

## 有效性契约

W6 负责规范指纹、校验和失效传递。它不创建投影或决定策略内容；W5、W8 和 W11 提供 W6 校验的版本化输入。

用基于元数据的校验替代 `sdk/nexent/core/agents/agent_context.py` 中仅基于边界的指纹。派生视图或缓存投影仅在以下所有元数据输入匹配时有效：

- W4 会话身份和覆盖的起止事件序列。
- `partial_after_erasure` 标志（物理擦除传播的一次性标记）。
- 上下文策略和记忆策略版本。
- 摘要 Prompt 和输出 Schema 版本。
- 智能体/配置版本和模型 ID。
- Tokenizer 族/版本和容量计算版本。
- 投影/表示 Schema 版本。
- 相关的脱敏、授权和生命周期状态版本。
- 自上次压缩快照以来的事件计数（用于 W5 物化投影）。

内容哈希（遍历事件载荷计算摘要）从 W6 中移除。存储层完整性由数据库校验和处理，而非 W6。分开存储校验组件，使失效原因保持可观测。**发现：** CM-015。

## 失效规则

任何覆盖的事件变更、合法脱敏、删除、恢复/重置操作、模型切换、Prompt/Schema 变更、授权策略变更或记忆生命周期更新均使受影响的派生状态失效。覆盖范围之后的新事件不使已覆盖前缀失效；它们触发增量投影。历史通常不可变，因此编辑通过事件和失效元数据表示。

物理擦除或不可逆脱敏还会将所属会话的重放状态设为 `partial_after_erasure`。通过显式来源 ID 或覆盖的来源范围定位的派生对象作为整体失效；W6 不尝试从摘要或其他生成内容中进行字段级移除。

## 校验器契约

```text
validate_derived_state(candidate, current_inputs) -> ValidationResult
```

`ValidationResult` 为 `valid`、`invalid` 或 `error`，包含比较的指纹组件和稳定原因。必需的无效原因包括 `event_content_changed`、`event_range_changed`、`policy_version_changed`、`model_or_agent_changed`、`prompt_or_schema_changed`、`tokenizer_changed`、`projection_version_changed`、`lifecycle_changed`、`governance_changed` 和 `source_erased`。校验错误绝不降级为缓存命中。

## 校验与失效传递

- 定义一个版本注册表和校验组件 Schema。
- 分开存储校验组件，以便运维能够解释失效原因。
- 直接读取路径必须调用集中式校验器；绕过即为测试失败。
- 删除/脱敏/策略变更发布定向失效任务并持久重试；惰性校验仍作为正确性兜底。
- 已授权的 W11 删除墓碑使匹配的读取候选立即失效，即使目标特定的物理删除仍在进行中。
- 物理擦除通过 `agent_session` 上的一次性 `partial_after_erasure` 标志传播；所有历史压缩快照无需逐快照哈希计算即失效。**发现：** CM-015。

## 必需交付物和阶段

- 交付规范序列化器/哈希器、版本注册表、`DerivedStateValidator`、失效发布器/Worker、解释工具、指标和旧缓存迁移。
- 分阶段实施：影子校验、拒绝无效/读取重建行为、定向失效，最后删除仅基于边界的校验路径。

## 实施计划

1. 在 ADR 中定义版本注册表和校验组件 Schema。
2. 实现 O(1) 基于元数据的校验：
   - compression.snapshot：`partial_after_erasure` 标志 + 版本字段比较（policy_version、model_version、projection_version）。
   - W5 物化投影：快照有效性 + 自快照以来的事件计数 + 版本字段。
   - 物理擦除：一次性 `partial_after_erasure` 标志，使所有历史快照失效，无需逐快照哈希计算。
3. 扩展派生状态记录，包含校验输入和失效原因。
4. 将校验集中到 `DerivedStateValidator`；调用方不能绕过。
5. 为删除、脱敏和策略变更添加定向失效事件/任务。
6. 发送命中、未命中、无效、重建和原因码指标。
7. 提供运维工具，解释派生状态被接受或拒绝的原因。

## 代码触点

- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_cache.py`
- W4 事件日志仓库
- W8 和 W11 的策略/版本注册表
- 监控和生命周期服务

## 测试与完成标准

- 变更测试修改每个覆盖的事件字段和每个版本输入。
- 恢复/重置和模型/Prompt 切换测试证明失效。
- 仅追加增量测试证明有效前缀保持可复用。
- 删除/脱敏测试使所有受影响的投影和压缩快照失效。
- 擦除测试证明范围级和显式 ID 血缘能定位受影响的派生对象，并阻止其在载荷删除后被复用。
- 规范化测试跨进程和支持的运行时版本保持稳定。
- 当没有派生视图或缓存投影能在未经集中式完整校验的情况下被使用，且每次失效均可通过稳定原因码观测时，W6 即完成。
