# 武兆福 V5 测试问题归因分析（2026-10-22 批次）

## 数据来源

- 飞书文档：`Nexent_V5_测试用例责任田.xlsx`（https://dcnvjn24oieg.feishu.cn/wiki/PaeJwsoKOifiW8k0VhqcIN9Unzc）
- 主要工作表：`10-22未通过用例`（126 行，批次 `2026-10-22T021246`），19 条责任人为 @武兆福
- 佐证：`产品问题10-09`（4 条协同）、`责任田汇总`（模型管理 40 条 / 系统管理整体 124 条）
- 代码交叉验证：`C:\code\nexent`（develop `7dd0e0350`）+ `C:\code\nexent\test-e2e` + `latest-batch.zip` 实际 junit/failure.json

---

## 一、逐条判定（19 条）

### A 类：环境/依赖未就绪（3 条｜非用例设计错误，属环境准备缺失）

**1. CTR-016｜依赖阻断 (BLOCKED_BY_DEPENDENCY)**
- 描述：远程图片 JSON base64/stream 代理、URL解码、上游失败｜核心流程。报 `required test asset is not READY: mock.ext-knowledge`
- **判定：环境准备缺失**（介于用例与业务之间，归入测试基础设施）
- 依据：`cases/CTR-016/execution.yaml` 声明 `required_mock_services: [http-fixture]`，而 `validate_execution.py` 将 `http-fixture` 归入 **ext-served 子集**（与 knowledge-provider/model-provider 同级），挂载时必须解析 `<test-home>/config/ext-knowledge.yaml`。该文件缺失 → 阻断。用例声明本身**符合规范**（http-fixture 是合法逻辑服务 ID），不是用例写错，是**测试环境未按 README 完成 mock 挂载**

**2. CTR-017｜依赖阻断**：同 CTR-016，另一场景。判定同上。

**3. REL-02｜依赖阻断**：声明 `required_mock_services: [model-provider]`，同样属 ext-served 子集，缺 `ext-knowledge.yaml` 被阻断。判定同上。

> A 类归因：**测试环境准备缺失**。3 条用例的依赖声明都合法，是 `config/ext-knowledge.yaml` 未按 `infra/config/ext-knowledge.example.yaml` 创建并挂载 mock 所致。

---

### B 类：用例/测试代码缺陷（11 条）

**4. PW-MEDIA-STT-01｜超时**
- 描述：真实 STT 配置→Chat 语音输入→转写→发送。失败于 `getByPlaceholder('发送消息...')`
- **判定：用例问题（定位器过时）**
- 依据：`public/locales/zh/common.json` 中**不存在**「发送消息...」这个 placeholder 文案。存在的只有 `chatInput.sendMessageTo`「给 {productName} 发送消息」和 `chatInterface.createDialogFailedButContinue`（日志文案）。用例的 Composer 定位器与当前 UI 不符

**5. PW-MEDIA-VLM-01｜超时**
- 描述：真实 VLM→图片附件→多模态回答。失败于 `locator('[data-composer-action-trigger]')`
- **判定：用例问题（定位器不存在）**
- 依据：全前端代码库 `grep -rn "data-composer-action-trigger"` **零匹配**。该 data 属性已被移除或改名，用例仍在引用

**6. PW-MODEL-01｜失败 (FAIL)** ⚠️ 部分业务嫌疑
- 描述：模型 V2 从 Provider 导入/自定义接入→真实连通性→保存→Agent 使用。失败于 `[data-testid='agent-debug-panel'] textarea[placeholder='输入"/"快速引用技能及指令']:visible, textarea[placeholder*="输入测试问题"]:visible`
- **判定：以用例问题为主（定位器之一已失效），但需二次确认**
- 依据：`agent-debug-panel` testid **存在**（`agents/[agentId]/components/debug/agent-debug.tsx:210`）；`输入测试问题` placeholder **存在**（locale `agent.debug.placeholder` = 「输入测试问题...」）；但 `输入"/"快速引用技能及指令` **不存在**。用例用了双候选定位器（逗号 OR），第二种理论上应能命中——若两种都超时，说明 **debug 面板整体未渲染**（可能因前置的模型保存步骤失败导致面板未出现），此时应转为业务链路问题。建议先修定位器再复跑，若仍失败则升级为业务缺陷

