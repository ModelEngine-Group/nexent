ALTER TABLE nexent.ag_a2a_external_agent_t
    ADD COLUMN IF NOT EXISTS agent_card_headers JSONB;

COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.agent_card_headers
    IS 'Headers saved only for Agent Card discovery and refresh';
    
ALTER TABLE nexent.ag_a2a_external_agent_t
    ADD COLUMN IF NOT EXISTS security_schemes JSONB,
    ADD COLUMN IF NOT EXISTS security_requirements JSONB,
    ADD COLUMN IF NOT EXISTS security_credentials JSONB;

COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.security_schemes
    IS 'Security schemes declared by the Agent Card';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.security_requirements
    IS 'Security requirements declared by the Agent Card';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.security_credentials
    IS 'Credential values for Agent Card security schemes, never exposed by APIs';
