# W11：模型添加时的容量建议

## 目标

让 W1 的能力配置目录能够从默认前端“单模型”添加流程中触达，而不要求运维人员理解
`model_factory` 字段、目录中的精确 Provider 键，或 `ProviderCapabilityUnknown`
回退路径。大多数生产租户通过手动表单（URL + API key + 模型名称）添加 LLM，目前会完全绕过目录（见 CM-031 / W1 ADR 已知限制），使 W1 的目标落空。

W11 还复用现有的连通性检查时机来展示容量建议。运维人员在添加模型前本来就必须点击连通性验证；该验证在能够安全推导时应返回容量建议，同时仍把未知容量视为非阻塞的建议缺失。

## 当前状态与范围

W1 在 `backend/consts/capability_profiles.py` 中交付了一个小型、已批准的 day-one 目录。请求时解析仅在 `(provider, model_name)` 精确匹配目录键时成功。前端“单模型”添加表单不暴露 `model_factory`，因此它以 Pydantic 默认值 `'OpenAI-API-Compatible'` 提交，无法匹配任何目录键。后端辅助函数 `_infer_model_factory` 目前只对 embedding 类型记录生效。

W11 负责面向用户的“添加时建议默认值”体验，以及触发该体验的连通性检查集成。它**不**修改 W1 解析器、目录数据模型或 W1 指纹契约。已批准目录仍是高置信度 profile 默认值的可信来源。

不在范围内：

- 用动态 Provider 元数据替换 W1 目录。
- 弱化 `ProviderCapabilityUnknown` 语义。
- 未经运维人员接受就自动持久化 `provider_candidate` 值。
- 从 Provider 级 `ProviderConfigEditDialog` 路径批量配置容量。容量仍按模型配置；Provider 级批量配置按 CM-032 继续隐藏容量。

## 用户旅程

角色：正在添加或编辑 LLM/VLM 模型的运维人员。

1. 运维人员打开单模型添加对话框，输入 `base_url`、`api_key` 和 `model_name`。
2. 运维人员点击现有连通性验证控件。添加按钮仍与今天一样受连通性成功结果控制。
3. 在同一个后端验证请求中，W11 从 `provider_hint` 或 `base_url` 推断 Provider 候选，然后按以下顺序尝试容量建议：
   - 已批准 W1 目录的精确/模糊匹配。
   - 仅第二版：Provider 发现元数据，当 Provider 适配器和凭据能够返回模型列表或带容量提示的原始元数据时。
   - 无建议。
4. 如果找到建议，容量字段以 `suggested` 状态填充，并用提示说明来源。此时不会保存任何内容。
5. 运维人员可以点击“使用建议”，也可以编辑任意建议字段。该操作会把受影响字段提升为 `operator` 状态。
6. 保存时，已接受的建议通过现有模型管理端点写入，作为运维人员确认过的配置。对于目录匹配，如果为了 W1 精确查找必须这么做，保存 payload 还会写入 `model_factory = suggested_provider` 和目录规范 `model_name`。
7. 第一次模型请求后，监控必须显示运行时容量来自 `profile`、`operator` 还是 fallback。目录匹配应产生预期的 `capability_profile_version`；运维人员接受的 Provider 发现建议应产生 `capacity_source = 'operator'`，且不能错误声称命中 profile。

过去不可见的值现在应可见：

- 运维人员能看到容量建议来自已批准目录数据；第二版可继续加入置信度较低的 Provider 发现。
- 运维人员可以在保存前纠正错误建议。
- 建议缺失仍不阻塞流程，但可通过端点指标和 debug 日志观测；UI 保留现有空容量表单。

容量建议由 `CAPACITY_SUGGESTION_ENABLED` 控制，并且在前端每个单模型容量入口的新增/编辑界面展示一个开关：普通 Add/Edit 对话框，以及批量 Provider 流程中的单模型配置入口都包含该开关。该开关控制是否向用户展示来自确定性推理和未来 Provider 容量接口的容量建议。建议默认值为**开启**，因为建议不会自动写库、会显示来源，并且必须由运维人员显式接受后才会持久化。

## 现有裸容量模型的可见性

W11 还承担一个互补任务：暴露**现有**模型行中容量列仍为 NULL 的记录，也就是 W1 步骤 7 让 `context_window_tokens` 和 `max_output_tokens` 在新增/编辑表单中必填之前创建的遗留行。没有 W11 时，这些行会静默关闭 W2 输出 token enforcement 和 W1→W2 dispatch 一致性检查；今天唯一信号是模型管理员和 agent 作者都看不到的后端 WARNING。

### 问题陈述

遗留裸容量行的修复路径与 W11 添加时流程相同：打开模型、填写容量、保存。缺失的是让能够采取行动的人（模型管理员和 agent 作者）**发现**哪些行需要处理，而不是去 grep 后端日志。今天：

- 模型管理列表页将裸行和已配置行渲染得完全一样；UI 不提示 enforcement 已关闭。
- agent 编辑的“选择模型”下拉框把裸模型和已配置模型同等排序；agent 作者可能在不知情的情况下把未保护模型绑定到高流量 agent。
- 唯一日志是后端 WARNING，目标读者是通常不能编辑每租户模型记录的平台运维人员。

