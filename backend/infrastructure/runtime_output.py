# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Validate the explicit root result without inferring success from stream EOF."""

import json

from nexent.core.agents.output.answer import AnswerBoundaryError, PublicTextFilter, normalize_public_answer
from nexent.core.agents.contracts.output import RunResult


def is_runtime_event(event):
    return (event.get("schema_version") == 1 and event.get("runtime_mode") == "native_agent"
            and event.get("agent_core") == "jiuwen")


def _restore_duplicate_runtime_envelope(event):
    """Repair the old non-text double wrapper only when all event metadata agrees."""
    if event.get("type") not in {"step_count", "tool", "tool_result", "step_observation", "run_terminal"}:
        return event
    try:
        nested = json.loads(event.get("content", ""))
    except (ValueError, TypeError):
        return event
    if (
        isinstance(nested, dict)
        and is_runtime_event(nested)
        and {key: value for key, value in nested.items() if key != "content"}
        == {key: value for key, value in event.items() if key != "content"}
    ):
        return nested
    return event


def project_runtime_history(content, units):
    """Clean proven runtime records for display without rewriting audit data or user messages."""
    parsed = []
    for unit in units:
        try:
            event = json.loads(unit.get("unit_content", ""))
        except (ValueError, TypeError):
            event = None
        parsed.append(event if isinstance(event, dict) and is_runtime_event(event) else None)
    if not any(parsed):
        return content, units, False
    native_invocations = {e.get("invocation_id") for e in parsed if e}
    filters = {}
    projected = []
    invalid_root = False

    def final(text):
        try:
            return normalize_public_answer(text), False
        except AnswerBoundaryError:
            return "", True

    for unit, event in zip(units, parsed):
        item = dict(unit)
        if event:
            if event.get("type") == item.get("unit_type"):
                event = _restore_duplicate_runtime_envelope(event)
            event = dict(event)
            kind = event.get("type")
            if kind in {"model_output", "model_output_deep_thinking"}:
                key = (event.get("turn_id"), event.get("invocation_id"), event.get("block_id"), kind)
                event["content"] = filters.setdefault(key, PublicTextFilter()).push(event.get("content", ""))
            elif kind == "run_terminal" and event.get("status") == "completed":
                # A terminal clarification intentionally has no final answer. Keep
                # its explicit state without weakening normal answer validation.
                waiting = (event.get("end_reason") == "awaiting_input"
                           and event.get("final_content") == ""
                           and event.get("final_block_ids") == []
                           and event.get("error") is None)
                event["final_content"], invalid = ("", False) if waiting else final(event.get("final_content", ""))
                if invalid:
                    event.update(status="failed", final_block_ids=[], end_reason="JIUWEN_FINAL_OUTPUT_INVALID",
                                 error={"category": "JIUWEN_FINAL_OUTPUT_INVALID", "scope": "protocol",
                                        "retryable": False, "safe_message": "JIUWEN_FINAL_OUTPUT_INVALID"})
                    invalid_root |= not event.get("invocation_id")
                # Persisted terminal content also carries a serialized RunResult.
                # Keep both representations consistent for all existing consumers.
                if "content" in event:
                    event["content"] = json.dumps({key: event[key] for key in (
                        "turn_id", "status", "end_reason", "final_content", "final_block_ids", "error"
                    ) if key in event}, ensure_ascii=False)
            item["unit_content"] = json.dumps(event, ensure_ascii=False)
        elif item.get("unit_type") == "final_answer" and item.get("invocation_id") in native_invocations:
            item["unit_content"], invalid = final(item.get("unit_content", ""))
            invalid_root |= invalid and not item.get("invocation_id")
        projected.append(item)
    if None in native_invocations:
        content, invalid = final(content) if content else (content, False)
        invalid_root |= invalid
    return content, projected, invalid_root


class RuntimeOutputState:
    def __init__(self, required=False):
        self.required = required
        self.result = None
        self.invalid = False

    def observe(self, event):
        if not is_runtime_event(event) or event.get("invocation_id"):
            return
        self.required = True
        if self.result is not None:
            self.invalid = True
        if event.get("type") == "run_terminal":
            try:
                self.result = RunResult.model_validate({key: event[key] for key in (
                    "turn_id", "status", "end_reason", "final_content", "final_block_ids", "error",
                ) if key in event})
            except ValueError:
                self.invalid = True

    @property
    def status(self):
        return self.result.status if self.result is not None and not self.invalid else "failed"

    @property
    def final_content(self):
        return self.result.final_content if self.status == "completed" else ""
