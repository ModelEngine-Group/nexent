-- Add is_a2a column to ag_tenant_agent_version_t for tracking A2A Server agent publish status
-- This field indicates whether this version was published as an A2A Server agent

ALTER TABLE nexent.ag_tenant_agent_version_t
ADD COLUMN IF NOT EXISTS is_a2a BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.is_a2a IS 'Whether this version is published as an A2A Server agent';
