# AgentOS 接口与开发用法

本文对应 `feat-data-process-retirement` 当前实现。AgentOS 是 Management 与 Runtime 之间的带类型服务协议，当前使用 HTTP POST、JSON 和 SSE。协议定义在 `backend/contracts/agentos.py`，客户端在 `infrastructure/agentos_client.py`，Management 通过 `management.clients.agentos.AgentOSClient` 使用它。

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
| 工具试跑 | `/agent/tools/invoke` | `invoke_tool` | `AgentToolInvocation`，返回 `AgentToolResult`；当前支持文本分析，执行归 Runtime |
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
| 分页查询模型元数据 | `/model/list` | `ModelListQuery`，可按 model_type 筛选，返回 `ModelCatalogPage` |
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

`EmbeddingInvocation.input_type` 默认为 `text`。多模态模型可传 `image`，此时 `input` 只接收 `data:image/<mime>;base64,...`，支持 PNG、JPEG、GIF、WebP、BMP、TIFF，不读取任意 URL、S3 或本地文件。纯文本 embedding 模型会拒绝图片输入。现有 AgentOS HTTP 请求体上限仍为 8 MiB，内联图片也受该上限约束。

Runtime 的 KB 入库从已确认的清洗 manifest 读取钉住版本及 SHA256 的图片，经同一 Model.invoke 服务向量化。图片字节不会落入向量 payload；检索结果的可空 `image_ref` 返回 typed ObjectReference 和位置。普通 embedding 模型继续只处理文字。图片引用的前端展示、旧检索结果对照和 Management 公开工作流切换仍需后续完成。

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

这些路径统一位于 `/internal/agentos/v1/model/`。`client.list_models(ModelListQuery(...), user_id, tenant_id)` 查询 Runtime 权威模型目录，默认每页 100 条，上限 1000；后续页使用返回的 next_cursor。结果仅包含 ID、类型、展示名、限定模型名和版本，不返回 URL、凭据或 headers。游标受租户和查询范围限制，目录查询有 10 秒总截止。

## 文本工具试跑与清洗

Management 的工具试跑先编译已有 `ToolBinding`，再调用 `/internal/agentos/v1/agent/tools/invoke`。输入包含服务端生成的 run_id、工具绑定、inputs 和 language。入口接受 `analyze_text_file` 及第 2 版知识工具绑定，Runtime 校验资源和模型版本后在受管线程执行。文本工具总截止 600 秒，知识工具总截止 180 秒；请求断开或超时会取消当前 scope。该接口不创建普通会话消息，也不返回 SSE。知识工具运行输入只允许 query 和可选 index_names，文件与模型范围由已授权绑定固定。

```python
from uuid import uuid4
from contracts.agentos import AgentToolInvocation

result = await client.invoke_tool(
    AgentToolInvocation(
        run_id=uuid4().hex, tool=authorized_binding,
        inputs={"file_url_list": file_urls, "query": query}, language="zh",
    ), user_id, tenant_id,
)
analyses = result.result
```

普通 Agent 的文本工具也使用同一 Runtime 清洗适配器，run_id 来自运行上下文。SDK 接收本地 `text_cleanser` callable，此对象仅在 Runtime 内注入，不能放入跨HTTP的资源快照。SDK benchmark 直接构造文本工具时，也必须显式传入此能力。随仓库提供的 generic benchmark CLI 显式使用本机SDK DataProcessCore公共算法，不依赖服务容器，需安装SDK data_process依赖及本机解析资源；这是离线算法评测场景。旧 `DATA_PROCESS_SERVICE` 地址和 `process_text_file` 方法已经移除。

Runtime 将已加载的文件字节存为本次 run 的唯一暂存对象，再反向调用 Management 的 FileCleanse.submit/inspect。Management 提取结构，Runtime 读取带 revision/hash 的私有产物并完成最终分块；JSON 分块使用同一源字节。工具按原顺序逐文件分析，保留长文本模型接口与每文件分析异常结果。

