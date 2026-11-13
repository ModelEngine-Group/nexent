# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Stable execution membership, exact whole-result metrics and authorized facets."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from infrastructure.observability.trajectory_store import parse_time

from .access import authorize
from .conversation_view import frozen_runs, project
from .primitives import QueryError, fingerprint, percentiles


def _run_matches(run, filters):
    """Apply authoritative manifest predicates before opening OTLP bodies."""
    if filters.get("agent_id") and run["root_agent_id"] != filters["agent_id"]:
        return False
    business = run["business_status"]
    status = (
        "success"
        if business == "completed"
        else ("error" if business in {"failed", "cancelled", "interrupted"} else None)
    )
    if filters.get("status") and status != filters["status"]:
        return False
    started = parse_time(run["started_at"]) if run.get("started_at") else None
    if filters.get("started_from") and (
        started is None or started < parse_time(filters["started_from"])
    ):
        return False
    return not (
        filters.get("started_to")
        and (started is None or started > parse_time(filters["started_to"]))
    )


def _matches(item, nodes, filters):
    if filters.get("agent_id") and item["root_agent_id"] != filters["agent_id"]:
        return False
    if filters.get("model") and filters["model"] not in item["models"]:
        return False
    if filters.get("status") and item["status"] != filters["status"]:
        return False
    for key, predicate in [
        ("started_from", lambda a, b: a >= b),
        ("started_to", lambda a, b: a <= b),
    ]:
        if filters.get(key) and (
            not item["started_at"]
            or not predicate(parse_time(item["started_at"]), parse_time(filters[key]))
        ):
            return False
    query = filters.get("id_query", "").strip().casefold()
    return (
        not query
        or query in item["conversation_id"].casefold()
        or any(query in n["display_trace_id"].casefold() for n in nodes)
    )


