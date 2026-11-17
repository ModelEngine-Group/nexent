-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Existing rows retain unknown execution ownership until explicitly confirmed.
ALTER TABLE nexent.file_cleanse_job_t
    ADD COLUMN IF NOT EXISTS execution_ended BOOLEAN;
ALTER TABLE nexent.file_cleanse_job_t
    ALTER COLUMN execution_ended SET DEFAULT TRUE;
COMMENT ON COLUMN nexent.file_cleanse_job_t.execution_ended IS
    'Confirmed local parser execution and process group have ended; NULL for legacy unknown, independent of object write certainty.';
