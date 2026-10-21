-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_message_t
    ADD COLUMN IF NOT EXISTS message_source VARCHAR(16) NOT NULL DEFAULT 'CHAT';
ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS last_activity_time TIMESTAMP;

-- Preserve UTC instants on installations that applied the pre-merge column type.
DO $activity_timestamp$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_attribute
        WHERE attrelid = 'nexent.conversation_record_t'::regclass
          AND attname = 'last_activity_time'
          AND atttypid = 'timestamp with time zone'::regtype
    ) THEN
        DROP INDEX IF EXISTS nexent.idx_conversation_activity_order;
        ALTER TABLE nexent.conversation_record_t
            ALTER COLUMN last_activity_time TYPE TIMESTAMP
            USING last_activity_time AT TIME ZONE 'UTC';
    END IF;
END;
$activity_timestamp$;

COMMENT ON COLUMN nexent.conversation_message_t.message_source IS
    'Trusted message origin: CHAT consumes the ordinary user-turn quota; AUTOMATION is exempt';
COMMENT ON COLUMN nexent.conversation_record_t.last_activity_time IS
    'Last committed visible message activity as a UTC timestamp; NULL falls back to conversation creation';

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
    (SELECT MAX(message.create_time)
     FROM nexent.conversation_message_t AS message
     WHERE message.conversation_id = conversation.conversation_id
       AND message.delete_flag = 'N'
       AND (message.message_role = 'user'
            OR (message.message_role = 'assistant' AND message.message_content <> ''))),
    conversation.create_time
)
WHERE conversation.last_activity_time IS NULL;

CREATE INDEX IF NOT EXISTS idx_conversation_activity_order
    ON nexent.conversation_record_t
    (created_by, (COALESCE(last_activity_time, create_time)) DESC, conversation_id DESC)
    WHERE delete_flag = 'N';
CREATE INDEX IF NOT EXISTS idx_conversation_chat_turns
    ON nexent.conversation_message_t (conversation_id)
    WHERE delete_flag = 'N' AND message_role = 'user' AND message_source = 'CHAT';
