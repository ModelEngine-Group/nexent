-- Migration: Add custom_headers column to mcp_record_t
-- Date: 2026-05-26
-- Description: Add custom_headers field to store custom HTTP headers for MCP server requests

SET search_path TO nexent;

BEGIN;

-- Add custom_headers column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
        AND table_name = 'mcp_record_t'
        AND column_name = 'custom_headers'
    ) THEN
        ALTER TABLE nexent.mcp_record_t
        ADD COLUMN custom_headers JSON DEFAULT NULL;
    END IF;
END $$;

-- Add comment to the column
COMMENT ON COLUMN nexent.mcp_record_t.custom_headers IS 'Custom HTTP headers as JSON object for MCP server requests';

COMMIT;
