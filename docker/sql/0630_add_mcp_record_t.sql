-- Migration: Add mcp_record_t table
-- Date: 2024-06-30
-- Description: Create MCP (Model Context Protocol) records table with audit fields

-- Set search path to nexent schema
SET search_path TO nexent;

-- Create the mcp_record_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.mcp_record_t (
    mcp_id SERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100),
    user_id VARCHAR(100),
    mcp_name VARCHAR(100),
    mcp_server VARCHAR(500),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE "mcp_record_t" OWNER TO "root";

-- Add comment to the table
COMMENT ON TABLE nexent.mcp_record_t IS 'MCP (Model Context Protocol) records table';

-- Add comments to the columns
COMMENT ON COLUMN nexent.mcp_record_t.mcp_id IS 'MCP record ID, unique primary key';
COMMENT ON COLUMN nexent.mcp_record_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.mcp_record_t.user_id IS 'User ID';
COMMENT ON COLUMN nexent.mcp_record_t.mcp_name IS 'MCP name';
COMMENT ON COLUMN nexent.mcp_record_t.mcp_server IS 'MCP server address';
COMMENT ON COLUMN nexent.mcp_record_t.create_time IS 'Creation time, audit field';
COMMENT ON COLUMN nexent.mcp_record_t.update_time IS 'Update time, audit field';
COMMENT ON COLUMN nexent.mcp_record_t.created_by IS 'Creator ID, audit field';
COMMENT ON COLUMN nexent.mcp_record_t.updated_by IS 'Last updater ID, audit field';
COMMENT ON COLUMN nexent.mcp_record_t.delete_flag IS 'When deleted by user frontend, delete flag will be set to true, achieving soft delete effect. Optional values Y/N';

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_mcp_record_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Add comment to the function
COMMENT ON FUNCTION update_mcp_record_update_time() IS 'Function to update the update_time column when a record in mcp_record_t is updated';

-- Create a trigger to call the function before each update
CREATE TRIGGER update_mcp_record_update_time_trigger
BEFORE UPDATE ON nexent.mcp_record_t
FOR EACH ROW
EXECUTE FUNCTION update_mcp_record_update_time();

-- Add comment to the trigger
COMMENT ON TRIGGER update_mcp_record_update_time_trigger ON nexent.mcp_record_t IS 'Trigger to call update_mcp_record_update_time function before each update on mcp_record_t table';