**生产证据（2026-06-17，开发部署）：**活动开发集群上的 `model_record_t` 快照显示共有 7 条未删除记录，其中 6 条携带 `model_factory = 'OpenAI-API-Compatible'`，也就是 CM-031 中的手动添加默认值。W2 目录回填迁移只匹配到一条记录（`dashscope` 上的 `glm-5.1`），导致运维人员正在聊天使用的 LLM（`glm-5`）保持裸容量，并静默绕过 CM-030 enforcement。这不是边缘情况：没有 W11 时，默认 factory 路径是主导路径，裸行数量会随着正常使用单调增长。

### 范围：仅 LLM 和 VLM

该可见性层仅覆盖 `model_type IN ('llm', 'vlm')` 的行。Embedding、speech-to-text 和 text-to-speech 模型共享同样的 `context_window_tokens` / `max_output_tokens` 列，但不参与 W1 容量解析器或 W2 dispatch 路径，因此这些行上的 NULL 不是 enforcement 缺失，不能展示为警告。徽标、agent 编辑选择器提示、仪表盘 widget 和 `/capacity-coverage` 端点都在数据层应用 `model_type IN ('llm', 'vlm')` 过滤；下游 UI 把它当作不变量，而不是运行时检查。

### 解决方案入口（三个 UI 触点）

#### 1. 模型管理列表页徽标

在 LLM/VLM 列表视图中，对容量不完整的行，在模型名称旁渲染一个黄色小警告徽标。该徽标：

- 与模型名称内联展示，而不是放在行尾，确保在窄视口和密集列表中也可见。
- 使用现有图标集（warning triangle）；绝不使用红色，因为模型仍可用，只是 enforcement 关闭。
- 悬停时显示 tooltip：“该模型未启用输出 token 上限 enforcement。点击立即填写容量值。”（i18n key 见下文。）
- 点击徽标打开与现有铅笔/齿轮控件相同的 `ModelEditDialog`，容量面板预展开；如果 W11 建议可以匹配，则预填建议。

徽标和修复入口只对管理员或具备模型管理权限的用户展示。没有模型管理权限的用户不会看到可跳转的修复入口。

徽标条件是 `context_window_tokens IS NULL OR max_output_tokens IS NULL`，与 W1 解析器的 `ProviderCapabilityUnknown` gate 一致。两个字段都要检查，而不只是其中一个，因为任一字段为 NULL 都会在请求时产生 `ProviderCapabilityUnknown`。

#### 2. Agent 编辑模型选择器警告

当 agent 作者在 agent 编辑页打开模型下拉框时，背后是裸容量行的条目应显示同一个 warning triangle，并带一行副标题：“Output cap not enforced — configure capacity in Model Management.” 条目仍可选择（降级行为优于阻塞 agent 创建）。

如果作者选择了裸容量模型，agent 编辑表单应在保存按钮上方显示非阻塞内联提示：“所选模型未配置容量。agent 会继续运行，但在模型管理中设置容量之前，输出 token enforcement 和预算一致性检查会关闭。” 没有模型管理权限的普通 agent 作者不展示修复链接，只展示非阻塞警告和：“请让模型管理员为 `<model_name>` 配置容量。” 管理员或具备模型管理权限的用户可以看到跳转到模型管理修复入口的链接。

#### 3. 面向运维人员的仪表盘 Widget

在系统仪表盘（平台管理员使用的现有运维落地页）中，为平台管理员或模型管理管理员增加一个小型 “Model capacity coverage” widget，展示：

- 裸容量 LLM/VLM 行数 / 总行数。
- 一个“查看全部”链接，打开模型管理并过滤到裸行。

当计数为零时隐藏该 widget，且普通 agent 作者不展示该 widget。不做告警；widget 用于可观测性，不用于 paging。

### 后端端点契约

```text
GET /api/v1/models/capacity-coverage
```

只读、幂等。按 bearer token 的 tenant claim 做租户隔离。返回：

| 字段 | 方向 | 类型 | 说明 |
| --- | --- | --- | --- |
| `total_llm_vlm` | 出 | integer | 租户内未删除 LLM/VLM 行数 |
| `bare_count` | 出 | integer | `context_window_tokens IS NULL OR max_output_tokens IS NULL` 的行数 |
| `bare_models` | 出 | array | 逐行标识信息 |

每个 `bare_models[]` 条目：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `model_id` | integer | DB 主键 |
| `model_name` | string | 原始展示值 |
| `model_factory` | string | 当前值，通常是 `OpenAI-API-Compatible` |
| `model_type` | string | `llm` 或 `vlm` |
| `suggestion_available` | boolean | `/suggest-capacity` 是否可以预填 |

该端点刻意保持很小。前端本地过滤和排序。不分页，因为该端点目标行数通常每租户小于 100，简单列表足够，运维过滤也只需本地完成。

`suggestion_available` 通过对每条裸行非阻塞调用 W11 目录 matcher 预计算。该端点**不**尝试 Provider 发现建议（那需要凭据和按行数扩展的网络调用）；只运行目录匹配。如果 W11 feature flag 关闭，`suggestion_available` 始终为 `false`，该字段仅提供信息。

### 前端实现

裸容量可见性与容量建议分离。它是面向旧行的默认开启修复提示，不是自动修复路径，也不属于 `CAPACITY_SUGGESTION_ENABLED`。

当 `CAPACITY_SUGGESTION_ENABLED` 关闭时：

- 列表页徽标仍渲染，因为徽标只依赖裸容量条件。
- agent 编辑下拉框警告仍渲染。
- 仪表盘 widget 仍渲染。
- “点击填写”操作打开现有 `ModelEditDialog`，但不预填建议；运维人员手动输入值。

