
### Requirement: 系统 SHALL 检测并记录故障率告警
系统 SHALL 在每次 LLM 调用完成后，检查该模型在最近 5 分钟内的故障率。当总请求数 ≥ 10 且故障率 > `HIGH_FAILURE_RATE_THRESHOLD`（默认 1%）时，系统 SHALL 创建一条 `failure_rate_high` 类型、`critical` 严重级别的告警记录。同一模型同一告警类型在 5 分钟窗口内 SHALL NOT 重复创建告警。

#### Scenario: 故障率超过阈值触发告警
- **WHEN** 模型 `gpt-4o` 在最近 5 分钟内收到 100 个请求，其中 3 个为不可恢复故障（故障率 3%），阈值为 1%
- **THEN** 系统 SHALL 创建一条 `failure_rate_high` 告警，`severity` 为 `critical`，`metric_value` 为 0.03，`threshold_value` 为 0.01

#### Scenario: 请求数不足不触发告警
- **WHEN** 模型在最近 5 分钟内仅收到 5 个请求，其中 2 个为故障（故障率 40%）
- **THEN** 系统 SHALL NOT 创建告警（低于最小请求数阈值 10）

#### Scenario: 告警去重生效
- **WHEN** 模型 A 在 3 分钟前已触发 `failure_rate_high` 告警，当前检查故障率仍超阈值
- **THEN** 系统 SHALL NOT 创建新的告警记录（5 分钟去重窗口内）

### Requirement: 系统 SHALL 检测并记录错误率告警
系统 SHALL 检查模型在最近 5 分钟内的错误率（可恢复错误）。当总请求数 ≥ 10 且错误率 > `HIGH_ERROR_RATE_THRESHOLD`（默认 5%）时，系统 SHALL 创建一条 `error_rate_high` 类型、`warning` 严重级别的告警记录，遵循相同的 5 分钟去重规则。

#### Scenario: 错误率超过阈值触发告警
- **WHEN** 模型在最近 5 分钟内收到 100 个请求，其中 8 个为可恢复错误（错误率 8%），阈值为 5%
- **THEN** 系统 SHALL 创建一条 `error_rate_high` 告警，`severity` 为 `warning`

### Requirement: 系统 SHALL 检测并记录慢请求告警
系统 SHALL 在每次 LLM 调用完成后检查请求耗时。当请求耗时 > `SLOW_REQUEST_THRESHOLD_MS`（默认 5000ms）时，系统 SHALL 创建一条 `slow_request` 类型、`warning` 严重级别的告警记录，遵循相同的去重规则。

#### Scenario: 慢请求触发告警
- **WHEN** LLM 调用耗时 6500ms，阈值为 5000ms
- **THEN** 系统 SHALL 创建一条 `slow_request` 告警，`metric_value` 为 6500，`metric_unit` 为 `ms`

### Requirement: 系统 SHALL 检测并记录质量低分告警
系统 SHALL 在收到用户质量评分时检查。当最近 10 次评分的平均值 < `LOW_QUALITY_SCORE_THRESHOLD`（默认 60）时，系统 SHALL 创建一条 `quality_low` 类型、`warning` 严重级别的告警记录。

#### Scenario: 质量评分低于阈值触发告警
- **WHEN** 某模型最近 10 次评分平均值为 45 分，阈值为 60
- **THEN** 系统 SHALL 创建一条 `quality_low` 告警

### Requirement: 系统 SHALL 通过环境变量配置告警阈值
所有告警阈值 SHALL 通过环境变量配置：`SLOW_REQUEST_THRESHOLD_MS`、`HIGH_ERROR_RATE_THRESHOLD`、`HIGH_FAILURE_RATE_THRESHOLD`、`LOW_QUALITY_SCORE_THRESHOLD`、`HIGH_RETRY_RATE_THRESHOLD`、`ALERT_DEDUP_WINDOW_MINUTES`。当环境变量未设置时 SHALL 使用默认值。

#### Scenario: 自定义故障率阈值
- **WHEN** 设置 `HIGH_FAILURE_RATE_THRESHOLD=0.02`（2%）
- **THEN** 故障率超过 2% 时才触发 `failure_rate_high` 告警
