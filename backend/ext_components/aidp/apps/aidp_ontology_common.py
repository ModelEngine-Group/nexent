# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


"""Projection, enrichment and binding helpers shared by ontology routes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from nexent.core.concurrency import run_blocking

from contracts.constants.constants import CAN_EDIT_ALL_USER_ROLES
from contracts.errors.exceptions import AppException
from contracts.roles import has_any_role
from ext_components.aidp.apps.aidp_mgmt_common import _credentials
from ext_components.aidp.database import aidp_permission_db
from ext_components.aidp.services import aidp_permission_service as perms
from ext_components.aidp.services.aidp_ontology_binding_service import (
    list_ontology_bindings_impl,
)
from ext_components.aidp.services.aidp_ontology_domain_service import (
    create_ontology_relation_impl,
    delete_ontology_relation_impl,
    get_ontology_entity_impl,
    list_ontology_domains_impl,
    list_ontology_relations_impl,
)
from ext_components.aidp.services.aidp_ontology_metadata_service import (
    list_ontology_metadata_fields_impl,
)
from ext_components.aidp.services.aidp_service import get_aidp_kb_impl
from management.db.identity.user_tenant import get_user_role_by_tenant


logger = logging.getLogger("aidp_ontology_app")


async def _load_bindings(
    user_id: str,
    tenant_id: str,
    *,
    domain_id: str | None = None,
    readable_only: bool = True,
) -> list[dict[str, Any]]:
    """Load binding rows and drop KBs the caller cannot read.

    The ontology page is shared by management roles and KB owners; filtering
    keeps names and identifiers of other tenants' knowledge bases out of the
    response without changing the upstream count used for the domain owner.
    """
    server_url, api_key = _credentials()
    rows = await run_blocking(
        "aidp-ontology-bindings",
        list_ontology_bindings_impl,
        server_url,
        api_key,
        domain_id=domain_id,
        lane="control-io",
        owner="config",
    )
    role = get_user_role_by_tenant(user_id, tenant_id)
    # Ontology managers see every binding so the tab agrees with the trusted
    # binding count. Other callers only see knowledge bases they can read.
    if readable_only and rows and not has_any_role(role, CAN_EDIT_ALL_USER_ROLES):
        allowed = await run_blocking(
            "aidp-ontology-binding-access",
            perms.filter_accessible_kds,
            [row["kds_id"] for row in rows],
            user_id,
            tenant_id,
            lane="control-io",
            owner="config",
        )
        allowed_set = set(allowed)
        rows = [row for row in rows if row["kds_id"] in allowed_set]
    return rows


def _enrich_bindings_sync(
    rows: list[dict[str, Any]],
    tenant_id: str,
    domain_names: dict[str, str],
    server_url: str,
    api_key: str,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        record = (
            aidp_permission_db.get_permission_by_kb_id(row["kds_id"], tenant_id) or {}
        )
        kds_name = record.get("kds_name")
        if not kds_name:
            # A binding can outlive the local permission row (for example a
            # KB created outside Nexent). Read its display name from AIDP so
            # the management view does not degrade to bare identifiers.
            try:
                detail = get_aidp_kb_impl(server_url, api_key, row["kds_id"]) or {}
                kds_name = detail.get("kds_name") or detail.get("name")
            except Exception as error:  # noqa: BLE001 - name lookup is best effort
                logger.debug(
                    "AIDP binding KB name unavailable for %s: %s",
                    row["kds_id"],
                    error,
                )
        enriched.append(
            {
                "binding_id": row.get("binding_id"),
                "od_id": row["od_id"],
                "od_name": domain_names.get(row["od_id"]),
                "kds_id": row["kds_id"],
                "kds_name": kds_name,
                "create_time": row.get("create_time"),
            }
        )
    return enriched


async def _binding_count(domain_id: str) -> int | None:
    """Return the trusted binding count, or ``None`` when it cannot be read."""
    server_url, api_key = _credentials()
    try:
        rows = await run_blocking(
            "aidp-ontology-binding-count",
            list_ontology_bindings_impl,
            server_url,
            api_key,
            domain_id=domain_id,
            lane="control-io",
            owner="config",
        )
        return len(rows)
    except AppException as error:
        logger.warning(
            "AIDP binding count unavailable for domain %s: %s", domain_id, error
        )
        return None


async def _domain_names(tenant_id: str) -> dict[str, str]:
    server_url, api_key = _credentials()
    try:
        envelope = await run_blocking(
            "aidp-ontology-domain-names",
            list_ontology_domains_impl,
            server_url,
            api_key,
            page=1,
            page_size=100,
            lane="control-io",
            owner="config",
        )
    except AppException as error:
        logger.warning("AIDP ontology domain names unavailable: %s", error)
        return {}
    names: dict[str, str] = {}
    for item in envelope.get("value", []):
        domain_id = item.get("od_id") or item.get("domain_id") or item.get("id")
        name = item.get("name") or item.get("display_name") or item.get("od_name")
        if domain_id is not None and isinstance(name, str):
            names[str(domain_id)] = name
    return names


def _optional_count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _domain_summary(item: dict[str, Any], binding_count: int | None) -> dict[str, Any]:
    """Map the AIDP list row without inventing fields it does not return.

    The deployed list contract currently exposes only the domain id, name and
    description. Metadata/entity counts and audit fields are optional
    extensions; when absent they stay null so the browser can render "—".
    """
    domain_id = item.get("od_id") or item.get("domain_id") or item.get("id")
    return {
        "domain_id": str(domain_id) if domain_id is not None else None,
        "name": item.get("name") or item.get("display_name") or item.get("od_name"),
        "description": item.get("description") or "",
        "bound_kb_count": binding_count,
        "metadata_count": _optional_count(item.get("metadata_count")),
        "entity_count": _optional_count(item.get("entity_count")),
        "rule_count": _optional_count(item.get("rule_count")),
        "created_by": item.get("created_by")
        or item.get("creator_name")
        or item.get("create_user"),
        "create_time": item.get("create_time") or item.get("created_at"),
        "update_time": item.get("update_time") or item.get("updated_at"),
    }


def _entity_summary(
    item: dict[str, Any],
    binding_count: int | None,
    *,
    entity_id: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    resolved_id = item.get("entity_id") or item.get("id") or item.get("type_id")
    raw_kind = item.get("kind") or kind
    return {
        "entity_id": str(resolved_id if resolved_id is not None else entity_id)
        if (resolved_id is not None or entity_id is not None)
        else None,
        # PATCH answers `name` for the updated api_name; create answers api_name.
        "api_name": item.get("api_name") or item.get("name"),
        "display_name": item.get("display_name"),
        "description": item.get("description") or "",
        "kind": (raw_kind or "").lower() or None,
        "type_id": item.get("type_id"),
        "properties": item.get("properties") or [],
        "primary_properties": item.get("primary_properties") or [],
        "detail_loaded": item.get("detail_loaded")
        if isinstance(item.get("detail_loaded"), bool)
        else None,
        "parent_entities": item.get("parent_entities") or [],
        "synonym_entities": item.get("synonym_entities") or [],
        "child_entities": item.get("child_entities") or item.get("children") or [],
        "chunk_count": item.get("chunk_count")
        if isinstance(item.get("chunk_count"), int)
        else None,
        "extended_properties": item.get("extended_properties") or [],
        "create_time": item.get("create_time") or item.get("createTime"),
        "update_time": item.get("update_time") or item.get("updateTime"),
        "bound_kb_count": binding_count,
    }


def _relation_maps(
    relations: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    """Map is-a relations into parent/children endpoints keyed by entity id.

    Confirmed semantics: subject_entity is the child, object_entity the parent.
    """
    parents: dict[str, list[dict[str, Any]]] = {}
    children: dict[str, list[dict[str, Any]]] = {}
    for relation in relations:
        if str(relation.get("api_name") or "").lower() not in ("is-a", "is_a"):
            continue
        subject = relation.get("subject_entity") or {}
        obj = relation.get("object_entity") or {}
        child_id = subject.get("entity_id")
        parent_id = obj.get("entity_id")
        if child_id:
            parents.setdefault(str(child_id), []).append(obj)
        if parent_id:
            children.setdefault(str(parent_id), []).append(subject)
    return parents, children


def _synonym_values(item: dict[str, Any]) -> list[str]:
    """Extract synonym values from the entity's `synonym` property list."""
    values: list[str] = []
    for prop in item.get("properties") or []:
        if not isinstance(prop, dict):
            continue
        if prop.get("api_name") != "synonym":
            continue
        raw = prop.get("value")
        if isinstance(raw, str) and raw.strip():
            values.extend(
                part.strip()
                for part in raw.replace("，", "、").split("、")
                if part.strip()
            )
    return values


