-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Persist deletion ownership before any Runtime or source cleanup side effect.
ALTER TABLE nexent.knowledge_file_lifecycle_t
    ADD COLUMN IF NOT EXISTS deletion_request JSONB;

COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.deletion_request IS
    'Immutable Management deletion intent with actor, scope, file generation and source snapshot, at most 16 KiB; NULL before admission or for legacy rows.';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'nexent.knowledge_file_lifecycle_t'::regclass
          AND conname = 'ck_knowledge_deletion_request'
    ) THEN
        ALTER TABLE nexent.knowledge_file_lifecycle_t
            ADD CONSTRAINT ck_knowledge_deletion_request CHECK (
                deletion_request IS NULL OR (
                    jsonb_typeof(deletion_request) = 'object'
                    AND octet_length(deletion_request::text) <= 16384
                )
            );
    END IF;
END $$;
