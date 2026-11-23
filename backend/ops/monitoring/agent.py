# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Agent execution facts and daily metrics for the shared monitoring pipeline."""

from collections.abc import Iterable

from infrastructure.monitoring.contracts import stable_key
from infrastructure.monitoring.facts import AgentFact
from ops.monitoring.contracts import MonitoringKind


DIMENSIONS = ("tenant_id", "fact_kind", "statistic_date", "group_snapshot_state", "group_key",
              "initiator_group_ids", "agent_id")
COUNTERS = ("execution_count", "duration_sum_ms", "duration_sample_count")
RESULT_COUNTERS = ("succeeded_count", "failed_count")
TTFT_COUNTERS = ("ttft_sum_ms", "ttft_sample_count")


def accumulate_agent(documents: Iterable[dict]) -> Iterable[tuple[str, dict]]:
    """Count executions and sum measured durations by Agent and starting scope."""
    groups: dict[str, dict] = {}
    for fact in documents:
        dimensions = {field: fact[field] for field in DIMENSIONS}
        key = stable_key(*dimensions.values())
        if key not in groups:
            groups[key] = {**dimensions, **dict.fromkeys(COUNTERS + RESULT_COUNTERS + TTFT_COUNTERS, 0)}
        row = groups[key]
        row["execution_count"] += 1
        row["succeeded_count"] += fact["outcome"] == "succeeded"
        row["failed_count"] += fact["outcome"] in {"failed", "timed_out"}
        if fact.get("ttft_ms") is not None:
            row["ttft_sum_ms"] += fact["ttft_ms"]
            row["ttft_sample_count"] += 1
        duration = fact.get("duration_ms")
        if fact.get("ended_at") is not None and duration is not None:
            row["duration_sum_ms"] += duration
            row["duration_sample_count"] += 1
    return groups.items()


def summarize_agent(rows: Iterable[dict]) -> dict:
    """Merge exact counts before computing duration averages and success rate."""
    totals = dict.fromkeys(COUNTERS, 0)
    results = dict.fromkeys(RESULT_COUNTERS, 0)
    ttft_sum = ttft_samples = 0
    for row in rows:
        for counter in totals:
            totals[counter] += row[counter]
        if all(row.get(field) is not None for field in TTFT_COUNTERS):
            ttft_sum += row["ttft_sum_ms"]
            ttft_samples += row["ttft_sample_count"]
        for counter in results:
            if row.get(counter) is None:
                results[counter] = None
            elif results[counter] is not None:
                results[counter] += row[counter]
    samples = totals["duration_sample_count"]
    denominator = sum(results.values()) if all(value is not None for value in results.values()) else None
    return {
        "execution_count": totals["execution_count"],
        "avg_duration_ms": totals["duration_sum_ms"] / samples if samples else None,
        "duration_sample_count": samples,
        "avg_ttft_ms": ttft_sum / ttft_samples if ttft_samples else None,
        "ttft_sample_count": ttft_samples,
        **results,
        "success_rate": results["succeeded_count"] / denominator if denominator else None,
    }


AGENT_MONITORING = MonitoringKind(
    fact_model=AgentFact,
    aggregate=accumulate_agent,
    fact_fields={"is_root": "boolean", "parent_run_id": "keyword", "agent_version_no": "integer", "ttft_ms": "long",
                 "execution_started_at": "date"},
    daily_fields=dict.fromkeys(COUNTERS + RESULT_COUNTERS + TTFT_COUNTERS, "long"),
)
