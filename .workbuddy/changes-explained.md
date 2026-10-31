# 本次改动的用例说明：期望什么、为什么改

按「用例期望 → 原来的问题 → 为什么这么改」逐条说明。

---

## 一、产品类（1 条）

### PW-UI-02 键盘可访问性 Smoke

**用例期望什么**

`case.yaml` 的 step 4 写的是「按 Escape 关闭，焦点返回触发元素」，expected 是「Dialog 焦点管理正确」。这是 WCAG 2.1.2（No Keyboard Trap）和 ARIA APG Dialog 模式的标准要求——ESC 必须能关掉对话框。

**原来的问题**

`StandardModal.tsx` 把三条关闭路径全禁了：

```tsx
closable={false}              // ① 没有右上角 X
mask={{ closable: false }}    // ② 点遮罩不关
keyboard={false}              // ③ ESC 不关 ← 缺陷
```

失败日志是 `3 × ... 59 × ...` 两次轮询、59 次重试全都 `visible`，30 秒超时。**这说明关闭通路是彻底打不开的**，不是时序问题。

**为什么这么改**

底层 `@rc-component/dialog` 里 `keyboard = true` 本来就是默认值：

```js
const onEsc = ({ top, event }) => {
  if (top && keyboard) {      // keyboard=false 时直接跳过
    event.stopPropagation();
    onClose?.(event);
  }
};
```

**所以这不是「缺功能」，是封装层主动覆盖了库的合理默认值。** 改成 `keyboard={closeOnEscape}`，新 prop 默认 `true`，需要防误触的场景显式传 `false`。

顺带说明：`closable={false}`（无 X 按钮）我**没动**，那属于产品体验决策，得产品拍板。

---

## 二、定位器类（7 条）

这几条的共同特征：**表现为 30 秒超时，而不是断言失败**——因为选择器根本找不到元素，Playwright 一直在等。

### PW-MEDIA-STT-01 真实 STT 语音输入

**期望什么**：真实调 STT，转写结果进入 Composer，且能直接发送。

**为什么改**：用例用 `getByPlaceholder('发送消息...')` 找输入框。但 `composer.tsx:703` 和 `:715` 的 `placeholder` 被**显式赋值为空字符串**：

```tsx
placeholder=""
```

页面上永远不会有「发送消息...」这个 placeholder。更麻烦的是输入框已经从 `<textarea>` 换成了 Lexical contenteditable（`.aui-lexical-input`），所以 `inputValue()` / `toHaveValue()` 也一起失效。

**改成什么**：新增 `ChatPage.composerText()` 读 `innerText` 并剔除零宽字符（`\u200b`，Lexical 会产生），断言用 `expectComposerText()` 轮询——STT 转写是异步的，必须轮询。

### PW-MEDIA-VLM-01 图片附件多模态

**期望什么**：上传图片附件，触发多模态回答。

**为什么改**：`[data-composer-action-trigger]` 在整个前端代码库**零匹配**。工具栏重构后这个属性被删了。

**改成什么**：`ComposerAddAttachment` 是 `TooltipIconButton`，它的 tooltip 会同时输出成 `sr-only` 文本，所以按钮有可访问名「添加附件」（locale key `chat.composer.addAttachment`）。改用 `getByRole("button", { name: "添加附件" })`。

### PW-MODEL-01 模型接入后 Agent 使用

**期望什么**：模型配置保存后，Agent 调试面板能用这个模型跑起来。

**为什么改**：debug 面板已经改成 `@assistant-ui` 的 `Thread`，输入元素不再是 textarea。而 `agent.debug.placeholder` 这个 locale key **还存在但已无任何代码引用**——是遗留死键。

**改成什么**：新增 `AgentPage.debugComposer()`，用 `[data-workbench-composer], .aui-lexical-input` 锚点，一次性替换 5 处失效定位。

> **这里我和 develop 的 #4178 做了不同选择**：#4178 用 `getByRole("textbox", { name: "对话输入" })`。我查了 `@assistant-ui/react-lexical` 源码，`aria-label` 挂在外层 `div.aui-lexical-editor` 上，`role=textbox` 在内层 contentEditable 上——两者不在同一个元素，按可访问名匹配有落空风险，所以用锚点直接命中。

