# PR #4246 检视报告

**标题**：fix: persist agent tutorial preferences through shared storage
**作者**：hzw ｜ **提交**：`4dc214c94`（1 个）
**规模**：6 文件 / +199 −25
**检视时间**：2026-10-29
**检视方式**：拉取 `refs/pull/4246/head`，逐个文件读 diff + 实际运行验证

---

## 结论

**功能方向是对的，逻辑基本正确，但目前不建议直接合并。** 有 1 个中等问题（内存态污染）、3 个应改的细节、1 个流程问题（落后 develop 8 个提交）。

已验证通过的部分：类型检查无新增错误、新增 3 个测试全过、双引导隔离正常、脏数据容错正常、无渲染死循环、首屏不闪烁。

---

## 一、这个 PR 想解决什么

### 背景

`agents/page.tsx` 的配置引导原来是：

```tsx
const [isGuideExpanded, setIsGuideExpanded] = useState(true);   // 刷新就重置
const [isGuideMounted, setIsGuideMounted] = useState(true);
```

**纯组件内 state，刷新即丢失**。用户折叠了引导，下次进页面又弹出来。

另一处 `agentCreationGuide.ts` 用 `<key> = "1"` 的 localStorage 存「已看过的创建引导」，是**另一套独立机制**，只能存一个布尔值，无法扩展。

### 本 PR 的做法

抽出统一的 `lib/guidePreferences.ts`：

```ts
type GuideId = "agent-configuration" | "agent-creation";
// key: nexent.guide-preferences.v1/{tenantId}/{userId}
// value: { "agent-creation": { dismissed: true }, "agent-configuration": { dismissed: false } }
```

加 `useGuidePreference` hook 用 `useSyncExternalStore` 订阅，两处引导都走它，并做了旧 key 的**自动迁移**。

### 这个设计合理的地方

| 点 | 说明 |
| :--- | :--- |
| 多引导可扩展 | 从「一个 key 一个布尔」升级为「一个 key 多个引导」，加引导不用再加 storage key |
| 按用户隔离 | key 含 `tenantId` + `userId` 且都 `encodeURIComponent`，多租户/多账号互不干扰 |
| 旧数据迁移 | `isGuideDismissed` 里检测到旧 key 为 `"1"` 会自动写进新结构，老用户不会又被弹一次 |
| 跨 Tab 同步 | 监听原生 `storage` 事件，另一个 Tab 折叠了这边也跟着变 |
| 同页多实例同步 | 自定义事件 `nexent-guide-preferences`，补上 `storage` 事件在同页不触发的缺口 |
| 降级有兜底 | localStorage 抛异常（隐私模式/配额满）时退到内存 Map，UI 不会崩 |

---

## 二、发现的问题

### 🔴 中等问题 1：内存态会永久污染，且跨 `clear()` 存活

**位置**：`frontend/lib/guidePreferences.ts` 的 `read()`

```ts
function read(key: string): Preferences {
  try {
    const value = JSON.parse(window.localStorage.getItem(key) ?? "{}");
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return { ...value, ...memory.get(key) };   // ← memory 永远覆盖 storage
    }
  } catch { /* 忽略 */ }
  return memory.get(key) ?? {};
}
```

`setGuideDismissed` 只在**写失败**时才写 `memory`，但 `read` 里 **`memory` 的优先级永远高于 storage**，且 `memory` 只在写成功时才 `delete`。

**实测证实的后果**（我写了探针测试跑出来的）：

```
after memory write: true
after clear (should be false): true     ← localStorage.clear() 之后仍然是 true
```

即：一旦某次写入失败落了内存，**这个 key 之后无论 storage 里是什么、哪怕被清空，读出来永远是内存里那个值**。用户「重置引导」也无效——因为 `setGuideDismissed(key, id, false)` 若写成功会 `delete` 掉 memory，这点还好；但如果此时 storage 仍然不可写，memory 会一直保留旧值，UI 永远显示「已折叠」。

**真实场景**：用户在 Safari 无痕模式 / 存储配额满时操作，折叠了引导；之后恢复正常模式或腾出空间，引导仍然消失且永远回不来。

**建议**：内存只作为「storage 不可用时的临时替身」，不该长期压过 storage。两种改法：

