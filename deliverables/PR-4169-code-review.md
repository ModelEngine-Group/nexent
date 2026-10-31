# PR #4169 代码评审

> https://github.com/ModelEngine-Group/nexent/pull/4169
> 标题 `feat(frontend): refine agent configuration list`｜作者 hzwllm
> head `09808976b`｜merge-base `0436d6570`｜**drift 2**
> 分析：nexent-review skill（R1 证据阶梯 / R2 反向验证 / R3 merge-base 归因 / R4 场景卡片）
> 时间：2026-10-22

---

## 一、版本方向核查

| 项 | 值 |
| --- | --- |
| merge-base | `0436d6570` |
| PR head | `09808976b` |
| drift | **2**（develop 已前进到 `ed373b9f0`） |
| commit | 1 个 |
| 规模 | 13 文件 **+354 / −164** |
| 业务代码 | **5 文件 +80 / −63**（其余 8 个是测试/e2e/需求资产） |
| 后端改动 | **0**（纯前端 PR） |

### drift 的 2 个 commit 与本 PR 无交集

```
ed373b9f0 release(v2.8.0): consolidate migrations after v2.7.0 and bump version (#4168)
53957a8a9 fix(frontend): show shimmer skeletons during route navigation (#4167)
```

- `#4168`（v2.8.0 发版）：只动 `VERSION` + `deploy/sql/migrations/*`
- `#4167`（骨架屏）：动 `layout.client.tsx` / `loading.tsx` / `avatarDropdown.tsx` / `SideNavigation.tsx`

**文件重叠 0 个**，合并预演 0 冲突（见第八节）。这 2 个 commit 不需要 rebase 也能干净合入。

**标题与内容一致** ✅。commit message 精确。

---

## 二、风险等级（脚本判定）

按 `scoring.py` 的 `rate_change()`（rules v1.1）：

| 口径 | 评级 | 命中规则 |
| --- | --- | --- |
| 全部 13 文件（518 行） | 🔴 高 | R3 规模大（>400 行或 >10 文件） |
| **仅 5 个业务文件（143 行）** | 🟢 **低** | 无命中 |

R3 完全由 e2e/test 资产（+274 行、8 个文件）推起来的。**业务代码 +80/−63、5 文件，脚本判 🟢 低**——这是本次三个 PR 里业务风险最低的一个。

上下文补充（不覆盖脚本结论）：虽然量小，但每个改动都在**用户高频接触面**（智能体列表卡片、页面标题、引导分隔线），影响的是"所有打开智能体配置页的人"，所以不能因为 🟢 就轻看体验问题。

---

## 三、变更总览

| # | 文件 | 增/删 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | `agents/components/agent-config-actions.tsx` | +33/−3 | **混合** | 新增 `onConfigure` / `onPublish` props，菜单顶部插入「配置」「发布」+ divider |
| 2 | `agents/components/agent-list-card.tsx` | +7/−17 | **混合** | 移除 hover 浮现的按钮组；footer 改 `justify-between`；日期 `flex-1` |
| 3 | `agents/page.tsx` | +9/−30 | **混合** | 标题 key `agentDev`→`agentConfig`；删除「我创建的/导入的」标签页；divider 提升到所有情况 |
| 4 | `locales/zh/common.json` | +0/−3 | **变更** | 删 3 个 key |
| 5 | `locales/en/common.json` | +0/−3 | **变更** | 同上，en/zh 完全同步 |
| 6-13 | 测试 + e2e + 需求 | +274 | 新增 | 见第六节 |

---

## 四、代码链路追踪

### 4.1 卡片操作从「hover 按钮」迁移到「… 菜单」

| 步 | 代码位置 | 职责 | 数据变化 | 确信度 |
| --- | --- | --- | --- | --- |
| 1 | `agent-list-card.tsx` L140-148 | 把 `onConfigure` / `onPublish` 传给 `AgentConfigActions` | 新增 2 个 props 透传 | 已确认 |
| 2 | `agent-config-actions.tsx` L288-311 | 按 props 存在性**条件插入**菜单项 | `menuItems` 由数组字面量改为可变数组 push | 已确认 |
| 3 | 同上 L311 | 有 configure/publish 时插 divider 作分组 | 菜单视觉分组 | 已确认 |
| 4 | 同上 L406-415 | `variant="menu"` → `<Dropdown menu={{items: menuItems}}>` | 渲染入口 | 已确认 |
| 5 | `agent-list-card.tsx` L102-137 | footer 只剩日期 + 状态 | 移除隐藏按钮组 | 已确认 |

