-- Migration: Add mcp_community_record_t table
-- Date: 2026-03-26
-- Description: Community MCP market table aligned with public-shareable fields from mcp_record_t.

SET search_path TO nexent;

BEGIN;

CREATE TABLE IF NOT EXISTS nexent.mcp_community_record_t (
    community_id SERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100),
    user_id VARCHAR(100),
    mcp_name VARCHAR(100) NOT NULL,
    mcp_server VARCHAR(500) NOT NULL,
    source VARCHAR(30) DEFAULT 'community',
    version VARCHAR(50),
    registry_json JSONB,
    transport_type VARCHAR(30),
    config_json JSON,
    tags TEXT[],
    description TEXT,
    last_sync_time TIMESTAMP WITHOUT TIME ZONE,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.mcp_community_record_t OWNER TO root;

COMMENT ON TABLE nexent.mcp_community_record_t IS 'Community MCP market records, publishable from tenant MCP services';
COMMENT ON COLUMN nexent.mcp_community_record_t.community_id IS 'Community record ID, unique primary key';
COMMENT ON COLUMN nexent.mcp_community_record_t.tenant_id IS 'Publisher tenant ID';
COMMENT ON COLUMN nexent.mcp_community_record_t.user_id IS 'Publisher user ID';
COMMENT ON COLUMN nexent.mcp_community_record_t.mcp_name IS 'MCP name';
COMMENT ON COLUMN nexent.mcp_community_record_t.mcp_server IS 'MCP server URL';
COMMENT ON COLUMN nexent.mcp_community_record_t.source IS 'Source type, fixed to community for this table';
COMMENT ON COLUMN nexent.mcp_community_record_t.version IS 'MCP version';
COMMENT ON COLUMN nexent.mcp_community_record_t.registry_json IS 'Full MCP server metadata JSON for discovery and quick import';
COMMENT ON COLUMN nexent.mcp_community_record_t.transport_type IS 'Transport type: http/sse/container';
COMMENT ON COLUMN nexent.mcp_community_record_t.config_json IS 'Public-shareable MCP configuration JSON';
COMMENT ON COLUMN nexent.mcp_community_record_t.tags IS 'Tags';
COMMENT ON COLUMN nexent.mcp_community_record_t.description IS 'Description';
COMMENT ON COLUMN nexent.mcp_community_record_t.last_sync_time IS 'Last sync time';
COMMENT ON COLUMN nexent.mcp_community_record_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.mcp_community_record_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.mcp_community_record_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.mcp_community_record_t.updated_by IS 'Updater ID';
COMMENT ON COLUMN nexent.mcp_community_record_t.delete_flag IS 'Soft delete flag: Y/N';

CREATE INDEX IF NOT EXISTS idx_mcp_community_tenant_delete
    ON nexent.mcp_community_record_t (tenant_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_community_name_delete
    ON nexent.mcp_community_record_t (mcp_name, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_community_transport_delete
    ON nexent.mcp_community_record_t (transport_type, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_community_user_delete
    ON nexent.mcp_community_record_t (user_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_community_tags_gin
    ON nexent.mcp_community_record_t USING GIN (tags);

CREATE OR REPLACE FUNCTION update_mcp_community_record_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_mcp_community_record_update_time() IS 'Auto-update update_time for mcp_community_record_t';

DROP TRIGGER IF EXISTS update_mcp_community_record_update_time_trigger ON nexent.mcp_community_record_t;
CREATE TRIGGER update_mcp_community_record_update_time_trigger
BEFORE UPDATE ON nexent.mcp_community_record_t
FOR EACH ROW
EXECUTE FUNCTION update_mcp_community_record_update_time();

COMMENT ON TRIGGER update_mcp_community_record_update_time_trigger ON nexent.mcp_community_record_t IS 'Trigger to maintain update_time';

COMMIT;
