# AIDP 知识库详情页开发与联调交接

更新日期：2026-10-09。交接对象：接手知识库详情页前端、Nexent 后端代理及真实 AIDP 联调的开发同事。

## 1. 从哪里开始

| 项目           | 交接基线                                                                    |
| -------------- | --------------------------------------------------------------------------- |
| 仓库           | `ModelEngine-Group/nexent`                                                  |
| 远端分支       | `feat-knowledge-base-pages-refactor`                                        |
| 业务代码提交   | `92cf2d8d2c51b61e4fa4b05d81b89c911b71fe57`                                  |
| 功能范围       | 仅 AIDP 知识库详情页，包括文件、上传任务、详细信息、编辑、权限、导入抽屉    |
| 不属于本次接手 | ES 知识库；知识库列表和创建页的独立需求；图谱可视化、文件预览、切片内容编辑 |
| 当前验证环境   | 本地 AIDP mock；尚不能据此认定真实 AIDP 已联调通过                          |

当前分支包含知识库列表、创建和详情的完整改造。建议接手者从此基线新建自己的详情页分支，保留完整运行依赖；不要只复制详情组件或者随意挑选几条提交。

下面的分支名是建议名称，可以换为团队约定的名称：

```bash
git fetch origin
git switch -c feat-aidp-knowledge-detail-followup 92cf2d8d2c51b61e4fa4b05d81b89c911b71fe57
```

这不是一条“只包含详情改动、可独立合入 develop”的分支。若需要那种交付方式，要另外整理公共依赖和提交，不能把上面的新分支当成已经完成代码拆分。

交接后的职责：接手者负责详情页前后端和 AIDP 联调；原开发者继续负责列表、创建页。修改共用组件、接口返回类型或权限服务时，双方需要同步评估其他页面。

## 2. 文档优先级与交接资料

本说明记录截至基线提交的当前行为、用户最新决定、已发现差异与联调任务。历史设计稿和原型用于补充视觉与接口证据，不能覆盖后续已经确认的修改。

原始资料目前在交接人的工作区 `uploads/`，不在 Git 分支中；只拉代码不会拿到这些资料。因此本次另提供附件包，包含：

| 附件包内位置                                                          | 内容                                                           |
| --------------------------------------------------------------------- | -------------------------------------------------------------- |
| 根目录的本交接说明                                                    | 当前范围、代码入口、接口和验收清单                             |
| `references/knowledge-base-detail-design/`                            | 历史详情设计 `design.md`、`proposal.md`、`tasks.md`            |
| `references/knowledge-base-detail-design/references/detail-files.png` | 详情概览与文件页原型                                           |
| 同目录 `detail-tasks.png`                                             | 上传任务原型                                                   |
| 同目录 `detail-failure-drawer.png`                                    | 失败详情原型                                                   |
| 同目录 `detail-information.png`                                       | 详细信息原型                                                   |
| 同目录 `AIDP-26.0.0-1790238797166.xls`                                | AIDP 接口文档                                                  |
| `references/knowledge-base-import-design/`                            | 导入抽屉设计和 UCD 测量记录                                    |
| `local-dev-guide/DEV-GUIDE.md`                                        | 交接人电脑的本地启动说明；另一台电脑需替换路径、端口配置和凭据 |

历史详情稿日期为 2026-09-29，仍写“尚未开发”，并包含后来取消的安全护栏。导入稿也仍有“尚未部署”等旧状态。阅读这些资料时，以本说明中的当前状态为准。

重要的后续决定：安全护栏已取消；相似度阈值只读；导入选择文件即上传、底部按钮为“确定”；上传区不再有独立“选择本地文件”按钮；用户组只读展示最多一行；搜索、分页使用 AIDP 能力，不在 Nexent 全量读取后处理。

## 3. 页面行为与数据来源

### 3.1 入口与顶部概览

