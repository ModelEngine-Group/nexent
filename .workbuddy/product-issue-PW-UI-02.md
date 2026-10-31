# PW-UI-02 产品问题说明：StandardModal 无法用 ESC 关闭

## 一、问题是什么

**一句话**：所有基于 `StandardModal` 的对话框（含「创建智能体」「添加模型」「编辑提示词」）**按 ESC 键完全无效**，键盘用户只能靠鼠标点击右上角关闭按钮或底部取消按钮退出。

**缺陷代码位置**：`frontend/components/common/StandardModal.tsx`（修复前第 80 行）

```tsx
<Modal
  open={open}
  centered
  closable={false}                  // ① 消除右上角 X 按钮
  mask={{ closable: false }}         // ② 点击遮罩不关闭
  keyboard={false}                   // ③ ESC 不关闭  ← 缺陷
  ...
>
```

**三条关闭路径被同时禁掉**，只剩 Modal 内部自定义的 `StandardCloseButton` 和 footer 取消按钮。

**底层库证据**（`@rc-component/dialog/es/DialogWrap.js`）：

```js
const onEsc = ({ top, event }) => {
  if (top && keyboard) {        // keyboard=false 时直接跳过，不调 onClose
    event.stopPropagation();
    onClose?.(event);
    return;
  }
};
```

`keyboard` 默认值是 `true`（第 24 行 `keyboard = true`），antd 的默认行为本来就是支持 ESC。是 `StandardModal` 这层封装**主动把它关掉了**。

---

## 二、如何复现

### 方式 A：浏览器手动复现（最快，3 步）

1. 启动前端（`http://localhost:3000`），用管理员账号登录
2. 进入 **智能体配置** 页（`/zh/agents`），按 `Tab` 键把焦点移到 **「新建」** 按钮，按 `Enter` 打开「创建智能体」对话框
   - 或用鼠标点击「新建」，效果一样
3. 按 `Esc` 键

**实际结果**：对话框**纹丝不动**，仍然显示
**期望结果**：对话框关闭，焦点回到「新建」按钮

同样可在 `/zh/models` → 「添加模型」对话框复现。

### 方式 B：自动化断言复现（用例原文）

`test-e2e/cases/PW-UI-02/case.yaml` 步骤 4：

```yaml
- order: 4
  action: 按Escape关闭，焦点返回触发元素。
```

`test.spec.ts` 对应实现：

```ts
async () => {
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "创建智能体" })).toBeHidden();  // ← 这里失败
  focusReturned = await trigger.evaluate((node) => node === document.activeElement);
  expect(focusReturned).toBeTruthy();
  return "Escape closed the dialog and restored focus to the New Agent trigger";
},
```

**10-22 批次实际失败信息**：

```
Error: expect(locator).toBeHidden() failed
Locator:  getByRole('dialog', { name: '创建智能体' })
Expected: hidden
Received: visible
Timeout:  30000ms

3 × locator resolved to <div role="dialog" aria-modal="true" ...>…</div>
  - unexpected value "visible"
59 × locator resolved to <div role="dialog" aria-modal="true" ...>…</div>
  - unexpected value "visible"
```

**3 次 + 59 次重试全部 visible**（共轮询 30 秒），说明不是时序问题，是**永久打不开关闭通路**。

### 方式 C：单元测试复现（我新增的，可双向验证）

新建 `frontend/tests/component/standardModalEscape.test.tsx`：

```tsx
it("closes on Escape by default", async () => {
  const onOpenChange = renderModal();          // 渲染 StandardModal
  const dialog = await screen.findByRole("dialog");
  fireEvent.keyDown(dialog, { key: "Escape", code: "Escape", keyCode: 27 });
  await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
});
```

**双向验证结果**：

| 代码状态 | 测试结果 |
|---|---|
| `keyboard={false}`（缺陷版） | ❌ **1 failed**（closes on Escape by default 失败，1187ms） |
| `keyboard={closeOnEscape}`（修复版） | ✅ **2 passed** |

这个对照证明测试确实钉住了这个缺陷，不是空断言。

---

## 三、期望 vs 实际：Gap 明细

