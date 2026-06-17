# W17：模型添加时的容量建议

## 目标

让 W1 的能力配置目录可从默认前端"单模型"添加流程中触达，而无需运维人员理解 `model_factory` 字段、目录的精确 Provider 键或 `ProviderCapabilityUnknown` Fallback 路径。多数生产租户通过手动表单（URL + API key + 模型名称）添加 LLM，当前完全绕过了目录（见 CM-031 / W1 ADR 已知限制），使 W1 的目标落空。

## 当前状态与范围

W1 在 `backend/consts/capability_profiles.py` 中交付了八个已验证的目录条目。请求时的解析仅在 `(provider, model_name)` 精确匹配目录键时成功。前端"单模型"添加表单不暴露 `model_factory`，因此它以 Pydantic 默认值 `'OpenAI-API-Compatible'` 提交，无法匹配任何目录键。后端辅助函数 `_infer_model_factory` 仅对 embedding 类型记录生效。

W17 负责面向用户的"添加时建议默认值"体验。它**不**修改解析器、目录数据模型或 W1 指纹契约；它在前端和目录之间增加一层轻量查询，以及一个接受建议值的 UX 交互。

不在范围内：修改 W1 的目录优先级；削弱 `ProviderCapabilityUnknown` 语义；自动持久化 `provider_candidate` 值（仍需运维人员确认）。

## 目标契约

新增一个端点提供容量建议；前端可选地将其作为表单占位符接受。

```text
POST /api/v1/models/suggest-capacity
```

| 字段 | 方向 | 类型 | 说明 |
| --- | --- | --- | --- |
| `model_name` | 入 | string | 运维人员输入的原始值 |
| `base_url` | 入 | string | 可选；用于推断 Provider |
| `provider_hint` | 入 | string | 可选；运维人员的显式选择 |
| `suggestions` | 出 | object | 建议的容量值（snake_case） |
| `match_kind` | 出 | enum | `catalog_exact`、`catalog_fuzzy`、`provider_discovery`、`none` |
| `match_confidence` | 出 | enum | `high`、`medium`、`low` |
| `match_explanation` | 出 | string | 人类可读的原因（"matched openai/gpt-4o@1 via tokenizer family"） |
| `suggested_provider` | 出 | string | 将被持久化的 Provider 键 |

建议对象包含与 W1 `CapabilityProfile` 暴露的相同六个容量字段：`context_window_tokens`、`max_input_tokens`、`max_output_tokens`、`default_output_reserve_tokens`、`tokenizer_family`，以及派生的 `capacity_source`（精确匹配为 `profile`，模糊/发现为 `provider_candidate`，`none` 时省略）。

该端点是**只读且幂等的**。它绝不修改数据库，也绝不绕过运维人员。接受建议是一个显式的前端操作，通过现有的模型管理端点写入，并标记 `capacity_source = 'operator'`（用户承担了责任）。

## 设计

两层匹配，按顺序执行：

1. **目录模糊匹配。** 对用户输入做规范化（小写、去除最后一个 `/` 前的命名空间、替换 `-`/`/`/`.`/`_` 边界），对目录键做同样处理后精确匹配。模糊逻辑是有界的，不尝试语义匹配，仅处理 Provider 文档与用户习惯之间的已知命名变体（`gpt-4o` vs `GPT-4o`、`deepseek-v4-flash` vs `deepseek-ai/DeepSeek-V4-Flash`、`glm-5.1` vs `glm5.1`）。匹配类型：`catalog_exact`（规范化后完全相同）或 `catalog_fuzzy`（一次允许的变换之内）。
2. **Provider 发现。** 如果 `base_url` 主机或 `provider_hint` 映射到已支持的 Provider 适配器（silicon / dashscope / tokenpony / modelengine），调用一次现有的 `get_provider_models` 流程，搜索 ID 包含用户输入的 `model_name` 的模型。使用 W1 步骤 3 的 `_extract_capacity_hints_from_raw` 辅助函数提取 Provider 发布的容量。匹配类型：`provider_discovery`。

如果两层都未匹配，返回 `match_kind: "none"` 且不带建议。前端随后显示现有的空表单。

一个小型推断辅助函数为响应选择 `suggested_provider`：

- 如果 `provider_hint` 已设置，使用它。
- 否则如果 `base_url` 主机匹配已知映射（`api.openai.com` → `openai`、`dashscope.aliyuncs.com` → `dashscope` 等），使用该映射。
- 否则如果找到了目录匹配，使用该条目的 Provider。
- 否则返回 `OpenAI-API-Compatible` 和 `match_kind: "none"`。

该辅助函数取代并覆盖了 `_infer_model_factory` 中仅限 LLM 的缺口。Embedding 记录继续使用现有的推断路径；W17 不对其进行重构。

## 运行时契约

```text
suggest_capacity(model_name, base_url, provider_hint)
  -> SuggestCapacityResult
```

