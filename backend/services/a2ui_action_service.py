"""Authorization and idempotency checks for A2UI v0.9 actions."""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from consts.model import A2UIActionSubmission
from database.conversation_db import get_conversation_history
from utils.a2ui_action_utils import (
    get_a2ui_action_fallback_label,
    project_a2ui_submission_state,
    sanitize_a2ui_action_label,
    serialize_a2ui_action_payload,
)
from utils.redis_utils import get_redis_client

_ACTION_TTL_SECONDS = 24 * 60 * 60
_ACTION_CONTEXT_LIMIT = 64 * 1024
_FORM_VALUES_LIMIT = 64 * 1024
_ACTION_PAYLOAD_LIMIT = 256 * 1024
_FORM_FIELD_TYPES = {"text", "textarea", "number", "select", "checkbox", "date"}
_FORM_COMPONENT_KEYS = ("id", "component", "title", "fields", "submitLabel", "action")
_MISSING = object()
_COMPONENT_ACTION_KEYS = {
    "Button": ("action",),
    "Form": ("action",),
    "ApprovalCard": ("approveAction", "rejectAction"),
}

logger = logging.getLogger(__name__)


class A2UIActionValidationError(ValueError):
    """Raised when an A2UI action is not authorized by persisted surface state."""


class A2UIActionDuplicateError(A2UIActionValidationError):
    """Raised when the submission id has already been accepted."""


@dataclass(frozen=True)
class ValidatedA2UIAction:
    """An authorized action and the canonical payload exposed to the agent."""

    payload: dict[str, Any]
    component: dict[str, Any]
    reservation_keys: tuple[str, ...] = ()


def build_a2ui_action_label(
    validated_action: ValidatedA2UIAction,
    *,
    action_name: str,
    language: str,
) -> str:
    """Resolve visible action text from the authoritative source component."""
    component = validated_action.component
    component_type = component.get("component")
    label: Any = None

    if component_type == "Form":
        label = component.get("submitLabel", "Submit")
    elif component_type == "ApprovalCard":
        if action_name == _find_action_name(component.get("approveAction")):
            label = component.get("approveLabel", "Approve")
        elif action_name == _find_action_name(component.get("rejectAction")):
            label = component.get("rejectLabel", "Reject")
    elif component_type == "Button":
        label = component.get("_resolvedActionLabel")

    return sanitize_a2ui_action_label(label) or get_a2ui_action_fallback_label(language)


def _find_action_name(value: Any) -> str | None:
    if isinstance(value, dict):
        if isinstance(value.get("name"), str):
            return value["name"]
        event = value.get("event")
        if isinstance(event, dict) and isinstance(event.get("name"), str):
            return event["name"]
        for child in value.values():
            result = _find_action_name(child)
            if result:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _find_action_name(child)
            if result:
                return result
    return None


def _component_action_names(component: dict[str, Any]) -> set[str]:
    """Return only actions declared by the component's catalog schema."""
    keys = _COMPONENT_ACTION_KEYS.get(str(component.get("component")), ())
    return {
        name
        for key in keys
        if (name := _find_action_name(component.get(key))) is not None
    }


def _find_surface_component(
    conversation_history: dict[str, Any],
    surface_id: str,
    component_id: str,
) -> dict[str, Any] | None:
    records = conversation_history.get("message_records", [])
    for record in reversed(records if isinstance(records, list) else []):
        units = record.get("units") or []
        for unit in reversed(units if isinstance(units, list) else []):
            if unit.get("unit_type") != "a2ui":
                continue
            content = unit.get("unit_content")
            try:
                envelope = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError:
                continue
            if (
                not isinstance(envelope, dict)
                or envelope.get("surfaceId") != surface_id
            ):
                continue
            message = envelope.get("message")
            update = (
                message.get("updateComponents") if isinstance(message, dict) else None
            )
            components = update.get("components") if isinstance(update, dict) else None
            if not isinstance(components, list):
                continue
            for component in components:
                if isinstance(component, dict) and component.get("id") == component_id:
                    resolved_component = dict(component)
                    child_id = resolved_component.get("child")
                    if (
                        resolved_component.get("component") == "Button"
                        and isinstance(child_id, str)
                        and child_id != component_id
                    ):
                        child = _find_surface_component(
                            conversation_history,
                            surface_id,
                            child_id,
                        )
                        if child and child.get("component") == "Text":
                            resolved_component["_resolvedActionLabel"] = child.get(
                                "text"
                            )
                    return resolved_component
    return None


def _encoded_size(value: Any) -> int:
    try:
        serialized = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise A2UIActionValidationError(
            "A2UI form values must be valid JSON primitives"
        ) from exc
    return len(serialized.encode("utf-8"))


