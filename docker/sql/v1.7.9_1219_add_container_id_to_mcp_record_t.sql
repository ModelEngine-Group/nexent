ALTER TABLE nexent.mcp_record_t
ADD COLUMN IF NOT EXISTS container_id VARCHAR(200);

COMMENT ON COLUMN nexent.mcp_record_t.container_id IS 'Docker container ID for MCP service, NULL for non-containerized MCP';


