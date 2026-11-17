# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Lossless creator checkpoint events and compatibility for unversioned text units."""

import json

from infrastructure.runtime_output import is_runtime_event


_ENVELOPE_TYPES = {
    "model_attempt_control", "agent_new_run", "skill_body", "file_content",
    "target_files", "done",
}
_SEMANTIC_FIELDS = {
    "answer_phase", "answer_preview", "reclassify_step", "step_id", "attempt_id",
    "block_id", "sequence", "phase", "tool_name", "tool_arguments", "provider_call_id",
}


def unpack_creator_event(content, kind):
    """Recognize only our explicit storage envelope, never ordinary JSON answers."""
    try:
        stored = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(stored, dict) or stored.get("creator_event_version") != 1:
        return None
    event = stored.get("event")
    if isinstance(event, dict) and event.get("type") == kind:
        return event
    return None


def creator_event_content(event, content):
    """Retain established card/file formats and version previously lossy metadata."""
    kind = event["type"]
    if is_runtime_event(event) or kind in _ENVELOPE_TYPES:
        return json.dumps(event, ensure_ascii=False)
    if kind not in {"nl2a", "nl2a_state"} and _SEMANTIC_FIELDS.intersection(event):
        return json.dumps({"creator_event_version": 1, "event": event}, ensure_ascii=False)
    return content


def unit_event(unit, context=None):
    """Decode saved facts; old text follows the historical loader's delta contract."""
    kind = unit["unit_type"]
    content = unit.get("unit_content") or ""
    event = unpack_creator_event(content, kind)
    if event is None:
        try:
            saved = json.loads(content)
        except (TypeError, ValueError):
            saved = None
        if isinstance(saved, dict) and (
            kind in _ENVELOPE_TYPES or is_runtime_event(saved) and saved.get("type") == kind
        ):
            event = saved
    if event is None:
        event = {
            "type": kind, "content": content,
            "tool_call_id": unit.get("tool_call_id"),
            "invocation_id": unit.get("invocation_id"),
        }
        if kind == "final_answer":
            event["answer_phase"] = "delta"
        if context is not None:
            event.update(context.get(event.get("invocation_id"), {}))
    event = {**event, "unit_index": unit["unit_index"]}
    if context is not None and kind == "model_attempt_control" and event.get("attempt_id"):
        scope = event.get("invocation_id")
        checkpoint = (scope, event["attempt_id"])
        if event.get("phase") == "begin":
            context[checkpoint] = dict(context.get(scope, {}))
            context[scope] = {key: event[key] for key in ("step_id", "attempt_id") if key in event}
        else:
            previous = context.pop(checkpoint, {})
            if event.get("phase") == "rollback":
                context[scope] = previous
    return event


class CreatorAnswer:
    """Keep the durable root answer consistent with complete/rollback boundaries."""

    def __init__(self):
        self.content = ""
        self.step = None
        self.attempts = {}

    def push(self, event):
        if event.get("invocation_id"):
            return
        kind = event["type"]
        if kind == "model_attempt_control" and event.get("attempt_id"):
            attempt = event["attempt_id"]
            if event.get("phase") == "begin":
                self.attempts[attempt] = self.content, self.step
            else:
                saved = self.attempts.pop(attempt, None)
                if event.get("phase") == "rollback" and saved is not None:
                    self.content, self.step = saved
        elif kind == "final_answer":
            text = str(event.get("content") or "")
            if event.get("answer_phase") == "complete":
                if text:
                    self.content = text
            else:
                step = event.get("step_id")
                if step and step != self.step:
                    self.content = ""
                if step:
                    self.step = step
                self.content += text
