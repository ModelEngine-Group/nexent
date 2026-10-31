# PR #4093 Code Review — 智能体编辑页与资源选择器 UI 精细化

- **PR**: [ModelEngine-Group/nexent#4093](https://github.com/ModelEngine-Group/nexent/pull/4093) `feat(frontend): refine agent editor UI and resource-picker dialogs`
- **作者**: bernard1234 · 7 commits · 39 files · +1594/−1151
- **基准**: merge-base `90bf1a5db`（= 刚合入的 #4084，PR 已含最新 develop，无漂移）
- **性质**: 纯前端 UI 改造，无后端/SDK 改动

---

## 总体评价

**工程素质高，但有 1 个 blocker——共享组件硬编码中文默认值，恰好复现了 #4084 刚修完的问题类型。** 改造本身系统性强：ParamDialog 从固定用途扩展为四变体共享 shell（tool/skill/model/publish），补齐了 `confirmLoading`/`cancelDisabled`/`destroyOnHidden` 这些生产必需的 props；发布弹窗迁移后双击防抖、缓存失效一应俱全；39 个文件版权头全覆盖；`fix(ci)` 单独补漏的提交说明 CI 有 header 检查且作者响应了。

---

## 🔴 Blocker

### B1. ParamDialog 按钮文案默认值硬编码中文 — 英文界面将显示"确定/取消"

`frontend/components/resource-picker/ParamDialog.tsx` **L29-30**：

```ts
confirmText = "确定",
cancelText = "取消",
```

组件内部已有 `const { t } = useTranslation("common")`，旧版实现用的是 `confirmText ?? t("common.confirm")`（fallback 到翻译），**本 PR 把它改成中文硬编码默认值，是倒退**。

三个调用方不传文案，直接吃这个默认值：
- `resource-picker/ToolConfigModal.tsx` L84（无 confirmText/cancelText）
- `resource-picker/SkillConfigModal.tsx` L33（同上）
- `resource-picker/ModelParamsModal.tsx` L311（同上）

而真实在用的两个（`agents/components/capability/tool/ToolConfigModal.tsx` L2235-2238、`skill/SkillConfigModal.tsx` L452-453）和发布弹窗（L188-189）都显式传了 `t(...)`——所以受影响的是 resource-picker 下的三个。加上 `resource-picker/SkillConfigModal.tsx` L36 的硬编码标题 `` `${skillName} 配置` `` 和 L43 的 `"查询数量"`，这个组件族在英文界面会全面显示中文。

**讽刺点**：merge-base 恰好是 #4084（"修复英文界面有中文"）——这个 PR 紧跟着引入了同型问题。

**建议**：默认值改回 `t("common.confirm")` / `t("common.cancel")`，或者干脆删掉默认值让调用方必传。

---

## 🟡 Suggestions

### S1. useAuthorization 硬编码路由权限特判

`frontend/hooks/auth/useAuthorization.ts` **L193**：

```ts
(cleanPath === "/workbench" && accessibleRoutes.includes("/chat")) ||
```

一行代码让所有能访问 `/chat` 的用户都能访问 `/workbench`。这是**权限模型的后门**——它绕过了后端下发的 `accessibleRoutes`，且没有注释解释为什么 workbench 要依附 chat 权限。如果是有意的（workbench 未单独配权限时降级到 chat），至少需要注释说明来源（哪个需求/决策）；如果 workbench 未来有独立权限位，这行会静默扩大访问面。

**建议**：补充决策出处注释，或改为后端在 `accessibleRoutes` 里直接下发 `/workbench`。

### S2. zh locale 改文案但未评估 en 对齐

`frontend/public/locales/zh/common.json` 两处：
- L779 `toolPool.group.mcp`: `"MCP"` → `"MCP服务"`
- L5740 `resourcePicker.knowledge.chunks`: `"{{count}}块"` → `"{{count}}分块"`

en 侧对应值（`"MCP"` / `"{{count}} chunks"`）未动。zh 侧改法本身合理（分组标签更明确），但 PR 描述只提"Fix zh locale labels"一笔带过，且这类产品文案变更建议在 PR 描述里列明改动前后对照，方便验收。

### S3. `resumeLatestAgentConversation` 成为死代码

`frontend/app/[locale]/newchat/page.tsx` L797 把唯一的调用者从 `resumeLatestAgentConversation(runtime, ...)` 换成了 `startAgentConversation(runtime, ...)`（会话切换改为每次新起会话——这是行为变更：**切换智能体不再恢复最近会话**，请确认这是产品意图）。但 `thread-agent-registry.ts` L57 的函数定义和导出原样保留，无任何调用者。

**建议**：删除死函数，或在 PR 描述确认"恢复最近会话"被有意移除（用户切换智能体时丢失会话上下文是可感知的行为变化）。

### S4. demo 组件里的假 API key 与硬编码中文

`frontend/components/resource-picker/SkillConfigModal.tsx` L28 `useState("aqVLa_4z7T…")`（假 Tavily key）、L36 `` `${skillName} 配置` ``、L43 `"查询数量"`。已确认该组件无任何页面引用（真实在用的是 `agents/components/capability/skill/` 下的同名组件），是 demo/prototype 遗留。非本 PR 引入（merge-base 就有），但本 PR 还在给它加 `variant` prop 继续维护它。

**建议**：要么删除，要么文件头标注 `@internal demo`，避免后人误用。

---

## 💭 Nits

- **ParamDialog.module.css 36 处 `!important`**：对 antd 内部样式的覆盖面较大，antd 升级时是回归重灾区（`input.ant-input { height: 28px !important }` 等）。建议记录在样式文档里，或用 antd `ConfigProvider theme` 收敛一部分。
- **发布弹窗文件名拼写**：`AgentVersionPubulishModal.tsx`（Pubulish）——存量拼写错误，顺手改名成本最低的时机就是现在。
- **composer.tsx L791-793 残留硬编码中文**（`"退出创建模式"` aria-label、`"Skill 创建"/"Agent创建"`）——存量，非本 PR 引入，但既然 PR 动了这个文件的字号样式，可顺手 i18n 化。

---

## ✅ 验证通过的部分

- **发布弹窗迁移**（`AgentVersionPublishModal.tsx`）：`confirmLoading` + `confirmDisabled` + `cancelDisabled={isLoading}` 双击防抖齐全；成功后 `resetFields` + 三个 queryClient 失效（agents/publishedAgentsList/myEditableAgents）；重名校验排除自身；`destroyOnHidden` 正确
- **locale 路由修复**：`agent-capability.tsx` 的 `router.push("/mcp-space")` → `router.push(\`/${locale}/mcp-space\`)`，`useParams` 取 locale，正确
- **BooleanSwitchInput 适配器**（agents 版 ToolConfigModal）：把 Form.Item 的 value/onChange 契约桥接到 ParamSwitch 的 checked/onChange，干净
- **三色渐变默认头像**：`getDefaultAgentAvatarSvg` 返回字符串 SVG，`DefaultAgentAvatar` 用 data-URI `<img>` 渲染——比旧的 inline span+svg 更轻，`encodeURIComponent` 转义正确，颜色数组带 `bottom = middle` 兜底
- **HarmonyOS 字体引用**：`@font-face` 引用的 Regular/Bold ttf 均真实存在于 `frontend/public/fonts/harmonyos-sans-sc/`（含 LICENSE），与 newchat-design.module.css 的既有用法一致
- **MODEL_PROVIDER_LOGOS**（`const/modelConfig.ts` L130-140）：5 个 png 全部存在，silicon/siliconflow 双 key 兜底合理
- **版权头**：39 个改动的 ts/tsx 文件全部带 `Copyright (c) 2025-2026 Huawei` 头，单独 `fix(ci)` 提交补漏
- **真实在用的两个 ConfigModal**（agents 版）：0 中文残留，文案全部 `t()` 化

---

## 结论

| 项 | 结论 |
| --- | --- |
| 🔴 blocker | 1（B1 ParamDialog 中文默认值——紧接 #4084 之后引入同型问题） |
| 🟡 建议 | 4（S1 权限特判需确认、S2 locale 文案对照、S3 死代码+行为变更确认、S4 demo 清理） |
| ✅ 质量 | 发布弹窗迁移、路由修复、头像方案、版权头覆盖均到位 |

**建议**：修复 B1（一行改动，默认值改 `t()`）、S1 加决策注释后可合入。S3 的"切换智能体不再恢复会话"是需要产品确认的行为变化，建议在 PR 描述中显式声明。
