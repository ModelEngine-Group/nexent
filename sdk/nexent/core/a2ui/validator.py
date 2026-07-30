"""Validation boundary for server-generated A2UI v0.9 basic catalog messages."""

from __future__ import annotations

import json
import re
from typing import Any


A2UI_PROTOCOL_VERSION = "v0.9"
A2UI_CATALOG_ID = "https://a2ui.org/specification/v0_9/basic_catalog.json"
A2UI_MAX_MESSAGE_BYTES = 256 * 1024
A2UI_MAX_COMPONENTS = 200
A2UI_MAX_DEPTH = 16
A2UI_MAX_ACTION_CONTEXT_BYTES = 64 * 1024

A2UI_COMPONENTS = frozenset(
    {
        "Text",
        "Button",
        "Card",
        "Row",
        "Column",
        "Divider",
        "TextField",
        "CheckBox",
        "ChoicePicker",
        "DateTimeInput",
    }
)
_COMMON_COMPONENT_KEYS = frozenset({"id", "component", "weight"})
_COMPONENT_CONTRACTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "Text": (frozenset({"text"}), frozenset({"variant"})),
    "Button": (frozenset({"child", "action"}), frozenset({"variant"})),
    "Card": (frozenset({"child"}), frozenset()),
    "Row": (frozenset({"children"}), frozenset({"justify", "align"})),
    "Column": (frozenset({"children"}), frozenset({"justify", "align"})),
    "Divider": (frozenset(), frozenset({"axis"})),
    "TextField": (frozenset({"label"}), frozenset({"value", "variant", "validationRegexp"})),
    "CheckBox": (frozenset({"label", "value"}), frozenset()),
    "ChoicePicker": (
        frozenset({"options", "value"}),
        frozenset({"label", "variant", "displayStyle", "filterable"}),
    ),
    "DateTimeInput": (
        frozenset({"value"}),
        frozenset({"label", "enableDate", "enableTime", "min", "max"}),
    ),
}
_COMPONENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ACTION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HTML_RE = re.compile(r"<\s*/?\s*[a-z][a-z0-9-]*\b", re.I)


class A2UIValidationError(ValueError):
    """Raised when generated A2UI crosses the supported schema or safety boundary."""


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _validate_safe_value(value: Any, *, depth: int = 0) -> None:
    if depth > 32:
        raise A2UIValidationError("A2UI value nesting is too deep")
    if isinstance(value, str):
        lowered = value.strip().lower()
        if "javascript:" in lowered or _HTML_RE.search(value):
            raise A2UIValidationError("HTML and script-like content are forbidden")
        return
    if isinstance(value, dict):
        forbidden = {"style", "className", "css", "html", "dangerouslySetInnerHTML", "api", "endpoint"}
        if forbidden.intersection(value):
            raise A2UIValidationError("A2UI contains a forbidden property")
        for child in value.values():
            _validate_safe_value(child, depth=depth + 1)
        return
    if isinstance(value, list):
        for child in value:
            _validate_safe_value(child, depth=depth + 1)


def _is_binding(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"path"}
        and isinstance(value["path"], str)
        and value["path"].startswith("/")
        and len(value["path"]) <= 512
    )


def _validate_dynamic_string(value: Any, property_name: str) -> None:
    if not isinstance(value, str) and not _is_binding(value):
        raise A2UIValidationError(f"{property_name} must be a string or data binding")


def _validate_dynamic_boolean(value: Any, property_name: str) -> None:
    if not isinstance(value, bool) and not _is_binding(value):
        raise A2UIValidationError(f"{property_name} must be a boolean or data binding")


def _validate_dynamic_string_list(value: Any, property_name: str) -> None:
    if _is_binding(value):
        return
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise A2UIValidationError(f"{property_name} must be a string array or data binding")


def _validate_action(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"event"}:
        raise A2UIValidationError("Button.action must contain exactly one event")
    event = value["event"]
    if not isinstance(event, dict) or set(event) - {"name", "context"}:
        raise A2UIValidationError("Button.action.event has unsupported properties")
    name = event.get("name")
    if not isinstance(name, str) or not _ACTION_NAME_RE.fullmatch(name):
        raise A2UIValidationError("Button.action.event.name is invalid")
    context = event.get("context", {})
    if not isinstance(context, dict):
        raise A2UIValidationError("Button.action.event.context must be an object")
    if _json_size(context) > A2UI_MAX_ACTION_CONTEXT_BYTES:
        raise A2UIValidationError("Action context exceeds 64 KiB")
    for item in context.values():
        if isinstance(item, (str, int, float, bool, list)) or item is None or _is_binding(item):
            continue
        raise A2UIValidationError("Action context values must be literals or data bindings")


