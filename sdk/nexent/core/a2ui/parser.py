"""A2UI response parsing helpers."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from .constants import A2UI_CLOSE_TAG, A2UI_MESSAGE_KEYS, A2UI_OPEN_TAG
from .types import A2UIResponsePart

logger = logging.getLogger(__name__)


def is_a2ui_message(value: Any) -> bool:
    """Check if a dict is an A2UI message (contains exactly one of the 4 known keys)."""
    return isinstance(value, dict) and len(A2UI_MESSAGE_KEYS.intersection(value)) == 1


def coerce_message_list(value: Any) -> list[dict[str, Any]] | None:
    """Normalize a single message or list of messages to a list, or return None."""
    if isinstance(value, list) and all(is_a2ui_message(item) for item in value):
        return [copy.deepcopy(item) for item in value]
    if is_a2ui_message(value):
        return [copy.deepcopy(value)]
    return None


def iter_tagged_block_bodies(text: str) -> list[tuple[int, str]]:
    """Extract all bodies between <a2ui-json> and </a2ui-json> tags."""
    blocks: list[tuple[int, str]] = []
    cursor = 0
    while True:
        start = text.find(A2UI_OPEN_TAG, cursor)
        if start < 0:
            return blocks
        body_start = start + len(A2UI_OPEN_TAG)
        end = text.find(A2UI_CLOSE_TAG, body_start)
        if end < 0:
            blocks.append((len(blocks), text[body_start:]))
            return blocks
        blocks.append((len(blocks), text[body_start:end]))
        cursor = end + len(A2UI_CLOSE_TAG)


def strip_tagged_a2ui_blocks(text: str) -> str:
    """Remove all <a2ui-json>...</a2ui-json> blocks from text."""
    output: list[str] = []
    cursor = 0
    while True:
        start = text.find(A2UI_OPEN_TAG, cursor)
        if start < 0:
            output.append(text[cursor:])
            break
        output.append(text[cursor:start])
        end = text.find(A2UI_CLOSE_TAG, start + len(A2UI_OPEN_TAG))
        if end < 0:
            break
        cursor = end + len(A2UI_CLOSE_TAG)
    return "".join(output).strip()


def parse_raw_json(text: str) -> list[dict[str, Any]] | None:
    """Try to parse text as a raw JSON array or single object of A2UI messages."""
    stripped = text.strip()
    if not stripped.startswith(("[", "{")):
        return None
    try:
        return coerce_message_list(json.loads(stripped))
    except json.JSONDecodeError:
        return None


def parse_jsonl(text: str) -> list[dict[str, Any]] | None:
    """Try to parse text as JSONL (one JSON object per line)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or not all(line.startswith("{") and line.endswith("}") for line in lines):
        return None
    messages: list[dict[str, Any]] = []
    try:
        for line in lines:
            parsed = json.loads(line)
            if not is_a2ui_message(parsed):
                return None
            messages.append(parsed)
    except json.JSONDecodeError:
        return None
    return messages


def parse_a2ui_response(content: str) -> list[A2UIResponsePart]:
    """Parse agent response into a list of text/A2UI parts.

    Tries multiple formats in priority order:
    1. JSONL format (one JSON per line)
    2. Raw JSON (array or single object)
    3. Tagged blocks (<a2ui-json>...</a2ui-json>)
    """
    text = content or ""
    if not text.strip():
        return []

    # Try JSONL format
    jsonl_messages = parse_jsonl(text)
    if jsonl_messages is not None:
        return [A2UIResponsePart(kind="a2ui", messages=jsonl_messages)]

    # Try raw JSON format
    raw_json_messages = parse_raw_json(text)
    if raw_json_messages is not None:
        return [A2UIResponsePart(kind="a2ui", messages=raw_json_messages)]

    # Try tagged block format
    blocks = iter_tagged_block_bodies(text)
    if not blocks:
        return [A2UIResponsePart(kind="text", text=text)]

    parts: list[A2UIResponsePart] = []
    cursor = 0
    for _block_index, body in blocks:
        open_idx = text.find(A2UI_OPEN_TAG, cursor)
        if open_idx < 0:
            break
        if open_idx > cursor:
            text_before = text[cursor:open_idx]
            if text_before.strip():
                parts.append(A2UIResponsePart(kind="text", text=text_before))

        close_idx = text.find(A2UI_CLOSE_TAG, open_idx + len(A2UI_OPEN_TAG))
        body_text = text[open_idx + len(A2UI_OPEN_TAG):close_idx] if close_idx > 0 else ""

        messages = parse_raw_json(body_text)
        if messages is not None:
            parts.append(A2UIResponsePart(kind="a2ui", messages=messages))
        else:
            # If parsing fails, include as text with a note
            parts.append(A2UIResponsePart(kind="text", text=f"[A2UI parsing error]\n{body_text}"))

        cursor = close_idx + len(A2UI_CLOSE_TAG) if close_idx > 0 else len(text)

    remaining = text[cursor:]
    if remaining.strip():
        parts.append(A2UIResponsePart(kind="text", text=remaining))

    return parts or [A2UIResponsePart(kind="text", text=text)]


def may_contain_a2ui_content(content: str) -> bool:
    """Check if content might contain A2UI data."""
    text = content or ""
    return bool(
        A2UI_OPEN_TAG in text
        or parse_jsonl(text) is not None
        or parse_raw_json(text) is not None
    )