当 `CAPACITY_SUGGESTION_ENABLED` 开启时，相同控件可以额外从 W11 目录匹配或后续 Provider 容量接口预填建议值。建议 UI 还受新增/编辑界面中的可见开关控制；该开关默认开启，并覆盖普通单模型对话框和批量 Provider 流程中的单模型配置入口。

涉及文件（新增子列表，不替换既有 Repository Touchpoints）：

- `frontend/app/[locale]/models/components/model/ModelList.tsx`（徽标列）
- `frontend/app/[locale]/setup/components/agentInfo/AgentGenerateDetail.tsx`（选择器副标题和内联提示）
- `frontend/app/[locale]/dashboard/ModelCapacityCoverageWidget.tsx`（新增）
- `frontend/services/modelService.ts`（`getCapacityCoverage()` 方法）
- `backend/apps/model_managment_app.py`（新增 GET 路由）
- `backend/services/model_management_service.py`（`get_capacity_coverage(tenant_id)` 查询）

### 本地化字符串（追加到上方 W11 字符串集合）

- `model.list.capacityWarning.badgeTooltip`
- `model.list.capacityWarning.tooltipAction`
- `agent.modelSelector.bareCapacity.subtitle`
- `agent.modelSelector.bareCapacity.formNotice`
- `agent.modelSelector.bareCapacity.formNoticeNoPermission`
- `dashboard.capacityCoverage.title`
- `dashboard.capacityCoverage.subtitle`
- `dashboard.capacityCoverage.viewAll`

### 测试

单元测试：

- `get_capacity_coverage` 针对混合已配置/裸容量行 fixture 返回正确 `bare_count`；`bare_models[]` 排除 embedding/rerank 行；排除已删除行。
- 对 `model_name` 和 `model_factory` 能够目录匹配（或模糊匹配）的行，`suggestion_available` 为 true；否则为 false。

集成测试：

- `GET /api/v1/models/capacity-coverage` 在一个已配置 `openai/gpt-4o` 行和一个裸行的情况下返回 `bare_count = 1`、`total_llm_vlm = 2`，并在 `bare_models[]` 中包含裸行的 `model_id`。
- 跨租户隔离：租户 B 的裸行不出现在租户 A 的响应中。

前端 E2E：

- 模型管理列表页有一个裸行：徽标与模型名称内联可见。点击徽标打开 `ModelEditDialog`，容量面板已展开。
- agent 编辑页选择裸容量模型：保存按钮上方出现内联提示。保存仍成功。
- 仪表盘 widget 在 `bare_count = 0` 时不渲染；在 `bare_count > 0` 时展示计数，且“查看全部”链接可用。

### W11 内的阶段位置

该可见性工作是 **Phase 1.5**（位于 Phase 1 目录匹配和 Phase 2 连通性集成之间）。它可独立于添加时建议 UX 发布，因为：

- 它不需要连通性验证变更。
- 它不需要 Provider 发现代码。
- 无论建议 flag 是否开启，它都直接处理现有裸行问题。

如果 Phase 1 在第 N 周发布，Phase 1.5 应在第 N+1 周作为默认开启的可见性功能发布。必要时运维可以关闭该可见性入口，但它不受容量建议开关控制，因为它不提出或保存容量值。

### 遗留 `max_tokens` 指引，而不是自动修复

当 W1 目录回填未命中（CM-031：典型情况是 `model_factory = 'OpenAI-API-Compatible'`），且没有可用容量建议时，该行会保持裸容量，dispatch 路径可能绕过 CM-030 enforcement。W11 **不**自动修复这些行，也绝不把推断容量写入 `model_record_t`。

相反，裸容量 UI 入口在遗留 `max_tokens` 存在且为正数时展示该值。提示文案说明：W1 拆分容量字段之前，旧 `max_tokens` 经常被填写为模型的上下文窗口；请运维人员核对 Provider 文档，如果该值确实是上下文窗口，则手动填入 `context_window_tokens` 字段。运维人员也可以手动填写 `max_output_tokens`、`default_output_reserve_tokens` 和其他容量字段，或显式接受 W11 建议。

持久化语义：

- W11 不会在没有运维人员保存动作的情况下修改裸行。
- 遗留 `max_tokens` 只作为证据展示；不会自动复制到 `context_window_tokens`。
- 已接受建议和手动编辑继续通过现有模型管理端点保存，并使用 `capacity_source = 'operator'`。
- 仍不完整的行继续出现在默认开启的裸容量可见性入口中。

UI 文案：

- 裸容量 tooltip/details 包含：“Legacy max_tokens is `<max_tokens>`. If this value is the provider context window, enter it as Context Window and save.”
- 如果 `max_tokens` 缺失或非正数，UI 不展示该值，并提示运维人员查阅 Provider 文档。
- Agent 编辑选择器警告保持非阻塞，且不尝试推断容量值。

### 本节范围外

- 自动修复裸行。修复路径是运维人员打开编辑对话框，查看遗留 `max_tokens` 证据或 W11 建议，然后保存。目录匹配行的自动写入路径仍由目录回填 SQL 迁移（`docker/sql/v2.2.0_0617_backfill_w2_capacity_from_w1_catalog.sql`）管理，而不是由该 UI 工作管理。
- 选择裸容量模型时阻塞 agent 保存。选择的 UX 是降级行为（警告 + 非阻塞），因此 agent 创建永远不会被跨团队协调阻塞。
- 从仪表盘 widget 发出 Email/Slack 告警。该 widget 是信息性入口；集成方可在下游添加告警。
- 在聊天 UI 中向终端用户展示警告。终端用户不能编辑模型容量；向他们展示警告只会制造无处处理的责任路由。

