-- Migration: Add ag_agent_repository_t table
-- Date: 2026-06-05
-- Description: Agent marketplace repository for frozen shareable agent snapshots.

SET search_path TO nexent;

BEGIN;

CREATE SEQUENCE IF NOT EXISTS nexent.ag_agent_repository_t_agent_repository_id_seq;

CREATE TABLE IF NOT EXISTS nexent.ag_agent_repository_t (
    agent_repository_id BIGINT NOT NULL DEFAULT nextval('nexent.ag_agent_repository_t_agent_repository_id_seq'),
    publisher_tenant_id VARCHAR(100) NOT NULL,
    publisher_user_id VARCHAR(100) NOT NULL,
    agent_id INTEGER NOT NULL,
    source_version_no INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    display_name VARCHAR(100),
    description TEXT,
    author VARCHAR(100),
    category_id INTEGER,
    tags TEXT[],
    tool_count INTEGER,
    version_label VARCHAR(100),
    agent_info_json JSONB NOT NULL,
    status VARCHAR(30) DEFAULT 'NOT_SHARED',
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT ag_agent_repository_t_pkey PRIMARY KEY (agent_repository_id)
);

ALTER SEQUENCE nexent.ag_agent_repository_t_agent_repository_id_seq
    OWNED BY nexent.ag_agent_repository_t.agent_repository_id;

ALTER TABLE nexent.ag_agent_repository_t OWNER TO root;

COMMENT ON TABLE nexent.ag_agent_repository_t IS 'Agent marketplace repository for frozen shareable agent snapshots';
COMMENT ON COLUMN nexent.ag_agent_repository_t.agent_repository_id IS 'Agent repository listing ID, unique primary key';
COMMENT ON COLUMN nexent.ag_agent_repository_t.publisher_tenant_id IS 'Publisher tenant ID';
COMMENT ON COLUMN nexent.ag_agent_repository_t.publisher_user_id IS 'Publisher user ID';
COMMENT ON COLUMN nexent.ag_agent_repository_t.agent_id IS 'Root agent ID from ag_tenant_agent_t; upsert key with publisher_tenant_id';
COMMENT ON COLUMN nexent.ag_agent_repository_t.source_version_no IS 'Published version number frozen at share time';
COMMENT ON COLUMN nexent.ag_agent_repository_t.name IS 'Root agent programmatic name for display and search';
COMMENT ON COLUMN nexent.ag_agent_repository_t.display_name IS 'Root agent display name';
COMMENT ON COLUMN nexent.ag_agent_repository_t.description IS 'Root agent description';
COMMENT ON COLUMN nexent.ag_agent_repository_t.author IS 'Agent author';
COMMENT ON COLUMN nexent.ag_agent_repository_t.category_id IS 'Optional marketplace category ID';
COMMENT ON COLUMN nexent.ag_agent_repository_t.tags IS 'Marketplace tags';
COMMENT ON COLUMN nexent.ag_agent_repository_t.tool_count IS 'Total tool count across all agents in the bundle (display only)';
COMMENT ON COLUMN nexent.ag_agent_repository_t.version_label IS 'Repository entry version label for display (e.g. v1.0)';
COMMENT ON COLUMN nexent.ag_agent_repository_t.agent_info_json IS 'Frozen ExportAndImportDataFormat snapshot with optional skills';
COMMENT ON COLUMN nexent.ag_agent_repository_t.status IS 'Listing status: NOT_SHARED (未共享) / PENDING_REVIEW (待审核) / REJECTED (审核驳回) / SHARED (已共享)';
COMMENT ON COLUMN nexent.ag_agent_repository_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_agent_repository_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.ag_agent_repository_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.ag_agent_repository_t.updated_by IS 'Updater ID';
COMMENT ON COLUMN nexent.ag_agent_repository_t.delete_flag IS 'Soft delete flag: Y/N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_repository_tenant_agent_active
    ON nexent.ag_agent_repository_t (publisher_tenant_id, agent_id)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_agent_repository_publisher_delete
    ON nexent.ag_agent_repository_t (publisher_tenant_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_agent_repository_status_delete
    ON nexent.ag_agent_repository_t (status, delete_flag);

CREATE INDEX IF NOT EXISTS idx_agent_repository_name_delete
    ON nexent.ag_agent_repository_t (name, delete_flag);

CREATE INDEX IF NOT EXISTS idx_agent_repository_tags_gin
    ON nexent.ag_agent_repository_t USING GIN (tags);

CREATE OR REPLACE FUNCTION update_ag_agent_repository_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_ag_agent_repository_update_time() IS 'Auto-update update_time for ag_agent_repository_t';

DROP TRIGGER IF EXISTS update_ag_agent_repository_update_time_trigger ON nexent.ag_agent_repository_t;
CREATE TRIGGER update_ag_agent_repository_update_time_trigger
BEFORE UPDATE ON nexent.ag_agent_repository_t
FOR EACH ROW
EXECUTE FUNCTION update_ag_agent_repository_update_time();

COMMENT ON TRIGGER update_ag_agent_repository_update_time_trigger ON nexent.ag_agent_repository_t IS 'Trigger to maintain update_time';

COMMIT;
