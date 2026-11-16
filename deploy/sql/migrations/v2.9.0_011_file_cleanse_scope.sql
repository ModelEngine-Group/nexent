-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Extend existing run-scoped jobs with a disjoint knowledge-file authorization context.
BEGIN;
ALTER TABLE nexent.file_cleanse_job_t
    ADD COLUMN IF NOT EXISTS scope_kind VARCHAR(30) NOT NULL DEFAULT 'run',
    ADD COLUMN IF NOT EXISTS knowledge_id INT4,
    ADD COLUMN IF NOT EXISTS file_id VARCHAR(32),
    ADD COLUMN IF NOT EXISTS file_version INT4;
ALTER TABLE nexent.file_cleanse_job_t ALTER COLUMN run_id DROP NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'nexent.file_cleanse_job_t'::regclass
          AND conname = 'ck_file_cleanse_job_scope'
    ) THEN
        ALTER TABLE nexent.file_cleanse_job_t ADD CONSTRAINT ck_file_cleanse_job_scope CHECK (
            (scope_kind = 'run' AND run_id IS NOT NULL AND knowledge_id IS NULL
                AND file_id IS NULL AND file_version IS NULL)
            OR (scope_kind = 'knowledge' AND run_id IS NULL AND knowledge_id IS NOT NULL
                AND knowledge_id > 0 AND file_id IS NOT NULL AND file_id ~ '^[0-9a-f]{32}$'
                AND file_version IS NOT NULL AND file_version >= 0)
        );
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_file_cleanse_job_knowledge
    ON nexent.file_cleanse_job_t (tenant_id, knowledge_id, file_id, file_version);
COMMENT ON COLUMN nexent.file_cleanse_job_t.scope_kind IS 'Authorization context: run callback or knowledge file.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.knowledge_id IS 'Knowledge base reference authorized by Management; knowledge scope only.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.file_id IS 'Stable knowledge file identifier; knowledge scope only.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.file_version IS 'Authorized knowledge file generation; knowledge scope only.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.request_hash IS 'SHA256 of the canonical scope-specific cleansing request payload.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.request_payload IS 'Validated run or knowledge cleansing request; no credentials or raw file bytes.';
COMMIT;
