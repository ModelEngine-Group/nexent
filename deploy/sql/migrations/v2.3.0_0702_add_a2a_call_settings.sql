ALTER TABLE nexent.ag_a2a_external_agent_t
ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER DEFAULT 300;

COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.timeout_seconds IS 'Request timeout in seconds for calling this external A2A agent';
