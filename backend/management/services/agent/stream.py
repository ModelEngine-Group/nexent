# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent stream unit projection, retry rollback and safe SSE errors."""

import json
import logging
from typing import Any, Dict, Optional

from consts.agent import SAFE_AGENT_STREAM_ERROR_MESSAGE

try:
    from consts.agent import (
        REASONING_CONFIGURATION_ERROR_CODE,
        SAFE_REASONING_CONFIGURATION_ERROR_MESSAGE,
    )
except ImportError:  # Compatibility with slim test/runtime consts stubs.
    from backend.consts.agent import (
        REASONING_CONFIGURATION_ERROR_CODE,
        SAFE_REASONING_CONFIGURATION_ERROR_MESSAGE,
    )


logger = logging.getLogger(__name__)


def finalize_buffered_unit_fragments(message_units: list[dict[str, Any]]) -> int:
    """Join mergeable unit fragments once and return finalized UTF-8 bytes."""
    finalized_bytes = 0
    for unit in message_units:
        unit.pop("_attempt_id", None)
        fragments = unit.pop("_content_fragments", None)
        if fragments is not None:
            content = "".join(fragments)
            unit["content"] = content
            unit["unit_content"] = content
        finalized_bytes += len(str(unit.get("unit_content", "")).encode("utf-8"))
    return finalized_bytes


def rollback_model_attempt_units(
    message_units: list[dict[str, Any]], attempt_id: str
) -> int:
    """Remove uncommitted model fragments for one physical model attempt."""
    original_count = len(message_units)
    message_units[:] = [
        unit for unit in message_units if unit.get("_attempt_id") != attempt_id
    ]
    return original_count - len(message_units)


def is_stream_unit_continuation(
    current_unit: dict[str, Any] | None,
    mergeable: bool,
    chunk_type: str,
    data: dict[str, Any],
) -> bool:
    """Return whether a chunk can extend the current persisted stream unit."""
    return bool(
        current_unit is not None
        and mergeable
        and current_unit.get("type") == chunk_type
        and current_unit.get("_attempt_id") == data.get("attempt_id")
        and current_unit.get("invocation_id") == data.get("invocation_id")
        and current_unit.get("_step_id") == data.get("step_id")
    )


def serialize_stream_unit_content(data: Dict[str, Any], content: Any) -> str:
    """Preserve structured content and tool metadata in the text unit column."""
    if data.get("type") == "human_interaction" and not isinstance(content, str):
        return json.dumps(content, ensure_ascii=False)
    if data.get("type") not in {"tool", "tool-call"}:
        return content

    payload: Dict[str, Any] = {"content": content}
    for field in ("tool_name", "tool_arguments", "role"):
        if field in data:
            payload[field] = data[field]
    return json.dumps(payload, ensure_ascii=False)


def _is_reasoning_configuration_error(exception: Optional[BaseException]) -> bool:
    """Return whether an exception chain contains a reasoning configuration error."""
    current = exception
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "is_reasoning_configuration_error", False):
            return True
        current = current.__cause__ or current.__context__
    return False


def _reasoning_configuration_error_chunk() -> str:
    error_payload = json.dumps(
        {
            "type": "error",
            "code": REASONING_CONFIGURATION_ERROR_CODE,
            "content": SAFE_REASONING_CONFIGURATION_ERROR_MESSAGE,
        },
        ensure_ascii=False,
    )
    return f"data: {error_payload}\n\n"


def _generic_agent_stream_error_chunk() -> str:
    error_payload = json.dumps(
        {"type": "error", "content": SAFE_AGENT_STREAM_ERROR_MESSAGE},
        ensure_ascii=False,
    )
    return f"data: {error_payload}\n\n"


def safe_agent_stream_error_chunk(exception: Optional[BaseException] = None) -> str:
    """Return a sanitized SSE error chunk without internal exception details."""
    if _is_reasoning_configuration_error(exception):
        return _reasoning_configuration_error_chunk()
    return _generic_agent_stream_error_chunk()


def resolve_answer_completion(
    units: list[dict[str, Any]], event: dict[str, Any]
) -> bool:
    """Remove explicitly reclassified bodies; return whether completion has a body."""
    invocation = event.get("invocation_id")
    if event.get("answer_phase") == "delta" and event.get("step_id"):
        units[:] = [
            unit
            for unit in units
            if not (
                unit.get("invocation_id") == invocation
                and unit["type"] == "final_answer"
                and unit.get("_step_id") != event["step_id"]
            )
        ]
    if event.get("reclassify_step") and event.get("step_id"):
        original = [
            unit
            for unit in units
            if (
                unit.get("invocation_id") == invocation
                and unit.get("_step_id") == event["step_id"]
                and unit["type"] in {"model_output_thinking", "model_output_code"}
            )
        ]
        if original and not event.get("content"):
            first = original[0]
            fragments = [
                fragment
                for unit in original
                for fragment in unit.get(
                    "_content_fragments", [unit.get("content", "")]
                )
            ]
            first.update(
                type="final_answer",
                unit_type="final_answer",
                _content_fragments=fragments,
                content="",
                unit_content="",
            )
            units[:] = [
                unit
                for unit in units
                if unit is first or not any(unit is item for item in original)
            ]
            return False
        units[:] = [
            unit
            for unit in units
            if not (
                unit.get("invocation_id") == invocation
                and unit.get("_step_id") == event["step_id"]
                and unit["type"] in {"model_output_thinking", "model_output_code"}
            )
        ]
    if event.get("answer_phase") == "complete" and event.get("content"):
        units[:] = [
            unit
            for unit in units
            if not (
                unit.get("invocation_id") == invocation
                and unit["type"] == "final_answer"
            )
        ]
    return bool(event.get("content"))


def remove_answer_only_steps(units: list[dict[str, Any]]) -> None:
    """Keep markers only for steps with meaningful reasoning or actions."""
    answers = {
        (unit.get("invocation_id"), unit.get("_step_id"))
        for unit in units
        if unit["type"] == "final_answer"
    }
    actual = set()
    for unit in units:
        content = "".join(unit.get("_content_fragments", [])) or unit.get("content", "")
        if unit["type"] in {
            "model_output_thinking",
            "model_output_deep_thinking",
            "model_output_code",
        }:
            meaningful = bool(str(content).strip())
        else:
            meaningful = unit["type"] in {"tool", "tool-call", "parse"}
        if meaningful:
            actual.add((unit.get("invocation_id"), unit.get("_step_id")))
    units[:] = [
        unit
        for unit in units
        if not (
            unit["type"] == "step_count"
            and (unit.get("invocation_id"), unit.get("_step_id")) in answers - actual
        )
    ]
    for unit in units:
        unit.pop("_step_id", None)
