-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.agent_automation_proposal_t
    ADD COLUMN IF NOT EXISTS confirmed_task_id BIGINT;

COMMENT ON COLUMN nexent.agent_automation_proposal_t.confirmed_task_id
    IS 'Task created when this proposal was accepted';

CREATE INDEX IF NOT EXISTS idx_agent_automation_proposal_conversation
    ON nexent.agent_automation_proposal_t (tenant_id, user_id, conversation_id, proposal_id DESC)
    WHERE delete_flag = 'N';

-- Restore legacy receipts when the original owned conversation card identifies the exact task.
WITH legacy_receipts AS MATERIALIZED (
    SELECT proposal.proposal_id, proposal.conversation_id, proposal.tenant_id, proposal.user_id,
        (
            SELECT substring(
                unit.unit_content FROM '"confirmed_task_id"[[:space:]]*:[[:space:]]*([0-9]{1,19})[[:space:]]*[,}]'
            )::numeric
            FROM nexent.conversation_message_unit_t AS unit
            WHERE unit.unit_id = CASE
                WHEN (proposal.proposed_task ->> '_conversation_unit_id') ~ '^[0-9]{1,10}$'
                THEN (proposal.proposed_task ->> '_conversation_unit_id')::bigint
            END
                AND unit.conversation_id = proposal.conversation_id
                AND unit.created_by = proposal.user_id
                AND unit.unit_type = 'automation_proposal'
                AND unit.delete_flag = 'N'
                AND substring(
                    unit.unit_content FROM '"proposal_id"[[:space:]]*:[[:space:]]*([0-9]+)[[:space:]]*[,}]'
                ) = proposal.proposal_id::text
        ) AS task_id
    FROM nexent.agent_automation_proposal_t AS proposal
    WHERE proposal.confirmed_task_id IS NULL
        AND proposal.status = 'ACCEPTED'
        AND proposal.delete_flag = 'N'
)
UPDATE nexent.agent_automation_proposal_t AS proposal
SET confirmed_task_id = task.task_id
FROM legacy_receipts AS receipt
JOIN nexent.agent_automation_task_t AS task
    ON task.task_id = CASE WHEN receipt.task_id <= 9223372036854775807 THEN receipt.task_id::bigint END
    AND task.conversation_id = receipt.conversation_id
    AND task.tenant_id = receipt.tenant_id
    AND task.user_id = receipt.user_id
WHERE proposal.proposal_id = receipt.proposal_id
    AND proposal.confirmed_task_id IS NULL;
