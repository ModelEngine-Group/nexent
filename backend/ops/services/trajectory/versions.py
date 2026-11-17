# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep built-in display versions separate from immutable execution snapshots."""


def _persisted_id(value):
    if type(value) is int:
        return str(value) if 0 < value <= 2147483647 else None
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 10:
        number = int(value)
        return str(number) if 0 < number <= 2147483647 else None
    return None


def apply_builtin_versions(catalog, tenants, items, *, nodes=False):
    """Decorate only authorized system Agent DTOs; source attributes stay intact."""
    selected = []
    for item in items:
        if nodes and item.get("kind") != "agent":
            continue
        agent = _persisted_id(
            item.get("_agent_id") if nodes else item.get("root_agent_id")
        )
        if agent is not None:
            selected.append((item, item.get("tenant_id", tenants[0]), agent))
    if not selected:
        return
    identities = catalog.builtin_agent_ids(tenants, {agent for _, _, agent in selected})
    prefix = "agent_" if nodes else "root_agent_"
    for item, tenant, agent in selected:
        if (tenant, agent) in identities:
            item[prefix + "version_no"] = 1
            item[prefix + "version_name"] = "V1"