def _validate_component(component: dict[str, Any]) -> set[str]:
    component_type = component["component"]
    required, optional = _COMPONENT_CONTRACTS[component_type]
    missing = required - set(component)
    if missing:
        raise A2UIValidationError(
            f"{component_type} is missing required properties: {', '.join(sorted(missing))}"
        )
    unknown = set(component) - (_COMMON_COMPONENT_KEYS | required | optional)
    if unknown:
        raise A2UIValidationError(
            f"{component_type} has unsupported properties: {', '.join(sorted(unknown))}"
        )
    if "weight" in component and not isinstance(component["weight"], (int, float)):
        raise A2UIValidationError(f"{component_type}.weight must be a number")

    references: set[str] = set()
    if component_type in {"Button", "Card"}:
        child = component.get("child")
        if not isinstance(child, str) or not child:
            raise A2UIValidationError(f"{component_type}.child must be a component id")
        references.add(child)
    if component_type in {"Row", "Column"}:
        children = component.get("children")
        if not isinstance(children, list) or not all(isinstance(child, str) and child for child in children):
            raise A2UIValidationError(f"{component_type}.children must contain component ids")
        references.update(children)

    if component_type == "Text":
        _validate_dynamic_string(component["text"], "Text.text")
        if component.get("variant", "body") not in {"h1", "h2", "h3", "h4", "h5", "caption", "body"}:
            raise A2UIValidationError("Text.variant is invalid")
    elif component_type == "Button":
        _validate_action(component["action"])
        if component.get("variant", "default") not in {"default", "primary", "borderless"}:
            raise A2UIValidationError("Button.variant is invalid")
    elif component_type in {"Row", "Column"}:
        if component.get("align", "stretch") not in {"start", "center", "end", "stretch"}:
            raise A2UIValidationError(f"{component_type}.align is invalid")
        if component.get("justify", "start") not in {
            "start", "center", "end", "stretch", "spaceAround", "spaceBetween", "spaceEvenly"
        }:
            raise A2UIValidationError(f"{component_type}.justify is invalid")
    elif component_type == "Divider":
        if component.get("axis", "horizontal") not in {"horizontal", "vertical"}:
            raise A2UIValidationError("Divider.axis is invalid")
    elif component_type == "TextField":
        _validate_dynamic_string(component["label"], "TextField.label")
        if "value" in component:
            _validate_dynamic_string(component["value"], "TextField.value")
        if component.get("variant", "shortText") not in {"shortText", "longText", "number"}:
            raise A2UIValidationError("TextField.variant is invalid")
        if "validationRegexp" in component and not isinstance(component["validationRegexp"], str):
            raise A2UIValidationError("TextField.validationRegexp must be a string")
    elif component_type == "CheckBox":
        _validate_dynamic_string(component["label"], "CheckBox.label")
        _validate_dynamic_boolean(component["value"], "CheckBox.value")
    elif component_type == "ChoicePicker":
        if "label" in component:
            _validate_dynamic_string(component["label"], "ChoicePicker.label")
        options = component["options"]
        if not isinstance(options, list) or not options:
            raise A2UIValidationError("ChoicePicker.options must be a non-empty array")
        for option in options:
            if not isinstance(option, dict) or set(option) != {"label", "value"}:
                raise A2UIValidationError("ChoicePicker options require label and value")
            _validate_dynamic_string(option["label"], "ChoicePicker.options.label")
            if not isinstance(option["value"], str):
                raise A2UIValidationError("ChoicePicker.options.value must be a string")
        _validate_dynamic_string_list(component["value"], "ChoicePicker.value")
        if component.get("variant", "mutuallyExclusive") not in {"multipleSelection", "mutuallyExclusive"}:
            raise A2UIValidationError("ChoicePicker.variant is invalid")
        if component.get("displayStyle", "checkbox") not in {"checkbox", "chips"}:
            raise A2UIValidationError("ChoicePicker.displayStyle is invalid")
        if "filterable" in component and not isinstance(component["filterable"], bool):
            raise A2UIValidationError("ChoicePicker.filterable must be a boolean")
    elif component_type == "DateTimeInput":
        _validate_dynamic_string(component["value"], "DateTimeInput.value")
        if "label" in component:
            _validate_dynamic_string(component["label"], "DateTimeInput.label")
        for key in ("min", "max"):
            if key in component:
                _validate_dynamic_string(component[key], f"DateTimeInput.{key}")
        for key in ("enableDate", "enableTime"):
            if key in component and not isinstance(component[key], bool):
                raise A2UIValidationError(f"DateTimeInput.{key} must be a boolean")

    _validate_safe_value(component)
    return references