def _row(service, row, meta, run, nodes, root, coverage, *, publication=None):
    root_node = next((node for node in nodes if node["id"] == root), {})
    business = run["business_status"] if run else None
    return {
        **{
            k: row[k]
            for k in (
                "tenant_id",
                "user_id",
                "user_name",
                "conversation_id",
                "conversation_title",
            )
        },
        "tenant_name": row.get("tenant_name", row["tenant_id"]),
        "trajectory_id": run["trajectory_id"] if run else None,
        "root_agent_id": run["root_agent_id"] if run else None,
        "root_agent_name": root_node.get("name", (run or {}).get("root_agent_name")),
        "root_agent_version_no": root_node.get(
            "agent_version_no", (run or {}).get("root_agent_version_no")
        ),
        "root_agent_version_name": root_node.get(
            "agent_version_name", (run or {}).get("root_agent_version_name")
        ),
        "models": sorted({node["model"] for node in nodes if node["model"]}),
        "status": "success"
        if business == "completed"
        else ("error" if business in {"failed", "cancelled", "interrupted"} else None),
        "business_status": business,
        "availability": service.archive.available(run)
        if run
        else service.conversation_availability(meta, publication),
        "started_at": run["started_at"] if run else None,
        "finished_at": run["finished_at"] if run else None,
        "duration_ms": root_node.get("duration_ms"),
        "usage": root_node.get("usage"),
        "coverage": coverage,
    }


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
    if service.execution_catalog is not None:
        from .pg_collection import records as pg_records
        return pg_records(service, actor, filters, view=view, query_id=query_id, page=page, page_size=page_size,
                          sort_by=sort_by, sort_order=sort_order, all_items=all_items)
    if (
        view not in {"execution", "conversation"}
        or (
            view == "execution" and filters.get("status") in {"not_captured", "expired"}
        )
        or not 1 <= page_size <= 100
        or page < 1
        or page > 1_000_000
        or sort_by not in {"started_at", "duration_ms", "total_tokens"}
        or sort_order not in {"asc", "desc"}
    ):
        raise QueryError("invalid_parameters")
    tenants = authorize(service.catalog, actor, filters.get("tenant_id"))
    budget, filter_hash = service.budget(), fingerprint({"view": view, **filters})
    previous, query_key = None, str(uuid4())
    if query_id:
        token = service.references.resolve(
            query_id, "query", actor=actor.binding, filters=filter_hash
        )
        query_key = token["query"]
        previous = service.queries.get(query_key)
        if previous is None:
            raise QueryError("snapshot_reset", 409)
        candidates, as_of = previous["members"], previous["as_of"]
    else:
        candidates = service.catalog.candidates(
            tenants,
            target_user_id=filters.get("target_user_id"),
            conversation_id=filters.get("conversation_id"),
            limit=service.max_candidates,
        )
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    names = service.catalog.names(tenants)
    result, ttfts, durations, members = [], [], [], []
    validations, read_ids, conversation_durations = [], set(), []
    for candidate in candidates:
        budget.check(nodes=1)
        if candidate["tenant_id"] not in tenants:
            continue
        try:
            row = service.catalog.resolve(
                [candidate["tenant_id"]],
                candidate["conversation_id"],
                target_user_id=candidate["user_id"],
            )
        except QueryError as error:
            if error.status == 404:
                continue
            raise
        row["tenant_name"] = names.get(row["tenant_id"], row["tenant_id"])
        try:
            meta = service.archive.manifest(row)
        except QueryError as error:
            if error.status == 404:
                continue
            raise
        if previous and (meta or {}).get("cleanup_version", 0) != candidate["cleanup"]:
            raise QueryError("snapshot_reset", 409)
        upper = (
            candidate["publication"]
            if previous
            else (meta or {}).get("publication_no", 0)
        )
        if view == "conversation":
            runs = frozen_runs(meta, candidate, previous)
            uncaptured = (
                candidate["latest_uncaptured"]
                if previous
                else (
                    (meta or {}).get("source_coverage_verified") is True
                    and (meta or {}).get("latest_source_captured") is False
                )
            )
            item, samples, model_samples, matching, loaded = project(
                service,
                actor,
                row,
                meta,
                runs,
                filters,
                budget,
                _row,
                _matches,
                latest_uncaptured=uncaptured,
                latest_execution=candidate.get("latest_execution")
                if previous
                else (meta or {}).get("latest_execution"),
                execution_count=candidate.get("execution_count")
                if previous
                else (meta or {}).get("next_turn_no", len(runs) + 1) - 1,
            )
            read_ids.update(loaded)
            if item is not None:
                result.append(item)
                durations.extend(samples)
                ttfts.extend(model_samples)
                if samples:
                    conversation_durations.append(sum(samples))
            members.append(
                {
                    **row,
                    "publication": upper,
                    "cleanup": (meta or {}).get("cleanup_version", 0),
                    "runs": [run["trajectory_id"] for run in runs],
                    "frozen_runs": [dict(run) for run in runs],
                    "latest_uncaptured": uncaptured,
                    "matching_runs": matching,
                    "execution_count": candidate.get("execution_count")
                    if previous
                    else (meta or {}).get("next_turn_no", len(runs) + 1) - 1,
                    "latest_execution": candidate.get("latest_execution")
                    if previous
                    else (meta or {}).get("latest_execution"),
                }
            )
            validations.append((row, (meta or {}).get("cleanup_version", 0)))
            continue
        selected_ids = candidate["runs"] if previous else None
        run_members, visible = [], 0
        for run in (meta or {}).get("runs", []):
            budget.check(nodes=1)
            if run.get("publication_no") is None or run["publication_no"] > upper:
                continue
            if selected_ids is not None and run["trajectory_id"] not in selected_ids:
                continue
            run_members.append(run["trajectory_id"])
            if not _run_matches(run, filters):
                continue
            availability = service.archive.available(run)
            if availability == "expired":
                continue
            nodes, root, coverage = (
                [],
                None,
                {"complete": False, "reasons": [availability]},
            )
            if availability in {"available", "partial"}:
                nodes, root, coverage = service.load(
                    actor, row, run["trajectory_id"], budget
                )
            item = _row(service, row, meta, run, nodes, root, coverage)
            if _matches(item, nodes, filters):
                result.append(item)
                visible += 1
                if coverage["complete"] and item["duration_ms"] is not None:
                    durations.append(item["duration_ms"])
                for node in nodes:
                    if (
                        node["kind"] == "model"
                        and node["ttft_ms"] is not None
                        and (
                            not filters.get("model")
                            or node["model"] == filters["model"]
                        )
                    ):
                        ttfts.append(node["ttft_ms"])
        if not visible and not any(
            service.archive.available(run) != "expired"
            for run in (meta or {}).get("runs", [])
            if run.get("publication_no") and run["publication_no"] <= upper
        ):
            placeholder = _row(
                service,
                row,
                meta,
                None,
                [],
                None,
                service.coverage(meta),
                publication=upper,
            )
            placeholder["coverage"] = {
                **placeholder["coverage"],
                "complete": False,
                "reasons": list(
                    dict.fromkeys(
                        [
                            *placeholder["coverage"]["reasons"],
                            placeholder["availability"],
                        ]
                    )
                ),
            }
            if _matches(placeholder, [], filters):
                result.append(placeholder)
        members.append(
            {
                **row,
                "publication": upper,
                "cleanup": (meta or {}).get("cleanup_version", 0),
                "runs": run_members,
            }
        )
        validations.append((row, (meta or {}).get("cleanup_version", 0)))
    # Revalidate every owner and expiry before emitting a previously assembled aggregate.
    now = service.archive.store.clock()
    result_ids = (
        read_ids
        if view == "conversation"
        else {item["trajectory_id"] for item in result if item["trajectory_id"]}
    )
    for row, cleanup in validations:
        service.recheck(actor, row)
        meta = service.archive.manifest(row)
        if (meta or {}).get("cleanup_version", 0) != cleanup:
            raise QueryError("snapshot_reset", 409)
        for run in (meta or {}).get("runs", []):
            if (
                run.get("expires_at")
                and parse_time(run["expires_at"]) <= now
                and run["trajectory_id"] in result_ids
            ):
                raise QueryError("snapshot_reset", 409)
        budget.check()

    agent_ids = {str(item["root_agent_id"]) for item in result if item["root_agent_id"]}
    agent_names = service.catalog.agent_names(tenants, agent_ids)
    if not isinstance(agent_names, dict):
        agent_names = {}
    for item in result:
        if item["root_agent_id"]:
            agent_id = str(item["root_agent_id"])
            display_name = agent_names.get((item["tenant_id"], agent_id))
            item["root_agent_name"] = (
                display_name if display_name and display_name != agent_id else None
            )

    def stable(item):
        return (
            item["tenant_id"],
            item["user_id"],
            int(item["conversation_id"]),
            item["trajectory_id"] or "",
        )

    def value(item):
        return (
            (item.get("usage") or {}).get("total")
            if sort_by == "total_tokens"
            else (
                parse_time(item[sort_by])
                if sort_by == "started_at" and item[sort_by] is not None
                else item[sort_by]
            )
        )

    result.sort(key=stable)
    known, unknown = (
        [r for r in result if value(r) is not None],
        [r for r in result if value(r) is None],
    )
    known.sort(key=value, reverse=sort_order == "desc")
    result = known + unknown
    if not previous:
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        cached = {"members": members, "as_of": as_of, "view": view}
        if not service.queries.put(
            query_key, cached, len(json.dumps(cached).encode()) * 4
        ):
            raise QueryError("query_membership_budget_exceeded", 503, retry_after=2)
    summary = {
        "conversation_count": len(
            {(r["tenant_id"], r["user_id"], r["conversation_id"]) for r in result}
        ),
        "duration": {
            **percentiles(durations),
            "mean_ms": sum(durations) / len(durations) if durations else None,
        },
        "conversation_duration": percentiles(conversation_durations),
        "ttft": percentiles(ttfts),
        "complete": True,
        "coverage": {
            "complete": all(r["coverage"]["complete"] for r in result),
            "execution_count": sum(
                r.get("matching_execution_count", bool(r["trajectory_id"]))
                for r in result
            ),
            "scanned_bytes": budget.used_bytes,
            "scanned_nodes": budget.used_nodes,
        },
    }
    response = {
        "query_id": service.references.issue(
            "query",
            {"actor": actor.binding, "filters": filter_hash, "query": query_key},
        ),
        "as_of": as_of,
        "items": result
        if all_items
        else result[(page - 1) * page_size : page * page_size],
        "total": len(result),
        "page": page,
        "page_size": page_size,
        "summary": summary,
    }
    if (
        not all_items
        and len(json.dumps(response, ensure_ascii=False).encode()) > 2 * 1024 * 1024
    ):
        raise QueryError("record_page_budget_exceeded", 503, retry_after=2)
    return response


