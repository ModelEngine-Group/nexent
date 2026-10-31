# PR #4243 代码评审

> https://github.com/ModelEngine-Group/nexent/pull/4243
> 标题 `fix(frontend): repair agent debug controls and mode switching`｜作者 bernard1234
> head `7af62ae50`｜merge-base `bafb7607b`｜**drift 3**
> 分析：nexent-review skill（R1 证据阶梯 / R2 反向验证 / R3 merge-base 归因 / R4 场景卡片）
> 时间：2026-10-29

---

## 一、版本方向核查

| 项 | 值 |
| --- | --- |
| merge-base | `bafb7607b` |
| PR head | `7af62ae50` |
| drift | **3** |
| commit | 5 个（2 个 fix + 3 个 docs） |
| 规模 | 10 文件 **+467 / −47** |
| **业务代码** | **4 文件 +34 / −38**（1 tsx + 1 css + 2 locale） |
| 后端改动 | **0**（纯前端） |

**标题与内容一致** ✅。

### 5 个 commit 的实际内容

| commit | 实际改动 |
| --- | --- |
| `56ac78338` fix(frontend): streamline agent debug header actions | 业务代码主体（标题栏重构） |
| `c428c5dfc` docs: add agent debug header preview screenshots | 添加截图 |
| `751d38e97` docs: replace previews with real agent debug screenshots | 替换截图 |
| `122048900` docs: remove screenshot assets from source tree | **移除截图** |
| `7af62ae50` fix(frontend): restore ordinary debug mode switching | 模式切换修复 |

**3 个 docs commit 的净效果是零**——加了截图又删了。我核实了最终 diff **无任何图片文件**（`git diff --name-only | grep -E "\.(png|jpg|gif|webp)$"` 为空），说明作者最终选择"截图只放 PR 描述、不进仓库"，这是对的。但**中间那两个 commit 留在历史里**，`git log` 会看到加了又删的噪音。

> 💭 若用 squash merge，这段噪音会自动消失；若用 merge commit，历史里会保留"加截图→换截图→删截图"三条无意义记录。

---

## 二、风险等级（脚本判定）

按 `scoring.py` 的 `rate_change()`（rules v1.1）：

| 口径 | 评级 | 命中规则 |
| --- | --- | --- |
| 全部 10 文件（514 行） | 🟡 **中** | R5 规模中等（>150 行或 >5 文件） |
| **仅 4 业务文件（72 行）** | 🟢 **低** | 无命中 |

R5 由 `AgentDebugHeader.test.tsx`（+276 行）推起来的。**业务代码只有 72 行、纯前端 UI，无契约变动**，实际风险低。

---

## 三、变更总览

| # | 文件 | 增/删 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | `debug/agent-debug.tsx` | +33/−30 | **变更** | 标题栏重构 + 透传 `onChatModeChange` |
| 2 | `debug/agent-debug.css` | +3/−1 | **变更** | 加 `gap`/`align-items`/`flex-shrink`，移除 `cursor:pointer` |
| 3 | `locales/zh/common.json` | +1/−0 | **新增** | `agent.debug.toggleCompareMode` |
| 4 | `locales/en/common.json` | +1/−0 | **新增** | 同上，完全对齐 |
| 5 | `tests/workbench/AgentDebugHeader.test.tsx` | +276 | **新增** | 8 个标题栏/模式用例 |
| 6 | `tests/workbench/AgentDebugModelControls.test.ts` | +17 | 新增 | 11 个用例（PR 描述提及） |
| 7-10 | 2 个 e2e 变更记录 + 2 个 e2e 工具文件 | +77 | 新增/修改 | 见第六节 |

---

## 四、代码链路追踪

### 4.1 核心 bug 修复：`onChatModeChange` 从空函数到真实回调

**改动前的代码（bug 根因）**：

```tsx
// agent-debug.tsx — DebugConversation
<Thread
  chatMode={chatMode}
  onChatModeChange={() => undefined}   // ← 用户点了没反应
  ...
/>
```

**改动后的链路（5 跳，全部已核实）**：