```ts
// 改法 A：storage 可读就以 storage 为准，memory 只做兜底
function read(key: string): Preferences {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw !== null) {
      const value = JSON.parse(raw);
      if (value && typeof value === "object" && !Array.isArray(value)) return value;
    }
    return memory.get(key) ?? {};     // storage 键不存在时才看 memory
  } catch {
    return memory.get(key) ?? {};
  }
}
```

```ts
// 改法 B：保留 merge，但写成功后无条件清 memory（含 read 时的惰性清理）
// 至少要保证 storage 一旦可写，memory 立刻失效
```

---

### 🟡 应改 1：迁移旧 key 后没有删除旧数据

**位置**：`isGuideDismissed` 的迁移分支

```ts
if (legacyKey && window.localStorage.getItem(legacyKey) === "1") {
  setGuideDismissed(key, id, true);
  return true;
  // ← 没有 removeItem(legacyKey)
}
```

实测：

```
shared stored: {"agent-creation":{"dismissed":true}}
legacy still present: 1      ← 旧 key 还在
```

功能上没坏（新 key 优先级更高，`isGuideDismissed` 先读新结构），但**旧 key 永久残留**，用户 localStorage 里会同时存在两套格式。而且如果将来有人改了读取顺序，旧值会重新生效。

**建议**：迁移成功后 `window.localStorage.removeItem(legacyKey)`，并包在 try/catch 里。

---

### 🟡 应改 2：`useGuidePreference` 里的字符串替换是隐式契约，很脆

```ts
const key =
  preferenceKey?.replace(
    "nexent.agent.creation-guide.v1/",
    "nexent.guide-preferences.v1/"
  ) ?? ...
```

`preferenceKey` 是调用方传进来的**完整 storage key**，hook 内部靠「前缀字符串替换」推算出新 key。这意味着：

1. `agentCreationGuide.ts` 里 `GUIDE_VERSION = "v1"` 一旦改成 `v2`，这个 `replace` **静默失效**——`replace` 找不到就原样返回，于是新 key 变成旧的 legacy key 格式，写入污染。
2. `agentCreationGuide.ts` 里 `sharedKey()` 做的是同样的替换，**两处重复逻辑**，改一处忘另一处就错位。

**建议**：不要让 hook 去「猜」key。让调用方直接传 `tenantId` / `userId`：

```ts
// 调用方
const { dismiss } = useGuidePreference("agent-creation");   // 内部自己算 key

// 或显式传结构化参数
useGuidePreference({ id: "agent-creation", tenantId, userId })
```

若要保留 `preferenceKey`，至少把 `GUIDE_VERSION` 拼进正则或断言前缀存在：

```ts
if (!preferenceKey.startsWith(LEGACY_PREFIX)) throw new Error(...)
```

---

### 🟡 应改 3：`lib/guidePreferences.ts` 缺 `"use client"`

文件里直接访问 `window.localStorage`、`window.dispatchEvent`，但文件头没有 `"use client"`。

目前两个调用方（`agents/page.tsx`、`agent-creation-guide.tsx`）都是 `"use client"`，所以**现在不会炸**。但这是个定时炸弹：任何人从 Server Component 或 Route Handler 里 import 它，就会拿到 `window is not defined`。

对比：`hooks/useGuidePreference.ts` 有 `"use client"`，同目录 `lib/userIdentity.ts` 这类纯函数库则刻意无副作用。这个文件不是纯函数，应该标上。

**建议**：加 `"use client"`。或者把 `window` 访问再包一层 `typeof window !== "undefined"`。

---

### 🟢 细节 1：`setGuideDismissed` 在 SSR 下会抛

```ts
window.dispatchEvent(new Event("nexent-guide-preferences"));
```

这行在 try/catch **外面**。如果 `window` 不存在（SSR），前面 `setItem` 已经 catch 住了走 memory，但这一行会直接 `ReferenceError`。

同样因为调用方都是 client 组件，现在不会触发，但配合上一条一起修更稳。

---

### 🟢 细节 2：测试在 workbench 配置下才跑，容易被漏

新增的 `tests/workbench/GuidePreferences.test.ts` 属于 workbench 套件：

- `vitest.config.ts` 的 include 是 `tests/component/**/*.test.tsx`
- `vitest.workbench.config.ts` 的 include 是 `tests/workbench/**/*.test.{ts,tsx}`
- 对应脚本分别是 `npm run test:components` 和 `npm run test:workbench`

