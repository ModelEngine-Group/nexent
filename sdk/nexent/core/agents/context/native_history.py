# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Decode bound storage events and render closed native calls as historical data."""

import json
from collections import OrderedDict

from .history_facts import turn_execution_text, turn_user_text


def decode_history_event(record):
    """Called by the authorized history loader, never on arbitrary model text."""
    try:
        event = json.loads(record.get("content") or "")
    except (ValueError, TypeError):
        return None
    if not isinstance(event, dict) or not (
        event.get("schema_version") == 1 and event.get("runtime_mode") == "native_agent"
        and event.get("agent_core") == "jiuwen" and event.get("type") == record.get("record_type")
        and event.get("type") in {"tool", "tool_result"}
    ):
        return None
    local_id = record.get("tool_call_id")
    if (not local_id or event.get("local_call_id") != local_id
            or event.get("tool_call_id") != local_id
            or event.get("invocation_id") != record.get("invocation_id")):
        return None
    # Child observations remain evidence, not root model tool calls.
    if record.get("invocation_id") or event.get("parent_call_id"):
        return None
    turn = event.get("turn_id")
    if not isinstance(turn, str) or not turn:
        return None
    common = {"kind": event["type"], "local_id": local_id, "turn_id": turn,
              "call_id": event.get("provider_call_id")}
    if event["type"] == "tool_result":
        if not isinstance(event.get("is_error"), bool) or not isinstance(event.get("result"), str):
            return None
        return {**common, "result": event["result"], "is_error": event["is_error"],
                "sequence": event.get("sequence")}
    if (event.get("source_protocol") not in {None, "model_native_fc"}
            or not isinstance(event.get("provider_call_id"), str) or not event["provider_call_id"]):
        return None
    group = event.get("call_group_id") or event.get("block_id") or event.get("step_id")
    index, count = event.get("call_index"), event.get("call_count")
    if (not isinstance(group, str) or not group or type(index) is not int or type(count) is not int
            or not 0 <= index < count or not isinstance(event.get("tool_name"), str)
            or not event["tool_name"]):
        return None
    arguments = event.get("raw_arguments", event.get("tool_arguments"))
    try:
        arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
        if not isinstance(arguments, dict):
            return None
        arguments = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        return None
    return {**common, "group_id": group, "index": index, "count": count,
            "name": event["tool_name"], "arguments": arguments}


def _reference(records):
    return {"role": "assistant", "content": turn_execution_text({"execution_records": records})}


def _fact(record):
    if not isinstance(record, dict):
        return {}
    event = record.get("execution_event")
    if not isinstance(event, dict) or any(not isinstance(event.get(key), str) or not event[key]
                                          for key in ("turn_id", "local_id", "call_id")):
        return {}
    if event.get("kind") == "tool":
        if (any(not isinstance(event.get(key), str) or not event[key]
                for key in ("group_id", "name", "arguments"))
                or type(event.get("index")) is not int or type(event.get("count")) is not int):
            return {}
    elif event.get("kind") != "tool_result" or not isinstance(event.get("result"), str):
        return {}
    return event


def render_native_turn(item):
    """Preserve response boundaries; only complete, unambiguous groups become FC."""
    content = item.content
    records = content.get("execution_records") or []
    groups = OrderedDict()
    results = {}
    for record in records:
        event = _fact(record)
        if not event:
            continue
        if event.get("kind") == "tool":
            key = (event.get("turn_id"), event.get("group_id"))
            groups.setdefault(key, []).append((record, event))
        elif event.get("kind") == "tool_result":
            key = (event.get("turn_id"), event.get("local_id"))
            results.setdefault(key, []).append((record, event))
    projections, used_ids = {}, set()
    for key, entries in groups.items():
        calls, paired, seen = {}, [], {}
        valid = True
        for record, event in entries:
            call_id, local_id = event.get("call_id"), event.get("local_id")
            index, count = event.get("index"), event.get("count")
            if (not isinstance(call_id, str) or not call_id or not isinstance(local_id, str)
                    or type(index) is not int or type(count) is not int or not 0 <= index < count):
                valid = False
                break
            if local_id in seen:
                valid &= seen[local_id] == event
                continue
            seen[local_id] = event
            if index in calls or call_id in used_ids or any(c["id"] == call_id for c in calls.values()):
                valid = False
                break
            observations = results.get((event["turn_id"], local_id), [])
            values = [e for _, e in observations]
            if (not values or any(e != values[0] for e in values[1:])
                    or values[0].get("call_id") != call_id):
                valid = False
                break
            calls[index] = {"id": call_id, "type": "function", "function": {
                "name": event["name"], "arguments": event["arguments"]}}
            paired.append((observations[0][0], {"role": "tool", "tool_call_id": call_id,
                                               "content": values[0]["result"]}))
        counts = {e.get("count") for _, e in entries}
        count = next(iter(counts), 0)
        if not valid or len(counts) != 1 or count > len(entries) or sorted(calls) != list(range(count)):
            continue
        used_ids.update(c["id"] for c in calls.values())
        # Preserve recorded result completion order, independently of call order.
        order = {id(record): i for i, record in enumerate(records)}
        paired.sort(key=lambda pair: order[id(pair[0])])
        consumed = {id(record) for record, _ in entries}
        for _, e in entries:
            consumed.update(id(r) for r, _ in results.get((e["turn_id"], e["local_id"]), []))
        projections[key] = ([{"role": "assistant", "content": None,
                             "tool_calls": [calls[i] for i in sorted(calls)]},
                            *[message for _, message in paired]], consumed)
    messages = [{"role": "user", "content": turn_user_text(content)}]
    emitted, consumed = set(), set()
    for record in records:
        if id(record) in consumed:
            continue
        event = _fact(record)
        key = (event.get("turn_id"), event.get("group_id"))
        if key in projections and key not in emitted:
            projected, group_records = projections[key]
            messages.extend(projected)
            consumed.update(group_records)
            emitted.add(key)
        else:
            messages.append(_reference([record]))
    messages.append({"role": "assistant", "content": str(content["assistant_final_answer"])})
    return messages