| 步 | 代码位置 | 职责 | 确信度 |
| --- | --- | --- | --- |
| 1 | `agent-debug.tsx` L193 | `useState<ChatMode>("execution")` 持有模式状态 | 已确认 |
| 2 | 同上 L287/L298 `onChatModeChange={setChatMode}` | 传给 `AgentDebugChat`（普通/对比两个入口） | 已确认 |
| 3 | 同上 L172 `onChatModeChange={onChatModeChange}` | 继续传给 `DebugConversation` | 已确认 |
| 4 | `Thread` → `chat.tsx` L174/L209 → `composer.tsx` L764 | 一路透传到 `WorkbenchPlanningMenu` | 已确认 |
| 5 | `agent-debug.tsx` L155-163 | `chatMode` 变化 → effect 更新 `runConfig.custom.enablePlan` | 已确认 |

第 5 步是关键——**UI 选择必须真正影响运行参数**：

```tsx
useEffect(() => {
  runtime.thread.composer.setRunConfig({
    custom: {
      agentId,
      enablePlan: chatMode === "planning",   // ← L159
      modelId: effectiveModelId,
    },
  });
}, [agentId, runtime, chatMode, effectiveModelId]);
```

最终在 `remote-chat-model-adapter.ts` L1563 / L1764 变成请求体的 `enable_plan`：

```ts
requestBody.enable_plan = custom?.enablePlan === true;
```

**这条链路完整贯通**，不是"UI 变了但请求没变"的假修复。

**顺带一个设计亮点**：`setChatMode` 同时传给了普通调试（L287）和对比面板（L298），**两者共享同一份 `chatMode` state**。这是 PR 描述"统一普通和对比调试的模式状态"的实现方式——切换对比模式时不会出现"单栏是规划、双栏是执行"的状态分裂。测试用例 `shares the mode across ordinary and compare views without clearing unsent text` 正是验这一点。

### 4.1b 现象与根因的最简说明（实测确认）

**现象（用户视角）**

调试面板底部的模式按钮（写着「执行」+ ▶ 图标）：

1. 点开 → 弹出「规划 / 执行」两个选项
2. 点「规划」→ 弹层关闭
3. **按钮还是显示「执行」**，没有任何变化
4. 发消息 → Agent 走的是**执行模式**（不是规划模式）

用户的感受是：「我明明选了规划，它自己跳回去了」。反复点几次都一样。

**根因（代码视角）**

```tsx
// agent-debug.tsx 改前 L97
<Thread
  chatMode={chatMode}
  onChatModeChange={() => undefined}   // ← 空回调，丢掉了 setChatMode
/>
```

`WorkbenchPlanningMenu`（`composer.tsx` L904-955）是个**纯受控组件**：

```tsx
const [open, setOpen] = useState(false);   // ← 只有"弹层开合"是自己的状态
// 图标和文字完全由 props 决定：
{chatMode === "planning" ? <MessageCircleMore /> : <Play />}
{chatMode === "planning" ? t("planningMode") : t("executionMode")}
```

用户点击时执行 `onChatModeChange("planning")` + `setOpen(false)`：

- `setOpen(false)` 生效 → 弹层关闭（**这是用户唯一能看到的反馈**）
- `onChatModeChange("planning")` 是空函数 → **什么都不发生**
- 父组件 `chatMode` 仍是 `"execution"` → 重新渲染时按钮还是「执行」

于是形成一次"**假成功**"：界面动了（弹层收起），但状态没变。

**实测证据**（最小复现探针）：

| 场景 | 点「规划」后按钮显示 | 父 chatMode | enablePlan |
| --- | --- | --- | --- |
| 空回调（bug） | **执行**（没变） | `execution` | **false** |
| 真实 setState（修复后） | 规划 ✅ | `planning` | **true** ✅ |

**为什么之前不容易发现**

改前标题栏那个 Dropdown **也能切模式**（`agent-debug.tsx` 改前 L228 `setChatMode(key)`）。所以：

- 从标题栏菜单切 → **能生效**
- 从底部 composer 菜单切 → **不生效**

同一个页面两个入口，一个正常一个失效。如果测试或走查只用了标题栏入口，就发现不了。这也是本 PR 顺带把模式切换从标题栏 Dropdown 移走、只保留底部 composer 入口的原因之一（避免双入口不一致）。

### 4.2 R1 验证：UI 控件真实存在吗？

`composer.tsx` 有两处渲染点，都核实过：

