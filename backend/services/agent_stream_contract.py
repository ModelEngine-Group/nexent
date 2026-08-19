"""Shared SSE contracts for Agent runtime streams."""

import json
from typing import Any


RUN_INTERRUPTED_MESSAGE = "The run was interrupted. Please start it again."


def _extract_json_objects_from_text(text: str) -> list[dict[str, Any]]:
    """Extract JSON objects embedded in an SSE chunk or text fragment."""
    if not text:
        return []

    decoder = json.JSONDecoder()
    results: list[dict[str, Any]] = []
    index = 0
    while index < len(text):
        start_index = text.find("{", index)
        if start_index < 0:
            break
        try:
            payload, end_index = decoder.raw_decode(text, start_index)
        except json.JSONDecodeError:
            index = start_index + 1
            continue
        if isinstance(payload, dict):
            results.append(payload)
        index = max(end_index, start_index + 1)
    return results


def _run_interrupted_chunk() -> str:
    """Return the public SSE terminal event for an interrupted Agent run."""
    payload = json.dumps(
        {
            "type": "error",
            "status": "run_interrupted",
            "code": "run_interrupted",
            "content": RUN_INTERRUPTED_MESSAGE,
        },
        ensure_ascii=False,
    )
    return f"data: {payload}\n\n"


def _is_run_interrupted_event(event: dict[str, Any]) -> bool:
    """Return whether a decoded Agent event represents an interruption."""
    return event.get("code") == "run_interrupted" or event.get("status") == "run_interrupted"


def _is_run_interrupted_chunk(chunk: str) -> bool:
    """Return whether an SSE chunk carries the interruption contract."""
    return any(_is_run_interrupted_event(payload) for payload in _extract_json_objects_from_text(chunk))
