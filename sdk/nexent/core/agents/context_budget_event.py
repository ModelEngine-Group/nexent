"""Build the content-free P3 conversation budget event."""

from __future__ import annotations

from typing import Any


_COMPRESSION_REASON_BY_CALL_TYPE = {
    "history_summary": "history_summary",
    "history_incremental": "history_incremental",
    "long_term_memory_block_selection": "long_term_memory_selection",
}


def _compression_reasons(context_evidence: Any) -> list[str]:
    """Project internal compression records onto a stable, content-free enum."""
    reasons: list[str] = []
    for record in getattr(context_evidence, "compression_records", ()) or ():
        call_type = getattr(record, "call_type", None)
        if call_type is None and isinstance(record, dict):
            call_type = record.get("call_type")
        reason = _COMPRESSION_REASON_BY_CALL_TYPE.get(call_type)
        if reason is not None and reason not in reasons:
            reasons.append(reason)
    if bool(getattr(context_evidence, "fallback_compaction_used", False)):
        reasons.append("representation_compaction")
    return reasons


def build_context_budget_event(
    preflight: Any,
    context_evidence: Any,
    *,
    step_number: int,
    recovery_state: str = "not_needed",
    recovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    components = preflight.components
    raw_context = int(getattr(context_evidence, "raw_token_estimate", 0) or 0)
    final_context = int(getattr(context_evidence, "final_token_estimate", 0) or 0)
    saved = max(raw_context - final_context, 0)
    event = {
        "schema_version": 1, "purpose": getattr(context_evidence, "purpose", "step"),
        "step_number": int(step_number), "raw_tokens": raw_context, "final_tokens": final_context,
        "soft_budget": int(preflight.soft_budget), "hard_budget": int(preflight.hard_budget),
        "hard_count": int(preflight.hard_count),
        "components": {
            "message_text": int(components.message_text), "message_framing": int(components.message_framing),
            "tools": int(components.tools), "media": int(components.media),
            "reasoning": int(components.reasoning), "other_semantic": int(components.other_semantic),
        },
        "count_source": getattr(preflight.count_source, "value", str(preflight.count_source)),
        "compression": {
            "attempted": bool(getattr(context_evidence, "compression_attempted", False)),
            "saved_tokens": saved, "ratio": saved / raw_context if raw_context else 0.0,
            "fallback_compaction": bool(getattr(context_evidence, "fallback_compaction_used", False)),
            "reasons": _compression_reasons(context_evidence),
        },
        "recovery_state": recovery_state, "request_fingerprint": preflight.request_fingerprint,
        "budget_fingerprint": preflight.identity_fingerprint, "retry_ordinal": int(preflight.retry_ordinal),
    }
    archive_active = bool(getattr(context_evidence, "archive_active", False))
    if archive_active or recovery:
        details = dict(recovery or {})
        details.setdefault("phase", "archive" if archive_active else "compression")
        details.setdefault("attempt", int(preflight.retry_ordinal))
        details.setdefault("maximum_attempts", 2)
        details.setdefault("compression_target", int(preflight.hard_budget))
        details.setdefault("archive_active", archive_active)
        details.setdefault("archived_item_count", int(getattr(context_evidence, "archived_item_count", 0)))
        details.setdefault("retained_item_count", int(getattr(context_evidence, "retained_item_count", 0)))
        details.setdefault("recall_invocation_count", int(getattr(context_evidence, "recall_invocation_count", 0)))
        details.setdefault("recalled_tokens", int(getattr(context_evidence, "recalled_tokens", 0)))
        event["recovery"] = details
    return event
