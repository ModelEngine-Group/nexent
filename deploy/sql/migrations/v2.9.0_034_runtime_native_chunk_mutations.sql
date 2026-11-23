-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.runtime_knowledge_chunk_change_t
    ADD COLUMN IF NOT EXISTS native_documents boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.native_documents IS
    'Physical mutation target uses the original knowledge index.';
