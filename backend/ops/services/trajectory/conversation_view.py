# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Project a conversation without letting historical matches replace its latest state."""

from .primitives import QueryError


def frozen_runs(meta, candidate, previous):
    """Keep query membership, including unpublished executions, fixed until refresh."""
    if not previous:
        return sorted((meta or {}).get("runs", []), key=lambda run: run["turn_no"])
    current = {run["trajectory_id"]: run for run in (meta or {}).get("runs", [])}
    result = []
    for saved in candidate["frozen_runs"]:
        run = current.get(saved["trajectory_id"])
        if run is None:
            raise QueryError("snapshot_reset", 409)
        # Publication after this query must not silently turn a placeholder into a readable run.
        result.append(run if saved.get("publication_no") is not None else saved)
    return result


def sum_usage(items):
    usages = [item.get("usage") for item in items]
    if not any(usages):
        return None
    known = {
        key: sum(
            (
                usage.get(key)
                if usage.get(key) is not None
                else usage.get("known", {}).get(key, 0)
            )
            or 0
            for usage in usages
            if usage
        )
        for key in ("input", "output", "total")
    }
    complete = all(usage and usage.get("complete", True) for usage in usages)
    return {
        **{
            key: sum(usage[key] for usage in usages)
            if all(usage and usage.get(key) is not None for usage in usages)
            else None
            for key in known
        },
        "complete": complete,
        "known": known,
    }


def project(
    service,
    actor,
    row,
    meta,
    runs,
    filters,
    budget,
    row_factory,
    matches,
    *,
    latest_uncaptured=False,
    latest_execution=None,
    execution_count=None,
):
    executions, matching, ttfts, durations, read_ids = [], [], [], [], []
    execution_filters = {
        key: value for key, value in filters.items() if key != "status"
    }
    for run in runs:
        budget.check(nodes=1)
        availability = service.archive.available(run)
        nodes, root, coverage = [], None, {"complete": False, "reasons": [availability]}
        if availability in {"available", "partial"}:
            nodes, root, coverage = service.load(
                actor, row, run["trajectory_id"], budget
            )
            read_ids.append(run["trajectory_id"])
        item = row_factory(service, row, meta, run, nodes, root, coverage)
        executions.append(item)
        if matches(item, nodes, execution_filters):
            matching.append(run["trajectory_id"])
            if coverage["complete"] and item["duration_ms"] is not None:
                durations.append(item["duration_ms"])
            ttfts.extend(
                node["ttft_ms"]
                for node in nodes
                if node["kind"] == "model"
                and node.get("ttft_ms") is not None
                and (not filters.get("model") or node.get("model") == filters["model"])
            )
    latest = (
        dict(executions[-1])
        if executions
        else row_factory(service, row, meta, None, [], None, service.coverage(meta))
    )
    if latest_execution and (
        not runs or latest_execution["turn_no"] > runs[-1]["turn_no"]
    ):
        latest = row_factory(
            service,
            row,
            meta,
            latest_execution,
            [],
            None,
            {
                "complete": False,
                "reasons": [service.archive.available(latest_execution)],
            },
        )
        # A pruned tombstone cannot serve as a verifiable execution identity.
        latest["trajectory_id"] = None
    if (
        not latest_execution
        and runs
        and execution_count is not None
        and execution_count > runs[-1]["turn_no"]
    ):
        latest.update(
            availability="unknown",
            trajectory_id=None,
            status=None,
            business_status=None,
            root_agent_id=None,
            root_agent_name=None,
            root_agent_version_no=None,
            root_agent_version_name=None,
            started_at=None,
            finished_at=None,
        )
    if latest_uncaptured:
        latest.update(
            trajectory_id=None,
            availability="not_captured",
            business_status=None,
            status=None,
            started_at=None,
            finished_at=None,
            root_agent_id=None,
            root_agent_name=None,
            root_agent_version_no=None,
            root_agent_version_name=None,
        )
    if latest["availability"] not in {"available", "partial"}:
        latest["status"] = None
    state = latest["status"] or latest["availability"]
    if filters.get("status") and filters["status"] != state:
        return None, [], [], [], read_ids
    # Missing archives only match predicates proven by their retained metadata.
    if not matching and not matches(latest, [], execution_filters):
        return None, [], [], [], read_ids
    reasons = list(service.coverage(meta).get("reasons", []))
    for execution in executions:
        reasons.extend(execution["coverage"].get("reasons", []))
        if not execution["coverage"]["complete"] and not execution["coverage"].get(
            "reasons"
        ):
            reasons.append("partial")
    if (
        latest_uncaptured
        or not executions
        or latest["availability"] not in {"available", "partial"}
    ):
        reasons.append(latest["availability"])
    known_durations = [
        item["duration_ms"] for item in executions if item["duration_ms"] is not None
    ]
    latest.update(
        models=sorted(
            {model for execution in executions for model in execution["models"]}
        ),
        duration_ms=sum(known_durations) if known_durations else None,
        usage=sum_usage(executions),
        round_count=execution_count if execution_count is not None else len(runs),
        execution_count=execution_count if execution_count is not None else len(runs),
        matching_execution_count=len(matching),
        cleanup_reason=(
            (latest_execution or (runs[-1] if runs else {})).get("cleanup_reason")
            or "retention"
        )
        if state == "expired"
        else None,
        coverage={
            "complete": not reasons,
            "reasons": list(dict.fromkeys(reasons)),
            "scope": "conversation",
        },
    )
    return latest, durations, ttfts, matching, read_ids
