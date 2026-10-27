-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Nexent merged SQL migrations: v2.8.1
-- API-to-MCP service and tool synchronization changes.

-- Keep API-to-MCP tools associated with the service that produced them.
ALTER TABLE nexent.ag_tool_info_t
    ADD COLUMN IF NOT EXISTS outer_api_service_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_ag_tool_info_outer_api_service
    ON nexent.ag_tool_info_t (author, outer_api_service_id);

COMMENT ON COLUMN nexent.ag_tool_info_t.outer_api_service_id IS
    'Source API-to-MCP service ID; NULL for non-OpenAPI tools';

-- Allow each OpenAPI-to-MCP service to opt out of TLS certificate verification.
ALTER TABLE nexent.ag_outer_api_services
    ADD COLUMN IF NOT EXISTS ssl_verify BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE nexent.ag_outer_api_services
SET ssl_verify = TRUE
WHERE ssl_verify IS NULL;

-- Explicitly persist whether authentication headers are enabled for API-to-MCP services.
ALTER TABLE nexent.ag_outer_api_services
    ADD COLUMN IF NOT EXISTS auth_enabled BOOLEAN NOT NULL DEFAULT FALSE;

-- Preserve the effective behavior of existing services that already have headers.
UPDATE nexent.ag_outer_api_services
SET auth_enabled = TRUE
WHERE headers_template IS NOT NULL
  AND headers_template <> '{}'::jsonb;
