
### Requirement: 系统 SHALL 采集故障率指标
系统 SHALL 在每次 LLM 调用失败时，将错误分类为可恢复错误（`is_error`）或不可恢复故障（`is_failure`）。不可恢复故障类型 SHALL 包括：`auth_failure`（401/403）、`model_not_found`（404）、`invalid_response`（响应解析失败）、`quota_exceeded`（配额超限）、`content_filter`（内容过滤）。可恢复错误类型 SHALL 包括：`rate_limit`（429）、`timeout`、`service_unavailable`（502/503/504）、`network_error`。系统 SHALL 通过 `llm_failure_count` Counter 指标按 `model`、`failure_type`、`tenant_id`、`agent_id` 标签记录不可恢复故障计数。

#### Scenario: 认证失败被归类为不可恢复故障
- **WHEN** LLM 调用返回 HTTP 401 或错误消息包含 "api key" 或 "unauthorized"
- **THEN** 系统 SHALL 记录 `llm_failure_count` 指标，`failure_type` 标签为 `auth_failure`，`is_failure` 设为 `True`，`is_error` 设为 `False`

#### Scenario: 限流被归类为可恢复错误而非故障
- **WHEN** LLM 调用返回 HTTP 429 或错误消息包含 "rate limit"
- **THEN** 系统 SHALL 记录 `llm_error_count` 指标，`error_type` 标签为 `rate_limit`，`is_error` 设为 `True`，`is_failure` 设为 `False`

#### Scenario: 未知错误默认归类为不可恢复故障
- **WHEN** LLM 调用失败且错误消息不匹配任何已知模式
- **THEN** 系统 SHALL 记录 `llm_failure_count` 指标，`failure_type` 标签为 `unknown_failure`

### Requirement: 系统 SHALL 采集请求总数指标
系统 SHALL 在每次 LLM 调用结束时（无论成功或失败）递增 `llm_request_total` Counter 指标，标签包含 `model`、`tenant_id`、`agent_id`、`operation`、`status`（`success`/`error`/`failure`）。

#### Scenario: 成功请求计数
- **WHEN** LLM 调用成功返回完整响应
- **THEN** 系统 SHALL 递增 `llm_request_total`，`status` 标签为 `success`

#### Scenario: 故障请求计数
- **WHEN** LLM 调用发生不可恢复故障
- **THEN** 系统 SHALL 递增 `llm_request_total`，`status` 标签为 `failure`

### Requirement: 系统 SHALL 采集成本指标
系统 SHALL 在每次 LLM 调用完成时计算成本并记录到 `llm_cost_total` Counter 指标。成本计算公式为：`(input_tokens / 1,000,000) × input_price_per_1m + (output_tokens / 1,000,000) × output_price_per_1m`。系统 SHALL 维护主流模型的默认单价映射，并支持从数据库 `model_record_t` 表的 `input_price_per_1m` 和 `output_price_per_1m` 字段读取自定义单价，数据库值优先。

#### Scenario: 使用默认单价计算成本
- **WHEN** LLM 调用使用 `gpt-4o` 模型完成，消耗 1000 input tokens 和 500 output tokens，且数据库无自定义单价
- **THEN** 系统 SHALL 计算成本为 `(1000/1000000) × 2.50 + (500/1000000) × 10.00 = 0.0075 USD`

#### Scenario: 数据库自定义单价覆盖默认值
- **WHEN** 数据库 `model_record_t` 中某模型设置了 `input_price_per_1m = 5.0`
- **THEN** 系统 SHALL 使用 5.0 而非默认映射中的值计算输入成本

### Requirement: 系统 SHALL 采集并发请求指标
系统 SHALL 维护 `llm_concurrent_requests` Gauge 指标，在 LLM 调用开始时 +1，调用结束时 -1（无论成功或失败）。标签包含 `model` 和 `tenant_id`。

#### Scenario: 并发请求正确增减
- **WHEN** 模型 A 同时有 3 个正在进行的请求
- **THEN** `llm_concurrent_requests{model="A"}` SHALL 为 3；当其中一个请求完成时 SHALL 变为 2

### Requirement: 系统 SHALL 在 LLM 调用链路中注入监控采集
系统 SHALL 在 `backend/utils/llm_utils.py` 的 `call_llm_for_system_prompt` 函数以及通过 `OpenAIModel` 实例发起的 LLM 调用中注入监控数据采集逻辑。当 `ENABLE_MODEL_MONITORING` 环境变量为 `false` 时，所有监控采集 SHALL 被跳过且不影响原有功能。

#### Scenario: 监控采集正确记录全链路数据
- **WHEN** 用户通过前端发起对话，触发 LLM 调用
- **THEN** 系统 SHALL 在调用开始记录并发数+1和请求开始时间，在收到第一个 Token 时记录 TTFT，在流式完成时记录总耗时和 Token 数，在发生错误时分类并记录

#### Scenario: 监控关闭时不影响原有功能
- **WHEN** `ENABLE_MODEL_MONITORING=false`
- **THEN** 系统 SHALL 完全跳过所有监控数据采集代码，LLM 调用行为与未安装监控时一致
