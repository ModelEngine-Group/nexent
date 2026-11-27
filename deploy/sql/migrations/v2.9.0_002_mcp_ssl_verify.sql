-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.mcp_record_t
    ADD COLUMN IF NOT EXISTS ssl_verify BOOLEAN NOT NULL DEFAULT TRUE;
COMMENT ON COLUMN nexent.mcp_record_t.ssl_verify IS
    'Verify remote MCP server TLS certificate for discovery, health checks and agent invocation';
