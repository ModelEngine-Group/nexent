# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restore backend-bound completed actions, retaining uncovered evidence verbatim."""

import json
import re
from html import unescape

from .execution_history import result_text
from .models import ContextItem, ContextItemInput


def decode_execution_fields(payload):
    """Decode canonical escaped channels without imposing XML character restrictions."""
    try:
        text, fields, position = payload["content"], {}, 0
        for match in re.finditer(r"<(STDOUT|OUTPUT|RETURN_VALUE|ERROR)>(.*?)</\1>(?:\n|$)", text, re.DOTALL):
            if match.start() != position or match[1] in fields:
                return None
            fields[match[1]] = unescape(match[2])
            position = match.end()
        return fields if fields and position == len(text) and result_text(fields) == text else None
    except (KeyError, TypeError, ValueError):
        return None


def register_historical_results(items, history, owner):
    """Grant only completed execution results present in this authorized run snapshot."""
    from .native_history import decode_history_event

    history.authorize_persisted_reads(owner)
    results, refs_by_item = [], {}
    for item in items:
        selected = []
        if item.type == "conversation_turn":
            message = item.content.get("assistant_message_id")
            if type(message) is int and message > 0:
                records = item.content.get("execution_records") or []
                for record, _, fields in persisted_actions(records):
                    selected.append((message, record["unit_index"], result_text(fields)))
                for record in records:
                    event = decode_history_event(record) if record.get("record_type") == "tool_result" else None
                    index = record.get("unit_index")
                    if (event is not None and isinstance(event.get("call_id"), str) and event["call_id"]
                            and type(index) is int and index >= 0):
                        selected.append((message, index, event["result"]))
        results.extend(selected)
        refs_by_item[item.id] = list(dict.fromkeys(
            f"message:{message}/unit-index:{index}" for message, index, _ in selected))
    history.restore_results(owner, results)
    registered = []
    for item in items:
        metadata = {key: value for key, value in item.metadata.items()
                    if key not in {"execution_source_refs", "structured_source_proofs"}}
        if refs_by_item[item.id]:
            metadata["execution_source_refs"] = refs_by_item[item.id]
        registered.append(item if metadata == item.metadata else item.model_copy(update={"metadata": metadata}))
    return registered


def _payload(record):
    if record.get("record_type") != "execution_result" or record.get("invocation_id"):
        return None
    try:
        payload = json.loads(record["content"])
        action = payload["model_action"]
        index = record["unit_index"]
        covered = payload["covered_unit_indices"]
        if (
            type(index) is not int
            or index < 0
            or not isinstance(covered, list)
            or any(type(i) is not int or not 0 <= i < index for i in covered)
            or len(set(covered)) != len(covered)
            or type(action.get("schema_version")) is not int
            or action["schema_version"] != 1
            or action.get("agent_core") != "smolagents"
            or type(action.get("step_number")) is not int
            or action["step_number"] < 0
            or not isinstance(action.get("tool_calls"), list)
            or action.get("dispatch_state") not in {"dispatched", "not_dispatched"}
            or action["dispatch_state"] == "not_dispatched"
            and action["tool_calls"]
        ):
            return None
        for call in action["tool_calls"]:
            if (
                not isinstance(call, dict)
                or any(not isinstance(call.get(k), str) or not call[k] for k in ("id", "name"))
                or not isinstance(call.get("arguments"), (dict, str, type(None)))
            ):
                return None
        fields = decode_execution_fields(payload)
        if fields is None:
            return None
        return payload, fields
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def persisted_actions(records):
    """Accept coverage only over actual earlier root units in this authorized message."""
    by_index = {}
    for record in records:
        index = record.get("unit_index")
        if type(index) is int:
            by_index.setdefault(index, []).append(record)
    candidates = []
    for record in records:
        decoded = _payload(record)
        if decoded is None or len(by_index.get(record["unit_index"], [])) != 1:
            continue
        payload, fields = decoded
        covered = payload["covered_unit_indices"]
        if any(
            len(by_index.get(i, [])) != 1
            or by_index[i][0].get("invocation_id")
            or by_index[i][0].get("record_type") not in {"tool", "tool-call", "execution_logs", "error"}
            for i in covered
        ):
            continue
        candidates.append((record, payload, fields))
    counts = {}
    for _, payload, _ in candidates:
        for index in payload["covered_unit_indices"]:
            counts[index] = counts.get(index, 0) + 1
    return [entry for entry in candidates if all(counts[i] == 1 for i in entry[1]["covered_unit_indices"])]


def render_persisted_actions(records, *, assistant_message_id, history=None, owner=None):
    """Render native source/result once; raw storage remains independently addressable."""
    from .history_facts import _render_legacy_execution_records
    from .rendering import _render_current_action

    if type(assistant_message_id) is not int or assistant_message_id <= 0:
        actions = []
    else:
        actions = persisted_actions(records)
    selected = {id(record): (payload, fields) for record, payload, fields in actions}
    covered = {index for _, payload, _ in actions for index in payload["covered_unit_indices"]}
    parts, raw = [], []

    def flush():
        if raw:
            parts.append(_render_legacy_execution_records(list(raw)))
            raw.clear()

    for record in records:
        accepted = selected.get(id(record))
        if accepted is None:
            if type(record.get("unit_index")) is not int or record["unit_index"] not in covered:
                raw.append(record)
            continue
        flush()
        payload, fields = accepted
        reference = f"message:{assistant_message_id}/unit-index:{record['unit_index']}"
        if history is not None and owner is not None:
            history.restore(owner, assistant_message_id, record["unit_index"], fields)
        action = payload["model_action"]
        content = {
            "step_number": action["step_number"],
            "tool_calls": action["tool_calls"],
            "execution_fields": fields,
            "output_ref": reference,
        }
        view = payload.get("model_view")
        if isinstance(view, dict) and set(view) <= {"summary", "preview"} and len(view) == 1:
            key, value = next(iter(view.items()))
            if isinstance(value, str):
                content[key] = value
        item = ContextItem.from_input(ContextItemInput(id=reference, type="current_action", content=content))
        parts.extend(message["content"][0]["text"] for message in _render_current_action(item))
    flush()
    return "\n".join(parts)