FileCleanse 的 submit、inspect、cancel、release 分别位于 `/internal/agentos/v1/file/cleanse`、`file/cleanse-status`、`file/cleanse-cancel`、`file/cleanse-release`，客户端为同名 `*_file_cleanse` 方法。清洗等待上限300秒，各HTTP操作仍受10秒总截止。消费后先确认release，再删除本次暂存源；用户原文件保持不变。提交结果不明或release失败会报错并保留对象，不自动重试或恢复。已知未结束任务只发送一次cancel。

新镜像部署需要设置 `MANAGEMENT_FILE_CLEANSE_ENABLED=true`。新 `.env.example` 和 Helm `nexent-common.config.fileCleanse.enabled` 均已默认启用，升级已有 `.env` 时需同步该值；通过 `nexent-env` Secret注入同名变量时也需同步。本地backend未配置时仍默认关闭。维护窗口内先确认Management迁移与清洗root就绪，再部署Runtime并恢复流量。

该开关同时启用 Management 的持久 KB 摄取协调任务。发现端口只返回原用户、租户和文件 ID，每轮最多 100 项，保存分页游标直到末页再回绕；业务推进重新读取当前资源授权。未知提交结果只查询原清洗/Runtime job ID，不补投。后台任务退出后 ready 返回 503，live 保持 200，应用不会自动重启任务。

普通文件处理、北向上传和官方二进制资源导入通过 Management 接纳服务进入同一协调器。北向响应由现有 Northbound 服务适配，公开接口保持原格式。部署前执行 SQL 020 和 021。未指定 KB 的 local 上传登记在当前用户及租户下，处理时检查目标 KB 编辑权限，再固定目标文件 ID并复用对象上传和配额流程。local_source_path 只用于 Management 核对登记的别名，Runtime 接收固定对象引用；未登记的历史路径不能直接处理，未知绑定不会自动重传。状态和删除切换、历史维护及完整服务验收仍按退役 SPEC 完成，当前不能据此删除 data-process。

文本清洗执行链已经迁移。通用SDK加载器原有MinIO调用、历史附件及共享知识库的旧URL权限策略仍需后续整改；当前没有扩大读取范围，不能据此声称StorageInterface全覆盖或data-process完整退役。

KB 搜索图片由 Runtime 注入本地 image_filterer，并传入当前运行的取消 scope。筛选只接受 KnowledgeContentRequest，经 AgentOS authorize-content 获取实时授权，再通过单键、单版本只读 ObjectStore 读取。旧 KB URL/inline 读取和对象 ACL 直查已经移除，网页工具仍使用自己的网页图片读取能力。每张图沿用两秒总预算及原尺寸/CLIP 判定；取消会终止活动请求并向本次拥有的存储 worker 发出取消信号。

KB 的 PICTURE_WEB 返回 images_url 空数组及 images_ref 列表，每项保存 file_ref、image_ref、cite_index 和 tool_sign。原先筛选全空时展示原图的行为仅应用于本次成功授权并解码的图片，撤权/超时引用不能被恢复。前端与历史来源记录仍需接入新字段，本轮不能视作完整图片展示迁移。

## Memory 与反向回调

`/memory/store` 使用 `store_agent_memory`，接收 `AgentMemoryStore` 并返回 `AgentMemoryReceipt`。当前 Memory.search 由运行资源绑定中的 Runtime 工具执行，尚未暴露独立 HTTP search 操作。

Runtime 调用 Management 时使用 `ManagementOperation`，包括自动化提案、Memory 写入通知、Workbench Skill 挂载查询。NL2Agent 的草稿写入使用 `contracts/agentos_agent_creator.py` 中的专用带范围回调。Management 必须校验运行、租户、用户和被授权资源，不能因调用带有效服务签名就省略资源权限校验。

## 鉴权、错误与超时

### KnowledgeBase 文件生命周期

`KnowledgeSearch.expected_revisions` 可钉住知识库配置快照。提供时必须包含全部请求知识库 ID 与 SHA256 版本；Runtime 在每次授权中比对，配置变化返回冲突。普通即时查询可省略该字段。`file_ids` 用于限制返回的稳定文件 ID。

