-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Serialize deletion admission against new uploads using the existing KB revision.
ALTER TABLE nexent.knowledge_record_t ADD COLUMN IF NOT EXISTS deletion_request JSONB;
COMMENT ON COLUMN nexent.knowledge_record_t.deletion_request IS
    'Management-owned KB deletion snapshot with schema_version, knowledge_id, index_name and user_id; NULL before deletion admission.';
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'nexent.knowledge_record_t'::regclass
          AND conname = 'ck_knowledge_deletion_request'
    ) THEN
        ALTER TABLE nexent.knowledge_record_t ADD CONSTRAINT ck_knowledge_deletion_request CHECK (
            deletion_request IS NULL OR (
                jsonb_typeof(deletion_request) = 'object'
                AND octet_length(deletion_request::text) <= 4096
            )
        );
    END IF;
END $$;
