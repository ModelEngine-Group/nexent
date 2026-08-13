-- Destructive pre-production replacement of tenant/user lists and Dreaming artifacts.
DELETE FROM nexent.memory_records_t WHERE layer IN ('tenant', 'user');
ALTER TABLE nexent.memory_records_t DROP CONSTRAINT IF EXISTS ck_memory_records_agent_short_term;
ALTER TABLE nexent.memory_records_t ADD CONSTRAINT ck_memory_records_agent_short_term
    CHECK (layer = 'agent' AND memory_type = 'short_term');

DROP TABLE IF EXISTS nexent.memory_dreaming_activation_audit_t;
DROP TABLE IF EXISTS nexent.memory_dreaming_version_t;

ALTER TABLE nexent.memory_dreaming_schedule_t
    RENAME COLUMN compression_max_attempts TO summarization_max_attempts;
UPDATE nexent.memory_dreaming_audit_t
SET current_phase = 'summarization'
WHERE current_phase = 'compression';

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

CREATE TABLE IF NOT EXISTS nexent.memory_long_term_activation_audit_t (
    activation_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL, scope VARCHAR(20) NOT NULL,
    subject_id VARCHAR(100) NOT NULL, actor_user_id VARCHAR(100) NOT NULL,
    from_version_id BIGINT, to_version_id BIGINT NOT NULL, action VARCHAR(30) NOT NULL,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100), updated_by VARCHAR(100), delete_flag VARCHAR(1) DEFAULT 'N'
);
CREATE INDEX IF NOT EXISTS idx_memory_long_term_activation_scope
    ON nexent.memory_long_term_activation_audit_t (tenant_id, scope, subject_id, create_time);

-- Old result payloads may reference discarded version ids.
UPDATE nexent.memory_dreaming_audit_t
SET result_json = result_json - 'version' - 'version_id'
WHERE result_json IS NOT NULL;
