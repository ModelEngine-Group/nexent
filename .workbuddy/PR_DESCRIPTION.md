# 🔧 fix: 对齐 V5 测试用例与产品实际行为，修复 StandardModal ESC 关闭缺陷

## 修改说明

将 `fix/v5-test-alignment` 合入 `develop`，**8 个提交 / 21 个文件 / +327 −101**。

其中产品代码仅改动 `frontend/components/common/StandardModal.tsx` 一处关闭行为，其余全部为测试用例与测试基础设施，**未改动部署配置、未改动 GitHub workflow**。

修复对象为 10-22 批次 D4/D5 回归中 **19 条**未通过用例。逐条排查（`10-22未通过用例` 工作表 + `latest-batch.zip` 内 `junit.xml`/`failure.json` + 代码走查）后的分布如下，本 PR 修掉前两类共 **16 条**：

| 判定 | 条数 | 用例 |
| :--- | :---: | :--- |
| 产品问题 | 1 | `PW-UI-02` |
| 测试侧问题 | 15 | 见下方逐条明细 |
| 环境缺失（本 PR 不改） | 3 | `CTR-016`、`CTR-017`、`REL-02` |

---

## 一、产品缺陷（1 条）

### `PW-UI-02` 键盘可访问性 Smoke：导航 → Dialog → 表单 → 关闭

| 项 | 内容 |
| :--- | :--- |
| **原失败** | `expect(locator).toBeHidden()` 失败，日志显示 `3 × ` 与 `59 × ` 两次轮询后 `role="dialog"` 始终 `visible`，30s 超时 |
| **根因** | `StandardModal.tsx:80` 硬编码 `keyboard={false}`，叠加同处的 `closable={false}` 与 `mask={{closable:false}}`，**三条关闭路径被同时禁用** |
| **关键证据** | 底层 `@rc-component/dialog/es/DialogWrap.js` 中 `keyboard = true` 本就是默认值，且 `onEsc` 只在 truthy 时触发：`if (top && keyboard) { event.stopPropagation(); onClose?.(event); }`。这说明是**封装层主动覆盖了可用默认值**，而非功能缺失 |
| **规范依据** | 违反 WCAG 2.1.2（No Keyboard Trap）与 ARIA APG Dialog (Modal) Pattern，两者均明确要求 Escape 关闭对话框 |
| **修复** | `keyboard={false}` → `keyboard={closeOnEscape}`，新增 prop 默认 `true`，保留 opt-out 给真正会丢失大量输入的长表单 |
| **影响面** | 调用方仅 2 个组件共 3 处。`CreateAgentModal` 只有 1 个 `Form.Item`（`displayName`）+ 模板选择区，Escape 丢失成本极低；`HighFidelityPromptEditModal` 留待单独评估 |
| **本次未改** | `closable={false}`（无右上角 X）保留。属产品体验决策，建议至少恢复 X，但需产品拍板 |
| **测试** | 新增 `standardModalEscape.test.tsx` 覆盖 `true`/`false` 两个分支，并做了缺陷版反向验证（见「验证方法」§1） |

---

## 二、定位器失效（7 条）

前端两次重构（Composer 组件库迁移、导航改版）使这批选择器全部指向不存在的元素，表现为 30s 超时而非断言失败。

