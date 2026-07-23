-- Manual Dreaming run audit. Advisory locks are transaction-scoped and
-- therefore require no persistent lock table.
SET search_path TO nexent;
BEGIN;

CREATE TABLE IF NOT EXISTS nexent.memory_dreaming_audit_t (
    run_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    agent_id VARCHAR(100) NOT NULL,
    trigger_source VARCHAR(30) NOT NULL DEFAULT 'manual',
    status VARCHAR(30) NOT NULL DEFAULT 'running',
    current_phase VARCHAR(30),
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    light_count INTEGER NOT NULL DEFAULT 0,
    rem_count INTEGER NOT NULL DEFAULT 0,
    promoted_count INTEGER NOT NULL DEFAULT 0,
    deferred_count INTEGER NOT NULL DEFAULT 0,
    result_json JSONB,
    error TEXT,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS idx_memory_dreaming_audit_scope
    ON nexent.memory_dreaming_audit_t
    (tenant_id, user_id, agent_id, started_at DESC);

COMMIT;
