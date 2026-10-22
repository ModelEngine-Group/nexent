-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Keep API-to-MCP tools associated with the service that produced them.
ALTER TABLE nexent.ag_tool_info_t
    ADD COLUMN IF NOT EXISTS outer_api_service_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_ag_tool_info_outer_api_service
    ON nexent.ag_tool_info_t (author, outer_api_service_id);

COMMENT ON COLUMN nexent.ag_tool_info_t.outer_api_service_id IS
    'Source API-to-MCP service ID; NULL for non-OpenAPI tools';