`KnowledgeSearch.file_versions` 可进一步固定文件版本，键必须与 `file_ids` 完全对应，值为非负整数。Runtime 在 top-k 前按文件 ID 和版本成对过滤，并核对结果。Management 的 `prepare_tool_files` 将精确对象路径解析为 `KnowledgeFileReference`；Runtime 工具组件使用 `file_refs` 接收这些引用，避免装配期间选中的文件被后续新版本替换。当前工具装配已使用此绑定，公开读写及历史数据仍按退役计划联合切换。

Runtime 的 `KnowledgeToolSearch` 按每个知识库绑定的模型 ID 和版本调用标准检索服务。单模型沿用原分数，多模型按排名融合，统一 rerank 经一次 `Model.invoke` 执行。固定文件白名单为空时拒绝全部文件，未指定时仅受知识库权限约束。必要知识工具实现位于 `runtime/knowledge_base/tool.py`，由 `sdk_tool.py` 注入标准检索能力；旧 SDK 知识工具文件已移除。Management 通过 contracts 获取纯目录信息，通过 Model.get/list 编译资源，Runtime 通过签名 AgentOS 重新核对 KB 授权。第 2 版绑定保存每库 embedding_models 和版本化 file_refs，拒绝第 1 版绑定。

新工具事件保留 typed file_ref、image_ref 和位置。来源下载与图片展示消费者、公开写入切换及历史索引迁移尚未完成，生产切换须按退役 SPEC 联合执行。

Management 使用会话来源记录的 knowledge_reference 保存这些身份。字段接受 file_ref、可选 image_ref 和 location，紧凑 UTF-8 JSON 上限 16 KiB；旧行及网页来源保持 NULL。新增迁移为 v2.9.0_018_knowledge_source_reference.sql，部署 Management 前须完成数据库基础表初始化并应用该迁移，镜像已包含它。批量投影、单条来源、会话分支和两处历史回读均保留引用，内容访问仍须当前用户和租户重新授权。前端展示接入尚未完成。

Runtime 已挂载以下内部接口。上传返回持久 `queued`，删除返回 `cleanup_pending`。上传和文本向量删除 worker 已接入 Runtime lifespan，文本检索及 rerank 已有标准接口。图片及 Management 对象清理仍在迁移，当前公开入库和旧 SDK 检索尚未切换。

| 用途 | AgentOS 路径 | 客户端方法及契约 |
| --- | --- | --- |
| 接纳已完成清洗的文件 | `/internal/agentos/v1/knowledge/files/upload` | `upload_knowledge_file(KnowledgeFileUpload, user_id, tenant_id)`，返回 `KnowledgeJobState`，HTTP 202 |
| 查询原用户、租户及文件版本的任务 | `/internal/agentos/v1/knowledge/files/inspect` | `inspect_knowledge_file(KnowledgeJobLookup, user_id, tenant_id)`，HTTP 200 |
| 提交逻辑删除及清理义务 | `/internal/agentos/v1/knowledge/files/delete` | `delete_knowledge_file(KnowledgeFileDelete, user_id, tenant_id)`，HTTP 202 |
| Runtime 查询 Management 的实时资源授权 | `/internal/agentos/v1/knowledge/authorize` | `authorize_knowledge(KnowledgeAuthorizationRequest, user_id, tenant_id)`，返回 `KnowledgeFileGrant` |
| 文本检索与重排 | `/internal/agentos/v1/knowledge/search` | `search_knowledge(KnowledgeSearch, user_id, tenant_id)`，返回 `KnowledgeSearchResult`，HTTP 200 |
| Runtime 查询 Management 的 KB 读权限 | `/internal/agentos/v1/knowledge/authorize-search` | `authorize_knowledge_search(KnowledgeSearchAuthorization, user_id, tenant_id)`，返回 `KnowledgeSearchGrant` |
| Runtime 查询来源/图片只读授权 | `/internal/agentos/v1/knowledge/authorize-content` | `authorize_knowledge_content(KnowledgeContentRequest, user_id, tenant_id)`，返回 `KnowledgeContentGrant` |
| 删除已排空的 KB 物理集合 | `/internal/agentos/v1/knowledge/bases/delete` | `delete_knowledge_base(KnowledgeBaseDelete, user_id, tenant_id)`，返回 `KnowledgeBaseDeleteState`，HTTP 202 |
| 核对 KB 集合删除结果 | `/internal/agentos/v1/knowledge/bases/inspect` | `inspect_knowledge_base_deletion(KnowledgeBaseDeleteLookup, user_id, tenant_id)`，HTTP 200 |
| Runtime 查询整体删除授权 | `/internal/agentos/v1/knowledge/authorize-base-deletion` | `authorize_knowledge_base_deletion(KnowledgeBaseDeleteAuthorization, user_id, tenant_id)`，返回 `KnowledgeBaseDeleteGrant` |

