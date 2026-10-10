# AIDP 知识库页面拆分说明

日期：2026-10-10。

## 分支和基线

- 后续开发分支：`cj/aidp-knowledge-pages-core`。
- 工作区：`worktrees/aidp-knowledge-pages-core`。
- 从最新 `origin/develop` 的 `afa4565f1fa9a394c9fa72de45a674d1f3319521` 创建，包含该提交以前的 develop 改动。
- 从 `feat-knowledge-base-pages-refactor` 的 `5c1ea70fa1eb2f34348b4de9e41eea5daf1e7cb8` 提取本次需要的实现，没有整体合入原功能分支。
- 原功能工作区保留，已交接的上传任务、失败详情和详细信息实现仍可从原分支获取。

## 页面范围和入口

| 页面                   | 前端主要文件                                                                                           | 保留内容                                                                                                               |
| ---------------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| 知识库列表             | `frontend/ext_components/aidp/components/AidpKnowledgeConfiguration.tsx`、`AidpKnowledgeList.tsx`      | 卡片、表格、教程、搜索分页、创建时间、Nexent 创建人、权限和用户组、列宽拖动                                            |
| 知识库详情中的文件页面 | `frontend/ext_components/aidp/components/AidpKnowledgeFilesPage.tsx`                                   | 页头、文件列表、搜索分页、导入、下载、删除、页头名称描述与权限编辑                                                     |
| 导入文件               | `frontend/ext_components/aidp/components/AidpImportDrawer.tsx`、对应 CSS                               | 点击整个区域选文件、拖放、最多 50 个文件、批量请求进度、图标内透明环形进度、成功实线边框、失败条目的前端删除、确认按钮 |
| 创建知识库             | `frontend/app/[locale]/knowledges/create/page.tsx`、`AidpCreateKbPage.tsx`、`AidpCreateKbSections.tsx` | 配置表单、三类模型、接口图谱模板、提示词联动、提示信息、样式与默认折叠                                                 |

列表路由仍为 `/zh/knowledges`；选择知识库通过 `?kb=<id>` 展示文件页面。创建路由为 `/zh/knowledges/create`。旧的创建弹窗和旧文件列表组件已删除，避免两套实现并存。

不包含上传任务页、任务状态筛选、任务重试、失败详情抽屉、详细信息页及其参数编辑功能。`AidpKnowledgeDetail.tsx` 和 `AidpKnowledgeDetailInformation.tsx` 没有带入本分支。共同页头需要的 `AidpUpdateKbModal.tsx` 保留。

## 前后端共用部分

- `useAidpKnowledgeQueries.ts` 使用 Nexent 现有 React Query 组织列表、模型、图谱模板及相关修改请求；缓存按租户和账号区分。
- `aidpKnowledgeService.ts` 保留上述页面需要的请求，不新增上传任务或任务重试的方法。上传使用 XHR 获取传输进度，同一请求的进度用于每个文件行；请求完成以前保持正在上传状态，等待 AIDP 返回最终结果。
- 上传错误保留后端错误码并使用中英文翻译；无错误码时使用接口错误信息，展示在对应文件行。
- 后端 `aidp_mgmt_app.py` 保留文件分页接口 `/api/aidp-mgmt/knowledge-bases/{id}/files` 和图谱模板接口。已入库文件的搜索和分页交给 AIDP，避免 Nexent 全量读取。
- 创建配置适配实际 AIDP 接口：模型一次查询，图谱参数由模板获取，`graph_config` 提交为 JSON 字符串，使用七个模板字段和 `llm_model_name`。不发送额外图谱 TOP K 参数。
- `aidp_creator_service.py` 从本地权限记录的创建人 ID 批量查询当前租户 Nexent 用户名称；权限和用户组仍由 Nexent 管理。
- develop 原有 History 兼容接口保留，没有迁入原功能分支新增的上传任务筛选、重试或详细信息参数更新逻辑。
- 保留最新 develop 的管理接口线程调度实现，部署前后端使用同一提交。

## Mock 范围

Mock 仅迁入模型和完整中文图谱模板、创建配置校验与保存、中文知识库和已入库文件示例、文件搜索分页、上传结果模拟，以及默认 10 秒上传响应延迟。模板数据文件为 `test/ext_components/aidp/mock_servers/graph_config_template_chinese.json`。

原有兼容接口保留；没有迁入上传任务筛选和重试、失败任务样例、详细信息专用样例。现有持久化 state 和本机数据库继续使用，不重置。上传延迟可用 `--upload-seconds 0` 关闭，便于快速自动化测试。

## 后续合代码

本分支可以单独评审合入 develop。不要为了取得这四部分页面，再整体合并原功能分支，否则会把已交接部分一并带入。

同事继续开发详情时，可在独立文件中实现上传任务和详细信息，再将入口接入详情页面。合代码时重点检查路由入口、`aidpKnowledgeService.ts`、`services/api.ts`、类型、翻译、后端管理路由和 mock，避免互相覆盖。文件页面已拆成独立组件，便于保留现有文件功能。

知识库教程展开状态、卡片/表格视图以及表格列显示设置保存在当前标签页的 `sessionStorage` 中；从知识库配置离开再返回时恢复。表格只有知识库名称可进入详情，点击其余单元格不会导航。知识库卡片和表格每 30 秒查询当前页，后台标签页、详情页面以及导入抽屉或删除确认框打开期间暂停；恢复可见时刷新。定时刷新保留已有数据与用户设置，失败显示错误区域。列表和文件页均在确认、取消或 X 关闭导入抽屉后刷新一次；上传完成回调不刷新来源列表。完整约定见 [页面验收用例](aidp-knowledge-pages-core-acceptance.md)。

Mock 新增 `POST /_mock/file-faults`：`query_seconds` 设置文件查询延迟（0～30 秒），`query_fail` 设置查询失败，`delete_fail` 设置逐文件删除失败；默认全部关闭，重启清除，不修改持久化文件。测试结束调用不带参数的同一路径恢复正常。

## 验证与本地部署

前端验证包括类型检查、查询与上传错误组件测试、列宽测试、创建表单与图谱模板测试、导入文件交互测试，以及文件页面仅展示文件列表和传递搜索词的回归测试。后端验证包括管理接口、创建实际请求结构、mock、AIDP 服务、创建人和用户查询测试。旧测试使用的全局模块替身会互相影响，后端不同测试文件按独立 pytest 进程执行。

本地运行遵循 `DEV-GUIDE.md`：Windows 前端与 WSL 后端均从 `worktrees/deploy` 启动，切换部署提交前先停止服务。保持 `ENABLE_AIDP_KNOWLEDGE=true`、`AIDP_SERVER_URL=http://127.0.0.1:30081` 和固定历史数据目录；不提交本机 env 或持久化 state。