| 用例 | 原定位器 | 失效原因（代码事实） | 改为 |
| :--- | :--- | :--- | :--- |
| `PW-MEDIA-STT-01` | `getByPlaceholder('发送消息...')` | `composer.tsx:703` 与 `:715` 的 `placeholder` 被**显式置为空字符串** `placeholder=""`；输入框已从 `<textarea>` 改为 Lexical contenteditable（`.aui-lexical-input`），`inputValue()` / `toHaveValue()` 同时失效 | 新增 `ChatPage.composerText()` 读 `innerText` 并剔除零宽字符；`expectComposerText()` 做轮询断言 |
| `PW-MEDIA-VLM-01` | `[data-composer-action-trigger]` | 全前端代码库**零匹配**，工具栏重构后该属性已移除 | 改用 `ComposerAddAttachment` 的可访问名「添加附件」——`TooltipIconButton` 会把 tooltip 镜像为 `sr-only` 文本，可被 `getByRole('button',{name})` 解析 |
| `PW-MODEL-01` | `textarea[placeholder='输入"/"快速引用技能及指令']` | debug 面板已改为 `@assistant-ui` 的 `Thread`，输入元素类型不再是 textarea；`agent.debug.placeholder` 文案键虽仍存在但**已无任何代码引用** | 新增 `AgentPage.debugComposer()`，统一替换 **5 处**同类失效定位 |
| `PW-MODEL-02` | `getByRole('heading',{name:'知识库'})` | `KnowledgeBaseConfiguration.tsx` 渲染的标题不是 `role=heading`（无 `h1`/`h2`），该 role 在前端产物中不存在 | 改为断言互斥双态：创建工具栏可见 / 「未配置向量模型」提示可见 |
| `PW-AUTH-01` | `getByText('智能体开发')` | `智能体开发` 在 `SideNavigation.tsx` 中是 `isSection: true` 项，被 `accessibleMenuItems` 的 `!route.isSection` 过滤，**永不上屏** | 改用导航项「工作台」——`hideHomePage=true` 时的默认落地页，最稳定 |
| `PW-UI-01` | `getByText(/简体中文/).last()` | 语言选项渲染在**头像菜单 → 语言设置 → 二级子菜单**中（`avatarDropdown.tsx` 用 `children` 渲染），直接 click 因不可见超时 | 新增 `AuthPage.switchLanguageTo()`，先 hover 展开子菜单再选择 |
| `PW-CHAT-02`、`PW-KB-LOCAL-01` | 同上两类 | 与 `PW-MEDIA-STT-01`、`PW-MODEL-02` 同源 | 同步收敛到 page object 方法 |

> **工程改进**：定位器统一收敛进 page object（`ChatPage.composerText()`、`AgentPage.debugComposer()`、`AuthPage.switchLanguageTo()`），后续 UI 改版只需改一处，不必逐条用例修改。

---

## 三、断言与脚手架（8 条）

### `API-AUTO-DDE7582FFE405D54` — Agent 批量命名 `check_name` 契约

- **原失败**：`assert 1 >= 2`。用例在同一租户内创建两个同名 Agent 后，期望 `len(conflict_agents) >= 2`
- **排查结论：用例前提不成立**。`update_agent_info_impl` 在创建时就调用 `check_agent_value_duplicate` + `generate_unique_agent_value`，自动追加数字后缀改名（`dup_name_1`），因此**租户内不可能存在两个同名草稿**，返回 1 条才是正确行为
- **修复**：改为断言自动改名契约——`existing_names` 中存在 `dup_name_1` 形式的后缀名，且 `conflict_agents == 1`

### `UT-FE-005` — locale 切换与 fallback

四处问题叠加：

| 问题 | 证据 |
| :--- | :--- |
| 硬编码 `/portal` 前缀 | 实现是 `/locales/${localePath}/common.json` + 运行时 `withBasePath`，用例却断言绝对路径 |
| 模块级缓存污染 | `i18n.tsx` 用 `commonMessageRequests` / `customMessageRequest` 单例记忆化，前序测试已填充，stub 的 `fetch` 永不被调用 |
| mock 缺 `ok` 字段 | `response.ok` 为 `undefined`，导致每次请求都落入异常分支 |
| 断言错对象 | 读 `resourcesCustom.en.common`，但 `common` 实际在 `resources.en.common`（`resourcesCustom` 只承载 `custom` overlay）；且加载失败路径下返回的载体从不填充 |

**修复**：`vi.resetModules()` + 重新 `import` 获取干净缓存；mock 补 `ok: true`；改读 `resources.en.common`；失败场景改为观察 i18n 实例（`hasResourceBundle` / `t()`）而非返回载体。

