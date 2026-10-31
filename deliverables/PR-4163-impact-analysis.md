# PR #4163 变更影响分析报告

> https://github.com/ModelEngine-Group/nexent/pull/4163
> head `31e3fb09c`｜develop `0436d6570`（**drift 0，已含 develop 最新**）
> 标题 `Fix/agent prompt limit 100000`｜作者 lijiayang619
> 分析方式：code-diff-analyzer（Step1-7）+ fast-code-path（链路追踪）+ map-project-change-impact（依赖图）
> 分析时间：2026-10-22

---

## 一、版本方向核查

| 项 | 值 |
| --- | --- |
| 对比基准 | `0436d6570`（develop HEAD） |
| 目标 HEAD | `31e3fb09c`（PR head） |
| 方向 | ✅ 正常前进（develop → PR），**无版本回退** |
| 文件/行数 | 13 文件 **+431 / −29** |
| commit 数 | 5 个功能提交 + 1 个 merge |
| 后端改动 | **0 文件**（纯前端 PR） |

**⚠️ PR 标题严重不匹配内容**：标题只说「prompt limit 100000」，实际包含 **5 个互不相关的修复**，横跨 Agent 配置、模型管理、会话建议三个业务域。评审者仅看标题会严重低估范围（这正是本次影响分析的价值所在）。

### 5 个 commit 与真实内容

| Commit | 消息声称 | 实际改动 |
| --- | --- | --- |
| `b7fe554e8` | raise agent prompt length limit from 1000 to 100000 | 3 处 `limit={1000}` → `limit={100000}` |
| `93209b990` | skip blank preset questions in chat and debug suggestions | 2 处空白过滤 |
| `e0c64736f` | use the single-page edit dialog for tenant model edits | ModelList 编辑切到 `ModelEditDialog` |
| `d6d126c1e` | use the v0 add dialog for tenant model creation | ModelList 新增切到 v0 `ModelAddDialog` |
| `0048d6bf0` | stop superseded connectivity probes from sticking in detecting | `updateModelStatus` 移入 timer 回调 |

---

## 二、风险等级（脚本判定，非人工估）

按技能要求走 `scripts/scoring.py` 的 `rate_change()`（rules v1.1）：

| 口径 | 评级 | 命中规则 |
| --- | --- | --- |
| **全部 13 文件**（含 5 个测试） | 🔴 **高** | R3 变更规模大（>400 行 或 >10 文件） |
| **仅 8 个业务文件** | 🟡 **中** | R5 变更规模中等（>150 行 或 >5 文件） |

**上下文补充（不覆盖脚本结论）**：脚本命中的 R3 主要来自测试文件（+412 行中 400 行是测试）。纯业务代码 8 文件、+119/−26，实际风险应看 🟡 中。但**业务改动横跨 3 个域 + 触及模型管理这一核心配置面**，建议按 🟡 偏高处理。

> 未命中 R1（认证/权限/支付）与 R2（数据格式/契约变更）——见 5b 专项校验第 1 项的解释。

---

## 三、变更总览

| # | 文件 | 增/删 | 类型 | 说明 | 风险 |
| --- | --- | --- | --- | --- | --- |
| 1 | `agents/[agentId]/components/HighFidelityPromptEditModal.tsx` | +3/−1 | 变更 | `limit` 1000→100000 + 补版权头 | 🟢 |
| 2 | `agents/[agentId]/components/agent-prompt.tsx` | +2/−2 | 变更 | 2 处 `limit` 1000→100000 | 🟢 |
| 3 | `agents/[agentId]/components/debug/agent-debug-welcome.tsx` | +3/−2 | 变更 | 过滤空白 `example_questions` | 🟢 |
| 4 | `models/components/model/ModelEditDialog.tsx` | +18/−1 | **混合** | 新增 `tenantId` prop + 路由到 manage 端点 | 🟡 |
| 5 | `models/components/modelConfig.tsx` | +6/−1 | **变更** | `updateModelStatus(CHECKING)` 移入 timer 回调 | 🟡 |
| 6 | `newchat/assistant-ui/thread.tsx` | +8/−5 | 变更 | 过滤空白后 slice(0,4) | 🟢 |
| 7 | `resource-manage/.../ModelList.tsx` | +6/−17 | **变更** | 编辑切 `ModelEditDialog`，新增切 v0 `ModelAddDialog` | 🟡 |
| 8 | `services/modelService.ts` | +5/−0 | **新增** | `type?: ModelType` → `model_type` 透传 | 🟡 |
| 9-13 | 5 个测试文件 | +412/−5 | 新增 | 见第六节 | 🟢 |