**7. PW-MODEL-02｜失败 (FAIL)**
- 描述：真实 Embedding/Multi-Embedding→Local KB 索引→检索。失败于 `getByRole('heading', {name:'知识库'})`
- **判定：用例问题（断言方式不合理）**
- 依据：`app/[locale]/knowledges/KnowledgeBaseConfiguration.tsx` 中**没有任何 `<h1>/<h2>/Typography.Title>` 或 `role="heading"` 元素**。知识库页标题不以 heading role 呈现，用例用 ARIA role 断言一个不存在的语义节点

**8. UT-FE-005｜失败 (FAIL)** ⚠️ 用例数据错误
- 描述：locale 切换、路由保留、关键文案 fallback
- **判定：用例问题（断言预期值错误）**
- 依据：用例断言 `expect(request.mock.calls.map(...)).toEqual(['/portal/locales/en/common.json', ...])`，硬编码了 `/portal/` 前缀；但实现 `app/[locale]/i18n.tsx:106` 请求的是 `/locales/${localePath}/common.json`，**无 `/portal` 前缀**（basePath 由构建注入，不是硬编码在 fetch 里）。用例把构建期 basePath 写死进了断言

**9. UT-FE-AUTO-190989439ADD3E0F｜失败（6/6 全挂）**
- 描述：个人资料账户信息区按 authProvider 区分 Username/Email 展示与 CAS 空用户名回退邮箱
- **判定：用例问题（测试缺 Provider 包装）**
- 依据：6 个 testcase 全部报 `No QueryClient set, use QueryClientProvider to set one`

**10. UT-FE-AUTO-63334E6F5D10C7FD｜失败（11/12 挂）**
- 描述：avatarDropdown 与 TopNavbar 用户区 username 优先、回退 email、两者皆空显示 '-'
- **判定：用例问题（测试缺 Provider 包装）**
- 依据：同样全部报 `No QueryClient set`。测试直接 `render(<TopNavbar />)` / `render(<AvatarDropdown />)`，未包 `QueryClientProvider`；而 `avatarDropdown.tsx:76` 调用 `useAccountMonitoring()`，后者 `hooks/useAccountMonitoring.ts:16` 使用 `@tanstack/react-query` 的 `useQuery`。**依赖链 100% 确认**

**11. UT-FE-AUTO-877E165BC61D430D｜失败**
- 描述：标签定义/值编辑、启停与置顶，资源分配单/多选、容量上限及 409 冲突提示
- **判定：用例问题（断言实现细节，重构即碎）**
- 依据：用例读源文件做**字符串匹配**：`expect(readFileSync('.../TagDefinitionManagementModal.tsx')).toContain('createDefinition')`。实际该 Modal 已被 #4155 重构为壳组件（50 行，只渲染 `<TagDefinitionManagementPanel>`），`createDefinition`/`updateDefinitionStatus`/`moveDefinitionToTop` 已迁至 `TagDefinitionManagementPanel.tsx`（实测 5 处命中）。**功能完全正常，断言绑定了具体文件名+函数名，属白盒过度耦合**

**12. REL-AUTO-80AA755E2436D269｜失败**
- 描述：ES 向量库统计异常时个人/租户配额检查与用量展示 fail-open（源文件账本唯一口径）
- **判定：用例问题（monkeypatch 打错模块）**
- 依据：失败 `assert 0 == 5242880`。用例 `monkeypatch.setattr(quota_service, 'get_tenant_committed_source_bytes', tenant_committed)` 打在 `management.services.knowledge_base.quota` 模块；但 `get_usage` 实际定义在 `knowledge_base/usage.py:503`，并在 `usage.py:567` 调用**本模块导入**的 `get_tenant_committed_source_bytes`。**打桩目标模块错位导致桩不生效**，业务实现正确

