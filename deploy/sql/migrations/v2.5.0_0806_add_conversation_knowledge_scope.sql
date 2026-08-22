SET search_path TO nexent, public;

ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS knowledge_scope JSONB;

COMMENT ON COLUMN nexent.conversation_record_t.knowledge_scope IS
    'Conversation-scoped desired policy for local and AIDP knowledge retrieval';
