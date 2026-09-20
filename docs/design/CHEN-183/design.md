# 技术设计 — CHEN-183 对话管理功能

| 字段 | 值 |
| --- | --- |
| **创建者** | Architect-9e918769-33c2-406f-a9aa-ac60396f4875 |
| **创建时间** | 2026-09-18 15:25 |
| **版本** | v0.3 |
| **状态** | 草稿 |
| **JIRA** | CHEN-183 |
| **上游 PRD** | 无法发布（Confluence/JIRA 未配置域名与凭据，见风险与边界 RISK-1） |
| **稳定引用** | `docs/design/CHEN-183/design.md`（Git，分支 `agent/architect/02700bba0782`） |

## 修订记录

| 日期 | 版本 | 作者 | 变更 |
| --- | --- | --- | --- |
| 2026-09-18 | v0.1 | Architect-9e918769-33c2-406f-a9aa-ac60396f4875 | 初稿 |
| 2026-09-18 | v0.2 | Architect-9e918769-33c2-406f-a9aa-ac60396f4875 | 按第 1 轮架构评审 FAIL（REV-1/2/3 + SUG-1~5）修订：收敛分桶口径与补种机制、升版本并逐条回应 |
| 2026-09-20 | v0.3 | Architect-9e918769-33c2-406f-a9aa-ac60396f4875 | 按第 2 轮架构评审 FAIL（REV-4，第 3 轮末轮）修订：恢复模板必备两节（实现步骤 / 非功能需求）、重算评审回应 SUG-1~5 对齐首轮实际清单、SUG 措辞按收敛口径改述、升 v0.3 并逐条登记 |

## 理解（当前系统做什么）

系统 `nexent` 是一个多智能体（agent）平台，会话（conversation）是用户与智能体问答的主载体：

- **后端** `conversation_management_app.py` 暴露 `/conversation` 路由。核心接口：
  - `GET /conversation/list`（`get_conversation_list_page`，行 877）：按**创建时间倒序**分页返回**未删除**会话（`delete_flag == 'N'`），并给出 `total / today / last_7_days / older` 分桶计数（`conversation_db.py` line 894 起窗口计数机制）。
  - `GET /conversation/{conversation_id}`：返回会话详情（完整消息历史），由 `get_conversation_history_service`（行 708）承接，消息按 `message_id`、`unit_id` 组织。
  - 其余：`POST /create`、`POST /rename`、`POST /sources`、`POST /generate_title`、`POST /message/update_opinion`、`DELETE /{id}`、`POST /batch-delete` 等。
- **模型**：`ConversationRequest` / `ConversationResponse`（`conversation_models.py`）已含 `conversation_title`、`agent_id`、`chat_mode` 等字段。会话树模型 `db_models.py`：`ConversationRecord`（含 `conversation_title`、`agent_id`、`create_time`）、`ConversationMessage`、`ConversationMessageUnit`、`ConversationSourceImage`、`ConversationSourceSearch`。
- **前端** `frontend`（Next.js App Router + Ant Design + react-query）：
  - `services/conversationService.ts`：`getList(offset/limit/today_start_ms/week_start_ms)` 分页拉取；`getDetail()` 拉取详情；`conversationService` 是左侧会话列表（`chatLeftSidebar.tsx`）与「对话管理」新页共用的数据源。
  - `types/conversation.ts`：`ConversationListItem`、`ConversationListPage`、`ConversationListMetadata`（total/today/last_7_days/older）。
  - `hooks/chat/useConversationManagement.ts`：`useInfiniteQuery`，queryKey `["conversations","legacy-chat"]`，`limit` 默认 20，滚底翻页。
  - 历史渲染：`app/[locale]/newchat`（assistant-ui）消息气泡 / 来源渲染组件；`memory/MemoryManager.tsx` 是「筛选器 + 分页表格 + 空态」成熟页面范式；`SideNavigation.tsx` 由 `ROUTE_CONFIG` + `accessibleRoutes`（后端 `LEFT_NAV_MENU` 角色权限）驱动侧边栏菜单。

**目标（与 PRD 对齐）**：新增「对话管理」页面，支持会话列表查看与按条件筛选，满足：
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

## 实现步骤（前端 / 后端）

### 后端