KB 集合删除请求只接受 knowledge_id 与 idempotency_key，查询使用 knowledge_id 与稳定 job_id。Management 核对当前编辑权限、KB 删除意图原用户和全部文件的精确 full 删除终态，Runtime 再检查自己的 writer 已结束且文件墓碑覆盖最后版本、可见指针已清空。物理索引名及模型维度不由请求提供，不需要模型推理。

Runtime 先持久预留一次删除，再通过 Infrastructure 的 StorageInterface 检查整个物理集合为空并删除。普通文件写句柄没有删除集合的权限。重复请求和 inspect 只观察集合是否不存在，未知结果不重发；集合仍存在则保持 cleanup_pending。只有确认不存在才能返回 deleted 与 physical_cleanup_complete=true。每次调用共享十秒总截止，超时关闭 HTTP 并取消后续存储提交。部署前由 Management 应用 SQL 027，Runtime 保持 SQL 启动模式 off。当前公开 KB 整体删除编排、共享产物和最终元数据清理仍待接通，不能以此接口视作完整退役。

`KnowledgeContentRequest` 携带 knowledge_id、file_id、file_version。不传 image_ref 时读取该版本的来源；传入时必须是该文件已完成清洗 manifest 中的精确图片引用。Management 检查当前用户和租户的 KB 读权限、文件版本、来源及 manifest 成员，返回 object_ref 和 filename；授权不包含凭据或任意对象前缀。Runtime 的 `KnowledgeContentReader` 在同一截止内获取授权、经只读 ObjectStore 校验版本/hash 并读取、再复核授权，权限或来源变化时不返回字节。该过程不调用普通文件 HTTP，不增加重试。

Management 的公开 `POST /api/file/knowledge/content` 接收同一 typed 请求，来源以 attachment 返回，图片以 inline 返回，均禁止缓存。前端 typed 引用消费和 Runtime 图片筛选仍需接入；旧 URL 消费者尚未全部撤除。新接口不能读取缺少固定 source revision/hash 的历史文件，历史维护按退役计划处理。

文件生命周期和 search 发往 Runtime，两种授权查询发往 Management，均复用 `AgentOSClient` 的方向隔离签名。Management 校验当前 DAC、源代次与已完成清洗任务，返回固定对象引用、文件名、逻辑集合及 KB 模型 ID。Runtime 校验 grant 和实际模型 revision 后接纳，不读取 Management 业务表。上传要求已有确认产物；新建幂等键不能绕过版本或删除墓碑。

KB 文件生命周期及授权客户端有十秒总截止，connect/read/write/pool 分别为 5/10/10/5 秒，连接关闭属于这次请求的所有者，不自动重试。Runtime 接纳与 Management 授权各自也有十秒服务预算。未知写入返回 `KNOWLEDGE_OUTCOME_UNKNOWN`，调用方应保留原幂等身份核对状态。`physical_cleanup_complete=false` 不能解释为物理数据已清空。