- 从知识库列表点击知识库名称或卡片进入详情，列表不提供编辑入口。
- 详情占满内容区，面包屑为“知识库 / 知识库详情”；当前由列表容器切换到详情组件，不能假定它是一个独立的 `/detail` 路由。
- 顶部展示名称、描述、文件数量、私有/共享、可访问用户组、创建时间、创建人；可编辑用户有名称旁的编辑入口及删除入口。
- 顶部编辑弹窗直接展示名称、描述、权限与用户组，不再放入折叠的高级选项。
- 顶部“权限与用户组”当前只读值主要展示私有/共享；组内可编辑或只读的详细设置在“详细信息”的权限区展示。

### 3.2 文件页

- 数据来自 AIDP 的已入库文件接口，不能用上传任务 History 替代，也不将文件列表写入 Nexent PG。
- 列为名称、类型、大小、导入方式、首次上传时间、更新时间、操作；操作为下载、删除。
- 名称搜索、页码与每页数量传给后端，再由后端传给 AIDP。不要新增本地全量搜索。
- 文件类型、大小、导入方式和时间的筛选/排序，只能在上游支持并确认参数后增加。当前不显示这些未经确认的能力。
- 分页在右侧，可选每页数量；名称和操作列固定，表格中间横向滚动。列宽拖动尚未实现，见第 9 节。

### 3.3 上传任务页

- 数据来自 AIDP History；AIDP 负责只返回近 30 天任务。页面提醒任务只保留近 30 天，Nexent 不再做额外日期过滤。
- 上传后先有任务记录；成功入库后，文件才属于文件页。成功任务在保留期内仍可查询。
- 列为名称、类型、大小、更新时间、状态、操作；文件名称可搜索。
- 状态筛选位于“状态”表头，单选，必须包含“全部”。
- 请求 `status` 映射固定为：全部 0、成功 1、提取中 2、向量入库失败 3、排队中 4、图谱入库失败 5。没有独立“失败”筛选选项。
- 统计使用 AIDP 返回的统计字段，不从当前页计算总数、提取中、失败或成功数量。
- 顶部没有批量重试按钮。失败行有单文件“重新提取”和“失败详情”；只读用户不应提交重试。
- 失败详情从右侧抽屉展示文件名称、状态、任务更新时间、错误码、原因；缺失值显示“—”。当前实现还在抽屉底部提供单文件重试，历史稿对此有矛盾说明，见第 9 节。

请求状态数字与任务记录返回的状态不是同一份约定。返回的 `FAILED` 暂显示为向量入库失败，`UPLOADING` 暂显示为排队中；这是用户授权的临时映射，需真实环境核对。不要将未识别的状态直接判断为成功。

### 3.4 详细信息页

| 模块         | 展示或修改范围                                                                                   |
| ------------ | ------------------------------------------------------------------------------------------------ |
| 基础信息     | 知识库 ID、创建时间、更新时间、创建人                                                            |
| 配置参数     | 切片方式、向量化模型、VLM 开启状态与模型、Rerank 模型、相似度、向量检索 Top K                    |
| 可修改设置   | 当前只有切片方式 `chunk_mode` 和向量 Top K `topk`；Top K 使用创建页同款滑块与数值控件            |
| 只读设置     | 相似度阈值、模型及其他没有明确修改参数的配置，不额外提交这些字段                                 |
| 知识图谱     | LLM 模型、子图扩展跳数、领域、图谱检索 Top K、思考、同义词合并、语义消歧、提示词语言、提示词模板 |
| 权限与用户组 | 私有/共享、组内权限、可访问用户组；此处编辑弹窗只有权限与用户组，没有名称、描述                  |

`chunk_mode=0` 为智能分片，`chunk_mode=1` 为法律条文。向量生成的 embedding、VLM 与构图 LLM 是不同用途的字段，不能混成一个模型选择。

用户组只读展示已统一到一个组件：最多一行、最多两个标签，其余用 `+N`；长名称截断，可悬停看完整名称；点击 `+N` 打开有滚动条的完整名单。私有库显示仅创建人可访问；共享库名称无法解析时当前会回退到组 ID。编辑仍使用多选框。

### 3.5 数据归属

