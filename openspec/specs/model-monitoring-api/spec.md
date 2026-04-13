
### Requirement: 系统 SHALL 提供模型监控列表 API
系统 SHALL 提供 `GET /api/monitoring/models` 端点，返回模型监控概览列表。支持查询参数：`tenant_id`（租户过滤）、`start_time`/`end_time`（ISO8601 时间范围）、`page`/`page_size`（分页）。响应 SHALL 包含每个模型的 `model_id`、`model_name`、`display_name`、`total_requests`、`avg_duration_ms`、`p95_duration_ms`、`avg_ttft_ms`、`error_rate`、`failure_rate`、`total_cost_usd`、`avg_quality_score`。端点 SHALL 通过现有认证中间件鉴权，仅返回当前用户所属租户的数据。

#### Scenario: 获取模型监控列表
- **WHEN** 认证用户请求 `GET /api/monitoring/models?start_time=2026-04-09T00:00:00Z&page_size=20`
- **THEN** 系统 SHALL 返回 200 状态码，响应体包含 `total`、`page`、`page_size`、`items` 字段，每个 item 包含完整的模型监控概览数据

#### Scenario: 未认证请求被拒绝
- **WHEN** 未认证用户请求 `GET /api/monitoring/models`
- **THEN** 系统 SHALL 返回 401 状态码

### Requirement: 系统 SHALL 提供单模型详细统计 API
系统 SHALL 提供 `GET /api/monitoring/models/{model_id}/summary` 端点，返回单个模型的详细统计信息，包含 `performance`（成功率、错误率、故障率、P50/P95/P99 耗时、重试率）、`errors`（按 error_type 和 failure_type 分布）、`tokens`（总输入/输出 Token）、`cost`（总成本、平均每次请求成本）、`quality`（平均评分、满意度率）。

#### Scenario: 获取模型详细统计
- **WHEN** 认证用户请求 `GET /api/monitoring/models/1/summary`
- **THEN** 系统 SHALL 返回 200 状态码，`failure_rate` 字段 SHALL 为不可恢复故障占总请求的比例，`errors.by_failure_type` SHALL 包含各故障类型的计数分布

### Requirement: 系统 SHALL 提供模型趋势数据 API
系统 SHALL 提供 `GET /api/monitoring/models/{model_id}/trend` 端点，支持 `interval` 参数（`5m`/`15m`/`1h`/`6h`/`1d`）和 `start_time`/`end_time` 参数。每个时间点 SHALL 包含 `request_count`、`avg_duration_ms`、`p95_duration_ms`、`error_count`、`failure_count`、`error_rate`、`failure_rate`、`input_tokens`、`output_tokens`、`cost_usd`。

#### Scenario: 获取小时级趋势数据
- **WHEN** 请求 `GET /api/monitoring/models/1/trend?interval=1h&start_time=2026-04-09T00:00:00Z`
- **THEN** 系统 SHALL 返回按小时聚合的趋势数据点列表，每个点包含所有指标字段

### Requirement: 系统 SHALL 提供故障详情 API
系统 SHALL 提供 `GET /api/monitoring/models/{model_id}/failures` 端点，支持 `failure_type` 过滤、时间范围和分页参数。响应 SHALL 包含故障明细列表，每条包含 `monitoring_id`、`failure_type`、`error_message`、`agent_name`、`conversation_id`、`request_duration_ms`、`create_time`。`error_message` 中的 API Key SHALL 被脱敏为 `***`。

#### Scenario: 查询特定故障类型详情
- **WHEN** 请求 `GET /api/monitoring/models/1/failures?failure_type=auth_failure&page_size=20`
- **THEN** 系统 SHALL 仅返回 `auth_failure` 类型的故障记录，错误消息中不包含任何 API Key 信息

#### Scenario: 错误消息自动脱敏
- **WHEN** 原始错误消息为 "Incorrect API key: sk-abc123xyz"
- **THEN** 返回的 `error_message` SHALL 为 "Incorrect API key: ***"

### Requirement: 系统 SHALL 提供告警列表 API
系统 SHALL 提供 `GET /api/monitoring/alerts` 端点，支持 `status`（`active`/`acknowledged`/`resolved`/`all`）、`alert_type`、`severity` 过滤和分页。响应 SHALL 包含告警列表，每条包含 `alert_id`、`alert_type`、`severity`、`model_name`、`metric_value`、`threshold_value`、`status`、`message`、`create_time`。

#### Scenario: 获取活跃告警列表
- **WHEN** 请求 `GET /api/monitoring/alerts?status=active`
- **THEN** 系统 SHALL 仅返回 `status` 为 `active` 的告警记录

### Requirement: 系统 SHALL 提供告警状态更新 API
系统 SHALL 提供 `PUT /api/monitoring/alerts/{alert_id}/acknowledge` 端点将告警状态更新为 `acknowledged`，以及 `PUT /api/monitoring/alerts/{alert_id}/resolve` 端点将告警状态更新为 `resolved`。解决告警时 SHALL 记录 `resolved_by` 和 `resolved_time`。

#### Scenario: 确认告警
- **WHEN** 运维人员请求 `PUT /api/monitoring/alerts/1/acknowledge`
- **THEN** 系统 SHALL 将告警 ID 1 的 `status` 更新为 `acknowledged`

#### Scenario: 解决告警
- **WHEN** 运维人员请求 `PUT /api/monitoring/alerts/1/resolve`
- **THEN** 系统 SHALL 将 `status` 更新为 `resolved`，`resolved_by` 设为当前用户 ID，`resolved_time` 设为当前时间

### 需求：聚合趋势端点
后端 SHALL 提供 `GET /monitoring/trend` 端点，返回时间序列趋势数据。SHALL 接受可选查询参数：`interval`（1h/6h/1d/7d）、`time_range`（24h/7d/30d）和 `model_id`（可选）。当省略 `model_id` 时，响应包含聚合指标及 `models` 对象（含分模型明细）；当提供 `model_id` 时，响应仅返回该模型的指标，不含 `models` 明细。

#### 场景：获取所有模型的聚合趋势
- **WHEN** 客户端发送 `GET /monitoring/trend?time_range=24h&interval=1h` 且不含 `model_id`
- **THEN** 端点返回趋势数据点列表，每个点包含聚合指标和 `models` 对象（含分模型明细）

#### 场景：获取单一模型的趋势
- **WHEN** 客户端发送 `GET /monitoring/trend?time_range=24h&interval=1h&model_id=model-1`
- **THEN** 端点返回仅包含该模型指标的趋势数据点列表，不含 `models` 分模型明细对象
