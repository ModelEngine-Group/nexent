# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restore backend-bound completed actions, retaining uncovered evidence verbatim."""

import json
from xml.etree import ElementTree

from .execution_history import result_text
from .models import ContextItem, ContextItemInput


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
        root = ElementTree.fromstring("<fields>" + payload["content"] + "</fields>")
        fields = {}
        for node in root:
            if node.tag not in {"STDOUT", "OUTPUT", "RETURN_VALUE", "ERROR"} or len(node) or node.tag in fields:
                return None
            fields[node.tag] = node.text or ""
        if not fields or result_text(fields) != payload["content"]:
            return None
        return payload, fields
    except (KeyError, TypeError, ValueError, AttributeError, ElementTree.ParseError):
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
    from .history_facts import turn_execution_text
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
            parts.append(turn_execution_text({"execution_records": list(raw)}))
            raw.clear()

    for record in records:
        accepted = selected.get(id(record))
        if accepted is None:
            if record.get("record_type") != "execution_result" and (
                type(record.get("unit_index")) is not int or record["unit_index"] not in covered
            ):
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