| 位置 | 控件 | 渲染条件 |
| --- | --- | --- |
| L598-601 | `<PlanView>` | `onChatModeChange && !creationMode && !configurationLayout && !hidePlan` |
| L761-767 | `<WorkbenchPlanningMenu>` | `!creationMode && onChatModeChange` |

改动前 `onChatModeChange={() => undefined}` 是个**真函数**（truthy），所以 `WorkbenchPlanningMenu` **本来就会渲染**——菜单能打开、选项能点。但 `WorkbenchPlanningMenu` **没有内部 chatMode 状态**（`composer.tsx` L904-955，图标和文字 L926-933 完全由 props 决定），所以点击后父组件 `chatMode` 不更新 → **菜单立刻弹回「执行」**，`enablePlan` 一直是初始值 `execution`。

这解释了现象（**已实测确认**）：点「规划」→ 弹层关闭 → 按钮**还是显示「执行」**，父状态仍是 `execution`、`enablePlan` 仍是 `false`。用户看到的是"**我明明选了规划，可它自己变回去了**"。这是典型的"受控组件失去控制"——空回调让 props 永远不更新。

### 4.3 标题栏重构

| 改前 | 改后 |
| --- | --- |
| 标题是 `<button>`，点开 `Dropdown`（含 6 个菜单项：执行/规划、单/对比、关闭） | 标题是 `<span>` 静态文本 + 独立按钮 |
| 关闭藏在 Dropdown 里 | 关闭独立成 X 按钮 |
| 对比模式藏在 Dropdown 里 | 独立 `Columns2` 按钮 + `aria-pressed` |
| `Brush` 图标（清空） | `SquarePen` 图标 |

**CSS 改动与 JSX 一致**：因为标题从 `<button>` 改成 `<span>`，所以移除 `cursor: pointer` 是**正确的**（span 不该有手型光标，否则误导用户以为可点）。

同时补了 `gap: 16px`（header 内间距）和 `align-items: center` + `flex-shrink: 0`（actions 区），配合新加的第三个按钮。

---

## 五、场景验证与问题清单

### 🟡 M1 — 键盘用户丢失了一条操作路径

**页面**：Agent 配置 → 调试面板标题栏

**操作**：只用键盘，Tab 到标题

**看到的（改前）**：标题是 `<button>`，可 Tab 聚焦，按 Enter 打开 Dropdown，方向键选择"对比模式"/"关闭"

**看到的（改后）**：标题是 `<span>`，**不可聚焦**；对比/关闭改为独立按钮，需 Tab 到各自按钮

**为什么值得提**：

- **功能上没有损失**——对比和关闭现在都有独立按钮，且带 `aria-label`，键盘可达 ✅
- 但**原来的 Dropdown 提供了"一个入口做完所有事"的路径**，现在需要 Tab 过 4 个按钮（对比、清空、全屏、关闭）
- 更重要的是：`<span>` 里的 `title` 属性（L222）**在键盘聚焦时不会显示**，只有鼠标悬停才出现。长智能体名被 `min-w-0` 截断时，键盘用户无法看到全名

**这不是阻塞项**（PR 描述明确说了"名称改为静态文本"，是有意为之），但建议给 `<span>` 加 `tabIndex={0}` 让 `title` 能通过聚焦触发，或改用一个可访问的 tooltip：

```tsx
<Tooltip title={debugAgent.display_name || debugAgent.name}>
  <span className="agent-debug-header-title truncate" tabIndex={0}>
    ...
  </span>
</Tooltip>
```

### 💭 L1 — 可选 prop 的使用风格不一致

三个回调都是可选的：

```tsx
onCompareModeChange?: (value: boolean) => void;   // L38
onToggleFullscreen?: () => void;                   // L39
onClose?: () => void;                              // L40
```

但使用方式不同：

```tsx
onClick={() => onCompareModeChange?.(!isCompareMode)}   // L233 ← 有可选链
onClick={onToggleFullscreen}                            // L265 ← 直接传
onClick={onClose}                                       // L274 ← 直接传（本 PR 新增）
```

**实际风险为零**——我核实了唯一生产调用点 `page.tsx` L562-566，三个回调全部传了：

```tsx
<AgentDebugPanel
  onCompareModeChange={setIsCompareMode}
  onClose={closeDebug}
  onToggleFullscreen={() => { ... }}
/>
```

