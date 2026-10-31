# PR #4058 功能向评审（聚焦影响行为的部分）

> 配合此前的代码规范评审（review-pr-4058.md）使用，本文只列**影响功能**的发现。

---

## 🔴 P1 — 会静默失效的用户可见功能

### 1. Composer 技能选择是纯视觉 mock，用户操作不生效

`composer.tsx:540-541`：

```ts
// TODO(mock): skill selection remains visual until skill scope APIs are wired.
const [selectedSkillNames, setSelectehttps://github.com/ModelEngine-Group/nexent/pull/4058/changes#diff-71291fd4b5c5051ea779f7c38b4b342b505f515489ecf65e67adcffc30f05ee6dSkillNames] = useState<string[]>([]);
```

新聊天输入框的 "+" → Skill 面板：用户可以搜索、点选技能，选中项显示为 chips（`composer.tsx:831-851`），但 `selectedSkillNames` **只用于渲染**——`setRunConfig`（page.tsx:592-631）只携带 `agentId`/`knowledgeScope`/`runtimeMetadata`，从不包含技能。用户选完技能发消息，技能完全不参与执行，且无任何提示。  
**问题**：这是要正式上线的新 UI，还是设计稿占位？若上线，建议在 API 就绪前禁用交互或显示"即将支持"，否则用户会以为技能已生效。

### 2. Agent 创建模板硬编码 4 个医疗 demo 模板，且描述会真实持久化

`agentCreationTemplates.ts:9-11` 自述：

```ts
/**
 * Temporary frontend-only template metadata for the creation modal.
 * Replace this catalog with the repository API when a template contract is available.
 */
```

4 个模板全部是医疗场景（心肌病筛查助手、用药安全顾问、体检报告解读师、医学文献速读员）。`CreateAgentModal.tsx` 中选中模板后 `description: selectedTemplate ? t(selectedTemplate.descriptionKey) : ""` —— **模板描述会写进真实 agent 记录**。  
**问题**：通用开源产品里向所有用户默认展示医疗 demo 模板是否是产品意图？"Temporary" 注释表明作者自己也认为需要换掉，建议明确上线前是否保留。

---

## 🟡 P2 — 行为变化 / 回归风险

### 3. AddAgentDrawer「取消全选」清空范围过大，与 AddToolDrawer 行为不一致

`AddAgentDrawer.tsx:342-349`：

```ts
const handleSelectAll = (checked: boolean) => {
  const ids = filteredAgents.map((item) => Number(item.id));
  if (activeSource === "internal") {
    applyInternalSelection(checked ? ids : []);   // 取消 = 清空全部 internal
```

而 `AddToolDrawer.tsx:455-465` 的 `deselectAllVisibleTools` 只移除**当前筛选结果**内的工具。协作者抽屉里用户先筛选过再点"取消全选"，会连同筛选外的既有选择一起清掉（`updateSubAgentIds([])` 同时清空 `sub_agent_relations`），无确认。

### 4. 外部协作者（A2A）选择即时产生后端副作用，与内部协作者语义不同

`AddAgentDrawer.tsx:285-305`：`setExternalSelection` 在每次 toggle 时立即调用 `a2aClientService.addRelation/removeRelation`（`Promise.all` 逐个发）。同一抽屉里：

- 内部协作者 → 本地 store，随 agent 保存统一提交，可撤销
- 外部协作者 → 点击瞬间写后端，无确认、无失败回滚（失败只 toast，选择状态不回滚——`results.some(!success)` 时 return，但 UI 的 CheckMark 状态依赖 store，实际上 external ids 未更新所以视觉不勾选，行为勉强自洽但用户看到报错原因不明）

**建议**：至少统一为"确认时提交"，或给外部关系操作加二次确认。

### 5. 切换 agent 时的会话恢复可能触发逐页全量拉取

`thread-agent-registry.ts:57-109`：`resumeLatestAgentConversation` 的 `while (true)` 循环——若目标 agent 的会话不在已加载页（首页 30 条），会不断 `loadMore()`（每页 `CONVERSATION_PAGE_SIZE`）直到找到或拉完。会话数多的用户每次切换 agent 都可能发起 N 次列表请求。有终止条件（无进展即 break）不会死循环，但建议加上限（如最多加载 5 页）或在后端提供按 agent 过滤的会话查询。

### 6. 无历史用户在聊天页失去 agent 切换入口

