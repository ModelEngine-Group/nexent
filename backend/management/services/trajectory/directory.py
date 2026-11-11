# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Administrator branch of the existing latest-Agent conversation directory."""

from infrastructure.observability.trajectory_store import business_id

from .access import authorize
from .primitives import QueryError


def directory(
    service,
    actor,
    *,
    target_user_id,
    tenant_id=None,
    category="agent_chat",
    group_key=None,
    limit=20,
    cursor=None,
    search="",
):
    if not target_user_id or category not in {"agent_chat", "workbench"} or not 1 <= limit <= 100:
        raise QueryError("invalid_directory_parameters")
    tenant_id = tenant_id or actor.tenant_id
    authorize(service.catalog, actor, tenant_id)
    if not service.catalog.user_active(tenant_id, target_user_id):
        raise QueryError("trajectory_not_found", 404)
    if group_key is not None and group_key != "other":
        if not group_key.startswith("agent:"):
            raise QueryError("invalid_group")
        business_id(group_key[6:])
    binding = {
        "actor": actor.binding,
        "tenant": tenant_id,
        "owner": target_user_id,
        "category": category,
        "group": group_key,
        "search": search.strip().casefold(),
    }
    state = service.references.resolve(cursor, "directory", **binding) if cursor else binding
    rows = service.catalog.directory_page(
        tenant_id,
        target_user_id,
        category,
        group_key,
        state.get("after", -1),
        limit,
        binding["search"],
    )
    has_more = len(rows) > limit
    agents = service.catalog.agent_names([tenant_id], {r["agent_id"] for r in rows if r["agent_id"]})
    options = {}
    checked_after = state.get("after", -1)
    budget = service.budget()
    for row in rows[:limit]:
        budget.check(nodes=1)
        key = "agent:" + row["agent_id"] if row["agent_id"] else "other"
        if group_key and key != group_key:
            continue
        if group_key:
            item = {
                "conversation_id": row["conversation_id"],
                "conversation_title": row["conversation_title"],
                "agent_id": row["agent_id"],
            }
            sort_key = int(row["conversation_id"])
            label = row["conversation_title"] or ""
        else:
            sort_key = int(row["agent_id"]) if row["agent_id"] else 0
            label = agents.get((tenant_id, row["agent_id"]), row["agent_id"] or "Other")
            item = {"group_key": key, "agent_id": row["agent_id"], "agent_name": label}
        if sort_key <= state.get("after", -1):
            continue
        # Check only bounded PG candidates. No OTLP body is scanned to fill a directory page.
        checked_after = sort_key
        try:
            service.archive.manifest(row)
        except QueryError as error:
            if error.status == 404:
                continue
            raise
        options[sort_key] = (item, row)
    selected = sorted(options)[:limit]
    for key in selected:
        service.recheck(actor, options[key][1])
        service.archive.manifest(options[key][1])
    return {
        "items": [options[key][0] for key in selected],
        "included": [],
        "pinned": [],
        "next_cursor": service.references.issue("directory", {**binding, "after": checked_after}) if has_more else None,
    }
