-- Add model_id column to ag_tenant_agent_t table and deprecate model_name field
-- Date: 2024-09-28
-- Description: Add model_id field to ag_tenant_agent_t table and mark model_name as deprecated

-- Switch to the nexent schema
SET search_path TO nexent;

-- Add model_id column to ag_tenant_agent_t table
ALTER TABLE ag_tenant_agent_t 
ADD COLUMN model_id INTEGER;

-- Add comment for the new model_id column
COMMENT ON COLUMN ag_tenant_agent_t.model_id IS 'Model ID, foreign key reference to model_record_t.model_id';

-- Update comment for model_name column to mark it as deprecated
COMMENT ON COLUMN ag_tenant_agent_t.model_name IS '[DEPRECATED] Name of the model used, use model_id instead';

-- Optional: Add foreign key constraint (uncomment if needed)
-- ALTER TABLE ag_tenant_agent_t 
-- ADD CONSTRAINT fk_ag_tenant_agent_model_id 
-- FOREIGN KEY (model_id) REFERENCES model_record_t(model_id);