**菜单最终结构**（已核实无相邻 divider）：`配置 → 发布 → ─── → 复制 → 调用关系 → 版本管理 → 导出 → ─── → 删除`。两处 divider（L311 新增、L350 既有）中间隔着 4 个菜单项，不会连成一条。

### 4.2 关键前置假设验证（R1：找实证，不读注释）

| 假设 | 验证方式 | 结果 |
| --- | --- | --- |
| `sidebar.agentConfig` 是子项而非分组 | 读 `SideNavigation.tsx` L93-121 | ✅ `agentDev` 是 `isSection: true` 分组（path `/agent-dev`），`agentConfig` 是其子项（path `/agents`）。**页面标题用子项名是正确的** |
| 被删的 3 个 locale key 无残留引用 | grep 全库 3 个 key | ✅ 代码引用文件数均为 **0** |
| en/zh 删除集合一致 | 脚本比对 merge-base vs head | ✅ 完全一致，无新增 |
| `variant="table"` 的 filter 会不会误带 configure/publish | 读 `agent-list-table.tsx` L231-237 | ✅ 该调用点**不传** `onConfigure`/`onPublish`，filter 里永远不会有这两个 key，无害 |
| 键盘能否打开新菜单 | 读 L407-414，trigger 是 `<Button>` 带 `aria-label` | ✅ 可 Tab 聚焦 + Enter/Space 触发 click |
| `onPublish` 的 disabled 条件是否等价 | 读 L68 `isReadOnly = readOnly ?? storeIsReadOnly` | ✅ 卡片传 `permission === "READ_ONLY"`，等同于旧逻辑 |

---

## 五、场景验证与问题清单

### 🟡 M1 — 卡片操作从「一眼可见」变成「藏进菜单」，是可用性权衡需确认

**页面**：智能体配置 → 卡片视图

**操作**：鼠标移到某张智能体卡片上

**看到的（改前）**：卡片底部浮现「配置」「发布」两个蓝色按钮，直接点

**看到的（改后）**：卡片底部只有「创建于 xxx」和「已上线/未上线」，**没有任何操作按钮**；需要移到右上角点「…」，弹出菜单里才有「配置」「发布」

**期望的**：符合设计意图就是这样的（PR 描述明确说"moved card Configure and Publish actions into the … menu"）

**为什么值得提**：这是**有意的交互简化**（减少卡片视觉噪音），但代价是：

- 「配置」是卡片最高频操作（改一个智能体先要进配置），从 1 次点击变成 2 次
- 旧设计是 hover 才浮现，本身不算噪音源；新设计把唯一入口收进菜单

**这不是 bug**，是产品权衡。建议在 PR 描述里明确写"这是有意的交互收敛，代价是配置多一次点击"，让后续 review 的人知道不是随手删的。

### 🟡 M2 — 新增的菜单项与禁用门控**零测试覆盖**

**验证方式（R2 反向验证）**：

| 实验 | 操作 | 结果 |
| --- | --- | --- |
| 1 | 把 footer 布局还原成旧版（`gap-[clamp(...)]`） | ✅ 测试变红 |
| 2 | 移除 publish 的 `isReadOnly` 门控 | ⚠️ **8 个测试全绿** |
| 3 | 直接 `if (false && onPublish)` 让 publish 菜单项永不出现 | ⚠️ **8 个测试仍全绿** |

**根因**：`agentListCard.test.tsx` L35-72 **mock 掉了 `AgentConfigActions` 整个组件**，mock 内部自己写了一份 `disabled={readOnly}` 的假实现：

```tsx
vi.mock(".../agent-config-actions", () => ({
  default: function MockAgentConfigActions({ onConfigure, onPublish, ... }) {
    return (
      <>
        <button onClick={() => setOpen(true)}>更多</button>
        {open && (
          <>
            <button onClick={() => onConfigure(agentId)}>配置</button>
            <button disabled={readOnly} onClick={() => onPublish(agentId)}>发布</button>
```

所以测试验证的是「我 mock 的逻辑」，不是「真实组件的逻辑」。

**后果**：`agent-config-actions.tsx` 里新增的 33 行（菜单项构建 + 条件插入 + divider + disabled 计算）**完全没有被任何测试执行**。我 grep 了全库，`agentListTable.test.tsx` L47 也 mock 了它，没有专门的 `agentConfigActions.test.tsx`。

