# PR #4155 业务场景视角检视

> head `57a0b3e5a`（已 rebase，与 develop 零领先）｜需求文档 `RESOURCE-TAG-TAB-20261020`
> 本文只从**业务场景**看：谁在什么情境下用这个功能、能不能用顺、有没有踩坑。

---

## 一、标签在业务里到底解决哪几件事

我沿着「谁用、用来干什么」把链路走了一遍，标签在业务上有**四个真实场景**，重要程度差别很大：

| # | 业务场景 | 谁用 | 实际价值 |
| --- | --- | --- | --- |
| 1 | **选资源时按标签筛选** | 所有建 Agent / 建 Skill 的人 | ⭐⭐⭐ 最高频 |
| 2 | **知识文档按标签过滤检索** | 知识库管理员 + 提问的用户 | ⭐⭐⭐ 直接影响答案质量 |
| 3 | **资源分类治理**（标记环境/密级/归属） | 管理员 | ⭐⭐ 中低频 |
| 4 | 标签字典维护本身 | 管理员 | ⭐ 极低频 |

### 场景 1：选资源时筛选（最高频）

在这条业务链上：用户要建一个 Agent，点「选工具/选 Skill/选知识库」，候选列表可能几十上百条。标签让他按「部门=研发部」「用途=合同审查」快速缩小。

我确认了 `useResourceTags.ts` L13-19 有个 `intersectAuthorizedIds`：**标签结果只与已授权集合求交集，绝不扩大可见范围**。业务上这意味着——标签不是权限系统，不能用来「发现」原本看不到的资源。这个边界划得很清楚，是对的。

### 场景 2：知识文档标签 → 影响检索结果（这个最容易被忽略）

我之前说「标签主要用于前端筛选」不够准确。查 `vectordatabase_app.py` L1164-1165：

```python
if payload.tag_predicates:
    search_kwargs["tag_predicates"] = payload.tag_predicates
result = ElasticSearchService.search_hybrid(**search_kwargs)
```

**标签会直接进入 ElasticSearch 混合检索做过滤**。业务含义是：文档被打上「密级=内部」后，检索时可以只在那批文档里找。这比「前端筛选」重要得多——它决定 Agent 答出来的内容范围。

还有 `document_tag_projection` 表（`db_models.py` L2612）是给 local / aidp 两个 provider 做标签同步的账本，带 `status`(`pending`/`synced`/`failed`/`unsupported`) 和 `retry_count`。说明**标签同步到检索引擎是个异步的、可能失败的过程**。

> ⚠️ **重点**：本次 PR **完全没碰后端**（`git diff --stat -- backend/` 为空），所以这条链路的安全性和正确性不在本次评审范围内。但业务上必须知道：**你在 Tags Tab 里改标签，到检索侧真正生效之间有个异步同步窗口**。PR 没有在 UI 上提示这个「同步中」状态。

### 场景 3 & 4：分类治理与字典维护

这是 Tags Tab 的主场，但业务频率很低——一个租户的标签体系基本定一次能用很久。

---

## 二、这次 PR 在业务上做对了什么

### ✅ 把「配置」和「使用」拆开了

原来的问题：你在「选工具」的抽屉里，看到一个「管理标签」按钮。这个按钮的业务含义很别扭——**我正在挑工具，为什么让我去改标签字典？**

改完之后职责清晰了：
- 选资源的地方 → 只筛选（`ResourceTagFilter` 保留）
- 配字典的地方 → 资源管理 → 租户 → Tags

这是对的产品判断。

### ✅ 租户隔离的业务处理很正

`TagList.tsx` L24-33，如果当前选中租户和登录用户租户不一致，直接显示提示而不是默默给空列表。

业务上这很重要：**管理员在资源管理页会切换多个租户查看**，如果在这里误操作别人的标签，后果比看到空表严重得多。提示文案 `tagManagement.currentTenantOnly` 也说得明白。

### ✅ 容量逼近有可视化

`TagDefinitionManagementPanel.tsx` L363-384 展示 `active_value_count/value_capacity`，L450 展示 `tagManagement.libraryCapacity`。业务上后端有硬限制（definition 100 / value 1000 / assignment 100，见 `library.py` L45/L50、`tag_management_db.py` L30），提前让管理员看到「快满了」比撞墙报错友好。

