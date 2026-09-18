# 技术设计 — CHEN-183 对话管理功能

| 字段 | 值 |
| --- | --- |
| **创建者** | Architect-9e918769-33c2-406f-a9aa-ac60396f4875 |
| **创建时间** | 2026-09-18 15:25 |
| **版本** | v0.1 |
| **状态** | 草稿 |
| **JIRA** | CHEN-183 |
| **上游 PRD** | 无法发布（Confluence/JIRA 未配置凭据与域名，见风险与边界 RISK-1） |

> 文档头部元数据遵循 `multica-technical-design` 模板（`design-template.md`）。

## 修订记录

| 日期 | 版本 | 作者 | 变更 |
| --- | --- | --- | --- |
| 2026-09-18 | v0.1 | Architect-9e918769-33c2-406f-a9aa-ac60396f4875 | 初稿 |

## 理解（当前系统做什么）

系统 `nexent` 是一个多智能体（agent）平台，会话（conversation）是用户与智能体问答的主载体：

- **后端** `backend/apps/conversation_management_app.py` 暴露 `/conversation` 路由。核心接口：
  - `GET /conversation/list`（`list_conversations_endpoint`，line 65）：按**创建时间倒序**分页返回**未删除**会话（`delete_flag == 'N'`），并在 `metadata` 中给出 `total / today / last_7_days / older` 分桶计数。数据来自 `backend/database/conversation_db.py` 的 `get_conversation_list_page`（line 877），会话归属校验为 `created_by == user_id`（当前用户视角）。
  - `GET /conversation/{conversation_id}`：返回会话详情（完整消息历史）。获取消息历史由 `services/conversation_management_service.py` 的 `get_conversation_history_service`（line 708）承接，消息按 `message_id`、`unit_id`（来源检索）组织。
  - 其余：`POST /create`、`POST /rename`、`POST /sources`、`POST /generate_title`、`POST /message/update_opinion`、`DELETE /{id}`、`POST /batch-delete` 等。
- **模型**（`backend/consts/model_models.py`）：`ConversationRequest`（line 894）、`ConversationResponse`（line 898）；已包含 `conversation_title`、`agent_id`、`chat_mode` 等字段。会话树模型在 `backend/database/db_models.py`：`ConversationRecord`（line 254，含 `conversation_title`、`agent_id`）、`ConversationMessage`（line 290）、`ConversationMessageUnit`（line 315）、`ConversationSourceImage`（line 487）、`ConversationSourceSearch`（line 509）、`ConversationShare`（line 549）。
- **前端** `frontend`（Next.js App Router + Ant Design + react-query）：
  - `services/conversationService.ts`：`getList(offset/limit/today_start_ms/week_start_ms)` 分页拉取；`getDetail()` 拉取会话详情；`conversationService` 是左侧会话列表（`chatLeftSidebar.tsx`）与「对话管理」新页共用的数据源。
  - `types/conversation.ts`：`ConversationListItem`（conversation_id / conversation_title / agent_id / create_time / update_time）、`ConversationListPage`、`ConversationListMetadata`（total/today/last_7_days/older）、`ApiMessage` 系列。
  - `hooks/chat/useConversationManagement.ts`：`useInfiniteQuery`，queryKey `["conversations","legacy-chat"]`，`limit` 默认 20，滚底翻页。
  - 会话历史渲染：`app/[locale]/newchat`（assistant-ui）与 `chat/internal/chatInterface.tsx` 已有消息气泡/来源渲染组件；`memory/MemoryManager.tsx` 是「筛选器（智能体下拉 + DatePicker.RangePicker + 名称关键字）+ 分页表格 + 空态」的成熟页面范式，可直接作为新页 UI 范式参考；`SideNavigation.tsx` 通过 `ROUTE_CONFIG` + `accessibleRoutes`（后端 LEFT_NAV_MENU 角色权限）驱动侧边栏菜单。

**目标（与 PRD 对齐）**：新增「对话管理」页面，支持会话列表查看与按条件筛选，满足以下验收标准：
- **AC-1** 按**日期范围**筛选（创建时间落在指定区间）。
- **AC-2** 按**智能体（agent）**筛选。
- **AC-3** 按**名称关键字**模糊筛选（fuzzy）。
- **AC-4** 三个筛选维度（日期区间 / 智能体 / 名称）**可组合**。
- **AC-5** 点击某条会话 → 查看该会话**完整消息内容**。
- **AC-6** 无匹配结果时展示**空态**（empty state）。

## 非目标（Non-goals）

