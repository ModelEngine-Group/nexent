-- Migration: Add permission fields to mcp_market_record_t
-- Date: 2026-07-16
-- Description: Add group_ids and ingroup_permission columns for group-based
-- access control, matching the permission model used by agents and knowledge bases.

SET search_path TO nexent;

BEGIN;

ALTER TABLE nexent.mcp_market_record_t
    ADD COLUMN IF NOT EXISTS group_ids VARCHAR,
    ADD COLUMN IF NOT EXISTS ingroup_permission VARCHAR(30) DEFAULT 'READ_ONLY';

COMMENT ON COLUMN nexent.mcp_market_record_t.group_ids IS 'Comma-separated group IDs that can access this MCP';
COMMENT ON COLUMN nexent.mcp_market_record_t.ingroup_permission IS 'In-group permission: EDIT, READ_ONLY, PRIVATE';

COMMIT;
