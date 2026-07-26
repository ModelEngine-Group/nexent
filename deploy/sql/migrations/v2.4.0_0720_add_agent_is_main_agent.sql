-- Add a main-agent flag to tenant agents.
ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS is_main_agent BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.is_main_agent
    IS 'Whether this agent is a main agent';