## 目标契约

容量建议通过两种方式暴露：

```text
POST /api/v1/models/suggest-capacity
```

以及在现有连通性验证成功后，由该流程可选返回一个 capacity-suggestion payload。独立端点对编辑流程、Provider 浏览流程和测试有用；添加对话框主要使用连通性检查响应，以避免第二个可见步骤。

### 请求

| 字段 | 方向 | 类型 | 说明 |
| --- | --- | --- | --- |
| `model_name` | 入 | string | 运维人员输入的原始值 |
| `base_url` | 入 | string | 可选；用于推断 Provider |
| `provider_hint` | 入 | string | 可选显式 Provider，通常来自 Provider 浏览器或现有模型记录 |
| `api_key` | 入 | string | 可选；仅用于连通性检查或 Provider 发现路径，绝不记录日志 |
| `model_type` | 入 | string | 可选；用于把建议限制到 LLM/VLM 路径和 Provider 适配器 |

独立 `/suggest-capacity` 端点仅在 Provider 发现开启时接受 `api_key`。仅目录匹配的 Phase 1 不需要它。连通性检查已经在内存中持有凭据，可以把它们传给同一个 service，而不持久化。

### 响应

| 字段 | 方向 | 类型 | 说明 |
| --- | --- | --- | --- |
| `suggestions` | 出 | object/null | snake_case 的建议容量值 |
| `match_kind` | 出 | enum | `catalog_exact`、`catalog_fuzzy`、`provider_discovery`、`none` |
| `match_confidence` | 出 | enum | `high`、`medium`、`low` |
| `match_explanation` | 出 | string | 人类可读原因，例如 `Matched approved catalog profile openai/gpt-4o@1` |
| `suggested_provider` | 出 | string/null | 接受时要持久化的 Provider 键，例如 `openai` |
| `canonical_model_name` | 出 | string/null | 接受时要持久化的目录/Provider 模型 ID |
| `capability_profile_version` | 出 | string/null | 仅目录匹配时存在 |
| `capacity_source_on_accept` | 出 | enum/null | 已接受写入始终为 `operator`；`match_kind = none` 时为 null |

建议对象只包含 W11 能够安全预填的模型记录容量字段：

- `context_window_tokens`
- `max_input_tokens`
- `max_output_tokens`
- `default_output_reserve_tokens`
- `tokenizer_family`

对于目录匹配，`capability_profile_version` 作为响应元数据返回，但不会被盲目写作运维值。W1 运行时解析仍必须从保存后的 `(model_factory, model_name)` 证明 profile 匹配。

该端点只读且幂等。它绝不修改数据库，也绝不绕过运维人员。接受建议是明确的前端动作，通过现有模型管理端点以 `capacity_source = 'operator'` 写入；用户对已保存容量值承担责任。目录精确/模糊建议在保存后仍可能让运行时得到 `capacity_source = 'profile'`，但前提是接受的 Provider 和规范模型名让 W1 精确目录查找成功。

## 设计

W11 按严格信任顺序使用三种容量来源。

### 1. 已批准目录匹配

读取 `backend/consts/capability_profiles.py`，将运维人员输入与已批准 W1 目录匹配。

规范化：

- 仅用于比较时转小写。
- 去除空白。
- 将 `-`、`_`、`.` 和 `/` 边界视为可比较的 token 分隔符。
- 对带命名空间的目录 ID，如果最终片段在推断 Provider 的目录条目内唯一，允许匹配完整 Provider 模型 ID 或最终片段。

允许示例：

- `gpt-4o` 和 `GPT-4o`。
- `glm-5.1` 和 `glm5.1`。
- `Deepseek V4 Flash` 和 `deepseek-ai/DeepSeek-V4-Flash`。
- `Kimi-K2.6` 和 `Pro/moonshotai/Kimi-K2.6`，仅当它在推断 Provider 下唯一。

`catalog_exact` 表示规范化 Provider 和规范化模型名已经能在不丢弃命名空间片段的情况下识别同一目录条目。`catalog_fuzzy` 表示需要使用某个允许的规范化规则或唯一最终片段规则。

目录匹配返回 high 或 medium 置信度：

- `catalog_exact`：`high`，绿色 UI 样式。
- `catalog_fuzzy`：`medium`，绿色 UI 样式，并提示如果接受，将使用保存后的规范模型名/Provider。

### 2. 连通性验证期间的 Provider 发现（第二版）

Provider 发现不进入 W11 第一版实现。第一版只发布目录精确/模糊建议。第二版中，如果目录没有匹配，且 `base_url` host 或 `provider_hint` 映射到受支持的 Provider 适配器（`silicon`、`dashscope`、`tokenpony`、`modelengine`），W11 可在连通性验证期间调用 Provider 容量接口或现有 Provider 发现流程。

Provider 发现的可信度刻意低于已批准目录：

- 它可以使用 `get_provider_models` 或现有 Provider 适配器返回的 Provider 专属原始元数据。
- 它可以使用 W1 步骤 3 的 `_extract_capacity_hints_from_raw`。
- 它可以先搜索精确 Provider 模型 ID，然后仅在 Provider 适配器标记返回 ID 无歧义时使用 contains 匹配。
- 它绝不修改 W1 目录，也不声称 `capacity_source = 'profile'`。
- 它返回 `match_kind = provider_discovery`、`match_confidence = low`，并使用黄色 UI 样式。

