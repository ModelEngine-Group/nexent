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
| 获取模型元数据 | `/model/get` | `ModelReference`，返回 ID、类型、revision 和可选 embedding_dimensions，不返回供应方密钥 |
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

新 KB 清洗产物保存在 `knowledge-cleanse/{knowledge_id}/{file_id}/{file_version}/{job_id}/` 专属目录，目录内继续使用 artifacts/images 与内容哈希。Management 的执行器和隔离工厂共用 `cleanse_lookup(row, request)`，在解析前核对完整接纳快照；`KnowledgeCleanseLookup` 与 run lookup 共用严格的 `cleanse_output_prefix`。Runtime 依据可信 manifest 读取精确图片，Management 核对当前 DAC、文件版本、清洗 job 和 manifest 成员。相同源在其他文件或任务中使用不同对象键。已有共享产物按固定引用继续读取，清理归 P4 历史维护，单文件删除没有共享对象删除权限。

KB 专属目录回收已接入 `DELETE_CLEANSE_PENDING`，必须先确认 Runtime 删除完成、解析执行结束，再在当前资源权限下校验完整对象清单，以任务 revision 保留一次物理删除。结果未知后仅查询目录，确认不存在才标记 `released` 并允许源文件清理。原任务 user_id 保持不变，审计记录实际编辑者。重复图片保留所有位置块，只上传一次固定版本。部署本批前由 Management 应用 SQL 028，任务表的 artifact_prefix 保存执行前固定的目录，旧行保持 NULL；Runtime 继续 off。历史共享对象、未知原写入或未确认执行结束的任务保持 pending，由 P4 核对，不自动重发或清除未知标记。

`source_only` 完成后，图片授权从已确认的删除意图取得固定来源证明，再核对同文件版本的已完成 manifest 和精确图片引用。当前读者仍须满足用户、租户和 KB 读权限，原删除用户不代替当前身份。已删除的源文件继续拒绝读取；full 删除、KB 删除中、软删除、未完成的源删除或原清洗结果未知也不授予图片读取。共享与专属产物的只读约定保持，回收时若 artifact 引用与已记录的专属目录不一致，会在对象操作前拒绝。

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
| Runtime 查询分块浏览只读授权 | `/internal/agentos/v1/knowledge/authorize-chunks` | `authorize_knowledge_chunks(KnowledgeChunksAuthorization, user_id, tenant_id)`，返回 `KnowledgeChunksGrant`，无模型配置依赖 |
| 分页浏览已发布分块 | `/internal/agentos/v1/knowledge/chunks` | `knowledge_chunks(KnowledgeChunks, user_id, tenant_id)`，返回 `KnowledgeChunksResult`，HTTP 200 |
| 查询真实分块写目标 | `/internal/agentos/v1/knowledge/chunks/inspect` | `inspect_knowledge_chunk(ChunkMutationLookup, user_id, tenant_id)`，返回 `ChunkMutationTarget`，元数据总预算10秒 |
| 接纳并执行单键分块写入 | `/internal/agentos/v1/knowledge/chunks/mutate` | `mutate_knowledge_chunk(ChunkMutationIntent, user_id, tenant_id)`，返回 `ChunkMutationState`，总预算180秒 |
| Runtime 查询实时分块编辑授权 | `/internal/agentos/v1/knowledge/authorize-chunk-mutation` | `authorize_knowledge_chunk_mutation(ChunkMutationAuthorization, user_id, tenant_id)`，返回精确 `ChunkMutationGrant` |
| Runtime 查询来源/图片只读授权 | `/internal/agentos/v1/knowledge/authorize-content` | `authorize_knowledge_content(KnowledgeContentRequest, user_id, tenant_id)`，返回 `KnowledgeContentGrant` |
| 删除已排空的 KB 物理集合 | `/internal/agentos/v1/knowledge/bases/delete` | `delete_knowledge_base(KnowledgeBaseDelete, user_id, tenant_id)`，返回 `KnowledgeBaseDeleteState`，HTTP 202 |
| 核对 KB 集合删除结果 | `/internal/agentos/v1/knowledge/bases/inspect` | `inspect_knowledge_base_deletion(KnowledgeBaseDeleteLookup, user_id, tenant_id)`，HTTP 200 |
| Runtime 查询整体删除授权 | `/internal/agentos/v1/knowledge/authorize-base-deletion` | `authorize_knowledge_base_deletion(KnowledgeBaseDeleteAuthorization, user_id, tenant_id)`，返回 `KnowledgeBaseDeleteGrant` |

