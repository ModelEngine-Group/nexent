# PR #4163 四个问题 —— 从场景讲清「到底哪里不对」

> 本文是对 `PR-4163-impact-analysis.md` 的**更正与重写**。
> ⚠️ **重要更正**：原报告的 M1「能力降级」判断**是错的**。我重新核实后确认 v0 对话框保留了全部三项能力。下面按"用户在哪个页面、点了什么、看到什么"的方式重讲四个问题。

---

## 先更正：M1 不成立

原报告说「v0 三样全无」，实际逐项核实后是**全部都有**：

| 能力 | 原报告判断 | **实际情况** | 证据 |
| --- | --- | --- | --- |
| 高级参数设置 | ❌ 说没有 | ✅ **有** | v0 L738 `高级设置` 按钮 → L791 `RowSettingsDialog` → L1547 复用 `ModelAdvancedConfig`，注释写明"capacity + inference for LLM family" |
| 提交前连通性探测 | ❌ 说没有 | ✅ **有** | 单个：L519 `if (probe !== "available")` **强制门控**；批量：L1049 `rowCheck !== "available"` **强制门控** |
| 批量逐行参数编辑 | ❌ 说没有 | ✅ **有** | L827 `RowOverride { displayName, settings }` + L855 `rowOverrides` per-row 覆盖 + L1097 `applyAdvancedSettingsToParams` |

**决定性证据**是 `ModelAdvancedSettings.tsx` L207-210 的注释：

> Resolve which reasoning controls a model exposes from its catalog capability. **Shared by ModelAdvancedSettings and the v0 ModelAdvancedConfig so the two dialogs render identical controls.**

以及 L259-261：

