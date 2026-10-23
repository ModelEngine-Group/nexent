-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Allow each OpenAPI-to-MCP service to opt out of TLS certificate verification.
ALTER TABLE nexent.ag_outer_api_services
    ADD COLUMN IF NOT EXISTS ssl_verify BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE nexent.ag_outer_api_services
SET ssl_verify = TRUE
WHERE ssl_verify IS NULL;
