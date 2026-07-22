-- Migration: Add permission and sharing fields to MCP tables
-- Date: 2026-07-16
-- Description:
--   - mcp_record_t: add group_ids, ingroup_permission, shared_fields
--   - mcp_market_record_t: add group_ids, ingroup_permission, shared_fields
--   Both target the same commit to keep the migration atomic.

SET search_path TO nexent;

BEGIN;

-- -------------------------------------------------------------------------
-- mcp_market_record_t — group-based access control
-- -------------------------------------------------------------------------
ALTER TABLE nexent.mcp_market_record_t
    ADD COLUMN IF NOT EXISTS group_ids VARCHAR,
    ADD COLUMN IF NOT EXISTS ingroup_permission VARCHAR(30) DEFAULT 'READ_ONLY';

COMMENT ON COLUMN nexent.mcp_market_record_t.group_ids IS
    'Comma-separated group IDs that can access this MCP';
COMMENT ON COLUMN nexent.mcp_market_record_t.ingroup_permission IS
    'In-group permission: EDIT, READ_ONLY, PRIVATE';

-- -------------------------------------------------------------------------
-- mcp_market_record_t — shared-fields snapshot at submission time
-- -------------------------------------------------------------------------
ALTER TABLE nexent.mcp_market_record_t
    ADD COLUMN IF NOT EXISTS shared_fields JSON;

COMMENT ON COLUMN nexent.mcp_market_record_t.shared_fields IS
    'Snapshot of shared_fields at submission time';

-- -------------------------------------------------------------------------
-- mcp_record_t — group-based access control
-- -------------------------------------------------------------------------
ALTER TABLE nexent.mcp_record_t
    ADD COLUMN IF NOT EXISTS group_ids VARCHAR,
    ADD COLUMN IF NOT EXISTS ingroup_permission VARCHAR(30) DEFAULT 'READ_ONLY';

COMMENT ON COLUMN nexent.mcp_record_t.group_ids IS
    'Comma-separated group IDs that can access this MCP';
COMMENT ON COLUMN nexent.mcp_record_t.ingroup_permission IS
    'In-group permission: EDIT, READ_ONLY, PRIVATE';

-- -------------------------------------------------------------------------
-- mcp_record_t — field-level sharing flags
-- -------------------------------------------------------------------------
ALTER TABLE nexent.mcp_record_t
    ADD COLUMN IF NOT EXISTS shared_fields JSON;

COMMENT ON COLUMN nexent.mcp_record_t.shared_fields IS
    'JSON object of field-level sharing flags (e.g. {"serverUrl": true, "authorizationToken": false})';

COMMIT;
