# W1：正确的模型 Token 容量配置

## 目标

用显式的模型容量字段和统一的解析器替代含义模糊的 `max_tokens` 契约，为每次模型请求提供可信的容量数据。这是正确执行压缩、输出预留和最终适配检查的前置条件。

## 现状与范围

`backend/database/db_models.py` 将 `ModelRecord.max_tokens` 描述为总可用 Token 数，而 `sdk/nexent/core/agents/agent_model.py` 和 `sdk/nexent/core/models/openai_llm.py` 将其用作补全输出上限。`backend/agents/create_agent_info.py` 还将该数据库值用作上下文阈值。W1 修正数据库、后端 API、Provider 发现、SDK 配置、前端模型表单和监控中的聊天/LLM 容量语义。当前复用 `max_tokens` 的 Embedding 模型维度不在范围内，必须在单独迁移前保持现有行为。

## 目标契约

在模型记录和 SDK `ModelConfig` 中新增以下可选字段：

| 字段 | 数据库 / SDK 类型 | 契约 |
| --- | --- | --- |
| `context_window_tokens` | 可空正整数 | 输入/输出合计窗口（如适用） |
| `max_input_tokens` | 可空正整数 | Provider 硬输入上限（如与之不同） |
| `max_output_tokens` | 可空正整数 | Provider 支持或运维配置的输出上限 |
| `default_output_reserve_tokens` | 可空正整数 | 每次请求预留的默认输出额度 |
| `tokenizer_family` | 可空字符串，最长 100 字符 | Tokenizer/计数适配器标识 |
| `capacity_source` | 可空枚举/字符串：`operator`、`profile`、`provider_candidate`、`legacy`、`unknown` | 持久化或解析后容量值的来源 |
| `capability_profile_version` | 可空字符串，最长 100 字符 | 请求所使用的已批准 Provider/模型能力 Profile 版本 |

迁移期间保留 `max_tokens` 作为 `max_output_tokens` 的已弃用 API/数据库别名。它绝不能用于填充 `ContextManagerConfig.token_threshold`。

## 设计

在 SDK 模型层创建 `ModelCapacityResolver`，为每个正式支持的 Provider/模型或部署 ID 维护一个小型版本化能力 Profile。该 Profile 仅包含 W1-W10 和 W3 所需的能力：硬容量字段、Token 计数模式/Tokenizer 族、推理窗口行为、Provider 开销行为、Prompt 缓存模式和缓存指标可用性。

解析优先级为：已批准的运维覆盖、已批准的版本化能力 Profile、Provider 发现作为未验证的候选元数据，最后为 unknown。Provider 发现在被批准进入 Profile 版本之前，绝不改变生产行为。每次请求记录所选 Profile 版本和字段来源。

拒绝不可能的值：非正容量、输出上限超过合计窗口、输入上限超过合计窗口且无 Provider 显式例外、预留超过可用容量。未知的硬容量不允许用于生产调度，返回 `provider_capability_unknown`。当硬容量已知但任何必需的 Tokenizer、推理或 Provider 开销行为未知时，W2 应用已批准的统一不确定性预留。

此初始 Profile 是配置，而非通用的 Provider 能力发现平台。它仅覆盖受支持的生产模型，不会自动抓取、探测或信任所有 Provider/模型能力。

Nexent 继续允许用户配置不在平台维护的 Profile 目录中的模型。该目录是已批准默认值的来源，而非模型白名单。对于未入目录的模型，由授权模型配置提供硬容量字段。当这些字段解析为有效的已知硬容量时允许生产调度；否则以 `provider_capability_unknown` 失败。不完整的 Tokenizer、推理窗口或 Provider 开销行为使用 W2 的不确定性规则。

## 运行时契约

```text
resolve_capacity(model_id, provider, operator_overrides, requested_output_tokens)
  -> ModelCapacitySnapshot
```

`ModelCapacitySnapshot` 是不可变/冻结的 SDK 模型，包含：

| 字段 | 类型 / 规则 |
| --- | --- |
| `model_record_id` | 可空整数 |
| `provider`、`model_name` | 标识所选部署的必填字符串 |
| `context_window_tokens`、`max_input_tokens`、`max_output_tokens`、`default_output_reserve_tokens` | 可空正整数 |
| `requested_output_tokens` | 为本次请求解析的必填正整数 |
| `provider_input_limit_tokens` | 必需的硬输入上限派生值 |
| `tokenizer_family` | 可空字符串 |
| `counting_mode` | `exact` 或 `estimated` |
| `unknown_capabilities` | 有界的能力原因码列表 |
| `field_sources` | 从容量字段到来源枚举的有界映射 |
| `capability_profile_version`、`resolver_version` | 分别为可空/必填字符串 |
| `warnings` | 稳定的原因码有界列表 |
| `fingerprint` | 基于解析后契约的确定性必填字符串 |

