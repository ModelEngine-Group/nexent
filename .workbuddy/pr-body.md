## 修改说明

将 `fix/v5-test-alignment` 合入 `develop`，包含 5 个提交，涉及 22 个文件。产品代码仅修改 `StandardModal.tsx` 一处关闭行为，其余全部是测试与测试基础设施，未改动部署配置或 GitHub workflow。

修复对象为 10-22 批次 D4/D5 回归中 19 条未通过用例。逐条排查后分布如下，本 PR 修掉前两类共 16 条：

| 判定 | 条数 | 用例 |
|---|---|---|
| 产品问题 | 1 | PW-UI-02 |
| 测试侧问题 | 15 | 见下表 |
| 环境缺失（本 PR 不改） | 3 | CTR-016、CTR-017、REL-02 |

## 逐条用例修复明细

### 一、产品缺陷（1 条）

**PW-UI-02** —「键盘可访问性 Smoke：导航 → Dialog → 表单 → 关闭」

| 项 | 内容 |
|---|---|
| 原失败 | `expect(locator).toBeHidden()` 失败，59 次重试后 `role=dialog` 始终 visible |
| 根因 | `StandardModal.tsx:80` 硬编码 `keyboard={false}`，叠加 `closable={false}` 与 `mask.closable=false`，三条关闭路径全禁 |
| 关键证据 | `@rc-component/dialog/es/DialogWrap.js` 的 `keyboard` 默认即为 `true`，`onEsc` 中 `if (top && keyboard)` 才触发 `onClose`——是封装层主动覆盖了可用默认值 |
| 修复 | 改为 `keyboard={closeOnEscape}`，新 prop 默认 `true`，保留 opt-out 给真正会丢失大量输入的长表单 |
| 影响面评估 | 仅 2 个组件 3 处调用。`CreateAgentModal` 只有 1 个 `Form.Item`（displayName）+ 模板选择区，Escape 丢失成本低；`HighFidelityPromptEditModal` 留待单独评估 |
| 未改动 | `closable={false}`（无右上角 X）保留，属产品体验决策，需产品拍板是否恢复 |
| 验证 | 见「验证方法 §1」双向验证 |

### 二、定位器失效（7 条）

| 用例 | 原定位器 | 为什么失效 | 改成什么 |
|---|---|---|---|
| PW-MEDIA-STT-01 | `getByPlaceholder('发送消息...')` | `composer.tsx:703/715` 的 `placeholder` 被**显式置空字符串**，且输入框已从 `<textarea>` 改为 Lexical contenteditable，`inputValue()`/`toHaveValue()` 均不适用 | 新增 `ChatPage.composerText()` 读 `innerText` 并剔除零宽字符；`expectComposerText()` 做轮询断言 |
| PW-MEDIA-VLM-01 | `[data-composer-action-trigger]` | 全前端代码库**零匹配**，工具栏重构后该属性已移除 | 改用 `ComposerAddAttachment` 的可访问名「添加附件」（`TooltipIconButton` 会把 tooltip 输出为 `sr-only` 文本） |
| PW-MODEL-01 | `textarea[placeholder='输入"/"快速引用技能及指令']` | debug 面板已改为 `@assistant-ui` 的 `Thread`，输入元素类型不再是 textarea；`agent.debug.placeholder` 文案键虽保留但**已无任何代码引用** | 新增 `AgentPage.debugComposer()`，统一替换 5 处失效定位 |
| PW-MODEL-02 | `getByRole('heading', { name: '知识库' })` | `KnowledgeBaseConfiguration.tsx` 渲染的标题不是 `role=heading`（无 h1/h2） | 改为断言互斥双态：创建工具栏 / 「未配置向量模型」提示 |
| PW-AUTH-01 | `getByText('智能体开发')` | `智能体开发` 是 `SideNavigation` 的 `isSection: true` 项，被 `accessibleMenuItems` 的 `!route.isSection` 过滤，**永不上屏** | 改用导航项「工作台」（`hideHomePage=true` 时的默认落地页，最稳定） |
| PW-UI-01 | `getByText(/简体中文/).last()` | 语言选项在**头像菜单 → 语言设置 → 二级子菜单**里（`avatarDropdown.tsx` 用 `children` 渲染），直接点击会因不可见而超时 | 新增 `AuthPage.switchLanguageTo()`，先 hover 展开子菜单再选 |
| PW-CHAT-02 / PW-KB-LOCAL-01 | 同上两类 | 与 STT、MODEL-02 同源 | 同步收敛到 page object 方法 |

