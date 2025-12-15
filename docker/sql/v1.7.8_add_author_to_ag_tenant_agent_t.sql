-- Add author column to ag_tenant_agent_t table
-- This migration adds the author field to support agent author information

-- Add author column with default NULL value for backward compatibility
ALTER TABLE nexent.ag_tenant_agent_t 
ADD COLUMN IF NOT EXISTS author VARCHAR(100);

-- Add comment to the column
COMMENT ON COLUMN nexent.ag_tenant_agent_t.author IS 'Agent author';

