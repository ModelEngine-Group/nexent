-- Add the opt-in agent-level context selection policy.
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS context_policy JSONB;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.context_policy IS
'Agent-level context selection policy override; NULL preserves the default behavior';