`File.inspect` 返回可空的 `processed_chunks` 和 `total_chunks`。Runtime 准备好切片后固定总量，每批向量写入确认后更新数量；未知写入不增加计数。数量达到总量仍须检查任务 `status`，它不表示文件已发布或物理清理完成。inspect 保留原用户、租户及资源授权校验。Management 的原用户协调任务保存这些观测，公开列表读取投影的接线仍在退役计划中，不能改用其他知识库读者身份查询原任务。

对 `File.delete` 产生的任务，只有 `status=deleted` 且 `physical_cleanup_complete=true` 时，两个计数才表示本次确认移除的覆盖版本向量数，此时二者相同。Runtime 先确认覆盖写入方已结束，再计数、执行一次删除并确认剩余为零，计数与删除终态一起持久化；重复 inspect 返回同一结果。未知结果不补零，也不重发删除。Management 将确认数单独保存为 `deleted_vector_count`，保留原文件的上传进度；`source_only` 不调用 Runtime 删除。

部署该状态快照前执行 SQL 022，再升级 Management，最后升级 Runtime。新列允许空值，历史行保持未知；回滚先 Runtime、后 Management，保留新增列。

文本 search 的客户端与 Runtime 各有 180 秒总截止，包含授权、embedding、存储、rerank 和最终可见性检查。`search_mode` 支持 accurate、semantic、hybrid，默认 semantic；指定 `rerank_model` 才执行重排，使用既有十倍候选常量。accurate/hybrid 的文本分支沿用原分词加权、短语/模糊匹配及同次查询高亮，失败不回退普通 text。所有模型调用进入 `ModelService.invoke`，非法重排结果直接报错。Runtime 在重排前及返回前核对权威 generation，不能返回已删除或未发布的向量。结果 `score_details` 包含适用的 accurate/semantic 归一化分量和 retrieval_highlight_terms，重排后仍保留这些检索信息。

```python
result = await runtime.search_knowledge(
    KnowledgeSearch(
        knowledge_ids=[knowledge_id], query=query, top_k=3,
        search_mode="hybrid",
        embedding_model={"model_id": embedding_id, "revision": embedding_revision},
        rerank_model={"model_id": rerank_id, "revision": rerank_revision},
        file_ids=[],
    ), user_id, tenant_id,
)
```

同一请求的 KB 必须绑定同一 embedding ID；不同模型由 Management 分组调用。新接口当前面向原租户的本地 Elasticsearch KB，普通文件使用内容全文字段；历史数据若有 title，需在维护迁移中显式声明对应全文 schema。默认映射不会隐式更改。图片与源文件引用卡片仍需随消费者和历史数据迁移完成对照，不能把文本接口验证视为旧 SDK 已切换。

`KnowledgeUploadWorker.process(lookup, actor, owner_id=...)` 执行已接纳的任务。装配方显式提供源与产物大小上限，并安装 Runtime 的 `ThreadManager`。worker 经 Management 实时授权后领取 attempt，读取固定版本对象，再通过 `ModelService.invoke` 写入显式向量；每批写前复查授权和 owner。只有全部写入确认并仍持有有效 attempt 时才发布可见 generation，已完成任务再次投递不会调用模型。在途或 unknown 写入保留清理义务，不自动重跑。

Runtime lifespan 从持久任务表发现新上传，每轮最多 100 项，按原用户和租户依次执行。发现端口仅返回调度元数据，只选尚未开始且无未知义务的 `queued`，不扫描 `running` 或失败任务。空闲发现间隔为一秒，异常使调度退出并将 `/health/ready` 标为 503，不自动重试或重启。关闭时先标记取消，再等待 owned task，最后排空现有线程管理器。源和产物上限共用 `MAX_KNOWLEDGE_FILE_SIZE_MB`，单次执行截止采用现有 `DP_SPLIT_WAIT_TIMEOUT_MAX_S`，当前支持至 3600 秒。

同一调度器也发现未开始的 `cleanup_pending` 删除，仅选择覆盖 upload writer 均已结束的任务。`KnowledgeDeleteWorker` 经 Management 授权后持久记录删除 owner/attempt，再通过不依赖模型维度的 VectorStore 维护句柄执行一次过滤删除和数量核对。过滤包含 KB、文件及版本上限；确认无残留并重新校验授权后才标为 `deleted`。partial、unknown、取消、撤权或非零残留均保持待核对状态，不自动重放。它只清理 Runtime 文本向量，源对象及清洗产物仍归 Management。

