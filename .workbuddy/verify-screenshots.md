# PR 验证截图指南

本文按「截图能说明什么」排序，每张图都给了**准确命令**、**预期输出**和**截图框选范围**。

全部命令均在本机实测通过（2026-10-22 19:11）。

---

## 截图 1：产品缺陷双向验证（最推荐，说服力最强）

**这张图能说明**：这个测试不是空转，它真的能捕获缺陷。

### 操作

打开一个终端，依次执行：

```bash
cd C:/code/nexent
```

**① 切到缺陷版**（把修复还原成 bug 代码）：

```bash
sed -i 's/keyboard={closeOnEscape}/keyboard={false}/' frontend/components/common/StandardModal.tsx
grep -n "keyboard=" frontend/components/common/StandardModal.tsx
```

预期看到：`89:      keyboard={false}`

**② 跑测试，会失败**：

```bash
cd frontend
npx vitest run tests/component/standardModalEscape.test.tsx
```

### 📸 此时截图（截图 A）

预期输出关键行：

```
 FAIL  tests/component/standardModalEscape.test.tsx > StandardModal Escape dismissal > closes on Escape by default
 ...
 ❯ tests/component/standardModalEscape.test.tsx:34:46
     34|     await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
       |                                              ^

 Test Files  1 failed (1)
      Tests  1 failed | 1 passed (2)
```

**截图框选**：从命令 `npx vitest run ...` 一直到 `Tests  1 failed | 1 passed (2)` 这几行。重点是最后的 `1 failed | 1 passed`。

**③ 恢复修复版**：

```bash
cd C:/code/nexent
sed -i 's/keyboard={false}/keyboard={closeOnEscape}/' frontend/components/common/StandardModal.tsx
grep -n "keyboard=" frontend/components/common/StandardModal.tsx
cd frontend
npx vitest run tests/component/standardModalEscape.test.tsx
```

### 📸 再截图（截图 B）

预期输出：

```
 ✓ tests/component/standardModalEscape.test.tsx (2 tests) 300ms

 Test Files  1 passed (1)
      Tests  2 passed (2)
```

**两张图放一起**就是完整的双向验证：缺陷版 1 failed → 修复版 2 passed。

---

## 截图 2：19 个组件测试全通过

**这张图能说明**：修复没有引入回归，且顺手修好了既有的 `sharedShellLayout` 10 个失败。

### 操作

```bash
cd C:/code/nexent/frontend
npx vitest run \
  tests/component/standardModalEscape.test.tsx \
  tests/component/createAgentModal.test.tsx \
  tests/component/sharedShellLayout.test.tsx
```

### 📸 截图

预期输出：

```
 ✓ tests/component/standardModalEscape.test.tsx (2 tests) 300ms
   ✓ CreateAgentModal (7)
   ✓ renders API-only templates with the existing high-fidelity dimensions 415ms
   ✓ creates once with the selected API description and the user's trimmed name 522ms
   ✓ clears selection on a second click and on reopening 613ms

 Test Files  3 passed (3)
      Tests  19 passed (19)
 Duration  5.29s
```

**截图框选**：`Test Files  3 passed (3)` 和 `Tests  19 passed (19)` 这两行是重点。

---

## 截图 3：4 条 D1 用例全部 PASS（最有分量）

**这张图能说明**：实际跑通了 4 条真实用例，不只是单元测试。

### ⚠️ 前置步骤（必须做，否则会看到全失败）

测试运行器的 `pretest` 会把产品 React 软链过来，但 `run_cases.py` 直接调 `vitest.mjs` **不经过 npm script**，必须手动对齐一次：

```bash
cd C:/code/nexent/test-e2e/infra/automation/d1/frontend
NEXENT_REPO=C:/code/nexent node ensure-product-react.mjs

# 确认版本已对齐，必须输出 19.2.3
node -e "console.log(require('./node_modules/react/package.json').version)"
```

如果输出 `18.2.0`，说明没对齐，跑出来会 12/12 全失败（假象）。

### 操作

```bash
cd C:/code/nexent/test-e2e
NEXENT_TEST_HOME=C:/code/nexent-test-suite \
C:/Users/byzha/.workbuddy/binaries/python/envs/default/Scripts/python.exe \
  infra/tools/run_cases.py \
  UT-FE-005 \
  UT-FE-AUTO-877E165BC61D430D \
  UT-FE-AUTO-190989439ADD3E0F \
  UT-FE-AUTO-63334E6F5D10C7FD
```

### 📸 截图

预期输出（实测）：

```
UT-FE-005: PASS; local evidence: C:\code\nexent-test-suite\runs\repository-local\...\UT-FE-005
UT-FE-AUTO-877E165BC61D430D: PASS; local evidence: ...
UT-FE-AUTO-190989439ADD3E0F: PASS; local evidence: ...
UT-FE-AUTO-63334E6F5D10C7FD: PASS; local evidence: ...
```

