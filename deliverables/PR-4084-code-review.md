# PR #4084 Code Review — i18n 英文界面中文残留修复

- **PR**: [ModelEngine-Group/nexent#4084](https://github.com/ModelEngine-Group/nexent/pull/4084) `fix(i18n): 修复问题英文界面有中文`
- **作者**: yunshuang-hw · 6 commits · 4 files · +568/−146 · `ai-assisted` 标签
- **基准**: merge-base `639e8c1c0`（develop 已领先 1 提交，PR 已 merge 过一次 develop）
- **验证方法**: 除代码审读外，用仓库本地 `frontend/node_modules/i18next@25` 对配置改动做了**行为实测**（before/after 对比）

---

## 总体评价

**方向正确、一半修复真实有效，但 PR 描述的核心技术论断不成立。**

PR 分两部分：① `MemoryManager.tsx` 把 180 行硬编码中文字面量改为 `t()` + 补 48 个 `memory.manager.*` key（en/zh 对齐）——这是**真实有效的修复**；② `i18n.tsx` 加 `keySeparator: false, nsSeparator: false`——实测证明这行配置**修的不是问题**，因为带点 flat key 在默认配置下本来就能解析。

真正导致"英文界面显示中文"的原因没有被完整处理：**56 个代码在用的 key 在 en/zh locale 里根本不存在**。

---

## 🔴 Blocker

### B1. 56 个代码在用的 i18n key 缺失，"英文界面有中文"的根源未修

我用脚本全量扫描了 `frontend/` 源码中 `t('...')` 的静态 key（3579 个），对照 PR head 的 `en/common.json`（5940 keys），发现 **56 个 key 在代码中使用但 locale 文件中不存在**，且在 merge-base 上也不存在（存量缺口，非本 PR 删除）：

- `officialAgent.*` 40 个：`officialAgent.wizard.next/back/install/installing/mcp/model/rename/select`、`officialAgent.rename.*`、`officialAgent.installModal.*` 等
- `modelConfig.*Dialog.apiKey/baseUrl` 6 个（addDialog/editDialog/batchEdit）
- `workbench.creation.*` 8 个（agentDraftSaved/skillCreated/openAgent 等）
- 其他：`common.select`、`common.selected`、`common.error.loadFailed`、`a2a.security.requirementRequired`、`mcpTools.publish.tagsInheritedHint`、`notifications.deepLink.mcpNotFound` 等

**为什么这些表现为"英文界面有中文"**：key 缺失时 i18next 返回 key 本身或组件内的中文 fallback，用户看到的是英文页面里夹杂 key 字符串或中文兜底。本 PR 只修了 MemoryManager 一处，其他页面（官方智能体向导、模型配置对话框、工作台创建流程）的残留原样保留。

**建议**：把 56 个 key 补进 en/zh（或单独开 follow-up PR），否则这个 fix 只修了问题的二十分之一。

## 🟡 Suggestions

### S1. PR 描述的技术论断与实测结果不符（应修正描述，避免误导后人）

PR 描述称：带点 key（如 `modelConfig.advancedConfig.temperature`）"被当作嵌套结构查找失败"，需要 `keySeparator=false` 强制 flat 查找。

**实测**（i18next 25，仓库本地依赖）：

```
=== BEFORE: default (keySeparator=".") ===
  flat key (memory)   => "Failed to load memory list."   ← 带点 flat key 正常解析
  plural count=2      => "2 matching installed MCP tools" ← 复数正常
  returnObjects array => [ok len=6]                       ← 对象返回正常
=== AFTER: keySeparator:false + nsSeparator:false ===
  （全部行为完全一致）
```

原因：i18next 的解析顺序是先按 separator 拆嵌套路径查找，**失败后回退用整串 key 直接匹配**。既然 `common.json` 本来就是 flat 结构（5940 个 key、深度 1、无嵌套对象——merge-base 上唯一的嵌套块 `model.dialog.error.provider` 也被本 PR 拍平了），默认配置从未导致过查找失败。

**建议**：`modelConfig.advancedConfig.temperature` 显示中文的真正原因是该 key 在 en locale 里不存在（属于 B1 的缺口）。建议在 PR 描述中更正归因；配置本身无害，可保留可回退，但不应作为"修复"来表述。

### S2. 321KB 二进制截图进入了 git 历史

`caeb12656` 把 `doc/04_国际化-i18n.jpg`（321898 字节）提交进仓库，`d0e8e3749` 又删除了它。最终 diff 干净，但**这个二进制将永远留在 git 历史里**，所有 clone 都要背着它。

**建议**：验证截图放 PR 描述（GitHub 上传）而不是 commit。若在意历史整洁，可以 squash 这两个 docs 提交（注意：develop 分支流入的 squash 约束不适用于 feature → develop 的场景，需按仓库合并规约处理）。

### S3. commit 历史可以更干净

6 个提交里 2 个是"加截图/删截图"的自抵消对，1 个是 merge develop。最终有效改动只有 3 个逻辑单元（i18n 配置、MemoryManager 改造、locale 对齐）。非阻塞，仅供合并方式参考。

---

## ✅ 验证通过的部分

- **en/zh 完全对齐**：两侧各 5940 keys，`en-only` 和 `zh-only` 均为 0
- **新增 48 个 `memory.manager.*` key 翻译质量合格**：无 "value==key" 偷懒、无 "en==zh 未翻译"（`memory.manager.loadListFailed` = "Failed to load memory list." / "记忆列表加载失败"）
- **复数 key 完整**：`nl2agent.toolRecommendations.count/selectedCount/confirmedSummary` 的 `_other` 形式 en/zh 两侧都有，实测 `count=1/2` 输出正确
- **`t(key, string)` 第二参数 fallback**：实测在 keySeparator=false 下行为不变（i18next 兼容处理），`WorkbenchLandingExamples.tsx` 的 `t("workbench.landingExamples.agent.category", "智能体创建")` 用法不受影响
- **`returnObjects` 用法安全**：`page.tsx` 的 `t("page.features", { returnObjects: true })` 实测两种配置下都正常返回数组
- **`model.dialog.error.provider` 嵌套块拍平**（ff5b9d414）：9 个子 key 变为 flat `model.dialog.error.provider.title` 等，消费者 `lib/providerError.ts` 全部用 flat 形式访问，一致
- **无越权改动**：6 个提交全部来自作者本人，diff 仅触及声明的 4 个文件

---

## 结论

| 项 | 结论 |
| --- | --- |
| 真实修复 | MemoryManager 硬编码中文 → t()（有效） |
| 无效修复 | keySeparator=false/nsSeparator=false（无害但归因错误） |
| 未修的根源 | 56 个缺失 key（officialAgent/modelConfig/workbench.creation 等） |
| 风险 | 321KB 截图留在 git 历史；其余无风险 |

**建议**：合入前补齐 56 个缺失 key（或拆 follow-up issue 明确跟踪），修正 PR 描述的归因。配置改动可留可回退。整体改动安全，无破坏性。
