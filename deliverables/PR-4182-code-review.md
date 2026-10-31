# PR #4182 代码评审

> https://github.com/ModelEngine-Group/nexent/pull/4182
> 标题 `fix(frontend): 补齐模型参数覆盖弹窗的温度与 Top P 提示`｜作者 bernard1234
> head `5597a4a53`｜merge-base `0436d6570`｜**drift 12**
> 分析：nexent-review skill（R1 证据阶梯 / R2 反向验证 / R3 merge-base 归因 / R4 场景卡片）
> 时间：2026-10-22

---

## 一、版本方向核查

| 项 | 值 |
| --- | --- |
| merge-base | `0436d6570` |
| PR head | `5597a4a53` |
| drift | **12**（develop 已前进到 `8c424a023`） |
| commit | 1 个 |
| 规模 | 5 文件 **+117 / −3** |
| 业务代码 | **3 文件 +22 / −2**（1 个组件 + 2 个 locale） |
| 后端改动 | **0**（纯前端） |

**标题与内容一致** ✅。中英文标题都精确描述了改动。

### drift 12 但不冲突

develop 的 12 个提交里包括 `#4167`（骨架屏）、`#4169`（智能体列表）、`#4163`（prompt limit）、`#4175`（模型控件）等，但：

- **合并预演 0 冲突**（合并树 `e1ffe7ac3`）
- `ModelParamsModal.tsx` 与 `resonPickerLocalization.test.tsx` 均未被这 12 个提交触碰

无需 rebase。

---

## 二、风险等级（脚本判定）

按 `scoring.py` 的 `rate_change()`（rules v1.1）：

| 口径 | 评级 | 命中规则 |
| --- | --- | --- |
| 全部 5 文件（120 行） | 🟢 **低** | 无命中 |
| 仅 3 业务文件（24 行） | 🟢 **低** | 无命中 |

**两个口径都是 🟢 低**——这是近期评审中风险最低的一个。改动本质是给两个已有图标包一层 Tooltip + 补 4 条文案，不涉及逻辑分支、数据流、契约。

---

## 三、变更总览

| # | 文件 | 增/删 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | `resource-picker/ModelParamsModal.tsx` | +18/−2 | **变更** | 温度 / Top P 的 `QuestionCircleOutlined` 外包 `<Tooltip>`，加 `tabIndex={0}` |
| 2 | `locales/zh/common.json` | +2/−0 | **新增** | `modelParams.temperatureInfo`、`modelParams.topPInfo` |
| 3 | `locales/en/common.json` | +2/−0 | **新增** | 同上，en/zh 完全对齐 |
| 4 | `tests/component/resourcePickerLocalization.test.tsx` | +58/−1 | **新增** | 4 组参数化用例（zh/en × hover/focus × 可编辑/只读） |
| 5 | `test-e2e/changes/bugs/MODEL-PARAMS-TOOLTIPS-20261022.yaml` | +37 | 新增 | 缺陷变更记录 |

---

## 四、代码链路追踪

### 4.1 Tooltip 的渲染链路

| 步 | 代码位置 | 职责 | 确信度 |
| --- | --- | --- | --- |
| 1 | `ModelParamsModal.tsx` L397-407 | `<Tooltip title={t("modelParams.temperatureInfo")} trigger={["hover","focus"]}>` 包住图标 | 已确认 |
| 2 | `ParamDialog.tsx` L280-312 `ParamField` | 接收 `icon` prop，渲染在 `<span data-config-label>` 内 | 已确认 |
| 3 | `ParamDialog.tsx` L306-311 | `infoNode && (showInfo && infoText ? <Tooltip title={infoText}>{infoNode}</Tooltip> : infoNode)` | 已确认 |
| 4 | antd `AntdIcon.js` L39-53 | 把 `tabIndex` 透传到 `<span role="img" aria-label="question-circle">` | 已确认 |