KB 集合删除请求只接受 knowledge_id 与 idempotency_key，查询使用 knowledge_id 与稳定 job_id。Management 核对当前编辑权限、KB 删除意图原用户和全部文件的精确 full 删除终态，Runtime 再检查自己的 writer 已结束且文件墓碑覆盖最后版本、可见指针已清空。物理索引名及模型维度不由请求提供，不需要模型推理。

Runtime 先持久预留一次删除，再通过 Infrastructure 的 StorageInterface 检查整个物理集合为空并删除。普通文件写句柄没有删除集合的权限。重复请求和 inspect 只观察集合是否不存在，未知结果不重发；集合仍存在则保持 cleanup_pending。只有确认不存在才能返回 deleted 与 physical_cleanup_complete=true。每次调用共享十秒总截止，超时关闭 HTTP 并取消后续存储提交。部署前由 Management 应用 SQL 027，Runtime 保持 SQL 启动模式 off。普通及 Northbound KB 删除已接入父协调器和最终 SI 元数据事务，未确认完成复用原 KNOWLEDGE_DELETE_BLOCKED；PRIVATE 删号已使用目的授权入口；租户共享本地 KB 已接入独立 SU 目的授权；DataMate 本地关联另用停用前 SI 事务清退；历史共享产物和完整退役验收仍待完成。

PRIVATE 删号使用服务器保存的专用清理授权。首次接纳通过有限 SI 身份投影验证实际管理员和目标用户，持久记录实际 user_id、其原租户、目标 owner、purpose 及精确 KB。已接纳命令可以在身份停用后继续，只授予该 KB 的 cleanup/edit 清理及精确 full 删除状态查询，普通读取、编辑、上传和检索仍执行原 DAC。File.inspect 还须匹配原执行用户、文件/代次、对象和来源；返回 source=None，不能借查询状态读取源内容。AgentOS 的 user_id 保持实际管理员，tenant_id 明确绑定此次委派的资源租户；原管理员租户留在 Management 的内部快照中，不把目标用户写为执行身份。Runtime 仍调用原 File.delete/inspect 和 KB 授权接口，不接收或创建该授权快照。用户删号先通过 SI 分页选择目标用户在指定租户创建的本地 PRIVATE KB，并准备目的授权，随后停用成员、撤销凭据，再推进已接纳命令。租户删除在批量停用前准备全部用户的计划，PRIVATE 及已有删除意图的 KB 不再由原生软删移除。内部汇总将 pending 单列，只有持久终态确认才计成功。现有 Management 生命周期循环用独立父游标继续发现清理，要求目标账号和成员均已停用且无相应活动记录；读取调度身份后仍由原协调器复查授权，没有新的轮询任务或重试机制。选择失败保留原删号 best-effort 语义并记录错误，未接纳的历史孤立资源留待部署前维护核对。租户共享本地 KB 使用独立 tenant_cleanup，不能扩大 PRIVATE grant。