**修法**：补一个直接测真实组件的用例，例如：

```tsx
// tests/component/agentConfigActions.test.tsx
it("puts configure and publish at the top of the menu when handlers are given", async () => {
  render(<AgentConfigActions agentId={42} variant="menu"
    onConfigure={vi.fn()} onPublish={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "agentRepository.mine.menu.more" }));
  // 断言菜单项顺序：配置 → 发布 → divider → 复制 → ...
  expect((await screen.findAllByRole("menuitem")).map(e => e.textContent))
    .toEqual(["配置", "发布", "", "复制", /* ... */]);
});

it("disables publish for a read-only agent", async () => { /* readOnly + 断言 disabled */ });
```

### 🟡 M3 — 删除「我创建的 / 导入的」标签页后，`agentConfig.list.importedUnavailable` 的语义信息彻底丢失

**页面**：智能体配置列表（有数据时）

**操作**：无（改前会看到一个灰色不可点的「导入的智能体」页签）

**看到的（改前）**：两个页签「我创建的智能体」（激活）+「导入的智能体」（灰色禁用），后者 `title` 悬停提示「当前列表接口不支持按导入来源筛选」

**看到的（改后）**：页签整条消失

**为什么值得记一笔**：那个 disabled 页签其实在**传达一个能力边界**——"当前后端不支持按导入来源筛选"。删掉之后：

- 用户不再知道有"导入的智能体"这个分类概念
- 将来后端支持了筛选，也没有自然的入口位置了

**这不是 bug**（PR 描述明确说 removed the creator and import tabs），只是提醒：这条 disabled 标签页原本是一份"能力边界文档"，删了就没了。若后端后续要支持筛选，需要重新设计入口。

### 💭 L1 — `agent-list-card.tsx` 的 `onConfigure` / `onPublish` 现在是纯 prop 透传，可考虑合并

改动后卡片自己不再用这两个回调（只透传给菜单），而 `onOpen` 仍被卡片内部的 `<button>` 消费。这没问题，但 4 个回调（`onOpen`/`onConfigure`/`onPublish`/`onManageVersions`）让卡片 props 偏多。属未来可选的 props 收敛，不阻塞。

### 🟡 M4 — `agentListCard.test.tsx` 的 i18n 是「手抄副本」，改 locale 测试不会红

> 本节为 2026-10-22 14:38 追加（用户追问「这个测试是不是没做国际化」）

**结论先说**：**做了 i18n mock，但方式是「手抄一份翻译表」**，与真实 locale 完全脱钩。

**位置**：`agentListCard.test.tsx` L12-29

```tsx
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { date?: string }) => {
      const translations: Record<string, string> = {   // ← 手写的
        "agentConfig.list.configure": "配置",
        "agentConfig.list.publish": "发布",
        "agentConfig.list.online": "已上线",
        "agentConfig.list.offline": "未上线",
        ...
      };
      ...
      return translations[key] ?? key;
    },
  }),
}));
```

### 当前值与真实 locale 一致（这点没问题）

我逐条比对了 mock 的 7 个 key 与 `zh/common.json`：**7/7 完全一致**，包括 `createdAt` = `创建于{{date}}`（mock 用模板字符串复现）。所以**现在**测试是对的。

### 但有两条实质风险，实测确认

在临时 worktree 上做了两个实验：

| 实验 | 操作 | 结果 |
| --- | --- | --- |
| 1 | 把 `zh/common.json` 里 `agentConfig.list.configure` 从「配置」改成「设置」 | ⚠️ **8 个测试仍全绿** |
| 2 | **直接删除** `agentConfig.list.configure` 这个 key | ⚠️ **8 个测试仍全绿** |

**实验 2 更严重**：连 key 被删掉都发现不了。生产环境里 `t()` 会 fallback 到显示原始 key 名（`agentConfig.list.configure`），用户会看到一串英文 key，而 CI 完全绿。

### 有没有别的测试兜底？——**没有**

我查了全库，唯一做 locale 完整性校验的是 `tests/agentUsageGuideLocales.test.ts`，但它的守护范围是：

```ts
const prefix = /^agentUsageGuide\./;   // ← 只管这个前缀
```

`agentConfig.list.*` **完全裸奔**。

### 为什么这是 M2 的更深一层

M2 说的是「测试 mock 掉 `AgentConfigActions`，真实组件零覆盖」。M4 是同一根源的另一个面向：

