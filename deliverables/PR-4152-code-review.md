# PR #4152 代码评审

> **标题**：fix(frontend): cap workbench model selector width to keep composer controls on one row
> **作者**：lijiayang619　|　**状态**：Open　|　**规模**：7 文件 **+84 / −9**
> **commits**：2（`a12c69418` 样式修复 → `a7fa95afc` i18n 修复）
> **merge-base**：`7ca15722c`（#4143 合入点），落后 develop 4 个提交
> **检视时间**：2026-10-21

---

## 一、变更目的与整体范围

### 1.1 实际包含两块独立改动

PR 标题只描述了第一块，第二个 commit 是**另一件事**：

| # | Commit | 内容 | 文件 |
| --- | --- | --- | --- |
| 1 | `a12c69418` fix(frontend): keep workbench composer controls on one row | 模型选择器宽度上限 + 悬停显示全名 | `composer.tsx`、`model-selector.tsx`、`Composer.test.tsx` |
| 2 | `a7fa95afc` fix(frontend): localize workbench creation example titles and section labels | Skill 创建示例卡片标题与区块 aria-label 的 i18n | `CreationExamples.tsx`、locale ×2、`Composer.test.tsx`、`CreationExamples.test.tsx` |

**第 2 块是真实缺陷且修复正确**：`CreationExamples.tsx` L74-77 原来只有 `agent_create` 走 `t()`，`skill_create` 的卡片标题是**硬编码中文**，英文界面下会直接显示「发票信息提取」。现在改成无差别 `t()`，并补了 5 个 locale key（en/zh 完全对齐，无删除）。`aria-label` 也一并修了（原来的 `"Agent创建示例"` 还缺一个空格）。

**问题**：两块改动塞进一个 PR，而 PR 描述完全没提第二个。评审者只读描述会漏看 i18n 改动，回滚时也无法单独回滚。建议在描述里补一节，或拆成两个 PR。

### 1.2 第一块（样式）的真实根因

`composer.tsx` L759 的外层容器是 `flex flex-wrap ... justify-between`，右侧控件组是 `ml-auto flex min-w-0`（无 `flex-1`）。`ml-auto` 只负责右推，**不给收缩能力**——当模型名过长时，右侧组的 hypothetical main size 超过剩余空间，`flex-wrap` 就把它整体换到第二行，导致工具栏高度跳动。

修复两手：
- L819：`ml-auto flex min-w-0` → **`flex min-w-0 flex-1 items-center justify-end gap-1`**
- L841：`ModelSelector` 的 className 追加 **`max-w-[280px]`**
- `model-selector.tsx` L472：给 `truncate` 的那层 span 加 **`title={selectedModel.name}`**

---

## 二、代码逻辑正确性（逐条验证）

### 2.1 `flex-1` 防换行的机制成立 ✅

`flex-1` = `flex: 1 1 0%`，flex-basis 为 0，因此该组的 hypothetical main size = 0，**永远不会被判定为溢出**，也就不会被 `flex-wrap` 推下去。改成 `justify-end` 后仍保持右对齐，视觉上等价于原来的 `ml-auto`。L819 的 `min-w-0` 保留了，内部可以正常收缩。**逻辑正确**。

### 2.2 `max-w-[280px]` 能真正生效 ✅

`modelSelectorTriggerVariants`（`model-selector.tsx` L363）根类含 **`w-fit`**（`width: fit-content`）。`max-width` 对 `fit-content` 计算值有硬上限约束，两者不冲突。内部 `ModelSelectorValue` 已有 `min-w-0`（L469），`truncate` span 才能收缩。整条链路成立。

### 2.3 `title` 属性可用 ✅

`title` 加在最内层的 `truncate` span 上，而非 `overflow-hidden` 的 trigger 上。`overflow-hidden` 只裁剪像素，不影响 `title` 的 hover 事件。项目内同款写法很多（`composer.tsx` L655/L683 的 skill/knowledge 芯片、`agent-groups.tsx` L95、`agent-landing.tsx` L339），**符合项目惯例**。

### 2.4 i18n 改动无 fallback 语义退化 ✅

`t(\`${translationKey}.title\`, title)` 的第二个参数是 default value。key 存在时用翻译，不存在时回落到硬编码中文——与改动前 `agent_create` 的行为一致，`skill_create` 从「永远硬编码」升级为「优先翻译」，**是纯增量改进**。

### 2.5 locale key 对齐 ✅

用脚本逐 key 比对 merge-base 与 head：
- en 新增 5、zh 新增 5，**key 集合完全相同**
- 无删除、无空值
- 新增：3 个 `skill.*.title` + `skillSectionLabel` + `agentSectionLabel`

