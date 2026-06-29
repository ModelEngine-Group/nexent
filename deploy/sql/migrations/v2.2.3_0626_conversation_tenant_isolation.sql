-- W4: add tenant scope to conversation-owned records.

ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'tenant_id';

ALTER TABLE nexent.conversation_message_t
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'tenant_id';

ALTER TABLE nexent.conversation_message_unit_t
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'tenant_id';

ALTER TABLE nexent.conversation_source_image_t
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'tenant_id';

ALTER TABLE nexent.conversation_source_search_t
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'tenant_id';

COMMENT ON COLUMN nexent.conversation_record_t.tenant_id IS 'Tenant ID for conversation ownership isolation';
COMMENT ON COLUMN nexent.conversation_message_t.tenant_id IS 'Tenant ID for conversation ownership isolation';
COMMENT ON COLUMN nexent.conversation_message_unit_t.tenant_id IS 'Tenant ID for conversation ownership isolation';
COMMENT ON COLUMN nexent.conversation_source_image_t.tenant_id IS 'Tenant ID for conversation ownership isolation';
COMMENT ON COLUMN nexent.conversation_source_search_t.tenant_id IS 'Tenant ID for conversation ownership isolation';

CREATE INDEX IF NOT EXISTS idx_conversation_record_t_tenant_user_delete
    ON nexent.conversation_record_t (tenant_id, created_by, delete_flag);

CREATE INDEX IF NOT EXISTS idx_conversation_record_t_tenant_conversation_delete
    ON nexent.conversation_record_t (tenant_id, conversation_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_conversation_message_t_tenant_conversation_delete
    ON nexent.conversation_message_t (tenant_id, conversation_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_conversation_message_unit_t_tenant_conversation_delete
    ON nexent.conversation_message_unit_t (tenant_id, conversation_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_conversation_source_image_t_tenant_conversation_delete
    ON nexent.conversation_source_image_t (tenant_id, conversation_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_conversation_source_search_t_tenant_conversation_delete
    ON nexent.conversation_source_search_t (tenant_id, conversation_id, delete_flag);