- `AgentConfigActions` 被 mock 后，测试里那三个按钮「配置」「发布」「版本管理」是 **mock 自己硬编码的中文**
- 断言 `screen.getByRole("button", { name: "配置" })` 匹配的是 mock 的字面量，不是 `t()` 的输出
- 所以**这段断言既没验证真实组件的 i18n，也没验证 locale 文件**

### 项目惯例对比

我统计了 `frontend/tests/` 下两种 mock 风格：

| 风格 | 文件数 | 说明 |
| --- | --- | --- |
| A：`t: (key) => key` | **20 个** | 返回 key 本身，断言直接用 key 名，**不依赖 locale 内容** |
| B：自建翻译表 | **4 个** | 本文件 + `agentListTable` / `createAgentModal` / `myAgentMainBadge` |

**风格 A 是主流（20 vs 4）**，且它天然不会和 locale 脱钩——因为没有"副本"可脱钩。

### 修法（两个选项）

**选项 1（推荐，改动小）**：改成风格 A，断言用 key

```tsx
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: any) =>
      opts?.date ? `${key}:${opts.date}` : key,   // 不维护副本
  }),
}));

// 断言随之改为
fireEvent.click(screen.getByRole("button", { name: "agentConfig.list.configure" }));
expect(screen.getByText("agentConfig.list.createdAt:2026-01-23")).toBeInTheDocument();
```

好处：永不失同步；坏处：断言可读性下降（看到的是 key 不是中文）。

**选项 2（可读性优先）**：mock 直接从真实 locale 读

```tsx
import zh from "../../public/locales/zh/common.json";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: any) => {
      const raw = (zh as Record<string, string>)[key] ?? key;
      return opts?.date ? raw.replace("{{date}}", opts.date) : raw;
    },
  }),
}));
```

好处：断言仍写中文、可读性好，且**locale 改了测试会跟着变**（这才是"测真实行为"）；坏处：需要处理 `{{}}` 插值。

**选项 2 更适合这个文件**，因为它现在的断言（`创建于2026-01-23`）可读性很好，不必为了同步性牺牲掉。

### 顺带：如果要真正守护 locale 完整性

建议把 `agentUsageGuideLocales.test.ts` 的前缀白名单从 `^agentUsageGuide\.` 扩展成按模块分组（`agentConfig\.` / `agentRepository\.` 等），或在 CI 加一条 en/zh key 集合相等的全量校验。当前只有 `agentUsageGuide.` 一个前缀被守护。

### 💭 L2 — divider 从 `inset-x-6` 改成 `inset-x-0` 后，与左侧内容缩进的关系

`agents/page.tsx` L248：`inset-x-0` 让分隔线跨满容器宽度。父容器有 `p-6`，所以线会顶到 padding 内边界的左右两侧。PR 描述说"full-width across the list content area"，符合意图。但**空列表时**（改前 divider 只在空列表分支）与**有数据时**现在是同一条线，位置从原来的 `inset-x-6`（两侧内缩）变为贴边——视觉上会与上方引导区的缩进不一致。建议人工看一眼截图确认这是想要的。

---

## 六、测试验证

### 6.1 实跑结果

独立 worktree + junction 链接依赖：

```
npx vitest run tests/component/agentListCard.test.tsx
→ Test Files  1 passed (1)
  Tests      8 passed (8)          ← 与 PR 描述"component test (8/8)"一致
```

### 6.2 反向验证（R2）

| 实验 | 操作 | 结果 | 判定 |
| --- | --- | --- | --- |
| 1 | footer 布局还原成旧版 | 测试变红 | ✅ 反向验证有效 |
| 2 | 移除 publish 的 `isReadOnly` 门控 | 8 个全绿 | ⚠️ **无覆盖** |
| 3 | `if (false && onPublish)` 让 publish 永不出现 | 8 个全绿 | ⚠️ **无覆盖** |

实验 2、3 共同证明：`agent-config-actions.tsx` 的新增逻辑完全没有测试执行路径（见 M2）。

### 6.3 测试改动质量

`agentListCard.test.tsx` 有两处做得不错：

- mock 从"永远渲染一个按钮"改成"模拟菜单展开"（`useState` + 条件渲染），能验证「先点更多、再点配置」的两步流程
- 新增 `keeps publishing disabled for a read-only Agent in the more menu` 用例，检查了 `READ_ONLY` 权限下发布按钮 disabled 且点击不触发回调

**但**这份测试测的是 mock 的行为，不是真实组件——这是 M2 的根源。

