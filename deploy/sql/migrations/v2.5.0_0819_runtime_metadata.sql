SET search_path TO nexent, public;

ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS allow_chat_metadata BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS runtime_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS runtime_metadata_version INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.allow_chat_metadata IS
    'Whether Native Chat and Debug users may submit runtime metadata';

COMMENT ON COLUMN nexent.conversation_record_t.runtime_metadata IS
    'Conversation-scoped runtime metadata available to agent runs';

COMMENT ON COLUMN nexent.conversation_record_t.runtime_metadata_version IS
    'Monotonic version of conversation runtime metadata';