1. **扩展列表查询过滤**：`conversation_db.py` 的 `get_conversation_list_page` 与 `list_conversations_endpoint` 增加**可选查询参数**（全部可选，缺省后行为与现状完全一致，保证向后兼容）：
   - `start_date_ms` + `end_date_ms`（含端点）：`create_time` 落在 `[start_date_ms, end_date_ms]` 区间内。
   - `agent_id`（int，可选）：`ConversationRecord.agent_id == agent_id`。
   - `keyword`（str，可选）：`conversation_title` 模糊包含匹配（`ilike %keyword%`，大小写不敏感）。
   - 三个维度在 SQL 层用 `and_` 组合（必然满足 AC-4 可组合）；分页复用现有 `offset/limit` 与 metadata 分桶。实现上可将过滤条件放进现有 `stmt` 的 `.where(...)` 链（`get_conversation_list_page`，已有 `user_id` 条件与 `delete_flag` 过滤，直接在其上加条件即可）。
2. **版本化补种迁移（REV-2 已收敛）**：为 `/conversation-manage` 提供侧边栏路由**权限种子**，新增**版本化迁移**（`deploy/sql/migrations/`，参照现有逐路由补种范式）：
   - 迁移为**持有 `conversation` 列表 / `chat` 相关 role** 的角色补种 `/conversation-manage` 路由（`LEFT_NAV_MENU` 条目），**不含 SU**（SU 现有种子无 `/chat`，故不含——见评审回应 SUG-1）。
   - 迁移**幂等可回滚**（`if not exists` / 可逆 down），与现有逐路由补种模式保持一致。
   - 若保留索引覆盖 `(create_time, agent_id)`，属 **DDL**，并入**版本化迁移补种批次**同批、可回滚（见评审回应 SUG-2）。

### 前端

1. **路由与侧边栏**：新增路径 `/conversation-manage`。在 `SideNavigation.tsx` 的 `ROUTE_CONFIG` 增加菜单项（Icon 用 lucide 图标库，`labelKey` 指向新的多语言 key），并因侧边栏由后端 `LEFT_NAV_MENU` 角色权限驱动，同步 `accessibleRoutes` 到需鉴权可访问列表。新增路由依赖**版本化权限补种迁移**（见后端步骤 2）生效。
2. **页面组件**：新建页面目录（如 `frontend/app/[locale]/conversation-manage/`），复用 `memory/MemoryManager.tsx`「筛选器 + 分页表格 + 空态」范式：
   - **筛选区**：日期范围（`DatePicker.RangePicker`，dayjs 区间 → `start_date_ms/end_date_ms`）、智能体下拉（`Select`，选项来自 agent 列表服务）、名称关键字输入框（`Input`，模糊搜索，可带防抖）。
   - **列表区**：`Table`（列：标题、智能体、创建时间、更新时间、操作「查看」），服务端分页（`offset/limit`）。
   - **空态（AC-6）**：无匹配时展示 `Empty`（复用 `memory` 页空态风格），区分「初始无数据」与「筛选无结果」文案；**加载态**：首屏 `Spin`/骨架，筛选变化时局部 loading。
   - **详情查看（AC-5）**：点击「查看」→ 复用 `conversationService.getDetail()` + 现有 `newchat`（assistant-ui）消息气泡 / 来源渲染组件展示完整只读会话。
   - 多语言：在 `frontend/public/locales/{zh,en}/common.json` 补充 `sidebar.conversationManage` 与页面文案 key。
3. **查询 Hook**：扩展 `useConversationManagement`，支持筛选参数（`startDateMs/endDateMs/agentId/keyword`），筛选变化时 `refetch` / reset queryKey。

## 非功能需求（按需）

| 类别 | 承诺 | 实现对策 |
| --- | --- | --- |
| 性能 | 有筛选时列表查询与分桶同一次查询、同 WHERE 链、**无子查询**；分页 `offset/limit` 保持 | 过滤条件并入现有 `stmt.where(...)` 链；`keyword` 模糊匹配扫描量受控 |
| 性能（索引） | **若保留索引覆盖 `(create_time, agent_id)` 即 DDL** → 并入版本化迁移补种批次、可回滚、不含 SU | 见后端步骤 2 / 评审回应 SUG-2；否则不引入该索引 |
| 安全 | 会话归属维持 `created_by == user_id` 越权边界；`conversation-manage` 菜单受 `LEFT_NAV_MENU` 角色权限控制 | 复用现有 `authorization` Header 与会话过期处理（401）；侧边栏由 `accessibleRoutes` 鉴权 |
| 可用性 | 筛选 / 分页变化不整页刷新；空态 / 加载态明确区分 | 前端步骤 2（空态 / 加载态） |
| 可观测性 | 后端查询日志包含**筛选参数**（日期区间 / agent / keyword）与分桶口径 | 后端步骤 1 实现时在日志入参补齐（见评审回应 SUG-5） |

