# PR 验证执行报告

执行时间：2026-10-22 19:15 - 19:18
执行人：AI Agent（全流程实际运行，非模拟）
分支：`fix/v5-test-alignment`（5 个提交，已推送至 origin）

---

## 执行总览

| # | 验证项 | 结果 | 关键数据 |
| :-: | :--- | :-: | :--- |
| 1 | 产品缺陷双向验证 | ✅ 通过 | 缺陷版 `1 failed \| 1 passed` → 修复版 `2 passed` |
| 2 | 前端组件测试 | ✅ 通过 | `Test Files 3 passed (3)` / `Tests 19 passed (19)` |
| 3 | 4 条 D1 用例实跑 | ✅ 通过 | 4 条全部 `PASS` |
| 4 | junit 断言明细 | ✅ 通过 | 合计 25 个测试点，**0 failures / 0 errors** |
| 5 | 用例契约校验 | ✅ 通过 | `704 cases, 702 implementations` |
| 6 | 浏览器页面可达 | ✅ 通过 | `/zh` 与 `/zh/agents` 均返回 `200` |

**六项全部通过。**

---

## 验证 1：产品缺陷双向验证

### 1-A 缺陷版（还原 `keyboard={false}`）

```bash
cd C:/code/nexent
sed -i 's/keyboard={closeOnEscape}/keyboard={false}/' frontend/components/common/StandardModal.tsx
cd frontend && npx vitest run tests/component/standardModalEscape.test.tsx
```

实际输出：

```text
     × closes on Escape by default 1212ms
     ✓ keeps Escape inert only when closeOnEscape is explicitly disabled 91ms
⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯
 FAIL  tests/component/standardModalEscape.test.tsx > StandardModal keyboard dismissal (WCAG 2.1.2 / ARIA APG) > closes on Escape by default
 Test Files  1 failed (1)
      Tests  1 failed | 1 passed (2)
   Duration  4.07s
```

**结论**：缺陷代码下，"按 Esc 关闭"用例失败（1212ms 后超时）。这证明断言确实锁定了这个缺陷。

### 1-B 修复版（`keyboard={closeOnEscape}`）

```bash
cd C:/code/nexent
sed -i 's/keyboard={false}/keyboard={closeOnEscape}/' frontend/components/common/StandardModal.tsx
cd frontend && npx vitest run tests/component/standardModalEscape.test.tsx
```

实际输出：

```text
 ✓ tests/component/standardModalEscape.test.tsx (2 tests) 295ms
 Test Files  1 passed (1)
      Tests  2 passed (2)
   Duration  2.91s
```

**结论**：修复后两个分支均通过（默认允许 Esc 关闭；显式传 `closeOnEscape={false}` 时 Esc 无效）。

---

## 验证 2：前端组件测试（19 个）

```bash
cd C:/code/nexent/frontend
npx vitest run \
  tests/component/standardModalEscape.test.tsx \
  tests/component/createAgentModal.test.tsx \
  tests/component/sharedShellLayout.test.tsx
```

实际输出：

```text
 Test Files  3 passed (3)
      Tests  19 passed (19)
   Duration  5.39s
```

**覆盖内容**：
- `standardModalEscape` 2 个：Esc 关闭的两个分支
- `createAgentModal` 7 个：创建智能体弹窗行为
- `sharedShellLayout` 10 个：**本次从 10 failed 修好为 10 passed**（补 `useRouter` mock）

---

## 验证 3：4 条 D1 用例实跑

### 前置：对齐 React 版本

```bash
cd C:/code/nexent/test-e2e/infra/automation/d1/frontend
NEXENT_REPO=C:/code/nexent node ensure-product-react.mjs
node -e "console.log(require('./node_modules/react/package.json').version)"
```

实际输出：`19.2.3` ✅（与产品一致；若为 `18.2.0` 会看到全失败假象）

### 执行

```bash
cd C:/code/nexent/test-e2e
NEXENT_TEST_HOME=C:/code/nexent-test-suite \
python infra/tools/run_cases.py \
  UT-FE-005 UT-FE-AUTO-877E165BC61D430D \
  UT-FE-AUTO-190989439ADD3E0F UT-FE-AUTO-63334E6F5D10C7FD
```