普通 chat/completions 连通性调用预期不会揭示模型硬容量。验证调用中的 token usage 不足以推断 context window、input limit、output limit、tokenizer family、reasoning-window 行为或 Provider overhead。因此连通性验证可以触发发现元数据，但单次模型调用结果本身只作为连通性证据。

### 3. 运维覆盖

如果目录和 Provider 发现都没有返回建议，表单保持为空，并沿用现有手动容量路径。如果运维人员接受或编辑任意建议，保存的容量字段使用 `capacity_source = 'operator'`。

## Provider 推断与保存规则

共享辅助函数选择 Provider 候选：

- 如果 `provider_hint` 已设置，使用它。
- 否则如果 `base_url` host 匹配已知映射，使用映射 Provider：
  - `api.openai.com` -> `openai`
  - 包含 `dashscope` 的 host -> `dashscope`
  - 已知 SiliconFlow host -> `silicon`
  - 已知 TokenPony host -> `tokenpony`
  - 已知 ModelEngine/open-router host -> `modelengine`
- 否则如果没有 Provider hint 也能唯一目录匹配，使用该条目的 Provider。
- 否则返回 null 和 `match_kind = none`。

该辅助函数也将 `_infer_model_factory` 扩展到 LLM/VLM。Embedding 记录继续使用现有 embedding 行为，但 host map 必须共享，避免 LLM/VLM 和 embedding 推断漂移。

接受建议时的持久化规则：

| 匹配类型 | 保存 `model_factory` | 保存 `model_name` | 保存容量字段 | 运行时期望 |
| --- | --- | --- | --- | --- |
| `catalog_exact` | `suggested_provider` | 如果已有值已规范化则保留；否则保存 `canonical_model_name` | 可选，作为运维确认后的可见值 | W1 精确 profile 匹配应产生 `capacity_source = profile` |
| `catalog_fuzzy` | `suggested_provider` | 保存 `canonical_model_name`，除非运维人员明确保留原始名称 | 是，`capacity_source = operator` | 仅在保存规范名称时 profile 才匹配 |
| `provider_discovery` | 已知时保存 `suggested_provider` | 已知时保存 Provider 返回的精确模型 ID；否则保留现有值 | 是，`capacity_source = operator` | 运维配置容量，不声称 profile |
| `none` | 现有行为 | 现有行为 | 仅现有手动输入 | 现有 fallback/override 行为 |

如果运维人员保留不会匹配 W1 目录的原始模糊名称，UI 必须显示警告：“除非保存规范模型 ID，否则运行时将使用运维人员配置的容量值，而不是已批准的目录 profile。”

## 运行时契约

```text
suggest_capacity(
  model_name: str,
  base_url: Optional[str],
  provider_hint: Optional[str],
  model_type: Optional[str],
  api_key: Optional[str],
) -> SuggestCapacityResult
```

`SuggestCapacityResult` 是与上方响应表一致的 Pydantic 模型。目录、Provider 适配器、host-to-provider map 和 feature flag 都作为参数注入，遵循与 W1 解析器相同的纯函数规则。

类型化失败：

- `InvalidInput`：空 `model_name`、模型名过长、不支持的 `model_type` 或 URL 格式错误。端点对无效请求形状返回 400。
- `ProviderDiscoveryFailed`：Provider 发现 HTTP/auth/timeout 错误会被捕获并降级为 `match_kind = none`，附带说明。端点仍返回 200，因为缺少建议不是添加流程失败。

安全与隐私：

- `api_key` 绝不记录日志、持久化、返回或写入 trace。
- Provider 发现遵守现有租户授权和限流中间件。
- 连通性验证只有在普通模型管理授权检查成功后，才能调用建议逻辑。

## 数据库迁移契约

无。W11 不引入 schema。它读取已批准目录，并可在 Provider 发现期间发起可选上游 HTTP 调用。

如果需要按租户 rollout，使用现有 `tenant_config_t` 配置存储，key 为 `capacity_suggestion_enabled`。该 key 默认未设置，表示由全局 env flag 决定行为。

## 迁移、交付物与阶段

- Phase 1：仅目录精确/模糊匹配。放在默认开启的 `CAPACITY_SUGGESTION_ENABLED=true` 后发布，并且前端新增/编辑容量界面的建议开关也默认开启。
- Phase 2：把目录建议输出集成到连通性验证响应。第一版暂不做 Provider 发现。
- 第二版：当连通性验证或显式 `/suggest-capacity` 请求有凭据时，为受支持适配器加入 Provider 发现；前提是 Provider 容量接口、timeout、限流和凭据处理契约已接受。
- Phase 4：通过共享 host-to-provider map 将 `_infer_model_factory` 扩展到所有 LLM/VLM 路径；保持 embedding 行为兼容。
- Phase 5：dogfood 和 SLO 证据通过后移除 feature flag。

## 实施计划

### 后端

1. 新增 `backend/services/model_capacity_suggestion_service.py`，包含：
   - `suggest_capacity`
   - `_normalize_model_name`
   - `_pick_provider`
   - `_fuzzy_catalog_match`
   - `_suggest_from_provider_discovery`
   - W11 和 `_infer_model_factory` 共同使用的共享 host-to-provider map