`SuggestCapacityResult` 是一个 Pydantic 模型，包含契约表中列出的八个字段。目录、Provider 适配器和主机到 Provider 的映射作为参数注入（与 W1 解析器相同的纯函数规则）。

类型化失败：`InvalidInput`（`model_name` 为空或过长）、`ProviderDiscoveryFailed`（步骤 2 中的 HTTP 错误被捕获并降级为 `match_kind: "none"`；端点仍返回 200 并附带说明，因为缺少建议不是请求失败）。

该端点通过现有中间件按租户限流（Provider 发现会发起上游 API 调用）。

## 数据库迁移契约

无。W17 不引入 Schema。它读取目录并可选地发起上游 HTTP 调用。

## 迁移、交付物与阶段

- 阶段 1：仅目录模糊匹配，不含 Provider 发现。在 Feature Flag 后交付。
- 阶段 2：为四个已支持的适配器增加 Provider 发现。
- 阶段 3：通过 suggest-capacity 使用的同一主机到 Provider 映射，将 `_infer_model_factory` 扩展到所有模型类型；废弃仅限 embedding 的路径。
- 阶段 4：收集 SLO 证据后移除 Feature Flag（见测试）。

## 实施计划

### 后端（第 1-3 项）

1. 新增 `backend/services/model_capacity_suggestion_service.py`，包含 `suggest_capacity`（纯函数）以及 `_normalize_model_name`、`_pick_provider`、`_fuzzy_catalog_match` 辅助函数。
2. 在 `backend/apps/model_managment_app.py` 中新增 `POST /api/v1/models/suggest-capacity` 路由。
3. 在 `backend/consts/model.py` 中新增 `ModelCapacitySuggestionRequest` 和 `...Response` Pydantic 模型。

### 前端服务层（第 4 项）

4. 在 `frontend/services/modelService.ts` 中新增 `modelService.suggestCapacity(model_name, base_url, provider_hint)`，返回类型化的 `SuggestCapacityResponse`。请求体为 snake_case，响应为 camelCase（沿用现有的 `mapCapacityFieldsFromApi` 风格）。

### 前端表单状态机（第 5-7 项）

5. 在 `ModelCapacityFields.tsx` 中，为每个容量输入增加三种状态：`empty | suggested | operator`。`suggested` 值在标签旁显示小型"建议"标签 chip，文字为灰色/暗淡样式；用户输入或点击"使用建议"将字段提升为 `operator` 样式（现有样式）。当状态已为 `operator` 时拒绝建议写入，防止覆盖用户输入。
6. 在 `ModelAddDialog.tsx`（以及 `ModelEditDialog.tsx` 中如有类似添加流程的部分），在 `model_name` 失焦或 `base_url` 变更后防抖 300 ms，调用 `suggestCapacity`。非 `none` 响应时，将字段填充为 `suggested`。`none` 时保持表单原样，**不**显示错误，空路径即现有行为。
7. 将 `match_explanation` 和 `match_kind` 渲染为容量网格上方的小型可关闭 `Alert`（"建议来自 openai/gpt-4o@1 目录条目"）。使用现有 i18n 键；新增 `model.dialog.capacity.suggestion.*`。

### 前端覆盖所有模型添加路径（第 8 项）

8. **将建议逻辑应用于全部三条添加路径**：
   - `ModelAddDialog`（单模型流程）— 主要目标
   - Provider 浏览流程（当用户从 `ModelDeleteDialog` Provider 列表中启用模型时）— 当现有模型记录缺少容量值时调用建议，以"补充容量"提示展示
   - `ProviderConfigEditDialog`（每个模型的齿轮图标）— 如果 model_record 的容量字段为 null，显示"有可用建议"徽标，点击后通过同一 API 填充

### 错误与 Fallback 处理（第 9 项）

9. 建议端点失败模式：
   - HTTP 5xx / 网络错误 → 记录到控制台，**静默回退**到现有的空表单行为。绝不阻塞添加流程。
   - 200 且 `match_kind: "none"` → 无 UI 变化；与空状态一致。
   - 200 且 `provider_discovery` 匹配，容量值为 `provider_candidate` → 以黄色边框（非绿色）渲染，让运维人员知道其置信度低于目录匹配。

### 国际化（第 10 项）

10. 在 en/zh 中新增 locale 字符串：
    - `model.dialog.capacity.suggestion.title`
    - `model.dialog.capacity.suggestion.matchExact`
    - `model.dialog.capacity.suggestion.matchFuzzy`
    - `model.dialog.capacity.suggestion.matchProviderDiscovery`
    - `model.dialog.capacity.suggestion.useSuggestion`（按钮文字）
    - `model.dialog.capacity.suggestion.candidateWarning`（低置信度提示）

## 代码触点

后端：
- `backend/services/model_capacity_suggestion_service.py`（新增）
- `backend/apps/model_managment_app.py`（新增路由）
- `backend/consts/model.py`（请求/响应 Pydantic）
- `backend/services/model_health_service.py`（将 `_infer_model_factory` 扩展为通过共享主机映射覆盖 LLM）