该快照原样传递给 W2、W10、W3、监控和 Provider 调度。类型化失败包括 `invalid_capacity_configuration`、`provider_capability_unknown`、`uncertainty_reserve_basis_unknown`、`requested_output_exceeds_cap` 和 `provider_metadata_invalid`。

## 数据库迁移契约

遵循仓库现有的 SQL 迁移惯例：

- 在两个全新安装 Schema 中添加可空容量列和注释：`docker/init.sql` 和 `k8s/helm/nexent/charts/nexent-common/files/init.sql`。
- 在 `docker/sql/` 下添加一个版本前缀的幂等升级 SQL 文件，使用 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 和列注释。
- 不要将新的聊天/LLM 容量列用于 Embedding 维度。
- 保持现有行在新字段为 null 时仍然有效；已知模型的回填单独进行，旧版 `max_tokens` 仅作为临时输出上限别名解析。
- 回滚可以恢复旧版读取器，但绝不能将 `max_tokens` 重新解释为上下文容量。

## 迁移、交付物和阶段

- 新增字段先于读取方变更发布；聊天 `max_tokens` 仅作为临时输出上限别名，Embedding 维度在单独迁移前保持现有行为。
- 交付 ADR、迁移脚本、API/SDK 模型、解析器、小型已批准能力 Profile 目录、Provider 适配器、Tokenizer 注册表、前端字段、回填报告和遥测仪表盘。
- 分阶段实施：影子解析、已知模型回填、消费方切换、无效配置强制校验，最后移除旧版聊天模型写入。
- 回滚可以恢复旧版读取，但绝不能将 `max_tokens` 恢复为上下文容量。

## 实施计划

1. 添加 ADR，定义字段语义、能力 Profile 优先级、未知行为和迁移方案。
2. 添加可空数据库列，更新模型管理 CRUD/服务 Schema。
3. 更新 Provider 发现适配器，返回显式容量元数据。
4. 扩展 SDK `ModelConfig`；将内部 LLM 输出上限用法重命名为 `max_output_tokens`。
5. 添加 `ModelCapacityResolver` 和 Tokenizer 适配器注册表。
6. 停止在 `create_agent_info.py` 中将旧版 `max_tokens` 赋值给上下文阈值。
7. 更新前端添加/编辑表单和标签；显示容量来源和警告。
8. 为每次请求添加已解析快照的监控字段。

## W1 到 W2/W10 的交接

- W1 在解析所选模型和请求输出后，为一次模型请求创建恰好一个不可变的 `ModelCapacitySnapshot`。
- W2 消费该快照并返回记录 W1 指纹的预算快照；W2 绝不修改或独立重新解析容量。
- W10 消费两个快照，在适配/序列化或调度之前拒绝缺失或不匹配的 W1 指纹。
- Provider 调度验证所选 Provider/模型、请求输出和 W1 指纹仍与最终请求匹配。

## 代码触点

- `backend/database/db_models.py`
- `backend/database/model_management_db.py`
- `backend/services/model_management_service.py`
- `backend/services/model_provider_service.py`
- `backend/agents/create_agent_info.py`
- `backend/apps/model_managment_app.py`
- `frontend/app/[locale]/models/`
- `frontend/types/modelConfig.ts`
- `sdk/nexent/core/agents/agent_model.py`
- `sdk/nexent/core/models/openai_llm.py`
- `sdk/nexent/core/utils/token_estimation.py`

## 测试与发布证据

- 对合计窗口和独立输入 Provider 的优先级和校验进行单元测试。
- 保留稳定的 Fixture 用例：合计窗口模型、独立输入上限模型、未入目录的运维配置模型、未知硬容量和不完整的必需行为。
- 测试未验证的 Provider 发现不能静默改变生产 Profile，且未知硬容量阻止生产调度。
- 对旧版记录、空字段、覆盖和回滚兼容性进行迁移测试。
- 对后端、前端和 SDK 序列化进行契约测试。
- 断言没有运行时上下文阈值来源于旧版 `max_tokens`。
- 仪表盘证据必须显示总窗口、硬输入上限、输出上限、预留、Tokenizer 族、能力 Profile 版本/来源、未知能力比率和 Provider 上下文长度错误。

## 上线与完成标准

先部署新增列，双读旧版记录，回填目录已知模型，然后将读取切换到解析器。所有客户端迁移完成后才移除旧版写入。当每次聊天模型请求都有经过校验的容量快照，且仓库搜索找不到将旧版 `max_tokens` 用作上下文容量的代码时，W1 即完成。
