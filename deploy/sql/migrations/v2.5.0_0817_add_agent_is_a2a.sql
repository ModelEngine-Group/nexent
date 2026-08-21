-- Store the A2A publication preference on the editable agent draft.
ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS is_a2a BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.is_a2a IS
    'Whether the draft configuration publishes this agent as an A2A Server';

-- Preserve the A2A state of agents that have at least one historical A2A version.
UPDATE nexent.ag_tenant_agent_t AS agent
SET is_a2a = TRUE
WHERE agent.version_no = 0
  AND agent.delete_flag = 'N'
  AND EXISTS (
      SELECT 1
      FROM nexent.ag_tenant_agent_version_t AS version
      WHERE version.agent_id = agent.agent_id
        AND version.tenant_id = agent.tenant_id
        AND version.is_a2a IS TRUE
  );

-- A2A publication state is now owned exclusively by ag_tenant_agent_t.
ALTER TABLE nexent.ag_tenant_agent_version_t
    DROP COLUMN IF EXISTS is_a2a;
