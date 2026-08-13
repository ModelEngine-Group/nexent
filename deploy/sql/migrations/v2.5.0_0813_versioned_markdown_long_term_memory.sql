-- Final pre-production Dreaming schema. This file is the only Dreaming migration.
-- Upgrade unpublished intermediate schemas before the complete CREATE definitions.
-- On a fresh installation none of these tables exist, so this block performs no ALTERs.
DO $$ BEGIN
    IF to_regclass('nexent.memory_dreaming_audit_t') IS NOT NULL THEN
        ALTER TABLE nexent.memory_dreaming_audit_t
            ADD COLUMN IF NOT EXISTS lock_owner VARCHAR(100),
            ADD COLUMN IF NOT EXISTS lock_until TIMESTAMP,
            ADD COLUMN IF NOT EXISTS decisions JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS published_version_id BIGINT,
            ADD COLUMN IF NOT EXISTS reason VARCHAR(100);

        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'nexent'
            AND table_name = 'memory_dreaming_audit_t' AND column_name = 'result_json') THEN
            UPDATE nexent.memory_dreaming_audit_t
            SET decisions = COALESCE(result_json -> 'decisions', '[]'::jsonb),
                published_version_id = CASE
                    WHEN result_json #>> '{version,version_id}' ~ '^[0-9]+$'
                    THEN (result_json #>> '{version,version_id}')::BIGINT
                    ELSE NULL
                END,
                reason = result_json ->> 'reason';
            ALTER TABLE nexent.memory_dreaming_audit_t DROP COLUMN result_json;
        END IF;
        ALTER TABLE nexent.memory_dreaming_audit_t ALTER COLUMN agent_id SET DEFAULT '';
    END IF;

    IF to_regclass('nexent.memory_dreaming_schedule_t') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'nexent'
            AND table_name = 'memory_dreaming_schedule_t' AND column_name = 'compression_max_attempts')
           AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'nexent'
            AND table_name = 'memory_dreaming_schedule_t' AND column_name = 'summarization_max_attempts') THEN
            ALTER TABLE nexent.memory_dreaming_schedule_t
                RENAME COLUMN compression_max_attempts TO summarization_max_attempts;
        END IF;
        ALTER TABLE nexent.memory_dreaming_schedule_t
            ADD COLUMN IF NOT EXISTS min_score DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS min_recall_count INTEGER,
            ADD COLUMN IF NOT EXISTS min_unique_queries INTEGER,
            ADD COLUMN IF NOT EXISTS source_limit INTEGER,
            ADD COLUMN IF NOT EXISTS long_term_max_chars INTEGER,
            ADD COLUMN IF NOT EXISTS summarization_max_attempts INTEGER;
        ALTER TABLE nexent.memory_dreaming_schedule_t ALTER COLUMN agent_id SET DEFAULT '';
    END IF;

END $$;

CREATE TABLE IF NOT EXISTS nexent.memory_dreaming_audit_t (
    run_id BIGSERIAL PRIMARY KEY, tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL, agent_id VARCHAR(100) NOT NULL DEFAULT '',
    trigger_source VARCHAR(30) NOT NULL DEFAULT 'manual', status VARCHAR(30) NOT NULL DEFAULT 'running',
    current_phase VARCHAR(30), started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP, light_count INTEGER NOT NULL DEFAULT 0, rem_count INTEGER NOT NULL DEFAULT 0,
    promoted_count INTEGER NOT NULL DEFAULT 0, deferred_count INTEGER NOT NULL DEFAULT 0,
    decisions JSONB NOT NULL DEFAULT '[]'::jsonb, published_version_id BIGINT,
    reason VARCHAR(100), error TEXT, lock_owner VARCHAR(100), lock_until TIMESTAMP,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100), updated_by VARCHAR(100), delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);
CREATE INDEX IF NOT EXISTS idx_memory_dreaming_audit_scope
    ON nexent.memory_dreaming_audit_t (tenant_id, user_id, agent_id, started_at DESC);

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
    (1004, 'SU', 'RESOURCE', 'DREAMING', 'VIEW_TENANT'),
    (1005, 'SU', 'RESOURCE', 'DREAMING', 'EDIT_TENANT'),
    (1116, 'ADMIN', 'RESOURCE', 'DREAMING', 'VIEW_TENANT'),
    (1117, 'ADMIN', 'RESOURCE', 'DREAMING', 'EDIT_TENANT'),
    (1514, 'ASSET_OWNER', 'RESOURCE', 'DREAMING', 'VIEW_TENANT'),
    (1515, 'ASSET_OWNER', 'RESOURCE', 'DREAMING', 'EDIT_TENANT')
ON CONFLICT (role_permission_id) DO UPDATE SET
    user_role = EXCLUDED.user_role, permission_category = EXCLUDED.permission_category,
    permission_type = EXCLUDED.permission_type, permission_subtype = EXCLUDED.permission_subtype;