2. 在 `backend/apps/model_managment_app.py` 中新增 `POST /api/v1/models/suggest-capacity` 路由。
3. 在 `backend/consts/model.py` 中新增 `ModelCapacitySuggestionRequest`、`ModelCapacitySuggestionResponse` 和嵌套的 `CapacitySuggestionFields` Pydantic 模型。
4. 扩展现有连通性验证响应，在验证成功后可选包含 `capacity_suggestion`。建议失败不导致连通性验证失败。
5. 扩展 `backend/services/model_health_service.py::_infer_model_factory`，使用共享 host map 覆盖 LLM/VLM。
6. 更新模型保存处理，使接受目录建议时，在 W1 目录查找需要的情况下可以保存 `model_factory = suggested_provider` 和 `model_name = canonical_model_name`。
7. 发出指标：
   - `model_capacity_suggestion_requests_total{match_kind,model_type,provider}`
   - `model_capacity_suggestion_latency_ms{match_kind,provider}`
   - `model_capacity_suggestion_accept_total{match_kind,provider}`
   - `model_capacity_suggestion_dispatch_profile_hit_total{provider}`

### 前端服务层

8. 在 `frontend/services/modelService.ts` 中新增 `modelService.suggestCapacity(...)`，返回类型化 `SuggestCapacityResponse`。请求体为 snake_case；响应映射为 camelCase，沿用 `mapCapacityFieldsFromApi` 风格。
9. 扩展连通性检查服务响应映射，包含 `capacitySuggestion`。

### 前端表单状态机

10. 在 `ModelCapacityFields.tsx` 中为每个容量输入新增三种状态：`empty | suggested | operator`。
11. `suggested` 值在字段标签附近渲染一个小型来源 chip：
    - catalog exact/fuzzy：绿色
    - provider discovery：黄色
12. 用户输入或点击“使用建议”会把受影响字段提升为 `operator`。当字段已经是 `operator` 时拒绝写入建议，避免延迟响应覆盖用户输入。
13. 表单保留 pending suggestion 元数据：`matchKind`、`suggestedProvider`、`canonicalModelName`、`capabilityProfileVersion` 和 `capacitySourceOnAccept`。
14. 保存时，已接受的建议元数据包含在现有保存 payload 中，使后端可按上述保存规则持久化 Provider/模型规范化和容量字段。
15. 容量建议开关渲染在每个新增/编辑容量入口中，包括普通单模型对话框，以及从批量 Provider 流程打开的单模型配置入口。关闭该开关会抑制该对话框内的建议请求和建议 chip，但不会抑制裸容量警告。
16. 当 `context_window_tokens` 没有建议时，将 context window 控件渲染为支持预设的选择器，而不是普通数字输入。该选择器必须允许运维人员选择常见预设，或输入自定义正整数。选择或输入值会把字段标记为 `operator`。
17. 当 `default_output_reserve_tokens` 没有建议时，将 output reserve 控件渲染为较小的支持预设选择器，并具备相同的自定义正整数行为。

预设值：

```ts
const MAX_TOKEN_OPTIONS = [
  { value: "4096", label: "4K / 4,096" },
  { value: "8192", label: "8K / 8,192" },
  { value: "16384", label: "16K / 16,384" },
  { value: "32768", label: "32K / 32,768" },
  { value: "65536", label: "64K / 65,536" },
  { value: "131072", label: "128K / 131,072" },
  { value: "204800", label: "200K / 204,800" },
  { value: "262144", label: "256K / 262,144" },
  { value: "1048576", label: "1M / 1,048,576" },
];

const OUTPUT_RESERVE_OPTIONS = [
  { value: "256", label: "256" },
  { value: "512", label: "512" },
  { value: "1024", label: "1K / 1,024" },
  { value: "2048", label: "2K / 2,048" },
  { value: "4096", label: "4K / 4,096" },
  { value: "8192", label: "8K / 8,192" },
  { value: "16384", label: "16K / 16,384" },
];
```

预设选择器是 fallback UX，不是容量权威来源。从中选择的值保存为 `capacity_source = 'operator'`。

### 前端添加/编辑路径

18. `ModelAddDialog`：主流程。成功完成连通性验证后运行建议；当验证已通过时，也允许在 `model_name` blur 或 `base_url` change 后调用独立端点。
19. `ModelEditDialog`：如果现有自定义 OpenAI-compatible LLM/VLM 容量字段为 null，或 `model_factory = OpenAI-API-Compatible`，在验证或显式检查后显示“有可用建议”。
20. `ProviderConfigEditDialog` 的单模型齿轮路径：当为单个模型调用时复用同一编辑逻辑。Provider 级批量配置保持范围外，并按 CM-032 隐藏容量字段。
21. `ModelDeleteDialog` Provider 浏览流程：当启用的 Provider 模型记录缺少容量值时，把建议展示为 “Add capacity” 提示。除非运维人员接受建议，否则不覆盖现有 Provider 来源的 `model_factory` 值。

### 错误与 fallback 处理

22. `/suggest-capacity` 返回 HTTP 5xx / 网络错误：记录到 console，回退到现有空表单行为。绝不阻塞新增/编辑。
23. `match_kind = none`：不展示建议提示。容量字段仍可编辑，context window / output reserve 字段展示上文预设选择器。发出指标。
24. Provider 发现 timeout/auth 失败：除非连通性验证本身失败，否则不展示用户可见错误。建议缺失仅用于诊断。
25. 模糊目录规范化警告：如果运维人员拒绝保存规范模型名，提示运行时不会声明 profile capacity，除非 W1 精确查找成功。

