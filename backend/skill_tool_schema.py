"""Shared JSON schemas for Nexent builtin skill tools."""

from __future__ import annotations

import copy
import json
from typing import Any


_BUILTIN_SKILL_TOOL_INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "run_skill_script": {
        "type": "object",
        "properties": {
            "skill_name": {"type": "string"},
            "script_path": {"type": "string"},
            "params": {
                "type": ["string", "null"],
                "default": None,
            },
        },
        "required": ["skill_name", "script_path"],
    },
    "read_skill_md": {
        "type": "object",
        "properties": {
            "skill_name": {"type": "string"},
            "additional_files": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
        },
        "required": ["skill_name"],
    },
    "read_skill_config": {
        "type": "object",
        "properties": {
            "skill_name": {"type": "string"},
        },
        "required": ["skill_name"],
    },
    "write_skill_file": {
        "type": "object",
        "properties": {
            "skill_name": {"type": "string"},
            "file_path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["skill_name", "file_path", "content"],
    },
}


def get_builtin_skill_tool_input_schema(tool_name: str) -> dict[str, Any]:
    """Return an isolated input schema for a builtin skill tool."""
    try:
        schema = _BUILTIN_SKILL_TOOL_INPUT_SCHEMAS[tool_name]
    except KeyError as exc:
        raise ValueError(f"Unknown builtin skill tool: {tool_name}") from exc
    return copy.deepcopy(schema)


def get_builtin_skill_tool_inputs(tool_name: str) -> str:
    """Serialize a builtin skill tool input schema for legacy ToolConfig."""
    return json.dumps(
        get_builtin_skill_tool_input_schema(tool_name),
        ensure_ascii=False,
    )
