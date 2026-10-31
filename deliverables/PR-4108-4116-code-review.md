# PR #4108 & #4116 双 PR 代码检视报告

- **#4108**: `🐛 Fix(knowledge): clear agent and conversation bindings when deleting knowledge bases` · cj2026-bit · 22 commits · 37 files · +1444/−106
- **#4116**: `Feat: preview AIDP documents in the browser from the bytes AIDP serves` · gs-aion · 7 commits · 25 files · +2664/−37
- 基准：4108 merge-base `0d9960d5e`（落后 develop 5）；4116 merge-base `70177dbfe`（落后 develop 6）
- 检视方式：两个 PR 均拉取本地逐文件精读 + 双向合并预演

---

# PR #4108 — 删除知识库时清理 agent/会话绑定

## 实际功能

修复"删除知识库后绑定残留"：① 删除确认弹窗显示哪些智能体在用该 KB（ES + AIDP 双路径）；② 删除时从草稿/已发布智能体版本的 `knowledge_base_search`/`aidp_search` 工具配置中移除该 KB；③ 从会话的 knowledge_scope 和 Workbench 配置中移除，选择清空时把来源置 `disabled`（而非扩大搜索范围）；④ 清理失败仅告警不阻断删除。

## 逐层验证结论

**✅ 后端级联清理（tool_db.py L577-588）**：`params = dict(instance.params)` 后整体重赋值 `instance.params = params`——这个写法特意避开了 SQLAlchemy JSONB 无 mutable 追踪的原地修改陷阱，正确。白名单按 param_name（index_names/kds_list）对应工具名（knowledge_base_search/aidp_search），映射清晰。

**✅ 会话清理（conversation_db.py L2591-2640）**：JSONB `contains({"local":{"knowledge_ids":[id]}})` 查询——PostgreSQL 的 jsonb `@>` 对数组是"包含"语义，单元素 `[id]` 能命中多元素数组，查全正确。`_remove_scope_references` 用 deepcopy 防共享引用，`mode` 置 `disabled` 而非删除分支的设计（保留"显式空选择"语义）与 PR 描述一致。`workbench_config_version += 1` 正确触发前端配置刷新。

**✅ 权限**：ES 版 `bound_agents` 端点有完整的租户检查（跨租户需 SU）+ `require_knowledge_base_read_permission`；AIDP 版走 `require_permission(READ)`，KB 不存在时优雅返回空列表（删除确认仍可用）。最新提交 `b37cb318f` 补上了权限授权，说明作者响应了检视意见。

**✅ 失败语义**：清理失败 `logger.warning` 不阻断删除（L241-246）——权衡正确：KB 已在 ES/AIDP 侧删除，回滚反而造成更难处理的中间态。

**✅ 测试**：8 个新测试文件覆盖 DB 层（tool/agent/conversation bindings）、服务层（deletion bindings/preview）、API 层，PR 声明 522 passed。

## 🟡 建议

1. **JSONB contains 查询无索引支撑**：`remove_conversation_knowledge_bindings` 对 `knowledge_scope`/`workbench_config` 做 N 资源 × 2 字段的 OR contains + `with_for_update()`——大租户（数十万会话）全表扫描 + 行锁可能拖慢删除接口数秒。删除是低频管理操作，可接受，但建议：KB 选择器预览端点（bound_agents）已有单独查询，删除路径可考虑异步化或加 GIN 索引（`deploy/sql/migrations/` 下补一条）。
2. **清理失败的可见性**：warning 日志对运维够用，但用户侧无感知——绑定了已删 KB 的智能体下次打开会看到"不可用知识库"提示（本 PR 已实现该提示，闭环成立）。可在删除成功响应里带 `cleanup_warnings` 计数字段供前端提示。💭 轻微。
3. **develop 漂移 5 个提交**：合入前 rebase 或让 CI 在 merge 前跑一次。

## 结论：✅ 可合并

0 严重 / 2 建议 / 1 轻微。核心逻辑（JSONB 语义、ORM 变更追踪、权限、失败降级）全部正确，测试覆盖充分。

---

# PR #4116 — AIDP 文档浏览器内预览

## 实际功能

新增 `GET /aidp-mgmt/knowledge-bases/{kds_id}/documents/{file_uuid}/preview` 透传 AIDP 字节流，前端按 `X-File-Name` 实际文件名选渲染器：pdf.js / docx-preview / exceljs / pptxtojson / 纯文本 / 图片六分支，文件列表点文件名全屏预览。

## 安全审查（本 PR 的核心风险面）

**✅ Office HTML 净化器（officePreview.ts L182-323）**：这是把不可信文档渲染进 DOM 的防线，实现质量高——
- 21 个 ALLOWED_TAGS 白名单 + DROPPED_TAGS 整树丢弃（script/iframe/svg/img...）
- 未知标签 unwrap 保留文本但丢交互属性
- style 双重过滤：属性白名单 + 值黑名单（`url(`/`expression(`/`javascript:`/`@import`/反斜杠）
- DOMParser 解析（不执行脚本不拉资源）后再重建节点