租户删除对共享本地 KB 使用独立的 tenant_cleanup。首次接纳要求实际活动 SU、目标租户以及共享 EDIT/READ_ONLY 权限和 elasticsearch 来源，创建者可以已离开租户。两种清理 scope 互斥，普通删除和 PRIVATE 入口不能接管共享命令。租户流程在批量停用前准备全部授权，随后推进已接纳计划；后台发现要求目标租户已无活动成员，复用同一父协调器和原生命周期循环。KnowledgeCleanupPlan 与 execute_cleanup 共用准备结果和终态统计，PRIVATE/tenant 准备入口仍分离，空 PRIVATE owner 直接拒绝，没有兼容别名。DataMate 本地目录在身份停用前另用 SI 事务清退，不发送本地集合删除；未知权限和历史孤立资源继续留待部署前维护核对。

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

`KnowledgeBase.sample` 的内部路径为 `/internal/agentos/v1/knowledge/sample`，客户端为 `sample_knowledge`。请求包含 `knowledge_id`、`expected_revision` 和 `document_limit`，文档数默认为 200，范围为 1 至 200。`expected_revision` 来自当前 Management 知识资源授权，避免摘要跨越资源配置变化。该入口复用标准知识库读取授权，始终传实际读取者和租户。

Runtime 对权威可见文件做蓄水池抽样，通过 StorageInterface 的 `VectorStore.scan` 逐页读取已存向量。响应包含 `knowledge_revision`、`data_revision`、`embedding_model` 和 `documents`。每个文档携带版本化 `file_ref`、文件名以及按 `chunk_index` 排序的完整分块，分块含原文、embedding 和 location。分块数必须与已完成 job 的发布计数一致；旧 generation 被过滤，缺片、资源版本变化或读取期间可见 manifest 变化均报冲突，不返回部分成功，不重试或切回旧索引。样本入口不会调用 embedding 或 LLM。

`data_revision` 是当前全部可见文件版本、generation 和发布 job 的摘要，覆盖未被抽中的文件。分页使用逻辑键游标，不承诺数据库快照隔离，Runtime 返回前重新核对可见集合和当前授权。Runtime 总截止与客户端总截止均为 180 秒，单次 ES 请求最多 5 秒且禁用驱动重试；HTTP 超时会取消请求并关闭客户端。向量扫描游标绑定实际 actor、租户、集合、schema/维度与过滤条件，不能用于其他范围。

Management 手动摘要已切换到 `KnowledgeSummaryService`。它通过 SI 查询当前租户下的 index_name，核对实际用户的编辑权限，再调用 `sample_knowledge`。样本必须匹配知识资源 revision、模型 ID 和文件范围，返回后及模型阶段结束后都复查权限。原内容长度加权向量、KMeans、文档 100 词与簇 150 词 MapReduce 保留在 Management，所有模型请求继续使用 Model.invoke。旧 `ElasticSearchService.summary_index_name` 已无调用方并删除。

公开 `/{index_name}/auto_summary` 的 batch_size、model_id、认证与 SSE 事件保持。原 VDB 依赖隐式暴露的 db_type、tenant_id 查询参数仍被校验，tenant_id 不覆盖登录租户。DataMate 原 search 明确不支持原始查询，本次保持失败，不增加其他读取路径。逐字 success、completed 和 error 事件采用 JSON 序列化，保留原文中的引号、换行与反斜杠。

自动摘要仍有旧 ES 取样与 data-process 调度调用，继续按退役 SPEC 迁移其实际启用者、版本接纳和受管生命周期。发布前仍需完成 P4 历史源与旧索引维护，不能直接把旧 ES 数据当作 Runtime 已发布文件。先部署 Runtime 样本操作并确认维护完成，再切换 Management 消费者，回滚先消费者。当前没有新增公开摘要路径或备用协议，整个 data-process 退役尚未完成。

