# 知识库详情页遗留问题交接：has_more 误报、删除状态列与失败任务功能验证

> 日期：2026-10-16
> 状态：问题 1 待定位修复；问题 2 已实现、待真实环境验证；问题 3 功能已实现、待真实环境验证
> 基线分支：`develop_st` @ `72101dbcf`（Feat(aidp): Knowledge base details: file delete status column and re-delete guard）
> 页面入口：`/knowledges/detail?kb=xxx`，文件表使用 `/files` 端点，上传任务表使用 `/upload-tasks` 端点（禁止回退到旧 `/documents` 混合视图）

## 0. 文档定位

本文交接 AIDP 知识库详情页的三个遗留事项，供后续开发接手：

1. **问题 1（待修复）**：已上传文件列表和上传任务列表带关键词搜索时，结果为空或不足一页，接口仍返回 `has_more=true`，前端分页控件显示"还有第二页"，点击后是空页。
2. **问题 2（已实现、待验证）**：已上传文件列表新增"删除状态"列（`file_status`），删除中的文件置灰删除按钮和批量复选框。该更改在最后一次提交 `72101dbcf` 中完成，尚未验证。
3. **问题 3（已实现、待验证）**：上传任务列表中失败任务的"失败详情"抽屉和"重新提取"操作，待真实环境验证。

---

## 1. 问题 1：搜索结果不足一页时 has_more 误报

### 1.1 现象

- 复现路径：知识库详情页 → "已上传文件"或"上传任务"页签 → 输入关键词搜索。
- 当搜索结果为空或不足一页（< page_size）时，后端接口返回 `has_more=true`，前端分页显示存在第二页；翻到第二页后为空页（文件列表有空页自动回退逻辑，任务页签需确认行为）。
- 不带关键词时正常（该路径 `total_reliable=true`，用 Count 接口/全局统计计算 `has_more`）。

### 1.2 分页契约与根因分析

当前分页契约（2026-10-15 PR review P2 修复后确立）：

1. 未过滤列表（无 keyword、status=0）：`total_reliable=true`，`has_more = total > page * page_size`。
2. 过滤查询（有 keyword，任务表另有 status≠0）：`total_reliable=false`，上游 AIDP 的**显式分页信号**（`has_more` 布尔或 `next_link`）是权威信号，**禁止用行数推断覆盖**——即使当前页是短页。
3. 上游完全没有分页信号时才允许行数推断（`len(rows) >= page_size`）。

`has_more` 计算位置：

- [aidp_mgmt_app.py](../../backend/ext_components/aidp/apps/aidp_mgmt_app.py) `_history_reports_more()`（约 L532-545）：只信任 `has_more` 布尔或 `next_link` 键。
- `/files` 端点 `list_ingested_files`（约 L1137-1212）：带 keyword 时 `count_result=None` → `total_reliable=false` → `has_more` 走 `reported_more`。
- `/upload-tasks` 端点 `list_upload_tasks`（约 L1215-1297）：filtered 时 `total_reliable=false` → `has_more` 走 `reported_more`。

**根因假设（待真实环境确认）**：真实 AIDP 的 `next_link`/`has_more` 按未过滤全集计算（过滤条件在分页计算之后才应用，与 History 端点 `total_record_count` 是过滤前全局统计的行为一致）。因此过滤后只剩 3 条甚至 0 条时，`page * page_size < 未过滤总数` 仍成立，上游照常返回下一页信号。

**为什么本地 mock 复现不了**：mock 服务（[aidp_mgmt_mock_server.py](../../test/ext_components/aidp/mock_servers/aidp_mgmt_mock_server.py)）的 `KnowledgeFiles`（约 L1334-1388）和 `KnowledgeFiles/History`（约 L1521-1611）都是先应用 keyword/status 过滤、再按 `end < len(filtered)` 计算 `next_link`，分页语义正确。该问题只能在真实 AIDP 联调环境观察。

### 1.3 关键代码位置

