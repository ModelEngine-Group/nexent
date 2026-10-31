# PR #4058 评审文案（可直接粘贴）

> PR: feat(frontend): redesign agent and chat workflows（230 files, +26677/-5040, 34 commits）
> CI 状态：type-check / test / build / CodeQL / codecov 全绿
> 结论：**Request Changes** —— 整体方向和工程质量不错，但有 5 个应在合并前处理的问题
>
> **🔄 2026-10-12 20:04 更新（eff02a570 + 2 commits）复核**：作者已修复大部分意见，状态见文末「修复复核」一节。剩余未修：字体资产（问题2）、`前端UI.md` 悬空引用（问题1）、pageSize 死控件（问题10）。

---

## 总评论（建议作为 Request Changes 的整体评论粘贴）

检视了全部 230 个变更文件（重点：resource-picker 抽屉、newchat 重构、SideNavigation、字体资产、i18n、测试资产）。整体结构清晰：五个资源抽屉共享 `AddResourceDrawer` 骨架、`AddKnowledgeDrawer` 完整保留了 embedding 模型兼容校验、删除的 4 个旧 Dialog 无残留引用、D1/D4 测试资产断言充实、PR 新增的 259 个 i18n key 中英文全部对齐。以下问题建议合并前处理：

### 🔴 应修复（blocking）

1. **悬空文档引用**：`.agents/skills/nexent-frontend/SKILL.md` 新增了两处对 `../docs/前端UI.md` 的引用并声明其为 "visual source of truth"，但该文件在仓库中不存在（全部分支历史中也没有）。要么把设计稿文档提交进来，要么移除引用，否则后续 agent 会优先读一个不存在的权威文档。

2. **字体资产问题**（`frontend/public/fonts/harmonyos-sans-sc/` + `newchat-design.module.css`）：
   - 三个字重 TTF 共约 **23.6MB**（每个 ~7.9MB）直接进仓库和 `public/`，未子集化、未转 woff2，且中文字体三个字重各自全量下载；
   - `@font-face` 声明放在 `newchat-design.module.css`（CSS module，仅 `thread.tsx` import 时生效），但 `agent-list.css`、`agent-debug.css`、`StandardTour.tsx`、`agent-config.tsx` 都引用 "HarmonyOS Sans SC" 字体族 —— 这些页面在 newchat 模块未加载时字体未注册，会静默回退系统字体。`@font-face` 应移到全局样式（`frontend/styles/globals.css`）。
   - 建议：使用子集化 woff2（常用中文字符集可压到 1-2MB/字重），或改用 `next/font/local` 获得预加载与 `font-display` 控制。

3. **`resourcePicker.empty` key 未定义**：`AddKnowledgeDrawer.tsx:572`、`AddModelDrawer.tsx` 使用 `t("resourcePicker.empty", "暂无数据")`，但该 key 在 en/zh 语言包中都不存在 —— 英文界面会显示中文兜底值"暂无数据"。语言包里已有 `resourcePicker.tag`（"Tag"/"标签"）却没被 `AddResourceDrawer.tsx:78` 的 `placeholder="标签"` 使用（此处也是硬编码中文）。请补 key 并替换硬编码。

4. **`ModelConfigModal.tsx` 是 mock 且为死代码**：内部 `NUMBER_FIELDS` 硬编码 `value: "320,000"` 等假数据，全仓（含测试）无任何调用方。既然 `AddModelDrawer` 用的是 `ModelParamsModal`（603 行、已接真实参数），建议删除 `ModelConfigModal` 或明确 TODO 说明保留原因。

5. **`components/resource-picker/index.ts` 桶导出无消费者**：所有调用方（含测试）都直接 import 子路径（如 `@/components/resource-picker/AddResourceDrawer`）。要么让调用方统一走桶导出，要么删掉 index.ts，避免两套 import 路径并存。

### 🟡 建议处理（major）

6. **i18n 硬编码中文**（违反 components-ui.md "Localize user-facing text through useTranslation"）：
   - `WorkbenchPage.tsx`：`message.warning("最多选择 20 个 Skills")`、`"资源配置保存失败"`；
   - `ParamDialog.tsx`：默认 `confirmText = "确定"` / `cancelText = "取消"`；
   - `AddKnowledgeDrawer.tsx:56-73`：`私有`、`文档`、`块`、`使用过` 等元信息文案；
   - `ToolConfigModal.tsx`：`title={`${toolName} 配置`}`。