---

## 四、代码链路追踪（fast-code-path）

### 4.1 链路 A：Prompt 长度上限

| 步骤 | 代码位置 | 职责 | 输入/输出变化 | 确信度 |
| --- | --- | --- | --- | --- |
| 1 | `agent-prompt.tsx` L814 / L907 | 渲染 2 个 prompt 输入框 | `limit` 1000 → 100000 | 已确认 |
| 2 | `HighFidelityPromptEditModal.tsx` L56 | 弹窗内 prompt 编辑 | `limit` 1000 → 100000 | 已确认 |
| 3 | `HighFidelityTextArea.tsx` L26 | `maxLength={value.length > limit ? undefined : limit}` | 依赖 limit 做截断门控 | 已确认 |
| 4 | 后端 `duty_prompt: Optional[str] = None` | **无任何长度校验** | 无变化 | 已确认 |

**结论**：1000 是**纯前端限制**，后端从不校验长度。提高上限不会触发后端拒绝，也不会改数据结构。**风险极低**。

**改动完整性 ✅**：全库 grep `limit={1000}` 已归零，3 处全部覆盖，无遗漏。

### 4.2 链路 B：模型编辑的 `model_type` 透传（最需关注）

这是本次唯一深入到后端契约的改动，逐环核对：

| 步骤 | 代码位置 | 职责 | 输入/输出变化 | 确信度 |
| --- | --- | --- | --- | --- |
| 1 | `ModelEditDialog.tsx` L268-270 | `if (typeChanged) params.type = type` | **仅类型变更时才带 type** | 已确认 |
| 2 | `ModelEditDialog.tsx` L328-335 | `if (tenantId)` 走 manage，否则走 single | 路由分支 | 已确认 |
| 3 | `modelService.ts` L1412 | `...(params.type !== undefined ? { model_type: params.type } : {})` | 条件展开，不污染其他请求 | 已确认 |
| 4 | 后端 `ManageTenantModelUpdateRequest` L2232 | `model_type: Optional[str]` | **字段既有，PR 未改后端** | 已确认 |
| 5 | `management.py` L823 | 单条路径 `update_data = {k:v ... if k != "model_id"}` | **model_type 保留 → 真能改类型** | 已确认 |
| 6 | `management.py` L810-814 | multi_embedding 路径显式排除 `model_type` | **一对记录保持原类型** | 已确认 |

**结论：契约完全对齐，PR 注释准确。** 尤其第 6 步——`multi_embedding` 是一对记录（embedding + multi_embedding），若允许改类型会破坏这对关系，代码显式剥离是正确的保护。

### 4.3 链路 C：连通性检测的 CHECKING 状态时机

| 步骤 | 代码位置 | 职责 | 副作用 | 确信度 |
| --- | --- | --- | --- | --- |
| 1 | `modelConfig.tsx` L756 | 清除上一个 timer | 取消未发出的探测 | 已确认 |
| 2 | L757-758 | 新 timer 触发时才设 `CHECKING` | 状态与请求同生共死 | 已确认 |
| 3 | L764-774 | 成功/失败设置最终状态 | 不会停留 CHECKING | 已确认 |
| 4 | `updateModelStatus` L933-945 | 按 `displayName + modelType` 定位行 | 行级状态 | 已确认 |

**修复原理正确**：旧代码在 timer **外**设 CHECKING，被 `clearTimeout` 取消的那次点击会留下永久 CHECKING（该行按钮此时 disabled，无法自救）。移到 timer 内后，只有真正发出请求才置 CHECKING。

**⚠️ 但引入一个新边界（见 5.2）**。

### 4.4 链路 D：空白 example_questions 过滤

| 步骤 | 代码位置 | 变化 | 确信度 |
| --- | --- | --- | --- |
| 1 | `thread.tsx` L784-786 | `.filter(q => q.trim()).slice(0,4)` | 已确认 |
| 2 | `agent-debug-welcome.tsx` L80-81 | `visibleQuestions = questions?.filter(q => q.trim())` | 已确认 |

