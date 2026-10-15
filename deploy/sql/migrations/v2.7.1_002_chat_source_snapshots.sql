-- Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

-- Add AIDP-specific retrieval snapshots for each search hit.
ALTER TABLE nexent.conversation_source_search_t
    ADD COLUMN IF NOT EXISTS aidp_metadata JSONB,
    ADD COLUMN IF NOT EXISTS aidp_source_reference JSONB;

COMMENT ON COLUMN nexent.conversation_source_search_t.aidp_metadata
    IS 'Opaque AIDP metadata snapshot returned for this retrieval hit';
COMMENT ON COLUMN nexent.conversation_source_search_t.aidp_source_reference
    IS 'AIDP source reference attributes for this retrieval hit, excluding metadata';
