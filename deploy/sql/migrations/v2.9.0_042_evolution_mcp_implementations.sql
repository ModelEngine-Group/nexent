-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.ag_tool_instance_t
    ADD COLUMN IF NOT EXISTS released_mcp_implementation JSONB;

COMMENT ON COLUMN nexent.ag_tool_instance_t.released_mcp_implementation
    IS 'Verified MCP image and deployment digest for this released tool instance';