### PW-MODEL-02 Embedding 索引与检索

**期望什么**：配置 Embedding 后，Local KB 能建索引并检索。

**为什么改**：用例断言 `getByRole('heading', { name: '知识库' })`，但 `KnowledgeBaseConfiguration.tsx` 渲染的标题**不是 `role=heading`**（没有 h1/h2）。

**改成什么**：断言互斥双态——要么创建工具栏可见，要么「未配置向量模型」提示可见。这两个状态必居其一，比找标题更能证明「页面已就绪」。

### PW-AUTH-01 登录与路由保护

**期望什么**：未登录看不到受保护内容；登录后能访问；刷新不丢 session；退出后旧 session 不能复用。

**为什么改**：用例用 `getByText('智能体开发')` 判断受保护导航是否可见。但「智能体开发」在 `SideNavigation.tsx` 里是 `isSection: true` 的**分组标题**，被 `accessibleMenuItems` 的过滤条件排除：

```js
!route.isSection     // ← 分组标题不进入可点击菜单
```

**它永远不上屏。** 用这个断言「受保护导航可达」，无论登录与否都必然失败。

**改成什么**：用「工作台」——`hideHomePage=true` 时的默认落地页，最稳定。

### PW-UI-01 zh/en 切换

**期望什么**：切换语言后路由和页面状态不串。

**为什么改**：用例 `getByText(/简体中文/).last()` 直接点。但语言选项在**头像菜单 → 语言设置 → 二级子菜单**里（`avatarDropdown.tsx` 用 `children` 渲染）。元素存在于 DOM，但不可见，点击必然超时。

**改成什么**：新增 `AuthPage.switchLanguageTo()`，先 hover 展开二级菜单再选。

### PW-CHAT-02 / PW-KB-LOCAL-01

与上面同源，同步收敛到 page object 方法。`PW-CHAT-02` 的定位器修复 develop 的 #4178 也做了，合并时采用了它的方案。

---

## 三、断言与脚手架类（8 条）

### API-AUTO-DDE7582FFE405D54 Agent 批量命名契约

**期望什么**（`case.yaml` 原话）：

> `check_name` 对每个 item 返回 `{name_conflict, display_name_conflict, conflict_agents}`，**布尔与冲突记录与租户内实际重名情况一致**，并正确排除自身 `agent_id`。

**原来的问题**：用例在同一租户内连续创建两个同名 Agent，然后期望 `len(conflict_agents) >= 2`，实际返回 1 条，`assert 1 >= 2` 失败。

**为什么改 —— 用例的前提本身不成立**：

`update_agent_info_impl` 在**创建时**就会调用 `generate_unique_agent_value`：

```python
def generate_unique_agent_value(field_key, base_value, tenant_id, ...):
    """Find the first free numeric suffix using the existing tenant scope."""
    for counter in range(1, max_suffix_attempts + 1):
        candidate = f"{base_value}_{counter}"
```

也就是说第二个 Agent 落到 `dup_name_1`，**租户内物理上不可能存在两个同名草稿**。返回 1 条是正确行为。

**改成什么**：断言创建期的自动改名契约（存在 `dup_name_1` 这类后缀名），且 `conflict_agents == 1`。这才是产品真实行为。

### UT-FE-005 locale 切换与 fallback

**期望什么**：
1. 目标 locale 正确，业务路径和 BASE_PATH 保留，`NEXT_LOCALE` Cookie 更新
2. 未知 locale 用英文，缺失键回退英文或 defaultValue
3. **已有翻译不被清空**

**为什么改 —— 四处问题叠加**：

