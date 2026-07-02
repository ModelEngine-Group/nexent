-- W4: conversation ownership isolation.
--
-- conversation_record_t is the single source of ownership truth:
--   tenant_id  -> owning tenant
--   created_by -> immutable owning user for conversation access control
-- Conversation child tables do not duplicate tenant_id; they are authorized by
-- joining or subquerying through conversation_record_t.

\set default_tenant_id '''tenant_id'''

ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100);

COMMENT ON COLUMN nexent.conversation_record_t.tenant_id IS
    'Tenant ID for conversation ownership isolation';

COMMENT ON COLUMN nexent.conversation_record_t.created_by IS
    'Creator ID, audit field; W4 immutable owner user for the conversation';

-- Backfill existing conversations from the user-tenant relationship. Preserve
-- real tenant values when already present, and only fill missing/placeholder
-- values. The speed-mode bootstrap user maps to the default tenant_id row.
UPDATE nexent.conversation_record_t cr
SET tenant_id = COALESCE(
    (
        SELECT ut.tenant_id
        FROM nexent.user_tenant_t ut
        WHERE ut.user_id = cr.created_by
        ORDER BY
            CASE WHEN ut.tenant_id = :default_tenant_id THEN 0 ELSE 1 END,
            (ut.create_time IS NULL) ASC,
            ut.create_time ASC,
            ut.user_tenant_id ASC
        LIMIT 1
    ),
    :default_tenant_id
)
WHERE NULLIF(cr.tenant_id, '') IS NULL
   OR cr.tenant_id = :default_tenant_id;

CREATE INDEX IF NOT EXISTS idx_conversation_record_t_tenant_user_conversation_delete
    ON nexent.conversation_record_t (tenant_id, created_by, conversation_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_conversation_record_t_tenant_conversation_delete
    ON nexent.conversation_record_t (tenant_id, conversation_id, delete_flag);

-- Remove the earlier W4 draft's duplicated child-table tenant columns when this
-- migration is reapplied in development or pre-release environments.
DROP INDEX IF EXISTS nexent.idx_conversation_record_t_tenant_user_delete;
DROP INDEX IF EXISTS nexent.idx_conversation_message_t_tenant_conversation_delete;
DROP INDEX IF EXISTS nexent.idx_conversation_message_unit_t_tenant_conversation_delete;
DROP INDEX IF EXISTS nexent.idx_conversation_source_image_t_tenant_conversation_delete;
DROP INDEX IF EXISTS nexent.idx_conversation_source_search_t_tenant_conversation_delete;

ALTER TABLE nexent.conversation_message_t
    DROP COLUMN IF EXISTS tenant_id;

ALTER TABLE nexent.conversation_message_unit_t
    DROP COLUMN IF EXISTS tenant_id;

ALTER TABLE nexent.conversation_source_image_t
    DROP COLUMN IF EXISTS tenant_id;

ALTER TABLE nexent.conversation_source_search_t
    DROP COLUMN IF EXISTS tenant_id;
