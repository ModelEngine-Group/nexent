CREATE TABLE IF NOT EXISTS nexent.memory_dreaming_schedule_t (
    schedule_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    agent_id VARCHAR(100) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    rule_type VARCHAR(20) NOT NULL DEFAULT 'CRON',
    timezone VARCHAR(100) NOT NULL DEFAULT 'Asia/Shanghai',
    start_at TIMESTAMP NOT NULL,
    cron_expr VARCHAR(100),
    interval_seconds INTEGER,
    next_fire_at TIMESTAMP,
    last_fire_at TIMESTAMP,
    fire_count INTEGER NOT NULL DEFAULT 0,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N',
    CONSTRAINT ck_memory_dreaming_schedule_rule CHECK (
        (rule_type = 'CRON' AND cron_expr IS NOT NULL AND interval_seconds IS NULL)
        OR
        (rule_type = 'INTERVAL' AND cron_expr IS NULL AND interval_seconds >= 3600)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_dreaming_schedule_scope
    ON nexent.memory_dreaming_schedule_t (tenant_id, user_id, agent_id);
CREATE INDEX IF NOT EXISTS idx_memory_dreaming_schedule_due
    ON nexent.memory_dreaming_schedule_t (enabled, next_fire_at)
    WHERE delete_flag = 'N';
