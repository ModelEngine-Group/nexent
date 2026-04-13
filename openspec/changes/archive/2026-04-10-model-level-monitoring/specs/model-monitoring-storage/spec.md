## ADDED Requirements

### Requirement: 系统 SHALL 创建模型监控记录表
系统 SHALL 创建 `model_monitoring_record_t` 数据库表，包含以下字段：`monitoring_id`（SERIAL 主键）、`model_id`（INT4）、`model_name`（VARCHAR(100)）、`agent_id`（INT4）、`agent_name`（VARCHAR(100)）、`conversation_id`（INT4）、`tenant_id`（VARCHAR(100)）、`user_id`（VARCHAR(100)）、`request_duration_ms`（INT4）、`ttft_ms`（INT4）、`input_tokens`（INT4）、`output_tokens`（INT4）、`total_tokens`（INT4）、`generation_rate`（FLOAT）、`is_streaming`（BOOLEAN）、`is_success`（BOOLEAN）、`is_error`（BOOLEAN）、`is_failure`（BOOLEAN）、`error_type`（VARCHAR(50)）、`failure_type`（VARCHAR(50)）、`error_message`（TEXT）、`retry_count`（INT4）、`cost_usd`（FLOAT）、`input_price_per_1m`（FLOAT）、`output_price_per_1m`（FLOAT）、`quality_score`（FLOAT）、`user_satisfaction`（INT2）、`operation`（VARCHAR(50)）、`create_time`（TIMESTAMP）、`delete_flag`（VARCHAR(1)）。系统 SHALL 在 `model_id`、`tenant_id`、`agent_id`、`create_time`、`is_failure`、`(model_id, create_time)` 上创建索引。

#### Scenario: 监控记录正确插入
- **WHEN** 一次 LLM 调用完成（成功或失败）
- **THEN** 系统 SHALL 将完整的监控记录插入 `model_monitoring_record_t` 表，所有非空字段正确填充

#### Scenario: 故障记录包含故障类型
- **WHEN** LLM 调用发生不可恢复故障（如认证失败）
- **THEN** 记录中 `is_failure` SHALL 为 `True`，`failure_type` SHALL 为具体故障类型（如 `auth_failure`），`is_error` SHALL 为 `False`

### Requirement: 系统 SHALL 创建告警记录表
系统 SHALL 创建 `model_alert_record_t` 数据库表，包含以下字段：`alert_id`（SERIAL 主键）、`alert_type`（VARCHAR(50)）、`severity`（VARCHAR(20)）、`model_id`（INT4）、`model_name`（VARCHAR(100)）、`agent_id`（INT4）、`tenant_id`（VARCHAR(100)）、`metric_value`（FLOAT）、`threshold_value`（FLOAT）、`metric_unit`（VARCHAR(20)）、`status`（VARCHAR(20) DEFAULT 'active'）、`message`（TEXT）、`resolved_by`（VARCHAR(100)）、`resolved_time`（TIMESTAMP）、`create_time`（TIMESTAMP）、`update_time`（TIMESTAMP）、`delete_flag`（VARCHAR(1)）。`status` 枚举值为 `active`/`acknowledged`/`resolved`。系统 SHALL 在 `status`、`model_id`、`tenant_id`、`create_time`、`alert_type` 上创建索引。

#### Scenario: 告警记录正确创建
- **WHEN** 模型故障率超过阈值
- **THEN** 系统 SHALL 在 `model_alert_record_t` 中插入一条记录，`alert_type` 为 `failure_rate_high`，`severity` 为 `critical`，`status` 为 `active`

#### Scenario: 告警状态可更新
- **WHEN** 运维人员确认一条活跃告警
- **THEN** 系统 SHALL 将该记录 `status` 更新为 `acknowledged`

### Requirement: 系统 SHALL 为模型表添加单价字段
系统 SHALL 在 `model_record_t` 表中添加 `input_price_per_1m`（FLOAT）和 `output_price_per_1m`（FLOAT）两个可空字段，默认值为 NULL。

#### Scenario: 自定义单价存储
- **WHEN** 用户为某个模型设置了输入单价为 5.0 USD/1M tokens
- **THEN** 系统 SHALL 将 `input_price_per_1m` 设为 5.0，成本计算时使用此值

### Requirement: 系统 SHALL 批量写入监控记录
系统 SHALL 使用内存缓冲区收集监控记录，按批量大小（默认 100 条）或刷新间隔（默认 30 秒）触发批量 INSERT。批量写入 SHALL 在单次数据库事务中完成。缓冲区参数通过环境变量 `MODEL_MONITORING_BATCH_SIZE` 和 `MODEL_MONITORING_FLUSH_INTERVAL_SECONDS` 配置。

#### Scenario: 批量大小触发写入
- **WHEN** 缓冲区中积累了 100 条监控记录（默认批量大小）
- **THEN** 系统 SHALL 在一次事务中将全部 100 条记录写入数据库

#### Scenario: 刷新间隔触发写入
- **WHEN** 缓冲区中只有 30 条记录但距上次刷新已超过 30 秒
- **THEN** 系统 SHALL 将 30 条记录批量写入数据库
