-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Phase 1 of northbound MCP header passthrough feature: per-agent opt-in switches.
-- Defaults are FALSE so existing agents are not affected.

ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS allow_mcp_header_passthrough BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.allow_mcp_header_passthrough IS
    'Whether this agent allows northbound callers to inject per-request HTTP headers into the MCP session via metadata._mcp_headers*; disabled by default to prevent silent cross-tenant header leakage';

ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS strict_mcp_placeholder_resolution BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.strict_mcp_placeholder_resolution IS
    'Whether unresolved ${HeaderName} placeholders in MCP static headers abort the run with 400 (enabled) or fail-closed by dropping the header and continuing (disabled, default)';
