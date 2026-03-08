-- Migration: Add ingroup_permission column to ag_tenant_agent_t table
-- Date: 2025-03-02
-- Description: Add ingroup_permission field to support in-group permission control for agents

-- Add ingroup_permission column to ag_tenant_agent_t table
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS ingroup_permission VARCHAR(30) DEFAULT NULL;

-- Add comment to the column
COMMENT ON COLUMN nexent.ag_tenant_agent_t.ingroup_permission IS 'In-group permission: EDIT, READ_ONLY, PRIVATE';
