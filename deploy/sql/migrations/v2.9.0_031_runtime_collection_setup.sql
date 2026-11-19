-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.runtime_knowledge_chunk_state_t
    ADD COLUMN IF NOT EXISTS collection_setup JSONB;

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_state_t.collection_setup IS
    'Current bounded collection setup owner, dimensions, model binding and unknown-result fence; NULL permits normal KB lifecycle operations.';
