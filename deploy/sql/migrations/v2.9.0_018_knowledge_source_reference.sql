-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_source_search_t
    ADD COLUMN IF NOT EXISTS knowledge_reference JSONB;

COMMENT ON COLUMN nexent.conversation_source_search_t.knowledge_reference IS
    'Validated KB file/image identities and source location, at most 16 KiB; NULL for legacy or non-KB hits';