两处**实现一致**（都用 `.trim()` 真值判断），逻辑正确。

**⚠️ 但存在漏网点（见 5.3）**。

---

## 五、发现的问题（按严重程度）

### ⚠️ M1（已更正）— 原判「能力降级」不成立，v0 实际上更严格

> **本节于 2026-10-22 11:45 更正**。原判断基于 `ModelAddDialog.tsx` L70-73 的类注释，但该注释已过期。重新逐项核实 UI 后结论相反。详见 `PR-4163-scenario-correction.md`。

**位置**：`ModelList.tsx` L542-547

PR 把新增对话框从 `ModelAddDialogV2` 换成 `ModelAddDialog`（v0）。我最初据 L70-73 注释判定"三项能力全丢"，**实际核实后三项全部保留**：

| 能力 | 原判断 | **实际** | 证据 |
| --- | --- | --- | --- |
| 高级参数设置 | ❌ | ✅ | v0 L738「高级设置」按钮 → L791 `RowSettingsDialog` → L1547 复用 `ModelAdvancedConfig`（容量+推理） |
| 提交前连通性探测 | ❌ | ✅ **且强制** | 单个 L519 `if (probe !== "available")`；批量 L1049 `rowCheck !== "available"` |
| 批量逐行参数编辑 | ❌ | ✅ | L827 `RowOverride{displayName, settings}` + L855 `rowOverrides` + L1097 `applyAdvancedSettingsToParams` |

**决定性证据**：`ModelAdvancedSettings.tsx` L207-210 注释明确写 —— *"Shared by ModelAdvancedSettings and the v0 ModelAdvancedConfig so **the two dialogs render identical controls**"*。

L70-73 那段 "Deliberately simple: no per-row capacity or inference-param editing and no pre-submit connectivity gate" 是**过期注释**：代码后来补齐了这些能力，注释没跟着改。

**真正的行为变化（降级为 💭）**：v0 单个添加**强制要求先探测通过才能提交**（L519-526，否则弹「请先通过连通性检测再添加模型」）。管理员对已知可连通的模型（如内部部署）也要多点一次检测。这不算能力缺失，但是**静默的行为变更，PR 描述完全没提**。

**建议**：在描述里补一句说明；或提供"跳过检测"逃生口。

### 🟡 M2 — 共享 timer 会丢弃**跨行**的点击

**位置**：`modelConfig.tsx` L756-758

修复把 CHECKING 移进 timer 是对的，但共享单一 `throttleTimerRef` 带来新的边界：

```
t=0     点 A 行 → 设 timer1
t=0.3s  点 B 行 → clearTimeout(timer1)  → A 的探测被静默取消
t=1.3s  只有 B 行被探测
```

**用户可感知的后果**：快速连点两行，第一行的"检测连通性"看起来毫无反应（既不转圈也不出结果），只能再点一次。旧代码至少会留下 CHECKING 状态（虽然是 bug），现在变成**完全无反馈**。

**建议**（二选一）：
- **按行独立 timer**：`Map<string, Timeout>`，key 用 `${displayName}::${modelType}`，各行的防抖互不干扰。这是最贴合业务语义的做法——用户想同时检测多行是合理诉求。
- **保留共享 timer，但立刻给被取消的行设回原状态**，或在 UI 上提示"检测已排队"。

代码注释只解释了"被取消的点击不能留 CHECKING"，没说明"跨行点击会被丢弃是有意设计"。如果是刻意的（避免并发探测打爆后端），建议在注释里写明这个权衡。

### 🟡 M3 — `welcomeSuggestions` 分支未过滤空白（本次修复的漏网点）

**位置**：`thread.tsx` L782-783

```tsx
const suggestions = welcomeSuggestions?.length
  ? welcomeSuggestions.slice(0, 4)        // ← 这个分支没有 filter
  : (agent.example_questions || [])
      .filter((question) => question.trim())   // ← 只修了 else 分支
      .slice(0, 4)
```

`welcomeSuggestions` 来自 `nl2agent-chat-panel.tsx` L161-176 的 `t(suggestion.titleKey)` 映射。正常情况这些是静态常量，不会有空白。**但一旦某个 i18n key 缺失，`t()` 会返回空串**，此时空白建议会照常渲染。