**关键机制确认**：`ParamField` 只有在 `info && infoText && !icon` 时才自己包 Tooltip（L306-311）。本 PR 传了 `icon`，所以 `showInfo = info && !icon` 为 falsy，组件**不会**重复包一层 Tooltip——PR 自己包的那层是唯一生效的。不存在嵌套 Tooltip 冲突。

### 4.2 关键前置假设验证（R1：找实证，不读注释）

| 假设 | 验证方式 | 结果 |
| --- | --- | --- |
| `Tooltip` 已 import | 读 `ModelParamsModal.tsx` L7 | ✅ `import { Select, Tooltip } from "antd"` |
| 文件里是否还有别的问号图标被漏改 | grep `QuestionCircleOutlined` | ✅ 共 3 处：L366 的 token 字段**本来就有 Tooltip**（是本次的参照范式），L402/L432 是本 PR 新加的。**无遗漏** |
| `data-config-label` 是否存在（测试依赖） | grep 全库 | ✅ `ParamDialog.tsx` L294，`ParamField` 的 `<span>` 上 |
| 测试的 `getByRole("img")` 是否命中图标 | 读 `AntdIcon.js` L48-49 | ✅ 渲染为 `<span role="img" aria-label={icon.name}>`，`name` = `question-circle` |
| 文案「0–2 / 0–1」与组件实际范围是否一致 | 读 L416-418 / L442-444 | ✅ temperature `min=0 max=2`，topP `min=0 max=1`，**完全一致** |
| en/zh 新增 key 是否对齐 | 脚本比对 merge-base | ✅ 两边都是 `temperatureInfo` + `topPInfo`，集合相等 |

---

## 五、场景验证与问题清单

### 🟡 M1 — `tabIndex={0}` 是真实键盘可达的必需品，但测试对它零守护

**页面**：Agent 配置 → 模型参数覆盖弹窗

**操作（真实浏览器）**：只用键盘，Tab 键焦点移到「输出内容温度」旁的问号

**看到的（有 `tabIndex={0}`）**：焦点落在问号上，`focus` 事件触发，Tooltip 弹出，读屏播报说明 ✅

**看到的（若无 `tabIndex`）**：问号是 `<span role="img">`，**默认不可聚焦**，Tab 永远跳不到它，键盘用户看不到说明

**为什么**：我读 `node_modules/@ant-design/icons/es/components/AntdIcon.js` L39-40：

```js
let iconTabIndex = tabIndex;
if (iconTabIndex === undefined && onClick) {
  iconTabIndex = -1;
}
```

不传 `tabIndex` 且无 `onClick` 时，`iconTabIndex` 保持 `undefined`，渲染出的 `<span role="img">` **不在 tab 序列里**。

**问题在测试**：我做反向验证时把两处 `tabIndex={0}` 全删掉，**11 个测试仍然全绿**。

```
实验：移除 2 处 tabIndex={0}  →  Test Files 1 passed, Tests 11 passed
```

**根因**：测试用的是 `fireEvent.focus(icon)`，它**直接派发 focus 事件，不检查元素是否可聚焦**。jsdom 没有真实的 tab 序列概念。所以这条最重要的无障碍保证，测试完全没守住。

**建议**：补一条断言（一行）：

```tsx
const icon = within(label.closest("[data-config-label]")!)
  .getByRole("img", { name: "question-circle" });
expect(icon).toHaveAttribute("tabindex", "0");   // ← 锁住键盘可达性
```

或者在测试里用 `userEvent.tab()` 走真实 tab 序列（更接近浏览器行为，但需要构造完整的 focus 链）。

### 💭 L1 — 既有 token 字段的 Tooltip 没有 `tabIndex`，与本 PR 新增的两处不一致

**位置**：`ModelParamsModal.tsx` L365-369（token 容量字段）

```tsx
<Tooltip title={field.info}>
  <QuestionCircleOutlined
    style={{ color: "#8C8C8C", fontSize: 12 }}
  />                                  {/* ← 没有 tabIndex */}
</Tooltip>
```

本 PR 新增的两处都有 `tabIndex={0}`。

