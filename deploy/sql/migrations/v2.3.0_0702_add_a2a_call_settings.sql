ALTER TABLE nexent.ag_a2a_external_agent_t
ADD COLUMN IF NOT EXISTS custom_headers JSONB;

COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.custom_headers IS 'Custom HTTP headers for calling this external A2A agent';