自动摘要设置现经 SI 保存实际设置者。原 `PATCH /indices/{index_name}/summary_frequency` 的请求与成功响应保持，当前用户须有 KB 编辑权限；允许先设置频率再配置 embedding 模型。执行接纳另行要求本地 KB 和有效 embedding ID。SQL 029 在原 KB 行增加可空 `summary_schedule`，保存配置 ID、实际 user_id 与最后一次数据版本工作，不保存供应方配置。修改频率、关闭或重新启用均保留最后 attempt，当前相同 data_revision 不重复接纳；新数据版本可形成新工作。`admitted` 表示已接纳但结果尚未确认，重启不回放，`completed` 和 `failed` 有明确终态时间。摘要、last_summary_time 和 completed 状态在同一 SI 事务提交。

历史频率没有可信启用者时保持 NULL 快照，须在 P4 核对或由实际用户重新设置，不使用创建者或最后更新者代替。失败记录只允许原已接纳 attempt 的实际用户关闭，撤权后不能发布摘要。当前已交付设置、持久接纳和受限候选发现，旧自动执行器尚未接入这些能力，仍需迁入 Management lifespan 后移除 data-process 中的启动/关闭调用及旧 ES 取样。部署需先应用 SQL 029，完成全部 Management 写入方升级及 P4 维护，再切换执行归属；不能同时运行旧调度和新调度。

`legacy_resume.py` 仍承接旧数据的只读续传，Management 的历史消息适配与后台来源恢复也仍有调用方。它们不允许启动旧进程内 Agent。无调用方的 legacy admission/tracking/producer、Management 混合执行链、LegacyRunFactory 和旧工作区实现已删除。

Management 源/产物清理、KB 多模态入库、旧检索语义对照及业务入口切换仍待完成。文件 upload/inspect/delete 和文本 search 已有内部接口，上传及文本向量删除的发现和 lifespan 已验证，尚未完成整个知识入库流水线迁移。data-process 仍单独运行，完整退役继续按独立规格实施。

普通与 Northbound 文档删除已统一进入 Management 的持久删除协调器，公开路径和参数保持。full 经标准 File.delete/inspect 确认 Runtime 向量清理，再等待本地清洗排空、源对象与账本终态；source_only 保留 Runtime 向量和文件身份。公开调用共用十秒预算，提交结果未知时返回 pending，后续只查询固定任务，不自动重发。Northbound 响应适配由 northbound service 负责。旧源和旧 ES 数据仍需先完成退役 SPEC 的历史迁移，未经核实的历史文件在接纳前拒绝；当前切换不能作为历史清理完成的证明。

Management 的 KB 上传批次已通过 StorageInterface 原子接纳，上传更新并锁住 KB revision 后复核删除意图，合法并发上传顺序提交。KB 删除意图只保存在 Management；标准授权拒绝新的执行与读取，文件 delete/inspect 和清洗取消继续使用资源授权，没有新增 AgentOS operation。普通及 Northbound 的整体删除门面已经切换；PRIVATE 删号入口已迁移，旧全量删除、旧源对象清理及重复清理开关已移除。未知来源的历史关联清退和最终部署仍待完成，删除意图及上传接纳的并发证明不能替代整个 KB 的物理清理验收。

规范位于独立文档目录 `nexent-doc/docs/Developing/four-service-runtime-decoupling/changes/management-agentos-service-boundaries/`，部署过程见该目录的 `independent-service-deployment.md`。新增接口先修改中立契约、调用双方及回归验证，完成消费者迁移后删除旧实现。


DataMate 目录属于 Management 的本地关联，远端仍拥有内容。租户删除在批量停用之前，以实际活动 SU 调用 unlink_datamate_for_tenant。每项 SI 事务锁住 KB revision，检查目标租户、datamate 来源、无既有父删除意图、无活动本地文件和 COMMITTED 账本，然后清除本地知识绑定、标签/投影并软删目录；创建者和 AIDP 关联保持原值。账本句柄只有读取权限，普通 KB 最终事务默认不增加该命名空间。事务失败会回滚全部本地改动，结果不明仅记录 pending，不自动重写。流程没有 Runtime/远端数据删除请求、新任务表或持久授权。DataMate provider 的原生 upsert/列表同步仍须在存储旁路整改中迁移。