### ✅ 删除有后端兜底保护

`delete_definition`（`tag_management_db.py` L706-710）会先算 `active_value_count` 和 `active_usage_count`，**只要还被使用就拒绝删除**，抛 409。这是正确的业务保护——不会出现「删了标签，已有资源的标签凭空消失」。

---

## 三、业务场景上发现的问题

### 🟡 B1 — 「入口集中化」做了一半，业务上反而更容易迷路

PR 的立意是「把标签管理集中到资源管理页」。我对比了 PR 前后 `TagDefinitionManagementModal` 的使用点：

| | merge-base | PR head |
| --- | --- | --- |
| 使用文件数 | 7 | **6** |

只少了 1 个（`mcp-space/agent-space.tsx`）。**还剩下 5 处业务入口在弹标签定义管理弹窗**：

| 文件 | 业务场景 |
| --- | --- |
| `agent-info.tsx` L510 | 看 Agent 详情时改标签定义 |
| `SkillBuildModal.tsx` L1102 | 建 Skill 时改标签定义 |
| `DocumentList.tsx` L1758 | 文档列表打标签时改标签定义 |
| `KnowledgeBaseList.tsx` L1129 | 知识库列表打标签时改标签定义 |
| `McpServiceDetailModal.tsx` L1073 | MCP 服务详情改标签定义 |

这 5 处都挂在 `ResourceTagAssignmentModal` 的 `onManageDefinitions` 上——也就是「我正在给某个资源打标签，发现没有我要的标签，就地建一个」。

**业务后果**：管理员现在有**两条路**能到同一个标签定义表——从 Tags Tab 进，或从 5 个业务入口就地弹窗进。这比改之前更让人困惑，因为 PR 的描述让人以为只有一个入口了。

**我的判断**：这 5 个入口其实**有保留的合理性**（打标签时发现缺值就地补，是很顺的动线，硬跳去资源管理页反而打断流程）。但如果是这样，PR 的描述应该说清「集中化的是**浏览/管理**入口，就地补建保留」；如果本意是全集中，那这 5 处是漏改。

**建议**：先和产品确认意图。如果是「就地补建保留」，在 PR 描述里写明，避免后续又有人来"清理"；如果是漏改，`ResourceTagAssignmentModal` 的 `onManageDefinitions` 改成「引导跳转到 Tags Tab」。

### 🟡 B2 — 删除被拒绝时，用户看不懂为什么

后端 `delete_definition` 被拒时抛 `TagManagementConflictError`，`tag_management_app.py` L558-562 转成 409，detail 是 `{"message": ..., "details": {...}}`。

前端 `Panel.tsx` L184-186：

```tsx
catch (error) {
  message.error(error instanceof Error ? error.message : String(error));
}
```

`requestJson` 抛出的 message 大概率是 HTTP 层的通用文案（如 "Conflict" 或后端 message 的英文原文），**业务上用户看到的是「删不掉」，但不知道为什么删不掉、也不能知道影响多少个资源**。

而这个信息后端完全给得出来（`active_value_count` / `active_usage_count`）。

**更关键的是**：两个专门为这个场景准备的接口——`getDefinitionUsage`（`tagManagementService.ts` L112）和 `getValueUsage`（L166）——**全库没有任何地方调用**（我 grep 确认过，只有定义、没有消费）。说明本来设计上是要做「删除前告知影响面」的，但没做完。

**建议**（业务价值高、成本低）：
```tsx
const handleDeleteDefinition = async (definition) => {
  const usage = await tagManagementApi.getDefinitionUsage(bucketId, definition.definition_id);
  if (usage.active_value_count > 0 || usage.active_usage_count > 0) {
    message.error(t("tagManagement.error.inUse", {
      values: usage.active_value_count,
      resources: usage.active_usage_count,
    }));
    return;
  }
  // 继续删除...
};
```
至少让管理员知道「这个标签还被 12 个 Agent 用着」。

> 注：这个缺口**不是本 PR 引入的**（原 Modal 也没调 usage 接口），但 PR 正好在重写这块 UI，是补齐的最佳时机。

