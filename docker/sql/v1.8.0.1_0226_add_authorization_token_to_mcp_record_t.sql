-- Migration: Add authorization_token column to mcp_record_t table
-- Date: 2025-03-01
-- Description: Add authorization_token field to support MCP server authentication

-- Add authorization_token column to mcp_record_t table
ALTER TABLE nexent.mcp_record_t
ADD COLUMN IF NOT EXISTS authorization_token VARCHAR(500) DEFAULT NULL;

-- Add comment to the column
COMMENT ON COLUMN nexent.mcp_record_t.authorization_token IS 'Authorization token for MCP server authentication (e.g., Bearer token)';
