# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execution parameters and ACL projection for the shared AIDP tool."""

import hmac
import json

from contracts.constants import environment

_CONNECTION_FIELDS = frozenset({"server_url", "api_key", "tenant_id"})
SCOPED_SHARED_AIDP_CATALOG_ID = "prepared_scoped_aidp_catalog_id"


def shared_aidp_parameters(params: dict) -> dict:
    configured = params.get("kds_list") or []
    if isinstance(configured, str):
        try:
            configured = json.loads(configured)
        except json.JSONDecodeError:
            configured = []
    if not isinstance(configured, list):
        configured = []
    clean = {name: value for name, value in params.items() if name not in _CONNECTION_FIELDS}
    clean["kds_list"] = [str(kds_id) for kds_id in configured]
    return clean


def scoped_shared_aidp_revision(tenant_id: str, agent_id: int, version_no: int, row: dict) -> str:
    """Pin the catalog definition independently of the signed request options."""
    if not environment.JWT_SECRET:
        raise ValueError("AgentOS signing is not configured")
    catalog = {
        name: row[name] for name in (
            "tool_id", "name", "class_name", "source", "usage", "description", "inputs", "output_type",
        )
    }
    catalog["params"] = [param for param in row["params"] or [] if param["name"] not in _CONNECTION_FIELDS]
    key = hmac.digest(environment.JWT_SECRET.encode(), b"nexent/agentos/scoped-shared-aidp/v1", "sha256")
    payload = json.dumps(
        [tenant_id, agent_id, version_no, catalog], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hmac.digest(key, payload, "sha256").hex()


def restrict_aidp_access(configured: list[str], snapshot) -> dict:
    if snapshot is None:
        return {"allowed_kds_set": [], "kds_name_to_id_map": {}}
    scope = set(configured)
    names = {**snapshot.name_to_id, **snapshot.tenant_name_to_id}
    return {
        "allowed_kds_set": sorted(scope.intersection(snapshot.accessible_id_set)),
        "kds_name_to_id_map": {name: kds_id for name, kds_id in names.items() if kds_id in scope},
    }
