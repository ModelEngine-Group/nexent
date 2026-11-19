# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Agent execution facts and daily metrics for the shared monitoring pipeline."""

from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ops.monitoring.contracts import Fact, MonitoringKind, Outcome, stable_key


RunId = Annotated[str, Field(min_length=1, max_length=128)]
DIMENSIONS = ("tenant_id", "fact_kind", "statistic_date", "group_snapshot_state", "group_key",
              "initiator_group_ids", "agent_id")
COUNTERS = ("execution_count", "duration_sum_ms", "duration_sample_count")
RESULT_COUNTERS = ("succeeded_count", "failed_count")


class AgentFact(Fact):
    fact_kind: Literal["agent"] = "agent"
    root_run_id: RunId
    agent_run_id: RunId
    agent_id: int = Field(gt=0, le=2**31 - 1)
    is_root: bool
    parent_run_id: RunId | None = None
    agent_version_no: int | None = Field(default=None, ge=0, le=2**31 - 1)
    outcome: Outcome | Literal["timed_out"]

    @model_validator(mode="after")
    def check_run_identity(self):
        if self.fact_id != self.agent_run_id:
            raise ValueError("Agent fact ID must match its run ID")
        if self.is_root:
            if self.root_run_id != self.agent_run_id or self.parent_run_id is not None:
                raise ValueError("Invalid root Agent identity")
        elif self.parent_run_id in {None, self.agent_run_id} or self.root_run_id == self.agent_run_id:
            raise ValueError("Invalid child Agent identity")
        return self


def accumulate_agent(documents: Iterable[dict]) -> Iterable[tuple[str, dict]]:
    """Count executions and sum measured durations by Agent and starting scope."""
    groups: dict[str, dict] = {}
    for fact in documents:
        dimensions = {field: fact[field] for field in DIMENSIONS}
        key = stable_key(*dimensions.values())
        if key not in groups:
            groups[key] = {**dimensions, **dict.fromkeys(COUNTERS + RESULT_COUNTERS, 0)}
        row = groups[key]
        row["execution_count"] += 1
        row["succeeded_count"] += fact["outcome"] == "succeeded"
        row["failed_count"] += fact["outcome"] in {"failed", "timed_out"}
        duration = fact.get("duration_ms")
        if fact.get("ended_at") is not None and duration is not None:
            row["duration_sum_ms"] += duration
            row["duration_sample_count"] += 1
    return groups.items()


def summarize_agent(rows: Iterable[dict]) -> dict:
    """Merge exact counts before computing duration averages and success rate."""
    totals = dict.fromkeys(COUNTERS, 0)
    results = dict.fromkeys(RESULT_COUNTERS, 0)
    for row in rows:
        for counter in totals:
            totals[counter] += row[counter]
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
        **results,
        "success_rate": results["succeeded_count"] / denominator if denominator else None,
    }


AGENT_MONITORING = MonitoringKind(
    fact_model=AgentFact,
    aggregate=accumulate_agent,
    fact_fields={"is_root": "boolean", "parent_run_id": "keyword", "agent_version_no": "integer"},
    daily_fields=dict.fromkeys(COUNTERS + RESULT_COUNTERS, "long"),
)