**13. PW-AUTH-01｜失败**
- 描述：本地登录→受保护路由→刷新/多 Tab→退出。失败于 `getByText('智能体开发', {exact:true})`
- **判定：用例问题（导航结构已变）**
- 依据：`SideNavigation.tsx:322-334` 的 `accessibleMenuItems` 显式过滤 `!route.isSection`；`/agent-dev`（`labelKey: "sidebar.agentDev"` = 智能体开发）正是 `isSection: true`（第 99 行）。**该文本永远不会渲染为可点击菜单项**。文案仍在 locale 中，但不再上屏

**14. PW-RESOURCE-01｜失败**
- 描述：SU 创建租户→可选管理员→选择租户→资源 Tab 加载。失败于 `getByRole('tab', {name:'知识库'})`
- **判定：用例问题（未适配条件渲染）**
- 依据：`UserManageComp.tsx:1373-1385` 知识库 tab 是**条件渲染**：`...(!enableAidpKnowledge ? [{key:'knowledge', label: t('tenantResources.tabs.knowledge')}] : [])`，注释明确说明「AIDP 知识库启用时该 tab 由统一 `/knowledges` 入口管理，不得在此出现」。若测试环境开启 AIDP，tab 隐藏是**设计如此**。用例未声明/未适配该环境开关

> B 类归因：**用例/测试代码缺陷 11 条**，可细分：
> - 定位器过时/不存在：PW-MEDIA-STT-01、PW-MEDIA-VLM-01、PW-AUTH-01（3 条）
> - 断言方式不合理（ARIA 语义/源码字符串）：PW-MODEL-02、UT-FE-AUTO-877E（2 条）
> - 测试脚手架缺失（Provider 包装）：UT-FE-AUTO-190989、UT-FE-AUTO-63334（2 条）
> - 断言预期值错误：UT-FE-005、PW-RESOURCE-01（2 条）
> - 打桩目标错位：REL-AUTO-80AA（1 条）
> - 混合待确认：PW-MODEL-01（1 条）

---

### C 类：业务逻辑/实现问题（2 条）

**15. PW-UI-02｜失败**
- 描述：键盘可访问性 Smoke：导航→Dialog→表单→关闭。失败于 `getByRole('dialog', {name:'创建智能体'})` 期望 hidden 实际 visible
- **判定：业务问题（可访问性实现缺陷）**
- 依据：**`components/common/StandardModal.tsx:80` 显式设置 `keyboard={false}`**，禁用 ESC 关闭。`closable={false}` + `mask={{closable:false}}` + `keyboard={false}` 三重关闭路径全禁，只能点自定义关闭按钮。而 WCAG 2.1.2 / ARIA APG Dialog 模式要求 ESC 必须关闭对话框，用例步骤 4「按 Escape 关闭，焦点返回触发元素」是**正确的可访问性预期**。这是真实 a11y 缺陷。失败证据 `failure.json` 显示 59 次重试对话框始终 `visible`

**16. API-AUTO-DDE7582FFE405D54｜失败** ⚠️ 需澄清语义
- 描述：Agent 批量命名 check_name/regenerate_name 契约（冲突检测、quick-config LLM 重生成、数字后缀回退、无模型抛错）
- **判定：用例问题（租户隔离语义理解偏差）**
- 依据：失败 `assert 1 >= 2`（`conflict_agents` 只返回 1 条）。用例在**两个不同租户**各创建一个同名 Agent，然后期望当前租户的 check_name 返回 ≥2 条冲突。但实现 `management/services/agent/service.py:239` 明确：`query_all_agent_info_by_tenant_id(tenant_id)` **只查当前租户**，docstring 写明「conflicts exist **in the tenant**」。**跨租户同名不应冲突是租户隔离的正确设计**，用例把跨租户场景当成本租户冲突，属用例设计错误

