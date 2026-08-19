-- Final pre-production Dreaming schema. This file is the only Dreaming migration.
-- All tables introduced here are created directly with their final definitions.

CREATE TABLE IF NOT EXISTS nexent.memory_dreaming_audit_t (
    run_id BIGSERIAL PRIMARY KEY, tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL, agent_id VARCHAR(100) NOT NULL DEFAULT '',
    trigger_source VARCHAR(30) NOT NULL DEFAULT 'manual', status VARCHAR(30) NOT NULL DEFAULT 'running',
    current_phase VARCHAR(30), started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP, light_count INTEGER NOT NULL DEFAULT 0, rem_count INTEGER NOT NULL DEFAULT 0,
    promoted_count INTEGER NOT NULL DEFAULT 0, deferred_count INTEGER NOT NULL DEFAULT 0,
    published_version_id BIGINT,
    reason VARCHAR(100), error TEXT, lock_owner VARCHAR(100), lock_until TIMESTAMP,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100), updated_by VARCHAR(100), delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);
CREATE INDEX IF NOT EXISTS idx_memory_dreaming_audit_scope
    ON nexent.memory_dreaming_audit_t (tenant_id, user_id, agent_id, started_at DESC);

CREATE TABLE IF NOT EXISTS nexent.memory_dreaming_decision_t (
    decision_id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES nexent.memory_dreaming_audit_t(run_id) ON DELETE CASCADE,
    decision_order INTEGER NOT NULL, memory_id BIGINT NOT NULL, score DOUBLE PRECISION NOT NULL,
    noise BOOLEAN NOT NULL DEFAULT FALSE, signal_count INTEGER NOT NULL DEFAULT 0,
    context_diversity INTEGER NOT NULL DEFAULT 0, evidence_ids VARCHAR(100)[] NOT NULL DEFAULT '{}',
    event VARCHAR(20) NOT NULL, reason VARCHAR(100) NOT NULL,
    archive_suggested BOOLEAN NOT NULL DEFAULT FALSE,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100), updated_by VARCHAR(100), delete_flag VARCHAR(1) NOT NULL DEFAULT 'N',
    CONSTRAINT uq_memory_dreaming_decision_run_order UNIQUE (run_id, decision_order)
);
CREATE INDEX IF NOT EXISTS idx_memory_dreaming_decision_memory
    ON nexent.memory_dreaming_decision_t (memory_id);

CREATE TABLE IF NOT EXISTS nexent.memory_dreaming_schedule_t (
    schedule_id BIGSERIAL PRIMARY KEY, tenant_id VARCHAR(100) NOT NULL, user_id VARCHAR(100) NOT NULL,
    agent_id VARCHAR(100) NOT NULL DEFAULT '', enabled BOOLEAN NOT NULL DEFAULT FALSE,
    rule_type VARCHAR(20) NOT NULL DEFAULT 'CRON', timezone VARCHAR(100) NOT NULL DEFAULT 'Asia/Shanghai',
    start_at TIMESTAMP NOT NULL, cron_expr VARCHAR(100), interval_seconds INTEGER, next_fire_at TIMESTAMP,
    last_fire_at TIMESTAMP, fire_count INTEGER NOT NULL DEFAULT 0, min_score DOUBLE PRECISION,
    min_recall_count INTEGER, min_unique_queries INTEGER, source_limit INTEGER, long_term_max_chars INTEGER,
    summarization_max_attempts INTEGER, create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, created_by VARCHAR(100), updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N', CONSTRAINT ck_memory_dreaming_schedule_rule CHECK (
        (rule_type = 'CRON' AND cron_expr IS NOT NULL AND interval_seconds IS NULL) OR
        (rule_type = 'INTERVAL' AND cron_expr IS NULL AND interval_seconds >= 3600))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_dreaming_schedule_scope
    ON nexent.memory_dreaming_schedule_t (tenant_id, user_id, agent_id);
CREATE INDEX IF NOT EXISTS idx_memory_dreaming_schedule_due
    ON nexent.memory_dreaming_schedule_t (enabled, next_fire_at) WHERE delete_flag = 'N';

-- Destructive replacement of unpublished tenant/user lists and legacy Dreaming artifacts.
DELETE FROM nexent.memory_records_t WHERE layer IN ('tenant', 'user');
ALTER TABLE nexent.memory_records_t DROP CONSTRAINT IF EXISTS ck_memory_records_agent_short_term;
ALTER TABLE nexent.memory_records_t ADD CONSTRAINT ck_memory_records_agent_short_term
    CHECK (layer = 'agent' AND memory_type = 'short_term');

DROP TABLE IF EXISTS nexent.memory_dreaming_activation_audit_t;
DROP TABLE IF EXISTS nexent.memory_dreaming_version_t;
DROP TABLE IF EXISTS nexent.memory_long_term_activation_audit_t;

UPDATE nexent.memory_dreaming_schedule_t
SET last_fire_at = NULL, fire_count = 0
WHERE last_fire_at IS NOT NULL OR fire_count <> 0;

CREATE TABLE IF NOT EXISTS nexent.memory_long_term_version_t (
    version_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    scope VARCHAR(20) NOT NULL CHECK (scope IN ('tenant', 'user')),
    subject_id VARCHAR(100) NOT NULL,
    version_no INTEGER NOT NULL,
    parent_version_id BIGINT,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    content TEXT NOT NULL,
    source VARCHAR(20) NOT NULL CHECK (source IN ('manual', 'dreaming')),
    author_user_id VARCHAR(100) NOT NULL,
    editor_user_id VARCHAR(100) NOT NULL,
    authored_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dreaming_run_id BIGINT,
    character_count INTEGER NOT NULL,
    raw_dreaming_input TEXT,
    generation_audit JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    fallback_details JSONB NOT NULL DEFAULT '{}'::jsonb,
    omission_details JSONB NOT NULL DEFAULT '{}'::jsonb,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100), updated_by VARCHAR(100), delete_flag VARCHAR(1) DEFAULT 'N'
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_long_term_version_scope_no
    ON nexent.memory_long_term_version_t (tenant_id, scope, subject_id, version_no);
CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_long_term_active_scope
    ON nexent.memory_long_term_version_t (tenant_id, scope, subject_id)
    WHERE is_active AND delete_flag = 'N';
CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_long_term_run
    ON nexent.memory_long_term_version_t (dreaming_run_id) WHERE dreaming_run_id IS NOT NULL;

INSERT INTO nexent.role_permission_t (
    role_permission_id, user_role, permission_category, permission_type, permission_subtype
) VALUES
    (224, 'SU', 'RESOURCE', 'DREAMING', 'VIEW_TENANT'),
    (225, 'SU', 'RESOURCE', 'DREAMING', 'EDIT_TENANT'),
    (222, 'ADMIN', 'RESOURCE', 'DREAMING', 'VIEW_TENANT'),
    (223, 'ADMIN', 'RESOURCE', 'DREAMING', 'EDIT_TENANT'),
    (226, 'ASSET_OWNER', 'RESOURCE', 'DREAMING', 'VIEW_TENANT'),
    (227, 'ASSET_OWNER', 'RESOURCE', 'DREAMING', 'EDIT_TENANT')
ON CONFLICT (role_permission_id) DO UPDATE SET
    user_role = EXCLUDED.user_role, permission_category = EXCLUDED.permission_category,
    permission_type = EXCLUDED.permission_type, permission_subtype = EXCLUDED.permission_subtype;