7. **`AddToolDrawer.tsx` 18 处 `(tool: any)`**：`useToolList` 返回的 `selectableTools` 已有 `Tool` 类型（旧 `SelectToolsDialog` 同样逻辑是带类型的），建议恢复类型标注。

8. **分层依赖违规**：`components/resource-picker/AddSkillDrawer.tsx`、`AddToolDrawer.tsx` import 了 `@/app/agents/...` 下的 `SkillConfigModal`、`ToolConfigModal`、`useMergedToolParams`。architecture.md 规定 `components/` 不应依赖 `app/`。理解这是迁移中间态，建议后续 PR 把这几个模块搬进 `components/` 完成收尾（可先加 TODO）。

9. **`thread-list.tsx` 置顶持久化**：用 assistant-ui 客户端 thread id 作为 `localStorage` key（`chat.pinnedThreadIds`），对话删除或换环境后残留无效 id。轻微，但建议改用 server conversation id 或在加载时过滤不存在的 id。

### 🔵 可选（nit）

10. `AddResourceDrawer.tsx` 底部 `ResourcePagination` 的 pageSize Select（10/20/50）没有接 `onChange`，切换无效果，而所有抽屉的列表都是固定 `PAGE_SIZE = 10` 前端分页。要么实现，要么先隐藏该 Select。
11. `SideNavigation.tsx` `ROUTE_CONFIG` 用小数 `order`（0.5、1.5）插入菜单项，可用但容易撞号，建议整数序列 + 注释预留。
12. `thread-agent-registry.ts` 模块级 `overrides`/`activityTimes` Map 永不清理，长会话下缓慢增长（条目有限，可接受，建议加注释说明）。
13. `useSkillList.ts` `source === "官方"`：后端 skill source 的取值已有 "official"/"custom"/"导入"（后端默认值就是中文"导入"），前端白名单会越积越长，建议推动后端归一化为枚举值。

### ℹ️ 历史遗留（非本 PR 引入，可另行处理）

- 12 个 zh-only i18n key（`agent.deployment.a2aEnabled`、`agent.permission.readOnly`、`agent.runPolicy.maxStep` 等）在 develop 上就缺英文翻译，英文界面直接显示 key 本身。
- `useToolList.ts` 内部既有 `any`（本 PR 未恶化）。

### ✅ 做得好的

- 五个资源抽屉共享骨架，`AddKnowledgeDrawer` 完整复刻了 `KnowledgeBaseSelectorModal` 的 embedding 兼容/多模型冲突校验。
- antd v6 新 API（`size={number}`、`mask={{ closable: false }}`）使用正确。
- 全 PR 仅 6 处 `eslint-disable` 且均有理由注释；新增代码无 `console.log`。
- 删除的 4 个旧 Dialog 无残留引用。
- D1/D4 测试资产（case.yaml）包含真实断言、边界条件和 forbidden_side_effects，不是占位符。
- PR 新增的 259 个 i18n key 中英文完全对齐（en-only/zh-only 均为 0，差异全部来自历史遗留）。

---

## 附：各问题文件定位速查

| # | 问题 | 文件:行 |
|---|------|---------|
| 1 | 悬空文档引用 | `.agents/skills/nexent-frontend/SKILL.md:10,27` |
| 2 | 字体 23.6MB + @font-face 作用域 | `frontend/public/fonts/harmonyos-sans-sc/`、`newchat-design.module.css:1-27` |
| 3 | `resourcePicker.empty` 未定义 + 硬编码"标签" | `AddKnowledgeDrawer.tsx:572`、`AddModelDrawer.tsx`、`AddResourceDrawer.tsx:78` |
| 4 | ModelConfigModal mock 死代码 | `frontend/components/resource-picker/ModelConfigModal.tsx:15-18` |
| 5 | 桶导出无消费者 | `frontend/components/resource-picker/index.ts` |
| 6 | 硬编码中文 | `WorkbenchPage.tsx`（handleMountWorkbenchSkill）、`ParamDialog.tsx:16-17`、`AddKnowledgeDrawer.tsx:56-73` |
| 7 | 18 处 any | `AddToolDrawer.tsx:73-533` |
| 8 | components→app 反向依赖 | `AddSkillDrawer.tsx:15-16,29`、`AddToolDrawer.tsx:20-29` |
| 9 | pinned ids 持久化 | `thread-list.tsx:107-123` |
| 10 | pageSize Select 无效 | `AddResourceDrawer.tsx:292-302` |

---

## 🔄 修复复核（2026-10-12 20:04，head=eff02a570，新增 3 commits / 44 files +2118-316）

