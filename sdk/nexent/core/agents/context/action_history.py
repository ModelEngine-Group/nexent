# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restore backend-bound completed actions, retaining uncovered evidence verbatim."""

import json
from xml.etree import ElementTree

from .execution_history import result_text
from .models import ContextItem, ContextItemInput


def decode_execution_fields(payload):
    """Decode the exact canonical original, including empty and error channels."""
    try:
        root = ElementTree.fromstring("<fields>" + payload["content"] + "</fields>")
        fields = {}
        for node in root:
            if node.tag not in {"STDOUT", "OUTPUT", "RETURN_VALUE", "ERROR"} or len(node) or node.tag in fields:
                return None
            fields[node.tag] = node.text or ""
        return fields if fields and result_text(fields) == payload["content"] else None
    except (KeyError, TypeError, ValueError, ElementTree.ParseError):
        return None


def _historical_source(source):
    kind = source.get("record_type", "execution_result")
    common = {"message_id": source["message_id"], "unit_index": source.get("unit_index"),
              "source_kind": kind, "tool_call_id": source.get("tool_call_id")}
    if kind == "user_message":
        text = source["content"]
        return {**common, "text": text, "parts": (text,)}
    if kind == "execution_result":
        fields = decode_execution_fields(json.loads(source["content"]))
        if fields is not None:
            return {**common, "text": result_text(fields), "parts": tuple(fields.values()), "fields": fields}
    if kind == "tool_result":
        from .native_history import decode_history_event

        event = decode_history_event({**source, "record_type": "tool_result", "invocation_id": None})
        if event is not None and isinstance(event.get("call_id"), str) and event["call_id"]:
            return {**common, "text": event["result"], "parts": (event["result"],)}
    raise PermissionError("Invalid historical source provenance")


def register_authorized_sources(items, history, owner):
    """Restore only authorized private sources; never authorize model-provided references."""
    sources, refs_by_item, expected_proofs = [], {}, []
    for item in items:
        selected = []
        if item.type == "history_summary":
            selected.extend(item.content.get("execution_sources", []))
            expected_proofs.extend(item.content.get("structured_source_proofs", []))
        elif item.type == "conversation_turn":
            content = item.content
            if type(content.get("user_message_id")) is int and content["user_message_id"] > 0:
                selected.append({"record_type": "user_message", "message_id": content["user_message_id"],
                                 "unit_index": None, "content": content.get("user_source_content") if isinstance(content.get("user_source_content"), str) else content["user_message"]})
            records = content.get("execution_records") or []
            for record, _, _ in persisted_actions(records):
                selected.append({**record, "message_id": content["assistant_message_id"]})
            from .native_history import decode_history_event
            for record in records:
                event = decode_history_event(record) if record.get("record_type") == "tool_result" else None
                if event is not None and isinstance(event.get("call_id"), str) and event["call_id"]:
                    selected.append({**record, "message_id": content["assistant_message_id"]})
        refs = []
        for source in selected:
            sources.append(_historical_source(source))
            suffix = "user-message" if source.get("record_type") == "user_message" else f"unit-index:{source['unit_index']}"
            refs.append(f"message:{source['message_id']}/{suffix}")
        refs_by_item[item.id] = list(dict.fromkeys(refs))
    history.restore_sources(owner, sources, expected_proofs=expected_proofs)
    index = history.structured_source_index(owner)
    authorized = []
    for item in items:
        metadata = {key: value for key, value in item.metadata.items()
                    if key not in {"execution_source_refs", "structured_source_proofs"}}
        if refs_by_item[item.id]:
            metadata["execution_source_refs"] = refs_by_item[item.id]
            proofs = [proof for proof in index.collections.values() if proof["source_ref"] in refs_by_item[item.id]]
            if proofs:
                metadata["structured_source_proofs"] = proofs
        authorized.append(item if metadata == item.metadata else item.model_copy(update={"metadata": metadata}))
    return authorized


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
