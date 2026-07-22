ALTER TABLE nexent.conversation_message_t
ADD COLUMN IF NOT EXISTS message_type VARCHAR(30) NOT NULL DEFAULT 'chat';

ALTER TABLE nexent.conversation_message_t
ADD COLUMN IF NOT EXISTS message_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN nexent.conversation_message_t.message_type
IS 'Message presentation type, such as chat or nl2agent_action';

COMMENT ON COLUMN nexent.conversation_message_t.message_metadata
IS 'Structured metadata used to restore specialized message presentation';
