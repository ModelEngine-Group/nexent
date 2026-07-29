"""Strict validation boundary for server-generated A2UI v0.9 messages."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse


A2UI_PROTOCOL_VERSION = "v0.9"
A2UI_CATALOG_ID = "nexent.v1"
A2UI_MAX_MESSAGE_BYTES = 256 * 1024
A2UI_MAX_COMPONENTS = 200
A2UI_MAX_DEPTH = 16
A2UI_MAX_ACTION_CONTEXT_BYTES = 64 * 1024
A2UI_MAX_TABLE_ROWS = 500
A2UI_MAX_CHART_POINTS = 1000

A2UI_COMPONENTS = frozenset(
    {
        "Text",
        "Image",
        "Icon",
        "Button",
        "Card",
        "Row",
        "Column",
        "Divider",
        "DataTable",
        "Chart",
        "Form",
        "ApprovalCard",
        "ArtifactCard",
    }
)
_COMMON_COMPONENT_KEYS = frozenset({"id", "component", "accessibility", "weight"})
_COMPONENT_CONTRACTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "Text": (frozenset({"text"}), frozenset({"variant"})),
    "Image": (frozenset({"url"}), frozenset({"description", "fit", "variant"})),
    "Icon": (frozenset({"name"}), frozenset()),
    "Button": (frozenset({"child", "action"}), frozenset({"variant", "checks"})),
    "Card": (frozenset({"child"}), frozenset()),
    "Row": (frozenset({"children"}), frozenset({"justify", "align"})),
    "Column": (frozenset({"children"}), frozenset({"justify", "align"})),
    "Divider": (frozenset(), frozenset({"axis"})),
    "DataTable": (frozenset({"columns", "rows"}), frozenset({"caption"})),
    "Chart": (frozenset({"chartType", "data", "valueKey"}), frozenset({"xKey", "title"})),
    "Form": (frozenset({"fields", "action"}), frozenset({"title", "submitLabel"})),
    "ApprovalCard": (
        frozenset({"title", "approveAction", "rejectAction"}),
        frozenset({"description", "approveLabel", "rejectLabel"}),
    ),
    "ArtifactCard": (frozenset({"title", "url"}), frozenset({"description"})),
}
_COMPONENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HTML_RE = re.compile(r"<\s*/?\s*(?:script|style|iframe|object|embed|html|body|svg|[a-z][a-z0-9-]*)\b", re.I)
_REFERENCE_KEYS = frozenset({"child", "children", "trigger", "content", "entryPointChild"})


class A2UIValidationError(ValueError):
    """Raised when generated A2UI crosses the supported schema or safety boundary."""


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _walk(value: Any) -> Iterable[tuple[str | None, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield None, child
            yield from _walk(child)


def _validate_strings_and_urls(value: Any, allowed_url_hosts: set[str]) -> None:
    for key, child in _walk(value):
        if not isinstance(child, str):
            continue
        lowered = child.strip().lower()
        if "javascript:" in lowered or _HTML_RE.search(child):
            raise A2UIValidationError("HTML, script markup, and javascript URLs are forbidden")
        if key not in {"url", "href", "downloadUrl", "previewUrl"}:
            continue
        if child.startswith("/") and not child.startswith("//") and "\\" not in child:
            continue
        parsed = urlparse(child)
        if parsed.scheme != "https" or not parsed.hostname:
            raise A2UIValidationError("URLs must be same-origin paths or HTTPS URLs")
        if parsed.hostname not in allowed_url_hosts:
            raise A2UIValidationError(f"URL host is not trusted: {parsed.hostname}")


def _collect_references(component: dict[str, Any]) -> set[str]:
    references: set[str] = set()
    for key, value in component.items():
        if key in _REFERENCE_KEYS:
            if isinstance(value, str):
                references.add(value)
            elif isinstance(value, list):
                references.update(item for item in value if isinstance(item, str))
            elif isinstance(value, dict):
                for candidate_key in ("id", "componentId", "child"):
                    candidate = value.get(candidate_key)
                    if isinstance(candidate, str):
                        references.add(candidate)
        if key == "tabs" and isinstance(value, list):
            for tab in value:
                if isinstance(tab, dict) and isinstance(tab.get("child"), str):
                    references.add(tab["child"])
    return references


def _validate_action(value: Any, component_type: str, property_name: str) -> None:
    if not isinstance(value, dict) or set(value) != {"event"}:
        raise A2UIValidationError(f"{component_type}.{property_name} must contain exactly one event")
    event = value.get("event")
    if not isinstance(event, dict):
        raise A2UIValidationError(f"{component_type}.{property_name}.event must be an object")
    unknown = set(event) - {"name", "context"}
    if unknown:
        raise A2UIValidationError(
            f"{component_type}.{property_name}.event has unsupported properties: {', '.join(sorted(unknown))}"
        )
    if not isinstance(event.get("name"), str) or not event["name"].strip():
        raise A2UIValidationError(f"{component_type}.{property_name}.event.name must be a string")
    if "context" in event and not isinstance(event["context"], dict):
        raise A2UIValidationError(f"{component_type}.{property_name}.event.context must be an object")


def _validate_child_list(value: Any, component_type: str) -> None:
    if not isinstance(value, list) or not all(isinstance(child, str) and child for child in value):
        raise A2UIValidationError(f"{component_type}.children must contain component ids")


def _validate_component_contract(component: dict[str, Any]) -> None:
    component_type = str(component["component"])
    required, optional = _COMPONENT_CONTRACTS[component_type]
    missing = required - set(component)
    if missing:
        raise A2UIValidationError(f"{component_type} is missing required properties: {', '.join(sorted(missing))}")
    unknown = set(component) - (_COMMON_COMPONENT_KEYS | required | optional)
    if unknown:
        raise A2UIValidationError(f"{component_type} has unsupported properties: {', '.join(sorted(unknown))}")

    if component_type in {"Card", "Button"}:
        child = component.get("child")
        if not isinstance(child, str) or not child:
            raise A2UIValidationError(f"{component_type}.child must be a component id")
    if component_type in {"Row", "Column"}:
        _validate_child_list(component.get("children"), component_type)
    if component_type == "Button":
        _validate_action(component.get("action"), component_type, "action")
    elif component_type == "Form":
        _validate_action(component.get("action"), component_type, "action")
    elif component_type == "ApprovalCard":
        _validate_action(component.get("approveAction"), component_type, "approveAction")
        _validate_action(component.get("rejectAction"), component_type, "rejectAction")

    string_properties = {
        "DataTable": ("caption",),
        "Chart": ("valueKey", "xKey", "title"),
        "Form": ("title", "submitLabel"),
        "ApprovalCard": ("title", "description", "approveLabel", "rejectLabel"),
        "ArtifactCard": ("title", "description", "url"),
    }.get(component_type, ())
    for property_name in string_properties:
        if property_name in component and not isinstance(component[property_name], str):
            raise A2UIValidationError(f"{component_type}.{property_name} must be a string")

    if component_type == "DataTable":
        columns = component.get("columns")
        rows = component.get("rows")
        if not isinstance(columns, list) or not all(
            isinstance(column, dict)
            and set(column) == {"key", "label"}
            and isinstance(column.get("key"), str)
            and isinstance(column.get("label"), str)
            for column in columns
        ):
            raise A2UIValidationError("DataTable.columns must contain key/label objects")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise A2UIValidationError("DataTable.rows must contain objects")
    elif component_type == "Chart" and not isinstance(component.get("data"), list):
        raise A2UIValidationError("Chart.data must be an array")
    elif component_type == "Form":
        fields = component.get("fields")
        if not isinstance(fields, list):
            raise A2UIValidationError("Form fields must be an array")
        allowed_field_keys = {"name", "label", "type", "required", "options"}
        for field in fields:
            if not isinstance(field, dict):
                raise A2UIValidationError("Form fields must be objects")
            unknown_field_keys = set(field) - allowed_field_keys
            if unknown_field_keys:
                raise A2UIValidationError(
                    f"Form field has unsupported properties: {', '.join(sorted(unknown_field_keys))}"
                )
            if not isinstance(field.get("name"), str) or not isinstance(field.get("label"), str):
                raise A2UIValidationError("Form fields require string name and label")
            if "required" in field and not isinstance(field["required"], bool):
                raise A2UIValidationError("Form field required must be boolean")
            if "options" in field:
                options = field["options"]
                if not isinstance(options, list) or not all(
                    isinstance(option, dict)
                    and set(option) == {"label", "value"}
                    and isinstance(option.get("label"), str)
                    and isinstance(option.get("value"), str)
                    for option in options
                ):
                    raise A2UIValidationError("Form field options must contain label/value objects")


def _validate_component_limits(component: dict[str, Any]) -> None:
    component_type = component["component"]
    if component_type == "DataTable":
        rows = component.get("rows", component.get("data", []))
        if isinstance(rows, list) and len(rows) > A2UI_MAX_TABLE_ROWS:
            raise A2UIValidationError("DataTable exceeds the 500 row limit")
    if component_type == "Chart":
        data = component.get("data", [])
        point_count = len(data) if isinstance(data, list) else 0
        if point_count > A2UI_MAX_CHART_POINTS:
            raise A2UIValidationError("Chart exceeds the 1000 point limit")
        if component.get("chartType") not in {"line", "bar", "pie"}:
            raise A2UIValidationError("Chart chartType must be line, bar, or pie")
    if component_type == "Form":
        fields = component.get("fields", [])
        allowed = {"text", "textarea", "number", "select", "checkbox", "date"}
        if not isinstance(fields, list):
            raise A2UIValidationError("Form fields must be an array")
        for field in fields:
            if not isinstance(field, dict) or field.get("type") not in allowed:
                raise A2UIValidationError("Form contains an unsupported field type")

    for key, value in _walk(component):
        if key == "context" and isinstance(value, dict):
            if _json_size(value) > A2UI_MAX_ACTION_CONTEXT_BYTES:
                raise A2UIValidationError("Action context exceeds 64 KiB")
        if key in {"style", "className", "css", "html", "dangerouslySetInnerHTML", "api", "endpoint"}:
            raise A2UIValidationError(f"Forbidden component property: {key}")


def _validate_graph(component_ids: set[str], graph: dict[str, set[str]]) -> None:
    missing = {ref for refs in graph.values() for ref in refs if ref not in component_ids}
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


def validate_a2ui_messages(
    raw_messages: Any,
    *,
    surface_id: str,
    create_surface: bool = True,
    allowed_url_hosts: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Normalize model output and validate the v0.9 schema, catalog, references, and limits."""
    if isinstance(raw_messages, dict) and "messages" in raw_messages:
        raw_messages = raw_messages["messages"]
    if not isinstance(raw_messages, list):
        raise A2UIValidationError("Generator output must be a messages array")
    if not _COMPONENT_ID_RE.fullmatch(surface_id):
        raise A2UIValidationError("Invalid server-generated surface id")

    normalized: list[dict[str, Any]] = []
    components: dict[str, dict[str, Any]] = {}
    graph: dict[str, set[str]] = {}
    trusted_hosts = {host.lower() for host in allowed_url_hosts if host}

    if create_surface:
        normalized.append(
            {
                "version": A2UI_PROTOCOL_VERSION,
                "createSurface": {"surfaceId": surface_id, "catalogId": A2UI_CATALOG_ID},
            }
        )

    for raw in raw_messages:
        if not isinstance(raw, dict):
            raise A2UIValidationError("Each A2UI message must be an object")
        if "version" in raw and raw["version"] != A2UI_PROTOCOL_VERSION:
            raise A2UIValidationError("A2UI message version must be v0.9")
        update_components = raw.get("updateComponents")
        update_data = raw.get("updateDataModel")
        if update_components is not None:
            if not isinstance(update_components, dict) or not isinstance(update_components.get("components"), list):
                raise A2UIValidationError("updateComponents.components must be an array")
            message_components = update_components["components"]
            message_component_ids: set[str] = set()
            for component in message_components:
                if not isinstance(component, dict):
                    raise A2UIValidationError("Components must be objects")
                component_id = component.get("id")
                component_type = component.get("component")
                if not isinstance(component_id, str) or not _COMPONENT_ID_RE.fullmatch(component_id):
                    raise A2UIValidationError("Every component requires a safe id")
                if component_id in message_component_ids:
                    raise A2UIValidationError("Component ids must be unique")
                message_component_ids.add(component_id)
                if component_type not in A2UI_COMPONENTS:
                    raise A2UIValidationError(f"Component is outside nexent.v1: {component_type}")
                components[component_id] = component
                graph[component_id] = _collect_references(component)
                _validate_component_limits(component)
                _validate_component_contract(component)
                _validate_strings_and_urls(component, trusted_hosts)
            normalized.append(
                {
                    "version": A2UI_PROTOCOL_VERSION,
                    "updateComponents": {"surfaceId": surface_id, "components": message_components},
                }
            )
        elif update_data is not None:
            if not isinstance(update_data, dict):
                raise A2UIValidationError("updateDataModel must be an object")
            message = {
                "version": A2UI_PROTOCOL_VERSION,
                "updateDataModel": {
                    "surfaceId": surface_id,
                    "path": update_data.get("path", "/"),
                    "value": update_data.get("value"),
                },
            }
            _validate_strings_and_urls(message, trusted_hosts)
            normalized.append(message)
        elif "createSurface" in raw:
            continue
        else:
            raise A2UIValidationError(
                "Each messages item must wrap components in updateComponents or provide updateDataModel"
            )

    if len(components) > A2UI_MAX_COMPONENTS:
        raise A2UIValidationError("Surface exceeds 200 components")
    _validate_graph(set(components), graph)
    for message in normalized:
        if _json_size(message) > A2UI_MAX_MESSAGE_BYTES:
            raise A2UIValidationError("A2UI message exceeds 256 KiB")
    return normalized