只有测试里 `render(<AgentDebugPanel />)` 不传。所以这只是**风格不一致**：要么都加 `?.`，要么把这三个 prop 改成必填（更严谨，让 TypeScript 帮忙检查）。

### 💭 L2 — 3 个 docs commit 在历史里留下"加了又删"的噪音

`c428c5dfc` 加截图 → `751d38e97` 换截图 → `122048900` 删截图。

**净效果是零**（最终无图片文件，这点做得对——截图不该进源码树）。但这三次往返留在 commit 历史里，`git log` 和 `git blame` 都会看到。

**建议**：这类"中途改变主意"的 docs commit 在合入前 squash 掉，或用 `git rebase -i` 合并成一个（如果还有 `docs:` 需要在历史里留痕的话）。若最终走 squash merge，这条自动消解。

### 💭 L3 — 图标语义变化未在描述中说明

`Brush`（刷子）→ `SquarePen`（带笔的方块）。PR 描述里写的是"标题栏提供对比、新对话清空、全屏和关闭调试"，但**没提图标换了**。

语义上 `SquarePen` 比 `Brush` 更贴近"新对话"（新建/书写），这个改进是合理的。只是这类视觉变化对用户是"体感突变"，建议描述里带一句，方便 UI 走查。

---

### 🟡 M2 — 模式切换的能力被收窄了：现在只有底部 composer 能切，标题栏不再能切

> 2026-10-29 11:45 补充（用户追问后复查）

**页面**：Agent 配置 → 调试面板

**操作**：想切换「规划 / 执行」模式

**看到的（改前）**：**两个入口都能切** —— ① 点标题栏的智能体名，下拉菜单里有「执行 / 规划」② 底部 composer 的模式按钮

**看到的（改后）**：**只剩底部 composer 一个入口**。标题栏的智能体名变成静态文本，下拉菜单整个被移除

**为什么值得提**（这不是 bug，是能力收窄，但描述里没说清楚）：

PR 描述写的是「标题栏提供对比、新对话清空、全屏和关闭调试」，**没有明说"模式切换从标题栏移除了"**。而改前的 Dropdown 里确实有 `execution` / `planning` 两项（改前 L219-220、L228）。

**关键在于**：改前的标题栏入口是**唯一能正常工作的模式切换**（它能调用 `setChatMode`）。底部 composer 那个是坏的（就是本 PR 修的 bug）。

所以用户的实际体验变化是：

- 改前：标题栏能切（好的）、底部不能切（坏的）
- 改后：标题栏不能切了、底部能切（修好了）

**净效果是"修好一个、移除一个"**。如果团队里有人习惯了从标题栏切模式，这次会突然找不到入口。

**建议**：PR 描述里补一句"模式切换统一收敛到底部 composer 入口"。这是有意的设计决策（避免双入口不一致，我在 §4.1b 分析过），但需要让人知道。

### 💭 L4 — 对比模式下切模式，两侧各有一份 adapter，依赖 `useLocalRuntime` 的隐式刷新

**代码链路**（已核实）：

```tsx
// compare-panel.tsx L119-128
const adapter = useMemo(
  () => createSideAdapter(modelId, Number(agent.id), enablePlan),
  [modelId, agent.id, enablePlan]     // ← enablePlan 变化会重建 adapter
);
const runtime = useLocalRuntime(adapter, { ... });
```

我读了 `@assistant-ui/core/dist/react/runtimes/useLocalRuntime.js` 确认机制：

```js
const [runtime] = useState(() => new LocalRuntimeCore(opt, initialMessages));  // 只创建一次
useEffect(() => {
  runtime.threads.getMainThreadRuntimeCore().__internal_setOptions(opt);  // ← 无依赖数组，每次渲染都跑
  runtime.threads.getMainThreadRuntimeCore().__internal_load();
});
```

**结论：能工作**。`runtime` 只创建一次（消息不会丢），但那个**无依赖数组的 effect** 每次渲染都会把新 `opt`（含新 adapter）推进去，所以切模式后 `enablePlan` 会生效。

**但这是依赖框架内部实现细节**：如果将来 assistant-ui 给这个 effect 加了依赖数组（比如 `[opt]` 但做了浅比较，或改成 `[chatModel]`），对比模式的模式切换就会静默失效。而**这一点没有任何测试覆盖**——测试里 `useLocalRuntime` 被 mock 成返回固定 `fixture.runtime`，adapter 重建这条路根本没走。

