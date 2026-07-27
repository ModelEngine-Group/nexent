-- Immutable Dreaming long-term memory versions and active-version pointer.
SET search_path TO nexent;
BEGIN;

CREATE TABLE IF NOT EXISTS nexent.memory_dreaming_version_t (
    version_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    agent_id VARCHAR(100) NOT NULL,
    version_no INTEGER NOT NULL,
    parent_version_id BIGINT,
    run_id BIGINT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    raw_content TEXT NOT NULL,
    published_content TEXT NOT NULL,
    published_units JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_char_count INTEGER NOT NULL,
    published_char_count INTEGER NOT NULL,
    compression_status VARCHAR(30) NOT NULL,
    compression_attempts INTEGER NOT NULL DEFAULT 0,
    compression_audit JSONB NOT NULL DEFAULT '[]'::jsonb,
    omitted_evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    mechanical_truncation BOOLEAN NOT NULL DEFAULT FALSE,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);

ALTER TABLE nexent.memory_dreaming_version_t
    ADD COLUMN IF NOT EXISTS compression_audit JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE nexent.memory_dreaming_version_t
    ADD COLUMN IF NOT EXISTS source_evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_dreaming_version_scope
    ON nexent.memory_dreaming_version_t
    (tenant_id, user_id, agent_id, version_no);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_dreaming_version_active_scope
    ON nexent.memory_dreaming_version_t
    (tenant_id, user_id, agent_id)
    WHERE is_active AND delete_flag = 'N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_dreaming_version_run
    ON nexent.memory_dreaming_version_t (run_id);

CREATE INDEX IF NOT EXISTS idx_memory_dreaming_version_history
    ON nexent.memory_dreaming_version_t
    (tenant_id, user_id, agent_id, create_time DESC);

CREATE OR REPLACE FUNCTION nexent.prevent_memory_dreaming_version_content_update()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.version_no IS DISTINCT FROM NEW.version_no
       OR OLD.parent_version_id IS DISTINCT FROM NEW.parent_version_id
       OR OLD.run_id IS DISTINCT FROM NEW.run_id
       OR OLD.raw_content IS DISTINCT FROM NEW.raw_content
       OR OLD.published_content IS DISTINCT FROM NEW.published_content
       OR OLD.published_units IS DISTINCT FROM NEW.published_units
       OR OLD.source_evidence_ids IS DISTINCT FROM NEW.source_evidence_ids
       OR OLD.config_snapshot IS DISTINCT FROM NEW.config_snapshot
       OR OLD.raw_char_count IS DISTINCT FROM NEW.raw_char_count
       OR OLD.published_char_count IS DISTINCT FROM NEW.published_char_count
       OR OLD.compression_status IS DISTINCT FROM NEW.compression_status
       OR OLD.compression_attempts IS DISTINCT FROM NEW.compression_attempts
       OR OLD.compression_audit IS DISTINCT FROM NEW.compression_audit
       OR OLD.omitted_evidence_ids IS DISTINCT FROM NEW.omitted_evidence_ids
       OR OLD.mechanical_truncation IS DISTINCT FROM NEW.mechanical_truncation THEN
        RAISE EXCEPTION 'Dreaming version content is immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_memory_dreaming_version_immutable
    ON nexent.memory_dreaming_version_t;
CREATE TRIGGER trg_memory_dreaming_version_immutable
BEFORE UPDATE ON nexent.memory_dreaming_version_t
FOR EACH ROW EXECUTE FUNCTION nexent.prevent_memory_dreaming_version_content_update();

CREATE TABLE IF NOT EXISTS nexent.memory_dreaming_activation_audit_t (
    activation_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    agent_id VARCHAR(100) NOT NULL,
    actor_user_id VARCHAR(100) NOT NULL,
    from_version_id BIGINT,
    to_version_id BIGINT NOT NULL,
    reason VARCHAR(100) NOT NULL DEFAULT 'user_switch',
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);
CREATE INDEX IF NOT EXISTS idx_memory_dreaming_activation_scope
    ON nexent.memory_dreaming_activation_audit_t
    (tenant_id, user_id, agent_id, create_time DESC);

INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype
)
VALUES
    (1004, 'SU', 'RESOURCE', 'DREAMING', 'VIEW_TENANT'),
    (1005, 'SU', 'RESOURCE', 'DREAMING', 'EDIT_TENANT'),
    (1116, 'ADMIN', 'RESOURCE', 'DREAMING', 'VIEW_TENANT'),
    (1117, 'ADMIN', 'RESOURCE', 'DREAMING', 'EDIT_TENANT'),
    (1514, 'ASSET_OWNER', 'RESOURCE', 'DREAMING', 'VIEW_TENANT'),
    (1515, 'ASSET_OWNER', 'RESOURCE', 'DREAMING', 'EDIT_TENANT')
ON CONFLICT (role_permission_id) DO UPDATE SET
    user_role = EXCLUDED.user_role,
    permission_category = EXCLUDED.permission_category,
    permission_type = EXCLUDED.permission_type,
    permission_subtype = EXCLUDED.permission_subtype;

COMMIT;
