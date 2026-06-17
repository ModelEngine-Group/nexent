# 上下文管理工作流开发规范

本文件夹将 [`context-management-production-plan.md`](../context-management-production-plan.md) 中的工作流扩展为实施就绪的开发规范。生产计划仍然是路线图优先级和跨工作流架构的权威来源。

## 如何使用这些文档

- 为每个 W-ID 指定一名直接负责的工程师或团队。
- 在实施开始前解决所有未决的设计决策。
- 将依赖关系和契约视为集成要求，而非建议。
- 在工作推进过程中添加 ADR、迁移、拉取请求、仪表板和测试证据的链接。
- 在工作流的完成定义和发布证据满足之前，不要标记工作流为已完成。

## 实施就绪标准

每个 W-ID 规范必须使以下内容可执行，而不需要实施团队发明缺失的架构：

1. 说明目标、所有权边界、依赖关系和非目标。
2. 定义类型化的输入/输出、持久化、版本控制和失败契约。
3. 描述运行时顺序、并发性、幂等性、授权和恢复。
4. 列出必需的交付物和具体的仓库集成点。
5. 将交付划分为安全阶段，包含兼容性、迁移和回滚行为。
6. 定义可观察的原因代码、指标和操作员/调试证据。
7. 根据适用情况指定单元测试、集成测试、属性测试、迁移测试、安全测试、混沌测试和重放测试。
8. 以可衡量的完成门控结束，证明旁路路径和遗留权限已被移除。

如果工作流将行为委托给另一个 W-ID，它必须命名边界，并且不得重复或削弱委托的契约。

## 工作流索引

### 活跃工作流（按实施优先级排序）

| 优先级 | ID | 主题 | 模块 | 依赖 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | [W1](W1_Correct_Model_Token_Capacity_Configuration.md) | 正确的模型令牌容量配置 | 模型容量和请求安全 | 无 | 已完成 |
| 2 | [W2](W2_Output_and_Safety_Capacity_Reserve.md) | 输出和安全容量预留 | 模型容量和请求安全 | W1 | 已完成 |
| 3 | [W3](W3_Prompt_Cache_Aware_Assembly.md) | 提示缓存感知组装 | 质量和效率 | 无 | **移至第一阶段** |
| 4 | [W4](W4_Tenant_and_User_Isolation.md) | 租户和用户隔离 | 持久会话状态和生命周期 | 无 | 活跃 |
| 5 | [W5](W5_Structured_Agent_Execution_Event_Log.md) | 结构化代理执行事件日志 | 持久会话状态和生命周期 | W4 身份契约 | 首先修复缺陷 |
| 6 | [W12](W12_Release_1_History_Projections.md) | 发布 1 历史投影 | 持久会话状态和生命周期 | W5 事件日志 | W5 之后新增 W |
| 7 | [W13](W13_Unified_Context_and_Memory_Policy.md) | 统一上下文和内存策略 | 上下文塑造和压缩 | W5, W12 | W8/W10 之前新增 W |
| 8 | [W6](W6_Reliable_Governed_Compaction.md) | 可靠的受治理压缩 | 上下文塑造和压缩 | W2, W10, W7 | 优先可靠性 |
| 9 | [W7](W7_Full_Session_Lifecycle_APIs.md) | 完整会话生命周期 API | 持久会话状态和生命周期 | W4, W5, W12 | 活跃 |
| 10 | [W8](W8_Progressive_Component_Reduction.md) | 渐进式组件缩减 | 上下文塑造和压缩 | W13 | 活跃 |
| 11 | [W9](W9_Context_Quality_and_Reliability_SLOs.md) | 上下文质量和可靠性 SLO | 质量和效率 | 衡量所有工作流 | 活跃 |
| 12 | [W10](W10_Guaranteed_Context_Fit.md) | 保证上下文适配 | 模型容量和请求安全 | W1, W2; 集成 W8, W13 | 活跃 |
| 13 | [W11](W11_Capacity_Suggestion_On_Model_Add.md) | 模型添加时的容量建议 | 模型容量和请求安全 | W1 目录; 解决 CM-031 | 后验收 |

### 暂缓工作流（P 系列）

P 系列工作流是计划/提议文档，在其依赖项完成之前保持暂缓状态。它们使用 P 编号来区别于实施就绪的 W 系列规范。

| ID | 主题 | 模块 | 暂缓范围 | 激活触发条件 |
| --- | --- | --- | --- | --- |
| [P1](P1_Raw_History_and_Active_Context_Separation.md) | 原始历史和活跃上下文分离 | 持久会话状态和生命周期 | W12 之外的完整投影套件 | W12 完成加上消费者需求 |
| [P2](P2_Complete_Cache_Validation_and_Versioning.md) | 完整缓存验证和版本控制 | 持久会话状态和生命周期 | 完整版本注册表 | W5 + W12 + W13 + P5 完成 |
| [P3](P3_Unified_Context_and_Memory_Policy.md) | 统一上下文和内存策略扩展 | 上下文塑造和压缩 | W13 之外的扩展 | W13 完成加上高级策略需求 |
| [P4](P4_Context_Pollution_and_Large_Output_Control.md) | 上下文污染和大输出控制 | 上下文塑造和压缩 | 工件系统和输出限制快速修复 | 客户需求、大输出事件或 W5 + P5 完成 |
| [P5](P5_Trust_Provenance_Redaction_and_Retention.md) | 信任、溯源、脱敏和保留 | 治理和隐私 | 完整治理栈 | 合规、法律或客户需求 |

### 已退休

| ID | 主题 | 原因 |
| --- | --- | --- |
| ~~W7~~ | ~~持久多工作者上下文状态~~ | 已退休：合并到 W4 作为 `compression.snapshot` 事件 |

## 共享工程规则

1. 原始执行事件是持久的权威记录；投影和检查点可重建。
2. 每个上下文状态操作使用完整的 `ContextIdentity`。
3. 每个模型请求通过容量解析、预算、策略选择和最终适配。
4. 隐藏的思维链既不要求也不持久化。
5. 所有持久化的载荷在存储前经过脱敏和治理。
6. 上下文选择和生命周期决策发出稳定的原因代码和可观察的指标。
7. 现有的聊天 UI 行为在迁移期间保持兼容。
8. 持久执行历史是线性的且无分支。现有公共 API 保持整数 `conversation_id`；内部执行日志使用 `agent_session_id`。