# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Model monitoring facts, mappings and metrics."""

from collections.abc import Iterable
from typing import Literal

from pydantic import Field

from ops.monitoring.contracts import MAX_LONG, Fact, MonitoringKind, stable_key


TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")
SAMPLE_FIELDS = {
    "duration_ms": ("duration_sum_ms", "duration_sample_count"),
    "ttft_ms": ("ttft_sum_ms", "ttft_sample_count"),
    "generation_rate": ("generation_rate_sum", "generation_rate_sample_count"),
}
DIMENSIONS = ("tenant_id", "fact_kind", "statistic_date", "group_snapshot_state", "group_key",
              "initiator_group_ids", "model_id", "model_type", "agent_id", "has_agent_run")
COUNTERS = ("request_count", "error_count", "error_eligible_count") + tuple(
    field for names in SAMPLE_FIELDS.values() for field in names
) + tuple(f"{field}_{suffix}" for field in TOKEN_FIELDS for suffix in ("sum", "known_count"))


class ModelFact(Fact):
    fact_kind: Literal["model"] = "model"
    model_id: int | None = Field(default=None, gt=0, le=2147483647)
    model_type: str = Field(min_length=1, max_length=30)
    error_category: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,50}$")
    ttft_ms: int | None = Field(default=None, ge=0, le=MAX_LONG)
    input_tokens: int | None = Field(default=None, ge=0, le=MAX_LONG)
    output_tokens: int | None = Field(default=None, ge=0, le=MAX_LONG)
    total_tokens: int | None = Field(default=None, ge=0, le=MAX_LONG)
    generation_rate: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    span_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")


def accumulate_model(documents: Iterable[dict]) -> Iterable[tuple[str, dict]]:
    """Accumulate model facts without rounding integer sums or counting absent usage."""
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
        for field in TOKEN_FIELDS:
            if fact.get(field) is not None:
                row[f"{field}_sum"] += fact[field]
                row[f"{field}_known_count"] += 1
        for field, (total, count) in SAMPLE_FIELDS.items():
            if fact.get(field) is None or (field == "duration_ms" and fact["outcome"] not in {"succeeded", "failed"}):
                continue
            row[total] += fact[field]
            row[count] += 1
    return groups.items()


def summarize(rows: Iterable[dict]) -> dict:
    total = dict.fromkeys(COUNTERS, 0)
    for row in rows:
        for key in total:
            total[key] += row[key]
    count = total["request_count"]
    result = {key: total[key] for key in ("request_count", "error_count", "error_eligible_count")}
    eligible = total["error_eligible_count"]
    result["error_rate"] = total["error_count"] / eligible if eligible else None
    for field in TOKEN_FIELDS:
        known = total[f"{field}_known_count"]
        result[field] = {
            "value": str(total[f"{field}_sum"]) if known or not count else None,
            "known_count": known, "eligible_count": count,
            "coverage_rate": known / count if count else None,
        }
    for field, (value, samples) in SAMPLE_FIELDS.items():
        result[f"avg_{field}"] = total[value] / total[samples] if total[samples] else None
    return result


MODEL_MONITORING = MonitoringKind(
    fact_model=ModelFact,
    aggregate=accumulate_model,
    fact_fields={"model_id": "integer", "model_type": "keyword", "error_category": "keyword",
                 "trace_id": "keyword", "span_id": "keyword",
                 **dict.fromkeys((*TOKEN_FIELDS, "ttft_ms"), "long"), "generation_rate": "double"},
    daily_fields={"model_id": "integer", "model_type": "keyword", "has_agent_run": "boolean",
                  **dict.fromkeys(COUNTERS, "long"), "generation_rate_sum": "double"},
)