**业务后果**：同一个弹窗里，温度/Top P 的问号**键盘能 Tab 到**，而 token 容量字段的问号**Tab 不到**——对只用键盘的用户是体验不一致。

**这不是本 PR 引入的**（L366 是既有代码），但既然本 PR 已经确立了"图标加Tooltip就该配 tabIndex"的模式，建议顺手把 L366 也补齐，保持同一弹窗内的无障碍行为一致。

### 💭 L2 — Tooltip 文案比同类文案长得多，需确认不会被裁切

新增的 `topPInfo` 中文文案：

> 核采样概率阈值，取值范围为 0–1。模型从累积概率达到该阈值的候选词中采样；值越低，候选范围越小。通常建议只调整温度或 Top P 中的一个参数。

约 **65 个中文字符**。antd Tooltip 默认 `max-width` 是 250px（`overlayInnerStyle` 未覆盖时），这段文案在 250px 宽度下会折成 4-5 行。功能上没问题，但视觉效果需确认——PR 有截图，说明作者看过。

对比该文件里既有的 `field.info`（token 字段说明）通常是一句话。建议人工确认 Tooltip 弹层不会超出视口边缘（尤其在小屏或弹窗靠右时）。

### 💭 L3 — `defaultValue` 兜底只在温度上有，`topPInfo` / `temperatureInfo` 没有

```tsx
title={t("modelParams.temperatureInfo")}     // ← 无 defaultValue
title={t("modelParams.topPInfo")}            // ← 无 defaultValue
```

而同文件的 label 都带了兜底：

```tsx
label={t("modelParams.temperature", { defaultValue: "输出内容温度" })}
```

**这是个真实的不一致**：如果 locale key 缺失，label 会显示中文兜底，Tooltip 却会显示原始 key 名（`modelParams.temperatureInfo`）。

不过本 PR **同时补了 en/zh 两个 key**，所以当前不会触发。属防御性编程的取舍——加了兜底要维护两处中文。**不算问题**，仅记录这个风格不一致。

---

## 六、测试验证

### 6.1 实跑结果

独立 worktree + junction 链接依赖：

```
npx vitest run tests/component/resourcePickerLocalization.test.tsx
→ Test Files  1 passed (1)
  Tests      11 passed (11)
    ✓ shows sampling help in zh on hover (readonly=false) without changing the draft
    ✓ shows sampling help in en on hover (readonly=true) without changing the draft
    ✓ shows sampling help in zh on focus (readonly=true) without changing the draft
    ✓ shows sampling help in en on focus (readonly=false) without changing the draft
```

与 PR 描述「修复前 4 组失败、修复后 11 条通过」完全一致。

### 6.2 反向验证（R2）

| 实验 | 操作 | 结果 | 判定 |
| --- | --- | --- | --- |
| 1 | 移除 temperature 的 `<Tooltip>` 包裹（还原成裸图标） | **4 个用例全部失败** | ✅ 反向验证有效 |
| 2 | 移除两处 `tabIndex={0}` | ⚠️ **11 个全绿** | ⚠️ **无覆盖**（即 M1） |

实验 1 证明这套测试确实锁住了 Tooltip 的存在性；实验 2 暴露了键盘可达性没被守住。

### 6.3 测试质量亮点

这组测试写得比多数 PR 扎实，三点值得肯定：

1. **参数化覆盖矩阵完整**：`[zh, en] × [hover, focus] × [可编辑, 只读]`，4 组正好覆盖 PR 描述声称的所有场景
2. **断言了「看帮助不能改数据」**：`expect(onChange).not.toHaveBeenCalled()` / `onClose` / `onConfirm` 全部连续断言，防止 Tooltip 的事件冒泡误触保存或关闭——这是容易踩的坑
3. **Tooltip 消失也断言了**：`await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull())`，验证 unhover/blur 后弹层正确关闭

---

## 七、专项校验

