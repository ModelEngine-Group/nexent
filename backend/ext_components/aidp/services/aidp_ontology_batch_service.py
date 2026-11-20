# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ontology JSON import/export proxy operations."""
from __future__ import annotations

import logging
from typing import Any

from ext_components.aidp.services.aidp_ontology_common import (
    _domain_id_value,
    _get_ontology_path,
    _ontology_request,
)


logger = logging.getLogger("aidp_ontology_batch_service")


def export_ontology_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    include_properties: bool = True,
    include_relations: bool = True,
    kind: str | None = None,
    tenant_id: str | None = None,
) -> Any:
    return _ontology_request(
        server_url,
        api_key,
        "POST",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/batch/export",
        operation="export-ontology",
        json_body={
            "DOMAIN_ID": _domain_id_value(domain_id),
            "INCLUDE_PROPERTIES": bool(include_properties),
            "INCLUDE_RELATIONS": bool(include_relations),
            "KIND": kind,
        },
    )


def import_ontology_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    body: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> Any:
    return _ontology_request(
        server_url,
        api_key,
        "POST",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/batch/import",
        operation="import-ontology",
        json_body=body,
    )

