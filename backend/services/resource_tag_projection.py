"""Batch display-only tags after the resource service has applied authorization."""

from collections import defaultdict
from typing import Any

from database.tag_management_db import TagManagementDB


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
