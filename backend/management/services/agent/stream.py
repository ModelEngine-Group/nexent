# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent stream unit projection, retry rollback and safe SSE errors."""

import json
import logging
from typing import Any, Dict, Optional

from contracts.constants.constants import SAFE_AGENT_STREAM_ERROR_MESSAGE

try:
    from contracts.constants.constants import REASONING_CONFIGURATION_ERROR_CODE, SAFE_REASONING_CONFIGURATION_ERROR_MESSAGE
except ImportError:  # Compatibility with slim test/runtime consts stubs.
    from contracts.constants.constants import REASONING_CONFIGURATION_ERROR_CODE, SAFE_REASONING_CONFIGURATION_ERROR_MESSAGE


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
    sampling = sampling_configuration_error_payload(exception)
    if sampling:
        return f"data: {json.dumps(sampling, ensure_ascii=False)}\n\n"
    if _is_reasoning_configuration_error(exception):
        return _reasoning_configuration_error_chunk()
    return _generic_agent_stream_error_chunk()


def sampling_configuration_error_payload(exception: Optional[BaseException]) -> Optional[dict]:
    """Expose only actionable sampling intent errors, never raw provider details."""
    seen = set()
    while exception is not None and id(exception) not in seen:
        seen.add(id(exception))
        if getattr(exception, "is_sampling_configuration_error", False):
            return {"type": "error", "code": "MODEL_SAMPLING_CONFIG_INVALID",
                    "content": "The model provider rejected temperature or Top P. Restore defaults or change these settings."}
        exception = exception.__cause__ or exception.__context__
    return None


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