> C 类归因：**真业务问题 1 条（PW-UI-02 a11y）+ 1 条实为用例问题（API-AUTO 已归入 B 类性质）**

---

### D 类：记录缺失/无法判定（3 条）

**17. MON-D3-TRACE-NAME-001｜阻断 (BLOCKED)**
- 描述：Consistent main Agent trace name through real Langfuse ingestion
- **判定：无法判定（证据缺失）**
- 依据：`文本证据` 列为空、`运行器完整原因` 仅「blocked」、批次包内 `cases/MON-D3-TRACE-NAME-001/` **无 junit.xml**。需要补齐阻断原因才能归因

**18. NAV-MENU-D4-001｜阻断 (BLOCKED)**
- 描述：Preserve functional navigation while hiding inert controls
- **判定：用例问题（声明缺失）**
- 依据：报错 `Missing per-case preparation declaration`——用例 `execution.yaml` 的 `preparation` 段未声明必需字段。这是用例元数据不完整，不是业务缺陷

---

## 二、整体归因小结

| 类别 | 条数 | 占比 | 说明 |
|---|---|---|---|
| A 测试环境/依赖未就绪 | 3 | 16% | ext-knowledge mock 未挂载 |
| B 用例/测试代码缺陷 | 11 | 58% | 定位器过时 3、断言方式 2、脚手架缺失 2、预期值错 2、打桩错位 1、待确认 1 |
| C 真业务问题 | 1 | 5% | PW-UI-02 ESC 关闭 a11y 缺陷 |
| D 记录缺失/无法判定 | 2 | 11% | MON-D3 无证据、NAV-MENU 声明缺失（已归 B 的话则 3 条） |
| 其它（协同类） | 2 | 11% | 产品问题10-09 中的 API-049、API-056（已修复/待复核） |

**核心结论**：19 条中 **14 条（74%）属于测试侧问题**（用例缺陷 11 + 环境缺失 3），**仅 1 条（5%）是确定的业务实现缺陷**，2 条证据不足需补。

**系统性风险信号**（不是单条用例问题，而是测试资产治理问题）：
1. **UI 定位器批量失效**：3 条 PW 用例挂在 `发送消息...`、`data-composer-action-trigger`、`智能体开发` 这些已不存在的选择器上。说明**前端改版（#4095 导航重构、chat 重构 #4085）后未同步更新 page object**
2. **白盒断言过度耦合**：UT-FE-AUTO-877E 直接 grep 源文件函数名，任何重构都会误报
3. **测试脚手架规范缺失**：2 条 react-query 用例未包 Provider，说明缺少统一的 render 工具（应提供 `renderWithProviders`）
4. **Option/环境开关未参数化**：PW-RESOURCE-01 未处理 `enableAidpKnowledge` 分支
5. **monkeypatch 目标需按实现模块而非导入模块**：REL-AUTO 打桩错位暴露测试对代码边界的理解偏差

---

## 三、优先处理建议

### P0（本周内，影响面最大）

1. **建立统一前端测试渲染工具**（解决 2 条 react-query 用例）
   - 新增 `frontend/tests/utils/renderWithProviders.tsx`，包装 `QueryClientProvider` + `I18nProvider` + `AuthorizationProvider`
   - 所有组件级测试改用该工具，禁止裸 `render()`
   - 收益：UT-FE-AUTO-190989 / 63334 立即转绿，且预防后续同类问题

2. **修复 StandardModal 的 ESC 关闭**（唯一确定的业务缺陷）
   - `StandardModal.tsx:80` 的 `keyboard={false}` 改为 `keyboard` 或 `keyboard={true}`
   - 但需评估：当初设为 false 可能是为了防误触关闭（表单填写中）。建议按场景区分：只读/确认类 Modal 允许 ESC，表单类可保留 false 但必须在用例中显式声明例外
   - 若决定保留 `keyboard={false}`，则**必须把 PW-UI-02 步骤 4 改为显式跳过或改断言**，并在 a11y 文档中记录例外理由

