-- Add custom_headers column to mcp_record_t table
-- Purpose: Store custom HTTP headers in JSON format for MCP server requests
ALTER TABLE nexent.mcp_record_t
ADD COLUMN IF NOT EXISTS custom_headers VARCHAR(5000) DEFAULT NULL;

-- Add comment to the column
COMMENT ON COLUMN nexent.mcp_record_t.custom_headers IS 'Custom headers in JSON format for MCP server requests';
