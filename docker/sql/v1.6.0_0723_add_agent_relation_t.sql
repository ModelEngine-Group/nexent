-- Migration script to add ag_agent_relation_t table for recording agent parent-child relationships
-- This table is used to store the hierarchical relationships between agents

-- Create the ag_agent_relation_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.ag_agent_relation_t (
    relation_id SERIAL PRIMARY KEY NOT NULL,
    selected_agent_id INTEGER,
    parent_agent_id INTEGER,
    tenant_id VARCHAR(100),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_ag_agent_relation_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create a trigger to call the function before each update
CREATE TRIGGER update_ag_agent_relation_update_time_trigger
BEFORE UPDATE ON nexent.ag_agent_relation_t
FOR EACH ROW
EXECUTE FUNCTION update_ag_agent_relation_update_time();

-- Add comment to the table
COMMENT ON TABLE nexent.ag_agent_relation_t IS 'Agent parent-child relationship table';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_agent_relation_t.relation_id IS 'Relationship ID, primary key';
COMMENT ON COLUMN nexent.ag_agent_relation_t.selected_agent_id IS 'Selected agent ID';
COMMENT ON COLUMN nexent.ag_agent_relation_t.parent_agent_id IS 'Parent agent ID';
COMMENT ON COLUMN nexent.ag_agent_relation_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.ag_agent_relation_t.create_time IS 'Creation time, audit field';
COMMENT ON COLUMN nexent.ag_agent_relation_t.update_time IS 'Update time, audit field';
COMMENT ON COLUMN nexent.ag_agent_relation_t.created_by IS 'Creator ID, audit field';
COMMENT ON COLUMN nexent.ag_agent_relation_t.updated_by IS 'Last updater ID, audit field';
COMMENT ON COLUMN nexent.ag_agent_relation_t.delete_flag IS 'Delete flag, set to Y for soft delete, optional values Y/N'; 