| 问题 | 具体表现 |
| :--- | :--- |
| 硬编码 `/portal` | 实现是 `/locales/${localePath}/common.json` + 运行时 `withBasePath` 拼接 |
| 模块级缓存污染 | `i18n.tsx` 用 `commonMessageRequests` / `customMessageRequest` 单例记忆化，前面 4 个 `it.each` 已经把缓存填满，后面 stub 的 `fetch` **永不被调用** |
| mock 缺 `ok` | `response.ok` 是 `undefined`，每次请求都落进异常分支 |
| 断言错对象 | 读 `resourcesCustom.en.common`，但 `common` 在 `resources.en.common`（`resourcesCustom` 只承载 `custom` overlay） |

**改成什么**：`vi.resetModules()` + 重新 `import` 拿干净缓存；mock 补 `ok: true`；改读 `resources.en.common`；失败场景改为观察 live i18n 实例（`hasResourceBundle` / `t()`）。

> 第 3 个断言（已有翻译不被清空）原本读 `loadLocaleMessages` 的返回值，但**失败路径下那个载体从不被填充**，所以断言必然拿到 `{}`。这就是我一开始改错、后来改成查 i18n 实例的原因。

### UT-FE-AUTO-190989439ADD3E0F 个人资料页 authProvider 区分

**期望什么**（`case.yaml` 原话）：

> 标签判定严格以 `user.authProvider==="cas"` 为准：CAS 显示 "Username"，本地显示 "Email"。
> 本地用户取值**仅 `email.trim()`**，不使用 username。

**为什么改 —— 两个问题**：

**① 缺 Provider**。`UserProfileComp` 直接调 `useQuery`（oauthService 配置），裸 `render()` 会抛 `No QueryClient set`。补 `QueryClientProvider`。

**② 断言过度**。原用例这样写：

```ts
get username() {
  throw new Error('username must not be read for local users');
}
```

用「读一下就抛错」来证明不读 username。但实际实现是：

```tsx
<UserIdentity casUsername={user?.username} fallback={user?.email?.trim() || "-"} />
```

```ts
export function getUserDisplayName(authProvider, casUsername, fallback) {
  return authProvider === "cas" && casUsername?.trim() ? casUsername.trim() : fallback;
}
```

**`user?.username` 是照常传下去的，由 `getUserDisplayName` 内部按 provider 决定用不用。** 所以「读取」本身合法，规则是「不应采用」。

**改成什么**：给 username 塞一个哨兵值 `should_not_be_used`，断言页面上**不出现**它。这既证明了规则，又不要求实现不能碰这个字段。

### UT-FE-AUTO-63334E6F5D10C7FD avatarDropdown 与 TopNavbar

**期望什么**（原始设计）：

> 登录态下 username 存在时，**两处用户区**均显示 trim 后的 username。
> **avatarDropdown 菜单与 TopNavbar 用户区展示逻辑一致**。

**为什么改 —— 前置条件消失了**：

#4058（10-12 的 `feat(frontend): redesign agent and chat workflows`）把用户区从 `TopNavbar` 移到了 `SideNavigation` 的 rail。现在 `TopNavbar.tsx` 里 `AvatarDropdown` 和 `user?.username` 的引用数**都是 0**，顶栏只剩监控入口、GitHub 链接、语言切换。

**所以「两处用户区一致」这个前提不存在了**，6 个顶栏断言（用户名、trim、回退 email、显示 `-`）全部不可能通过。

**改成什么**：
- 顶栏部分改成**守卫断言**：TopNavbar 不得出现身份文本、不得有 `.ant-avatar`。这仍然有价值——防止用户区被误加回顶栏造成重复显示。
- 身份规则改由 `AvatarDropdown` 验证（它是两个入口共同挂载的组件）。
- 顺带补了漏掉的 `useAccountMonitoring` mock（14 个 mock 里唯独漏了真正用 TanStack Query 的那个）。

> **这条我改动最大，也最需要你确认**：它实质上是修改了验收标准（从「两处一致」变成「顶栏不含身份」）。如果团队认为应该保留原标准、标记为 blocked 等产品或测试负责人裁决，我可以改回去。

### UT-FE-AUTO-877E165BC61D430D 标签定义与值编辑

**期望什么**：定义/值 CRUD、启停、置顶都映射到对应 service 方法，成功路径有 success 提示并刷新列表。

**为什么改**：原断言读源文件后 grep 函数名：