**这不是本 PR 引入的 bug**（原来也没过滤），但 PR 的立意是"skip blank preset questions"，只修了一半分支。补一行成本极低：

```tsx
? welcomeSuggestions.filter((s) => s.title?.trim() || s.prompt?.trim()).slice(0, 4)
```

### 🟡 M4 — prompt 上限改动**零测试覆盖**

5 个修复里有 4 个带测试（ModelEditDialog 3 个、ModelAddDialog 2 个、modelConfigVerify 2 个、AgentDebugWelcome 5 个），**唯独 `limit` 1000→100000 没有任何测试**。

我 grep 全库 `frontend/tests/` 下的 `100000`，只有一处无关命中（`knowledgeBaseViewport.test.ts` 里的分页参数）。

**风险**：这个值改回 1000 或改成别的数字，CI 全绿。虽然改动本身简单，但它是本 PR 的标题诉求，应该是**最该被锁定**的一条。

**建议**（一行断言即可）：
```tsx
// agentSinglePrompt.test.tsx 已有该组件的渲染测试
expect(textarea).toHaveAttribute("maxlength", "100000");
```

### 💭 L1 — `connectStatus` 在租户编辑路径仍然丢失（存量，但值得在本 PR 记一笔）

`ModelEditDialog` L271-277 会设置 `params.connectStatus`（探测通过 → `"available"`，改身份 → `"not_detected"`），但 `updateManageTenantModel`（L1362-1394）的参数类型里**根本没有 `connectStatus`**，请求体也不发 `connect_status`。

因此租户管理员编辑模型后，行状态**不会随保存更新**。PR 描述自己承认了这点：

> `connect_status` 不在 `/model/manage/update` 请求模型内：编辑改类型/名称后行状态沿用旧值，由行内「检测连通性」刷新；后端 consts/model.py 加一个可选字段即可完全对齐，如需可跟进

**判断**：这是**存量问题**（旧的 `ModelAddDialogV2` 编辑路径同样走 manage 端点，同样丢 connectStatus），不是本 PR 引入。但既然本 PR 正好在改这段，且描述已经诊断清楚，建议顺手补——后端加一个 `connect_status: Optional[str]` 字段即可，改动约 3 行。

### 💭 L2 — V2 两个文件成为彻底的孤儿代码

全库确认 `ModelAddDialogV2` / `ModelEditDialogV2` **已无任何调用方**（只剩注释里的引用）。两个文件体积不小（V2 各自数百行），留着会让下一个人困惑"该用哪个"。

PR 描述也提到了这点：*"ModelAddDialogV2 / ModelEditDialogV2 现全仓库无调用方，可另行清理"*。建议单开一个清理提交，或在本 PR 里删掉。

---

## 六、测试验证（实测）

在独立 worktree 上实跑，**未污染主仓库**：

```
npx vitest run tests/component/modelEditDialog.test.tsx \
               tests/component/modelAddDialog.test.tsx \
               tests/component/modelConfigVerify.test.tsx
→ Test Files  3 passed (3)
  Tests       7 passed (7)

npx vitest run --config vitest.workbench.config.ts \
               tests/workbench/AgentDebugWelcome.test.tsx
→ Test Files  1 passed (1)
  Tests       5 passed (5)
```

### 反向验证（确认测试不是摆设）

| 实验 | 操作 | 结果 |
| --- | --- | --- |
| 1 | 把 `updateModelStatus(CHECKING)` 移回 timer 外（还原旧 bug） | ✅ `keeps a superseded row probe from sticking` **失败** |
| 2 | 删掉 `ModelEditDialog` 的 `tenantId` 分支（全走 single） | ✅ 2 个用例**失败**（routing + no-type） |

**结论：这两组测试真实有效**，能捕获原始 bug 的回归。

### 测试覆盖矩阵