def facets(service, actor, filters, facet, *, search="", cursor=None, limit=20):
    if service.execution_catalog is not None:
        from .pg_collection import facets as pg_facets
        return pg_facets(service, actor, filters, facet, search=search, cursor=cursor, limit=limit)
    if (
        facet not in {"tenants", "users", "agents", "conversations", "models"}
        or not 1 <= limit <= 100
    ):
        raise QueryError("invalid_facet")
    tenants = authorize(service.catalog, actor, filters.get("tenant_id"))
    validations = []
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
        options = [
            {"id": tenant, "name": names.get(tenant, tenant), "tenant_id": tenant}
            for tenant in tenants
        ]
    elif facet == "users":
        options = service.catalog.user_page(
            tenants, binding["search"], state.get("after"), limit
        )
        names = service.catalog.names(tenants)
        for option in options:
            option["tenant_name"] = names.get(option["tenant_id"], option["tenant_id"])
    elif facet in {"agents", "conversations"}:
        options = []
        budget = service.budget()
        candidates = service.catalog.candidates(
            tenants,
            target_user_id=filters.get("target_user_id"),
            limit=service.max_candidates,
        )
        for row in candidates:
            budget.check(nodes=1)
            try:
                meta = service.archive.manifest(row)
            except QueryError as error:
                if error.status == 404:
                    continue
                raise
            validations.append(row)
            runs = [
                run for run in (meta or {}).get("runs", []) if run.get("root_agent_id")
            ]
            ids = {run["root_agent_id"] for run in runs}
            if facet == "conversations":
                if filters.get("agent_id") and filters["agent_id"] not in ids:
                    continue
                options.append(
                    {
                        "id": row["conversation_id"],
                        "name": row["conversation_title"],
                        "tenant_id": row["tenant_id"],
                        "user_id": row["user_id"],
                    }
                )
            else:
                for agent in ids:
                    options.append(
                        {
                            "id": agent,
                            "name": agent,
                            "tenant_id": row["tenant_id"],
                            "user_id": row["user_id"],
                        }
                    )
        if facet == "agents":
            names = service.catalog.agent_names(
                tenants, {option["id"] for option in options}
            )
            for option in options:
                option["name"] = names.get(
                    (option["tenant_id"], option["id"]), option["id"]
                )
    else:
        scope = {k: v for k, v in filters.items() if k == "tenant_id"}
        rows = records(service, actor, scope, page_size=100, all_items=True)["items"]
        options = [
            {"id": model, "name": model, "tenant_id": row["tenant_id"]}
            for row in rows
            for model in row["models"]
        ]
    unique = {(o["tenant_id"], o["id"]): o for o in options}
    options = sorted(
        (
            o
            for o in unique.values()
            if not binding["search"]
            or binding["search"] in str(o["name"]).casefold()
            or binding["search"] in o["id"].casefold()
        ),
        key=lambda o: (o["tenant_id"], o["id"]),
    )
    after = state.get("after")
    options = [
        option
        for option in options
        if not after or (option["tenant_id"], option["id"]) > tuple(after)
    ]
    # A revoked owner must not leak a title or historical Agent through a facet.
    for row in validations:
        budget.check()
        service.recheck(actor, row)
        service.archive.manifest(row)
    if facet == "users":
        options = [
            option
            for option in options
            if service.catalog.user_active(option["tenant_id"], option["id"])
        ]
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
