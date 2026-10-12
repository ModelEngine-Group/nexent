-- Migration kind: REQUIRED_SCHEMA
-- Required for: Optional native Agent Core selection on every Agent version.
-- Preserve the execution core on each draft and published Agent version.
ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS agent_core VARCHAR(30) NOT NULL DEFAULT 'smolagents';

COMMENT ON COLUMN nexent.ag_tenant_agent_t.agent_core IS
    'Execution core for this immutable agent version: smolagents or jiuwen';