| 修复 | 测试 | 质量评价 |
| --- | --- | --- |
| 1. prompt limit | ❌ **无** | 见 M4 |
| 2. ModelEditDialog 路由 | ✅ modelEditDialog.test.tsx (3) | 优秀：覆盖 tenant/single 分支 + type 有无 |
| 3. 空白问题过滤 | ✅ AgentDebugWelcome.test.tsx (5) | 良：覆盖组合场景 |
| 4. stuck detecting | ✅ modelConfigVerify.test.tsx (2) | 优秀：含跨行 supersede + 同列 collapse |
| 5. v0 add dialog | ✅ modelAddDialog.test.tsx (2) | 良：覆盖 tenant/manage 与 personal 路由 |

---

## 七、专项检测结果（Step 5b）

| 检测项 | 结果 | 说明 |
| --- | --- | --- |
| **1. 数据格式变更** | ⚠️ 有（轻） | `modelService` 请求体新增可选 `model_type` 字段。**后端字段既有**（`consts/model.py` L2232，PR 未改后端），条件展开保证 `undefined` 时不发送，**向后兼容**。无 schema 迁移。 |
| **2. 版本回退** | ✅ 无 | 5 个 fix commit，无 Revert |
| **3. 敏感信息泄露** | ✅ 无 | 全 diff 扫描 password/secret/token/private key，零命中 |
| **4. 测试同步** | ⚠️ 部分 | 4/5 有测试，**prompt limit 无测试**（M4） |
| **5. 循环依赖** | ✅ 无 | `modelService` ← `ModelEditDialog` ← `ModelList`，单向无环 |

---

## 八、影响范围（map-project-change-impact 依赖图）

脚本 `impact_graph.py` 执行成功（exit 0），`outside_known_paths: []` 表示所有受影响节点都在已知路径内。

### 直接改动（8 个）

`C_P1` agent-prompt｜`C_P2` HighFidelityPromptEditModal｜`C_M1` modelService｜`C_M2` ModelEditDialog｜`C_M3` ModelList｜`C_M4` modelConfig｜`C_Q1` thread.tsx｜`C_Q2` agent-debug-welcome

### 图上可达的复核候选（14 个）

| 候选 | 路径 | 复核要点 |
| --- | --- | --- |
| **A1** Agent 配置页 | C_P1 → A1 | prompt 上限放宽后，超长 prompt 的保存/回显是否正常 |
| **A2/A3** Agent 相关测试 | C_P1 → A2/A3 | 既有断言是否依赖 1000 上限 |
| **B1/B2** 后端 model_type | C_M1 → B1 → B2 | 已核对：字段既有、单条路径写入、multi_embedding 剥离 |
| **M1** 模型编辑 | C_M1/C_M2 → M1 | 编辑弹窗保存后类型是否立即刷新（PR 称手工验证过） |
| **M2** 模型添加 | C_M3 → M2 | 复核新增的「强制先探测」行为是否可接受（M1 已更正为 💭） |
| **M3** ModelList Tab | C_M3 → M3 | 列表能否显示新类型（PR 称手工验证过） |
| **M4** 连通性检测 | C_M4 → M4 | **跨行连点场景重点复核**（M2 问题） |
| **T1** 会话主视图 | C_Q1 → T1 | 空白 example_questions 不再渲染卡片 |
| **T2** 调试面板 | C_Q1/C_Q2 → T2 | 同上 |
| **T3/T4** 版本对比 | C_Q1 → T3/T4 | thread.tsx 被复用，空白过滤同样生效 |
| **T5** chat / nl2agent 面板 | C_Q1 → T5 | welcomeSuggestions 分支未过滤（M3 问题） |
| **Z1/Z2** V2 孤儿代码 | C_M3 → Z1/Z2 | 确认无调用方，建议清理 |

> ⚠️ 说明：可达 ≠ 必须修改。上表是"需要复核的候选"，实际需要处理的只有 M2/M3/M4 三条（M1 经核实已降为 💭）。

### 未覆盖的系统/边界

- **浏览器层面的实际渲染**：本次只跑了 jsdom 单测，未做 visual regression。`limit=100000` 的 `showCount` 显示（`xx/100000`）在窄输入框里是否会换行，建议人工看一眼。
- **真实后端的 model_type 写入**：第 5 节链路 B 是静态代码核对，未连真实 DB 验证。PR 描述称已手工验证"改类型保存后列表立即显示新类型"。
- **未展开**：模型的 `connect_status` 字段在后端的完整流转（见 L1）。

---

## 九、分优先级回归测试建议

### P1 必测（阻塞合入）

