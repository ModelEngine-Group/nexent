-- Add idempotent source-message linkage for AgentLoop-created automation proposals.

SET search_path TO nexent;

BEGIN;

ALTER TABLE nexent.agent_automation_proposal_t
    ADD COLUMN IF NOT EXISTS source_message_id BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_automation_proposal_source_message
    ON nexent.agent_automation_proposal_t (tenant_id, user_id, source_message_id)
    WHERE delete_flag = 'N' AND source_message_id IS NOT NULL;

COMMIT;
