-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.knowledge_file_lifecycle_t
    ADD COLUMN IF NOT EXISTS local_source_path VARCHAR(2048);

COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.local_source_path IS
    'Management-owned local upload alias; never forwarded to Runtime.';

CREATE INDEX IF NOT EXISTS idx_knowledge_file_local_source
    ON nexent.knowledge_file_lifecycle_t (tenant_id, knowledge_id, local_source_path)
    WHERE delete_flag = 'N' AND local_source_path IS NOT NULL;