- 文件内容、已入库文件、上传任务、提取状态和知识库处理配置由 AIDP 管理。
- Nexent PG 保存本地知识库授权关系及用户组关系；它们用于限制用户能查看、编辑哪些 AIDP 知识库。
- 单库详情经过现有 AIDP 详情缓存读取，并合并本地权限。文件和任务列表按页面请求查询上游；不要把“有缓存的单库配置”和“全量落库文件列表”混为一谈。
- 不能为补齐页面空值，在 PG 新增文件或任务历史副本。字段缺失应显示“—”，并记录真实返回供适配。

## 4. 前端代码入口

路径相对仓库根目录；下面链接可在仓库中直接打开。

| 文件                                                                                                                   | 职责与接手注意点                                                                                            |
| ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| [AidpKnowledgeConfiguration.tsx](../../frontend/ext_components/aidp/components/AidpKnowledgeConfiguration.tsx)         | 列表容器选择知识库后渲染详情；返回、删除、更新回调由容器提供。不是整文件归详情页独占                        |
| [AidpKnowledgeDetail.tsx](../../frontend/ext_components/aidp/components/AidpKnowledgeDetail.tsx)                       | 主详情组件；顶部概览、请求与状态、文件/任务表、失败抽屉、配置编辑、导入入口。仍包含较多逻辑                 |
| [AidpKnowledgeDetailInformation.tsx](../../frontend/ext_components/aidp/components/AidpKnowledgeDetailInformation.tsx) | 基础信息、配置、图谱、权限区；导出 `AidpDetailField` 供顶部复用                                             |
| [AidpGroupNamesDisplay.tsx](../../frontend/ext_components/aidp/components/AidpGroupNamesDisplay.tsx)                   | 一行用户组标签、`+N` 完整名单；顶部和权限区共用                                                             |
| [AidpUpdateKbModal.tsx](../../frontend/ext_components/aidp/components/AidpUpdateKbModal.tsx)                           | `metadata` 与 `permissions` 两种编辑模式；只发送发生变化的名称/描述，处理权限已保存但 AIDP 元数据失败的结果 |
| [AidpKnowledgeBaseModalParts.tsx](../../frontend/ext_components/aidp/components/AidpKnowledgeBaseModalParts.tsx)       | 编辑/创建共用的基础字段、权限字段与弹窗布局                                                                 |
| [AidpImportDrawer.tsx](../../frontend/ext_components/aidp/components/AidpImportDrawer.tsx)                             | 列表与详情共用的文件导入抽屉；选择即上传、结果行、进度、确认/取消                                           |
| [AidpImportDrawer.module.css](../../frontend/ext_components/aidp/components/AidpImportDrawer.module.css)               | 导入抽屉、文件行、边框与进度布局                                                                            |
| [AidpSliderNumberField.tsx](../../frontend/ext_components/aidp/components/AidpSliderNumberField.tsx)                   | 创建和详情 Top K 编辑共用控件                                                                               |
| [AidpPagination.tsx](../../frontend/ext_components/aidp/components/AidpPagination.tsx)                                 | 列表、文件、任务共用分页；支持可靠总数与只知道还有下一页的情况                                              |
| [useAidpGroupOptions.ts](../../frontend/ext_components/aidp/hooks/useAidpGroupOptions.ts)                              | 根据账号角色获取可配置用户组，映射 ID/名称                                                                  |
| [aidpKnowledgeService.ts](../../frontend/ext_components/aidp/services/aidpKnowledgeService.ts)                         | 前端接口方法、类型和操作结果整理；多个页面共用                                                              |
| [services/api.ts](../../frontend/services/api.ts)                                                                      | `API_ENDPOINTS.aidpMgmt` 定义请求路径与代理前缀                                                             |
| [aidpKnowledgeDisplay.ts](../../frontend/lib/aidpKnowledgeDisplay.ts)                                                  | 缺失值、可靠文件计数等公共展示规则                                                                          |
| `frontend/public/locales/zh/common.json`、`en/common.json`                                                             | `aidpKnowledge.*` 文案；新增文案需同时维护中英文                                                            |

接手后若继续拆组件，建议从主组件中逐步拆顶部、文件表、任务表和失败抽屉；先保持现有请求参数、回调与权限校验不变。代码拆组件与交接是两件事，不必在联调前整体重写。