| # | 场景 | 代码点 | 验证方法 | 预期 |
| --- | --- | --- | --- | --- |
| P1-1 | 租户管理员编辑模型并改类型 | `ModelEditDialog` L268-335 | 资源管理→模型 Tab→编辑→改 rerank→保存 | 列表立即显示新类型，请求打到 `/manage/update` 且带 `model_type` |
| P1-2 | 个人（非租户）编辑模型 | 同上 | 模型管理页→编辑→改类型→保存 | 走 `/model/update`（single），不误发 tenantId |
| P1-3 | multi_embedding 编辑 | `management.py` L810-814 | 编辑 multi_embedding 模型 | **类型不变**，两条记录都更新，不被改成单类型 |
| P1-4 | 快速连点不同行的"检测连通性" | `modelConfig.tsx` L756 | 1 秒内先后点 A 行、B 行 | **确认 A 行是否被丢弃**（M2），若丢弃需修 |
| P1-5 | 长 prompt 保存 | `agent-prompt.tsx` L814/907 | 输入 5000 字符 prompt → 保存 → 重进页面 | 完整保存不截断，计数显示 `5000/100000` |

### P2 建议

| # | 场景 | 验证方法 | 预期 |
| --- | --- | --- | --- |
| P2-1 | 租户新增模型（单个） | 资源管理→模型→新增→直接点添加 | 确认被「请先通过连通性检测」拦下（这是 v0 的强制门控，非 bug 但需知情） |
| P2-2 | 租户批量导入 | 新增→批量添加 | 确认简化是否符合预期 |
| P2-3 | 空白 example_questions | 造一个含空白项的 Agent | 会话欢迎区不显示空卡片 |
| P2-4 | 编辑后 connect_status | 编辑改类型→保存→看行状态 | 确认沿用旧值（已知限制 L1） |

### P3 可选

- 版本对比页（T3/T4）的空白问题过滤
- V2 孤儿文件的清理验证
- `limit=100000` 的计数文案在窄屏的显示

---

## 十、结论与建议

### 总评

**代码质量整体不错**：4/5 的修复有针对性测试且经反向验证有效；PR 描述主动披露了 `connect_status` 限制和 V2 孤儿代码两个已知问题，这种坦诚值得肯定。链路 B（model_type 透传）从 `typeChanged` 门控到后端 multi_embedding 剥离，每一环都对得上。

**需要处理的问题**：

| 严重度 | 问题 | 建议 |
| --- | --- | --- |
| 🟡 **M2** | 共享 timer 丢弃跨行点击，用户点了没反应 | 改成按行独立 timer（`Map`），或至少给被取消行恢复状态 |
| 🟡 **M4** | prompt 上限（本 PR 标题诉求）零测试 | 加一行 `maxlength` 断言 |
| 🟡 M3 | `welcomeSuggestions` 分支漏过滤 | 补一行 filter |
| 💭 **M1'** | v0 新增**强制先探测**，静默行为变更 | 描述里说明一句即可（原"能力降级"判断已更正） |
| 💭 L1 | `connectStatus` 租户路径丢失（存量） | 后端加可选字段，或本 PR 记一笔 |
| 💭 L2 | V2 孤儿代码 | 单开清理提交 |

### 合并建议：**通过（建议顺手修 M2 + M4）**

> **2026-10-22 11:45 更正**：原判「需修改后通过，阻碍项 M1」已撤销——M1 经核实不成立（v0 保留了全部能力且更严格），降为 💭。

**最建议修**：M2（用户点了没反应，会被当 bug 报）、M4（一行断言锁住核心诉求）。
**可带可不带**：M3（一行 filter）。M1' 只需描述补一句。

### 附带建议

1. **PR 标题必须改**。5 个不相关修复塞进一个 `Fix/agent prompt limit 100000`，会让 review 和后续 git blame 都失真。建议拆成 3 个 PR（prompt / 模型对话框 / 空白建议），或至少把标题改成 `fix(frontend): prompt limit + model dialog routing + blank suggestion filtering`。
2. **L1 值得跟进**：`connect_status` 对齐只需后端加一个可选字段，能让"编辑后状态立即刷新"这个体验闭环。
3. **V2 清理**：两个孤儿文件建议尽快删，否则下个人会纠结用哪个。