> 定位器统一收敛进 page object（`ChatPage.composerText()`、`AgentPage.debugComposer()`、`AuthPage.switchLanguageTo()`），避免下次改版又要逐条用例改。

### 三、断言与脚手架（8 条）

**API-AUTO-DDE7582FFE405D54** — Agent 批量命名 check_name 契约

原用例期望：同租户内创建两个同名 Agent 后 `len(conflict_agents) >= 2`，实际返回 1 条，`assert 1 >= 2` 失败。

排查结论：**用例前提不成立**。`update_agent_info_impl` 创建时就调用 `check_agent_value_duplicate` + `generate_unique_agent_value`，自动加数字后缀改名（`dup_name_1`），租户内**不可能存在两个同名草稿**。返回 1 条是正确行为。

修复：改为断言自动改名契约——`existing_names` 中存在 `dup_name_1` 这类后缀名，且 `conflict_agents == 1`。

**UT-FE-005** — locale 切换与 fallback

四处问题叠加：

| 问题 | 证据 |
|---|---|
| 硬编码 `/portal` 前缀 | 实现是 `/locales/${localePath}/common.json` + 运行时 `withBasePath`，测试却断言绝对路径 |
| 模块级缓存污染 | `i18n.tsx` 用 `commonMessageRequests` / `customMessageRequest` 单例记忆化，前序测试已填充，stub 的 fetch 永不被调用 |
| mock 缺 `ok` 字段 | `response.ok` 为 `undefined` 导致每次请求都走异常分支 |
| 断言错对象 | 读 `resourcesCustom.en.common`，但该字段只在 `resources.en.common`；且失败路径下返回的载体从不填充 |

修复：`vi.resetModules()` + 重新 import 拿干净缓存；mock 补 `ok: true`；改读 `resources.en.common`；失败场景改为观察 i18n 实例（`hasResourceBundle` / `t()`）而非返回载体。

**UT-FE-AUTO-190989439ADD3E0F** — 个人资料页 authProvider 区分展示

两处问题：

- `UserProfileComp` 直接调用 `useQuery`（oauthService 配置），测试裸 `render()` 缺 `QueryClientProvider` → 补 Provider 包装
- 原断言用 getter 抛错证明「本地用户完全不读 username」，但实现是 `user?.username` 照常传参、由 `getUserDisplayName(provider, casUsername, fallback)` 内部按 `authProvider === "cas"` 决定是否采用——**读取本身合法，不应采用才是规则** → 改为断言渲染值不来自 username

**UT-FE-AUTO-63334E6F5D10C7FD** — avatarDropdown / TopNavbar 用户区

两处问题：

- mock 了 14 个模块，唯独漏掉真正使用 TanStack Query 的 `useAccountMonitoring` → 补 `vi.mock`（对齐 `tests/component/accountMenu.test.tsx` 的既有做法）
- **前置条件已消失**：#4058（10-12）把用户区从 `TopNavbar` 移到 `SideNavigation` rail，顶栏只剩监控入口、GitHub 链接、语言切换，**不再渲染任何身份文本** → 6 个顶栏断言改为守卫断言（顶栏不得出现 identity 文本），身份规则改由 `AvatarDropdown`（两个入口共同挂载的组件）验证

**UT-FE-AUTO-877E165BC61D430D** — 标签定义/值编辑

原断言 `readFileSync(TagDefinitionManagementModal.tsx)` 后 grep 函数名，但 #4155 标签管理集中化后，`createDefinition` / `updateDefinitionStatus` / `moveDefinitionToTop` 已迁到 `TagDefinitionManagementPanel.tsx`（原 Modal 变成 50 行壳）。**功能完全正常，只是断言绑死了文件路径**。

修复：新增 `readComponentSource()` 支持候选文件列表，存在即读取拼接，避免下次重构再碎。

**REL-AUTO-80AA755E2436D269** — ES 统计异常时的配额 fail-open

`monkeypatch.setattr(quota_service, 'get_tenant_committed_source_bytes', ...)` 打在 `quota` 模块，但 `QuotaService.get_usage` 实际定义在 `usage.py:503`，调用的是**它自己模块导入的符号**，桩从未生效（真实账本读到 0，`assert 0 == 5242880`）。

修复：同时 patch `usage_service` 模块。

**NAV-MENU-D4-001** — 导航可见性

`execution.yaml` **完全没有 `preparation` 段**（对照 PW-UI-02 有完整的 `families` / `anchors` / `special_assets` / `d4_groups` 四字段），运行器直接阻断。已补齐。

### 四、顺带修复的既有失败（2 个测试文件）