def _validate_graph(component_ids: set[str], graph: dict[str, set[str]]) -> None:
    missing = {reference for references in graph.values() for reference in references if reference not in component_ids}
    if missing:
        raise A2UIValidationError(f"Unknown component references: {', '.join(sorted(missing))}")
    if "root" not in component_ids:
        raise A2UIValidationError("A root component with id 'root' is required")

    def visit(node: str, path: set[str], depth: int) -> None:
        if depth > A2UI_MAX_DEPTH:
            raise A2UIValidationError("Component nesting exceeds depth 16")
        if node in path:
            raise A2UIValidationError("Component references contain a cycle")
        for child in graph.get(node, set()):
            visit(child, path | {node}, depth + 1)

    visit("root", set(), 1)


def validate_a2ui_messages(raw_messages: Any, *, surface_id: str) -> list[dict[str, Any]]:
    """Normalize model output and validate the supported v0.9 basic catalog subset."""
    if isinstance(raw_messages, dict) and "messages" in raw_messages:
        raw_messages = raw_messages["messages"]
    if not isinstance(raw_messages, list) or not raw_messages:
        raise A2UIValidationError("Generator output must be a non-empty messages array")
    if not _COMPONENT_ID_RE.fullmatch(surface_id):
        raise A2UIValidationError("Invalid server-generated surface id")

    normalized: list[dict[str, Any]] = [
        {
            "version": A2UI_PROTOCOL_VERSION,
            "createSurface": {"surfaceId": surface_id, "catalogId": A2UI_CATALOG_ID},
        }
    ]
    components: dict[str, dict[str, Any]] = {}
    graph: dict[str, set[str]] = {}

    for raw in raw_messages:
        if not isinstance(raw, dict):
            raise A2UIValidationError("Each A2UI message must be an object")
        allowed_keys = {"version", "updateComponents", "updateDataModel"}
        if set(raw) - allowed_keys:
            raise A2UIValidationError("A2UI message contains an unsupported operation")
        if "version" in raw and raw["version"] != A2UI_PROTOCOL_VERSION:
            raise A2UIValidationError("A2UI message version must be v0.9")
        operations = [key for key in ("updateComponents", "updateDataModel") if key in raw]
        if len(operations) != 1:
            raise A2UIValidationError("Each message must contain exactly one update operation")

        if operations[0] == "updateComponents":
            update = raw["updateComponents"]
            if not isinstance(update, dict) or set(update) != {"components"}:
                raise A2UIValidationError("updateComponents must contain only components")
            message_components = update["components"]
            if not isinstance(message_components, list) or not message_components:
                raise A2UIValidationError("updateComponents.components must be a non-empty array")
            for component in message_components:
                if not isinstance(component, dict):
                    raise A2UIValidationError("Components must be objects")
                component_id = component.get("id")
                component_type = component.get("component")
                if not isinstance(component_id, str) or not _COMPONENT_ID_RE.fullmatch(component_id):
                    raise A2UIValidationError("Every component requires a safe id")
                if component_id in components:
                    raise A2UIValidationError("Component ids must be unique")
                if component_type not in A2UI_COMPONENTS:
                    raise A2UIValidationError(f"Component is outside the supported basic catalog: {component_type}")
                components[component_id] = component
                graph[component_id] = _validate_component(component)
            normalized.append(
                {
                    "version": A2UI_PROTOCOL_VERSION,
                    "updateComponents": {"surfaceId": surface_id, "components": message_components},
                }
            )
        else:
            update = raw["updateDataModel"]
            if not isinstance(update, dict) or set(update) - {"path", "value"}:
                raise A2UIValidationError("updateDataModel has unsupported properties")
            path = update.get("path", "/")
            if not isinstance(path, str) or not path.startswith("/") or len(path) > 512:
                raise A2UIValidationError("updateDataModel.path must be a JSON Pointer path")
            if "value" not in update:
                raise A2UIValidationError("updateDataModel.value is required for generated forms")
            _validate_safe_value(update["value"])
            normalized.append(
                {
                    "version": A2UI_PROTOCOL_VERSION,
                    "updateDataModel": {
                        "surfaceId": surface_id,
                        "path": path,
                        "value": update["value"],
                    },
                }
            )

    if len(components) > A2UI_MAX_COMPONENTS:
        raise A2UIValidationError("Surface exceeds 200 components")
    _validate_graph(set(components), graph)
    for message in normalized:
        if _json_size(message) > A2UI_MAX_MESSAGE_BYTES:
            raise A2UIValidationError("A2UI message exceeds 256 KiB")
    return normalized