| 层 | 文件 | 说明 |
|---|---|---|
| 后端 has_more 计算 | `backend/ext_components/aidp/apps/aidp_mgmt_app.py` | `_history_reports_more` L532-545；`/files` L1137-1212；`/upload-tasks` L1215-1297 |
| 后端上游请求 | `backend/ext_components/aidp/services/aidp_service.py` | `list_aidp_docs_impl` L1667+（keyword 透传 L1683-1685）；`list_aidp_doc_history_impl` L1964+ |
| 前端分页控件 | `frontend/ext_components/aidp/shared/components/AidpPagination.tsx` | `effectiveTotal` L39-43：`totalReliable=false` 时 `hasMore ? currentPage*pageSize+1 : currentPage*pageSize`，即 `has_more=true` 必然渲染出下一页 |
| 前端文件表 | `frontend/ext_components/aidp/pages/knowledge-files/AidpKnowledgeFilesPage.tsx` | `fileHasMore` L134；空页自动回退 L178-204；分页挂载 L724-730 |
| 前端任务表 | `frontend/ext_components/aidp/pages/knowledge-files/AidpKnowledgeTasksTab.tsx` | `taskHasMore` L90；分页挂载 L376-382 |
| 前端 service | `frontend/ext_components/aidp/shared/services/aidpKnowledgeService.ts` | `listIngestedFiles` L307-333；`listUploadTasks` L338-372 |
| mock | `test/ext_components/aidp/mock_servers/aidp_mgmt_mock_server.py` | `KnowledgeFiles` L1334-1388；`History` L1521-1611（过滤后计算 next_link，与真实 AIDP 行为不一致） |

### 1.4 修复方向（需先确认根因，再权衡）

1. **先取证**：在真实 AIDP 环境，用带 keyword 的请求直接观察上游原始响应（`next_link`/`has_more`/`total_count` 在空结果、短页时的实际值），确认"按未过滤全集计算分页"的假设。可在 `list_aidp_docs_impl`/`list_aidp_doc_history_impl` 的日志中补充原始 payload。
2. **AIDP 侧修复（首选）**：若确认是上游缺陷，推动 AIDP 在应用过滤后再计算分页信号。修复后现有后端逻辑无需改动。
3. **后端防御（若上游不可改）**：过滤查询（`total_reliable=false`）且短页（`len(rows) < page_size`）时不信任显式信号，按最后一页处理。**注意**：这会推翻"显式 next_link 在短页上也是权威信号"的既有契约——该契约是为了防另一类误报（真实 AIDP 中间页可能短页但仍有后续数据）。改动前必须确认真实 AIDP 过滤查询不会出现"短页但真有下一页"的情况，否则会把一种误报换成另一种。建议同步更新 `test/backend`/`test/ext_components` 中相关 UT 的契约断言。
4. **前端兜底（可选补充，不作为根治）**：任务页签可参照文件页签的空页回退逻辑（`AidpKnowledgeFilesPage.tsx` L178-204）处理空页；但分页控件显示"第二页"的误导仍在，根治应以 `has_more` 正确为准。

### 1.5 验证要点

- 带关键词搜索：结果为空 → 只有一页；结果 0 < n < page_size → 只有一页；结果跨页 → 分页正确。
- 任务表额外覆盖 status 过滤（含 keyword + status 组合）。
- 未过滤列表分页回归：Count 接口路径的 `has_more` 不受影响。
- `useAidpKnowledgeFiles` 的 `document_count` 同步逻辑（无 keyword 且 total_reliable 时写缓存）不受影响。

---

## 2. 问题 2：文件列表删除状态列（已实现，待验证）

### 2.1 需求与实现内容

需求：已上传文件列表新增"删除状态"列。接口已有 `file_status` 字段：`0`=已入库、`1`=删除中、`2`=删除失败。删除中的文件需置灰行内删除按钮和批量操作复选框。

已在提交 `72101dbcf` 实现：

