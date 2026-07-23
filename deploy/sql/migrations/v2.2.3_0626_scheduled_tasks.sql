-- ============================================================
-- Scheduled Tasks Schema
-- Migration Date: 2026-06-26
-- Adds the scheduled_tasks_t table backing the ScheduledTaskTool
-- (deferred / recurring agent execution).
-- ============================================================

CREATE TABLE IF NOT EXISTS nexent.scheduled_tasks_t (
    task_id SERIAL PRIMARY KEY,
    task_uuid VARCHAR(36) NOT NULL UNIQUE,
    task_name VARCHAR(200),
    task_prompt TEXT NOT NULL,
    task_type VARCHAR(10) NOT NULL,
    cron_expression VARCHAR(100),
    delay_seconds INTEGER,
    status VARCHAR(20) DEFAULT 'pending',
    next_fire_time TIMESTAMP,
    fire_count INTEGER DEFAULT 0,
    max_fires INTEGER,
    agent_id INTEGER NOT NULL,
    conversation_id INTEGER,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    delete_flag VARCHAR(1) DEFAULT 'N',
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS ix_scheduled_task_status_next_fire
    ON nexent.scheduled_tasks_t (status, next_fire_time);
CREATE INDEX IF NOT EXISTS ix_scheduled_task_agent_delete
    ON nexent.scheduled_tasks_t (agent_id, delete_flag);

COMMENT ON TABLE nexent.scheduled_tasks_t IS 'Scheduled task records for deferred and recurring agent execution';
COMMENT ON COLUMN nexent.scheduled_tasks_t.task_uuid IS 'Unique task identifier (UUID)';
COMMENT ON COLUMN nexent.scheduled_tasks_t.task_type IS 'Task type: oneshot or cron';
COMMENT ON COLUMN nexent.scheduled_tasks_t.cron_expression IS 'Cron expression for recurring tasks';
COMMENT ON COLUMN nexent.scheduled_tasks_t.delay_seconds IS 'Delay in seconds for oneshot tasks';
COMMENT ON COLUMN nexent.scheduled_tasks_t.status IS 'Task status: pending, fired, cancelled, error';
COMMENT ON COLUMN nexent.scheduled_tasks_t.next_fire_time IS 'Next scheduled execution time';
COMMENT ON COLUMN nexent.scheduled_tasks_t.fire_count IS 'Number of times this task has fired';
COMMENT ON COLUMN nexent.scheduled_tasks_t.max_fires IS 'Maximum number of fires (NULL = unlimited)';
