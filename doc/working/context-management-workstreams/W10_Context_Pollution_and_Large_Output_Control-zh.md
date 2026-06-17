# W10：上下文污染与大型输出控制

## 目标

将大型工具输出、日志、文件、搜索结果和委派探索保持在主 Prompt 之外，同时在需要详细信息时保留可靠的、经授权的检索能力。

## 运行产物（Artifact）契约

W10 负责运行产物（Artifact）转存、有界摘要/Pointer 和经授权的检索。它不决定最终上下文选择、保留策略或密钥处理策略；W8/W15、W11 和共享脱敏服务治理这些决策。

大型或二进制输出作为 `agent_artifact` 存储；事件日志和活动上下文保留有界摘要、元数据、内容哈希、授权作用域、保留策略和确定性 Artifact Pointer。内联大小和 Token 阈值由策略驱动。Artifact 是不可变的；更新创建新版本。

Pointer 解析必须校验 W3 身份、授权、生命周期状态、哈希和后端可用性。失败发出不同的类型化故障：denied、deleted/expired、not found、hash mismatch 和 backend error。原始密钥在 Artifact 存储前按 W11 脱敏。如果分类或脱敏失败，原始内容绝不作为 Artifact 或内联降级存储。

## 运行时行为

- 默认启用安全的观察限制。
- 即使原始结果已转存，仍保留完整的工具调用/结果配对。
- 摘要说明省略了什么以及如何检索。
- 智能体对 Artifact 切片的检索受预算控制和审计。
- 委派工作作为独立子智能体运行，拥有自己的 `agent_session`、执行事件日志和容量预算。子智能体委派实现为特殊的内置工具，异步执行并向父智能体返回会话 ID。框架在子智能体执行完成时通知父智能体；父智能体通过查询机制获取子智能体的最终答案。仅子智能体的最终答案暴露给父智能体的上下文；中间执行历史保留在子智能体自己的会话中。父智能体在子智能体执行期间可自由继续其他工作或等待。支持并发子智能体执行；父智能体可并行委派多个任务。W11 治理不在子智能体到父智能体的结果转移期间重新应用；父智能体中的 W8 策略选择自然处理权限差异。**发现：** CM-025。
- 检测重复的等价检索/工具调用以供 W13 度量。

## 子智能体 Artifact 隔离

子智能体 Artifact 作用域限于子智能体的 `agent_session`。父智能体不能直接访问子智能体 Artifact；仅子智能体的最终答案（可能引用子智能体 Artifact）暴露给父上下文。如果父智能体需要子智能体 Artifact 中的详细信息，子智能体必须在其最终答案中包含相关信息，或提供父智能体可通过经授权检索解析的 Artifact Pointer。

## Artifact 与检索契约

```text
offload_output(identity, source_event, content, policy) -> ArtifactReference
resolve_artifact(identity, artifact_reference, slice_request) -> ArtifactSliceResult
```

Artifact 记录包含不可变 ID/版本、所有者作用域、源事件、媒体类型、大小、内容哈希、存储位置、有界摘要、保留/生命周期状态和脱敏元数据。引用不暴露存储凭据。必需失败包括 `artifact_denied`、`artifact_deleted_or_expired`、`artifact_not_found`、`artifact_not_ready`、`artifact_hash_mismatch`、`slice_invalid`、`artifact_governance_failed` 和 `artifact_backend_error`。

Artifact 的有界摘要和引用保留可查询的源事件血缘。源事件或 Artifact 的物理擦除使关联的有界摘要和 Pointer 作为整体派生对象失效；已删除的载荷不保留在证明元数据中。

## 转存发布与失败行为

- 在内容进入 W4 内联细节或活动上下文之前评估字节/Token/类型阈值。
- 首先获取完整的 W11 `GovernedPayload`。治理失败仅允许 sanitized 原因码失败事件、重试、临时进程本地处理或运行失败；绝不允许原始持久化。
- 使用幂等键和内容哈希将治理后的字节上传到不可读的暂存对象。
- 在一个关系事务中，创建 `pending` Artifact 记录、追加 W4 源/引用事件，并创建 artifact-finalize outbox 行。
- W10 所属的 Worker 幂等地完成不可变对象并将 Artifact 标记为 `ready`；仅 `ready` Artifact 可读。
- 失败的 finalize 留下显式的 `pending` 或 `failed` 结果供重试/修复。孤立和过期的暂存对象由 W10 所属的作业清理。
- 失败的转存遵循类型化的按策略行为：治理后的有界内联降级、可重试失败或运行失败；原始超大内容绝不静默注入。
- 检索受范围限制、预算控制、审计，并返回有界切片。

初始 Artifact 生命周期为 `pending -> ready`、`pending -> failed` 和 `ready -> deleted`。这是路径特定的 outbox/finalize 契约；分布式事务、两阶段提交和通用 saga/workflow 平台不在范围内。

## 必需交付物与阶段

- 交付 Artifact Schema/存储库、对象存储适配器、转存决策器、有界摘要器、Pointer 格式、检索 API/工具、生命周期作业和仪表板。
- 分阶段交付：影子阈值度量、工具结果转存、检索/Pointer、委派输出隔离，最后默认安全的观察限制。

## 实施计划

1. 定义 Artifact Schema/状态、暂存/最终存储适配器、Pointer 格式和生命周期策略。
2. 在工具结果摄入时、活动上下文插入前新增 Artifact 转存。
3. 实现确定性有界摘要和元数据提取。
4. 新增 artifact-finalize outbox Worker、重试/修复状态和暂存孤立清理。
5. 新增经授权的 Pointer 解析 API/工具，支持范围/切片。
6. 通过智能体配置按工具类型配置转存阈值。超过阈值的输出作为 Artifact 存储并附带 Pointer；原始内容保留供检索。这是转存决策，不是截断，完整内容仍可通过 Artifact Pointer 访问。上下文空间决策（是否包含完整内容、仅 Pointer 或摘要）由 W8 策略选择和 W15 最终适配做出，而非 W10。
7. 新增隔离的子智能体结果契约和父上下文边界。
8. 将 Pointer 与 W9 表示和 W15 适配阶段集成。

## 代码触点

- W4 事件/Artifact 持久化
- `sdk/nexent/core/` 中的工具执行和观察者路径
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_config.py`
- 托管智能体和外部 A2A 执行路径
- 后端 Artifact API/服务和对象存储适配器

## 测试与完成定义

- 多兆字节输出对活动上下文的影响有界。
- 经授权的智能体检索精确的已转存详细信息和切片。
- Pointer 拒绝、过期、后端缺失和损坏发出不同的故障。
- 发布故障测试证明暂存/上传、数据库提交、finalize 和清理重试不能暴露非 ready Artifact 或丢失修复工作。
- 治理失败测试证明原始内容不存在于 Artifact、事件、降级、日志和修复记录中。
- 工具调用/结果配对在转存和压缩过程中保持完整。
- 子智能体隔离测试证明父 Prompt 仅接收有界输出。
- 子智能体委派测试证明委派工作作为独立会话运行，拥有自己的事件日志。
- 并发子智能体测试证明多个子智能体可在一个父运行下并行执行。
- 最终答案隔离测试证明仅子智能体的最终答案进入父上下文。
- 递归委派测试证明子智能体不能再委派更多任务。
- 性能基线测试度量工具结果摄入时的 Artifact 转存延迟和上下文装配期间的 Artifact 检索延迟（较低优先级，在功能实现稳定后进行）。
- W10 在大型输出默认以 Artifact 优先、检索可靠且受治理、且 Prompt 增长/成本目标达到 W13 阈值时视为完成。