前端 — **全部三个模型管理对话框**，不仅限于添加：
- `frontend/app/[locale]/models/components/model/ModelAddDialog.tsx`（主要建议流程）
- `frontend/app/[locale]/models/components/model/ModelEditDialog.tsx`（编辑无目录匹配的自定义 OpenAI-API-Compatible 模型时的建议）
- `frontend/app/[locale]/models/components/model/ProviderConfigEditDialog`（通过齿轮图标编辑 Provider 分类模型时的建议，同一对话框组件来源于 `ModelEditDialog.tsx`）
- `frontend/app/[locale]/models/components/model/ModelDeleteDialog.tsx`（Provider 浏览流程：当用户从 Provider 列表中启用模型时，如果后端返回容量提示则展示建议）
- `frontend/app/[locale]/models/components/model/ModelCapacityFields.tsx`（建议占位符渲染、`suggested` vs `operator` 状态）
- `frontend/services/modelService.ts`（新增 `suggestCapacity`）
- 说明文字的 Locale 文件

## 运维依赖

W17 需要后端 + Web 容器协调部署。无数据库迁移。

| 组件 | 操作 | 触发条件 |
| --- | --- | --- |
| `nexent-runtime` / `nexent-northbound` / `nexent-config` / `nexent-mcp` | 镜像重建 + `compose up --force-recreate`（`nexent 代码改动生效流程.md` 中的流程 A） | 后端路由 + 服务新增 |
| `nexent-web` | 镜像重建 + `compose up --force-recreate`（流程 D） | 前端对话框 + 服务变更 |
| `nexent-postgresql` | 无变更 | 无 Schema 迁移 |
| `consts.const` | 新增 `CAPACITY_SUGGESTION_ENABLED` 环境变量 | 新 Feature Flag |
| 租户配置 | 可选：在 `tenant_config_t` 中按租户覆写 `capacity_suggestion_enabled`，支持按租户分阶段发布 | 阶段 2/3 发布 |
| 监控 | 将新端点的 `match_kind` 和延迟指标加入仪表盘 | 阶段 2 观测 |

**发布顺序**：在 staging 全局启用环境变量 → 通过 `tenant_config_t` 为一个内部租户启用 → 观测 1 周 → 为付费租户全局启用 → 观测 1 周 → 全量启用。

**回滚**：设置 `CAPACITY_SUGGESTION_ENABLED=false`。前端隐藏建议 UI；后端路由不再被调用。无需数据迁移，因为 W17 从不自动持久化 `provider_candidate` 值。

## 测试与发布证据

- `_normalize_model_name` 的单元测试，覆盖全部八个目录条目和已记录的变体模式。
- `_pick_provider` 针对主机映射的单元测试。
- 集成测试：POST /suggest-capacity，`gpt-4o` → `catalog_exact`；`Deepseek V4 Flash` → `catalog_fuzzy`；`qwen-some-experimental-model` 配合 dashscope URL → `provider_discovery`（mock）。
- 前端 Playwright（或 Cypress）流程：添加模型，输入 `https://api.openai.com/v1` + `gpt-4o` → 看到四个字段自动填充并带 `provider_candidate` 标签；点击"使用建议" → 标签切换为 `operator`；提交；验证监控记录显示 `capability_profile_version = 'openai/gpt-4o@1'`、`capacity_source = 'operator'`。
- SLO：发布窗口期间至少 70% 的新增手动添加 LLM 行产生 `match_kind != 'none'` 响应。（通过统计 `capacity_source = 'operator'` 且 `capability_profile_version` 非空的行与新增 LLM 总行数之比来度量。）
- 无回归：移除建议端点后，解析器、监控和现有编辑流程仍正常工作。通过禁用 Feature Flag 并运行 W1 端到端测试验证。

## 发布与完成定义

- 阶段 1 在 Feature Flag 后交付，默认关闭。
- 内部试用一周；验证八个目录条目的建议准确性。
- 阶段 2（Provider 发现）以试用证据和限流预算批准为 Gate。
- 阶段 3（扩展 `_infer_model_factory`）以阶段 2 上线 + 一周监控为 Gate。
- 当试用和 SLO 检查连续两周通过且 Feature Flag 已移除时，W17 即视为完成。

## 为什么这不是 W1

W1 的 ADR 明确限定在目录数据模型和解析器契约范围内。"目录如何从真实用户行为中正确填充"是同一问题的另一个层面。将修复移入新的工作流，既保持 W1 的不变量稳定（目录键保持精确匹配；`provider_candidate` 永远不作为权威值），又让 W17 在不必重新协商 W1 的 CM-016 边界的前提下迭代 UX。

参见 `W1_ADR_Capability_Catalog_Storage_and_Fingerprint.md` 的"已知限制"部分，了解本工作流解决的缺口。
