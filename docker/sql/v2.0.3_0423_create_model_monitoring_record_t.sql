-- Model Monitoring Record Table
-- Stores per-request LLM performance metrics for the monitoring feature.
-- Run this script against the 'nexent' schema in PostgreSQL.

CREATE TABLE IF NOT EXISTS nexent.model_monitoring_record_t (
    monitoring_id       SERIAL          PRIMARY KEY,
    model_id            INT4,
    model_name          VARCHAR(100)    NOT NULL,
    model_type          VARCHAR(20)     DEFAULT 'llm',
    agent_id            INT4,
    agent_name          VARCHAR(100),
    conversation_id     INT4,
    tenant_id           VARCHAR(100)    NOT NULL,
    user_id             VARCHAR(100),
    display_name        VARCHAR(100),
    request_duration_ms INT4,
    ttft_ms             INT4,
    input_tokens        INT4,
    output_tokens       INT4,
    total_tokens        INT4,
    generation_rate     FLOAT,
    is_streaming        BOOLEAN         DEFAULT FALSE,
    is_success          BOOLEAN         DEFAULT TRUE,
    is_error            BOOLEAN         DEFAULT FALSE,
    error_type          VARCHAR(50),
    error_message       TEXT,
    retry_count         INT4            DEFAULT 0,
    operation           VARCHAR(50),
    create_time         TIMESTAMP       DEFAULT NOW(),
    delete_flag         VARCHAR(1)      DEFAULT 'N'
);

-- Single-column indexes for common query patterns
CREATE INDEX IF NOT EXISTS ix_monitoring_model_id     ON nexent.model_monitoring_record_t (model_id);
CREATE INDEX IF NOT EXISTS ix_monitoring_tenant_id    ON nexent.model_monitoring_record_t (tenant_id);
CREATE INDEX IF NOT EXISTS ix_monitoring_agent_id     ON nexent.model_monitoring_record_t (agent_id);
CREATE INDEX IF NOT EXISTS ix_monitoring_create_time  ON nexent.model_monitoring_record_t (create_time);
CREATE INDEX IF NOT EXISTS ix_monitoring_is_error     ON nexent.model_monitoring_record_t (is_error);
CREATE INDEX IF NOT EXISTS ix_monitoring_model_type   ON nexent.model_monitoring_record_t (model_type);

-- Composite index for time-range queries per model
CREATE INDEX IF NOT EXISTS ix_monitoring_model_time   ON nexent.model_monitoring_record_t (model_id, create_time);
