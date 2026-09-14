"""Convert A2UI JSON content to AG-UI ACTIVITY_SNAPSHOT wire format.

This module bridges the A2UI protocol (agent-emitted beginRendering /
surfaceUpdate / dataModelUpdate / deleteSurface messages) with the AG-UI
wire contract that assistant-ui's JSONGenerativeUI expects on the stream:

    {
        "type": "ACTIVITY_SNAPSHOT",
        "messageId": "a2ui-surface-call_<surfaceId>",
        "activityType": "a2ui-surface",
        "replace": true,
        "content": { "a2ui_operations": [...] }
    }

The conversion is lossless for v0.9 A2UI surfaces. Components remain in
their A2UI adjacency-list form (id + component + children references);
assistant-ui's useAgUiRuntime performs the A2UI -> generative-ui
conversion on the client side.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from .constants import (
    A2UI_CLOSE_TAG,
    A2UI_MESSAGE_KEYS,
    A2UI_OPEN_TAG,
)

logger = logging.getLogger(__name__)


def extract_surface_id(operations: list[dict[str, Any]]) -> str:
    """Deterministically pick a surface id from the operations list.

    Prefers explicit surfaceId fields; falls back to a uuid4-derived id.
    """
    for op in operations:
        if not isinstance(op, dict):
            continue
        for key in ("createSurface", "updateSurface", "updateComponents",
                    "updateDataModel", "deleteSurface"):
            target = op.get(key)
            if isinstance(target, dict):
                sid = target.get("surfaceId")
                if isinstance(sid, str) and sid:
                    return sid
    return uuid.uuid4().hex[:12]


def _strip_tags(text: str) -> str:
    """Remove <a2ui-json> and </a2ui-json> wrappers if present."""
    if A2UI_OPEN_TAG in text:
        text = text[text.find(A2UI_OPEN_TAG) + len(A2UI_OPEN_TAG):]
    if A2UI_CLOSE_TAG in text:
        text = text[:text.find(A2UI_CLOSE_TAG)]
    return text.strip()


def parse_a2ui_content(content: str) -> list[dict[str, Any]] | None:
    """Parse raw content (text, tagged block, JSON, or JSONL) into A2UI messages.

    Supports JSONL, multi-line JSON objects, JSON array, and single JSON object.
    Uses json.JSONDecoder().raw_decode() for robust multi-object extraction,
    matching the strategy used by the validator so both paths give the same result.

    Returns None when content is not parseable A2UI at all.
    """
    text = _strip_tags(content) if content else ""
    if not text:
        return None

    # 1. Try raw_decode for multiple concatenated JSON objects (most common for A2UI)
    decoder = json.JSONDecoder()
    messages: list[dict[str, Any]] = []
    idx = 0
    text_len = len(text)

    while idx < text_len:
        while idx < text_len and text[idx] in " \t\n\r":
            idx += 1
        if idx >= text_len:
            break
        try:
            obj, end_idx = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict) and A2UI_MESSAGE_KEYS.intersection(obj):
            messages.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict) and A2UI_MESSAGE_KEYS.intersection(item):
                    messages.append(item)
        idx = end_idx

    if messages:
        return messages

    # 2. Fallback: try single JSON object or array
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and A2UI_MESSAGE_KEYS.intersection(item)] or None
    if isinstance(data, dict) and A2UI_MESSAGE_KEYS.intersection(data):
        return [data]
    return None


def _ensure_v_prefix(version: str) -> str:
    """Normalize version strings: '0.9' → 'v0.9', 'v0.9' → 'v0.9'."""
    if not version:
        return "v0.9"
    return version if version.startswith("v") else f"v{version}"


def a2ui_messages_to_operations(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert A2UI protocol messages to AG-UI a2ui_operations."""
    operations: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        version = _ensure_v_prefix(str(msg.get("version", "0.9")))

        if "beginRendering" in msg:
            begin = msg["beginRendering"]
            if isinstance(begin, dict):
                schema = begin.get("schema", {})
                schema_version = version
                if isinstance(schema, dict):
                    raw = schema.get("version", "0.9")
                    schema_version = _ensure_v_prefix(str(raw))
                operations.append({
                    "version": schema_version,
                    "createSurface": {
                        "surfaceId": begin.get("surfaceId", ""),
                    },
                })

        elif "surfaceUpdate" in msg:
            surface = msg["surfaceUpdate"]
            if isinstance(surface, dict):
                components = surface.get("components")
                if components is not None:
                    operations.append({
                        "version": version,
                        "updateComponents": {
                            "surfaceId": surface.get("surfaceId", ""),
                            "components": components,
                        },
                    })
                else:
                    operations.append({
                        "version": version,
                        "updateSurface": surface,
                    })

        elif "dataModelUpdate" in msg:
            data = msg["dataModelUpdate"]
            if isinstance(data, dict):
                operations.append({
                    "version": version,
                    "updateDataModel": {
                        "surfaceId": data.get("surfaceId", ""),
                        "path": data.get("path", "/"),
                        "contents": data.get("contents", []),
                    },
                })

        elif "deleteSurface" in msg:
            delete = msg["deleteSurface"]
            if isinstance(delete, dict):
                operations.append({
                    "version": version,
                    "deleteSurface": {
                        "surfaceId": delete.get("surfaceId", ""),
                    },
                })

    return operations


def wrap_as_activity_snapshot(content: str) -> dict[str, Any] | None:
    """Wrap A2UI JSON content into an AG-UI ACTIVITY_SNAPSHOT event.

    Returns None when the content is not A2UI or cannot be parsed.
    The returned dict is ready for JSON serialization as an SSE ``data:`` line.
    """
    messages = parse_a2ui_content(content)
    if messages is None:
        return None

    operations = a2ui_messages_to_operations(messages)
    if not operations:
        return None

    surface_id = extract_surface_id(operations)
    result = {
        "type": "ACTIVITY_SNAPSHOT",
        "messageId": f"a2ui-surface-call_{surface_id}",
        "activityType": "a2ui-surface",
        "replace": True,
        "content": {"a2ui_operations": operations},
    }
    return result


def is_activity_snapshot(obj: Any) -> bool:
    """Return True when ``obj`` is a parsed ACTIVITY_SNAPSHOT dict."""
    return (
        isinstance(obj, dict)
        and obj.get("type") == "ACTIVITY_SNAPSHOT"
        and obj.get("activityType") == "a2ui-surface"
        and isinstance(obj.get("content"), dict)
        and "a2ui_operations" in obj["content"]
    )


__all__ = [
    "a2ui_messages_to_operations",
    "extract_surface_id",
    "is_activity_snapshot",
    "parse_a2ui_content",
    "wrap_as_activity_snapshot",
]