`sharedShellLayout.test.tsx` 与 `agentPublishAndSharePage.test.tsx` 的 `next/navigation` mock 只提供各自导入的 hook，但组件树经 `ClientLayout` 会调用 `useRouter`，vitest 在断言前就抛缺失导出。

补齐后 `sharedShellLayout.test.tsx` 由 **10 failed → 10 passed**。

## 验证方法

### 1. 产品修复双向验证（30 秒，可截图）

```bash
cd frontend

# 还原缺陷版，确认断言有真实防护力
git stash push -- components/common/StandardModal.tsx
npx vitest run tests/component/standardModalEscape.test.tsx
# 预期：Tests  1 failed (1)   ← "closes on Escape" 在 1187ms 失败

git stash pop

# 恢复修复版
npx vitest run tests/component/standardModalEscape.test.tsx
# 预期：Tests  2 passed (2)
```

这一步的意义是排除「测试空转」——如果还原缺陷后仍通过，说明断言无效。

### 2. 前端组件测试（已实测 19 passed）

```bash
cd frontend
npx vitest run \
  tests/component/standardModalEscape.test.tsx \
  tests/component/createAgentModal.test.tsx \
  tests/component/sharedShellLayout.test.tsx
```

实测输出：

```
 Test Files  3 passed (3)
      Tests  19 passed (19)
```

其中 `sharedShellLayout` 的 10 个用例是本次一并修好的既有失败。

### 3. D1 前端用例本地实跑（已实测 4 条全 PASS）

**前置条件（关键）**：测试运行器的 `pretest` 会把产品 React 软链过来，但 `run_cases.py` 直接调 `vitest.mjs`，**不经过 npm script**，须手动执行一次。否则运行器用 React 18.2.0 加载产品 React 19.2.3 的代码，会看到 12/12 全失败的假象。

```bash
cd test-e2e/infra/automation/d1/frontend
NEXENT_REPO=/c/code/nexent node ensure-product-react.mjs

# 确认已对齐，预期输出 19.2.3
node -e "console.log(require('./node_modules/react/package.json').version)"
```

然后运行：

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

```
UT-FE-005: PASS
UT-FE-AUTO-877E165BC61D430D: PASS
UT-FE-AUTO-190989439ADD3E0F: PASS
UT-FE-AUTO-63334E6F5D10C7FD: PASS
```

单条证据在 `$NEXENT_TEST_HOME/runs/repository-local/<run_id>/`，含 `junit.xml`（断言明细）、`status.json`、`step-1.log`。

### 4. 用例契约校验

```bash
cd test-e2e
python infra/tools/validate_execution.py
```

实测输出：

```
Execution metadata valid: 704 cases, 702 implementations
```

### 5. 浏览器手动复现产品缺陷（最直观，适合截图）

1. 登录后进入 `/zh/agents`
2. 点击「新建」打开「创建智能体」对话框
3. 按 `Esc`

修复前：对话框纹丝不动。修复后：对话框关闭，焦点返回「新建」按钮。

## 验证状态说明

本 PR 分三类如实标注，不混为一谈：

| 类别 | 用例 | 状态 |
|---|---|---|
| **本地实测通过** | UT-FE-005、UT-FE-AUTO-877E、UT-FE-AUTO-190989、UT-FE-AUTO-63334、standardModalEscape、createAgentModal、sharedShellLayout | 已有本地运行记录 |
| **静态校验通过** | 全部 704 cases / 702 implementations 契约合法 | `validate_execution.py` |
| **需 CI / 真实环境** | PW-*（7 条，需 Playwright + 部署环境）、API-AUTO、REL-AUTO（需后端依赖完整） | 本地无法拉起，以 CI 为准 |

D4/D5 的 PW 与 API/REL 用例依赖浏览器服务与完整后端，本地环境缺 `smolagents` 等依赖链，因此未在本地跑通——**这几条的修复只做到代码层面对齐，运行结果以 CI 为准**。

## 已知遗留

- `agentPublishAndSharePage.test.tsx` 仍有 5 个失败，原因为 locale 缺 `agent.version.versionName`。已用 `git stash` 还原 `StandardModal` 复跑，同样 5 个失败，确认为既有问题，与本 PR 无关。
- `CTR-016` / `CTR-017` / `REL-02` 三条 BLOCKED 需运维按 `infra/config/ext-knowledge.example.yaml` 创建并挂载 mock，非代码侧可解。
- `MON-D3-TRACE-NAME-001` 无 `junit.xml` 且 `reason` 仅为 `blocked`，无法归因，未作改动。
- PW-RESOURCE-01 的「知识库」tab 是条件渲染（`!enableAidpKnowledge` 才显示），需按实际部署配置确定断言口径，未在本 PR 改动。
