# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Freeze bounded PG results; keep list snapshots independent of metric snapshots."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from .access import authorize
from .primitives import QueryError, fingerprint


def records(
    service,
    actor,
    filters,
    *,
    view="execution",
    query_id=None,
    page=1,
    page_size=10,
    sort_by="started_at",
    sort_order="desc",
    all_items=False,
):
    if (
        view not in {"conversation", "execution"}
        or not 1 <= page_size <= 100
        or not 1 <= page <= 1_000_000
        or sort_by not in {"started_at", "duration_ms", "total_tokens"}
        or sort_order not in {"asc", "desc"}
    ):
        raise QueryError("invalid_parameters")
    tenants = authorize(service.catalog, actor, filters.get("tenant_id"))
    binding = fingerprint({"view": view, **filters})
    key = str(uuid4())
    if query_id:
        key = service.references.resolve(
            query_id, "query", actor=actor.binding, filters=binding
        )["query"]
        state = service.queries.get(key)
        if state is None:
            raise QueryError("snapshot_reset", 409)
    else:
        items = service.execution_catalog.list_records(
            tenants,
            filters,
            view=view,
            limit=service.max_candidates,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        names = service.catalog.names(tenants)
        ids = {i.get("root_agent_id") for i in items if i.get("root_agent_id")}
        agents = service.catalog.agent_names(tenants, ids)
        for item in items:
            item["tenant_name"] = names.get(item["tenant_id"])
            name = agents.get((item["tenant_id"], item.get("root_agent_id")))
            item["root_agent_name"] = (
                name if name != item.get("root_agent_id") else None
            )
        state = {
            "members": items,
            "view": view,
            "as_of": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "sort_by": sort_by,
            "sort_order": sort_order,
            "pg": True,
        }
        if not service.queries.put(
            key, state, len(json.dumps(state, ensure_ascii=False).encode()) * 4
        ):
            raise QueryError("query_membership_budget_exceeded", 503, retry_after=2)
    service.execution_catalog.validate(tenants, state["members"])
    # Sorting frozen values never consults a mutable SQL OFFSET on later pages.
    items = list(state["members"])

    def identity(item):
        return (
            item["tenant_id"],
            item["user_id"],
            int(item["conversation_id"]),
            item.get("trajectory_id") or "",
        )

    def value(item):
        return (
            (item.get("usage") or {}).get("total")
            if sort_by == "total_tokens"
            else item.get(sort_by)
        )

    items.sort(key=identity)
    known = [i for i in items if value(i) is not None]
    known.sort(key=value, reverse=sort_order == "desc")
    items = known + [i for i in items if value(i) is None]
    summary = service.execution_catalog.statistics(
        tenants, global_scope=actor.role == "SU" and not filters.get("tenant_id")
    )
    if authorize(service.catalog, actor, filters.get("tenant_id")) != tenants:
        raise QueryError("snapshot_reset", 409)
    result = {
        "query_id": service.references.issue(
            "query", {"actor": actor.binding, "filters": binding, "query": key}
        ),
        "as_of": state["as_of"],
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "summary": summary,
        "items": [
            {k: v for k, v in i.items() if not k.startswith("_")}
            for i in (
                items if all_items else items[(page - 1) * page_size : page * page_size]
            )
        ],
    }
    if len(json.dumps(result, ensure_ascii=False).encode()) > 2 * 1024 * 1024:
        raise QueryError("record_page_budget_exceeded", 503, retry_after=2)
    return result


def facets(service, actor, filters, facet, *, search="", cursor=None, limit=20):
    if (
        facet not in {"tenants", "users", "agents", "conversations", "models"}
        or not 1 <= limit <= 100
    ):
        raise QueryError("invalid_facet")
    tenants = authorize(service.catalog, actor, filters.get("tenant_id"))
    binding = {
        "actor": actor.binding,
        "facet": facet,
        "filters": fingerprint(filters),
        "search": search.strip().casefold(),
    }
    state = (
        service.references.resolve(cursor, "facet", **binding) if cursor else binding
    )
    if facet == "tenants":
        names = service.catalog.names(tenants)
        options = [{"id": i, "name": names.get(i), "tenant_id": i} for i in tenants]
        options = [
            i
            for i in options
            if not search or search.casefold() in (i["name"] or "").casefold()
        ]
        options.sort(key=lambda i: (i["tenant_id"], i["id"]))
        options = [
            i
            for i in options
            if not state.get("after")
            or (i["tenant_id"], i["id"]) > tuple(state["after"])
        ]
    elif facet == "users":
        options = service.catalog.user_page(
            tenants, binding["search"], state.get("after"), limit
        )
        names = service.catalog.names(tenants)
        for item in options:
            item["tenant_name"] = names.get(item["tenant_id"])
    else:
        options = service.execution_catalog.facets(
            tenants, filters, facet, binding["search"], state.get("after"), limit
        )
        if facet == "agents":
            names = service.catalog.agent_names(tenants, {i["id"] for i in options})
            for item in options:
                item["name"] = names.get((item["tenant_id"], item["id"]))
    authorize(service.catalog, actor, filters.get("tenant_id"))
    return {
        "items": options[:limit],
        "next_cursor": service.references.issue(
            "facet",
            {
                **binding,
                "after": [options[limit - 1]["tenant_id"], options[limit - 1]["id"]],
            },
        )
        if len(options) > limit
        else None,
    }