- 不做会话的**编辑 / 重命名 / 删除 / 合并 / 导出**（复用现有列表侧栏的能力即可，不回写）。
- 不做**全文 / 语义搜索**，仅在 `conversation_title` 上做「包含」模糊匹配（AC-3 限定为名称关键字）。
- 不做跨智能体 / 跨用户的会话聚合与权限矩阵调整；保持**当前用户视角**（`created_by = user_id`），与现有会话列表契约一致。
- 不做对话消息的**流式加载 / 编辑 / 继续对话**交互，详情页仅**只读查看**。
- 不新增独立的导航菜单权限体系；复用现有 `LEFT_NAV_MENU` 路由可见性机制（否则侧边栏不生效）。
- 不引入新依赖 / 大变重构：所有改动在现有后端服务、前端服务与页面范式内完成。

## 建议改动（最小可行方案）

### 后端

1. **扩展列表查询过滤**：`backend/database/conversation_db.py` 的 `get_conversation_list_page`（line 877）与 `backend/apps/conversation_management_app.py` 的 `list_conversations_endpoint`（line 65）增加**可选查询参数**（全部可选，缺省后行为与现状完全一致，保证向后兼容）：
   - `start_date_ms` + `end_date_ms`（含端点）：`create_time` 落在 [start_date_ms, end_date_ms] 区间内。
   - `agent_id`（int，可选）：`ConversationRecord.agent_id == agent_id`。
   - `keyword`（str，可选）：`conversation_title` 模糊包含匹配（`like %keyword%`），大小写不敏感（后端用 `ilike` 或转小写比对）。
   - 三个维度在 SQL 层用 `and_` 组合（必然满足 AC-4 可组合）；分页复用现有 `offset/limit` 与 metadata 分桶。实现上可将过滤条件放进现有 `stmt` 的 `.where(...)` 链（`get_conversation_list` 模式，line 819 已有 `user_id` 条件与 `delete_flag` 过滤，直接在其上加条件即可）。
2. **详情复用**：查看完整消息（AC-5）直接复用现有 `GET /conversation/{conversation_id}` + `get_conversation_history_service`，前端调用 `conversationService.getDetail()`，**无需新增后端详情接口**。

### 前端（新建「对话管理」页面）

1. **路由与侧边栏**：新增路径 `/conversation-manage`。在 `frontend/` 的导航配置中：
   - `SideNavigation.tsx` `ROUTE_CONFIG` 增加一条菜单项（Icon 用现有 lucide 图标库，`labelKey` 指向新的多语言 key），挂在合适分组（建议独立一级项或挂 `chat` 相关分组，具体位置以现有分组结构为准）。
   - 由于侧边栏路由由后端 `LEFT_NAV_MENU` 角色权限驱动，新增路由需在**角色权限种子数据**中补充 `/conversation-manage` 条目（后端 `deploy/sql` 种子或运行时权限数据），否则菜单不展示（AC- 依赖侧边栏入口）。此项由 @BackendDev 与后端权限配置协同确认。
   - 若按现有模式由路由守卫 `accessibleRoutes` 控制，前端需同步该路径到需鉴权可访问列表。
2. **页面组件**：新建页面目录（如 `frontend/app/[locale]/conversation-manage/`），复用 `memory/MemoryManager.tsx` 的「筛选器 + 分页表格 + 空态」范式：
   - **筛选区**：日期范围选择（`DatePicker.RangePicker`，将 dayjs 范围转成 `start_date_ms/end_date_ms`）、智能体下拉（`Select`，选项来自现有 agent 列表服务）、名称关键字输入框（`Input`，模糊搜索，可带防抖）。
   - **列表区**：`Table`（列：标题、智能体、创建时间、更新时间、操作「查看」），服务端分页（`offset/limit`），滚底或分页器翻页。
   - **详情查看（AC-5）**：点击行「查看」→ 打开详情（复用 `conversationService.getDetail()` 返回的消息历史，用现有消息渲染组件展示完整对话）。
   - **空态（AC-6）**：无匹配时展示 `Empty`（复用 `memory` 页 `Empty.PRESENTED_IMAGE_SIMPLE` 风格），区分「初始无数据」与「筛选无结果」文案。
   - 多语言：在 `frontend/public/locales/{zh,en}/common.json` 补充 `sidebar.conversationManage` 与页面文案 key（遵循 i18n 约定）。
3. **查询 Hook**：新增或扩展 `useConversationManagement`，支持筛选参数（`startDateMs/endDateMs/agentId/keyword`），筛选变化时 `refetch` / reset queryKey。

## 受影响组件