用户通过原文件 process 接口显式再次处理新链 FAILED 文件时，Management 先 inspect 旧清洗/Runtime任务，确认终态、执行已结束、无待核对写入，以及清洗产物归属明确，再单次 CAS 接纳 processing_attempt+1。source_generation、源对象revision/hash保持不变，任务ID换新，旧进度与错误清空。进行中与已完成请求继续复用原意图；后台不会自动重试失败文件。旧执行用户不同、历史意图不完整、404或闭合信息缺失都拒绝重处理，不借其他用户身份查询旧job。

KB清洗状态补充 execution_ended、reconcile_required、artifact_ownership_known，Runtime File.inspect补充 writer_ended、reconcile_required。它们是可空严格布尔值，缺失表示未知。Runtime upload同时拒绝旧writer仍需reconcile的同版本替换。已确认、仍由旧job精确归属的局部对象保留到正常File.delete统一清理，不声称物理删除完成；未知历史义务留待维护。升级先完成全部Management实例，再升级Runtime，回滚先Runtime后Management，避免旧严格解析器收到新增字段。没有新AgentOS operation、SQL或公开请求参数。

模型的 `embedding_dimensions` 表示 Runtime 已配置的向量维度。`Model.get` 与 `Model.list` 使用同一规则，embedding 和 multi_embedding 从现有模型配置读取正整数，缺失或无效时返回 null；其他模型类型返回 null。该字段不代表已探测提供商输出。Management 可以将它与旧索引维度核对，无须读取 Runtime 数据库。实际摄取继续校验模型版本及配置维度，缺失值保持原有错误，不选择备用模型。内部响应增加字段仍遵循先升级Management、再升级Runtime的顺序，旧严格解析器不能先接收新Runtime响应。
### KnowledgeBase 已发布分块分页

`KnowledgeBase.chunks` 使用内部路径 `/internal/agentos/v1/knowledge/chunks`，客户端方法为 `knowledge_chunks`。请求包含 `knowledge_id`、当前授权的 `expected_revision`、非负 `offset` 和 1 至 1000 的 `limit`。后续页可携带首轮返回的 `expected_data_revision`，可见文件集合变化时返回冲突。可选 `file_ids` 接受唯一稳定文件 ID，省略表示全部，空列表表示不选择文件。Runtime 只选择各文件当前可见版本，允许上传新版本期间浏览上一已发布版本。

结果包含资源版本、数据版本、`total`、`chunks` 和 `next_offset`。每个分块返回文件引用、逻辑 `chunk_id`、`chunk_index`、文件名、正文和 location，不返回 embedding 或模型配置。Runtime 通过 StorageInterface 读取已发布 manifest 和完成的上传任务，按发布计数计算总数，只扫描分页所需的分块区间，过滤旧 generation 与已删除文件。模型标识仅与原已完成 job 核对，不再查询模型管理。缺片、重复、版本变化和撤权均拒绝结果，不重试、不调用模型推理。沿用读取操作的 180 秒总截止和 ES 单请求 5 秒无重试限制。

Runtime 使用标准 `authorize-chunks` 回调获取 Management 的 `KnowledgeChunksGrant`，其中只含 KB、集合、资源租户及 revision。Management 按实际调用者的活动账号、租户成员和原 own/shared DAC 授权，拒绝 KB 删除意图；无需 embedding 模型配置。Runtime 的只读 SI 端口限定该 KB 与资源所属租户，actor_id 仍为实际用户。签名 user_id/tenant_id 始终保持原请求身份，不使用创建者身份，也不扩大为跨租户模型或写入权限。