确认过 CI 会跑（`test:workbench` 有独立脚本），**只是提醒**：如果本地只跑 `npm test`，这个测试不会被执行。放在 `tests/workbench/` 而不是 `tests/component/` 是因为它测的是 `lib/` + `hooks/`，这个归类是对的。

---

## 三、流程问题：分支落后 develop 8 个提交

```
PR 落后 develop: 8 个提交
PR 领先 develop: 1 个提交
是否有冲突: 无（可干净合并）
```

**实证影响**——我分别在两个分支上跑了 `npm run test:workbench`：

| 分支 | 测试文件 | 测试数 | 失败 |
| :--- | :---: | :---: | :---: |
| `origin/develop` | 80 | 596 | 13 failed（5 文件） |
| `pr-4246` | 79 | 578 | 11 failed（4 文件） |

PR 少了 18 个测试，是因为 develop 上有两个 PR 分支还没有的测试文件：

```
frontend/tests/workbench/AgentDebugHeader.test.tsx
frontend/tests/workbench/ConversationResumeBranch.test.tsx
```

**这不代表 PR 修好了什么**，只是它没跟上 develop。

**重要说明**：两边都失败的那 4 个文件（`AutomationResultExpansion`、`ModelSelectorThinking`、`ThreadPins`、`WorkbenchThreadAdapter`）**是 develop 既有失败，与本 PR 无关**。我做了对照验证，不是 PR 引入的。

**建议**：合并前 rebase 到最新 develop，让 CI 在完整基线上跑一次。

---

## 四、验证记录

实际执行的检查：

| 检查 | 结果 |
| :--- | :--- |
| 新增 3 个测试 | ✅ `3 passed` |
| `npx tsc --noEmit` | ✅ PR 新增文件无错误（其余错误在 develop 既有代码：`thread-agent-registry.ts`、`NotificationBell.tsx`、`vitest.config.ts` 的 `oxc` 字段） |
| 双引导隔离 | ✅ 折叠 A 不影响 B |
| 渲染稳定性 | ✅ 挂载 1 次、dismiss 后 2 次，无 `useSyncExternalStore` 死循环 |
| 首屏闪烁 | ✅ 渲染条件从 `isGuideMounted` 改为 `isGuideExpanded \|\| isGuideMounted`，首屏即展开 |
| 脏数据容错 | ✅ `{"agent-creation":"yes"}`、`{dismissed:"true"}`、数组 payload 均安全返回 `false` |
| 内存污染 | ❌ **确认存在**（见问题 1） |
| 旧 key 残留 | ⚠️ **确认存在**（见应改 1） |
| workbench 全量 | PR 11 failed / develop 13 failed，均为既有问题 |

---

## 五、给作者的建议

按优先级：

1. **修内存态优先级**（问题 1）—— 这是唯一会让用户「引导再也回不来」的真 bug
2. **迁移后删旧 key**（应改 1）—— 一行 `removeItem`
3. **key 推算改成显式参数**（应改 2）—— 消除 `replace` 静默失效风险
4. **加 `"use client"`**（应改 3）—— 防未来踩坑
5. **rebase develop**（流程）—— 让 CI 在完整基线验证

另外补一句：`reset()` 在 `setGuideExpanded(true)` 时调用，会**持久化**「未折叠」状态。这个语义是对的（用户主动展开，说明想看），但值得在 PR 描述里写清楚，否则 reviewer 容易误以为「reset 只重置内存」。

---

## 附：探针测试怎么复现

我用的探针（已删除，未提交）：

```ts
it("memory leaks across localStorage.clear", () => {
  const key = "nexent.guide-preferences.v1/t/u";
  const spy = vi.spyOn(Storage.prototype, "setItem")
    .mockImplementation(() => { throw new Error("denied"); });
  setGuideDismissed(key, "agent-creation", true);   // 落进 memory
  spy.mockRestore();
  expect(isGuideDismissed(key, "agent-creation")).toBe(true);   // 正常
  localStorage.clear();
  // 期望 false，实际 true —— BUG
  expect(isGuideDismissed(key, "agent-creation")).toBe(true);
});
```

运行：

```bash
cd frontend
npx vitest run --config vitest.workbench.config.ts
```
