-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Explicitly persist whether authentication headers are enabled for API-to-MCP services.
ALTER TABLE nexent.ag_outer_api_services
    ADD COLUMN IF NOT EXISTS auth_enabled BOOLEAN NOT NULL DEFAULT FALSE;

-- Preserve the effective behavior of existing services that already have headers.
UPDATE nexent.ag_outer_api_services
SET auth_enabled = TRUE
WHERE headers_template IS NOT NULL
  AND headers_template <> '{}'::jsonb;
