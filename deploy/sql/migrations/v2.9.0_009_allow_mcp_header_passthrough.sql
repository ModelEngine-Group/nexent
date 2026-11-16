-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Phase 1 of northbound MCP header passthrough feature: per-agent opt-in switch.
-- Default is FALSE so existing agents are not affected.

ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS allow_mcp_header_passthrough BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.allow_mcp_header_passthrough IS
    'Whether this agent allows northbound callers to inject per-request HTTP headers into the MCP session via metadata._mcp_headers*; disabled by default to prevent silent cross-tenant header leakage';