### 本地化

26. 向 en/zh 新增 locale 字符串：
    - `model.dialog.capacity.suggestion.title`
    - `model.dialog.capacity.suggestion.matchExact`
    - `model.dialog.capacity.suggestion.matchFuzzy`
    - `model.dialog.capacity.suggestion.matchProviderDiscovery`
    - `model.dialog.capacity.suggestion.useSuggestion`
    - `model.dialog.capacity.suggestion.canonicalName`
    - `model.dialog.capacity.suggestion.candidateWarning`
    - `model.dialog.capacity.suggestion.profileMissWarning`
    - `model.dialog.capacity.suggestion.toggle`
    - `model.dialog.capacity.preset.custom`
    - `model.dialog.capacity.preset.contextWindow`
    - `model.dialog.capacity.preset.outputReserve`
    - `model.dialog.capacity.legacyMaxTokensHint`

## Repository Touchpoints

后端：

- `backend/services/model_capacity_suggestion_service.py`（新增）
- `backend/apps/model_managment_app.py`（新增路由和连通性响应）
- `backend/consts/model.py`（请求/响应 Pydantic 模型）
- `backend/services/model_health_service.py`（`_infer_model_factory` 共享 host-map 扩展）
- `backend/services/model_management_service.py`（保存已接受的 Provider/模型规范化和容量字段）
- `backend/services/model_provider_service.py` 和 `backend/services/providers/*`（Provider 发现输入/元数据契约）

前端：

- `frontend/app/[locale]/models/components/model/ModelAddDialog.tsx`
- `frontend/app/[locale]/models/components/model/ModelEditDialog.tsx`
- `frontend/app/[locale]/models/components/model/ProviderConfigEditDialog`（仅单模型齿轮路径；Provider 级批量容量配置不在范围内）
- `frontend/app/[locale]/models/components/model/ModelDeleteDialog.tsx`
- `frontend/app/[locale]/models/components/model/ModelCapacityFields.tsx`
- `frontend/services/modelService.ts`
- `frontend/public/locales/en/common.json`
- `frontend/public/locales/zh/common.json`

实施时要验证的调用点证据：

- `_infer_model_factory` 当前定义在 `backend/services/model_health_service.py`，并由 `backend/services/model_management_service.py` 中仅 embedding 的模型创建路径调用。
- 模型新增/编辑 service mapping 已经在 `frontend/services/modelService.ts` 中有 camelCase/snake_case 容量辅助函数。
- 容量 UI 通过 `ModelCapacityFields.tsx` 共享，由新增/编辑和单模型 Provider 配置路径渲染。

## 运维依赖

W11 需要后端和 web 容器协调部署。没有 DB 迁移。

| 组件 | 操作 | 触发条件 |
| --- | --- | --- |
| `nexent-runtime` / `nexent-northbound` / `nexent-config` / `nexent-mcp` | 镜像重建 + `compose up --force-recreate`（`nexent 代码改动生效流程.md` 中的流程 A） | 后端路由、service、连通性响应和建议变更 |
| `nexent-web` | 镜像重建 + `compose up --force-recreate`（流程 D） | 前端对话框、service 和 i18n 变更 |
| `nexent-postgresql` | 无变更 | 无 schema 迁移 |
| `consts.const` | 新增 `CAPACITY_SUGGESTION_ENABLED`，默认 `true` | 全局 feature flag |
| 租户配置 | 可选 key `capacity_suggestion_enabled`；未设置表示继承 env flag | 分阶段租户 rollout |
| Monitoring | 添加上方列出的端点和接受指标 | Phase 2 观测 |

Rollout 顺序：

1. 在 staging 全局启用 env var。
2. 对一个内部租户按租户启用。
3. 测量一周目录 exact/fuzzy 准确率和已接受保存的 profile hit。
4. Provider 发现推迟到第二版；仅在限流和凭据处理证据经过审查后启用。
5. 对付费租户启用。
6. 测量一周。
7. 对所有租户启用，并且只有在完成定义通过后移除 flag。

Rollback：

- 设置 `CAPACITY_SUGGESTION_ENABLED=false`。
- 前端隐藏建议 UI，并忽略连通性验证返回的 `capacity_suggestion`。
- 后端路由返回 disabled/no-op，或不被调用。
- 不需要数据迁移。之前已接受的运维容量值保留为普通运维配置。

## 测试与发布证据

### 单元测试

- `_normalize_model_name` 覆盖所有目录条目和文档中的变体：`GPT-4o`、`glm5.1`、`Deepseek V4 Flash`、`Kimi-K2.6`，以及带命名空间的 Silicon 条目。
- `_pick_provider` 覆盖 host map，并验证未知 host 返回 null。
- `_fuzzy_catalog_match` 拒绝有歧义的最终片段匹配。
- 第二版 Provider 发现测试验证 chat/completions token usage 绝不会被视为硬容量元数据。

### 集成测试

- `POST /api/v1/models/suggest-capacity` 使用 `{"model_name":"gpt-4o","base_url":"https://api.openai.com/v1"}` 返回 `catalog_exact`、`suggested_provider = openai`、`canonical_model_name = gpt-4o` 和 `capability_profile_version = openai/gpt-4o@1`。
- `POST /api/v1/models/suggest-capacity` 使用 `{"model_name":"Deepseek V4 Flash","provider_hint":"silicon"}` 返回 `catalog_fuzzy`、规范模型名 `deepseek-ai/DeepSeek-V4-Flash` 和 medium confidence。
- `POST /api/v1/models/suggest-capacity` 使用 `{"model_name":"unknown-local-model","base_url":"http://localhost:8000/v1"}` 返回 `match_kind = none` 且无 suggestions。
- 第二版 Provider 发现 mock 测试：`qwen-some-experimental-model` 针对带容量元数据的 DashScope Provider 响应，返回 `provider_discovery`、low confidence，且无 `capability_profile_version`。