**✅ 超链接 scheme 过滤**：`neutralizeUnsafeLinks` 只保留 http/https/mailto/tel，且注释明确"渲染后处理"的原因（实体编码的 scheme 到那时才解码）——想得比一般实现深。

**✅ altChunk 绕过修复（二轮提交 6ad05fe0c）**：`renderAltChunks: false` 关掉了 docx-preview 内嵌 HTML 走无沙箱 `iframe[srcdoc]` 的路径——这是典型的"净化器管不到的旁路"，作者主动发现并关闭，值得肯定。

**✅ 文件名编码闭环**：后端 latin-1 响应头限制 → 全量 URI 编码 `X-File-Name` + RFC 5987 `filename*` → 前端 `decodeServedFileName` 无条件解码 + 失败回退原文。中文文件名全链路自洽。

**✅ 权限**：preview 端点 `require_permission(READ)`，与下载端点同级。

## 逐项检查

| 检查项 | 结论 |
| --- | --- |
| 新依赖供应链 | docx-preview 0.4.1 / exceljs 4.4.0 / pptxtojson 2.2.0，均**锁死精确版本**（好习惯）；pdfjs-dist 复用已有 |
| 性能 | 四个渲染库全部 `await import()` 动态加载，不打进主 bundle |
| 边界 | 无 X-File-Name 时 disposition 降级 `inline`；txt 无后缀/纯后缀/尾点均处理；svg 在 IMAGE 集合但净化器丢弃 img——预览 svg 文件实际走哪个分支需确认（见建议 2） |
| 测试 | 后端 365 行新用例 + 前端 6+19 个测试（净化器专项 19 个），mock server 支持原生/转换双路径 |
| 已知限制 | pptxtojson 的 xfrm TypeError 已在 PR 中如实声明并定为后续兜底——诚实 |

## 🟡 建议

1. **Content-Type 透传的宽松性**：`media_type=aidp_response.headers.get("Content-Type", "application/octet-stream")` 直接透传 AIDP 的值。若 AIDP 某天返回 `text/html`，浏览器按 inline 渲染会执行脚本（虽然同源脚本风险有限，但 AIDP 内容不可信）。建议白名单化：非 pdf/office/text/image 已知类型一律 `application/octet-stream`。
2. **SVG 预览分支矛盾**：`IMAGE_EXTENSIONS` 含 `svg`，但净化器 `DROPPED_TAGS` 丢弃 `img` 且 svg 走 `<img>` 渲染时浏览器会执行其中的脚本（svg 是 XML 可含 script）。需确认 svg 是经 `<img>`（脚本被浏览器禁执行，安全）还是 inline（危险）渲染；若是前者无碍，建议加注释说明。
3. **大文件内存**：`blob.arrayBuffer()` 全量载入（xlsx/pptx 分支），几百 MB 的表格会撑爆标签页。建议加大小上限（如 50MB）超限提示下载后查看。
4. **develop 漂移 6 个提交**：合入前 rebase。

## 结论：✅ 可合并（建议 1 顺手修）

0 严重 / 3 建议 / 1 轻微。安全设计是这个 PR 的亮点（净化器、scheme 过滤、altChunk 旁路关闭都是超出平均水准的实现），已知限制声明诚实。

---

# 两 PR 关联与冲突分析

## 文件重叠：8 个

`aidp_mgmt_app.py`、`aidp_service.py`、`aidpKnowledgeService.ts`、`api.ts`、`en/zh common.json`、`test_aidp_mgmt_app.py`、`test_aidp_service.py`

## 冲突实测：0

`git merge-tree --write-tree` 双向合并预演：**0 文本冲突**。合并树抽查：
- `aidp_mgmt_app.py` 中两 PR 的端点共存（`get_knowledge_base_bound_agents` L963 / `preview_document` L1212）
- `AidpKnowledgeFilesPage.tsx` 仅 4116 修改（文件名点击预览），4108 不碰该文件

## 语义关系：互补而非重复

两 PR 分别覆盖 AIDP 知识库生命周期的两端——**4108 管删除路径**（删除时的绑定清理与确认预览），**4116 管浏览路径**（文件预览）。无重复改动（bound_agents 与 preview 是不同端点，前端改的是不同组件），无语义互踩。

## 合入顺序建议

**顺序无关，可独立合入。** 唯一注意点：两者都在 `test_aidp_mgmt_app.py` 追加测试且 locale 文件追加 key，后合入的那个需 rebase 一次（纯追加性冲突，git 自动合并已验证通过）。

---

# 总结论

| PR | 严重 | 建议 | 轻微 | 判断 |
| --- | --- | --- | --- | --- |
| #4108 | 0 | 2（JSONB 索引/异步化、清理失败可见性） | 1（rebase） | **可合并** |
| #4116 | 0 | 3（Content-Type 白名单、SVG 分支确认、大文件上限） | 1（rebase） | **可合并**（建议 1 顺手修） |
| 交叉 | — | — | — | 0 冲突，顺序无关 |