### `UT-FE-AUTO-190989439ADD3E0F` — 个人资料页 authProvider 区分展示

- `UserProfileComp` 直接调用 `useQuery`（oauthService 配置），测试裸 `render()` 缺 `QueryClientProvider` → **补 Provider 包装**
- 原断言用 getter 抛错证明「本地用户完全不读 `username`」，但实现是 `user?.username` 照常传参、由 `getUserDisplayName(provider, casUsername, fallback)` 内部按 `authProvider === "cas"` 决定是否采用。**读取本身合法，「不应采用」才是规则** → 改为断言渲染值不来自 `username`

### `UT-FE-AUTO-63334E6F5D10C7FD` — avatarDropdown / TopNavbar 用户区

- mock 了 14 个模块，唯独漏掉真正使用 TanStack Query 的 `useAccountMonitoring` → **补 `vi.mock`**（对齐 `tests/component/accountMenu.test.tsx` 的既有做法）
- **前置条件已消失**：#4058（10-12）把用户区从 `TopNavbar` 移到 `SideNavigation` rail，顶栏现在只剩监控入口、GitHub 链接、语言切换，**不再渲染任何身份文本** → 6 个顶栏断言改为守卫断言（顶栏不得出现 identity 文本），身份规则改由 `AvatarDropdown`（两个入口共同挂载的组件）验证

### `UT-FE-AUTO-877E165BC61D430D` — 标签定义/值编辑

- 原断言 `readFileSync(TagDefinitionManagementModal.tsx)` 后 grep 函数名。但 #4155 标签管理集中化后，`createDefinition` / `updateDefinitionStatus` / `moveDefinitionToTop` 已迁至 `TagDefinitionManagementPanel.tsx`（原 Modal 变成 50 行壳组件）
- **功能完全正常，只是断言绑死了文件路径** → 新增 `readComponentSource()` 支持候选文件列表，存在即读取拼接，避免下次重构再碎

### `REL-AUTO-80AA755E2436D269` — ES 统计异常时配额 fail-open

- `monkeypatch.setattr(quota_service, 'get_tenant_committed_source_bytes', ...)` 打在 `quota` 模块，但 `QuotaService.get_usage` 实际定义在 `usage.py:503`，调用的是**它自己模块导入的符号**，桩从未生效（真实账本读到 0，`assert 0 == 5242880`）
- **修复**：同时 patch `usage_service` 模块

### `NAV-MENU-D4-001` — 导航可见性

- `execution.yaml` **完全没有 `preparation` 段**（对照 `PW-UI-02` 有完整的 `families` / `anchors` / `special_assets` / `d4_groups` 四字段），运行器直接阻断
- **修复**：补齐 `preparation` 段

---

## 四、顺带修复的既有失败（2 个测试文件）

`sharedShellLayout.test.tsx` 与 `agentPublishAndSharePage.test.tsx` 的 `next/navigation` mock 只提供各自导入的 hook，但组件树经 `ClientLayout` 会调用 `useRouter`，vitest 在断言前就抛出缺失导出。

补齐后 `sharedShellLayout.test.tsx` 由 **10 failed → 10 passed**。

---

## 验证方法

### 1. 产品修复双向验证（复现缺陷 + 证明测试有效）

```bash
cd frontend

# 还原缺陷版，确认断言确有防护力
git stash push -- components/common/StandardModal.tsx
npx vitest run tests/component/standardModalEscape.test.tsx
# 预期：Tests  1 failed (1)      ← "closes on Escape" 在 1187ms 失败

git stash pop

# 恢复修复版
npx vitest run tests/component/standardModalEscape.test.tsx
# 预期：Tests  2 passed (2)
```

这一步的意义是排除「测试空转」：若还原缺陷后仍然通过，说明该断言无效。

### 2. 前端组件测试（实测 19 passed）

```bash
cd frontend
npx vitest run \
  tests/component/standardModalEscape.test.tsx \
  tests/component/createAgentModal.test.tsx \
  tests/component/sharedShellLayout.test.tsx
```

