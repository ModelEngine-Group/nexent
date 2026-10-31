# 武兆福 19 条问题归因（按表格原序）

数据源：飞书 `Nexent_V5_测试用例责任田.xlsx` → 工作表 `10-22未通过用例`，批次 `2026-10-22T021246.565216-0000-f4758b3d`
交叉验证：`C:\code\nexent`（develop `7dd0e0350`）、`test-e2e` 用例定义、`latest-batch.zip` 内 junit/failure.json

---

## 1｜CTR-016｜模型管理｜D3｜依赖阻断

**问题描述**：远程图片 JSON base64/stream 代理、URL解码、上游失败｜核心流程。报 `required test asset is not READY: mock.ext-knowledge`，`config/ext-knowledge.yaml` 缺失。

**判定**：**环境准备缺失**（测试基础设施，非用例设计错误、非业务缺陷）

**判断依据**：
- `cases/CTR-016/execution.yaml` 声明 `required_mock_services: [http-fixture]`
- `infra/tools/validate_execution.py:27` 的 `LOGICAL_MOCK_SERVICES` 把 `http-fixture` 列入合法值，且注释明确 "resolves the **ext-served** subset (knowledge-provider / http-fixture / model-provider) **against the machine-local ext-knowledge configuration at attach time**"
- `infra/tools/ext_attach.py:138-143`：`config/ext-knowledge.yaml` 不存在即抛 `AttachError`
- 用例声明本身合规（http-fixture 是合法 ID），失败原因纯粹是测试机未按 `infra/config/ext-knowledge.example.yaml` 创建配置并挂载 mock

---

## 2｜CTR-017｜模型管理｜D3｜依赖阻断

**问题描述**：同一功能的「外部依赖异常与超时」场景，同样报 `config/ext-knowledge.yaml` 缺失。

**判定**：**环境准备缺失**（同 CTR-016）

**判断依据**：`execution.yaml` 同样声明 `[http-fixture]`；阻断点相同（`ext_attach.py` 的 load_config）。两个用例是同一 mock 依赖的两个场景分支，环境修好后应同时解除。

---

## 3｜PW-MEDIA-STT-01｜模型管理｜D4｜超时

**问题描述**：真实 STT 配置→Chat 语音输入→转写→发送。卡在 `getByPlaceholder('发送消息...')`，超时 30s。

**判定**：**用例问题（定位器失效）**

**判断依据（决定性）**：
- `app/[locale]/newchat/assistant-ui/composer.tsx:703` 与 `:715` 两处 Composer 输入框的 `placeholder` 都被**显式设为空字符串** `placeholder=""`
- 也就是说页面上**任何时刻都不存在** `placeholder="发送消息..."` 的输入框
- locale 中相关的只有 `chatInput.sendMessageTo`（「给 {productName} 发送消息」）和 `chat.composer.inputLabel`（「对话输入」）
- 可用稳定标识是 `[data-workbench-composer]` 或 `aria-label="对话输入"`，用例应改用这些

---

## 4｜PW-MEDIA-VLM-01｜模型管理｜D4｜超时

**问题描述**：真实 VLM→图片附件→多模态回答。卡在 `locator('[data-composer-action-trigger]')`，超时 30s。

**判定**：**用例问题（定位器不存在）**

**判断依据（决定性）**：
- 全前端代码库 `grep -rn "data-composer-action-trigger"` **零匹配**
- 该 data 属性在当前代码中根本不存在（Composer 重构后改名或移除）
- 这是纯选择器失效，与产品行为无关

---

## 5｜PW-MODEL-01｜模型管理｜D4｜失败

**问题描述**：模型 V2 从 Provider 导入/自定义接入→真实连通性→保存→Agent 使用。卡在 `[data-testid='agent-debug-panel'] textarea[placeholder='输入"/"快速引用技能及指令']:visible, textarea[placeholder*="输入测试问题"]:visible`，超时 120s。

**判定**：**用例问题（定位器已随组件库迁移失效）**

