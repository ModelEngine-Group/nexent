# AgentOS 接口与开发用法

本文对应 `feat-management-runtime-boundary` 当前实现。AgentOS 是 Management 与 Runtime 之间的带类型服务协议，当前使用 HTTP POST、JSON 和 SSE。协议定义在 `backend/contracts/agentos.py`，客户端在 `infrastructure/agentos_client.py`，Management 通过 `management.clients.agentos.AgentOSClient` 使用它。

## 服务职责

Gateway 验证外部身份并路由请求。Management 检查资源权限、用户和租户的会话归属，编译 Agent 资源快照，组织评估与自动化，并将运行事件投影成会话消息。Runtime 根据快照构造 SDK 对象，执行 Agent、模型、工具和沙箱，维护运行状态与事件日志。

两个镜像分别安装 `backend/management` 和 `backend/runtime`。共享 contracts、infrastructure、SDK 不允许反向导入任一服务的业务源码。回调也采用 AgentOS 签名协议，不能从 Runtime 导入 Management 的仓库或服务函数。

## Agent 执行与生命周期

以下地址均以 `/internal/agentos/v1` 为前缀。所有接口都需要服务签名。

| 用途 | POST 路径 | 客户端方法 | 输入与结果 |
| --- | --- | --- | --- |
| 持久会话运行 | `/agent/run` | `start_prepared_run` | `PreparedAgentRun`，返回 `AgentRunReference`，执行与 SSE 订阅分离 |
| 临时运行与调试 | `/agent/run-ephemeral` | `run_ephemeral` | `PreparedEphemeralRun` 或创建类快照，返回流；不创建普通会话消息 |
| 单个评估样本执行 | `/agent/evaluation-case` | `run_prepared_evaluation` | `PreparedEvaluationRun`，返回 answer 和 events；任务编排及判分策略归 Management |
| 从游标重连 | `/agent/resume` | `resume` | `AgentResume`，返回保留的事件及后续 SSE |
| 检查运行 | `/agent/inspect` | `inspect_run` | `AgentRunLookup` 或 `AgentMessageRunLookup`，返回 `AgentRunState` |
| 请求停止 | `/agent/stop` | `stop_run` | `AgentStop`，返回状态和 cancellation_requested |
| 查询会话活动运行 | `/agent/active` | `find_active_run` | conversation_id，返回 run_id 或 None |
| 读取旧运行输出 | `/agent/resume-legacy` | `resume_legacy` | `AgentLegacyResume`；仅供历史会话只读续传，新运行禁止使用 |

`run_id` 是 32 位小写十六进制值，同一次提交与重试必须使用相同 ID。持久会话的 `conversation_id` 必须为正整数。Management 的提交键和事务负责消息幂等；Runtime 负责运行幂等与状态。HTTP 接纳成功不等于模型执行成功，应继续查询终态或消费事件。

`AgentRunState` 包含状态、最新事件游标、资源版本和停止标记。当前状态值以 `contracts/agentos.py` 为准。Runtime 重启后的终态修复由运行持久化与恢复逻辑负责，Management 继续按同一 run_id 处理消息投影。

`AgentResume.after_event_id` 使用 `<run_id>:<sequence>` 格式。Management 应保留 Last-Event-ID 对应关系和已投影位置。SSE 断开后运行可以继续，重连只订阅已有运行。HITL 当前会结束原运行，用户补充内容后创建下一次 run，不能把 SSE resume 当作 HITL 继续执行。

## 资源快照

| 类型 | 内容 | 所有者 |
| --- | --- | --- |
| `AgentResource` | Agent 版本、提示词、子 Agent、工具、Skill、MCP、知识及运行策略 | Management 选择并授权，Runtime 解析执行 |
| `ToolBinding` | 工具标识、参数、配置和受限绑定 | Management 合并参数，Runtime 初始化工具实例 |
| `ModelBindings` | llm、summary、verifier、embedding、rerank、additional_llms | Management 传模型 ID 和版本，Runtime 校验并调用供应方 |
| `RunInput` | query、history、attachment_refs | Management 检查来源与归属，Runtime 下载和处理运行附件 |
| `PreparedConversationScope` | run_id、conversation_id、历史上下文、元数据与版本 | Management 编译，Runtime 验证运行范围 |

快照必须可序列化。禁止传 Python 回调、数据库 session、SDK 模型实例或执行器。SDK 可以定义 PostgreSQL 等业务工具；凭据、连接初始化和授权绑定必须遵守相应资源边界。

新功能通常复用 Management 的 `preparation/evaluation_snapshot.py` 和资源编译器，不要自行拼接不完整的快照。Runtime 从 `prepared_run.py`、`ephemeral.py` 和 `prepared_evaluation.py` 进入 SDK。

```python
from backend.http.client import create_httpx_client
from contracts.agentos import AgentResume, AgentStop
from contracts.constants.environment import RUNTIME_SERVICE_URL
from management.clients.agentos import AgentOSClient

client = AgentOSClient(RUNTIME_SERVICE_URL, create_httpx_client)
# prepared is a Management-authorized PreparedAgentRun.
reference = await client.start_prepared_run(prepared, user_id, tenant_id)
stream = await client.resume(
    AgentResume(**reference.model_dump(), after_event_id=last_event_id),
    user_id, tenant_id,
)
state = await client.stop_run(
    AgentStop(**reference.model_dump()), user_id, tenant_id,
)
```

业务服务应让 HTTP 层消费流或关闭响应，不能建立上游连接后遗失响应对象。客户端的 StreamingResponse 通过迭代器 finally 和 background task 关闭上游。

## 模型调用

