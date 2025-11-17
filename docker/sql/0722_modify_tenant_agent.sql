-- Migration script to add new prompt fields to ag_tenant_agent_t table
-- Add three new columns for storing segmented prompt content

-- Add duty_prompt column
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS duty_prompt TEXT;

-- Add constraint_prompt column
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS constraint_prompt TEXT;

-- Add few_shots_prompt column
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS few_shots_prompt TEXT;

-- Drop prompt column
ALTER TABLE nexent.ag_tenant_agent_t
DROP COLUMN IF EXISTS prompt;

-- Add comments to the new columns
COMMENT ON COLUMN nexent.ag_tenant_agent_t.duty_prompt IS 'Duty prompt content';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.constraint_prompt IS 'Constraint prompt content';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.few_shots_prompt IS 'Few shots prompt content';