```ts
const definitions = readFileSync(`.../TagDefinitionManagementModal.tsx`, 'utf8');
expect(definitions).toContain('createDefinition');
```

但 #4155 标签管理集中化后，`createDefinition` / `updateDefinitionStatus` / `moveDefinitionToTop` 已经迁到 `TagDefinitionManagementPanel.tsx`（Modal 变成 50 行壳组件）。**功能完全正常，只是断言绑死了文件路径。**

**改成什么**：新增 `readComponentSource(repoRoot, relativePaths[])`，按候选列表读取——存在即读、全部读取后拼接。下次再重构拆文件不会碎。

> 说明：这本质还是「源码字符串匹配」的白盒断言，不够理想。但改成真实行为断言需要 mock 大量 service，超出本次范围。折中方案是让它对文件搬移有韧性。

### REL-AUTO-80AA755E2436D269 ES 统计异常时配额 fail-open

**期望什么**（`case.yaml` 原话）：

> `get_usage` 正常返回，`total_bytes` 等于**源文件账本口径**（`get_tenant_committed_source_bytes`），`es_physical_bytes` 作为独立字段返回且不影响 `total_bytes`。

**为什么改**：用例这样打桩：

```python
monkeypatch.setattr(quota_service, 'get_tenant_committed_source_bytes', tenant_committed)
```

打在 `quota` 模块。但 `QuotaService.get_usage` 实际定义在 `usage.py:503`，而 `usage.py` 自己 `from ... import get_tenant_committed_source_bytes` 到了**它自己的命名空间**。

Python 里 monkeypatch 模块属性只影响「通过那个模块访问」的路径，**管不到另一个模块里已经 import 好的符号引用**。所以桩从未生效，真实账本读到 0，`assert 0 == 5242880` 失败。

**改成什么**：同时 patch `usage_service`。这是**用例的打桩目标错了**，业务逻辑本身没问题。

### NAV-MENU-D4-001 导航可见性

**期望什么**：保持可用导航，隐藏失效控件。

**为什么改**：`execution.yaml` **完全没有 `preparation` 段**。对照 `PW-UI-02` 有完整的四个字段：

```yaml
preparation:
  families: []
  anchors: true
  special_assets: false
  d4_groups: []
```

运行器要求 D4 用例必须有这个声明，否则直接阻断（`Missing per-case preparation declaration`）。

**改成什么**：补齐。

---

## 四、顺带修的既有失败（2 个测试文件）

`sharedShellLayout.test.tsx` 和 `agentPublishAndSharePage.test.tsx` 的 `next/navigation` mock 只提供了自己 import 的 hook：

```ts
vi.mock("next/navigation", () => ({ usePathname: () => state.pathname }));
```

但组件树经 `ClientLayout` 会调用 `useRouter()`，vitest 在断言前就抛「No useRouter export is defined on the mock」。

补齐后 `sharedShellLayout` 从 **10 failed → 10 passed**。

`agentPublishAndSharePage` 还剩 5 个失败，原因是 locale 缺 `agent.version.versionName`。**我用 `git stash` 还原 `StandardModal` 复跑过，同样 5 个失败**，证明与我的改动无关，属于既有问题。

---

## 归纳：三类根因

| 类型 | 条数 | 本质 |
| :--- | :-: | :--- |
| **产品正常演进，用例没跟上** | 7 + 1 | 前端两次重构（Composer 换 Lexical、导航改版、用户区迁移）改变了 DOM 结构和方法语义，用例还在找旧元素 |
| **用例断言写错了** | 7 | 前提不成立（同名 Agent 创建）、打桩打错模块、硬编码 URL 前缀、断言过度、读错字段 |
| **产品真有缺陷** | 1 | StandardModal 覆盖了库的 ESC 默认值，违反 WCAG 2.1.2 |

**19 条里 15 条是测试侧问题，只有 1 条是产品缺陷。** 这个比例值得注意：可能是质量改善，也可能是 UI 层测试覆盖被大面积架空——大量用例根本没走到业务逻辑就在定位器上超时了。