class AssistantMessageProjection:
    """Project observer JSON into public event indices and durable assistant units."""

    _MERGEABLE_TYPES = {
        "final_answer", "model_output_code", "model_output_thinking", "model_output_deep_thinking",
    }

    def __init__(self, *, persist_units: bool, next_unit_index: int = 0):
        self.persist_units = persist_units
        self.next_unit_index = next_unit_index
        self.current_unit: dict[str, Any] | None = None
        self.units: list[dict[str, Any]] = []
        self.search_records: list[dict[str, Any]] = []
        self.image_urls: list[str] = []
        self._seen_images: set[str] = set()
        self.automation_proposals: list[dict[str, int]] = []
        self.final_answer_content = ""

    def project(self, chunk: str) -> tuple[str, dict[str, Any]]:
        """Return the forwarded JSON and parsed fields for transport-side handling."""
        try:
            data = json.loads(chunk)
            kind = data.get("type")
            content = data.get("content", "") or ""
            if kind == "final_answer":
                has_body = resolve_answer_completion(self.units, data)
                if data.get("answer_phase") == "complete":
                    self.current_unit = None
                if not has_body:
                    return chunk, data

            mergeable = kind in self._MERGEABLE_TYPES
            continuation = is_stream_unit_continuation(self.current_unit, mergeable, kind, data)
            if self.persist_units and kind:
                if continuation:
                    data["unit_index"] = self.current_unit["unit_index"]
                elif kind != "search_content_placeholder":
                    data["unit_index"] = self.next_unit_index
                chunk = json.dumps(data)
        except Exception:
            # Preserve malformed observer output without adding persistence metadata.
            return chunk, {}

        if kind == "model_attempt_control":
            self.current_unit = None
            attempt = data.get("attempt_id")
            if data.get("phase") == "rollback" and isinstance(attempt, str):
                rollback_model_attempt_units(self.units, attempt)
        elif self.persist_units and kind and kind not in {"skill_artifact", "file_artifact"}:
            if continuation:
                self.current_unit["_content_fragments"].append(content)
            else:
                self._buffer_unit(kind, content, data, mergeable)

        return chunk, data

    def _buffer_unit(self, kind, content, data, mergeable):
        if kind == "final_answer":
            self.final_answer_content = content
        if kind == "picture_web":
            self._buffer_images(content)
        if kind == "search_content":
            self._buffer_search_sources(content, data)
            self.current_unit = None
            self.next_unit_index += 1
            return
        if kind == "history_summary":
            # A checkpoint sink persists this event separately.
            self.current_unit = None
            return
        if kind == "search_content_placeholder":
            return

        persisted_content = serialize_stream_unit_content(data, content)
        unit = {
            "type": kind,
            "content": persisted_content,
            "unit_index": self.next_unit_index,
            "unit_type": kind,
            "unit_content": persisted_content,
            "tool_call_id": data.get("tool_call_id"),
            "invocation_id": data.get("invocation_id"),
            "_attempt_id": data.get("attempt_id"),
            "_step_id": data.get("step_id"),
            "mergeable": mergeable,
        }
        if mergeable:
            unit.update(_content_fragments=[persisted_content], content="", unit_content="")
        self.units.append(unit)
        self.current_unit = unit
        if kind == "automation_proposal":
            try:
                proposal_id = int(json.loads(persisted_content)["proposal_id"])
                self.automation_proposals.append({"unit_index": self.next_unit_index, "proposal_id": proposal_id})
            except (KeyError, TypeError, ValueError):
                logger.warning("Invalid persisted automation proposal event payload")
        self.next_unit_index += 1

    def _buffer_images(self, content):
        try:
            picture = json.loads(content)
            if isinstance(picture, dict):
                for url in picture.get("images_url", []):
                    if url and url not in self._seen_images:
                        self._seen_images.add(url)
                        self.image_urls.append(url)
        except Exception:
            logger.exception("Failed to buffer picture_web sources")

    def _buffer_search_sources(self, chunk_content, data):
        placeholder_index = self.next_unit_index
        self.units.append({
            "type": "search_content_placeholder",
            "content": '{"placeholder": true}',
            "unit_index": placeholder_index,
            "unit_type": "search_content_placeholder",
            "unit_content": '{"placeholder": true}',
            "tool_call_id": data.get("tool_call_id"),
            "invocation_id": data.get("invocation_id"),
            "mergeable": False,
        })
        try:
            search_results = json.loads(chunk_content)
            if not isinstance(search_results, list):
                search_results = [search_results]
            for result in search_results:
                self.search_records.append(
                    {
                        "unit_index": placeholder_index,
                        "source_type": result.get("source_type", ""),
                        "source_title": result.get("title", ""),
                        "source_location": result.get("url", ""),
                        "source_content": result.get("text", ""),
                        "aidp_metadata": result.get(
                            "score_details", {}
                        ).get("metadata"),
                        "aidp_source_reference": {
                            key: value
                            for key, value in result.get(
                                "score_details", {}
                            ).items()
                            if key != "metadata"
                        },
                        "score_overall": float(result.get("score"))
                        if result.get("score") not in (None, "")
                        else None,
                        "score_accuracy": float(
                            result.get("score_details", {}).get(
                                "accuracy"
                            )
                        )
                        if result.get("score_details", {}).get(
                            "accuracy"
                        )
                        not in (None, "")
                        else None,
                        "score_semantic": float(
                            result.get("score_details", {}).get(
                                "semantic"
                            )
                        )
                        if result.get("score_details", {}).get(
                            "semantic"
                        )
                        not in (None, "")
                        else None,
                        "retrieval_highlight_terms": result.get(
                            "score_details", {}
                        ).get("retrieval_highlight_terms", []),
                        "published_date": result.get("published_date")
                        if result.get("published_date")
                        not in (None, "")
                        else None,
                        "cite_index": result.get("cite_index")
                        if result.get("cite_index") != ""
                        else None,
                        "search_type": result.get("search_type")
                        if result.get("search_type")
                        else None,
                        "tool_sign": result.get("tool_sign", ""),
                    }
                )
        except Exception as src_exc:
            logger.error(
                "Failed to buffer search_content sources: %r",
                src_exc,
                exc_info=True,
            )