### P1（两周内，消除批量误报）

3. **page object 与 UI 契约同步机制**
   - 把 `发送消息...`、`data-composer-action-trigger`、`智能体开发`、`知识库 heading` 等定位器统一收敛到 `page-objects/` 下的选择器常量
   - 前端改版 PR 必须同步更新选择器（可在 CI 加 smoke：跑一次导航/Composer smoke 检查关键选择器存在）
   - 涉及：PW-MEDIA-STT-01、PW-MEDIA-VLM-01、PW-AUTH-01、PW-MODEL-02

4. **UT-FE-AUTO-877E 断言改造**（源码字符串 → 行为断言）
   - 改为渲染 `TagDefinitionManagementModal` 后断言「能看到定义列表 / 能触发创建流程 / 状态切换有效」
   - 或退一步：grep 目标改为 `TagDefinitionManagementPanel.tsx`（治标），但长期应做行为断言

5. **UT-FE-005 修正 basePath 断言**
   - 去掉硬编码 `/portal` 前缀，改为断言 `url.endsWith('/locales/en/common.json')` 或用构建期 basePath 变量

6. **REL-AUTO-80AA 修正打桩目标**
   - `monkeypatch.setattr` 改到 `management.services.knowledge_base.usage` 模块

### P2（一个月内，补齐与澄清）

7. **补齐 ext-knowledge mock 环境**（解决 3 条 BLOCKED_BY_DEPENDENCY）
   - 按 `infra/config/ext-knowledge.example.yaml` 创建 `<test-home>/config/ext-knowledge.yaml` 并挂载 mock compose
   - 建议在 `local_preflight.py` 增加「ext-served 用例已选但 mock 未配置」的**前置提示**，避免跑到一半才阻断

8. **PW-RESOURCE-01 环境参数化**
   - 在 `execution.yaml` 声明 `enableAidpKnowledge` 取值；或断言改为「知识库入口在 /knowledges 或当前 tab，二者其一可见」

9. **API-AUTO-DDE7582FFE405D54 澄清需求**
   - 需产品明确：Agent 名称唯一性是**租户内**还是**全局**。当前实现是租户内（且有 docstring 佐证），若产品确认租户内，用例改掉跨租户断言；若产品要求全局唯一，则是业务缺陷需改实现

10. **补齐 MON-D3-TRACE-NAME-001 证据链**
    - 记录阻断原因到 `运行器完整原因` 列，否则无法归因

11. **PW-MODEL-01 定位器修正后复跑**
    - 修掉 `输入"/"快速引用技能及指令` 这个不存在的候选，单用 `输入测试问题`；若仍失败，说明 debug 面板未渲染，转为业务链路排查

---

## 附：产品问题10-09 中武兆福相关（4 条，非本次批次）

| 用例 | 问题 | 判定 | 状态 |
|---|---|---|---|
| API-AUTO-357B84F01BA6D321 | 文档标签投影写入失败后对空状态调用 `.get()` 二次抛异常 | **业务问题**（强证据，异常处理缺陷） | 已修复 |
| API-049 | Provider 连接失败被包装 500，响应体却是 502 connection_failed | **业务问题**（HTTP 语义不一致） | 已修复 |
| API-056 | 跨租户查询 Agent 返回 500 而非明确拒绝 | **业务问题**（错误码不规范，未证实泄漏） | 待复核 |
| PW-MCP-MARKET-01 | 标签保存成功但 Mine 卡片 30 秒内未展示 | **待复核**（可能是缓存/投影延迟） | 待复核 |

> 注：这 4 条是 10-09 存量，非 10-22 批次。列在此处便于统一跟踪。其中前两条已修复，说明**早期批次确实发现过真业务缺陷**，与本次 10-22 批次「仅 1 条业务问题」形成对比——可能暗示近期业务质量有所改善，也可能暗示测试覆盖在 UI 层收缩（大量用例卡在环境/定位器上，未能触及业务逻辑）。