## 5. 后端代码入口与接口对应

| 文件                                                                                                | 职责                                                                           |
| --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| [aidp_mgmt_app.py](../../backend/ext_components/aidp/apps/aidp_mgmt_app.py)                         | HTTP 路由、请求校验、当前用户/租户、权限校验、接口返回组合；列表/创建/详情共用 |
| [aidp_service.py](../../backend/ext_components/aidp/services/aidp_service.py)                       | AIDP HTTP 请求、字段整理、文件与任务分页、上传/下载/删除/重试                  |
| [aidp_kb_update_service.py](../../backend/ext_components/aidp/services/aidp_kb_update_service.py)   | 先保存本地权限，再同步明确改变的名称/描述；处理部分成功                        |
| [aidp_permission_service.py](../../backend/ext_components/aidp/services/aidp_permission_service.py) | 可见范围与 READ/EDIT 判断、用户组校验                                          |
| [aidp_permission_db.py](../../backend/ext_components/aidp/database/aidp_permission_db.py)           | 本地授权记录读写，不是 AIDP 文件数据库                                         |
| [aidp_access_service.py](../../backend/ext_components/aidp/services/aidp_access_service.py)         | AIDP 目录/详情/计数缓存及失效；修改成功后需维持刷新逻辑                        |

下表的 Nexent 路径省略前端反向代理前缀；前端实际地址以 `API_ENDPOINTS` 为准。AIDP 路径省略 `/KnowledgeBase/Tenants/{tenant_id}`。Nexent 当前登录租户与配置中的 `AIDP_TENANT_ID` 不能当成同一个参数。

| 页面操作               | Nexent 接口                                               | 请求重点                                                       | AIDP 对应接口                                       |
| ---------------------- | --------------------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------------- |
| 单库详情               | GET `/aidp-mgmt/knowledge-bases/{id}`                     | 本地 READ 权限；合并 `permission/group_ids/ingroup_permission` | GET `/KnowledgeBases/{id}`                          |
| 修改切片/Top K         | PUT `/aidp-mgmt/knowledge-bases/{id}`                     | `chunk_mode` 0/1、`topk` 1–100；仅提交所改字段                 | PATCH `/KnowledgeBases/{id}`                        |
| 顶部名称/描述/权限编辑 | PATCH `/aidp-mgmt/aidp-permissions/{id}`                  | 必须有组内权限，名称/描述只在改变时发送                        | 本地权限先保存；有元数据变化才 PATCH AIDP 单库      |
| 权限区编辑             | 同上                                                      | 只发 `ingroup_permission/group_ids`                            | 不调用 AIDP 元数据修改                              |
| 删除库                 | DELETE `/aidp-mgmt/knowledge-bases/{id}`                  | EDIT；删除成功清理本地授权、失效相关缓存                       | DELETE `/KnowledgeBases/{id}`                       |
| 已入库文件             | GET `/aidp-mgmt/knowledge-bases/{id}/files`               | `page/page_size/keyword`                                       | GET `/KnowledgeBases/{id}/KnowledgeFiles`           |
| 未筛选文件总数         | 由文件列表接口处理                                        | 无 keyword 时使用 Count；不能拿未筛选 Count 充当搜索总数       | POST `/KnowledgeBases/{id}/KnowledgeFiles/Count`    |
| 上传任务               | GET `/aidp-mgmt/knowledge-bases/{id}/upload-tasks`        | `page/page_size/keyword/status`                                | POST `/KnowledgeBases/{id}/KnowledgeFiles/History`  |
| 任务来源信息           | 后端内部调用                                              | 获取本地上传 `fs_id`；History 的 `dir_path=/{id}`              | GET `/KnowledgeBases/{id}/Channels`                 |
| 单文件重新提取         | POST `/aidp-mgmt/knowledge-bases/{id}/upload-tasks/retry` | `file_uuids` 非空 UUID 数组；页面发一个元素                    | POST `/KnowledgeBases/{id}/KnowledgeFiles/Retry`    |
| 导入文件               | POST `/aidp-mgmt/knowledge-bases/{id}/documents`          | multipart 同名 `files` 字段，可多个；EDIT                      | POST `/KnowledgeBases/{id}/KnowledgeFiles/Upload`   |
| 删除文件               | POST `/aidp-mgmt/knowledge-bases/{id}/documents/remove`   | `file_uuids` 数组；页面单文件                                  | POST `/KnowledgeBases/{id}/KnowledgeFiles/Remove`   |
| 下载文件               | POST `/aidp-mgmt/knowledge-bases/{id}/documents/download` | `file_uuid`；READ；响应文件流                                  | POST `/KnowledgeBases/{id}/KnowledgeFiles/Download` |