实测输出：

```text
 Test Files  3 passed (3)
      Tests  19 passed (19)
```

### 3. D1 前端用例本地实跑（实测 4 条全部 PASS）

> **前置条件（重要）**：测试运行器的 `pretest` 会把产品 React 软链过来，但 `run_cases.py` 直接调用 `vitest.mjs`，**不经过 npm script**，须手动执行一次。否则运行器用 React 18.2.0 加载产品 React 19.2.3 的代码，会看到 12/12 全失败的假象。

```bash
cd test-e2e/infra/automation/d1/frontend
NEXENT_REPO=/c/code/nexent node ensure-product-react.mjs

# 确认已对齐，预期输出 19.2.3
node -e "console.log(require('./node_modules/react/package.json').version)"
```

```bash
cd test-e2e
NEXENT_TEST_HOME=/c/code/nexent-test-suite \
python infra/tools/run_cases.py \
  UT-FE-005 \
  UT-FE-AUTO-877E165BC61D430D \
  UT-FE-AUTO-190989439ADD3E0F \
  UT-FE-AUTO-63334E6F5D10C7FD
```

实测输出：

```text
UT-FE-005: PASS
UT-FE-AUTO-877E165BC61D430D: PASS
UT-FE-AUTO-190989439ADD3E0F: PASS
UT-FE-AUTO-63334E6F5D10C7FD: PASS
```

单条证据位于 `$NEXENT_TEST_HOME/runs/repository-local/<run_id>/`，含 `junit.xml`（断言明细）、`status.json`、`step-1.log`。

### 4. 用例契约校验

```bash
cd test-e2e
python infra/tools/validate_execution.py
```

实测输出：

```text
Execution metadata valid: 704 cases, 702 implementations
```

### 5. 浏览器手动复现（最直观）

1. 登录后进入 `/zh/agents`
2. 点击「新建」打开「创建智能体」对话框
3. 按 `Esc`

**修复前**：对话框纹丝不动。**修复后**：对话框关闭，焦点返回触发按钮。

---

## 五、版权头补全

`copyright-check` 对 PR 中**新增或修改**的每个源文件运行，不限于本分支创建的文件。因此一个历史上无头的老文件，只要本 PR 动过它，就会变成失败项。

本 PR 触及 20 个源文件，其中 13 个缺头：

| 类型 | 文件 |
| :--- | :--- |
| **本分支新增**（2 个） | `frontend/tests/component/standardModalEscape.test.tsx`、`frontend/tests/utils/renderWithProviders.tsx` |
| **基线本就缺头，本次被改动**（12 个） | `frontend/components/common/StandardModal.tsx`、`frontend/tests/component/agentPublishAndSharePage.test.tsx`、`test-e2e/cases/` 下 8 个用例脚本、`test-e2e/infra/automation/d4/pages/` 下 2 个 page object |

使用官方脚本批量修复：

```bash
python scripts/check_copyright.py --fix <files...>
```

一个例外单独手工处理：`UT-FE-AUTO-877E165BC61D430D/test.test.tsx` 首行是 `// @vitest-environment jsdom` 指令，必须留在文件头部注释块中，因此版权头放在它之前：

```ts
// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

// @vitest-environment jsdom
```

**验证**：按 CI 完全一致的 `git diff --name-only --diff-filter=ACMR` 收集文件后检查，23 个目标文件全部合规。

```bash
$ python scripts/check_copyright.py $(cat changed_files.txt)
Copyright header check (provided file list): 23 target file(s)
OK: all target files carry the required copyright header.
```

---

## 六、与 develop 的合并（#4176 / #4175 / #4178）

合并 `origin/develop`（`33e994eac`）时产生 3 处重叠，已全部解决。

值得注意：**#4178 `test(e2e): repair October 22 agent test assets` 也修了同一批定位器**，思路一致但落点不同：