---

## 三、实测验证

在独立 worktree（PR head）+ 链接主仓库 `node_modules` 上实跑：

```
npx vitest run --config vitest.workbench.config.ts \
  tests/workbench/Composer.test.tsx tests/workbench/CreationExamples.test.tsx
→ Test Files  2 passed (2)
  Tests      52 passed (52)
```

### 3.1 反向验证（确认断言不是摆设）

| 实验 | 改动 | 结果 |
| --- | --- | --- |
| 1 | 删掉 `max-w-[280px]` | ✅ 测试变红 |
| 2 | `flex-1 + justify-end` 回退成 `ml-auto` | ✅ 测试变红 |
| 3 | 同时加 `max-w-[280px]` 和 `max-w-[180px]` | ✅ 测试变红（Tailwind 后定义类覆盖前者，是真实风险） |
| 4 | 删掉 zh 的 `skill.invoiceExtraction.title` | ✅ 测试变红 |

**结论：4 个断言全部有真实防护力**，不是空断言。

### 3.2 全量回归

```
npx vitest run --config vitest.workbench.config.ts
→ Test Files  1 failed | 55 passed (56)
  Tests      7 failed | 371 passed (378)
```

7 个失败全部在 `tests/workbench/UserMessageEditComposer.test.tsx`，**本 PR 未改动该文件**。我在 merge-base `7ca15722c` 上跑同一文件，**同样 7 个失败**——确认是 develop 基线既有问题（`Unable to find an element with the text: Original question`），与本 PR 无关。

---

## 四、问题清单（按严重程度）

### 🟡 M1 — 修复不完整：下拉列表里同样截断，且无 `title`

**位置**：`model-selector.tsx` **L656**

```tsx
<span className="truncate font-medium">{model.name}</span>   // ← 没有 title
```

弹层宽度是 `w-72`（L503，= 288px），比触发器的 280px 更窄。带多段后缀的开源模型名在**下拉列表里同样会被截断**，而那里没有 `title`。

**为什么重要**：PR 的第二个诉求原文是「名称截断成省略号后，界面上没有任何途径看到完整模型名，无法确认所选的具体模型版本」。用户发现触发器上截断了，自然会打开下拉去确认——结果下拉里也截断且无提示，**原始诉求只解决了一半**。

**建议**（一行）：
```tsx
<span className="truncate font-medium" title={model.name}>{model.name}</span>
```
`ModelSelectorItem` 同样接受 `children` 覆盖，也可能被别处复用，所以这行改动影响面可控。

### 🟡 M2 — 触屏设备上长名仍无法查看

`title` 是原生 tooltip，**只在 hover 下触发**。移动端/触屏（WorkBuddy 有 Web 端）长按不会弹出。这是 `title` 方案的固有边界，不算引入 bug，但 PR 声称「截断不再丢信息」在触屏上不成立。

**建议**：若要彻底解决，改用项目已有的 `Tooltip`（`agent-selector-dropdown.tsx` L91 就是 `<Tooltip title={agentName}><span className="truncate">`），antd/Radix Tooltip 在触屏可配置长按触发。若维持 `title`，建议在描述里把结论收敛为「桌面端悬停可查」，避免过度承诺。

### 🟡 M3 — 新测试断言实现细节，且与既有测试风格不一致

**位置**：`Composer.test.tsx` L199-221

```tsx
expect(props.className).toContain("max-w-[280px]");
expect(group?.className).toContain("flex-1");
expect(group?.className).not.toContain("ml-auto");
```

我在全库 `frontend/tests/workbench/` 下搜索 `className).toContain`，**这个 PR 是唯一的出现者**——项目既有测试从不直接断言 Tailwind 类名，都是断言渲染结果/行为。

这类断言的代价：将来把 `flex-1` 换成 `grow`（语义完全等价），或把 `280px` 改成 `18rem`（视觉完全相同），测试都会假红。而它**保护不了真正的回归**——如果有人把 `max-w-[280px]` 写成 `max-w-[260px]`，测试照样绿，但视觉已经变了。

**建议**：断言可以保留（成本低、能挡明显回退），但建议补一条行为级断言，让测试真正验证「不换行」这个意图。例如：

```tsx
// mock ModelSelector 时透出 className 到真实 DOM，然后断言父容器是单行
const group = screen.getByRole("button", { name: "模型" }).closest("div");
expect(group?.className).toContain("flex-1");   // 保留
// 补：确认控件组与左侧组处于同一个 flex-wrap 容器内
expect(group?.parentElement?.className).toContain("flex-wrap");
```