所有跨服务推理进入 `Model.invoke`。Management 的评估判分、评估集生成、提示词生成、知识摘要、意图识别等功能均调用同一能力，解释输出和业务流程留在 Management。

| 用途 | 路径 | 输入 |
| --- | --- | --- |
| 获取模型元数据 | `/model/get` | `ModelReference`，返回 ID、类型和 revision，不返回供应方密钥 |
| 文本对话 | `/model/invoke` | `ChatInvocation`，operation 为 chat |
| 向量化 | `/model/invoke` | `EmbeddingInvocation`，operation 为 embedding |
| 重排 | `/model/invoke` | `RerankInvocation`，operation 为 rerank |

输入包含 model_id，可提供 expected_revision。供应方调用方式、Profile、凭据和模型记录由 Runtime 管理。结果为 `ModelResult(revision, output)`，output 的结构随 operation 变化，调用方应按具体类型解释。

```python
from contracts.agentos import ChatInvocation, ChatMessage, EmbeddingInvocation

metadata = await client.get_model(model_id, user_id, tenant_id)
answer = await client.invoke_model(
    ChatInvocation(
        model_id=model_id, expected_revision=metadata.revision,
        input=[ChatMessage(role="user", content="生成一段知识库摘要")],
    ), user_id, tenant_id,
)
vectors = await client.invoke_model(
    EmbeddingInvocation(model_id=embedding_id, input=["待向量化文本"]),
    user_id, tenant_id,
)
```

## 模型管理

`model_command` 接收 `ModelAdministrationOperation` 及 `contracts/model_administration.py` 中对应的类型。Management 对外提供管理 API 和权限校验，Runtime 执行管理写入与连接检查。返回对象经过脱敏，不回传 api_key。

| 能力 | 路径尾部 | 请求类型 |
| --- | --- | --- |
| 注册、更新 | register、update | ModelRegistration、ModelUpdate |
| 停用模型、清理租户模型 | deactivate、deactivate-tenant | ModelSelection、ModelTenantDeactivation |
| 导入供应方模型 | provider-import | ModelProviderImport |
| 批量更新 | batch-update | ModelBatchUpdate |
| 发现、列出供应方模型 | provider-discover、provider-list | ModelProviderDiscovery、ModelProviderList |
| 检查已有模型、探测配置 | healthcheck、probe | ModelHealthcheck、ModelProbe |

这些路径统一位于 `/internal/agentos/v1/model/`。当前没有单独通用的 `Model.list` AgentOS 操作；不要把设计中的抽象方法写成已存在的路由。

## Memory 与反向回调

`/memory/store` 使用 `store_agent_memory`，接收 `AgentMemoryStore` 并返回 `AgentMemoryReceipt`。当前 Memory.search 由运行资源绑定中的 Runtime 工具执行，尚未暴露独立 HTTP search 操作。

Runtime 调用 Management 时使用 `ManagementOperation`，包括自动化提案、Memory 写入通知、Workbench Skill 挂载查询。NL2Agent 的草稿写入使用 `contracts/agentos_agent_creator.py` 中的专用带范围回调。Management 必须校验运行、租户、用户和被授权资源，不能因调用带有效服务签名就省略资源权限校验。

## 鉴权、错误与超时

`AgentOSClient` 对 JSON body、operation、user_id、tenant_id 生成服务签名。双方用 JWT_SECRET 派生不同方向的 HMAC 密钥，token 有效期为 30 秒，绑定 issuer、audience、operation 和 body hash。客户端自动签名，业务代码不应自己拼 token。Gateway 外部用户 token 不直接替代 AgentOS 服务身份。

客户端禁用重定向，请求体上限为 8 MiB。没有签名或签名不匹配返回 401，结构错误通常返回 422，归属不匹配按具体公开合同返回 403 或 404。资源版本冲突、运行冲突和过期游标按接口各自的 409、410 合同处理；不要统一吞成 500。

连接错误转换为 RuntimeServiceUnavailableError，超时转换为 RuntimeServiceTimeoutError，上游非成功 JSON 响应使用 RuntimeUpstreamError 保留状态、响应体和必要响应头。Management HTTP 层负责对外映射，SSE 已建立后的错误按事件合同处理。

普通 JSON 请求默认 connect/read/write/pool 分别为 10/30/30/10 秒，Model.invoke 的 read 为 180 秒。SSE 建连至响应头返回还受 AGENTOS_STREAM_OPEN_TIMEOUT_SECONDS 总截止控制，默认 60 秒；响应头返回后的 SSE read 没有统一空闲超时，避免截断正常长流。评估执行使用单独的长请求策略，不应将它误写为普通 JSON 的 30 秒读截止。调用方还应遵守自身任务截止与取消要求。

## 当前保留项与后续工作

`legacy_resume.py` 仍承接旧数据的只读续传，Management 的历史消息适配与后台来源恢复也仍有调用方。它们不允许启动旧进程内 Agent。无调用方的 legacy admission/tracking/producer、Management 混合执行链、LegacyRunFactory 和旧工作区实现已删除。

KnowledgeBase.search、KnowledgeBase.File.upload/delete 在架构 SPEC 中有目标抽象，目前尚未形成完整独立 AgentOS HTTP 接口。data-process 仍单独运行，它的拆分将在后续规格中完成，不能把当前 Model.invoke 的 embedding 支持等同于整个知识入库流水线已迁移。

规范位于独立文档目录 `nexent-doc/docs/Developing/four-service-runtime-decoupling/changes/management-agentos-service-boundaries/`，部署过程见该目录的 `independent-service-deployment.md`。新增接口先修改中立契约、调用双方及回归验证，完成消费者迁移后删除旧实现。