**判断依据（决定性）**：
- `agent-debug-panel` testid **存在**（`agent-debug.tsx:210`）
- 但面板输入区已改为 `@assistant-ui` 的 `Thread` 组件（`agent-debug.tsx:98` 起），底部是 `<Thread ... composerTools={...}>`，**不再渲染原生 `textarea`**
- `agent.debug.placeholder`（「输入测试问题...」）这个 locale key **仍存在但全代码库零引用**——说明带 placeholder 的 textarea 已被移除
- 用例的两个候选定位器都指向 `textarea[placeholder=...]`，**元素类型层面就不匹配**，所以 OR 双候选也无法命中
- 由于失败发生在 UI 定位而非接口行为，**无法据此判定业务缺陷**；修正定位器后必须复跑才能确认模型保存→Agent 使用的业务链路是否正常

---

## 6｜PW-MODEL-02｜模型管理｜D4｜失败

**问题描述**：真实 Embedding/Multi-Embedding→Local KB 索引→检索。卡在 `getByRole('heading', {name:'知识库'})`。

**判定**：**用例问题（断言语义层不合理）**

**判断依据**：
- `app/[locale]/knowledges/KnowledgeBaseConfiguration.tsx` 中**没有任何 `<h1>/<h2>/<h3>` 或 `Typography.Title` 或 `role="heading"`**
- 知识库页标题不以 heading 语义节点呈现，`getByRole('heading')` 天然无法命中
- 用例用 ARIA role 断言了一个不存在语义层级的节点，属断言方式设计错误（而非页面缺少标题）

---

## 7｜REL-02｜模型管理｜D5｜依赖阻断

**问题描述**：Provider 429/5xx/timeout 降级。同样报 `config/ext-knowledge.yaml` 缺失。

**判定**：**环境准备缺失**

**判断依据**：`execution.yaml` 声明 `required_mock_services: [model-provider]`，`model-provider` 同属 `validate_execution.py:27` 的 ext-served 子集，挂载同样依赖 `ext-knowledge.yaml`。与 CTR-016/017 同源。

---

## 8｜UT-FE-005｜系统管理整体｜D1｜失败

**问题描述**：locale 切路由保留、关键文案 fallback。vitest 报 `expected 'test.fallback' to be 'English fallback'`（6 例中 1 失败）。

**判定**：**用例问题（断言预期值硬编码错误）**

**判断依据**：
- 用例断言 `expect(request.mock.calls.map(url => url)).toEqual(['/portal/locales/en/common.json', '/portal/locales/zh/custom.json', '/portal/locales/en/custom.json'])`
- 但实现 `app/[locale]/i18n.tsx:106` 实际请求的是 `` `/locales/${localePath}/common.json` ``——**没有 `/portal` 前缀**
- `/portal` 是构建期 basePath（由 next.config/环境注入），不应硬编码进单测断言
- mock 的 fetch 只对 `url.endsWith('common.json')` 生效，前缀不匹配导致 mock 未命中 → fallback 断言连带失败

---

## 9｜UT-FE-AUTO-190989439ADD3E0F｜系统管理整体｜D1｜失败

**问题描述**：个人资料账户信息区按 authProvider 区分 Username/Email 展示与 CAS 空用户名回退邮箱。6 例**全部失败**。

**判定**：**用例问题（测试脚手架缺失 Provider 包装）**

**判断依据（决定性）**：
- 失败信息 6/6 全为 `No QueryClient set, use QueryClientProvider to set one`
- 这是 `@tanstack/react-query` 在缺少 Provider 时的标准报错
- 测试用例渲染组件时未包 `QueryClientProvider`，属于测试代码自身的搭建缺失
- 与产品行为完全无关（组件在生产环境由根 Provider 提供 context）

---

## 10｜UT-FE-AUTO-63334E6F5D10C7FD｜系统管理整体｜D1｜失败

**问题描述**：avatarDropdown 与 TopNavbar 用户区 username 优先、回退 email、两者皆空显示 '-'。12 例中 **11 例失败**。

**判定**：**用例问题（同一类脚手架缺失）**

**判断依据（决定性依赖链）**：
- 失败信息仍为 `No QueryClient set`
- 用例 `test.test.tsx:141` 等直接 `render(<TopNavbar />)`、`:183` `render(<AvatarDropdown />)`，无任何 Provider 包装
- 依赖链实测确认：`components/auth/avatarDropdown.tsx:76` 调用 `useAccountMonitoring()` → `hooks/useAccountMonitoring.ts:5` `import { useQuery } from "@tanstack/react-query"` → `:16` 实际调用 `useQuery`
- 因此渲染 `AvatarDropdown` 必然缺 QueryClient
- 与第 9 条同根因，可**一次性统一修复**（提供 `renderWithProviders` 工具）