更好的做法是用 `@testing-library` 的 `getComputedStyle` 断言 `flex: 1 1 0%`，但这需要 jsdom 支持 layout（实际不支持），所以退而求其次保持类名断言、并在注释里说明「这是唯一可行的近似」。

—— 实际上测试 L215-217 已经写了注释解释机制，这点做得不错。

### 🟡 M4 — 第二个 commit 未在 PR 描述中体现

见 1.1 节。`a7fa95afc` 是独立缺陷修复，与宽度问题无关，描述里完全没提。

**建议**：在描述里补 "Also fixes: Skill creation example cards showed hardcoded Chinese titles in English UI"。若维护者偏好原子提交，拆 PR 更干净。

### 💭 L1 — `aria-label` 硬编码中文 fallback 仍存在

**位置**：`CreationExamples.tsx` L63

```tsx
mode === "skill_create" ? "Skill 创建示例" : "Agent 创建示例"
```

这是 `t()` 的 default value，key 存在时不会用到。但由于 key 已补全，这个中文 fallback 实际已成为死字符串。**不算问题**——保留 fallback 是 i18n 的通行做法（防 key 缺失时显示裸 key）。仅记录。

### 💭 L2 — `max-w-[280px]` 魔数无说明

280px 是怎么定出来的（预留附件/语音/发送按钮宽度？）代码里没有注释。项目内 `max-w-[Npx]` 用法很普遍（`max-w-[120px]` 9 处、`max-w-[360px]` 3 处），所以**不违反规范**，但一个 magic number 配一行注释会更好维护。

### 💭 L3 — 左组右组空间分配可能挤压左侧按钮

改后右侧是 `flex-1`（可无限增长占满剩余），左侧是 `flex min-w-0 flex-wrap`（无 `flex-1`，宽度由内容决定）。在极窄视口下，左侧三个按钮（智能体/知识库/Skills）+ 右侧模型选择器可能都不够放，左侧会先 wrap。这与原行为一致（原来左侧也会 wrap），**不是回归**，但值得在窄屏上手工确认一次。

---

## 五、安全性 / 性能

无相关风险。纯 CSS 类名与 `title` 属性，无数据流、无网络、无用户输入。

- 无 XSS 面：`title={selectedModel.name}` 由 React 转义
- 无性能影响：无新增渲染、无新增查询，`flex-1` 与 `max-w` 均由浏览器合成层处理
- 无包体影响：无新依赖

---

## 六、合并预演

| 目标 | 结果 |
| --- | --- |
| vs 最新 develop（`d7f5955da`） | **0 冲突**（合并树 `9719699fd`） |
| vs PR #4155（同样改 2 个 locale 文件） | **0 冲突**（合并树 `f077dcb83`）—— 两者新增的 key 不重叠 |
| vs PR #4149 / #4154 | 0 文件重叠 |

PR 落后 develop 4 个提交，建议合入前 rebase 一次并重跑这两个测试文件。

---

## 七、结论

| 维度 | 评价 |
| --- | --- |
| 根因定位 | ✅ 准确。`ml-auto` 不给收缩能力是换行的真实原因，不是猜的 |
| 修复手法 | ✅ 正确。`flex-1` + `justify-end` + `max-w` 三件套是标准解法 |
| 代码风格 | ✅ 符合（`max-w-[Npx]`、`title` 都有既有先例） |
| i18n 对齐 | ✅ en/zh 完全一致，无孤儿 key |
| 测试有效性 | ✅ 4 个断言经反向验证均有真实防护力 |
| 回归风险 | ✅ 全量 371 passed，7 个失败为基线既有 |
| 完整度 | ⚠️ 下拉列表截断未处理，原始诉求只解决一半 |

### 合并建议：**通过（建议先修 M1）**

M1 是一行改动，且直接对应 PR 自己写的问题陈述，建议同批带上。M2/M3/M4 可作为 follow-up 或至少在第 2 个 commit 的描述里说明。

**具体动作清单（按优先级）**：

1. **必做（一行）**：`model-selector.tsx` L656 加 `title={model.name}`
2. **建议**：PR 描述补上 i18n 改动说明
3. **建议**：M3 测试注释已解释机制，可保留；如时间允许加一条 `parentElement` 含 `flex-wrap` 的断言强化意图
4. **可选**：280px 加一行注释说明取值依据
5. **合入前**：rebase 到最新 develop，重跑 `tests/workbench/Composer.test.tsx` + `CreationExamples.test.tsx`