**建议**（可选）：对比模式的 `SideThread` 也改成普通调试那种显式 `setRunConfig` 方式（`agent-debug.tsx` L155-163），不依赖 adapter 重建 + 框架内部 effect。两条路径统一后，行为更可预测。这属于 follow-up，不阻塞本 PR。

### 🟡 M3 — commit 1 与 commit 5 之间的中间态是「完全不能切模式」（squash 后会消失，rebase 时会暴露）

> 2026-10-29 11:52 补充（用户指出后核实）

**用户提出的疑问**：删除了调用 `setChatMode(key)` 的标题菜单，但普通调试传给 `Thread` 的回调仍是 `onChatModeChange={() => undefined}`，所以选「规划模式」后状态不会更新。

**这个判断在 PR 的中间 commit 上完全成立。** 我逐 commit 核实了 `onChatModeChange={() => undefined}` 的存亡：

| commit | 说明 | 空函数 |
| --- | --- | --- |
| `bafb7607b` | merge-base（改动前） | ❌ 存在 |
| **`56ac78338`** | **fix: streamline agent debug header actions** | **❌ 仍存在** |
| `c428c5dfc` | docs: 加截图 | ❌ 仍存在 |
| `751d38e97` | docs: 换截图 | ❌ 仍存在 |
| `122048900` | docs: 删截图 | ❌ 仍存在 |
| **`7af62ae50`** | **fix: restore ordinary debug mode switching** | ✅ **已修复** |

**commit 1（`56ac78338`）的状态是：**

```
L97:  onChatModeChange={() => undefined}      ← 空函数还在
L292: onChatModeChange={setChatMode}          ← 只是传给了对比面板
```

同时，**标题栏那个能调 `setChatMode` 的 Dropdown 已经被这个 commit 删掉了**。

所以在这个中间态里：

- 标题栏入口：**没了**
- 底部 composer 入口：**还是坏的**（空函数）
- → **这个页面上任何地方都无法切换「规划 / 执行」模式**

比改动前更糟 —— 改动前至少标题栏还能切。

**这正是 commit 5 存在的理由**：`7af62ae50 fix(frontend): restore ordinary debug mode switching` —— "restore"（恢复）这个词说明作者意识到 commit 1 把能力弄丢了，补了一个 commit 修回来。

**所以最终状态（PR head）是正确的**，但导出两个教训：

1. **若用 squash merge**：三个 commit 压成一个，中间态不进入历史，问题消失 ✅
2. **若用 rebase merge 或维护者逐个 review commit**：`git log -p` 会看到 `56ac78338` 处"删了入口又没接上新入口"的破损状态，且这个 commit 单独看是**功能倒退**的

**建议**：
- 优先用 **squash**（本 PR 的 3 个 docs commit 本就是零净效果噪音，见 L2，压成一个正好一并解决）
- 若必须保留多 commit，建议把 `56ac78338` 和 `7af62ae50` 合并成一个 —— 因为前者单独存在是"半成品"，两者必须一起才构成完整修复

### 💭 L5 — 「修 bug」和「重构 UI」混在同一个 commit 的代价

commit 1 `56ac78338` 同时做了两件事：**删除标题栏 Dropdown**（重构）+ **没接上新的模式切换链路**（引入回归）。

这两件事本该分开：

- 若先接好底部链路再删标题栏 → 任何时刻都是可用的
- 实际是先删后接，中间留了个"功能倒退"的窗口

commit 5 的 subject 用了 "restore"（恢复）而不是 "fix"，正说明这是**自己造成的回归**再补回来。

**这不算缺陷**（最终代码正确），但作为流程建议：**改动"删除旧入口"时，应确保新入口在同一 commit 内就绪**，否则单 commit review 或 bisect 时会误判。

## 六、测试验证

### 6.1 实跑结果

独立 worktree + junction，**19 个测试全绿**：

```
npx vitest run --config vitest.workbench.config.ts \
  tests/workbench/AgentDebugHeader.test.tsx \
  tests/workbench/AgentDebugModelControls.test.ts
→ Test Files  2 passed (2)
  Tests      19 passed (19)
    AgentDebugHeader.test.tsx       8 tests
    AgentDebugModelControls.test.ts 11 tests
```