---

## 11｜UT-FE-AUTO-877E165BC61D430D｜系统管理整体｜D1｜失败

**问题描述**：标签定义/值编辑、启停与置顶，资源分配单/多选、容量上限及 409 冲突提示。1 例失败：`expected '// Copyright (c) 2025-2026 Huawei Tec…' to contain 'createDefinition'`。

**判定**：**用例问题（白盒断言绑定实现细节）**

**判断依据（决定性）**：
- 用例直接读源码做字符串匹配：`readFileSync('.../components/tag/TagDefinitionManagementModal.tsx')` 断言 `toContain('createDefinition')`
- 实测该文件现存 **50 行 / 1196 字节**，`grep -c createDefinition` = **0**——它已被 #4155（标签管理集中化）重构为壳组件，只渲染 `<TagDefinitionManagementPanel>`
- 而 `createDefinition` / `updateDefinitionStatus` / `moveDefinitionToTop` **全部在 `TagDefinitionManagementPanel.tsx`**（实测 5 处命中），功能完全正常
- 失败信息里 `expected '// Copyright...'` 说明断言读到的是文件首行版权头，进一步证明该文件已无业务代码
- 这是典型的「断言绑死文件名+函数名」的反模式：任何合理重构都会误报

---

## 12｜API-AUTO-DDE7582FFE405D54｜系统管理整体｜D2｜失败

**问题描述**：Agent 批量命名 check_name/regenerate_name 契约。失败 `AssertionError: assert 1 >= 2`，`conflict_agents` 只返回 1 条。

**判定**：**用例问题（租户隔离语义理解偏差）**

**判断依据（决定性）**：
- 用例在**两个不同租户**（tenant_a / tenant_b）各创建一个同名 Agent，随后在当前租户上下文调 `check_name`，期望返回 `len(conflict_agents) >= 2`
- 实现 `backend/management/services/agent/service.py:239` 的 `check_agent_name_conflict_batch_impl`：
  - docstring 明确无歧义：「Batch check whether agent name/display_name conflicts exist **in the tenant**」
  - 数据源是 `query_all_agent_info_by_tenant_id(tenant_id)`——**只查当前租户**
- **跨租户同名不冲突是租户隔离的正确设计**，不是缺陷。用例把跨租户场景误当成本租户内冲突
- 需要产品确认：Agent 名称唯一性若确为租户内，则用例需删除跨租户断言；若产品要求全局唯一，才转为业务缺陷

---

## 13｜MON-D3-TRACE-NAME-001｜系统管理整体｜D3｜阻断

**问题描述**：Consistent main Agent trace name through real Langfuse ingestion。`结果=阻断`，`失败原因=blocked`，无任何证据文件。

**判定**：**无法判定（证据缺失）**

**判断依据**：
- 表格 `文本证据` 列为空，`运行器完整原因` 仅 "blocked" 一个词
- `latest-batch.zip` 内 `cases/MON-D3-TRACE-NAME-001/` **无 junit.xml**（实测 KeyError）
- 表格备注写「原始结果未登记 Local evidence（未执行／阻断项）；见该批次 checkpoints/results.jsonl」
- 阻断原因未落到结构化字段，无法区分是用例问题还是业务问题，需补录后才能归因

---

## 14｜NAV-MENU-D4-001｜系统管理整体｜D4｜阻断

**问题描述**：Preserve functional navigation while hiding inert controls。报 `Missing per-case preparation declaration`。

**判定**：**用例问题（用例元数据声明缺失）**

**判断依据（决定性）**：
- `cases/NAV-MENU-D4-001/execution.yaml` 实际内容只有 `schema_version` / `case_id` / `implementations` / `timeout_seconds` / `acceptance_bindings`——**完全没有 `preparation` 段**
- 对照同批次正常用例 `cases/PW-UI-02/execution.yaml`，含完整四字段：`families: []` / `anchors: true` / `special_assets: false` / `d4_groups: [chat]`
- 运行器要求每条 D4 用例显式声明 preparation，缺段即阻断。属于用例文件未按 schema 补齐，非产品问题

---

## 15｜PW-AUTH-01｜系统管理整体｜D4｜失败

**问题描述**：本地登录→受保护路由→刷新/多 Tab→退出。卡在 `getByText('智能体开发', {exact:true})`。

