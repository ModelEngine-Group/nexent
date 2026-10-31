# PR #4155 新增的「标签」是什么，有什么用

> PR: https://github.com/ModelEngine-Group/nexent/pull/4155
> head `57a0b3e5a`（已 rebase 到 develop `41bc7efd0`）｜需求文档 `RESOURCE-TAG-TAB-20261020`

---

## 一句话结论

**标签不是这次新造的概念，而是把原本散落在 5 个地方的「标签管理入口」收拢成资源管理页里的一个 Tags Tab。**

标签本身是一套**租户级的受控分类体系**：管理员预先定义「标签维度 + 可选值」，然后给 Agent / Skill / Tool / MCP / 知识库 / 知识文档打上标签，**用来在资源选择器里做筛选**。这次 PR 只搬家和重写 UI，后端表结构、API 契约都没动。

---

## 一、标签到底是什么（数据模型）

后端三张表，租户隔离，全部软删除（`delete_flag`）：

| 表 | 含义 | 关键字段 |
| --- | --- | --- |
| `tag_bucket` | **标签库**（一个租户一组固定库） | `bucket_key`、`bucket_name`、`status` |
| `tag_definition` | **标签维度/键**（如「部门」「数据敏感度」） | `definition_name`、`selection_mode`、`sort_order`、`status` |
| `tag_value` | **标签值**（该维度下的可选项，如「研发部」「机密」） | `display_value`、`normalized_value`、`status` |
| `resource_tag_assignment` | **资源 ↔ 标签值 的绑定** | `resource_type`、`resource_id`、`definition_id`、`value_id` |

`selection_mode` 有三档：`single_select`（单选）、`multi_select`（多选）、`no_value`（纯标记，不带值）。

`resource_type` 支持 6 类：
`agent`、`skill`、`tool`、`mcp_service`、`knowledge_base`、`knowledge_document`

### 两个内置标签库

`bucket_key` 只有两个取值（`backend/consts/model.py` L296、`tag_management_db.py` L26 `SYSTEM_BUCKET_KEYS`）：

- **`default_resource`** —— 资源类标签（Agent / Skill / Tool / MCP / 知识库）
- **`knowledge_content`** —— 知识文档内容类标签

这不是用户随便建的，是系统预置的固定库。

---

## 二、标签解决什么问题

### 2.1 核心用途：资源选择器里的筛选

这是标签最大的价值。工作台/Agent 配置里选资源时，候选列表可能很长，标签让你按维度快速缩小范围。

调用链：
```
ResourceTagFilter（筛选 UI）
  → useResourceTags / useResourceTagFilter（hook 管状态）
  → tagManagementApi.filterResourceIds(resourceType, resourceIds, predicates)
  → POST /tag/assignments/{resourceType}/filter
  → 返回同时满足所有 predicate 的资源 id 子集
```

注意接口注释里这句（`tagManagementService.ts` L305-309）：

> Narrow an already-authorized non-document resource id set by tag predicates. The caller must supply ids its own list flow has already authorized; **the service only intersects that set**.

**安全设计**：标签只做「求交集」，永远不会扩大可见范围。你本来看不到的资源，不能通过标签筛出来。这个约束写得挺清楚。

实际接入筛选的界面：
- `AgentPicker.tsx` L103/L109（选 Agent，分「我的」和「资源库」两套标签）
- `SkillPicker.tsx` L96/L102（选 Skill，同样两套）
- `conversation-knowledge-scope-modal.tsx` L966/L1081（对话里选知识范围）
- `AgentDrawer` / `KnowledgeDrawer`（资源抽屉）

### 2.2 次要用途：分类与治理

- 管理员在资源管理页维护标签字典（谁能建、建哪些值）
- 给资源打标签本身也是一种元数据治理——比如标记「生产环境」「已审核」「机密度」
- 知识文档的标签还会同步到检索侧（`document_tag_projection` 表是给 AIDP/local 做投影的账本），影响文档级筛选

---

## 三、这次 PR 具体做了什么

### 3.1 新增：一个 Tags Tab

位置：**资源管理 → 选中租户 → Tabs 里的 `tags` 项**（`UserManageComp.tsx` L1401-1405）

```tsx
{
  key: "tags",
  label: t("tenantResources.tabs.tags"),
  children: <TagList tenantId={tenantId} />,
}
```

排在 Agents、MCP、Skills 之后，Invitations 之前。

新增文件 `TagList.tsx`（116 行）职责很薄，是个**壳**：
1. 校验当前租户一致性（标签 API 从鉴权取租户，不接受前端传租户参数）
2. 算 `canManage`（SU / ADMIN / SPEED / ASSET_OWNER 才可写）
3. 加载标签库列表，渲染一个库选择器（`Select`）
4. 把 `bucketId` 传给 `TagDefinitionManagementPanel`

默认库优先选 `default_resource`，没有则退第一个。

### 3.2 重构：Modal 拆成 Panel + 壳

| 文件 | 变化 |
| --- | --- |
| `TagDefinitionManagementModal.tsx` | **−609 行**，只剩 45 行壳（`<Modal>` 包 `<Panel>` + `destroyOnHidden` + `key={bucketId}`） |
| `TagDefinitionManagementPanel.tsx` | **新增 641 行**，承载全部逻辑 |
| `ResourceTagManagementModal.tsx` | **删除整文件（−91 行）** |

