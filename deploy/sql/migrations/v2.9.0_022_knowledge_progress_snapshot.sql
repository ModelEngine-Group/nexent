-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.runtime_knowledge_job_t
    ADD COLUMN IF NOT EXISTS processed_chunks INTEGER,
    ADD COLUMN IF NOT EXISTS total_chunks INTEGER;
ALTER TABLE nexent.knowledge_file_lifecycle_t
    ADD COLUMN IF NOT EXISTS cleanse_status VARCHAR(30),
    ADD COLUMN IF NOT EXISTS runtime_status VARCHAR(30),
    ADD COLUMN IF NOT EXISTS processed_chunks INTEGER,
    ADD COLUMN IF NOT EXISTS total_chunks INTEGER;

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.processed_chunks IS
    'Number of chunks with confirmed vector writes in this attempt; NULL when unknown.';
COMMENT ON COLUMN nexent.runtime_knowledge_job_t.total_chunks IS
    'Fixed chunk count after Runtime prepares text and image inputs; NULL before preparation.';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.cleanse_status IS
    'Last confirmed Management cleansing child state; NULL before observation or for legacy rows.';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.runtime_status IS
    'Last confirmed AgentOS Runtime child state; NULL before observation or for legacy rows.';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.processed_chunks IS
    'Last confirmed Runtime vector-write count for the current file attempt; NULL when unknown.';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.total_chunks IS
    'Fixed Runtime chunk total for the current file attempt; NULL when unknown.';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'nexent.runtime_knowledge_job_t'::regclass
                     AND conname = 'ck_runtime_knowledge_progress') THEN
        ALTER TABLE nexent.runtime_knowledge_job_t ADD CONSTRAINT ck_runtime_knowledge_progress CHECK (
            (processed_chunks IS NULL OR processed_chunks >= 0)
            AND (total_chunks IS NULL OR total_chunks >= 0)
            AND (processed_chunks IS NULL OR total_chunks IS NULL OR processed_chunks <= total_chunks)
        );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'nexent.knowledge_file_lifecycle_t'::regclass
                     AND conname = 'ck_knowledge_file_progress') THEN
        ALTER TABLE nexent.knowledge_file_lifecycle_t ADD CONSTRAINT ck_knowledge_file_progress CHECK (
            (processed_chunks IS NULL OR processed_chunks >= 0)
            AND (total_chunks IS NULL OR total_chunks >= 0)
            AND (processed_chunks IS NULL OR total_chunks IS NULL OR processed_chunks <= total_chunks)
        );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'nexent.knowledge_file_lifecycle_t'::regclass
                     AND conname = 'ck_knowledge_file_child_status') THEN
        ALTER TABLE nexent.knowledge_file_lifecycle_t ADD CONSTRAINT ck_knowledge_file_child_status CHECK (
            (cleanse_status IS NULL OR cleanse_status IN ('queued','running','completed','failed','cancelled'))
            AND (runtime_status IS NULL OR runtime_status IN ('queued','running','completed','failed','cancelled','deleted','cleanup_pending'))
        );
    END IF;
END $$;