---

## 七、专项校验

| 检测项 | 结果 | 说明 |
| --- | --- | --- |
| 1. 数据格式/契约 | ✅ 无 | `git diff -- backend/` 为空 |
| 2. 版本回退 | ✅ 无 | 1 commit，无 Revert |
| 3. 敏感信息 | ✅ 无 | 零命中 |
| 4. locale 对齐 | ✅ **完美** | en/zh 删除集合完全一致（3 个 key），无新增、无孤儿残留（代码引用数均为 0） |
| 5. 循环依赖 | ✅ 无 | 卡片 → Actions → Dropdown，单向 |

locale 这一项做得比多数 PR 干净：删 key 时 en/zh 同步删，且确认了代码里没有残留引用。

---

## 八、合并预演

| 目标 | 结果 |
| --- | --- |
| vs develop `ed373b9f0` | **0 冲突**（合并树 `e8c2f6d2e`） |
| 文件重叠 | **0 个**（develop 的 2 个 commit 改的 34 个文件与本 PR 的 13 个零交集） |

drift 2 但不影响合并，无需强制 rebase。

---

## 九、结论

### 总评

**业务风险最低的一个 PR**（脚本判 🟢 低）。改动很克制：删掉半成品的「导入的」页签、把卡片操作收进菜单、修页面标题用错层级、分隔线跨满。locale 清理干净（en/zh 同步删 + 确认无残留引用），这是很多 PR 会漏的。

**标题与内容一致**，commit message 精确，无多余改动。

### 问题汇总

| # | 严重度 | 问题 | 场景 |
| --- | --- | --- | --- |
| M1 | 🟡 | 卡片操作从 hover 按钮收进「…」菜单，配置从 1 次变 2 次点击 | 有意简化，但建议描述里写明代价 |
| M2 | 🟡 | 新增的菜单项与 disabled 门控**零测试覆盖**（测试 mock 掉了真实组件） | 反向验证：删掉 publish 菜单项，8 个测试仍全绿 |
| M3 | 🟡 | 「导入的智能体」disabled 页签删除，附带的能力边界说明一并消失 | 用户不再知道后端不支持按来源筛选 |
| **M4** | 🟡 | **i18n mock 是手抄副本，与真实 locale 脱钩** | 改 locale 文案或**删掉 key**，8 个测试仍全绿；全库只有 `agentUsageGuide.*` 被守护 |
| L1 | 💭 | 卡片 4 个回调 props 偏多 | 可选收敛 |
| L2 | 💭 | divider `inset-x-6`→`inset-x-0`，与上方引导缩进可能不一致 | 建议看截图确认 |

### 合并建议：**通过（建议补 M2 的测试 + 修 M4 的 mock 方式）**

**无阻塞项。** 功能实现正确，locale 清理干净，无契约/安全问题。

M2 是最值得补的：`agent-config-actions.tsx` 新增了 33 行菜单构建逻辑（含一个 `disabled || isReadOnly` 的权限门控），但测试 mock 掉了整个组件，**删掉或改坏这段代码 CI 不会红**。补一个直接测真实组件的用例即可。

M4 和 M2 是同一根源的两个面向：mock 掉的组件自带硬编码中文，断言匹配的是 mock 字面量。建议把 i18n mock 改成「从真实 locale 读」（选项 2），既保留断言可读性，又让 locale 变更能被测试感知。

M1/M3 是产品决策，建议在描述里补一句说明，避免后续维护者把它们当 bug "修回去"。

---

## 十、附：本次评审的关键取证

| 判断 | 证据 | 结果 |
| --- | --- | --- |
| 页面标题改用 `agentConfig` 是否正确 | 读 `SideNavigation.tsx` L93-121 菜单结构 | ✅ `agentDev` 是分组、`agentConfig` 是子项，改对了 |
| 删的 3 个 key 有残留引用吗 | grep 全库 | ✅ 均为 0 |
| `variant="table"` 的 filter 会不会误带新项 | 读 `agent-list-table.tsx` L231-237 | ✅ 该调用点不传新 props，无影响 |
| 新菜单键盘可达吗 | 读 trigger 是 `<Button>` + `aria-label` | ✅ Tab + Enter 可开 |
| 测试真的锁住了新逻辑吗 | 3 组反向验证 | ❌ 2 组失败 → 发现 M2 |
| drift 2 会冲突吗 | 文件交集 + merge-tree | ✅ 0 重叠 0 冲突 |
