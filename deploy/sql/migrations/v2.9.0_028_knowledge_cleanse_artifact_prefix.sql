-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.file_cleanse_job_t ADD COLUMN IF NOT EXISTS artifact_prefix VARCHAR(128);
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'nexent.file_cleanse_job_t'::regclass
          AND conname = 'ck_file_cleanse_artifact_prefix'
    ) THEN
        ALTER TABLE nexent.file_cleanse_job_t ADD CONSTRAINT ck_file_cleanse_artifact_prefix CHECK (
            artifact_prefix IS NULL OR artifact_prefix ~
            '^(run-cleanse/(debug-)?[0-9a-f]{32}/[0-9a-f]{32}/|knowledge-cleanse/[1-9][0-9]{0,9}/[0-9a-f]{32}/(0|[1-9][0-9]{0,9})/[0-9a-f]{32}/)$'
        );
    END IF;
END;
$$;
COMMENT ON COLUMN nexent.file_cleanse_job_t.artifact_prefix IS
'Attested private output directory fixed before parser side effects; NULL means historical ownership is unknown.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.status IS
'queued/running/completed/failed/cancelled/released lifecycle state; released confirms private artifacts are absent.';
