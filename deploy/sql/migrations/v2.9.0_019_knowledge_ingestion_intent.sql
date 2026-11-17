-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.knowledge_file_lifecycle_t
    ADD COLUMN IF NOT EXISTS ingestion_request JSONB;

COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.ingestion_request IS
    'Validated Management ingestion intent snapshot, at most 16 KiB; NULL for legacy or unadmitted files.';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'nexent.knowledge_file_lifecycle_t'::regclass
          AND conname = 'ck_knowledge_ingestion_request'
    ) THEN
        ALTER TABLE nexent.knowledge_file_lifecycle_t
            ADD CONSTRAINT ck_knowledge_ingestion_request CHECK (
                ingestion_request IS NULL OR (
                    jsonb_typeof(ingestion_request) = 'object'
                    AND octet_length(ingestion_request::text) <= 16384
                )
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_knowledge_ingestion_pending
    ON nexent.knowledge_file_lifecycle_t (update_time, file_id)
    WHERE delete_flag = 'N' AND ingestion_request IS NOT NULL
      AND status IN ('UPLOADED', 'PROCESSING', 'FORWARDING');