## 接口与契约边界

- **请求侧**：`GET /conversation/list` 新增可选 query：`start_date_ms`、`end_date_ms`（ms 时间戳，含端点）、`agent_id`（int）、`keyword`（str）。不传 = 全量（向后兼容）。
- **响应侧**：复用现有 `ConversationResponse` 契约（`code/message/data` 信封），列表项字段不变，避免破坏前端现有消费方。
- **鉴权 / 错误**：沿用现有 `authorization` Header 与会话过期处理（`TokenExpiredError` → 401），错误码沿用 `code != 0` 约定。
- **前后端边界**：时间筛选由前端将 dayjs 区间转成 ms 时间戳传后端；名称模糊筛选由后端 SQL 完成；智能体筛选下拉取前端 agent 列表服务。

## 验证计划

| 验证项 | 方式 | 对应 AC- |
| --- | --- | --- |
| 日期范围筛选生效 | 选区间 → 列表只含区间内创建会话 | AC-1 |
| 智能体筛选生效 | 选 agent → 列表只含该 agent 会话 | AC-2 |
| 名称关键字模糊筛选 | 输入关键字 → 列表只含标题匹配会话 | AC-3 |
| 三条件组合 | 同时选区间 + agent + 名称 → 交集结果 | AC-4 |
| 查看完整消息 | 点击会话 → 详情展示完整历史 | AC-5 |
| 空态 | 无匹配（或筛选无结果）→ 展示空态 | AC-6 |
| 分桶随筛选同口径 | 有筛选时 total 与四桶同 WHERE 链、无子查询 | AC-1 + REV-1 |
| 向后兼容 | 不传筛选参数 → 行为与现状一致（含分桶 metadata） | 回归 |

## 需求追溯

| AC- / FR- / BR- | 设计决策摘要 | 实现步骤引用 |
| --- | --- | --- |
| AC-1 | 后端 `start_date_ms/end_date_ms` 区间过滤 | 后端步骤 1、前端步骤 2 |
| AC-2 | 后端 `agent_id` 过滤 + 前端 agent 下拉 | 后端步骤 1、前端步骤 2 |
| AC-3 | 后端 `keyword` ilike 模糊 + 前端输入框 | 后端步骤 1、前端步骤 2 |
| AC-4 | SQL 层 `and_` 组合三条件 | 后端步骤 1 |
| AC-5 | 复用 `getDetail` + 现有消息渲染 | 前端步骤 2 |
| AC-6 | Table + Empty 空态 + 加载态 | 前端步骤 2 |
| 非目标（编辑/删除/全文搜索/导出） | 明确不做 | 非目标 |

## 风险与边界

| 编号 | 风险 | 缓解 |
| --- | --- | --- |
| RISK-1 | Confluence / JIRA 未配置域名与凭据，设计文档无法按 platform skill 发布到 Confluence | 本次以 **Git 仓库 `docs/design/CHEN-183/design.md`** 作为稳定引用回传；Confluence 发布步骤保留为后续 |
| RISK-2 | `conversation_title` 全表 `ilike %kw%` 在话量极大时触发顺序扫描 | 数据量小（当前阶段）直接可用；量大时评估 `pg_trgm` 或既有 title 倒排；纳入性能验证 |
| RISK-3 | 新增侧边栏路由若无 `LEFT_NAV_MENU` 权限记录，菜单不展示 / 路由守卫拦截 | **REV-2 已收敛**：通过版本化迁移为持会话/chat 相关角色权限角色补 `/conversation-manage`（**不含 SU**，SU 现有种子无 `/chat`，故不含）；幂等可回滚；前端同步 `accessibleRoutes` |
| RISK-4 | 分桶 metadata 在有筛选时的口径可能误导「总数」展示 | **REV-1 已收敛**：有筛选时四桶随筛选同口径、与 total 同一 WHERE 链、无子查询；空态以 `total` 为准 |
| RISK-5 | FrontendDev 的现有 chat 页与会话侧栏共用 `getList`，改签名可能波及 | `getList` 新增参数全可选 + 默认不传保持原行为，避免破坏现有消费方 |

