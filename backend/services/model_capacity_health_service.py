"""Deterministic, content-free capacity health classification for P3."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional

REVIEW_DUE_DAYS = 150
EXPIRED_DAYS = 180


class CapacityHealthStatus(str, Enum):
    HEALTHY = "healthy"
    REVIEW_DUE = "review_due"
    EXPIRED = "expired"
    ESTIMATED = "estimated"
    UNCONFIGURED = "unconfigured"
    INVALID = "invalid"
    PROBE_DEGRADED = "probe_degraded"


def _parse_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def catalog_freshness(
    verified_at: Optional[str], *, now: Optional[datetime] = None
) -> tuple[str, Optional[str], Optional[str]]:
    checked = _parse_utc(verified_at)
    if checked is None:
        return "expired", None, None
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_days = (current - checked).total_seconds() / 86400
    review_at = datetime.fromtimestamp(
        checked.timestamp() + REVIEW_DUE_DAYS * 86400, tz=timezone.utc
    ).isoformat()
    expires_at = datetime.fromtimestamp(
        checked.timestamp() + EXPIRED_DAYS * 86400, tz=timezone.utc
    ).isoformat()
    state = "expired" if age_days >= EXPIRED_DAYS else "review_due" if age_days >= REVIEW_DUE_DAYS else "current"
    return state, review_at, expires_at


def classify_capacity_health(
    record: Mapping[str, Any], *, match: Optional[Mapping[str, Any]] = None,
    profile_verified_at: Optional[str] = None, now: Optional[datetime] = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    context_window = record.get("context_window_tokens")
    max_output = record.get("max_output_tokens")
    max_input = record.get("max_input_tokens")
    if context_window is not None and context_window <= 0:
        reasons.append("context_window_invalid")
    if max_output is not None and max_output <= 0:
        reasons.append("max_output_invalid")
    if max_input is not None and max_input <= 0:
        reasons.append("max_input_invalid")
    if context_window and max_output and max_output >= context_window:
        reasons.append("output_not_below_context")

    match_data = dict(match or {})
    auto_applicable = bool(match_data.get("auto_applicable"))
    lifecycle, review_at, expires_at = catalog_freshness(profile_verified_at, now=now)
    probe = record.get("token_count_probe_metadata") or {}
    probe_status = probe.get("status") or probe.get("state")
    capacity_source = record.get("capacity_source") or "unknown"

    if reasons:
        status, action = CapacityHealthStatus.INVALID, "edit"
    elif context_window is None or max_output is None:
        status, action = CapacityHealthStatus.UNCONFIGURED, "review_profile" if auto_applicable else "edit"
        reasons.append("required_capacity_missing")
    elif lifecycle == "expired" and record.get("capability_profile_version"):
        status, action = CapacityHealthStatus.EXPIRED, "review_profile" if auto_applicable else "review_evidence"
        reasons.append("catalog_evidence_expired")
    elif probe_status in {"degraded", "temporary_failure", "failed", "stale"}:
        status, action = CapacityHealthStatus.PROBE_DEGRADED, "retry_probe"
        reasons.append("token_count_probe_degraded")
    elif capacity_source in {"unknown", "legacy"} or (
        not record.get("tokenizer_family") and probe_status != "supported"
    ):
        status, action = CapacityHealthStatus.ESTIMATED, "review_profile" if auto_applicable else "edit"
        reasons.append("capacity_or_counting_estimated")
    elif lifecycle == "review_due" and record.get("capability_profile_version"):
        status, action = CapacityHealthStatus.REVIEW_DUE, "review_profile" if auto_applicable else "review_evidence"
        reasons.append("catalog_evidence_review_due")
    else:
        status, action = CapacityHealthStatus.HEALTHY, "none"
        reasons.append("capacity_verified")
    return {
        "status": status.value, "reasons": reasons, "action": action,
        "match_kind": match_data.get("match_kind") or "none",
        "suggestion_available": auto_applicable,
        "profile_version": record.get("capability_profile_version"),
        "verified_at": profile_verified_at, "review_at": review_at,
        "expires_at": expires_at, "probe_status": probe_status,
    }
