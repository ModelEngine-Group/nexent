-- Add is_new column to ag_tenant_agent_t table for new agent marking
-- This migration adds a field to track whether an agent is marked as new for users

-- Add is_new column with default value false
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS is_new BOOLEAN DEFAULT FALSE;

-- Add comment for the new column
COMMENT ON COLUMN nexent.ag_tenant_agent_t.is_new IS 'Whether this agent is marked as new for the user';

-- Create index for performance on is_new queries
CREATE INDEX IF NOT EXISTS idx_ag_tenant_agent_t_is_new
ON nexent.ag_tenant_agent_t (tenant_id, is_new)
WHERE delete_flag = 'N';


