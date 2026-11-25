# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pure helpers converting AIDP ontology JSON export files into batch import bodies.

AIDP exports ``{<domain_name>: {types, entities, relations}}`` while its batch
import endpoint expects the flat uppercase ``DOMAIN_ID / ENTITIES / RELATIONS``
request table. This module owns the conversion and every pre-submit validation
so the HTTP layer only has to map the result to a response. It performs no I/O.
"""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger("aidp_ontology_transform")

ONTOLOGY_KIND_TYPE = "type"
ONTOLOGY_KIND_ENTITY = "entity"
_ONTOLOGY_KINDS = (ONTOLOGY_KIND_TYPE, ONTOLOGY_KIND_ENTITY)

# Fields the documented export contract emits. Anything outside this set is an
# AIDP-internal column (entity_id, record_type, versions, timestamps,
# _search_text) that the target library rebuilds, so it must not be forwarded.
_EXPORTED_ENTITY_FIELDS = (
    "api_name",
    "display_name",
    "description",
    "properties",
    "primary_properties",
    "source_info",
)
_EXPORTED_RELATION_FIELDS = (
    "api_name",
    "display_name",
    "source_api_name",
    "source_kind",
    "object_api_name",
    "object_kind",
    "source_ids",
)

MAX_SYNC_IMPORT_ITEMS = 200


class OntologyImportValidationError(ValueError):
    """Raised when an uploaded file cannot be converted into an import request."""

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        message = (
            errors[0]["message"] if errors else "Ontology import document is invalid"
        )
        super().__init__(message)


def _issue(
    index: int | None,
    object_type: str,
    api_name: Any,
    field: str,
    reason: str,
    message: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one field-level import issue.

    ``message`` is an English fallback for non-browser callers; the browser
    translates ``reason`` + ``params`` into the active locale.
    """
    return {
        "index": index,
        "type": object_type,
        "api_name": api_name if isinstance(api_name, str) else None,
        "field": field,
        "reason": reason,
        "params": params or {},
        "message": message,
    }


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _resolve_export_groups(
    document: Any, errors: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return the exported domain payloads, unwrapping the dynamic domain key.

    A single export file carries one dynamic key named after the ontology
    domain. The inner object (and the flat request body) are accepted too so a
    caller does not have to remember which wrapper it holds.
    """
    if not isinstance(document, dict):
        errors.append(_issue(None, "document", None, "$", "json_root_object", "JSON root must be an object"))
        return []

    if any(key in document for key in ("types", "entities", "relations")):
        return [document]

    groups = [
        value
        for value in document.values()
        if isinstance(value, dict)
        and any(key in value for key in ("types", "entities", "relations"))
    ]
    if not groups:
        errors.append(
            _issue(
                None,
                "document",
                None,
                "$",
                "group_missing", "No ontology group found; the key must be the ontology name and include types/entities/relations",
            )
        )
    return groups


def _project_entity(
    item: Any,
    *,
    kind: str,
    index: int,
    errors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    object_type = "type" if kind == ONTOLOGY_KIND_TYPE else "entity"
    if not isinstance(item, dict):
        errors.append(_issue(index, object_type, None, "$", "item_not_object", "Each entry must be an object"))
        return None
    api_name = _clean_text(item.get("api_name"))
    if not api_name:
        errors.append(_issue(index, object_type, None, "api_name", "api_name_required", "api_name is required"))
        return None
    declared_kind = _clean_text(item.get("kind")).lower()
    if declared_kind and declared_kind != kind:
        errors.append(
            _issue(
                index,
                object_type,
                api_name,
                "kind",
                "kind_mismatch", f"kind mismatch: group is {kind}, entry is {declared_kind}", {"kind": kind, "declared": declared_kind},
            )
        )
        return None

    projected: dict[str, Any] = {"api_name": api_name, "kind": kind}
    for field in _EXPORTED_ENTITY_FIELDS:
        if field in item:
            projected[field] = item[field]
    properties = projected.get("properties")
    if properties is not None and not isinstance(properties, list):
        errors.append(
            _issue(index, object_type, api_name, "properties", "properties_not_array", "properties must be an array")
        )
        return None
    primary = projected.get("primary_properties")
    if primary is not None and not isinstance(primary, list):
        errors.append(
            _issue(
                index,
                object_type,
                api_name,
                "primary_properties",
                "primary_properties_not_array", "primary_properties must be an array",
            )
        )
        return None
    for position, prop in enumerate(properties or []):
        if not isinstance(prop, dict) or not _clean_text(prop.get("api_name")):
            errors.append(
                _issue(
                    index,
                    object_type,
                    api_name,
                    f"properties[{position}].api_name",
                    "property_api_name_required", "Property api_name is required",
                )
            )
            return None
        # Confirmed import contract requires data_type on every property; the
        # export contract may omit it, so default to string and keep "" as the
        # only legal blank value.
        prop.setdefault("data_type", "string")
        if "value" not in prop or prop.get("value") is None:
            prop["value"] = ""
    # The import payload groups objects by array, not by kind.
    projected.pop("kind", None)
    return projected


def _resolve_relation_endpoint(
    relation: dict[str, Any],
    field: str,
    kind_field: str,
    entity_kinds: dict[str, set[str]],
    errors: list[dict[str, Any]],
    index: int,
    api_name: str,
) -> bool:
    endpoint_name = _clean_text(relation.get(field))
    if not endpoint_name:
        errors.append(_issue(index, "relation", api_name, field, "relation_field_required", f"{field} is required", {"field": field}))
        return False
    declared_kind = _clean_text(relation.get(kind_field)).lower()
    known_kinds = entity_kinds.get(endpoint_name, set())
    if declared_kind:
        if declared_kind not in _ONTOLOGY_KINDS:
            errors.append(
                _issue(
                    index,
                    "relation",
                    api_name,
                    kind_field,
                    "relation_kind_invalid", f"{kind_field} must be type or entity", {"field": kind_field},
                )
            )
            return False
        if endpoint_name not in entity_kinds:
            errors.append(
                _issue(
                    index,
                    "relation",
                    api_name,
                    field,
                    "relation_endpoint_missing", f"Relation endpoint {endpoint_name} is not part of this import", {"endpoint": endpoint_name},
                )
            )
            return False
        if declared_kind not in known_kinds:
            errors.append(
                _issue(
                    index,
                    "relation",
                    api_name,
                    kind_field,
                    "relation_kind_mismatch", f"Relation endpoint {endpoint_name} has kind {next(iter(known_kinds))}, which conflicts with {declared_kind}", {"endpoint": endpoint_name, "actual": next(iter(known_kinds)), "declared": declared_kind},
                )
            )
            return False
        return True
    if not known_kinds:
        errors.append(
            _issue(
                index,
                "relation",
                api_name,
                field,
                "relation_endpoint_kind_unknown", f"Relation endpoint {endpoint_name} is not part of this import; cannot determine kind", {"endpoint": endpoint_name},
            )
        )
        return False
    if len(known_kinds) > 1:
        errors.append(
            _issue(
                index,
                "relation",
                api_name,
                kind_field,
                "relation_kind_ambiguous", f"Relation endpoint {endpoint_name} appears as both type and entity; provide {kind_field} explicitly", {"endpoint": endpoint_name, "field": kind_field},
            )
        )
        return False
    relation[kind_field] = next(iter(known_kinds))
    return True


def _project_relation(
    item: Any,
    *,
    index: int,
    entity_kinds: dict[str, set[str]],
    errors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        errors.append(_issue(index, "relation", None, "$", "item_not_object", "Each entry must be an object"))
        return None
    api_name = _clean_text(item.get("api_name"))
    if not api_name:
        errors.append(_issue(index, "relation", None, "api_name", "api_name_required", "api_name is required"))
        return None

    projected: dict[str, Any] = {"api_name": api_name}
    for field in _EXPORTED_RELATION_FIELDS:
        if field in item:
            projected[field] = item[field]
    # AIDP auto-created is-a relations can carry an empty display_name; the
    # import validator rejects them even though the relation itself is valid.
    if not _clean_text(projected.get("display_name")):
        projected["display_name"] = api_name
    if not _resolve_relation_endpoint(
        projected,
        "source_api_name",
        "source_kind",
        entity_kinds,
        errors,
        index,
        api_name,
    ):
        return None
    if not _resolve_relation_endpoint(
        projected,
        "object_api_name",
        "object_kind",
        entity_kinds,
        errors,
        index,
        api_name,
    ):
        return None
    return projected


def build_import_request(
    document: Any, domain_name: str
) -> tuple[dict[str, Any], dict[str, int]]:
    """Convert an exported ontology document into the confirmed import body.

    The deployed service wants ``{"<target domain name>": {types, entities,
    relations}}`` with lowercase arrays, ``source_api_name``/``object_api_name``
    relation references and ``data_type`` on every property. Returns
    ``(request_body, counts)``. Raises
    :class:`OntologyImportValidationError` with field-level errors when the
    document cannot be located or a relation endpoint cannot be resolved, so
    the browser can report problems before any upstream request is made.
    """
    errors: list[dict[str, Any]] = []
    groups = _resolve_export_groups(document, errors)
    if errors:
        raise OntologyImportValidationError(errors)

    types: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    entity_kinds: dict[str, set[str]] = {}
    seen_entities: set[tuple[str, str]] = set()
    type_count = 0
    entity_count = 0

    for group in groups:
        for kind, source_key, target_list in (
            (ONTOLOGY_KIND_TYPE, "types", types),
            (ONTOLOGY_KIND_ENTITY, "entities", entities),
        ):
            raw_items = group.get(source_key) or []
            if not isinstance(raw_items, list):
                errors.append(
                    _issue(None, kind, None, source_key, "field_array_required", f"{source_key} must be an array", {"field": source_key})
                )
                continue
            for index, item in enumerate(raw_items):
                projected = _project_entity(item, kind=kind, index=index, errors=errors)
                if projected is None:
                    continue
                key = (projected["api_name"], kind)
                if key in seen_entities:
                    errors.append(
                        _issue(
                            index,
                            kind,
                            projected["api_name"],
                            "api_name",
                            "duplicate_api_name", "Duplicate (api_name, kind) in the same file",
                        )
                    )
                    continue
                seen_entities.add(key)
                entity_kinds.setdefault(projected["api_name"], set()).add(kind)
                target_list.append(projected)
                if kind == ONTOLOGY_KIND_TYPE:
                    type_count += 1
                else:
                    entity_count += 1

    for group in groups:
        raw_items = group.get("relations") or []
        if not isinstance(raw_items, list):
            errors.append(
                _issue(None, "relation", None, "relations", "field_array_required", "relations must be an array", {"field": "relations"})
            )
            continue
        for index, item in enumerate(raw_items):
            projected = _project_relation(
                item, index=index, entity_kinds=entity_kinds, errors=errors
            )
            if projected is not None:
                relations.append(projected)

    if errors:
        raise OntologyImportValidationError(errors)

    request_body = {
        domain_name: {
            "display_name": domain_name,
            "types": types,
            "entities": entities,
            "relations": relations,
        },
    }
    counts = {
        "type_count": type_count,
        "entity_count": entity_count,
        "relation_count": len(relations),
    }
    return request_body, counts


def unwrap_payload(payload: Any) -> dict[str, Any]:
    """Return the effective data object of an AIDP envelope."""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def is_async_task_payload(payload: Any) -> bool:
    """Return whether an AIDP response only acknowledges a background task."""
    data = unwrap_payload(payload)
    if not data:
        return False
    if any(
        key in data for key in ("imported_count", "failed_count", "types", "entities")
    ):
        return False
    return bool(data.get("task_id") or data.get("taskId"))


def async_task_summary(payload: Any) -> dict[str, Any]:
    data = unwrap_payload(payload)
    return {
        "accepted": True,
        "task_id": data.get("task_id") or data.get("taskId"),
        "status": data.get("status"),
    }


def _extract_error_message(item: dict[str, Any]) -> str:
    for key in (
        "message_zh",
        "message",
        "reason_zh",
        "reason",
        "message_en",
        "reason_en",
    ):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Import failed"


def _import_result_data(payload: Any) -> dict[str, Any]:
    """Return the counters object of a sync import response.

    Confirmed contract nests them under ``result``:
    ``{execution_mode, status, progress, result: {...counters...}}``.
    """
    data = unwrap_payload(payload)
    if not data:
        return {}
    nested = data.get("result")
    return nested if isinstance(nested, dict) else data


def normalize_import_errors(payload: Any) -> list[dict[str, Any]]:
    """Flatten ``first_error``/``errors[]`` into display-friendly entries.

    Numeric AIDP error codes stay in the logs; the UI only receives the
    readable message and the object locator.
    """
    data = _import_result_data(payload)
    raw_errors: list[Any] = []
    first_error = data.get("first_error")
    if isinstance(first_error, dict):
        raw_errors.append(first_error)
    bulk_errors = data.get("errors")
    if isinstance(bulk_errors, list):
        raw_errors.extend(bulk_errors)
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for item in raw_errors:
        if not isinstance(item, dict):
            continue
        key = (item.get("index"), item.get("api_name"))
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "index": item.get("index"),
                "type": item.get("type"),
                "api_name": item.get("api_name"),
                "message": _extract_error_message(item),
            }
        )
    return normalized


def normalize_import_result(payload: Any) -> dict[str, Any]:
    """Normalize a synchronous import response into per-item counters."""
    data = _import_result_data(payload)
    return {
        "accepted": False,
        "imported_count": int(data.get("imported_count") or 0),
        "skipped_count": int(data.get("skipped_count") or 0),
        "failed_count": int(data.get("failed_count") or 0),
        "relation_imported": int(data.get("relation_imported") or 0),
        "relation_failed": int(data.get("relation_failed") or 0),
        "first_error": data.get("first_error"),
        "errors": normalize_import_errors(payload),
    }


def sanitize_export_filename(name: str, fallback: str = "ontology") -> str:
    """Build a filesystem-safe download name without path separators."""
    cleaned = "".join(
        character if character.isalnum() or character in ("-", "_", ".", " ") else "_"
        for character in (name or "")
    ).strip(" ._")
    return f"{cleaned or fallback}.json"


def normalize_export_result(payload: Any) -> dict[str, Any]:
    """Return a synchronous export payload or the async acknowledgment."""
    if is_async_task_payload(payload):
        return async_task_summary(payload)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        # Some deployments answer with the grouped document at the top level.
        data = unwrap_payload(payload)
    domain_name = next(iter(data), None) if isinstance(data, dict) else None
    if not isinstance(domain_name, str):
        # A malformed upstream body is a value error for the HTTP layer, not a
        # Python type error raised by the caller.
        raise ValueError("AIDP export response does not contain a domain document")  # noqa: TRY004
    return {
        "accepted": False,
        "domain_name": domain_name,
        "data": data,
    }