### 前端 E2E

- 添加模型，输入 `https://api.openai.com/v1` + `gpt-4o`；点击连通性验证；容量字段填入绿色目录建议；点击“使用建议”；提交；保存行具有 `model_factory = openai`、必要时规范化的模型名，以及运维确认过的容量字段。
- 添加模型，输入 `provider_hint = silicon` + `Deepseek V4 Flash`；接受规范模型名；提交；第一次运行时请求的监控显示 `capability_profile_version = silicon/deepseek-v4-flash@1`。
- 添加未知模型；点击连通性验证；验证可通过，但不显示建议提示，添加流程仍可用，并允许手动输入容量。
- 对该未知模型，打开 context-window 选择器，选择 `128K / 131,072`；打开 output-reserve 选择器，选择 `4K / 4,096`；提交；保存行具有这些值，且 `capacity_source = operator`。
- 禁用 feature flag；新增/编辑流程与之前完全一致，W1 resolver 测试仍通过。

### 可复制 Demo 脚本

目录精确建议：

```bash
curl -sS -X POST http://127.0.0.1:5010/api/v1/models/suggest-capacity \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d '{"model_name":"gpt-4o","base_url":"https://api.openai.com/v1","model_type":"llm"}'
```

预期字段：

```json
{
  "match_kind": "catalog_exact",
  "match_confidence": "high",
  "suggested_provider": "openai",
  "canonical_model_name": "gpt-4o",
  "capability_profile_version": "openai/gpt-4o@1"
}
```

目录模糊建议：

```bash
curl -sS -X POST http://127.0.0.1:5010/api/v1/models/suggest-capacity \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d '{"model_name":"Deepseek V4 Flash","provider_hint":"silicon","model_type":"llm"}'
```

预期字段：

```json
{
  "match_kind": "catalog_fuzzy",
  "match_confidence": "medium",
  "suggested_provider": "silicon",
  "canonical_model_name": "deepseek-ai/DeepSeek-V4-Flash",
  "capability_profile_version": "silicon/deepseek-v4-flash@1"
}
```

负路径：

```bash
curl -sS -X POST http://127.0.0.1:5010/api/v1/models/suggest-capacity \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d '{"model_name":"unknown-local-model","base_url":"http://localhost:8000/v1","model_type":"llm"}'
```

预期字段：

```json
{
  "match_kind": "none",
  "suggestions": null
}
```

保存后验证 SQL：

```sql
SELECT model_id, model_name, model_factory, context_window_tokens,
       max_output_tokens, default_output_reserve_tokens, tokenizer_family,
       capacity_source, capability_profile_version
FROM nexent.model_record_t
WHERE model_name IN ('gpt-4o', 'deepseek-ai/DeepSeek-V4-Flash')
ORDER BY model_id DESC
LIMIT 5;
```

首次 dispatch 监控验证：

```sql
SELECT model_name, model_factory, capability_profile_version, capacity_source,
       context_window_tokens, max_output_tokens, default_output_reserve_tokens
FROM nexent.model_monitoring_record_t
WHERE capability_profile_version IN ('openai/gpt-4o@1', 'silicon/deepseek-v4-flash@1')
ORDER BY created_at DESC
LIMIT 5;
```

## SLO 与完成定义

Rollout 期间的 SLO：

- 至少 70% 新增手动添加的、目录支持模型 LLM 行，在连通性验证期间产生 `match_kind != none`。
- 至少 95% 已接受的目录建议在第一次 dispatch 时产生预期运行时 `capability_profile_version`。
- 第二版 Provider 发现建议 p95 延迟低于已批准的模型添加延迟预算，且 timeout 绝不阻塞连通性验证。
- 已启用租户的建议端点 5xx 率低于 1%。

完成定义：

- Phase 1 和 Phase 2 放在 `CAPACITY_SUGGESTION_ENABLED` 后发布，默认开启，并且每个新增/编辑容量入口都包含用户可见的建议开关。
- 内部 dogfood 验证每个已批准目录条目的精确和模糊建议。
- Provider 发现不进入第一版，仅在第二版凭据日志、限流和 timeout 测试通过后发布。
- `_infer_model_factory` 覆盖 LLM/VLM 添加路径，并保持 embedding 行为。
- 上方列出的所有前端 sibling 路径都被测试覆盖，或在测试中明确声明范围外。
- Dogfood 和 SLO 检查连续两周通过。
- 只有在 rollback plan 已测试后才移除 feature flag。

## 为什么这不是 W1

W1 的 ADR 明确限定在目录数据模型和解析器契约范围内。“目录如何从真实用户行为中正确填充”是同一问题的另一层。将修复移入新的工作流，可保持 W1 不变量稳定：目录键保持精确、已批准 profile 仍是经过审查的数据、`provider_candidate` 在运维人员接受前永远不是权威值。W11 改善了进入该契约的运维路径，但不替换该契约。

参见 `W1_ADR_Capability_Catalog_Storage_and_Fingerprint.md` 的 “Known Limitations” 部分，了解本工作流解决的缺口。