| 文件 | #4178 的做法 | 本 PR 的做法 | 最终采用 |
| :--- | :--- | :--- | :--- |
| `chat.page.ts` | 新增 `composerInput()` + 通用 `composerText()`（同时处理 textarea 和 contenteditable） | 新增 `composerText()` 读 `innerText` + `expectComposerText()` 轮询 | **两边都保留**：`composerInput()` / `composerText()` 用 #4178 的通用实现，本 PR 只保留 `expectComposerText()` |
| `agent.page.ts` | `getByRole("textbox", { name: "对话输入" })` | `debugComposer()` 用 `[data-workbench-composer], .aui-lexical-input` 锚点 | **本 PR 方案** |
| `PW-CHAT-02` | `chat.composerInput()` | 内联 `page.locator(...)` | **#4178 方案**（更简洁） |

`agent.page.ts` 选择锚点而非 `getByRole` 的原因：`@assistant-ui/react-lexical` 的 `LexicalComposerInput` 把 `aria-label` 放在外层 `div.aui-lexical-editor` 上，而 `role=textbox` 在内层 contentEditable 上，按可访问名匹配存在落空风险；锚点直接命中元素。

合并后净变更为 21 个文件（原 22 个，`PW-CHAT-02` 的定位器部分已由 develop 侧修好）。合并方式为 **merge commit**，未使用 squash。

---


本节如实区分三类，避免将未验证项表述为已通过：

| 类别 | 涉及用例 | 状态 |
| :--- | :--- | :--- |
| **本地实测通过** | `UT-FE-005`、`UT-FE-AUTO-877E`、`UT-FE-AUTO-190989`、`UT-FE-AUTO-63334`、`standardModalEscape`、`createAgentModal`、`sharedShellLayout` | ✅ 有本地运行记录 |
| **静态校验通过** | 全部 704 cases / 702 implementations 契约合法 | ✅ `validate_execution.py` |
| **待 CI / 真实环境验证** | `PW-*`（7 条，需 Playwright + 部署环境）、`API-AUTO`、`REL-AUTO`（需完整后端依赖） | ⏳ 以 CI 结果为准 |

D4/D5 的 PW 与 API/REL 用例依赖浏览器服务与完整后端，本地环境缺 `smolagents` 等依赖链，**未能本地跑通**。这几条的修复只做到代码层面对齐，运行结果以 CI 为准。

---

## 已知遗留

1. `agentPublishAndSharePage.test.tsx` 仍有 5 个失败，原因为 locale 缺 `agent.version.versionName`。已用 `git stash` 还原 `StandardModal` 复跑验证，同样 5 个失败，确认为既有问题，与本 PR 无关。
2. `CTR-016` / `CTR-017` / `REL-02` 三条 BLOCKED 需运维按 `infra/config/ext-knowledge.example.yaml` 创建并挂载 mock，非代码侧可解。
3. `MON-D3-TRACE-NAME-001` 无 `junit.xml` 且 `reason` 仅为 `blocked`，无法归因，未作改动。
4. `PW-RESOURCE-01` 的「知识库」tab 为条件渲染（`!enableAidpKnowledge` 才显示），需按实际部署配置确定断言口径，未在本 PR 改动。
5. `closable={false}`（无右上角关闭图标）未改动，属产品体验决策。

---

## 附：提交清单

| 提交 | 说明 |
| :--- | :--- |
| `acf503bed` | `fix(modal): restore Escape dismissal in StandardModal` |
| `1f87dac3c` | `test(e2e): realign D4 page objects with the current composer and navigation` |
| `52ef34fa6` | `test(e2e): correct assertions that drifted from product behaviour` |
| `2e4f05fcc` | `test(frontend): supply useRouter in next/navigation mocks` |
| `8fd96ecfb` | `test(e2e): verify the D1 frontend cases against the current identity contract` |
| `08b5d4e69` | `chore(copyright): add the required header to files touched by this branch` |
| `73a81a059` | `chore(test): trim the explanatory comments added earlier on this branch` |
| `2da65b094` | `Merge remote-tracking branch 'origin/develop' into fix/v5-test-alignment` |