**判定**：**用例问题（导航结构已变更）**

**判断依据（决定性）**：
- `components/navigation/SideNavigation.tsx:322-334` 的 `accessibleMenuItems` 过滤条件包含 `!route.isSection`
- 而 `/agent-dev`（`labelKey: "sidebar.agentDev"` = 「智能体开发」）在第 96-99 行被标记 `isSection: true`
- 结论：**该文本永远不会渲染为可点击菜单项**（section 仅作分组标题，且被过滤掉不上屏）
- 文案仍保留在 `public/locales/zh/common.json:2276`，但已无渲染出口
- 这是 #4095 导航重构后的必然结果，用例未同步

---

## 16｜PW-RESOURCE-01｜系统管理整体｜D4｜失败

**问题描述**：SU 创建租户→可选管理员→选择租户→资源 Tab 加载。卡在 `getByRole('tab', {name:'知识库'})`。

**判定**：**用例问题（未适配条件渲染）**

**判断依据（决定性）**：
- `app/[locale]/resource-manage/components/UserManageComp.tsx:1373-1385` 知识库 tab 是**条件渲染**：
  ```
  // When AIDP knowledge is enabled, the knowledge tab is managed
  // via the unified `/knowledges` entry and must not appear here.
  ...(!enableAidpKnowledge ? [{ key: "knowledge", label: t("tenantResources.tabs.knowledge"), ... }] : [])
  ```
- 代码注释明确：AIDP 知识库启用时该 tab **按设计隐藏**
- 若测试环境 `enableAidpKnowledge = true`，tab 不渲染是**正确行为**
- 用例既未在 `execution.yaml` 声明该环境开关前置，也未做双分支断言（tab 或 /knowledges 入口二选一）

---

## 17｜PW-UI-01｜系统管理整体｜D4｜超时

**问题描述**：核心路由导航→zh/en 切换→页面状态不串。卡在 `getByText(/简体中文|中文/).last()`，超时 30s。

**判定**：**用例问题（语言切换入口层级已变）**

**判断依据**：
- 「简体中文」文案确实存在：`const/constants.ts:2` `languageOptions = [{ label: "简体中文", value: "zh" }, ...]`
- 但它渲染在**头像下拉菜单 → 「语言设置」项 → hover/click 展开的二级子菜单**里（`components/auth/avatarDropdown.tsx:201-224`，`children: languageOptions.map(...)`）
- 用例直接 `getByText(/简体中文|中文/).last().click()`，**未先展开两级菜单**，元素在 DOM 中不可见故超时
- 属步骤未适配 #4095 的账户菜单改版

---

## 18｜PW-UI-02｜系统管理整体｜D4｜失败

**问题描述**：键盘可访问性 Smoke：导航→Dialog→表单→关闭。断言 `getByRole('dialog', {name:'创建智能体'})` 应 hidden，实际 visible（3 次 + 59 次重试均 visible）。

**判定**：**业务问题（可访问性实现缺陷）**

**判断依据（决定性，唯一确定的业务缺陷）**：
- `components/common/StandardModal.tsx:80` 显式设置 **`keyboard={false}`**，禁用 ESC 关闭
- 同处还有 `closable={false}`（:79）与 `mask={{ closable: false }}`（:81）——**ESC、右上关闭按钮、点遮罩三条关闭路径全部禁用**，只剩底部自定义按钮
- 用例步骤 4「按 Escape 关闭，焦点返回触发元素」符合 **WCAG 2.1.2 (No Keyboard Trap)** 与 **ARIA APG Dialog (Modal) Pattern**（原文要求 "Escape: Closes the dialog"）
- 失败证据显示 59 次重试中 dialog 始终 `visible`，与 `keyboard={false}` 的代码事实完全吻合
- 注意：`keyboard={false}` 可能是**为防表单误触关闭而有意设置**；若产品确认为有意设计，则需在 a11y 文档中记录例外理由，并同步修改 PW-UI-02 步骤 4（改为断言自定义关闭按钮 + 焦点回归）。**无论哪种结论都必须有一次明确裁决**，当前状态是"代码与用例各行其是"

---

## 19｜REL-AUTO-80AA755E2436D269｜系统管理整体｜D5｜失败

**问题描述**：ES 向量库统计异常时个人/租户配额检查与用量展示 fail-open（源文件账本唯一口径）。失败 `assert 0 == 5242880`（`usage['total_bytes']` 为 0，期望 5MB）。

