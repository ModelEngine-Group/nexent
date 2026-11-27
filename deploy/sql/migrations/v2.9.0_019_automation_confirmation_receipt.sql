-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.agent_automation_proposal_t
    ADD COLUMN IF NOT EXISTS confirmed_task_id BIGINT;

COMMENT ON COLUMN nexent.agent_automation_proposal_t.confirmed_task_id
    IS 'Task created when this proposal was accepted';

CREATE INDEX IF NOT EXISTS idx_agent_automation_proposal_conversation
    ON nexent.agent_automation_proposal_t (tenant_id, user_id, conversation_id, proposal_id DESC)
    WHERE delete_flag = 'N';

-- Find the latest active message at a conversation position without scanning message history.
CREATE INDEX IF NOT EXISTS idx_conversation_message_position
    ON nexent.conversation_message_t (conversation_id, message_index, message_id DESC)
    WHERE delete_flag = 'N';