普通及 Northbound 的原分块浏览已调用该入口。Management 将文件身份还原为原路径、创建时间及公开字段，同时保留 page/page_size、path_or_url 和响应格式。公开 page/page_size 同时提供才分页，单次内部窗口最多 1000；返回前复核资源与文件映射，整个操作最多 180 秒。北向适配位于 northbound service。普通 db_type=datamate 继续返回原远端文件清单，由 `get_external_file_chunks` 适配；ES 路径没有旧索引回退。公开分块写入已迁入AgentOS；旧 documents 向量化入口和通用权限仓库旁路仍待迁移，整个 data-process 退役未完成。

### KnowledgeBase 手工分块写入

Management 保留原公开路径、metadata 非null覆盖、默认时间和响应ID。创建先按真实存储键查询目标，删除允许显式 `resolve_public_id=true`，按原规则先查真实键，再匹配source展示ID。`ChunkMutationTarget` 返回当前分块、真实文件引用、generation和change_epoch；Management将这些绑定传入写意图的 `file_ref`、`generation`、`chunk_index` 和 `expected_change_epoch`。新建计数+1，已有键覆盖0，删除-1。创建响应返回实际存储键，删除响应保持原请求路径ID。

创建的 `changes` 使用 `ChunkCreateData`。`content` 可以保留metadata覆盖后的原始JSON，`embedding_input` 始终传原请求文本。`embedding_model` 可以指定固定的 `{model_id, revision}`，或只传 `{model_id}` 由Runtime通过Model.get固定版本，再执行Model.invoke。`supplied_embedding` 承载原metadata提供的向量；模型成功时生成结果覆盖它，原无模型或模型失败时才使用它，没有显式向量则保存正文。实际使用的空向量、零向量或畸形向量拒绝，不转换为正文，不选择其他模型。资源权限或SI读取失败始终阻止写入。

原始source放在location的 `nexent_public_chunk_v1`，不重复保存content或embedding。它可保留原metadata中的展示ID、数组filename和自定义字段；公开浏览仍只返回原九字段。可信执行身份来自独立的KB/file/generation字段，SI审计使用实际actor。带路径浏览对显式source路径先筛选再分页，未设置source时使用原文件映射，因此文件分块的路径覆盖也能按原值查询。此分支需要扫描当前文件元数据，仍受总预算和epoch限制。

Runtime按Management的实时编辑grant执行，创建在模型调用后再次授权。普通及共享资产写入保持原签名user_id/tenant_id，SI namespace可由精确grant选择固定资产租户，审计用户不替换。公共适配的180秒总预算包含元数据与两次AgentOS HTTP；超时取消，未完成或未知回执不返回成功，也不重试或重放。

Runtime标准 `update` 已支持 `changes.embedding` 与正文/payload的同次条件替换。缺少embedding字段时只patch payload并保留原向量；显式向量需要非空、非零且数值有限，使用已有VectorStore.put并核对业务generation，计数为0。纯正文集合可补齐匹配的向量映射。可信文件身份及既有模型绑定保持，不调用模型，不将缺失键转成create；未知结果只返回原状态，不重放。

公开更新已通过 `update_manual_chunk` 使用同一标准写链。Management执行原ES doc递归对象合并，数组和标量替换，顶层metadata null忽略，嵌套null保留。更新先按真实键/展示ID查询目标，响应保持实际存储ID；原审计展示值可被metadata覆盖，SI审计仍实际actor。旧静态create/update/delete方法均已移除。缺少原始source的发布文件从授权文件映射还原路径和时间，metadata不能改可信文件身份。

用户显式提供的手工向量可以没有模型标签。语义检索允许两个模型标签均空且有当前已确认手工create来源的实际KNN命中，继续检查当前文件、代次、epoch和集合维度。固定标签按原ID/版本规范化规则匹配，其他已声明模型不进入这个手工分支；不会补写模型标签或改用另一模型。纯正文没有KNN命中，无来源/已删除记录也不返回。采样复用同一确认来源规则保留未标注模型的真实手工向量，继续为原摘要算法提供已存向量，不补标签或重新推理。

