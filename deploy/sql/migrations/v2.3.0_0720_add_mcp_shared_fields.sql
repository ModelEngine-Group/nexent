-- Migration: Add shared_fields column to mcp_record_t
-- Date: 2026-07-20
-- Description: Add a JSON column for field-level sharing flags on MCP records.

SET search_path TO nexent;

BEGIN;

ALTER TABLE nexent.mcp_record_t
    ADD COLUMN IF NOT EXISTS shared_fields JSON;

COMMENT ON COLUMN nexent.mcp_record_t.shared_fields IS
    'JSON object of field-level sharing flags (e.g. {"serverUrl": true, "authorizationToken": false})';

COMMIT;
