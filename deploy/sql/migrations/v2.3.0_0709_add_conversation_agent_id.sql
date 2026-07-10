-- Store the latest agent used by each conversation so history selection can restore agent context.
ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS agent_id INTEGER;

COMMENT ON COLUMN nexent.conversation_record_t.agent_id
    IS 'Agent ID used by the latest run in this conversation';
