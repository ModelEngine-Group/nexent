-- Migration: Add first-phase MCP market support fields
-- Date: 2026-06-22
-- Description: Store local MCP versions and stable local-to-community associations.

SET search_path TO nexent;

BEGIN;

ALTER TABLE IF EXISTS nexent.mcp_record_t
    ADD COLUMN IF NOT EXISTS version VARCHAR(50),
    ADD COLUMN IF NOT EXISTS community_id INTEGER;

COMMENT ON COLUMN nexent.mcp_record_t.version IS 'MCP version';
COMMENT ON COLUMN nexent.mcp_record_t.community_id IS 'Published community record ID';

CREATE INDEX IF NOT EXISTS idx_mcp_record_t_community_id
    ON nexent.mcp_record_t (community_id, delete_flag);

COMMIT;
