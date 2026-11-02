-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS http_headers JSONB NOT NULL DEFAULT '{}'::jsonb;
COMMENT ON COLUMN nexent.model_record_t.http_headers IS
    'Credential-bearing custom HTTP headers; never included in outlet snapshots or public API values.';
