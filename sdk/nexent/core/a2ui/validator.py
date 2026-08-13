"""A2UI response validation - schema and runtime semantic checks."""

from __future__ import annotations

import json
import logging
from typing import Any

from .constants import A2UI_MESSAGE_KEYS
from .parser import coerce_message_list, iter_tagged_block_bodies
from .types import A2UIValidationResult

logger = logging.getLogger(__name__)


def _validate_message_structure(messages: list[dict[str, Any]]) -> list[str]:
    """Validate basic message structure. Returns list of error messages."""
    errors: list[str] = []
    valid_orders = {
        "beginRendering",
        "surfaceUpdate",
        "dataModelUpdate",
        "deleteSurface",
    }

    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            errors.append(f"Message {i} is not a dict")
            continue
        key_count = len(A2UI_MESSAGE_KEYS.intersection(msg.keys()))
        if key_count == 0:
            errors.append(f"Message {i} has no A2UI keys. Keys: {list(msg.keys())}")
        elif key_count > 1:
            errors.append(f"Message {i} has multiple A2UI keys. Keys found: {list(A2UI_MESSAGE_KEYS.intersection(msg.keys()))}")

    return errors


def _validate_component_references(messages: list[dict[str, Any]]) -> list[str]:
    """Validate that template componentId references are valid."""
    errors: list[str] = []

    # Build a map of surfaceId -> component IDs
    surface_components: dict[str, set[str]] = {}
    for msg in messages:
        surface_update = msg.get("surfaceUpdate")
        if isinstance(surface_update, dict):
            surface_id = surface_update.get("surfaceId", "")
            components = surface_update.get("components", [])
            if isinstance(components, list):
                if surface_id not in surface_components:
                    surface_components[surface_id] = set()
                for comp in components:
                    if isinstance(comp, dict) and "id" in comp:
                        surface_components[surface_id].add(str(comp["id"]))

    # Check template references
    for msg in messages:
        surface_update = msg.get("surfaceUpdate")
        if not isinstance(surface_update, dict):
            continue
        surface_id = surface_update.get("surfaceId", "")
        components = surface_update.get("components", [])
        if not isinstance(components, list):
            continue

        valid_ids = surface_components.get(surface_id, set())
        for comp in components:
            if not isinstance(comp, dict):
                continue
            component_def = comp.get("component", {})
            if not isinstance(component_def, dict):
                continue
            _check_template_refs(component_def, valid_ids, surface_id, errors)

    return errors


def _check_template_refs(obj: Any, valid_ids: set[str], surface_id: str, errors: list[str]) -> None:
    """Recursively check template componentId references."""
    if isinstance(obj, dict):
        template = obj.get("template")
        if isinstance(template, dict):
            comp_id = template.get("componentId")
            if isinstance(comp_id, str) and comp_id not in valid_ids:
                errors.append(
                    f"Surface '{surface_id}': template references unknown componentId '{comp_id}'"
                )
        for nested in obj.values():
            _check_template_refs(nested, valid_ids, surface_id, errors)
    elif isinstance(obj, list):
        for item in obj:
            _check_template_refs(item, valid_ids, surface_id, errors)


def _validate_data_model_paths(messages: list[dict[str, Any]]) -> list[str]:
    """Validate dataModelUpdate paths don't conflict."""
    errors: list[str] = []
    seen_paths: set[str] = set()

    for msg in messages:
        data_update = msg.get("dataModelUpdate")
        if not isinstance(data_update, dict):
            continue

        path = str(data_update.get("path", "/"))
        if path in seen_paths:
            errors.append(f"Duplicate dataModelUpdate path: {path}")
        seen_paths.add(path)

        contents = data_update.get("contents", [])
        if not isinstance(contents, list):
            continue

        keys_seen: set[str] = set()
        for entry in contents:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key", ""))
            if key in keys_seen:
                errors.append(f"Duplicate key '{key}' in dataModelUpdate path '{path}'")
            keys_seen.add(key)

    return errors


def validate_a2ui_messages(messages: list[dict[str, Any]]) -> A2UIValidationResult:
    """Perform comprehensive validation of A2UI messages."""
    if not messages:
        return A2UIValidationResult(valid=False, error="A2UI message list is empty")

    all_errors: list[str] = []
    all_errors.extend(_validate_message_structure(messages))
    all_errors.extend(_validate_component_references(messages))
    all_errors.extend(_validate_data_model_paths(messages))

    if all_errors:
        return A2UIValidationResult(valid=False, error="; ".join(all_errors))

    return A2UIValidationResult(valid=True)


def validate_a2ui_response(content: str) -> A2UIValidationResult:
    """Validate a complete A2UI response string.

    Checks both tagged block format and raw JSON format.
    """
    if not content or not content.strip():
        return A2UIValidationResult(valid=True)

    # Try tagged block validation first
    tagged_blocks = iter_tagged_block_bodies(content)
    if tagged_blocks:
        for block_index, body in tagged_blocks:
            body = body.strip()
            if not body:
                continue
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                return A2UIValidationResult(
                    valid=False,
                    error=f"A2UI block {block_index}: invalid JSON ({exc.msg})",
                )
            messages = coerce_message_list(parsed)
            if messages is None:
                return A2UIValidationResult(
                    valid=False,
                    error=f"A2UI block {block_index}: expected A2UI message list",
                )
            result = validate_a2ui_messages(messages)
            if not result.valid:
                return A2UIValidationResult(
                    valid=False,
                    error=f"A2UI block {block_index}: {result.error}",
                )
        return A2UIValidationResult(valid=True)

    # Try raw JSON validation
    try:
        parsed = json.loads(content.strip())
        messages = coerce_message_list(parsed)
        if messages is not None:
            return validate_a2ui_messages(messages)
    except json.JSONDecodeError:
        pass

    # Try JSONL validation
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    if lines and all(l.startswith("{") and l.endswith("}") for l in lines):
        all_messages: list[dict[str, Any]] = []
        for line in lines:
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                return A2UIValidationResult(valid=False, error=f"Invalid JSONL line: {line[:50]}")
            msgs = coerce_message_list(parsed)
            if msgs is None:
                return A2UIValidationResult(valid=False, error=f"Invalid A2UI message in JSONL: {line[:50]}")
            all_messages.extend(msgs)
        return validate_a2ui_messages(all_messages)

    # If no A2UI content detected, it's valid text
    return A2UIValidationResult(valid=True)