> Shared reasoning-form state effects (develop #4009 semantics), **used by ModelAdvancedSettings and the v0 ModelAdvancedConfig**

两套对话框**渲染相同的控件**，这是代码作者刻意保证的。

### 那 v0 到底比 V2 少了什么？——**反而更严**

| 维度 | V2 | v0 |
| --- | --- | --- |
| 单个添加：提交前必须探测通过 | 未强制 | **强制**（L519） |
| 批量添加：每行必须探测通过 | 强制 | 强制（L1049） |
| 未检测时的行为 | — | 弹警告「请先通过连通性检测再添加模型」（L522） |

**v0 是更严格的版本，不是简化版。** 原报告被 `ModelAddDialog.tsx` L70-73 那段注释误导了——注释说 "Deliberately simple: no per-row capacity or inference-param editing and no pre-submit connectivity gate"，但那是**过期注释**，代码后来补齐了这些能力，注释没跟着改。

### 但仍然存在一个真实场景问题（重新定义为 M1'）

**场景**：租户管理员在「资源管理 → 模型」点「添加模型」，选了一个服务商预设模型。

| 步骤 | 用户体验变化 |
| --- | --- |
| 改前（V2） | 填完基础字段 → 可直接点「添加」→ 模型入库 |
| 改后（v0） | 填完基础字段 → 点「添加」→ **被拦下**：「请先通过连通性检测再添加模型」→ 必须再点一次「检测连通性」 |

这不是能力缺失，而是**多了一步强制操作**。对已经知道模型能连通的管理员（比如内部部署的模型），这是纯增负担。

**这算问题吗？** 算，但严重度从 🟡 降为 💭——因为：
- 强制探测能防止把连不上的模型写进库（数据质量更好）
- 但**这个行为变化 PR 描述一个字都没提**，属于静默的行为变更

**建议**：要么在描述里说明"新增对话框现在强制先探测"，要么给个"跳过检测"的逃生口（类似 V2 的 `NotDetected` 状态）。

---

## M2：共享 timer 丢跨行点击（这个是真问题）

### 场景还原

**页面**：模型管理页 → 模型列表 → 每行有「检测连通性」按钮

**操作**：管理员看到 3 个新加的模型都没检测过，想一个个点一下检测。

```
t=0.0s   点第 1 行「检测连通性」
         → 界面上第 1 行没有任何变化（还是"未检测"灰点）
t=0.4s   点第 2 行「检测连通性」
         → 第 1 行那次点击被静默作废
t=1.4s   只有第 2 行开始转圈 → 出结果
```

**用户看到的现象**：第 1 行**点了没反应**。没有转圈、没有报错、没有 toast，就是没反应。

**为什么这是新问题**：

改前（旧代码）在 timer **外**就设了 CHECKING，所以第 1 行至少会变成"检测中"的转圈状态。虽然那个状态会永久卡住（这是本 PR 要修的 bug），但**用户看得见东西发生了**。

改后把 CHECKING 挪进 timer 回调，被取消的点击连状态都不留——**从"卡住但可见"变成"完全不可见"**。

**业务后果**：管理员会以为按钮坏了，反复点同一行（这时又变成只探测最后一次，看似"能用了"），或者干脆放弃检测直接去编辑。

### 代码点

```tsx
// modelConfig.tsx L756-758
if (throttleTimerRef.current) clearTimeout(throttleTimerRef.current);   // ← 上一行的点击在此被丢弃
throttleTimerRef.current = setTimeout(async () => {
  updateModelStatus(displayName, modelType, MODEL_STATUS.CHECKING);     // ← 只有这行被执行到才可见
```

### 为什么原作者会这么写

代码注释（L751-755）说明了他的顾虑：

> a superseded click never sent its request, so it must not leave a stuck "detecting" status behind (the row action disables while detecting, leaving the operator no way to recover without a full reload)

他关心的是"同一行连点"不能留 stuck 状态。**这个目标达成了**。但他用的共享 timer 是**跨行共享**的，顺手把跨行的点击也丢了——这不是他想要的副作用。

### 修法

```tsx
// 按行独立 timer，key 与 updateModelStatus 的定位维度一致
const throttleTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

const verifyOneModel = async (displayName: string, modelType: ModelType) => {
  if (!displayName) return;
  const key = `${displayName}::${modelType}`;
  const prev = throttleTimersRef.current.get(key);
  if (prev) clearTimeout(prev);
  const timer = setTimeout(async () => {
    throttleTimersRef.current.delete(key);
    updateModelStatus(displayName, modelType, MODEL_STATUS.CHECKING);
    // ... 原有探测逻辑不变
  }, 1000);
  throttleTimersRef.current.set(key, timer);
};
```

这样同一行连点仍然只发一次（原目标保留），不同行各自独立。

**或者**（改动更小）：保留共享 timer，但在 `clearTimeout` 前，如果被取消的行不在 CHECKING 状态，就给它加个短暂的"已排队"提示。

---

## M3：漏网点（这个是真问题，但发生概率低）

### 场景还原

**页面**：会话页（新建对话）

**操作**：打开一个配置了 `example_questions` 的 Agent，看输入框上方的"推荐提示词"卡片。

正常情况下这 3-4 张卡片显示 Agent 预设的问题。**如果 `example_questions` 数组里有空白项**（`""` 或 `"   "`），改前会渲染出一张**空白卡片**——点进去会往输入框里塞空文本。

**本 PR 修了这条路径**（`thread.tsx` L785 `.filter(q => q.trim())`）。

### 漏在哪

```tsx
// thread.tsx L782-791
const suggestions = welcomeSuggestions?.length
  ? welcomeSuggestions.slice(0, 4)          // ← 这个分支没 filter
  : (agent.example_questions || [])
      .filter((question) => question.trim())  // ← 只修了 else
      .slice(0, 4)
      .map(...)
```

**两个分支是互斥的**：只要传了 `welcomeSuggestions`，就用上面那个分支，`example_questions` 的过滤完全不生效。

### 什么时候会踩到

`welcomeSuggestions` 来自 `nl2agent-chat-panel.tsx` L161-176：

```tsx
.map((suggestion) => ({
  id: suggestion.id,
  title: t(suggestion.titleKey),      // ← i18n 缺 key 时返回空串
  description: t(suggestion.descriptionKey),
  prompt: t(suggestion.promptKey),
}))
```

**触发条件**：某个 `NL2AGENT_DEFAULT_SUGGESTIONS` 或 `AGENT_CREATION_EXAMPLES` 里的 `titleKey` 在 locale 文件里缺失（比如新加了建议项但忘了补翻译）。

这时 `t(key)` 返回 `key` 本身还是空串？——取决于 i18n 配置。如果是 `returnEmptyString: false`（常见默认），会返回 key 原文，不至于空白；如果配了别的策略，可能返回空。

**实际发生概率低，但存在**。

### 修法（一行）

```tsx
? welcomeSuggestions
    .filter((s) => String(s.title ?? "").trim() || String(s.prompt ?? "").trim())
    .slice(0, 4)
```

### 为什么值得提

PR 的立意是「skip blank preset questions」。既然改，两个分支应该一起改，否则下个人看到代码会疑惑"为什么只过滤一半"。

---

## M4：标题诉求零测试（这个是真问题，最好修）

### 场景还原

**页面**：Agent 配置 → 提示词（Prompt）编辑区

**操作**：粘贴一段 5000 字的提示词（真实场景：从别处复制一段详细的工作说明）

| 版本 | 结果 |
| --- | --- |
| 改前（limit=1000） | 输入框卡在 1000 字，**后面的内容被静默吞掉**，计数器显示 `1000/1000` |
| 改后（limit=100000） | 完整输入 5000 字，计数器 `5000/100000` |

**这个修复对用户价值很直接**——1000 字对 Agent 提示词太少了。

### 问题

5 个修复里 4 个有测试：

| 修复 | 测试 |
| --- | --- |
| 空白建议过滤 | ✅ AgentDebugWelcome.test.tsx (5 用例) |
| 模型编辑对话框路由 | ✅ modelEditDialog.test.tsx (3 用例) |
| 未测试探测卡住 | ✅ modelConfigVerify.test.tsx (2 用例) |
| 新增对话框路由 | ✅ modelAddDialog.test.tsx (2 用例) |
| **prompt 上限 100000** | ❌ **无** |

我 grep 了全库 `frontend/tests/` 下的 `100000`，只有一处无关命中（`knowledgeBaseViewport.test.ts` 里的分页参数）。

**意味着什么**：如果有人把这个值改回 1000，或者改成 50000，CI **全绿**。而这是 PR 的标题诉求——最该被锁定的那一条。

**对比**：`agent-prompt.tsx` 已经有现成测试 `frontend/tests/component/agentSinglePrompt.test.tsx`，加一行断言就行。

### 修法

```tsx
// agentSinglePrompt.test.tsx
it("allows long prompts up to 100000 characters", () => {
  // 渲染 AgentPrompt 组件...
  const textarea = screen.getByRole("textbox", { name: /prompt/i });
  expect(textarea).toHaveAttribute("maxlength", "100000");
  // 或者验证计数器
  expect(screen.getByText(/\/100000/)).toBeInTheDocument();
});
```

---

## 四个问题重新定级

| # | 问题 | 原定级 | **修正后** | 真实场景表现 |
| --- | --- | --- | --- | --- |
| M1' | v0 强制先探测才能添加（行为变更未告知） | 🟡 | **💭 轻微** | 新增模型时多点一次「检测连通性」，被拦下会弹警告 |
| M2 | 共享 timer 丢弃跨行点击 | 🟡 | **🟡 建议** | 快速点两行的检测，第一行**完全无反应** |
| M3 | welcomeSuggestions 分支漏过滤 | 🟡 | **🟡 建议** | i18n 缺 key 时欢迎区出现空白卡片（概率低） |
| M4 | prompt 上限零测试 | 🟡 | **🟡 建议** | 无用户可见问题，但改回旧值 CI 不会红 |

**合入判断修正**：原报告说"阻碍项 M1"，现在 **M1' 降为 💭，不再是阻碍项**。

**结论改为：通过（建议顺手修 M2 + M4）**

- **M2 最值得修**：用户点了没反应，会被当 bug 报
- **M4 最该补**：一行断言，锁住 PR 的核心诉求
- M3 一行 filter，可带可不带
- M1' 只需在描述里说一句"新增对话框现在强制先探测"

---

## 我这次误判的教训

原 M1 的判断基于 `ModelAddDialog.tsx` L70-73 的类注释：

```
Deliberately simple: no per-row capacity or inference-param editing and
no pre-submit connectivity gate (the v0 logic) — models land in
not_detected state and are checked/edited from the library afterwards.
```

我拿这段注释当结论，**没有去验证 UI 里实际的按钮和面板**。而代码后来补齐了 `RowSettingsDialog`、`rowOverrides`、`probe` 门控，注释却停留在旧状态。

**教训**：注释是作者某一时刻的意图，不是代码的当前事实。判断"有没有某能力"必须找**实际渲染的 UI 元素**（按钮文案、组件引用、状态变量），不能只读注释。