def _project_form(
    component: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fields = component.get("fields")
    if not isinstance(fields, list):
        raise A2UIActionValidationError("Persisted A2UI Form has invalid fields")

    projected_fields: list[dict[str, Any]] = []
    field_names: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            raise A2UIActionValidationError("Persisted A2UI Form has an invalid field")
        name = field.get("name")
        label = field.get("label")
        field_type = field.get("type")
        required = field.get("required", False)
        if not isinstance(name, str) or not name or name in field_names:
            raise A2UIActionValidationError(
                "Persisted A2UI Form field names must be unique strings"
            )
        if (
            not isinstance(label, str)
            or field_type not in _FORM_FIELD_TYPES
            or not isinstance(required, bool)
        ):
            raise A2UIActionValidationError(
                "Persisted A2UI Form field definition is invalid"
            )
        field_names.add(name)
        projected = {"name": name, "label": label, "type": field_type}
        if "required" in field:
            projected["required"] = required

        options = field.get("options", _MISSING)
        if options is not _MISSING:
            if not isinstance(options, list):
                raise A2UIActionValidationError(
                    "Persisted A2UI Form field options are invalid"
                )
            projected_options = []
            for option in options:
                if (
                    not isinstance(option, dict)
                    or not isinstance(option.get("label"), str)
                    or not isinstance(option.get("value"), str)
                ):
                    raise A2UIActionValidationError(
                        "Persisted A2UI Form field options are invalid"
                    )
                projected_options.append(
                    {"label": option["label"], "value": option["value"]}
                )
            projected["options"] = projected_options
        projected_fields.append(projected)

    projected_form = {
        key: component[key]
        for key in _FORM_COMPONENT_KEYS
        if key in component and key != "fields"
    }
    projected_form["fields"] = projected_fields
    return projected_form, projected_fields


def _normalize_form_values(
    values: dict[str, Any],
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    if _encoded_size(values) > _FORM_VALUES_LIMIT:
        raise A2UIActionValidationError("A2UI form values exceed 64 KiB")
    declared_names = {field["name"] for field in fields}
    if set(values) - declared_names:
        raise A2UIActionValidationError(
            "A2UI form submission contains an undeclared field"
        )

    normalized: dict[str, Any] = {}
    for field in fields:
        name = field["name"]
        field_type = field["type"]
        required = field.get("required", False)
        value = values.get(name, _MISSING)
        if value is _MISSING:
            if required:
                raise A2UIActionValidationError(
                    "A2UI form submission is missing a required field"
                )
            normalized[name] = False if field_type == "checkbox" else None
            continue

        if field_type in {"text", "textarea", "select", "date"}:
            if value is None and not required:
                normalized[name] = None
                continue
            if not isinstance(value, str):
                raise A2UIActionValidationError(
                    "A2UI form field has an invalid string value"
                )
            if required and not value.strip():
                raise A2UIActionValidationError(
                    "A2UI form submission contains an empty required field"
                )
            if not value and not required:
                normalized[name] = None
                continue
            if field_type == "select":
                allowed_values = {
                    option["value"] for option in field.get("options", [])
                }
                if value not in allowed_values:
                    raise A2UIActionValidationError(
                        "A2UI form select value is not declared by the Form"
                    )
            if field_type == "date":
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise A2UIActionValidationError(
                        "A2UI form date must use YYYY-MM-DD"
                    )
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise A2UIActionValidationError(
                        "A2UI form date must use YYYY-MM-DD"
                    ) from exc
            normalized[name] = value
            continue

        if field_type == "number":
            if value is None and not required:
                normalized[name] = None
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise A2UIActionValidationError("A2UI form number must be finite")
            normalized[name] = value
            continue

        if not isinstance(value, bool):
            raise A2UIActionValidationError("A2UI form checkbox must be boolean")
        if required and not value:
            raise A2UIActionValidationError(
                "A2UI form required checkbox must be selected"
            )
        normalized[name] = value

    return normalized


def _build_validated_payload(
    submission: A2UIActionSubmission,
    component: dict[str, Any],
) -> dict[str, Any]:
    payload = submission.model_dump(mode="json", by_alias=True, exclude_none=True)
    if component.get("component") == "Form":
        if submission.form_submission is None:
            raise A2UIActionValidationError("A2UI Form actions require formSubmission")
        projected_form, fields = _project_form(component)
        normalized_values = _normalize_form_values(
            submission.form_submission.values, fields
        )
        payload["formSubmission"] = {
            "form": projected_form,
            "values": normalized_values,
        }
    elif submission.form_submission is not None:
        raise A2UIActionValidationError(
            "formSubmission is only valid for A2UI Form actions"
        )

    try:
        payload_size = len(serialize_a2ui_action_payload(payload).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise A2UIActionValidationError(
            "A2UI action payload must contain valid JSON"
        ) from exc
    if payload_size > _ACTION_PAYLOAD_LIMIT:
        raise A2UIActionValidationError("A2UI action payload exceeds 256 KiB")
    return payload


def _history_has_form_submission(
    conversation_history: dict[str, Any],
    *,
    surface_id: str,
    component_id: str,
) -> bool:
    """Check the durable hidden action units for an accepted Form submission."""
    records = conversation_history.get("message_records", [])
    for record in records if isinstance(records, list) else []:
        units = record.get("units") or []
        for unit in units if isinstance(units, list) else []:
            if unit.get("unit_type") != "a2ui_action":
                continue
            content = unit.get("unit_content")
            try:
                payload = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError:
                continue
            state = project_a2ui_submission_state(payload)
            if (
                state is not None
                and state["surfaceId"] == surface_id
                and state["sourceComponentId"] == component_id
            ):
                return True
    return False


def _delete_redis_keys(redis_client: Any, keys: tuple[str, ...]) -> None:
    if not keys:
        return
    try:
        redis_client.delete(*keys)
    except Exception:
        logger.warning("Failed to release A2UI action reservation", exc_info=True)


def release_a2ui_action_reservation(validated_action: ValidatedA2UIAction) -> None:
    """Release Redis reservations when action persistence did not complete."""
    if not validated_action.reservation_keys:
        return
    redis_client = get_redis_client()
    if redis_client is not None:
        _delete_redis_keys(redis_client, validated_action.reservation_keys)


def validate_a2ui_action_submission(
    submission: A2UIActionSubmission,
    *,
    conversation_id: int | None,
    user_id: str,
) -> ValidatedA2UIAction:
    """Authorize an action, normalize Form values, and reserve its idempotency key."""
    if conversation_id is None:
        raise A2UIActionValidationError("A2UI actions require an existing conversation")
    history = get_conversation_history(conversation_id, user_id)
    if not history:
        raise A2UIActionValidationError("Conversation is not accessible")

    action = submission.message.action
    try:
        datetime.fromisoformat(action.timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise A2UIActionValidationError(
            "A2UI action timestamp must be ISO-8601"
        ) from exc
    if (
        len(json.dumps(action.context, ensure_ascii=False).encode("utf-8"))
        > _ACTION_CONTEXT_LIMIT
    ):
        raise A2UIActionValidationError("A2UI action context exceeds 64 KiB")

    component = _find_surface_component(
        history, action.surface_id, action.source_component_id
    )
    if component is None:
        raise A2UIActionValidationError(
            "A2UI surface or source component was not found"
        )
    if action.name not in _component_action_names(component):
        raise A2UIActionValidationError(
            "A2UI action name does not match the source component"
        )

    payload = _build_validated_payload(submission, component)

    is_form = component.get("component") == "Form"
    if is_form and _history_has_form_submission(
        history,
        surface_id=action.surface_id,
        component_id=action.source_component_id,
    ):
        raise A2UIActionDuplicateError("A2UI Form was already submitted")

    redis_client = get_redis_client()
    if redis_client is None:
        raise A2UIActionValidationError(
            "A2UI action idempotency storage is unavailable"
        )
    submission_key = (
        f"nexent:a2ui:submission:{user_id}:{conversation_id}:{submission.submission_id}"
    )
    try:
        accepted = redis_client.set(
            submission_key, "1", nx=True, ex=_ACTION_TTL_SECONDS
        )
    except Exception as exc:
        raise A2UIActionValidationError("A2UI action idempotency check failed") from exc
    if not accepted:
        raise A2UIActionDuplicateError("A2UI action was already submitted")

    reservation_keys = (submission_key,)
    if is_form:
        form_key = (
            "nexent:a2ui:form-submitted:"
            f"{user_id}:{conversation_id}:{action.surface_id}:{action.source_component_id}"
        )
        try:
            form_accepted = redis_client.set(
                form_key,
                str(submission.submission_id),
                nx=True,
                ex=_ACTION_TTL_SECONDS,
            )
        except Exception as exc:
            _delete_redis_keys(redis_client, reservation_keys)
            raise A2UIActionValidationError(
                "A2UI Form submission reservation failed"
            ) from exc
        if not form_accepted:
            _delete_redis_keys(redis_client, reservation_keys)
            raise A2UIActionDuplicateError("A2UI Form was already submitted")
        reservation_keys = (*reservation_keys, form_key)

    return ValidatedA2UIAction(
        payload=payload,
        component=component,
        reservation_keys=reservation_keys,
    )
