ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS enable_protocol_repair_retry BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE nexent.ag_tenant_agent_t
    ALTER COLUMN enable_protocol_repair_retry SET DEFAULT FALSE;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.enable_protocol_repair_retry IS
    'Whether this agent uses strict output validation and silent protocol repair';
