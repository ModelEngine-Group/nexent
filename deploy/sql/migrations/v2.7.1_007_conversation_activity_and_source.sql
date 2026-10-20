-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_message_t
    ADD COLUMN IF NOT EXISTS message_source VARCHAR(16) NOT NULL DEFAULT 'CHAT';
ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS last_activity_time TIMESTAMPTZ;

COMMENT ON COLUMN nexent.conversation_message_t.message_source IS
    'Trusted message origin: CHAT consumes the ordinary user-turn quota; AUTOMATION is exempt';
COMMENT ON COLUMN nexent.conversation_record_t.last_activity_time IS
    'Last committed visible message activity in UTC; NULL falls back to conversation creation';

-- Classify explicit message identities, never an entire task conversation.
UPDATE nexent.conversation_message_t AS message
SET message_source = 'AUTOMATION'
WHERE message.message_source = 'CHAT'
  AND (
    EXISTS (
        SELECT 1 FROM nexent.conversation_message_unit_t AS unit
        WHERE unit.message_id = message.message_id
          AND unit.unit_type = 'automation_prompt'
    ) OR EXISTS (
        SELECT 1 FROM nexent.agent_automation_run_t AS run
        WHERE run.conversation_id = message.conversation_id
          AND message.message_id IN (run.user_message_id, run.assistant_message_id)
    )
  );

-- Legacy audit timestamps include title/config changes, so use message creation.
UPDATE nexent.conversation_record_t AS conversation
SET last_activity_time = COALESCE(
    (SELECT MAX(message.create_time) AT TIME ZONE 'UTC'
     FROM nexent.conversation_message_t AS message
     WHERE message.conversation_id = conversation.conversation_id
       AND message.delete_flag = 'N'
       AND (message.message_role = 'user'
            OR (message.message_role = 'assistant' AND message.message_content <> ''))),
    conversation.create_time AT TIME ZONE 'UTC'
)
WHERE conversation.last_activity_time IS NULL;

CREATE INDEX IF NOT EXISTS idx_conversation_activity_order
    ON nexent.conversation_record_t
    (created_by, (COALESCE(last_activity_time, create_time AT TIME ZONE 'UTC')) DESC, conversation_id DESC)
    WHERE delete_flag = 'N';
CREATE INDEX IF NOT EXISTS idx_conversation_chat_turns
    ON nexent.conversation_message_t (conversation_id)
    WHERE delete_flag = 'N' AND message_role = 'user' AND message_source = 'CHAT';
