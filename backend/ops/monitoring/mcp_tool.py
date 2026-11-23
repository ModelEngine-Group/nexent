# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""MCP tool call monitoring mappings and metrics (OPS-MCP-TOOL-MONITORING-20261118)."""

from collections.abc import Iterable

from infrastructure.monitoring.contracts import stable_key
from infrastructure.monitoring.facts import McpToolFact
from ops.monitoring.contracts import MonitoringKind


DIMENSIONS = ("tenant_id", "fact_kind", "statistic_date", "group_snapshot_state", "group_key",
              "initiator_group_ids", "mcp_server_id", "mcp_server_name", "mcp_server_type",
              "tool_name", "agent_id", "has_agent_run")
COUNTERS = ("request_count", "error_count", "error_eligible_count",
            "duration_ms_sum", "duration_ms_sample_count")


def accumulate_mcp_tool(documents: Iterable[dict]) -> Iterable[tuple[str, dict]]:
    """Accumulate MCP tool facts per (tenant, server identity, tool, agent, group) dimension.

    Counting semantics follow the model kind (design D-005): one stored document
    counts one request; a crash leaving only the ``started`` revision still
    counts the attempt but neither an error nor a duration sample; cancelled
    calls never contribute duration.
    """
    groups: dict[str, dict] = {}
    for fact in documents:
        dimensions = {field: fact.get(field) for field in DIMENSIONS if field in fact}
        dimensions["has_agent_run"] = bool(fact.get("agent_run_id"))
        key = stable_key(*(dimensions.get(field) for field in DIMENSIONS))
        if key not in groups:
            groups[key] = {**dimensions, **dict.fromkeys(COUNTERS, 0)}
        row = groups[key]
        row["request_count"] += 1
        row["error_count"] += fact["outcome"] == "failed"
        row["error_eligible_count"] += fact["outcome"] in {"succeeded", "failed"}
        if fact.get("duration_ms") is not None and fact["outcome"] in {"succeeded", "failed"}:
            row["duration_ms_sum"] += fact["duration_ms"]
            row["duration_ms_sample_count"] += 1
    return groups.items()


def summarize(rows: Iterable[dict]) -> dict:
    total = dict.fromkeys(COUNTERS, 0)
    for row in rows:
        for key in total:
            total[key] += row[key]
    eligible = total["error_eligible_count"]
    return {
        "request_count": total["request_count"],
        "error_count": total["error_count"],
        "error_eligible_count": eligible,
        "error_rate": total["error_count"] / eligible if eligible else None,
        "avg_duration_ms": (total["duration_ms_sum"] / total["duration_ms_sample_count"]
                            if total["duration_ms_sample_count"] else None),
    }


MCP_TOOL_MONITORING = MonitoringKind(
    fact_model=McpToolFact,
    aggregate=accumulate_mcp_tool,
    fact_fields={"tool_name": "keyword", "mcp_server_id": "integer", "mcp_server_name": "keyword",
                 "mcp_server_type": "keyword", "error_category": "keyword",
                 "trace_id": "keyword", "span_id": "keyword"},
    daily_fields={"mcp_server_id": "integer", "mcp_server_name": "keyword",
                  "mcp_server_type": "keyword", "tool_name": "keyword", "has_agent_run": "boolean",
                  **dict.fromkeys(COUNTERS, "long")},
)
