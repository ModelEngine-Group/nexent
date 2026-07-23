"""Low-cardinality, secret-free OpenTelemetry metrics for NL2AGENT."""

from typing import Any, Iterable


try:
    from opentelemetry import metrics as _otel_metrics

    _meter = _otel_metrics.get_meter(__name__)
    _action_total = _meter.create_counter(
        name="nl2agent_action_total",
        description="NL2AGENT business actions grouped by action and outcome.",
        unit="actions",
    )
    _cas_conflict_total = _meter.create_counter(
        name="nl2agent_workflow_cas_conflict_total",
        description="NL2AGENT optimistic-lock conflicts grouped by operation.",
        unit="conflicts",
    )
    _installation_total = _meter.create_counter(
        name="nl2agent_installation_total",
        description="NL2AGENT durable installation events grouped by resource and outcome.",
        unit="events",
    )
    _card_parse_total = _meter.create_counter(
        name="nl2agent_card_parse_total",
        description="Completed NL2AGENT answer parsing outcomes.",
        unit="answers",
    )
    _atomic_finalize_total = _meter.create_counter(
        name="nl2agent_atomic_finalize_total",
        description="Atomic NL2AGENT message finalization outcomes.",
        unit="messages",
    )
    _structured_sse_total = _meter.create_counter(
        name="nl2agent_structured_sse_total",
        description="Structured NL2AGENT SSE delivery outcomes.",
        unit="events",
    )
except Exception:  # pragma: no cover - telemetry is optional at runtime
    _action_total = None
    _cas_conflict_total = None
    _installation_total = None
    _card_parse_total = None
    _atomic_finalize_total = None
    _structured_sse_total = None


_ACTIONS = {
    "confirm_requirements",
    "save_model_selection",
    "apply_local_resources",
    "skip_local_resources",
    "install_mcp",
    "bind_mcp_tools",
    "skip_mcp_tools",
    "install_web_skill",
    "complete_online_configuration",
    "save_identity",
    "finalize",
}
_ACTION_OUTCOMES = {"success", "replayed", "pending", "conflict", "failure"}
_CAS_OPERATIONS = {"action", "message_finalize", "session_mutation", "session_resume"}
_INSTALLATION_OUTCOMES = {
    "retry",
    "lease_takeover",
    "lease_conflict",
    "request_conflict",
    "provider_failure",
    "heartbeat_failure",
    "replayed",
    "success",
}
_PARSE_OUTCOMES = {"success", "failure"}
_FINALIZE_OUTCOMES = {"success", "conflict", "failure"}
_SSE_OUTCOMES = {"sent", "failure", "stopped"}


def _label(value: Any, allowed: Iterable[str]) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else "unknown"


def _add(counter: Any, attributes: dict[str, str]) -> None:
    if counter is None:
        return
    try:
        counter.add(1, attributes)
    except Exception:  # pragma: no cover - telemetry must never affect behavior
        pass


def record_action(action: str, outcome: str) -> None:
    _add(
        _action_total,
        {
            "action": _label(action, _ACTIONS),
            "outcome": _label(outcome, _ACTION_OUTCOMES),
        },
    )


def record_cas_conflict(operation: str) -> None:
    _add(
        _cas_conflict_total,
        {"operation": _label(operation, _CAS_OPERATIONS)},
    )


def record_installation(resource_type: str, outcome: str) -> None:
    _add(
        _installation_total,
        {
            "resource_type": _label(resource_type, {"mcp", "skill"}),
            "outcome": _label(outcome, _INSTALLATION_OUTCOMES),
        },
    )


def record_card_parse(outcome: str) -> None:
    _add(
        _card_parse_total,
        {"outcome": _label(outcome, _PARSE_OUTCOMES)},
    )


def record_atomic_finalize(outcome: str) -> None:
    _add(
        _atomic_finalize_total,
        {"outcome": _label(outcome, _FINALIZE_OUTCOMES)},
    )


def record_structured_sse(outcome: str) -> None:
    _add(
        _structured_sse_total,
        {"outcome": _label(outcome, _SSE_OUTCOMES)},
    )
