# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


"""Shared parsing of DB-cached MCP tool input schemas for lazy connections."""

import ast
import json


def parse_mcp_tool_inputs(tool_config) -> dict:
    """Parse the DB-cached MCP input schema into a properties dict.

    Tool scans persist standard JSON; older rows keep a Python dict repr,
    so both encodings are accepted. Raises ``ValueError`` when the cache is
    missing or unreadable so callers fail fast at agent construction instead
    of silently advertising a wrong schema.
    """
    raw = getattr(tool_config, "inputs", None)
    tool_label = getattr(tool_config, "class_name", None) or getattr(tool_config, "name", None) or "unknown"
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise ValueError(
            f"MCP tool '{tool_label}' has no cached input schema; refresh the MCP tool list and try again"
        )
    if isinstance(raw, dict):
        return raw
    parsed = None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            try:
                parsed = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                parsed = None
    if not isinstance(parsed, dict):
        raise ValueError(
            f"MCP tool '{tool_label}' has an unreadable cached input schema; "
            "refresh the MCP tool list and try again"
        )
    return parsed
