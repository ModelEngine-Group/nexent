"""Deterministic aggregation of immutable physical provider-call usage records."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from .provider_usage import ProviderCallUsage


_SUM_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "fresh_input_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "visible_output_tokens",
)
_CONTEXT_PURPOSES = frozenset({"main_agent", "final_answer"})


def aggregate_turn_usage(
    records: Iterable[ProviderCallUsage],
    *,
    context_limit_tokens: Optional[int] = None,
) -> dict[str, Any]:
    """Aggregate once by call ID; incomplete field coverage stays null."""
    unique: dict[str, ProviderCallUsage] = {}
    for record in records:
        existing = unique.get(record.call_id)
        if existing is None or _status_rank(record.status) >= _status_rank(existing.status):
            unique[record.call_id] = record
    calls = list(unique.values())

    sums: dict[str, Optional[int]] = {}
    known_counts: dict[str, int] = {}
    for field_name in _SUM_FIELDS:
        values = [getattr(record.usage, field_name) for record in calls]
        known = [value for value in values if value is not None]
        known_counts[field_name] = len(known)
        sums[field_name] = sum(known) if len(known) == len(values) and values else None

    context_calls = [
        record
        for record in calls
        if record.purpose in _CONTEXT_PURPOSES
        and record.source == "provider"
        and record.status in {"completed", "partial"}
        and record.usage.input_tokens is not None
    ]
    latest = context_calls[-1] if context_calls else None
    peak = max(context_calls, key=lambda record: record.usage.input_tokens or 0) if context_calls else None
    sources = {record.source for record in calls}
    if not calls:
        data_quality = "missing"
    elif sources == {"provider"}:
        data_quality = "provider"
    elif "provider" in sources:
        data_quality = "mixed"
    elif sources == {"estimated"}:
        data_quality = "estimated"
    else:
        data_quality = "degraded"

    return {
        "schema_version": 3,
        "call_count": len(calls),
        "known_usage_call_count": sum(
            record.usage.input_tokens is not None or record.usage.output_tokens is not None
            for record in calls
        ),
        "known_field_call_counts": known_counts,
        "usage": sums,
        "latest_context": _context_snapshot(latest, context_limit_tokens),
        "peak_context": _context_snapshot(peak, context_limit_tokens),
        "data_quality": data_quality,
        "call_ids": [record.call_id for record in calls],
    }


def _context_snapshot(
    record: Optional[ProviderCallUsage], context_limit_tokens: Optional[int]
) -> Optional[dict[str, Any]]:
    if record is None:
        return None
    return {
        "call_id": record.call_id,
        "input_tokens": record.usage.input_tokens,
        "limit_tokens": context_limit_tokens,
    }


def _status_rank(status: str) -> int:
    return {"failed": 0, "cancelled": 1, "partial": 2, "completed": 3}.get(status, -1)
