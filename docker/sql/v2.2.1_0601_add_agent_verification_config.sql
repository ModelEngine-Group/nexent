-- Migration: Add layered ReAct self-verification config to agents
-- Description: Stores per-agent verification controls for step-level and final-answer validation.

ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS verification_config JSONB;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.verification_config IS 'Layered ReAct self-verification configuration';