共享资产的标准搜索namespace还需补齐，当前KnowledgeSearchGrant没有资源租户且搜索端口使用调用者租户；共享写入验证不代表共享检索完成。历史旧索引、旧documents/search_hybrid及其他存储旁路仍需按退役SPEC迁移，最终镜像和完整部署验收继续待完成。

### KnowledgeBase 已登记文件清单

`KnowledgeBase.inspect` 的内部路径为 `/internal/agentos/v1/knowledge/bases/state`，客户端方法为 `inspect_knowledge_base`。请求 `KnowledgeBaseInspect` 固定 `knowledge_id` 和当前授权的 `expected_revision`，`page_size` 范围为1至1000，后续页原样传回 `cursor`。它与已有 `File.inspect`、删除协调状态查询分别服务不同场景。

返回 `KnowledgeBaseState` 包括资源版本、全量 `manifest_revision`、当前配置的 `embedding_model_id` 和一页文件状态。每项报告最新接纳版本、可见版本及代次、删除水位、记录版本与上传任务引用是否存在。上传引用可能在任务完成后保留，不能据此判断任务正在运行。清单包含未发布或设有删除水位的活动登记记录，不读取正文、模型、ES或对象存储，不证明物理向量完整。

Runtime用实际签名身份在读取前后重新请求Management授权。全量清单参与两次摘要核对，游标绑定实际user/tenant、KB资源版本与全量manifest版本，变化拒绝继续且不自动重试。游标只表示读取位置，不授予权限，不声称跨服务数据库事务快照。Management维护命令 `inspect-runtime` 另外读取 `Model.get` 的版本与配置维度，保留缺失模型/维度问题及 `migration_ready=false`。
### 历史文件显式重建

维护命令 `management.maintenance.migration` 的 plan/admit/execute/restore 复用现有Management摄取流程，未增加AgentOS执行接口。计划与接纳先核对实际操作者的current edit DAC，通过 `Model.get` 固定模型、通过 `KnowledgeBase.inspect` 确认目标文件尚未登记。执行继续使用本地清洗与标准AgentOS File.upload/inspect，保留原file_id及source_generation。

Management的 `KnowledgeIngestionIntent.legacy_snapshot` 只保存历史状态和审计，不随子请求发送。普通意图没有该字段时序列化形状保持不变。显式失败重处理保留既有迁移快照。旧任务引用、非canonical ID、缺失或未固定源仍拒绝接纳；维护前必须先停旧接纳并排空旧worker。仅INGEST_ACCEPTED且尚未预约子执行时允许SQL状态撤销，完整执行后的回滚仍需单独验证。

历史迁移维护入口增加只读 `management.maintenance.migration inspect`。它在当前实际用户 edit DAC 下通过 StorageInterface 核对已有计划回执，不要求 Runtime 在线，不调用模型或重新提交任务。旧任务盘点会跳过已确认的新摄取任务引用，无法解析的意图单独计数，避免把 AgentOS 任务误归入 Celery。


Model.get 与 Model.invoke 的执行配置读取现使用 Runtime 专用只读 StorageInterface RecordStore。ModelService 向读取函数传入实际签名 user/tenant 和同一 OperationContext，模型路由、KB 默认模型及 Memory 的推理组合复用该实现。私有记录保留凭据和 profile 原结构，public metadata/catalog 仍只返回白名单字段。读取受既有 10 秒预算约束，超时返回 MODEL_TIMEOUT，并记录 model_id、operation_id 与 phase，不自动重试。

SQL 时间字符串转换为原 get 使用的 ISO T 形式；revision 比较同时接受 catalog 已有的空格时间形式，普通版本 tag 保持。原 embedding 空 chunk 参数默认值保留在 Runtime，维度仍只取已配置 max_tokens，不探测或替换模型。此项没有迁移全部模型写入/健康检查或 Memory 配置读取，也不代表完整 data-process 流水线已验收。
