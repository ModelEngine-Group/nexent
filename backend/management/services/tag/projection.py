# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Batch display-only tags after the resource service has applied authorization."""

import logging
from collections import defaultdict
from typing import Any

from management.db.knowledge_base.repository import get_knowledge_record
from management.db.tag.repository import TagManagementDB
from management.services.tag.resources import (
    KNOWLEDGE_CONTENT_LIBRARY_CODE,
    LOCAL_DOCUMENT_PROVIDER,
    _encode_document_resource_id,
)

logger = logging.getLogger(__name__)

from contracts.constants.tag import (
    DOCUMENT_TAG_BATCH_SIZE,
    KNOWLEDGE_DOCUMENT_TYPE,
)
from contracts.constants.tag import (
    PUBLIC_DOCUMENT_ASSIGNMENT_FIELDS as _PUBLIC_ASSIGNMENT_FIELDS,
)


def project_authorized_resource_tags(
    resources: list[dict[str, Any]], *, resource_type: str, id_field: str, default_tenant_id: str,
) -> list[dict[str, Any]]:
    """Never discover resources through tags, and never query assignments per card."""
    grouped_ids: dict[str, list[str]] = defaultdict(list)
    for resource in resources:
        if resource.get(id_field) is not None:
            tenant = str(resource.get("tenant_id") or default_tenant_id)
            grouped_ids[tenant].append(str(resource[id_field]))
    by_tenant = {
        tenant: TagManagementDB.list_resource_assignment_display_values_by_ids(
            tenant, resource_type, list(dict.fromkeys(ids)),
        )
        for tenant, ids in grouped_ids.items()
    }
    return [
        {
            **resource,
            "tags": list(dict.fromkeys(
                by_tenant.get(str(resource.get("tenant_id") or default_tenant_id), {}).get(str(resource.get(id_field)), [])
            )),
        }
        for resource in resources
    ]


def _public_assignment(assignment: dict[str, Any]) -> dict[str, Any]:
    """Keep the documented display contract and drop internal tag fields."""

    return {field: assignment.get(field) for field in _PUBLIC_ASSIGNMENT_FIELDS}


def _load_document_assignments(
    *, tenant_id: str, resource_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """Read every assignment chunk with the existing batch database query."""

    assignments: dict[str, list[dict[str, Any]]] = {}
    for start in range(0, len(resource_ids), DOCUMENT_TAG_BATCH_SIZE):
        chunk = resource_ids[start:start + DOCUMENT_TAG_BATCH_SIZE]
        assignments.update(
            TagManagementDB.list_resource_assignments_batch(
                tenant_id,
                KNOWLEDGE_DOCUMENT_TYPE,
                chunk,
                KNOWLEDGE_CONTENT_LIBRARY_CODE,
            )
        )
    return assignments


def project_authorized_document_tags(
    files: list[dict[str, Any]],
    *,
    index_name: str,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """Attach display tags to files whose knowledge-base read access was proven.

    The caller must pass a file list it has already authorized. Documents keep
    the authenticated tenant boundary used by their tag assignments: a
    knowledge base readable across tenants does not expose another tenant's
    document tags. Any lookup failure degrades to empty tags so the file list
    itself is never lost.
    """

    projected = [{**file, "tags": []} for file in files]
    if not projected or not tenant_id or not index_name:
        return projected

    try:
        path_to_resource_id: dict[str, str] = {}
        for file in files:
            path = str(file.get("path_or_url") or "").strip()
            if path and path not in path_to_resource_id:
                path_to_resource_id[path] = _encode_document_resource_id(
                    LOCAL_DOCUMENT_PROVIDER, index_name, path
                )
        if not path_to_resource_id:
            return projected

        record = get_knowledge_record(
            {"index_name": index_name, "tenant_id": tenant_id}
        )
        if not record or str(record.get("tenant_id") or "") != str(tenant_id):
            return projected

        assignments = _load_document_assignments(
            tenant_id=tenant_id,
            resource_ids=list(path_to_resource_id.values()),
        )
        for projection, file in zip(projected, files):
            path = str(file.get("path_or_url") or "").strip()
            resource_id = path_to_resource_id.get(path)
            if not resource_id:
                continue
            projection["tags"] = [
                _public_assignment(assignment)
                for assignment in assignments.get(resource_id, [])
            ]
    except Exception as error:  # noqa: BLE001 - tags must never break the file list
        logger.warning(
            "Document tag projection failed for index %s: %s", index_name, error
        )
    return projected
