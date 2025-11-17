ALTER TABLE nexent.mcp_record_t
ADD COLUMN status BOOLEAN DEFAULT NULL;
COMMENT ON COLUMN nexent.mcp_record_t.status IS 'MCP server connection status, true=connected, false=disconnected, null=unknown'; 