**判定**：**用例问题（monkeypatch 打桩目标模块错位）**

**判断依据（决定性）**：
- 用例打桩：`monkeypatch.setattr(quota_service, 'get_tenant_committed_source_bytes', tenant_committed)`，其中 `quota_service` = `management.services.knowledge_base.quota`
- 但 `get_usage` **实际定义在另一个模块**：`management/services/knowledge_base/usage.py:503`
- 且 `usage.py:44` 自己 `from ... import get_tenant_committed_source_bytes`，在 `:567` 直接调用**本模块命名空间**的符号
- 因此把 `quota.py` 里的同名引用替换掉，**对 `usage.py` 的调用无任何影响**——桩完全未生效，走真实实现读到 0
- 业务实现正确（读的是源文件账本），修法是把 monkeypatch 目标改为 `management.services.knowledge_base.usage`

---

# 整体归因小结

| 判定 | 条数 | 用例 |
|---|---|---|
| **用例问题** | **11** | PW-MEDIA-STT-01、PW-MEDIA-VLM-01、PW-MODEL-01、PW-MODEL-02、UT-FE-005、UT-FE-AUTO-190989、UT-FE-AUTO-63334、UT-FE-AUTO-877E、API-AUTO-DDE75、NAV-MENU-D4-001、PW-AUTH-01、PW-RESOURCE-01、PW-UI-01、REL-AUTO-80AA |
| **业务问题** | **1** | PW-UI-02 |
| **环境缺失** | **3** | CTR-016、CTR-017、REL-02 |
| **无法判定** | **1** | MON-D3-TRACE-NAME-001 |

> 精确计数：用例问题 14 条（含 NAV-MENU 元数据缺失）、业务问题 1 条、环境缺失 3 条、无法判定 1 条，合计 19。

**用例问题再细分**：

| 子类型 | 条数 | 说明 |
|---|---|---|
| 定位器失效 | 5 | PW-MEDIA-STT-01（placeholder 被置空）、PW-MEDIA-VLM-01（属性不存在）、PW-MODEL-01（textarea 改 Lexical）、PW-AUTH-01（isSection 不上屏）、PW-UI-01（二级菜单未展开） |
| 断言方式不合理 | 2 | PW-MODEL-02（不存在的 heading role）、UT-FE-AUTO-877E（绑死源文件函数名） |
| 测试脚手架缺失 | 2 | UT-FE-AUTO-190989、UT-FE-AUTO-63334（缺 QueryClientProvider） |
| 断言预期值错误 | 2 | UT-FE-005（硬编码 /portal）、PW-RESOURCE-01（未适配条件渲染） |
| 打桩目标错位 | 1 | REL-AUTO-80AA（打在 quota.py，实现在 usage.py） |
| 语义理解偏差 | 1 | API-AUTO-DDE75（跨租户误判为本租户冲突） |
| 元数据缺失 | 1 | NAV-MENU-D4-001（无 preparation 段） |

## 系统性归因（比单条结论更重要）

1. **Composer 组件库迁移是最大震源**：`composer.tsx:703/715` 的 `placeholder=""` + 改为 Lexical 编辑器 + `data-composer-action-trigger` 移除，一次性打掉 3 条 PW 用例（STT/VLM/MODEL-01）。而代码里明明留了 `data-workbench-composer` 和 `aria-label="对话输入"` 两个稳定锚点没被用例采用。
2. **导航/菜单改版（#4095）未同步 page object**：`智能体开发`（isSection 不上屏）、`简体中文`（下沉二级菜单）2 条。
3. **白盒断言与技术栈耦合**：grep 源码函数名、断言具体模块属性名——重构即碎，误报率高。
4. **测试脚手架无统一规范**：2 条 react-query 用例裸 render，说明缺少团队级 `renderWithProviders`。
5. **条件渲染环境开关未参数化**：`enableAidpKnowledge`、`hideHomePage` 这类开关已进入产品，用例元数据尚无对应声明机制。

**风险提示**：19 条中 14 条卡在测试侧（定位器/脚手架/环境），意味着**本轮批次实际只触达了 1 条真实业务缺陷**。这既可能反映质量改善，也可能是**测试覆盖在 UI 层被大面积架空**——大量用例根本没走到业务逻辑就失败了。后者的风险更值得警惕。

---

