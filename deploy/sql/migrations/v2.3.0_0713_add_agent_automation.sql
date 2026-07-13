-- Add durable scheduled agent tasks, run history, chat proposals, and navigation permissions.

SET search_path TO nexent;

BEGIN;

CREATE TABLE IF NOT EXISTS nexent.agent_automation_task_t (
    task_id BIGSERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    conversation_id BIGINT NOT NULL,
    agent_id BIGINT NOT NULL,
    agent_version_no INTEGER,
    title VARCHAR(255) NOT NULL,
    instruction TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    source VARCHAR(32) NOT NULL,
    schedule_mode VARCHAR(16) NOT NULL,
    schedule_rule_type VARCHAR(16) NOT NULL,
    schedule_expr TEXT,
    schedule_config JSONB NOT NULL,
    capability_requirements JSONB,
    capability_bindings JSONB,
    runtime_snapshot JSONB,
    timezone VARCHAR(64) NOT NULL,
    next_fire_at TIMESTAMPTZ,
    last_fire_at TIMESTAMPTZ,
    fire_count INTEGER NOT NULL DEFAULT 0,
    last_run_status VARCHAR(32),
    last_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    timeout_seconds INTEGER NOT NULL,
    overlap_policy VARCHAR(16) NOT NULL,
    misfire_policy VARCHAR(16) NOT NULL,
    lock_owner VARCHAR(128),
    lock_until TIMESTAMPTZ,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE IF NOT EXISTS nexent.agent_automation_run_t (
    run_id BIGSERIAL PRIMARY KEY NOT NULL,
    task_id BIGINT NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    conversation_id BIGINT NOT NULL,
    scheduled_fire_at TIMESTAMPTZ NOT NULL,
    actual_fire_at TIMESTAMPTZ,
    trigger_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    generated_prompt TEXT,
    user_message_id BIGINT,
    assistant_message_id BIGINT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    duration_ms BIGINT,
    error_code VARCHAR(64),
    error_message TEXT,
    capability_check JSONB,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE IF NOT EXISTS nexent.agent_automation_proposal_t (
    proposal_id BIGSERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    conversation_id BIGINT NOT NULL,
    agent_id BIGINT NOT NULL,
    proposed_task JSONB NOT NULL,
    capability_resolution JSONB NOT NULL,
    status VARCHAR(32) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS idx_agent_automation_due
    ON nexent.agent_automation_task_t (status, next_fire_at)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_agent_automation_owner
    ON nexent.agent_automation_task_t (tenant_id, user_id, status)
    WHERE delete_flag = 'N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_automation_conversation_active
    ON nexent.agent_automation_task_t (conversation_id)
    WHERE delete_flag = 'N' AND status <> 'DELETED';

CREATE INDEX IF NOT EXISTS idx_agent_automation_run_task
    ON nexent.agent_automation_run_t (task_id, scheduled_fire_at)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_agent_automation_run_conversation
    ON nexent.agent_automation_run_t (conversation_id, status)
    WHERE delete_flag = 'N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_automation_active_occurrence
    ON nexent.agent_automation_run_t (task_id, scheduled_fire_at)
    WHERE delete_flag = 'N'
      AND trigger_type = 'SCHEDULED'
      AND status IN ('QUEUED', 'RUNNING');

CREATE INDEX IF NOT EXISTS idx_agent_automation_proposal_owner
    ON nexent.agent_automation_proposal_t (tenant_id, user_id, status)
    WHERE delete_flag = 'N';

-- The menu schema was introduced by v2.2.2_0622_update_left_nav_menu.sql.
-- Synchronize the sequence because that migration inserted explicit IDs.
SELECT setval(
    pg_get_serial_sequence('nexent.role_permission_t', 'role_permission_id'),
    COALESCE(MAX(role_permission_id), 0) + 1,
    false
)
FROM nexent.role_permission_t;

INSERT INTO nexent.role_permission_t (
    user_role,
    permission_category,
    permission_type,
    permission_subtype,
    parent_key
)
SELECT role_name, 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-tasks', NULL
FROM unnest(ARRAY['SU', 'ADMIN', 'DEV', 'USER', 'SPEED', 'ASSET_OWNER']) AS roles(role_name)
WHERE NOT EXISTS (
    SELECT 1
    FROM nexent.role_permission_t existing
    WHERE existing.user_role = roles.role_name
      AND existing.permission_category = 'VISIBILITY'
      AND existing.permission_type = 'LEFT_NAV_MENU'
      AND existing.permission_subtype = '/agent-tasks'
);

COMMIT;