现有 `/documents` GET 是旧混合文件视图兼容入口。新详情文件表使用 `/files`，上传任务表使用 `/upload-tasks`。不要为复用旧逻辑把两个新表重新合并。

### 5.1 分页返回与字段

文件列表返回 `value`、`total_count`、`total_reliable`、`has_more`。没有名称筛选时 Count 能提供可靠总数；名称搜索时未确认上游有可靠的筛选总数，后端根据 `next_link` 等判断还有没有下一页，总数可能只是下界。前端应尊重 `total_reliable`，不能把估计值展示成准确总数。

任务列表返回 `value`、`total_count`、`total_reliable`、`has_more`、`stats`、`retention_days=30`。统计映射为：

| Nexent 字段        | AIDP 字段                                      |
| ------------------ | ---------------------------------------------- |
| `stats.total`      | `total_record_count`，缺失时当前回退到列表总数 |
| `stats.extracting` | `processing_record_count`                      |
| `stats.failed`     | `failed_record_count`                          |
| `stats.success`    | `success_record_count`                         |
| `stats.queued`     | `queued_record_count`                          |

任务明细重点字段：`file_uuid`、`file_name`、`file_type`、`file_size`、`status`、`updated_at`、`error_code`、`extraction_failure_reason/reason`。时间、来源和异常字段需按真实响应核对，不能根据 mock 中“字段完整”推断上游一定返回。

文件名称搜索和 History 请求每次只读取所需页；重试不再预先扫描整份 History。缺少上游能力时记录问题，不要重新加入全量抓取、前端过滤或重复的 30 天过滤。

### 5.2 请求示例与部分成功

以下 ID 仅说明结构，联调时要使用环境中真实知识库、文件 UUID 和用户组 ID。

```json
{ "file_uuids": ["00000000-0000-4000-8000-000000000001"] }
```

```json
{ "ingroup_permission": "READ_ONLY", "group_ids": [101, 102] }
```

顶部编辑若名字发生变化，向权限请求额外加入 `name`；未变化就省略。描述的清空和未修改不同：需要清空时传空字符串，未修改时不传。

本地权限先保存，随后 AIDP 元数据同步可能失败。返回中的 `permissions_saved` 和 `metadata_status` 表示各自结果；`metadata_status=failed` 时不能提示“全部保存成功”或把名称改成新值，也不能假定权限被回滚。

上传/删除/重试结果使用 `summary`、`success_list`、`failed_list`。HTTP 200 不等于全部文件成功，必须读取结果列表；真实 AIDP 操作响应和部分成功结构仍需验证。

## 6. 导入文件的现行方案

1. 点击或拖入上传区域选择文件；没有单独的选择文件按钮。
2. 同次有效选择作为一次多文件 multipart 请求，浏览器先提交到 Nexent 后端。
3. FastAPI 以 `UploadFile` 接收文件，后端将 `UploadFile.file` 作为文件对象交给 httpx，再提交给 AIDP。框架可能有请求期临时文件，但没有独立暂存业务接口、MinIO 暂存或“确认后才开始上传”的流程。
4. 文件行的圆环使用这一请求的整体 XHR 上传百分比，每个上传中行显示相同百分比；第二行只显示该文件总大小，不显示已上传字节数，也不显示“本批进度”字样。
5. XHR 上传达到 100% 只表示浏览器向 Nexent 的请求体传输结束；此时仍可能在等待 Nexent/AIDP 结果。不能据此提前显示上传成功，更不等于解析入库完成。
6. 后端返回后，按 `success_list/failed_list` 更新各行；上传成功表示 AIDP 接受上传，后续处理状态去任务页查询。
7. 底部“确定”只关闭，不发第二次上传。存在待上传、上传中或等待接口结果时保持禁用；上传期间关闭、取消、遮罩关闭和 Esc 也被限制。
8. 只有失败行有删除按钮，删除只移除当前抽屉里的前端记录，不调用文件删除接口；没有重新上传按钮。

