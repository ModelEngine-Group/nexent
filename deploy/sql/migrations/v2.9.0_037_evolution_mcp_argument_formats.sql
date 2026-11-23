-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.ag_tool_instance_t ADD COLUMN IF NOT EXISTS released_argument_formats json;
COMMENT ON COLUMN nexent.ag_tool_instance_t.released_argument_formats IS
    'Deterministic public MCP argument formats approved for this business agent version.';
