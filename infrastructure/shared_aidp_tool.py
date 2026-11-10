# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execution parameters and ACL projection for the shared AIDP tool."""

import json


def shared_aidp_parameters(params: dict) -> dict:
    configured = params.get("kds_list") or []
    if isinstance(configured, str):
        try:
            configured = json.loads(configured)
        except json.JSONDecodeError:
            configured = []
    if not isinstance(configured, list):
        configured = []
    clean = {name: value for name, value in params.items() if name not in {"server_url", "api_key", "tenant_id"}}
    clean["kds_list"] = [str(kds_id) for kds_id in configured]
    return clean


def restrict_aidp_access(configured: list[str], snapshot) -> dict:
    if snapshot is None:
        return {"allowed_kds_set": [], "kds_name_to_id_map": {}}
    scope = set(configured)
    names = {**snapshot.name_to_id, **snapshot.tenant_name_to_id}
    return {
        "allowed_kds_set": sorted(scope.intersection(snapshot.accessible_id_set)),
        "kds_name_to_id_map": {name: kds_id for name, kds_id in names.items() if kds_id in scope},
    }