### 🟡 B3 — 改完标签，检索侧生效有延迟但 UI 不提示

场景 2 说到，文档标签要经 `document_tag_projection` 异步同步到 ES 才能影响检索。这个表有 `pending` / `failed` / `unsupported` 状态和重试机制，说明**同步会失败、会延迟**。

业务上：管理员给一批文档打了「密级=机密」，以为立刻就会被检索过滤，实际上**同步窗口内这些文档仍然可能被检索出来**。这是个合规风险场景。

前端有 `getProjectionStatus` 和 `getDocumentBatchStatus` 接口（`tagManagementService.ts` L251/L265），但 Tags Tab 里没有展示。

**建议**：至少在文档打标签成功后，如果返回 `pending`，提示一句「标签已保存，检索生效中」。如果涉及密级这类合规标签，这个提示是必须的。

### 🟡 B4 — 只读角色的体验没打磨

`TagList.tsx` L34-39 判定 `canManage`：SU / ADMIN / SPEED / ASSET_OWNER 四个角色。

业务上，`DEV` 和 `USER` 角色进来会看到完整的标签表格，但所有按钮都是 disabled。**问题是没有一句解释**——用户不知道自己为什么不能点，容易以为是 bug。

对比 `AgentList.tsx` L73 的做法：`canManageOfficialAgents = user?.role === USER_ROLES.SU`，至少在语义上明确。Tags Tab 建议在 `canManage=false` 时顶部加一行说明（如「当前角色仅可查看标签」）。

### 💭 B5 — 两个标签库的业务解释对用户不可见

`SYSTEM_BUCKET_KEYS = ("default_resource", "knowledge_content")`，库选择器显示的是 `t(\`tagManagement.libraries.${bucket_key}\`)`（`TagList.tsx` L108-110）。

业务上管理员需要理解「我在哪个库里干活」——`knowledge_content` 的标签影响文档检索，`default_resource` 的影响资源筛选。**选错库会白干**。目前只有库名，没有一句说明这个库管什么。

**建议**：在库选择器下面加一行描述，或者给 `Select` 的 option 加 `title` 说明适用范围。

---

## 四、业务场景下的几个疑问（想和作者确认）

1. **`knowledge_content` 库的标签能不能在 Tags Tab 里改？** 后端把两个库都返回给 `listLibraries`，`TagList` 也没过滤 `bucket_key`，所以管理员能在 Tags Tab 里直接改文档标签字典。但业务上文档标签是和 document 列表、检索投影强耦合的，在资源管理页改是否合适？

2. **跨租户场景**：`TagList` 阻止了跨租户操作，但 `KnowledgeBaseList.tsx` L1137 传的是 `canManage={true}` 硬编码。在同一页面体系里，这种不一致会不会让权限判断变得难以预测？

3. **标签总数上限 100 个 definition**：业务上够用吗？如果一个大租户要按「部门 × 密级 × 业务线」三个维度打标签，100 个 definition 可能偏紧。这不是本 PR 的问题，但容量设计的合理性值得产品确认。

---

## 五、结论

**从业务场景看，这个 PR 的方向是对的——把低频的「配置」从高频的「使用」路径里挪开。** 但它只完成了一半：5 个业务入口仍能弹同一个标签定义表，而 PR 描述让人以为已经集中。

按业务影响排序的建议：

| 优先级 | 事项 | 理由 |
| --- | --- | --- |
| **1** | 确认 B1 的意图：5 处「就地补建」是保留还是漏改 | 直接决定产品形态，也决定描述怎么写 |
| **2** | 补 B2：删除前调 `getDefinitionUsage` 告知影响面 | 后端接口已有、前端没接，误删风险高 |
| **3** | 补 B4：只读角色加一句说明 | 一行文案，避免被当 bug 报 |
| **4** | 补 B3：文档标签同步中的状态提示 | 涉及密级类合规标签时是必须的 |
| **5** | 补 B5：库选择器加业务说明 | 选错库会白干 |

**业务判定：可合入，但 B1 需要和产品对齐口径**（描述与实现不一致，会误导后续维护者）。