## 待决事项

| 编号 | 问题 | 负责人 | 截止 |
| --- | --- | --- | --- |
| DECISION-1 | 有筛选条件时，`today / last_7_days / older` 分桶是随筛选同步还是保持全量口径 | **已收敛（Leader）** | 已收敛 |
| DECISION-2 | `/conversation-manage` 菜单挂靠的导航分组与可见角色范围（影响 `LEFT_NAV_MENU` 权限种子） | **已收敛（Leader）** | 已收敛 |

## 评审回应

| 评审项 | 原意见 | 处理摘要 | 备注 |
| --- | --- | --- | --- |
| REV-1 | 有筛选条件时，分桶 metadata（today / last_7_days / older）口径不明，可能误导「总数」 | **已收敛**：有筛选时四桶均按筛选后的结果集口径计算，与 `total` 同一 WHERE 链、同一次查询、无子查询（分桶与筛选同源），空态以 `total` 为准；无筛选时保持现状口径。DECISION-1 关闭 | 后端步骤 1、非功能-性能 |
| REV-2 | 新增侧边栏路由的权限种子机制不明（`LEFT_NAV_MENU`），仅「由 @BackendDev 确认」不足以作为设计 | **已收敛**：明确为**版本化增补迁移**（`deploy/sql/migrations/`），为持 `conversation`/`chat` 相关角色权限的角色补 `/conversation-manage`（**不含 SU**），幂等可回滚，与逐路由补种范式一致。DECISION-2 关闭 | 后端步骤 2、RISK-3 |
| REV-3 | 版本未升、评审回应缺失、修订记录未更新 | **已修订**：升 v0.2，修订记录补充 v0.2 行，本节逐条回应 | 修订记录 |
| REV-4 | 需恢复模板必备两节：实现步骤（前端/后端）与非功能需求 | **已修订（v0.3）**：已恢复「实现步骤（前端/后端）」与「非功能需求」两节；步骤编号与「需求追溯」（前端 1-3、后端 1-2）及「评审回应」引用一一对应；评审回应 SUG-1~5 对齐首轮实际清单 | 实现步骤、非功能需求、需求追溯 |
| SUG-1 | 权限说明一行（首轮 SUG-1） | **已采纳**：将「SU 不走 LEFT_NAV_MENU 驱动」改为「SU 现有种子无 `/chat`，故不含」，并将该一句说明落在 RISK-3 / 后端步骤 2 / 评审回应 REV-2 | 后端步骤 2、RISK-3 |
| SUG-2 | 若保留 `(create_time, agent_id)` 索引即 DDL，须并入版本化迁移补种批次，勿静默删去该表述 | **已采纳**：索引表述不再静默消隐——若保留该索引覆盖即 DDL，并入版本化迁移补种批次（同批、可回滚、不含 SU），见非功能-性能与后端步骤 2 | 后端步骤 2、非功能-性能 |
| SUG-3 | 建议前端复用现有筛选器 + 表格 + 空态页面范式 | **已采纳**：复用 `memory/MemoryManager.tsx` 范式（前端步骤 2） | 前端步骤 2 |
| SUG-4 | 建议消息详情复用现有消息渲染组件（assistant-ui / chat 页） | **已采纳**：详情复用 `getDetail()` + 现有消息气泡 / 来源渲染组件（前端步骤 2） | 前端步骤 2 |
| SUG-5 | 后端日志含筛选参数（首轮 SUG-5） | **已采纳**：后端查询日志入参补齐筛选参数（日期区间 / agent / keyword）与分桶口径，见非功能-可观测性 | 非功能-可观测性、后端步骤 1 |

## 上下游协作

- 路由与页面遵循 `nexent-frontend` skill 约定（kebab-case route、i18n、`getEffectiveRoutePath`、`accessibleRoutes` 鉴权）。
- 后端遵循 `nexent-backend` skill 约定（`consts` 集中、查询收敛到 service / db 层、错误码契约不破坏）。

## 交付说明（本 run）

设计产物落位到 Git 仓库 `docs/design/CHEN-183/design.md`（分支 `agent/architect/02700bba0782`）。Confluence / JIRA 发布因凭据缺失暂不可用（RISK-1），以 Git 引用作为稳定引用回传 Leader。
