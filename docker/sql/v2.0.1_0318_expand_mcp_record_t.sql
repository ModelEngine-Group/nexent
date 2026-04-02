-- Migration: Extend mcp_record_t for MCP tools (direct schema)
-- Date: 2026-03-18
-- Description: One-step schema extension for mcp_record_t. No table merge, no data migration.

SET search_path TO nexent;

BEGIN;

-- 1) Extend mcp_record_t with final column names (idempotent)
ALTER TABLE IF EXISTS nexent.mcp_record_t
    ADD COLUMN IF NOT EXISTS source VARCHAR(30),
    ADD COLUMN IF NOT EXISTS version VARCHAR(50),
    ADD COLUMN IF NOT EXISTS registry_json JSONB,
    ADD COLUMN IF NOT EXISTS transport_type VARCHAR(30),
    ADD COLUMN IF NOT EXISTS config_json JSON,
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS tags TEXT[],
    ADD COLUMN IF NOT EXISTS description VARCHAR(100),
    ADD COLUMN IF NOT EXISTS last_sync_time TIMESTAMP WITHOUT TIME ZONE;

-- 2) Add comments for new columns
COMMENT ON COLUMN nexent.mcp_record_t.source IS 'Source type: local/mcp_registry';
COMMENT ON COLUMN nexent.mcp_record_t.version IS 'MCP version';
COMMENT ON COLUMN nexent.mcp_record_t.registry_json IS 'Full MCP registry server.json snapshot';
COMMENT ON COLUMN nexent.mcp_record_t.transport_type IS 'Transport type: streamable-http/sse/stdio';
COMMENT ON COLUMN nexent.mcp_record_t.config_json IS 'MCP config data';
COMMENT ON COLUMN nexent.mcp_record_t.enabled IS 'Enabled';
COMMENT ON COLUMN nexent.mcp_record_t.tags IS 'Tags';
COMMENT ON COLUMN nexent.mcp_record_t.description IS 'Description';
COMMENT ON COLUMN nexent.mcp_record_t.last_sync_time IS 'Last sync time';

-- 3) Add indexes for common management queries
CREATE INDEX IF NOT EXISTS idx_mcp_record_t_tenant_delete
    ON nexent.mcp_record_t (tenant_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_record_t_tenant_name
    ON nexent.mcp_record_t (tenant_id, mcp_name, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_record_t_tenant_server
    ON nexent.mcp_record_t (tenant_id, mcp_server, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_record_t_tags_gin
    ON nexent.mcp_record_t USING GIN (tags);

COMMIT;