作者提交了 3 个修复提交：`ee12f5549`（E2E 扩展 + 只读模式导航）、`8c5e70094`（创建模板改走 Agent API）、`eff02a570`（补齐本地化 + 删除死代码）。逐项复核结果：

### ✅ 已修复（验证通过）

| 原问题 | 修复方式 | 验证 |
|--------|----------|------|
| ③ `resourcePicker.empty` 未定义 + 硬编码"标签" | 补 en/zh key；placeholder 改用 `t("resourcePicker.tags")` | key 双语齐备，且新增测试断言 placeholder 随语言切换 |
| ④ ModelConfigModal mock 死代码 | 整个文件删除 | 无残留引用 |
| ⑤ index.ts 桶导出中的 ModelConfigModal 导出 | 已从导出中移除（保留其余导出） | — |
| ⑥ WorkbenchPage 硬编码中文（2 处） | 新增 `workbench.skills.limit` / `workbench.resources.saveFailed` key | 双语齐备 |
| ParamDialog 默认"确定/取消" | 改为 `confirmText ?? t("common.confirm")` 模式 | 保留调用方覆盖能力，新增语言切换测试 |
| AddKnowledgeDrawer 元信息硬编码中文（私有/文档/块/使用过） | `toKnowledgeItem` 注入 `t: TFunction`，全部走 `resourcePicker.knowledge.*` key | 双语齐备 |
| ⑦ AddToolDrawer 18 处 `(tool: any)` | 全部改为 `Tool` 类型 | `(tool: any)` 计数 = 0 |
| SkillPopoverContent "Skill 加载失败" | 改走 i18n | 含依赖数组修复 |
| 只读模式工作流导航被禁用（新发现的自伤 bug，作者自修） | `agent-config-header.tsx` 加回 `disabled={false}` | 配套 agentConfigHeader.test + 6 个 D4 case |
| 静态医疗模板（功能问题②） | 删除 `agentCreationTemplates.ts`，改 `useAgentCreationTemplates` 从 `/agent/list` 加载，含 loading/error/empty 三态 + 重试 | 见下方新问题 |

本地化修复质量高：新增 34 个 en key，zh 全部对齐（0 缺失）；新增 `resourcePickerLocalization.test.tsx`（5 用例）静态扫描相关文件的 `t()` 调用并断言双语可解析、无残留插值、英文无中文字符——这个测试能防同类问题复发，值得肯定。

### ⚠️ 修复引入的新问题（建议提）

**N1. 「创建模板」现在等于「全部主 Agent 列表」，语义和产品意图需要确认**
`useAgentCreationTemplates` 调 `fetchAgentList`（`/agent/list`）后仅过滤 `is_main_agent !== false`。后端没有 `is_template` 概念（已确认 db_models 无此字段），这意味着：
- 模板列表 = 当前用户可见的所有主 Agent（含本租户 + ASSET_OWNER 资产租户的官方 agent）；
- 用户自己刚创建的、描述为空的 Agent 也会出现在「模板」里；
- 选中"模板"创建新 Agent 时只复制 `description` 一个字段（名字、模型、工具、prompt 都不复制）——用户看到"模板"预期会复制完整配置。
如果产品语义就是"参考已有 Agent 的描述起稿"，建议 UI 文案别叫"模板"；如果要真正的模板，需要后端支持。至少应过滤掉无描述的 Agent（空描述模板卡片没有信息量）。

### ❌ 仍未修复（原文问题编号）

| 问题 | 现状 |
|------|------|
| ① SKILL.md 引用不存在的 `../docs/前端UI.md` | 引用仍在（两处），文件仍不存在 |
| ② 字体 23.6MB TTF + @font-face 藏在 CSS module | 未动：3 个 TTF 共 24MB，`@font-face` 仍在 `newchat-design.module.css`，agent-list 等页面字体仍未注册 |
| 10 pageSize Select（10/20/50）死控件 | 仍未接 onChange |
| 功能① composer 技能选择纯视觉 mock | `TODO(mock)` 注释仍在，无禁用/提示 |
| 功能③ AddAgentDrawer 取消全选清空范围过大 | 未动 |
| 功能⑤ resumeLatest 无 loadMore 页数上限 | 未动 |
| 功能⑥ 无历史用户无 agent 切换入口 | 未动 |
| 功能⑦ `source === "官方"` 中文白名单 | 未动 |

### 更新后的建议

模板语义（N1）+ 字体（②）+ 技能 mock（功能①）是合并前建议澄清的三件事；其余未修项均为 P2/nit，可开 follow-up issue 不阻塞合并。