与 PR 描述的"标题栏/模式 8 项、请求适配器 11 项"完全一致。

### 6.2 反向验证（R2）

| 实验 | 操作 | 结果 | 判定 |
| --- | --- | --- | --- |
| 1 | 把 `onChatModeChange` 改回 `() => undefined`（还原 bug） | **2 个用例变红** | ✅ 反向验证有效 |
| 2 | 移除 `aria-pressed={isCompareMode}` | **2 个用例变红** | ✅ 反向验证有效 |

**实验 1 的失败细节**（证明测试真的在验模式切换）：

```
× switches ordinary debug mode both ways and updates the runtime planning flag
× shares the mode across ordinary and compare views without clearing unsent text
```

第一条用例名精确对应 bug：**"updates the runtime planning flag"**——不仅验 UI 切换，还验了 runtime 的 `enablePlan` 真的被更新。这是高质量断言的标志。

**实验 2 的失败细节**：

```
× shows a static name and toggles comparison both ways without replacing the single draft
× keeps fullscreen controls and English labels
```

### 6.3 测试质量亮点

`AgentDebugHeader.test.tsx`（276 行 8 用例）覆盖得比较扎实：

- `aria-pressed` 断言了完整往返：`false` → `true` → `false`（L191/197/201），不是只测单向
- 用例名明确表达意图，例如 **"shares the mode across ordinary and compare views without clearing unsent text"** —— 一次验证了"跨视图共享模式" + "不清空草稿"两个约束
- **"without replacing the single draft"** 系列：验证切换对比模式时单栏草稿不丢，这是容易 regress 的点

`AgentDebugModelControls.test.ts`（11 用例）测的是请求适配器序列化，正好覆盖 `enablePlan → enable_plan` 这一段（PR 描述称"规划标记请求序列化测试"）。

---

## 七、专项校验

| 检测项 | 结果 | 说明 |
| --- | --- | --- |
| 1. 数据格式/契约 | ✅ 无 | `backend/`、`sdk/` 零改动；仅前端 UI |
| 2. 版本回退 | ✅ 无 | 5 commit 无 Revert |
| 3. 敏感信息 | ✅ 无 | 零命中 |
| 4. locale 对齐 | ✅ **完美** | en/zh 各新增 `agent.debug.toggleCompareMode`，集合一致 |
| 5. **图片文件残留** | ✅ 无 | 3 个 docs commit 涉及截图，但最终 diff 无任何图片文件 |
| 6. 循环依赖 | ✅ 无 | 仅新增 lucide-react 图标 import |

### PR 描述的"验证限制"逐条核实

PR 自己列了 3 条限制，我都验证了**全部属实**（这种诚实披露值得肯定）：

| 声明 | 核实结果 |
| --- | --- |
| 全项目类型检查受 `.next/types` 引用不存在的 `space/evaluators` 页面阻塞 | ✅ `frontend/app/[locale]/space/evaluators/page.tsx` 确实不存在 |
| 正式测试资产校验受 `CHAT-AGENT-DETAIL-20261026` 引用的缺失文件阻塞 | ✅ `ConversationResumeBranch.test.tsx` 确实缺失（既有问题，非本 PR 引入） |
| PW-PROMPT-02 真实双模型 D4 未执行 | ✅ `NEXENT_TEST_HOME` 确实未设置 |

其中前两条是**存量问题**（在 merge-base 上就存在），不阻塞本 PR。

---

## 八、合并预演

| 目标 | 结果 |
| --- | --- |
| vs develop | **0 冲突** |

---

## 九、结论

### 总评

**一个定位精准的小修复**。核心 bug 是 `onChatModeChange={() => undefined}` —— 一个空函数让"受控组件"失去了控制，表现是**点了「规划」，按钮自己弹回「执行」**。因为菜单本身是纯受控的（无内部状态），所以连视觉反馈都没有，用户会以为"这个菜单坏了"或"我点错了"。

修复方式正确：把空函数换成 `setChatMode`，并确保 `enablePlan` 通过 `useConfig` 的 effect 真的更新到 `runConfig.custom`。测试用例名 **"updates the runtime planning flag"** 说明作者理解这个问题的本质——不只是 UI 切换，而是运行参数要同步。