最多 50 条，失败条目也占名额；TXT、Excel、CSV 不超过 20 MB，其他受支持文件不超过 1024 MB。格式范围及具体校验以 `frontend/services/uploadService.ts` 和后端 `_validate_upload_files` 为准，调整限制时两侧同步。

文件列表在抽屉内独立滚动，顶部上传区域与底部按钮保持可见；待上传/上传中/失败文件行灰色虚线边框，成功行明显黑色实线。沿用 Nexent 字体与图标。

刷新浏览器会中断当前客户端请求；是否已有文件被 AIDP 接受不能仅据取消请求判断。因此不开放上传中删除，也不把浏览器中断解释为可靠撤回。真实环境需测试大文件、超时和部分失败。

## 7. 环境与启动交接

### 7.1 配置与页面入口

后端代码工作区根目录 `.env` 要开启 AIDP，并使用真实 AIDP 地址或 mock 地址。下面只有 mock 示例，不包含真实凭据：

```dotenv
DEPLOYMENT_VERSION=full
ENABLE_AIDP_KNOWLEDGE=true
AIDP_SERVER_URL=http://127.0.0.1:30081
AIDP_API_KEY=mock-aidp-key
AIDP_TENANT_ID=aidp
```

实际 PG、Supabase、JWT 和 AIDP 凭据由环境负责人提供，不随文档发送。运行后可检查 config 服务 `/tenant_config/deployment_version` 返回的 `enable_aidp_knowledge` 是否为 true。

当前基线的 `/zh/knowledges` 会根据配置选择 AIDP 或 ES；另有显式 AIDP 入口 `/zh/aidp-knowledges`。旧 DEV 文档将 `/zh/knowledges` 固定写成 ES，这个入口描述已不能原样套用。验收时结合配置与实际网络请求确认使用 `/aidp-mgmt/...`，不要仅凭 URL 判断。

AIDP 知识库最小环境需要主 PG 及 Full 登录所需 Supabase 服务、config、runtime、真实 AIDP 或 mock。该知识库路径不要求为了文件导入额外启动本地 ES、MinIO、Redis 和 data-process；项目其他功能如有依赖另行处理。

### 7.2 交接人电脑的运行方式

- Windows 前端：`C:/Users/cj/IdeaProjects/nexent/worktrees/deploy/frontend`，端口 3000。
- WSL 后端：`/mnt/c/Users/cj/IdeaProjects/nexent/worktrees/deploy/backend`，config 5010、runtime 5014。
- WSL mock：同一部署 worktree 的 `test/ext_components/aidp/mock_servers/aidp_mgmt_mock_server.py`，端口 30081。
- 前后端都从 `worktrees/deploy` 的同一提交启动；切换提交前先停止两侧服务。开发代码在功能 worktree 修改。
- 固定历史数据根为 `C:/Users/cj/nexent-data`，不得通过改成空目录来修复登录。Docker 配置与历史数据不属于代码交接内容。

另一台电脑按自己的路径、解释器和数据库配置启动。下面是已有环境配置完成后的命令，不替代首次安装说明。

WSL/Python 环境，在仓库根目录启动 mock：

```bash
python -u test/ext_components/aidp/mock_servers/aidp_mgmt_mock_server.py --port 30081
```

两个独立 WSL 终端，在 `backend/` 启动：

```bash
python -u config_service.py
```

```bash
python -u runtime_service.py
```

Windows PowerShell，在 `frontend/` 启动；对齐后端端口：

```powershell
$env:HTTP_BACKEND = 'http://127.0.0.1:5010'
$env:WS_BACKEND = 'ws://127.0.0.1:5014'
$env:RUNTIME_HTTP_BACKEND = 'http://127.0.0.1:5014'
npm run dev
```