# 优先处理建议

## P0 — 本周内（止血 + 唯一业务缺陷裁决）

1. **裁决 `StandardModal` 的 `keyboard={false}`**（PW-UI-02，唯一业务缺陷）
   - 若确认为缺陷：改为支持 ESC 关闭（保留表单类场景的可配置例外）
   - 若确认为有意设计：在 a11y 规范文档记录例外，同步修改 PW-UI-02 步骤 4 为「点击自定义关闭按钮 + 焦点回归」
   - **关键**：当前状态是代码与用例各说各话，必须先给出结论，否则这条永远挂着

2. **建立 `renderWithProviders` 测试工具**（解决 UT-FE-AUTO-190989 + 63334，2 条）
   - 路径建议 `frontend/tests/utils/renderWithProviders.tsx`，包装 `QueryClientProvider` + `I18nProvider` + `AuthorizationProvider`
   - 加 ESLint/CI 约束：组件测试禁止裸 `render()`
   - 收益：2 条立即转绿 + 预防后续所有同类问题

3. **补齐 `ext-knowledge.yaml`**（解决 CTR-016/017/REL-02，3 条）
   - 按 `infra/config/ext-knowledge.example.yaml` 在 `<test-home>/config/` 创建并挂载 mock compose
   - 建议在 `local_preflight.py` 增加前置校验：选中用例含 ext-served 依赖但配置缺失时，**在批次开始前**给出明确提示，而不是逐条阻断

## P1 — 两周内（消除批量误报）

4. **Composer 定位器统一改造**（PW-MEDIA-STT-01、PW-MEDIA-VLM-01、PW-MODEL-01，3 条）
   - 弃用 placeholder 定位，改用代码已提供的稳定锚点：`[data-workbench-composer]`、`aria-label="对话输入"`
   - `data-composer-action-trigger` 需与前端约定：要么恢复该属性，要么提供新的 action trigger 锚点（当前无任何替代）
   - PW-MODEL-01 的 debug 面板输入需改为基于 `agent-debug-panel` 内部的 contenteditable/Lexical 定位

5. **page object 与前端契约的 CI 守护**
   - 把导航项、Composer、Tab、语言切换等关键选择器收敛到 `page-objects/selectors.ts`
   - CI 加一条快速 smoke：启动前端后校验关键选择器存在，任一失效则前端 PR 红灯
   - 覆盖 PW-AUTH-01、PW-UI-01、PW-RESOURCE-01

6. **UT-FE-AUTO-877E 断言改造**（源码字符串 → 行为）
   - 改为渲染组件后断言「定义列表可见 / 能触发创建 / 状态切换有效」
   - 过渡方案：至少把 grep 目标改为 `TagDefinitionManagementPanel.tsx`（治标）
   - 同时清理这类「grep 源码」用例清单，逐个改造

7. **REL-AUTO-80AA 修正打桩目标**
   - `monkeypatch.setattr` 目标改为 `management.services.knowledge_base.usage`
   - 建议团队约定：打桩必须打在**实现所在模块**，而非导入方模块

## P2 — 一个月内（机制建设）

8. **UT-FE-005 修正 basePath 断言**
   - 去掉硬编码 `/portal`，改为 `url.endsWith('/locales/en/common.json')` 或引用构建期 basePath 常量

9. **PW-RESOURCE-01 环境参数化**
   - 在 `execution.yaml` 声明 `enableAidpKnowledge` 取值，或断言改为「知识库入口在 tab 或 /knowledges，二者其一」

10. **NAV-MENU-D4-001 补齐 `preparation` 段**
    - 按 `PW-UI-02` 的模板补 `families/anchors/special_assets/d4_groups`
    - 建议在 `validate_execution.py` 把该检查从运行期提前到提交期（pre-commit 或 CI），避免批次跑到一半才阻断

11. **API-AUTO-DDE75 需求澄清**
    - 请产品明确 Agent 名称唯一性是**租户内**还是**全局**
    - 当前实现为租户内且有 docstring 佐证；若确认租户内 → 删用例跨租户断言；若要求全局 → 转业务缺陷改实现

12. **MON-D3-TRACE-NAME-001 补证据链**
    - 把阻断原因写入 `失败原因` / `运行器完整原因` 结构化字段，禁止只写 "blocked"
    - 建议运行器侧增加约束：BLOCKED 状态必须带 reason code
