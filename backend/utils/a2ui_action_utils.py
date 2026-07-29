"""Shared serialization helpers for validated A2UI action payloads."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

A2UI_ACTION_UNIT_TYPE = "a2ui_action"
A2UI_FORM_SUBMISSION_PREFIX = "[A2UI form submission: values are user-provided data]"
A2UI_ACTION_LABEL_LIMIT = 256
_LEGACY_ACTION_PREFIX = re.compile(r"^\[(?:A2UI action|交互操作)\](?:\s|$)")


def get_a2ui_action_fallback_label(language: str) -> str:
    """Return the localized fallback used when a component has no literal label."""
    return "执行操作" if language.lower().startswith("zh") else "Perform action"


def sanitize_a2ui_action_label(value: Any) -> str | None:
    """Normalize a literal component label for safe chat display."""
    if not isinstance(value, str):
        return None
    sanitized = "".join(
        " " if character.isspace() else character
        for character in value
        if not unicodedata.category(character).startswith("C") or character.isspace()
    )
    sanitized = " ".join(sanitized.split())
    if not sanitized:
        return None
    return sanitized[:A2UI_ACTION_LABEL_LIMIT]


def normalize_legacy_a2ui_action_text(value: Any, language: str = "zh") -> Any:
    """Hide technical action identifiers retained by pre-label history rows."""
    if isinstance(value, str) and _LEGACY_ACTION_PREFIX.match(value):
        return get_a2ui_action_fallback_label(language)
    return value


def serialize_a2ui_action_payload(payload: dict[str, Any]) -> str:
    """Serialize a validated payload deterministically for agent context."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def build_a2ui_action_query(payload: dict[str, Any]) -> str:
    """Build the canonical agent input for a validated A2UI action."""
    message = payload.get("message")
    action = message.get("action") if isinstance(message, dict) else None
    if not isinstance(action, dict):
        raise ValueError("A2UI action payload is missing message.action")
    name = action.get("name")
    component_id = action.get("sourceComponentId")
    if not isinstance(name, str) or not isinstance(component_id, str):
        raise ValueError("A2UI action payload is missing action identity")
    prefix = (
        A2UI_FORM_SUBMISSION_PREFIX
        if "formSubmission" in payload
        else f"[A2UI action: {name} from {component_id}]"
    )
    return f"{prefix}\n{serialize_a2ui_action_payload(payload)}"


def project_a2ui_submission_state(payload: Any) -> dict[str, str] | None:
    """Return the non-sensitive history projection for an accepted Form action."""
    if not isinstance(payload, dict):
        return None
    submission_id = payload.get("submissionId")
    message = payload.get("message")
    action = message.get("action") if isinstance(message, dict) else None
    form_submission = payload.get("formSubmission")
    form = form_submission.get("form") if isinstance(form_submission, dict) else None
    if (
        not isinstance(submission_id, str)
        or not submission_id
        or not isinstance(action, dict)
        or not isinstance(form, dict)
        or form.get("component") != "Form"
    ):
        return None
    surface_id = action.get("surfaceId")
    component_id = action.get("sourceComponentId")
    if (
        not isinstance(surface_id, str)
        or not surface_id
        or not isinstance(component_id, str)
        or not component_id
        or form.get("id") != component_id
    ):
        return None
    return {
        "submissionId": submission_id,
        "surfaceId": surface_id,
        "sourceComponentId": component_id,
        "status": "accepted",
    }