1. **状态归一化**：`fileDeleteStatusCode()`（`aidpKnowledgeDetailUtils.ts` L100-115）接受数字和数字字符串（部分部署会把数字序列化成字符串），未识别值（缺失、越界、非数字字符串）一律回退 `0`（已入库），保证行仍可读。
2. **删除状态列**：`AidpKnowledgeFilesPage.tsx` L425-451，绿/蓝/红圆点 + 文案（已入库/删除中/删除失败），列宽基线 100、最小 90（`FILE_COLUMN_MIN_WIDTHS.file_status`）。
3. **防重复删除**：`isFileDeleting()`（L85-87）——
   - 行内删除按钮 `disabled`（L472）；
   - 批量复选框 `getCheckboxProps.disabled`（L704-706）；
   - 批量删除提交前过滤掉已变为 deleting 的行（L298-300，防陈旧选中）。
4. **删除失败的行保持可删除**（可重试）。
5. **类型**：`management.ts` L42 `file_status?: number | null`。
6. **国际化**：`frontend/public/locales/{zh,en}/common.json` 新增 `aidpKnowledge.detailFileDeleteStatus`、`aidpKnowledge.fileDeleteStatusIngested/Deleting/Failed`。
7. **单元测试**：`frontend/tests/component/aidpFileDeleteStatus.test.tsx`（148 行，覆盖归一化函数 + deleting 行复选框/删除按钮置灰、ingested/failed 行保持可用）。

### 2.2 验证要点（真实环境待办）

1. **字段形态确认**：真实 AIDP `/files`（`KnowledgeFiles`）返回的 `file_status` 是数字还是字符串，是否所有部署都有该字段；缺失时行应显示"已入库"（回退逻辑）。
2. **状态流转**：触发删除 → 行变为"删除中"（蓝点）且删除按钮/复选框置灰；删除完成后行消失；删除失败 → "删除失败"（红点）且删除按钮恢复可点（重试）。
3. **轮询**：文件表 30s 轮询（`useAidpKnowledgeFiles` `refetchInterval`）应自动刷新状态；弹窗打开时轮询暂停，关闭后恢复。
4. **批量操作**：勾选若干行后等某行变为删除中 → 批量删除提交时应自动排除该行；全部被排除时不应发出空请求。
5. **只读用户**：`canEdit=false` 时本就无删除按钮和复选框，确认无回归。
6. **国际化**：中英文文案正常显示。注意部署时必须同时同步 `.next` 构建目录和 `public/` 静态资源目录，否则会出现 i18n key 直接显示的问题。
7. **本地单测**：`cd frontend && npx vitest run tests/component/aidpFileDeleteStatus.test.tsx`（`npm run test:components` 跑全量）。

### 2.3 相关代码位置

| 文件 | 说明 |
|---|---|
| `frontend/ext_components/aidp/pages/knowledge-files/AidpKnowledgeFilesPage.tsx` | 状态列、删除守卫、批量过滤 |
| `frontend/ext_components/aidp/pages/knowledge-files/utils/aidpKnowledgeDetailUtils.ts` | `fileDeleteStatusCode`、列宽配置 |
| `frontend/ext_components/aidp/shared/types/management.ts` | `AidpDocumentItem.file_status` |
| `frontend/public/locales/{zh,en}/common.json` | 删除状态文案 |
| `frontend/tests/component/aidpFileDeleteStatus.test.tsx` | 单元测试 |

---

## 3. 问题 3：上传任务"失败详情"与"重新提取"待验证

### 3.1 功能概述

上传任务列表中，失败状态的任务行（`status=3` 向量入库失败、`status=5` 图谱入库失败）提供两个操作：

1. **失败详情**：打开右侧 Drawer，展示文件名、任务状态（红点，区分图谱/向量失败）、更新时间、错误码（`error_code`）、失败原因（`extraction_failure_reason`，回退 `reason`）。能看到该页签的用户均可查看；字段缺失时显示 `--`（UNKNOWN 兜底）。
2. **重新提取**：仅 `canEdit` 用户可见，行内与失败详情抽屉底部各一个入口（只读用户仅显示"失败详情"，行级 canEdit 判断于 2026-10-12 G-1 修复）。点击后调用 `POST /knowledge-bases/{kds_id}/upload-tasks/retry`（body `{file_uuids: [...]}`，当前为单文件逐行触发）；成功提示"已提交重新提取"、关闭抽屉并刷新列表；上游 `failed_list` 非空时按语言取 `reason_zh`/`reason_en`/`message`/`reason` 展示失败原因。

