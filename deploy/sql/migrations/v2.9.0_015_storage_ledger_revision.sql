-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
BEGIN;
ALTER TABLE nexent.knowledge_storage_object_t
    ADD COLUMN IF NOT EXISTS version INT4 NOT NULL DEFAULT 0;
COMMENT ON COLUMN nexent.knowledge_storage_object_t.version IS 'Optimistic revision for StorageInterface ledger writes; legacy rows start at zero.';
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'nexent.knowledge_storage_object_t'::regclass
            AND conname = 'ck_knowledge_storage_object_version'
    ) THEN
        ALTER TABLE nexent.knowledge_storage_object_t
            ADD CONSTRAINT ck_knowledge_storage_object_version CHECK (version >= 0);
    END IF;
END $$;
COMMIT;
