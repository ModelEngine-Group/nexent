# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pure interpretation of pre-profile model parameters, shared with one-time migration."""

from typing import Any, Dict, Optional

from nexent.core.model_service.compatibility.legacy_reasoning import legacy_reasoning_wire_parameters


COMMON_REASONING_LEVELS = ("low", "medium", "high")
COMMON_REASONING_DEFAULT = "auto"

def legacy_thinking_enabled(extra_params: Optional[Dict[str, Any]]) -> bool:
    """Return whether the model explicitly or implicitly enables reasoning."""
    if not isinstance(extra_params, dict):
        return False
    if isinstance(extra_params.get("enable_thinking"), bool):
        return extra_params["enable_thinking"]
    return (
        isinstance(extra_params.get("reasoning_effort"), str)
        or isinstance(extra_params.get("reasoning_budget_tokens"), int)
    )


def legacy_extra_body(extra_params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Flatten historical custom fields, excluding dedicated reasoning values."""
    if not extra_params or not isinstance(extra_params, dict):
        return None
    extra_body = dict(extra_params)
    # These are dedicated ModelConfig fields, not provider request-body keys.
    extra_body.pop("reasoning_effort", None)
    extra_body.pop("reasoning_budget_tokens", None)
    custom = extra_body.pop("__custom__", None)
    if custom and isinstance(custom, dict):
        extra_body.update(custom)
    return extra_body if extra_body else None


def legacy_reasoning_effort(
    extra_params: Optional[Dict[str, Any]],
    capability: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Resolve the enabled model's effort from its supported profile."""
    if not isinstance(extra_params, dict) or not legacy_thinking_enabled(extra_params):
        return None
    if extra_params.get("reasoning_effort") == "auto":
        return None
    capability = capability if isinstance(capability, dict) and capability.get("status") == "supported" else {}
    levels = capability.get("levels") or list(COMMON_REASONING_LEVELS)
    default = capability.get("default")
    if default not in levels:
        default = COMMON_REASONING_DEFAULT
    saved = extra_params.get("reasoning_effort")
    if saved in levels:
        return saved
    # Auto is the universal fallback: omit the provider-specific effort so the
    # model can choose its own reasoning depth.
    return None if saved is None or default == COMMON_REASONING_DEFAULT else default


def legacy_reasoning_budget(
    extra_params: Optional[Dict[str, Any]],
    capability: Optional[Dict[str, Any]],
) -> Optional[int]:
    """Resolve a persisted numeric reasoning budget within the source range."""
    if not isinstance(extra_params, dict) or not legacy_thinking_enabled(extra_params):
        return None
    value = extra_params.get("reasoning_budget_tokens")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    controls = capability.get("controls") if isinstance(capability, dict) else None
    budget_control = next(
        (control for control in controls or []
         if isinstance(control, dict) and control.get("type") == "budget_tokens"),
        None,
    )
    if isinstance(budget_control, dict):
        minimum = budget_control.get("min")
        maximum = budget_control.get("max")
        if isinstance(minimum, int) and isinstance(maximum, int):
            return min(maximum, max(minimum, value))
    return value


def legacy_agent_request_parameters(record, *, model_id, capability):
    """Resolve the old Agent's sampling/reasoning body without reading credentials."""
    if record.get("model_type") not in {"llm", "chat"}:
        raise ValueError("LEGACY_MODEL_TYPE_UNSUPPORTED")
    extra = record.get("extra_params")
    if extra is not None and not isinstance(extra, dict):
        raise ValueError("LEGACY_PARAMETERS_INVALID")
    body = legacy_reasoning_wire_parameters(
        model_id=model_id, base_url=record.get("base_url"), model_factory=record.get("model_factory"),
        capability=capability, effort=legacy_reasoning_effort(extra, capability),
        budget=legacy_reasoning_budget(extra, capability), extra_body=legacy_extra_body(extra),
    )
    # The old Agent passes these kwargs even when SQL values are NULL; custom body wins.
    return {"temperature": record.get("temperature"), "top_p": record.get("top_p"), **body}