**截图框选**：整个 4 行输出。每行末尾的 `local evidence:` 路径就是证据目录。

---

## 截图 4：junit.xml 断言明细（技术 reviewer 最认这个）

**这张图能说明**：12 个测试、0 失败，且能看到每个测试的名称。

### 操作

```bash
# 找最新的 63334 运行目录
R=$(ls -td /c/code/nexent-test-suite/runs/repository-local/*UT-FE-AUTO-63334* | head -1)
cat "$R/junit.xml" | head -6
```

或者直接用记事本打开该目录下的 `junit.xml`。

### 📸 截图

预期看到：

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<testsuites name="vitest tests" tests="12" failures="0" errors="0" time="0.7145183">
    <testsuite name=".../UT-FE-AUTO-63334E6F5D10C7FD/test.test.tsx" tests="12" failures="0" errors="0" skipped="0">
        <testcase ... name="TopNavbar 不再承载用户区（用户区已迁至 SideNavigation） &gt; ...
```

**截图框选**：第 2 行 `<testsuites ... tests="12" failures="0" errors="0">` 最关键。

---

## 截图 5：用例契约校验

**这张图能说明**：改动没有破坏用例元数据规范。

### 操作

```bash
cd C:/code/nexent/test-e2e
C:/Users/byzha/.workbuddy/binaries/python/envs/default/Scripts/python.exe infra/tools/validate_execution.py | tail -3
```

### 📸 截图

预期输出：

```
Execution metadata valid: 704 cases, 702 implementations
```

---

## 截图 6：浏览器手动复现（非技术读者最直观）

**这张图能说明**：用户视角真的能感知到这个 bug 和修复。

### 前提

Nexent 已部署并运行（`http://localhost:3000`）。

### 操作

1. 浏览器打开 `http://localhost:3000/zh/agents`
2. 点击「新建」按钮，弹出「创建智能体」对话框
3. **按 Esc 键**

### 📸 截图

| 状态 | 现象 |
| :--- | :--- |
| 修复前（`keyboard={false}`） | 对话框**纹丝不动**，按 Esc 完全无反应 |
| 修复后（`keyboard={closeOnEscape}`） | 对话框**关闭**，焦点回到「新建」按钮 |

想看修复前的效果，可以临时改回 `keyboard={false}`，等前端热更新后截图。

---

## 建议的截图组合

如果只想贴 2-3 张，按这个优先级：

| 优先级 | 截图 | 理由 |
| :---: | :--- | :--- |
| 1 | **截图 A + B**（双向验证） | 证明测试有真实防护力，不是空转 |
| 2 | **截图 3**（4 条用例 PASS） | 证明真实用例跑通 |
| 3 | **截图 6**（浏览器 Esc） | 非技术读者也能看懂 |

---

## 常见问题

### Q：跑 `run_cases.py` 报 `No module named pytest` / `dotenv`

本地环境缺依赖。装一下：

```bash
C:/Users/byzha/.workbuddy/binaries/python/envs/default/Scripts/python.exe -m pip install pytest pytest-asyncio python-dotenv
```

但 **API-AUTO / REL-AUTO 跑不了**——它们还要 `smolagents` 等深层依赖，本地装不齐，只能靠 CI。

### Q：跑 63334 出现 12 个全失败

几乎一定是 React 版本没对齐。检查：

```bash
cd C:/code/nexent/test-e2e/infra/automation/d1/frontend
node -e "console.log(require('./node_modules/react/package.json').version)"
```

如果是 `18.2.0`，执行 `NEXENT_REPO=C:/code/nexent node ensure-product-react.mjs` 修复。

### Q：截图里怎么体现"这是我改的代码"

可以额外截一张 diff：

```bash
cd C:/code/nexent
git diff origin/develop..HEAD -- frontend/components/common/StandardModal.tsx
```

---

## 附：实测记录（2026-10-22 19:11）

| 验证项 | 实测结果 |
| :--- | :--- |
| 缺陷版 `standardModalEscape` | `Test Files 1 failed (1)` / `Tests 1 failed \| 1 passed (2)` |
| 修复版 `standardModalEscape` | `Test Files 1 passed (1)` / `Tests 2 passed (2)` |
| 三文件合并跑 | `Test Files 3 passed (3)` / `Tests 19 passed (19)` |
| 4 条 D1 用例 | `UT-FE-005` / `877E` / `190989` / `63334` 全部 PASS |
| 契约校验 | `Execution metadata valid: 704 cases, 702 implementations` |
| 63334 的 junit.xml | `tests="12" failures="0" errors="0"` |