实际输出：

```text
UT-FE-005: PASS; local evidence: ...\20261022T111642948826Z-UT-FE-005
UT-FE-AUTO-877E165BC61D430D: PASS; local evidence: ...\20261022T111644970659Z-UT-FE-AUTO-877E165BC61D430D
UT-FE-AUTO-190989439ADD3E0F: PASS; local evidence: ...\20261022T111648619590Z-UT-FE-AUTO-190989439ADD3E0F
UT-FE-AUTO-63334E6F5D10C7FD: PASS; local evidence: ...\20261022T111656281370Z-UT-FE-AUTO-63334E6F5D10C7FD
```

**4 条全部 PASS。**

---

## 验证 4：junit 断言明细

逐条读取各用例证据目录的 `junit.xml`：

| 用例 | tests | failures | errors |
| :--- | :-: | :-: | :-: |
| `UT-FE-005` | 6 | **0** | **0** |
| `UT-FE-AUTO-877E165BC61D430D` | 1 | **0** | **0** |
| `UT-FE-AUTO-190989439ADD3E0F` | 6 | **0** | **0** |
| `UT-FE-AUTO-63334E6F5D10C7FD` | 12 | **0** | **0** |
| **合计** | **25** | **0** | **0** |

证据目录：`C:\code\nexent-test-suite\runs\repository-local\<run_id>\`

每个目录含 `junit.xml`、`status.json`、`step-1.log`。

---

## 验证 5：用例契约校验

```bash
cd C:/code/nexent/test-e2e
python infra/tools/validate_execution.py
```

实际输出：

```text
Execution metadata valid: 704 cases, 702 implementations
```

**结论**：全部用例元数据合法，本次改动（含新增 `preparation` 段、修改测试名）没有破坏契约。

---

## 验证 6：浏览器页面可达

```bash
curl -o /dev/null -w "%{http_code}" http://localhost:3000/zh
curl -o /dev/null -w "%{http_code}" http://localhost:3000/zh/agents
```

实际输出：

```text
/zh        -> 200
/zh/agents -> 200
```

页面标题：`AI Agent Platform`

容器状态：`nexent-web Up 4 hours`、`nexent-config Up 28 hours`

**结论**：环境可用，可进行手动 Esc 复现（打开 `/zh/agents` → 点「新建」→ 按 Esc）。

---

## 最终状态确认

| 项 | 状态 |
| :--- | :--- |
| 工作区未提交改动 | **0**（干净） |
| `StandardModal` 配置 | `keyboard={closeOnEscape}`（修复版，已恢复） |
| 分支提交数 | 5 个，均已推送 |

提交清单：

```text
8fd96ecfb test(e2e): verify the D1 frontend cases against the current identity contract
2e4f05fcc test(frontend): supply useRouter in next/navigation mocks
52ef34fa6 test(e2e): correct assertions that drifted from product behaviour
1f87dac3c test(e2e): realign D4 page objects with the current composer and navigation
acf503bed fix(modal): restore Escape dismissal in StandardModal
```

---

## 未能本地验证的部分（如实说明）

| 用例 | 原因 |
| :--- | :--- |
| `PW-*` 共 7 条 | 需 Playwright + 已部署浏览器环境，本地未配置 |
| `API-AUTO-DDE7582FFE405D54` | 需完整后端依赖（`dotenv` 可装，`smolagents` 装不齐） |
| `REL-AUTO-80AA755E2436D269` | 同上 |

这三类只做到**代码层面对齐**，运行结果以 CI 为准。此结论已同步写进 PR 描述的「验证状态说明」表。

---

## 截图建议

按说服力排序，推荐截这 3 张：

| 优先级 | 截图内容 | 关键行 |
| :-: | :--- | :--- |
| 1 | 验证 1-A + 1-B 并排 | `1 failed \| 1 passed` → `2 passed` |
| 2 | 验证 3 的 4 行 PASS | 4 个 `PASS` |
| 3 | 验证 4 的 junit 表 | `failures="0" errors="0"` |

验证 2 与验证 5 可作为补充。