| 组件 / 文件 / 服务 | 变更类型 | 说明 |
| --- | --- | --- |
| `backend/apps/conversation_management_app.py` | 修改 | `list_conversations_endpoint` 增加可选筛选 query 参数 |
| `backend/database/conversation_db.py` | 修改 | `get_conversation_list_page` 增加日期区间 / agent / keyword 过滤 |
| `backend/consts/model_models.py` | 修改（小） | 必要时扩展分页响应模型（若需回显筛选条件到响应） |
| `backend/deploy/sql` 权限种子 | 修改 | 为 `LEFT_NAV_MENU` 补充 `/conversation-manage` 路由权限（需 @BackendDev 确认种子机制） |
| `frontend/app/[locale]/conversation-manage/` | 新增 | 新页面目录与组件 |
| `frontend/components/navigation/SideNavigation.tsx` | 修改 | 新增 `ROUTE_CONFIG` 菜单项 |
| `frontend/services/conversationService.ts` | 修改 | `getList` 增加筛选参数透传 |
| `frontend/types/conversation.ts` | 修改 | 扩展列表请求参数与响应类型 |
| `frontend/hooks/chat/useConversationManagement.ts` | 修改 | 支持筛选参数与重置 |
| `frontend/public/locales/{zh,en}/common.json` | 修改 | 新增页面与侧边栏多语言 key |
| `frontend/services/api.ts` | 修改 | `API_ENDPOINTS.conversation` 若有新增端点则登记（详情复用则无） |

## 数据与状态（范围涉及时必填）

列表查询本身**不新增表 / 字段**；全部筛选落在现有 `conversation_record_t.create_time`、`conversation_record_t.agent_id`、`conversation_record_t.conversation_title` 上，无数据迁移。

- 会话归属：维持 `created_by == user_id`（当前用户）视图，符合现有会话数据权限边界。
- 分桶元数据：沿用 `total / today / last_7_days / older`；当有筛选条件时，`total` 反映筛选后的总数（空态判定依据），`today/last_7_days/older` 仍按现有口径计算（若需一致可由后端统一在有筛选时对分桶也按筛选生效，待 @BackendDev 确认）。
- 状态：无新增状态机。

## 接口与契约边界

- **请求侧**：`GET /conversation/list` 新增可选 query：`start_date_ms`、`end_date_ms`（ms 时间戳，含端点）、`agent_id`（int）、`keyword`（str）。不传 = 全量（向后兼容）。
- **响应侧**：复用现有 `ConversationResponse` 契约（`code/message/data` 信封），列表项字段不变，避免破坏前端现有消费方。
- **鉴权 / 错误**：沿用现有 `authorization` Header 与会话过期处理（`TokenExpiredError` → 401），错误码沿用 `code != 0` 约定。
- **前后端边界**：时间筛选由前端将 dayjs 区间转成 ms 时间戳传后端；名称模糊筛选由后端 SQL 完成（防止前端拉全量再筛）；智能体筛选下拉选项取前端 agent 列表服务。

## 实现步骤

### 前端（@FrontendDev）

1. 在 `SideNavigation.tsx` `ROUTE_CONFIG` 增加 `/conversation-manage` 菜单项（Icon + `labelKey` + 分组）；确认 `accessibleRoutes` 鉴权守卫放行该路径。
2. 在 `frontend/public/locales/{zh,en}/common.json` 补充 `sidebar.conversationManage` 与页面文案 key。
3. 扩展 `types/conversation.ts`：列表查询参数类型加 `startDateMs? / endDateMs? / agentId? / keyword?`。
4. 扩展 `conversationService.getList`，条件拼接 query 参数。
5. 新建 `app/[locale]/conversation-manage/` 页面，按 `memory/MemoryManager.tsx` 范式实现筛选器 + 分页表格 + 空态 + 详情查看（复用 `getDetail` 与消息渲染组件）。
6. 新建/扩展 `useConversationManagement` hook，支持筛选参数与重置；`npm run check-all` 校验 TS / lint / build。

### 后端（@BackendDev）

1. `conversation_db.py::get_conversation_list_page` 增加 `start_date_ms/end_date_ms/agent_id/keyword` 可选参数，在现有 `where` 链上用 `and_` 组合；`keyword` 用大小写不敏感的 `ilike`。
2. `conversation_management_app.py::list_conversations_endpoint` 透传这些 query 参数（`Optional`，默认 `None`）。
3. 为后端补充单元测试：日期区间、agent 过滤、名称关键词、三者组合、空结果、参数缺省行为向后兼容。
4. 与前端协商标识分桶口径在有筛选时是否同步（见待决事项 DECISION-1）。
5. 确认 `/conversation-manage` 路由在 `LEFT_NAV_MENU` 权限种子中的登记方式（DB 迁移或运行时权限），保证侧边栏可展示。

## 非功能需求（按需）

| 维度 | 要求 | 设计对策 |
| --- | --- | --- |
| 性能 | 列表分页 + 筛选不拖垮接口 | 筛选全部下推到 SQL 层 + 索引覆盖 `(create_time, agent_id)`；分页复用 `offset/limit`；名称模糊需评估全表 `ilike` 成本，数据量小时可接受，量大时见 RISK-2 |
| 安全 / 权限 | 会话数据不可越权 | 维持 `created_by == user_id` 过滤；沿用现有鉴权 / 会话过期处理 |
| 可用性 / 降级 | 空态与加载态友好 | 空态区分「无数据 / 筛选无结果」；保留 loading 与错误态 |
| 可观测性 | 排查问题 | 沿用现有 `logging` 与前端 `log`；错误码透传 |