mock 状态保存在 `test/ext_components/aidp/mock_servers/_state/knowledge_bases.json`，重启不会清空。`POST /_reset` 会恢复种子数据，不要在保留演示数据的环境随意调用。

## 8. 测试与已有验证记录

当前交接前最近一次实际运行：AIDP 前端组件/服务测试 3 个文件、13 项通过；`npm run type-check` 和本次改动的 Prettier 检查通过。本地浏览器已确认详情页用户组单标签样式；当前演示知识库只有 Default Group，多个组的浮层行为由组件测试覆盖，尚没有该数据下的浏览器验收记录。

这不代表生产构建、所有后端测试或真实 AIDP 联调已在同次验证通过。接手者按修改内容补做检查。

前端，在 `frontend/`：

```bash
npm run type-check
npm exec vitest -- run --config vitest.aidp.config.ts
```

后端，在已配置项目 Python 测试环境的仓库根目录：

```bash
python -m pytest test/ext_components/aidp/test_aidp_mgmt_app.py test/ext_components/aidp/test_aidp_service.py test/ext_components/aidp/test_aidp_mgmt_mock_server.py
```

相关资产：

- [后端路由测试](../../test/ext_components/aidp/test_aidp_mgmt_app.py)：已包含文件搜索单页转发、任务参数转发/统计、重试不预读 History 的检查；旧兼容 `/documents` 的全量历史测试不等于新接口行为。
- [AIDP 服务测试](../../test/ext_components/aidp/test_aidp_service.py)和 [mock 测试](../../test/ext_components/aidp/test_aidp_mgmt_mock_server.py)。
- [导入抽屉测试](../../test/automation/d1/AidpImportDrawer.test.tsx)、[上传服务测试](../../test/automation/d1/AidpUploadService.test.tsx)、[用户组展示测试](../../test/automation/d1/AidpGroupNamesDisplay.test.tsx)。
- [详情功能规则](../../test/features/aidp-knowledge-detail.yaml)、[需求记录](../../test/changes/requirements/aidp-knowledge-detail.yaml)、[缺陷记录](../../test/changes/bugs/aidp-knowledge-detail.yaml)。
- `test/cases/d1` 至 `d5` 下的 `aidp-knowledge-detail.yaml` 是分层验收定义，不可因为有文件就认为相关自动化已经全部执行。

## 9. 需要接手者继续处理或核对的事项

### 9.1 真实 AIDP 联调

| 编号 | 验证内容                 | 当前做法及需要记录的证据                                                                                          |
| ---- | ------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| A-01 | 六个任务筛选值及返回状态 | 请求数字 0–5 已由用户实测确认；记录每类任务的真实返回 `status`，重点核对暂定的 FAILED、UPLOADING                  |
| A-02 | 单文件重试               | 先按 POST + `file_uuids` 数组示例；分别验证向量失败、图谱失败被接受后的任务变化                                   |
| A-03 | 多文件重试与部分失败     | 后端保留数组，不增加 UI 批量按钮；确认上游数量限制、重复 ID、无效 ID、部分成功返回                                |
| A-04 | 文件来源字段             | 确认导入方式真实返回字段；不把目录路径或 mock 的本地上传文字当成正式接口事实                                      |
| A-05 | 中文搜索和分页           | 文件/任务中文、空结果、翻页和每页数量；保存实际请求，确认一次只取所需页，`next_link/total_count` 含义正确         |
| A-06 | 任务统计                 | 确认统计是本库、近 30 天、筛选前还是筛选后，以及失败统计是否包含两种入库失败；按返回展示，不从当前页合计          |
| A-07 | History 来源参数         | 确认 Channels 得到正确 `fs_id`；请求 `dir_path=/{id}`；无管道时当前可能返回空任务，需区分真的无任务与来源解析失败 |
| A-08 | 失败详情                 | 返回错误码、原因、更新时间的字段和格式；没有错误码就显示“—”，不能拆错误文字臆造代码                               |
| A-09 | 参数更新                 | chunk_mode 与 topk 保存后重新查询；相似度不提交；名称、描述更改和清空正确                                         |
| A-10 | 权限及部分成功           | 多用户组、只读/可编辑/私有、无权账号；模拟本地权限成功而 AIDP 元数据失败，确认警告与回读结果                      |
| A-11 | 上传、下载与删除         | 多个文件、部分失败、同名不同文件、大文件、断网/超时；检查成功仅代表上传接受；下载文件名和内容、删除后刷新正确     |
| A-12 | 详情字段                 | 更新时间、文件数量、容量、创建人、模型和 graph_config 缺失/字符串/对象等返回，保留真实响应以确认整理逻辑          |