新向量句柄把逻辑 collection 映射到固定 `si-kb-` 命名空间。旧索引会保留，历史数据迁移和核对仍是生产切换前置条件，当前不会自动回退查询旧索引。

`AgentOSClient` 对 JSON body、operation、user_id、tenant_id 生成服务签名。双方用 JWT_SECRET 派生不同方向的 HMAC 密钥，token 有效期为 30 秒，绑定 issuer、audience、operation 和 body hash。客户端自动签名，业务代码不应自己拼 token。Gateway 外部用户 token 不直接替代 AgentOS 服务身份。

客户端禁用重定向，请求体上限为 8 MiB。没有签名或签名不匹配返回 401，结构错误通常返回 422，归属不匹配按具体公开合同返回 403 或 404。资源版本冲突、运行冲突和过期游标按接口各自的 409、410 合同处理；不要统一吞成 500。

连接错误转换为 RuntimeServiceUnavailableError，超时转换为 RuntimeServiceTimeoutError，上游非成功 JSON 响应使用 RuntimeUpstreamError 保留状态、响应体和必要响应头。Management HTTP 层负责对外映射，SSE 已建立后的错误按事件合同处理。

普通 JSON 请求默认 connect/read/write/pool 分别为 10/30/30/10 秒，Model.invoke 的 read 为 180 秒。SSE 建连至响应头返回还受 AGENTOS_STREAM_OPEN_TIMEOUT_SECONDS 总截止控制，默认 60 秒；响应头返回后的 SSE read 没有统一空闲超时，避免截断正常长流。评估执行使用单独的长请求策略，不应将它误写为普通 JSON 的 30 秒读截止。调用方还应遵守自身任务截止与取消要求。

## 当前保留项与后续工作

`legacy_resume.py` 仍承接旧数据的只读续传，Management 的历史消息适配与后台来源恢复也仍有调用方。它们不允许启动旧进程内 Agent。无调用方的 legacy admission/tracking/producer、Management 混合执行链、LegacyRunFactory 和旧工作区实现已删除。

Management 源/产物清理、KB 多模态入库、旧检索语义对照及业务入口切换仍待完成。文件 upload/inspect/delete 和文本 search 已有内部接口，上传及文本向量删除的发现和 lifespan 已验证，尚未完成整个知识入库流水线迁移。data-process 仍单独运行，完整退役继续按独立规格实施。

普通与 Northbound 文档删除已统一进入 Management 的持久删除协调器，公开路径和参数保持。full 经标准 File.delete/inspect 确认 Runtime 向量清理，再等待本地清洗排空、源对象与账本终态；source_only 保留 Runtime 向量和文件身份。公开调用共用十秒预算，提交结果未知时返回 pending，后续只查询固定任务，不自动重发。Northbound 响应适配由 northbound service 负责。旧源和旧 ES 数据仍需先完成退役 SPEC 的历史迁移，未经核实的历史文件在接纳前拒绝；当前切换不能作为历史清理完成的证明。

Management 的 KB 上传批次已通过 StorageInterface 原子接纳，上传更新并锁住 KB revision 后复核删除意图，合法并发上传顺序提交。KB 删除意图只保存在 Management；标准授权拒绝新的执行与读取，文件 delete/inspect 和清洗取消仍按当前资源权限完成清理，没有新增 AgentOS operation。KB 整体删除的公开执行链仍待切换，删除意图和上传接纳的并发证明不能替代整个 KB 的物理清理验收。

规范位于独立文档目录 `nexent-doc/docs/Developing/four-service-runtime-decoupling/changes/management-agentos-service-boundaries/`，部署过程见该目录的 `independent-service-deployment.md`。新增接口先修改中立契约、调用双方及回归验证，完成消费者迁移后删除旧实现。
