-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
BEGIN;
ALTER TABLE nexent.knowledge_file_lifecycle_t ADD COLUMN IF NOT EXISTS source_upload_sha256 VARCHAR(64);
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.source_upload_sha256 IS 'Expected source SHA256 persisted before upload; null for legacy intents.';
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='nexent.knowledge_file_lifecycle_t'::regclass
        AND conname='ck_knowledge_source_upload_intent') THEN
        ALTER TABLE nexent.knowledge_file_lifecycle_t ADD CONSTRAINT ck_knowledge_source_upload_intent CHECK (
            (source_upload_sha256 IS NULL OR source_upload_sha256 ~ '^[0-9a-f]{64}$')
            AND (stage IS DISTINCT FROM 'SOURCE_UPLOAD' OR
                (source_upload_sha256 IS NOT NULL AND file_size IS NOT NULL AND file_size >= 0))
        );
    END IF;
END $$;
COMMIT;
