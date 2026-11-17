-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Preserve unknown historical counts; only confirmed Runtime results populate this field.
ALTER TABLE nexent.knowledge_file_lifecycle_t
    ADD COLUMN IF NOT EXISTS deleted_vector_count INTEGER;
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.deleted_vector_count IS
    'Runtime-confirmed removed vector records for full deletion; NULL for unconfirmed or source-only operations.';
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'nexent.knowledge_file_lifecycle_t'::regclass
          AND conname = 'ck_knowledge_file_deleted_vector_count'
    ) THEN
        ALTER TABLE nexent.knowledge_file_lifecycle_t
            ADD CONSTRAINT ck_knowledge_file_deleted_vector_count CHECK (deleted_vector_count >= 0);
    END IF;
END $$;

-- The existing KB model has no revision; the finite SI metadata mapping requires one.
ALTER TABLE nexent.knowledge_record_t
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 0;
COMMENT ON COLUMN nexent.knowledge_record_t.version IS
    'Revision for StorageInterface knowledge metadata updates; existing ORM response models do not expose this field.';
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'nexent.knowledge_record_t'::regclass
          AND conname = 'ck_knowledge_record_version'
    ) THEN
        ALTER TABLE nexent.knowledge_record_t
            ADD CONSTRAINT ck_knowledge_record_version CHECK (version >= 0);
    END IF;
END $$;
