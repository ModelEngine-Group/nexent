"""Shared normalization for canonical reasoning settings."""

from copy import deepcopy
from typing import Any, Dict, Optional


REASONING_PARAM_KEYS = (
    "enable_thinking",
    "reasoning_effort",
    "reasoning_budget_tokens",
)


def _controls(capability: Optional[dict]) -> list[dict]:
    """Return the declared reasoning controls in a backward-compatible shape."""
    if not isinstance(capability, dict) or capability.get("status") != "supported":
        return []
    declared = capability.get("controls")
    if isinstance(declared, list) and declared:
        return [control for control in declared if isinstance(control, dict)]
    levels = capability.get("levels") or []
    if levels:
        return [{"type": "effort", "values": list(levels)}]
    if capability.get("control") == "toggle":
        return [{"type": "toggle"}]
    return []


def supports_reasoning(capability: Optional[dict]) -> bool:
    """Whether the catalog explicitly declares a usable reasoning control."""
    return bool(_controls(capability))


def _control(capability: Optional[dict], control_type: str) -> Optional[dict]:
    return next(
        (control for control in _controls(capability) if control.get("type") == control_type),
        None,
    )


def normalize_reasoning_params(
    extra_params: Optional[Dict[str, Any]],
    capability: Optional[dict],
) -> Dict[str, Any]:
    """Normalize persisted canonical reasoning fields against model capability.

    Reasoning is intentionally fail-closed: a model without an explicit
    catalog capability never receives stale reasoning fields from an old row.
    When both controls are declared, a positive numeric budget is the active
    control and the effort enum is removed.
    """
    normalized = deepcopy(extra_params) if isinstance(extra_params, dict) else {}
    if not supports_reasoning(capability):
        for key in REASONING_PARAM_KEYS:
            normalized.pop(key, None)
        return normalized

    effort_control = _control(capability, "effort")
    budget_control = _control(capability, "budget_tokens")
    enabled = normalized.get("enable_thinking")

    if enabled is False:
        normalized.pop("reasoning_effort", None)
        normalized.pop("reasoning_budget_tokens", None)
        return normalized

    budget = normalized.get("reasoning_budget_tokens")
    has_budget = (
        budget_control is not None
        and isinstance(budget, int)
        and not isinstance(budget, bool)
        and budget > 0
    )
    if has_budget:
        minimum = budget_control.get("min")
        maximum = budget_control.get("max")
        if isinstance(minimum, int) and isinstance(maximum, int):
            normalized["reasoning_budget_tokens"] = min(maximum, max(minimum, budget))
        normalized.pop("reasoning_effort", None)
    else:
        normalized.pop("reasoning_budget_tokens", None)
        effort = normalized.get("reasoning_effort")
        if effort_control is None:
            normalized.pop("reasoning_effort", None)
        elif effort is not None:
            values = {str(value) for value in effort_control.get("values") or []}
            values.add("auto")
            if str(effort) not in values:
                normalized["reasoning_effort"] = "auto"

    # Historical rows may have only an effort/budget field. Preserve their
    # meaning for supported models while keeping unsupported rows fail-closed.
    if enabled is None and (
        "reasoning_effort" in normalized or "reasoning_budget_tokens" in normalized
    ):
        normalized["enable_thinking"] = True
    return normalized


def reasoning_controls(capability: Optional[dict]) -> list[dict]:
    """Expose normalized controls to callers that need to validate a value."""
    return _controls(capability)
