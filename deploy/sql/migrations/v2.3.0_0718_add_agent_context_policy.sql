-- Add the agent-level context processing mode override.
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS context_policy JSONB;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.context_policy IS
'Agent-level context processing override (passthrough/adaptive_compact); NULL preserves the platform default';