`agent-selector-dropdown.tsx:90-92`：

```ts
if (isLoading || !lastUsedAgent) {
  return null;
}
```

顶部 agent 选择器只展示「有过会话的 agent」，全新用户（或清空历史的用户）在聊天界面顶部完全没有切换 agent 的下拉，必须返回 landing 页。确认这是设计意图还是遗漏——设计稿通常会有"全部 agent"入口。

### 7. `useSkillList` 用中文值判断官方技能，数据契约脆弱

`useSkillList.ts:7-10`：`source === "official" || source === "官方"`。后端 skill source 实际取值混杂（`"official"`、`"custom"`、默认 `"导入"`——见 `backend/management/services/skill/service.py:358,1154`）。前端每遇到一个中文值就加白名单，建议推动后端把 source 归一为枚举，前端只认 `official`。

---

## 🔵 P3 — 边缘场景

1. **置顶会话持久化键易失效**：`thread-list.tsx:107` 用 assistant-ui 客户端 thread id 存 `localStorage`（`chat.pinnedThreadIds`），对话删除/环境迁移后残留死 id，且多端不同步。建议改用 server conversation id。
2. **`thread-agent-registry.ts` 模块级 `overrides`/`activityTimes` Map 永不清理**——条目有限可接受，建议注释说明。
3. **`agent-groups.tsx` 含硬编码医疗 demo 数据**（"体检报告解读师"、"对话对话对话对话……"占位文案），已验证**当前无任何渲染调用**（纯死代码），但这类 demo 内容留在代码里有被误接线的风险，建议删除或移到测试 fixtures。

---

## ✅ 已专门验证、确认无回归的（可放心）

| 疑点                                              | 验证结果                                                                                                                                                                                                     |
| ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 「更新时间」列是否有真实数据                                  | ✅ `AgentInfo` 继承 `TableBase`（`db_models.py:50` 自带 `update_time` + `onupdate`），`/agent/list/page` → `list_agent_page_impl` → `query_agent_info_by_ids`（`as_dict` 全字段）→ 前端 `formatAgentListItem` 透传，数据链路完整 |
| 知识检索参数配置是否丢失                                    | ✅ 从旧 `conversation-knowledge-scope-modal` 完整迁到 composer（`retrievalConfigOpen` + `KnowledgeRetrievalParamsForm` @ composer.tsx:1716，含保存与 embedding 校验），旧入口删除无残留                                           |
| AddKnowledgeDrawer 的 embedding 兼容校验是否比旧 modal 弱 | ✅ 对等。旧 `KnowledgeBaseSelectorModal` 的调用方（knowledge-base-search.tsx）在 develop 上就没传 `currentEmbeddingModel` 等参数（默认 null），新抽屉同样支持受控传入                                                                       |
| 旧 modal 的 onSync 与新抽屉 onRefresh 是否等价            | ✅ 旧：`onSync={async () => { await state.refetch(); }}`，新：`onRefresh={() => void state.refetch()}`，行为一致                                                                                                    |
| CreateAgentModal 重复提交                           | ✅ 本 PR 还加了 `isSubmitting` 防重（改进）                                                                                                                                                                         |
| 知识域随会话切换恢复                                      | ✅ `knowledgeScopesRef` 按 thread 缓存 + `conversationService.getById` 恢复，与 develop 逻辑一致                                                                                                                     |
| 流式对话中断后重连                                       | ✅ `resumedConversationIdsRef` 防重入 + `resumeRun` 逻辑保留                                                                                                                                                     |
| `update_time` 缺失时是否误回退 `create_time`            | ✅ `formatAgentUpdateTime` 只认 `update_time`，缺失显示 "-"，符合 case 断言（AGENT-LIST-D1-001 明确禁止回退）                                                                                                                 |

---

## 覆盖范围说明

深入读了：newchat 页面主流程（agent 绑定/会话恢复/知识域/runConfig）、composer（KB/技能/检索参数）、thread-list（分组/批量删/置顶）、thread-agent-registry、AddAgentDrawer、AddKnowledgeDrawer、AddToolDrawer、WorkbenchPage 资源挂载、CreateAgentModal、agent-list-table 数据链路（前端到后端 DB）。

未逐行覆盖：agent-prompt.tsx（+665）、agent-info.tsx（+404）、agent-debug.tsx、compare-panel、thread.tsx 消息渲染细节（+370）。这些如有需要可补检。