## 验证计划

| 验证项 | 方式 | 对应 AC- |
| --- | --- | --- |
| 日期范围筛选生效 | 选区间 → 列表只含区间内创建会话 | AC-1 |
| 智能体筛选生效 | 选 agent → 列表只含该 agent 会话 | AC-2 |
| 名称关键字模糊筛选 | 输入关键字 → 列表只含标题匹配会话 | AC-3 |
| 三条件组合 | 同时选区间 + agent + 名称 → 交集结果 | AC-4 |
| 查看完整消息 | 点击会话 → 详情展示完整历史 | AC-5 |
| 空态 | 无匹配（或筛选无结果）→ 展示空态 | AC-6 |
| 向后兼容 | 不传筛选参数 → 行为与现状一致（含分桶 metadata） | 回归 |

## 需求追溯

| AC- / FR- / BR- | 设计决策摘要 | 实现步骤引用 |
| --- | --- | --- |
| AC-1 | 后端 `start_date_ms/end_date_ms` 区间过滤 | 后端步骤 1、前端步骤 3-5 |
| AC-2 | 后端 `agent_id` 过滤 + 前端 agent 下拉 | 后端步骤 1、前端步骤 2-5 |
| AC-3 | 后端 `keyword` ilike 模糊 + 前端输入框 | 后端步骤 1、前端步骤 5 |
| AC-4 | SQL 层 `and_` 组合三条件 | 后端步骤 1 |
| AC-5 | 复用 `getDetail` + 现有消息渲染 | 前端步骤 5 |
| AC-6 | Table + Empty 空态 | 前端步骤 5 |
| 非目标（编辑/删除/全文搜索/导出） | 明确不做 | 非目标 |

## 风险与边界

| 编号 | 风险 | 缓解 |
| --- | --- | --- |
| RISK-1 | Confluence / JIRA 未配置域名与凭据（`config.yaml` 为占位符 `http://your-domain.atlassian.net...`，环境无 `JIRA_*`/`CONFLUENCE_*` 变量），设计文档无法按 platform skill 发布到 Confluence | 本次以 **Git 仓库 `docs/design/CHEN-183/design.md`** 作为稳定引用回传；Confluence 发布步骤保留为后续（凭据就绪后由 platform skill 落地） |
| RISK-2 | `conversation_title` 全表 `ilike %kw%` 在话量极大时触发顺序扫描 | 数据量小（当前阶段）直接可用；量大时评估 `pg_trgm` 或既有 title 倒排；纳入性能验证 |
| RISK-3 | 新增侧边栏路由若无 `LEFT_NAV_MENU` 权限记录，菜单不展示 / 路由守卫拦截 | 由 @BackendDev 确认权限种子机制并补齐 `/conversation-manage`；前端同步 `accessibleRoutes` |
| RISK-4 | 分桶 metadata 在有筛选时的口径可能误导「总数」展示 | 空态以 `total` 为准；分桶口径是否随筛选取决于 DECISION-1 |
| RISK-5 | FrontendDev 的现有 chat 页与会话侧栏共用 `getList`，改签名可能波及 | `getList` 新增参数全可选 + 默认不传保持原行为，避免破坏现有消费方 |

## 待决事项

| 编号 | 问题 | 负责人 | 截止 |
| --- | --- | --- | --- |
| DECISION-1 | 有筛选条件时，`today / last_7_days / older` 分桶是随筛选同步还是保持全量口径 | @BackendDev + Leader | 实现前 |
| DECISION-2 | `/conversation-manage` 菜单挂靠的导航分组与可见角色范围（影响 `LEFT_NAV_MENU` 权限种子） | @Leader（产品） | 开发启动前 |

## 评审回应

| 评审项 | 原意见 | 处理摘要 | 备注 |
| --- | --- | --- | --- |
| （本轮新稿，待评审） | — | — | 无历史评审 |

## 上下游协作

- 路由与页面遵循 `nexent-frontend` skill 约定（kebab-case route、i18n、`getEffectiveRoutePath`、`accessibleRoutes` 鉴权、`check-all` 校验）。
- 后端遵循 `nexent-backend` skill 约定（`consts` 集中、查询收敛到 service / db 层、错误码契约不破坏）。

## 交付说明（本 run）

设计产物落位到 Git 仓库 `docs/design/CHEN-183/design.md`（分支 `agent/architect/02700bba0782`）。Confluence / JIRA 发布因凭据缺失暂不可用（RISK-1），以 Git 引用作为稳定参考回传 Leader。