async def _list_all_relations(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Page through all Relations; AIDP rejects size > 100."""
    rows: list[dict[str, Any]] = []
    page = 1
    while page <= 100:
        envelope = await run_blocking(
            "aidp-ontology-entity-relations",
            list_ontology_relations_impl,
            server_url,
            api_key,
            domain_id,
            page=page,
            size=page_size,
            lane="control-io",
            owner="config",
        )
        values = envelope.get("value") or []
        rows.extend(item for item in values if isinstance(item, dict))
        if not envelope.get("has_more") or len(values) < page_size:
            break
        page += 1
    return rows


async def _enrich_entity_rows(
    server_url: str,
    api_key: str,
    domain_id: str,
    rows: list[dict[str, Any]],
    kind: str | None,
    *,
    detail_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Attach relations and the detail fields the list does not carry.

    The entity list omits relations, properties and audit fields, so each row
    needs one detail call for synonyms and properties. The detail endpoint also
    needs its relations enriched, so a single-row detail caller can pass its
    already-fetched detail through ``detail_by_id`` to avoid a duplicate call.
    """
    if not rows:
        return rows
    try:
        relation_rows = await _list_all_relations(
            server_url, api_key, domain_id, page_size=100
        )
    except AppException as error:
        logger.warning("AIDP relations unavailable for domain %s: %s", domain_id, error)
        relation_rows = []
    parents, children = _relation_maps(relation_rows)
    semaphore = asyncio.Semaphore(5)

    async def load_detail(row: dict[str, Any]) -> dict[str, Any] | None:
        entity_id = row.get("entity_id") or row.get("id")
        if entity_id is None:
            return None
        override = (detail_by_id or {}).get(str(entity_id))
        if override is not None:
            return override
        async with semaphore:
            try:
                detail = await run_blocking(
                    "aidp-ontology-entity-detail",
                    get_ontology_entity_impl,
                    server_url,
                    api_key,
                    domain_id,
                    str(entity_id),
                    lane="control-io",
                    owner="config",
                )
            except AppException:
                return None
        # A business error may still be a dict; only accept a real entity row.
        if not isinstance(detail, dict) or not (
            detail.get("api_name") is not None or "properties" in detail
        ):
            return None
        return detail

    details = await asyncio.gather(*(load_detail(row) for row in rows))
    enriched: list[dict[str, Any]] = []
    for row, detail in zip(rows, details):
        entity_id = row.get("entity_id") or row.get("id")
        row = dict(row)
        row["parent_entities"] = parents.get(str(entity_id), [])
        row["child_entities"] = children.get(str(entity_id), [])
        row["detail_loaded"] = detail is not None and isinstance(
            detail.get("properties"), list
        )
        if detail is None:
            row["synonym_entities"] = []
        else:
            if isinstance(detail.get("properties"), list):
                row["properties"] = detail["properties"]
            for field in (
                "primary_properties",
                "update_time",
                "type_id",
                "create_time",
            ):
                if detail.get(field) is not None:
                    row[field] = detail[field]
            row["synonym_entities"] = [
                {"api_name": value, "display_name": value}
                for value in _synonym_values(detail)
            ]
        enriched.append(row)
    return enriched


async def _reconcile_entity_relations(
    server_url: str,
    api_key: str,
    domain_id: str,
    entity_id: str,
    kind: str,
    *,
    parent_ids: list[str] | None,
    child_ids: list[str] | None,
) -> None:
    """Make this entity's is-a relations match the requested endpoint ids.

    AIDP's entity PATCH does not accept parent/child fields, so an edit that
    changes them has to diff Relations and create/delete rows explicitly.
    """
    if parent_ids is None and child_ids is None:
        return
    relations = await _list_all_relations(server_url, api_key, domain_id, page_size=100)
    current_parents: dict[str, dict[str, Any]] = {}
    current_children: dict[str, dict[str, Any]] = {}
    for relation in relations:
        if str(relation.get("api_name") or "").lower() not in ("is-a", "is_a"):
            continue
        subject = relation.get("subject_entity") or {}
        obj = relation.get("object_entity") or {}
        if str(subject.get("entity_id")) == str(entity_id):
            current_parents[str(obj.get("entity_id"))] = relation
        if str(obj.get("entity_id")) == str(entity_id):
            current_children[str(subject.get("entity_id"))] = relation

    async def create_link(
        subject_id: str, subject_kind: str, object_id: str, object_kind: str
    ) -> None:
        await run_blocking(
            "aidp-ontology-relation-create",
            create_ontology_relation_impl,
            server_url,
            api_key,
            domain_id,
            {
                "api_name": "is-a",
                "display_name": f"{subject_id}_{object_id}",
                "source_kind": subject_kind,
                "source_id": int(subject_id),
                "object_kind": object_kind,
                "object_id": int(object_id),
            },
            lane="control-io",
            owner="config",
        )

    async def remove_link(relation: dict[str, Any]) -> None:
        relation_id = relation.get("relation_id")
        if relation_id is None:
            return
        await run_blocking(
            "aidp-ontology-relation-delete",
            delete_ontology_relation_impl,
            server_url,
            api_key,
            domain_id,
            str(relation_id),
            lane="control-io",
            owner="config",
        )

    if parent_ids is not None:
        desired = {str(item) for item in parent_ids if str(item)}
        for stale_id, relation in current_parents.items():
            if stale_id not in desired:
                await remove_link(relation)
        for parent_id in desired - set(current_parents):
            await create_link(str(entity_id), kind, parent_id, "entity")
    if child_ids is not None:
        desired = {str(item) for item in child_ids if str(item)}
        for stale_id, relation in current_children.items():
            if stale_id not in desired:
                await remove_link(relation)
        for child_id in desired - set(current_children):
            await create_link(child_id, "entity", str(entity_id), kind)


def _rule_summary(item: dict[str, Any]) -> dict[str, Any]:
    rule_id = item.get("rule_id") or item.get("id")
    return {
        "rule_id": str(rule_id) if rule_id is not None else None,
        "name": item.get("name"),
        "description": item.get("description") or "",
        "enabled": bool(item.get("enabled", True)),
        "condition": item.get("condition"),
        "action": item.get("action"),
        # Confirmed rule contract uses created_time/updated_time; the other
        # spellings stay as fallbacks for older builds.
        "created_at": item.get("created_time")
        or item.get("created_at")
        or item.get("create_time"),
        "updated_at": item.get("updated_time")
        or item.get("updated_at")
        or item.get("update_time"),
    }


def _find_metadata_field(
    fields: list[dict[str, Any]], field_ref: str
) -> dict[str, Any] | None:
    for item in fields:
        if str(item.get("id")) == str(field_ref):
            return item
        if item.get("field_name") == field_ref:
            return item
    return None


async def _load_metadata_fields(domain_id: str) -> list[dict[str, Any]]:
    server_url, api_key = _credentials()
    envelope = await run_blocking(
        "aidp-ontology-metadata-list",
        list_ontology_metadata_fields_impl,
        server_url,
        api_key,
        domain_id,
        page=1,
        page_size=100,
        lane="control-io",
        owner="config",
    )
    return envelope["value"]