| 维度 | 期望（规范要求） | 实际（修复前） | Gap |
|---|---|---|---|
| **ESC 关闭** | 必须关闭对话框 | 完全无响应（59 次重试均 visible） | **不满足** |
| **焦点归还** | 关闭后焦点回到触发元素 | 无从谈起（根本没关闭） | **不满足** |
| **规范出处** | WCAG 2.1.2 No Keyboard Trap；ARIA APG Dialog (Modal) Pattern 明确写 "Escape: Closes the dialog" | 违反 | **不合规** |
| **可关闭性** | 至少有 1 条键盘可达的关闭路径 | 只有鼠标可达的按钮（Tab 可达但需多次 Tab + Enter） | **降级** |
| **关闭路径数量** | 3 条（X / 遮罩 / ESC） | 1 条（自定义关闭按钮） | **少 2 条** |

### 严格说，"gap" 里有一层要澄清

**这不是"功能缺失"，是"默认行为被覆盖"**：

- antd Modal 本来的 `keyboard` 默认值就是 `true`（支持 ESC）
- `StandardModal` 封装时**显式传了 `false`**，把库的合理默认关掉了
- 所以修复的核心是**恢复默认**，而不是新增能力

### 为什么会这样写（推测的合理动机）

`closable={false}` + `mask.closable=false` + `keyboard={false}` 三件套一起出现，通常是为了**防止用户在填表单时误触关闭导致输入丢失**。这个诉求本身合理，但做法过头了：

- 防误触只需禁「点遮罩关闭」（最容易误触）
- 禁 ESC 会直接**违反 WCAG**，且键盘用户失去唯一的快捷退出方式
- 禁 X 按钮让对话框看起来没有关闭入口（很多用户会困惑）

---

## 四、修复方案与取舍

### 已实施的修复

`StandardModal.tsx` 新增 `closeOnEscape` 属性，**默认 `true`**：

```tsx
export interface StandardModalProps {
  // ...
  /**
   * Whether ESC dismisses the dialog. Defaults to `true` per WCAG 2.1.2 /
   * ARIA APG Dialog (Modal) Pattern ...
   */
  closeOnEscape?: boolean;
}

// 默认值
closeOnEscape = true,
// ...
keyboard={closeOnEscape}
```

### 为什么默认开而不是默认关

**影响面评估**（实际只有 2 个组件、3 处调用）：

| 调用方 | 表单规模 | 是否应允许 ESC |
|---|---|---|
| `CreateAgentModal`（创建智能体） | **1 个 Form.Item**（`displayName`）+ 模板选择区（非表单字段） | ✅ 可以，丢失成本极低 |
| `HighFidelityPromptEditModal`（编辑提示词） | 需进一步评估 | 待定 |

`CreateAgentModal` 只有 1 个文本字段，ESC 关闭丢失内容的代价极小，默认开启是安全的。

### 保留 opt-out 的意义

如果将来出现**长表单**（比如几十行的配置页），可以在调用点显式传 `closeOnEscape={false}`，但**必须在调用点写明理由**，让 a11y 例外可审查：

```tsx
<StandardModal
  closeOnEscape={false}
  // a11y exception: 40+ field deployment form; ESC dismissal would discard
  // unsaved work. Tracked in #XXXX.
  ...
>
```

### 未改动、需产品确认的两点

1. **`closable={false}`**（无右上角 X）——这是主动设计，还是历史遗留？很多用户习惯点 X 关闭，完全去掉会增加困惑。建议至少保留 X。
2. **`mask={{closable: false}}`**（点遮罩不关闭）——这个**建议保留**，防误触是合理诉求。

也就是说，我的修复只解决了"ESC 不可用"这个硬性违规，**X 按钮缺失**是另一个可讨论的产品体验问题，需要产品拍板。

---

## 五、状态

- ✅ 修复已实施（`closeOnEscape` 默认 true）
- ✅ 新增 2 个单元测试，双向验证通过（缺陷版失败、修复版通过）
- ✅ `createAgentModal.test.tsx` 7/7 无回归
- ⚠️ 待产品确认：是否需要恢复右上角 X 关闭按钮
- ⚠️ 待评估：`HighFidelityPromptEditModal` 是否属于长表单需要 opt-out