**抽取动机很合理**：同一套「标签定义 + 值」的增删改查表格，现在有两个使用场景——弹窗（编辑 Agent 时弹）和 Tab（资源管理页内联）。抽成 Panel 后两边共用，不用维护两份。

Modal 层用 `destroyOnHidden` + `key={bucketId}` 承担了原来 `useEffect(!open → reset)` 的职责。

### 3.3 移除：5 处入口被清掉

这是 PR 的核心意图——**「入口集中化」**：

| 被移除的入口 | 位置 |
| --- | --- |
| Agent 资源选择器里的「管理标签」 | `ToolDrawer` 的 `onOpenManageLabels` |
| Agent Skill 选择器里的标签管理 | `SkillDrawer` 的 `enableTagManagement` |
| 知识库目录工具栏的标签管理 | `KnowledgeBaseList` |
| My MCP 工具栏的标签管理 | `mcp-space/agent-space.tsx` |
| `ResourceTagManagementModal`（批量打标签弹窗） | 整个文件删除 |

同时 `LabelManagementModal` 也不再被 `agent-capability.tsx` 引用。

**理由**：标签管理是低频的配置动作，散在各个选择器里会造成「入口到处都是、职责不清」。收拢到资源管理页后：选资源的地方只管选，配标签的地方只管配。

### 3.4 顺手修的 4 个缺陷

PR 里带了 4 个 bug 记录 yaml，都是这次碰到的：

- `EVALUATOR-GENERATE-LAYOUT` —— 评估器生成区布局
- `KB-CARD-MENU` —— 知识库卡片菜单
- `KB-MODAL-MASK` —— 弹窗遮罩（`maskClosable` → antd 6 的 `mask`）
- `TENANT-MODEL-SPACING` —— 租户模型页间距

---

## 四、对用户的实际变化

**如果你是普通用户**：几乎无感。选 Agent/Skill 时**标签筛选功能还在**（`ResourceTagFilter` 没动），只是不能再从选择器里跳去「管理标签定义」了。

**如果你是管理员（SU/ADMIN/SPEED/ASSET_OWNER）**：
- 原来：在 5 个不同地方想改标签就改
- 现在：统一到 **资源管理 → 租户 → Tags**，选库 → 维护维度与值

**如果你只有只读权限**：Tags Tab 能看到但不能改（`canManage=false` 时按钮禁用）。

---

## 五、几点值得留意的设计

✅ **做得好的**

1. **租户隔离的态度很正**：`TagList` L24-33 直接拒绝跨租户外加显示提示，而不是默默返回空数据。注释也写明了「Tag APIs resolve the tenant from authentication, not a request parameter」——后端从 token 取租户，不接受前端传参，这是对的做法。
2. **筛选的安全边界写清楚了**：`filterResourceIds` 的注释明确说了只求交集、不扩大授权范围。
3. **Panel 抽取干净**：Modal 变壳、`destroyOnHidden` 接管重置职责，能力零丢失（创建/更新/启停/置顶/删除维度 + 值的增改删 + 分页/搜索都保留了）。
4. **有需求文档 + 4 个缺陷记录 + 271 行新测试**（`tagLibraryManagement.test.tsx`），配套完整。

⚠️ **值得注意的**

1. **`ResourceTagManagementModal` 被删，但打标签能力没丢**。我核对过：它原本只在 `KnowledgeDrawer`（L558）和 `SkillDrawer`（L610）里被引用，作用是「在抽屉里列一个资源表格，逐个点管理标签」。真正执行打标签的 `ResourceTagAssignmentModal` 完好保留，且在 5 处仍在使用（`DocumentList` L1769、`KnowledgeBaseList` L1139、`agent-info` L498、`MineApplyListingModal` L437、`SkillBuildModal` L1088）。被删的只是「抽屉内的批量入口」，不是能力本身——符合「入口集中化」的意图，不算回退。
2. **`TagList.tsx` 里那个提前 `return` 在 `useState`/`useQuery` 之前**——虽然 `if` 分支里没有 hook 调用所以不违反 Hooks 规则，但这是很脆弱的写法。将来有人在 `if` 前加个 `useMemo` 就炸了。建议把租户校验提到外层组件（拆成 `TagList` = 校验 + `TenantTagList` = 渲染，其实代码里已经这么分了，但校验放在了外层组件的 return 里，可以再往上提一层）。
3. **两个标签库的选择器是「软」的**：`library` 的回退逻辑是 `selectedLibraryId → default_resource → libraries[0]`，用户切换后如果库列表刷新导致选中项消失，会静默跳回默认库，没有提示。

---

## 六、如果只记三句话

1. **标签 = 租户级的受控分类字典（维度 + 值）+ 资源绑定**，核心用途是**资源选择器里按标签筛选**，共 6 类资源可打标签。
2. **这次 PR 不是新增标签能力，而是把标签管理入口从 5 处收拢到资源管理页的 Tags Tab**，顺带把 609 行的 Modal 拆成可复用的 Panel（Modal 只剩 45 行壳）。
3. **筛选功能不受影响**，受影响的是「管理标签定义」的入口位置——统一到一处了。
