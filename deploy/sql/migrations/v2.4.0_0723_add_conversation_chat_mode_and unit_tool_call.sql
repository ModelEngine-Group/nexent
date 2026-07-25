-- Persist the UI chat mode (planning vs. execution) for each conversation so
-- switching threads can restore the toggle without re-inferring it from units.

ALTER TABLE nexent.conversation_record_t
  ADD COLUMN IF NOT EXISTS chat_mode varchar(16) NOT NULL DEFAULT 'execution';

COMMENT ON COLUMN nexent.conversation_record_t.chat_mode IS
  'UI chat mode of the conversation. Allowed values: planning, execution.';

SET search_path TO nexent;

ALTER TABLE nexent.conversation_message_unit_t
    ADD COLUMN IF NOT EXISTS tool_call_id VARCHAR(36);

COMMENT ON COLUMN nexent.conversation_message_unit_t.tool_call_id IS
    'Unique ID of the originating tool invocation, used to attribute side-channel units to the correct tool call during parallel execution.';