每条记录包含：环境与 AIDP 版本、Nexent 提交、页面操作、请求方法/路径/参数、响应字段、实际页面结果、通过或问题。请求头 token、API key、用户真实文件内容不加入交接记录。

### 9.2 已识别的实现和设计差异

| 编号 | 当前事实                                                                     | 后续动作                                                                                     |
| ---- | ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| U-01 | 两张详情表已固定名称与操作列并横向滚动，但没有列宽拖动手柄                   | 按用户已提出的要求补齐：拖动一个中间列只改该列宽，其他列不变，总表宽随之变化                 |
| U-02 | `AidpKnowledgeDetailInformation` 的图谱区域渲染了两次 LLM 模型               | 历史详情确认要求为只展示一次；整理成一处，保留构图模型字段，不能因此删接口字段               |
| U-03 | 多用户组只读展示已实现，但浏览器演示数据仅一个组                             | 用多个已有测试组验证窄宽度、长名称、两个/多个组、`+N` 点击、名单滚动，确认不换行也不裁掉按钮 |
| U-04 | 历史 proposal 写“失败抽屉只展示信息”，初始用户描述和当前实现保留抽屉底部重试 | 当前行为作为交接基线；若要移除按钮，需要明确产品决定，不能因旧稿一句话顺手删除               |
| U-05 | 后端将本地授权 `owner_user_id` 写入 `created_by`，前端优先展示它             | 当前“创建人”可能为 ID；若要显示人名，需要使用可核对的用户名称来源，不编造映射                |
| U-06 | 旧稿有安全护栏、尚未开发/尚未部署说明，旧 DEV 文档入口描述也有过期内容       | 安全护栏已取消；按本说明与代码确认现行范围。不要重新接入安全字段或把 AIDP 页面判成 ES        |

上面是交接时识别到的具体事项，不是对全部 UI 的完整审查。继续按原型逐项检查容器、间距、字号、颜色、固定高度和分页；字体与图标沿用 Nexent。

## 10. 接手后的验收流程

- [ ] 拉取基线，创建自己的分支，能独立启动 mock 页面；确认 `enable_aidp_knowledge=true`。
- [ ] 名称或卡片进入详情，面包屑返回列表；名称/描述修改与删除权限正确。
- [ ] 文件页只显示已入库数据，中文搜索、分页、下载、删除、导入与缺失值展示正确。
- [ ] 任务状态筛选在表头，包含全部 0；统计来自上游；没有顶部批量重试。
- [ ] 两种失败任务可查看抽屉；可编辑用户可重试，只读用户不能提交。
- [ ] 配置解析、chunk_mode/topk 修改、相似度只读、私有/共享及多个用户组显示和修改正确。
- [ ] 上传区点击/拖拽、50 条限制、滚动、圆环、虚实边框、部分失败、确认禁用与失败本地删除正确。
- [ ] 完成 U-01/U-02 的处理或给出明确延期记录；完成 U-03 浏览器检查。
- [ ] 连接真实 AIDP，逐条记录 A-01 至 A-12；mock 与真实返回不同的字段集中修复并补充回归检查。
- [ ] 检查共用组件涉及的知识库列表、创建页，确认 ES 场景未受影响。
- [ ] 提交代码、联调记录、仍未解决的问题及对应负责人；更新本说明或新增带日期的联调补充文档。

完成交接的标准：接手者能独立拉代码、启动环境、定位每项页面操作的前后端与上游接口，并按此清单完成一次真实 AIDP 验收。无需依赖前一段聊天记录才能继续开发。
