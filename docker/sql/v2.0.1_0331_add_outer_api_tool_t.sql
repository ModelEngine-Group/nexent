-- v2.0.1_0331_add_outer_api_tool_t.sql
-- Create table for outer API tools (OpenAPI to MCP conversion)

-- Create the ag_outer_api_tools table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.ag_outer_api_tools (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    method VARCHAR(10),
    url TEXT NOT NULL,
    headers_template JSONB DEFAULT '{}',
    query_template JSONB DEFAULT '{}',
    body_template JSONB DEFAULT '{}',
    input_schema JSONB DEFAULT '{}',
    tenant_id VARCHAR(100),
    is_available BOOLEAN DEFAULT TRUE,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.ag_outer_api_tools OWNER TO "root";

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_ag_outer_api_tools_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create a trigger to call the function before each update
CREATE TRIGGER update_ag_outer_api_tools_update_time_trigger
BEFORE UPDATE ON nexent.ag_outer_api_tools
FOR EACH ROW
EXECUTE FUNCTION update_ag_outer_api_tools_update_time();

-- Add comment to the table
COMMENT ON TABLE nexent.ag_outer_api_tools IS 'Outer API tools table - stores converted OpenAPI tools as MCP tools';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_outer_api_tools.id IS 'Tool ID, unique primary key';
COMMENT ON COLUMN nexent.ag_outer_api_tools.name IS 'Tool name (unique identifier)';
COMMENT ON COLUMN nexent.ag_outer_api_tools.description IS 'Tool description';
COMMENT ON COLUMN nexent.ag_outer_api_tools.method IS 'HTTP method: GET/POST/PUT/DELETE/PATCH';
COMMENT ON COLUMN nexent.ag_outer_api_tools.url IS 'API endpoint URL (full path with base URL)';
COMMENT ON COLUMN nexent.ag_outer_api_tools.headers_template IS 'Headers template as JSONB';
COMMENT ON COLUMN nexent.ag_outer_api_tools.query_template IS 'Query parameters template as JSONB';
COMMENT ON COLUMN nexent.ag_outer_api_tools.body_template IS 'Request body template as JSONB';
COMMENT ON COLUMN nexent.ag_outer_api_tools.input_schema IS 'MCP input schema as JSONB';
COMMENT ON COLUMN nexent.ag_outer_api_tools.tenant_id IS 'Tenant ID for multi-tenancy';
COMMENT ON COLUMN nexent.ag_outer_api_tools.is_available IS 'Whether the tool is available';
COMMENT ON COLUMN nexent.ag_outer_api_tools.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_outer_api_tools.update_time IS 'Update time';
COMMENT ON COLUMN nexent.ag_outer_api_tools.created_by IS 'Creator';
COMMENT ON COLUMN nexent.ag_outer_api_tools.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.ag_outer_api_tools.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- Create index for tenant_id queries
CREATE INDEX IF NOT EXISTS idx_ag_outer_api_tools_tenant_id
ON nexent.ag_outer_api_tools (tenant_id)
WHERE delete_flag = 'N';

-- Create index for name queries
CREATE INDEX IF NOT EXISTS idx_ag_outer_api_tools_name
ON nexent.ag_outer_api_tools (name)
WHERE delete_flag = 'N';
