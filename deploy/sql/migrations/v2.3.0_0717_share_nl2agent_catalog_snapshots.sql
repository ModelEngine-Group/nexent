-- Deduplicate immutable provider catalogs across NL2AGENT sessions.
CREATE TABLE IF NOT EXISTS nexent.nl2agent_catalog_snapshot_t (
    tenant_id VARCHAR(100) NOT NULL,
    snapshot_id VARCHAR(64) NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    catalogs JSONB NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT nl2agent_catalog_snapshot_t_pk PRIMARY KEY (tenant_id, snapshot_id)
);

ALTER TABLE nexent.nl2agent_session_t
ADD COLUMN IF NOT EXISTS catalog_snapshot_id VARCHAR(64);

INSERT INTO nexent.nl2agent_catalog_snapshot_t (
    tenant_id,
    snapshot_id,
    catalogs,
    created_by,
    updated_by
)
SELECT DISTINCT ON (tenant_id, md5(session_catalogs::text))
    tenant_id,
    md5(session_catalogs::text),
    session_catalogs,
    'nl2agent_migration',
    'nl2agent_migration'
FROM nexent.nl2agent_session_t
WHERE catalog_snapshot_id IS NULL
ON CONFLICT (tenant_id, snapshot_id) DO NOTHING;

UPDATE nexent.nl2agent_session_t
SET catalog_snapshot_id = md5(session_catalogs::text)
WHERE catalog_snapshot_id IS NULL;

ALTER TABLE nexent.nl2agent_session_t
ALTER COLUMN catalog_snapshot_id SET NOT NULL;

ALTER TABLE nexent.nl2agent_session_t
ADD CONSTRAINT fk_nl2agent_session_catalog_snapshot
FOREIGN KEY (tenant_id, catalog_snapshot_id)
REFERENCES nexent.nl2agent_catalog_snapshot_t (tenant_id, snapshot_id);

ALTER TABLE nexent.nl2agent_session_t
DROP COLUMN IF EXISTS catalog_revision;

ALTER TABLE nexent.nl2agent_session_t
DROP COLUMN IF EXISTS session_catalogs;