### 3.2 关键代码位置

| 层 | 文件 | 说明 |
|---|---|---|
| 前端任务页签 | `frontend/ext_components/aidp/pages/knowledge-files/AidpKnowledgeTasksTab.tsx` | 操作列 L240-272（仅 code 3/5 渲染，重提取带 canEdit）；`handleRetry` L123-161；失败详情 Drawer L392-473 |
| 前端 service | `frontend/ext_components/aidp/shared/services/aidpKnowledgeService.ts` | `retryUploadTasks` L377-391 |
| 后端端点 | `backend/ext_components/aidp/apps/aidp_mgmt_app.py` | `retry_upload_tasks` L1300-1323：要求 EDIT 权限，UUID 去重，成功后失效 KB 详情/文档数缓存，上游调 `retry_aidp_docs_impl` |
| mock | `test/ext_components/aidp/mock_servers/aidp_mgmt_mock_server.py` | `KnowledgeFiles/Retry` L1614+ |

### 3.3 验证要点（真实环境待办）

1. **字段形态**：真实 AIDP History 返回的 `error_code`、`extraction_failure_reason`（或 `reason`）的字段名与文案；缺失时抽屉应显示 `--`。
2. **重新提取成功流转**：提交后任务回到"排队中/提取中"，30s 轮询或手动刷新可见状态变化；最终成功后从失败筛选中消失、失败统计减少。
3. **重新提取失败**：上游 `failed_list` 非空时前端按语言展示失败原因，任务状态不变。
4. **只读用户**：`canEdit=false`（DEV 角色 + READ_ONLY 组授权场景）行内与抽屉均无"重新提取"按钮，仅"失败详情"。
5. **权限边界**：只读用户直接调 retry 接口应 403（后端 EDIT 校验）。
6. **非失败行**：成功/提取中/排队中行不渲染操作按钮。
7. **mock 预验证**：`aidp-kb-faq` 有 18 条任务数据（含图谱入库失败 1 条），可先在 mock 跑通基础链路，再到真实环境验证字段与流转。

---

## 4. 本地验证环境备忘

- **后端 UT**：根目录 `pytest test/ext_components/aidp -v`（aidp_service.py / aidp_mgmt_app.py 已有 518 个用例，覆盖率 99%/100%）；改动 has_more 逻辑需同步补充/调整契约断言。
- **前端检查**：`develop_st` 预存约 1518 个 lint 问题（未改动文件），`npm run check-all` 整体必败于 lint；自己改动的文件单独跑 `npx eslint <files>` 和 `npx prettier --check <files>`。
- **mock 数据**：仅 `aidp-kb-faq`（政务服务与城市治理知识库）有任务数据（18 条，含图谱入库失败 1 条、排队中 2 条）；owner=suadmin、ingroup_permission=READ_ONLY、group_ids=[2,4,5,6]，可作只读场景回归数据。
- **mock 局限**：mock 的 next_link 语义正确（见 1.2），无法复现问题 1；问题 1 的取证与修复验证必须在真实 AIDP 联调环境进行。
- **test-e2e D1**：本地运行用 `backend\.venv\Scripts\python.exe test-e2e\infra\tools\run_cases.py <Case-ID> --test-home C:\Users\s30032556\AppData\Local\Temp\nexent-test-home`（必须用 venv python，系统 python 缺 yaml 模块）。

## 5. 约束与注意事项

- 文件表用 `/files`、任务表用 `/upload-tasks`，禁止复用旧 `/documents` 混合视图逻辑。
- 详情页改动尽量少碰知识库列表页代码，减少并行开发冲突。
- 若修改"显式 next_link 是权威信号"的分页契约（1.4 方向 3），需在 PR 描述中明确记录推翻原因与新契约，并保留未过滤路径的既有行为。
- 新增/修改源文件需带版权头 `Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.`（Markdown 交接文档不要求）。
