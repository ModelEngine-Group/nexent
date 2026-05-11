-- v2.0.2_0410_add_columns_outer_api_tools.sql
-- Add MCP service-level columns to ag_outer_api_tools table
-- These columns enable grouping tools from the same OpenAPI spec under a single MCP service

-- Add columns for MCP service information
ALTER TABLE nexent.ag_outer_api_tools
    ADD COLUMN IF NOT EXISTS mcp_service_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS openapi_json JSONB,
    ADD COLUMN IF NOT EXISTS server_url VARCHAR(500);

-- Add comments to the new columns
COMMENT ON COLUMN nexent.ag_outer_api_tools.mcp_service_name IS 'MCP service name for grouping tools from same OpenAPI spec';
COMMENT ON COLUMN nexent.ag_outer_api_tools.openapi_json IS 'Complete OpenAPI JSON specification';
COMMENT ON COLUMN nexent.ag_outer_api_tools.server_url IS 'Base URL of the REST API server';

-- Create index for mcp_service_name queries
CREATE INDEX IF NOT EXISTS idx_ag_outer_api_tools_mcp_service_name
ON nexent.ag_outer_api_tools (mcp_service_name)
WHERE delete_flag = 'N' AND mcp_service_name IS NOT NULL;