| 检测项 | 结果 | 说明 |
| --- | --- | --- |
| 1. 数据格式/契约 | ✅ 无 | `git diff -- backend/` 为空 |
| 2. 版本回退 | ✅ 无 | 1 commit，无 Revert |
| 3. 敏感信息 | ✅ 无 | 零命中 |
| 4. locale 对齐 | ✅ **完美** | en/zh 新增集合完全相等：`temperatureInfo` + `topPInfo` |
| 5. 循环依赖 | ✅ 无 | 仅新增 antd `Tooltip` 引用，无跨模块新依赖 |

**文案准确性额外核对**：说「温度 0–2」「Top P 0–1」与代码里 `SliderStepper` 的 `min/max`（L416-418 / L442-444）**完全一致**，没有写错范围。

---

## 八、合并预演

| 目标 | 结果 |
| --- | --- |
| vs develop `8c424a023` | **0 冲突**（合并树 `e1ffe7ac3`） |

drift 12 但不冲突，`ModelParamsModal.tsx` 与测试文件均未被这 12 个提交触碰。

---

## 九、结论

### 总评

**一个干净的小修复**。两个 🟢 低风险口径，改动克制（业务代码 +22/−2），文案准确（范围与代码一致），en/zh 对齐完美，测试矩阵覆盖完整且断言了"看帮助不改数据"这个易错点。

尤其值得肯定的是**它沿着既有范式做**：文件里 L365-369 的 token 字段本来就有 `<Tooltip title={field.info}>` 的写法，本 PR 只是把温度/Top P 对齐到同一模式，没有另起一套。

### 问题汇总

| # | 严重度 | 问题 | 场景 |
| --- | --- | --- | --- |
| M1 | 🟡 | `tabIndex={0}` 是真实键盘可达的必需品，但删掉它 11 个测试仍全绿 | 键盘用户 Tab 不到问号就看不了说明，而 CI 不会红 |
| L1 | 💭 | 既有 token 字段的 Tooltip 无 `tabIndex`，同一弹窗内键盘行为不一致 | 温度/Top P 可 Tab 到，token 字段 Tab 不到 |
| L2 | 💭 | `topPInfo` 约 65 汉字，antd Tooltip 默认 250px 会折 4-5 行 | 建议确认不小屏溢出 |
| L3 | 💭 | Tooltip 的 `t()` 无 `defaultValue` 兜底，而 label 有 | key 缺失时 Tooltip 显示原始 key 名（当前 key 已补，不触发） |

### 合并建议：**通过（建议补 M1 的一行断言）**

**无阻塞项。** 修复本身正确，文案准确，测试覆盖了主要场景。

M1 是唯一值得动手的：`tabIndex={0}` 是"支持键盘聚焦查看"这个 PR 卖点的**唯一实现手段**，但测试用 `fireEvent.focus()` 绕过了可聚焦性检查，删掉它 CI 依然全绿。补一行 `toHaveAttribute("tabindex", "0")` 就能锁住。

L1-L3 都是可选优化。

---

## 十、附：本次评审的关键取证

| 判断 | 证据 | 结果 |
| --- | --- | --- |
| 是否漏改别的问号图标 | grep 出 3 处 `QuestionCircleOutlined` | ✅ L366 本来就有 Tooltip，无遗漏 |
| 会不会嵌套两层 Tooltip | 读 `ParamField` L290/L306-311 的 `showInfo = info && !icon` | ✅ 传了 icon 就不会重复包 |
| `tabIndex` 是否真影响键盘可达 | 读 `AntdIcon.js` L39-53 | ✅ 不传则 `undefined`，`<span role="img">` 不可聚焦 |
| 测试的 `data-config-label` 契约是否存在 | grep 全库 | ✅ `ParamDialog.tsx` L294 |
| 文案的 0–2 / 0–1 是否写对 | 对比 `SliderStepper` 的 min/max | ✅ 完全一致 |
| 测试真锁住 Tooltip 了吗 | 反向验证：删 Tooltip 包裹 | ✅ 4 个用例变红 |
| 测试锁住 tabIndex 了吗 | 反向验证：删 tabIndex | ❌ 11 个全绿 → M1 |