标题栏重构也做得干净：CSS 改动与 JSX 一致（`<button>`→`<span>` 所以去掉 `cursor:pointer`），`aria-pressed` 正确表达对比模式的开关状态，en/zh 文案对齐。

**三条验证限制都如实标注**，并且我核实全部属实。这种"我知道哪里没验到"的披露，比笼统写"全部通过"有价值得多。

### 问题汇总

| # | 严重度 | 问题 | 场景 |
| --- | --- | --- | --- |
| M1 | 🟡 | 标题改 `<span>` 后不可聚焦，长名称截断时键盘用户看不到全名 | Tab 过标题无法聚焦，`title` 属性不触发 |
| M2 | 🟡 | 模式切换入口从 2 个收窄到 1 个（标题栏不再能切），描述未说明 | 习惯从标题栏切模式的用户找不到入口 |
| M3 | 🟡 | **中间 commit `56ac78338` 是「删了入口、新入口未接」的破损态** | squash 后消失；rebase/逐 commit review 时会暴露功能倒退 |
| L1 | 💭 | 三个可选回调使用风格不一致（一个有 `?.`，两个直接传） | 实际零风险（调用方都传了），纯风格 |
| L2 | 💭 | 3 个 docs commit 留下"加截图→换截图→删截图"往返噪音 | 净效果为零，但污染 `git log` |
| L3 | 💭 | `Brush`→`SquarePen` 图标变化未在描述中说明 | UI 走查时可能疑惑 |
| L4 | 💭 | 对比模式靠 adapter 重建 + 框架无依赖 effect 隐式生效，无测试覆盖 | 框架升级后可能静默失效 |
| L5 | 💭 | 「删 UI 入口」与「接新链路」混在不同 commit，留下回归窗口 | commit 5 用 "restore" 而非 "fix"，是自造回归 |

### 合并建议：**通过**

**无阻塞项。** 核心 bug 修复正确、链路贯通、测试有效且有反向验证保护。

M1 是唯一建议改代码的（给标题 `<span>` 加 `tabIndex={0}` 或用 Tooltip），但影响面小——只有长名称截断 + 纯键盘用户才感知。

M2 只需要补描述（不必改代码）：明确写出"模式切换收敛到底部 composer 单一入口"，让习惯从标题栏切模式的人知道入口变了。

L4 建议作为 follow-up：把对比模式的 `SideThread` 改成和普通调试一致的显式 `setRunConfig`，不要依赖 adapter 重建 + 框架内部无依赖 effect 的隐式行为。

L2 建议合入时用 **squash**，把 5 个 commit（尤其 3 个 docs 往返）压成 1-2 个，历史更干净。

**M3 让 squash 从"建议"升级为"强烈建议"**：中间 commit `56ac78338` 是「标题栏入口已删、底部入口未接」的破损态——那个 commit 单独 checkout 出来，模式切换完全不可用（比改动前更糟）。squash 能彻底消除这个中间态；若用 rebase 保留多 commit，逐 commit review 或 `git bisect` 会撞上它。这也符合项目"docs 截图不进仓库"的既定做法——既然最终不留，中途也不该留。

L1/L3 属可选优化。

---

## 十、附：本次评审的关键取证

| 判断 | 证据 | 结果 |
| --- | --- | --- |
| bug 根因是否是空函数 | `git diff` 看到 `- onChatModeChange={() => undefined}` | ✅ 确认 |
| UI 控件真的存在吗 | 读 `composer.tsx` L598-601、L761-767 两处渲染 | ✅ 存在，且改动前也会渲染（空函数是 truthy） |
| 模式是否真影响请求 | 追到 `remote-chat-model-adapter.ts` L1563 `enable_plan` | ✅ 链路完整 |
| CSS 去 `cursor:pointer` 是否合理 | 对比 JSX：标题确实从 `<button>` 变 `<span>` | ✅ 合理 |
| 测试真守护了吗 | 2 组反向验证 | ✅ 各 2 个用例变红 |
| 截图是否残留在仓库 | `git diff --name-only \| grep -E "\.(png\|jpg)$"` | ✅ 无残留 |
| PR 的 3 条验证限制是否属实 | 逐一核实文件存在性 + 环境变量 | ✅ 全部属实 |
