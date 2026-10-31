# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared normalization for canonical reasoning settings."""

import logging
from copy import deepcopy
from typing import Any, Dict, Optional

from management.services.model.names import add_repo_to_name

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
        (
            control
            for control in _controls(capability)
            if control.get("type") == control_type
        ),
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


try:
    from configs.model_catalog_loader import (
        resolve_reasoning_capability,
    )
except Exception as _exc:  # noqa: BLE001
    logger_catalog_import = logging.getLogger("model_catalog")
    logger_catalog_import.warning(
        "model_catalog_loader import failed: %s. Catalog auto-fill disabled.", _exc
    )

    def resolve_reasoning_capability(  # type: ignore[no-redef]
        model_name: str,
        base_url: Optional[str] = None,
        provider_hint: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return None


COMMON_REASONING_LEVELS = ("low", "medium", "high")
COMMON_REASONING_DEFAULT = "auto"


def _enrich_model_reasoning_capability(model: Dict[str, Any]) -> None:
    """Attach catalog-declared reasoning capability to an API model row."""
    if model.get("model_type") not in {"llm", "chat"}:
        return
    remainder = model.get("resolved_profile")
    if model.get("profile_schema_version") is not None or (
            isinstance(remainder, dict) and "migration_error" in remainder):
        from management.services.model.outlet_projection import project_saved_outlet

        model.update(project_saved_outlet(model))
        return
    model_name = add_repo_to_name(
        model.get("model_repo", ""), model.get("model_name", "")
    )
    capability = resolve_reasoning_capability(
        model_name=model_name,
        base_url=model.get("base_url"),
        provider_hint=model.get("model_factory"),
    )
    model["extra_params"] = (
        normalize_reasoning_params(model.get("extra_params"), capability) or None
    )
    if capability is not None:
        model["reasoning_capability"] = capability


def get_model_reasoning_capability(
    model_name: str,
    base_url: Optional[str] = None,
    provider_hint: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve reasoning controls using the model ID and provider API URL."""
    return resolve_reasoning_capability(model_name, base_url, provider_hint)


def _enrich_discovered_model_reasoning_capability(
    model: Dict[str, Any],
    base_url: Optional[str],
    provider_hint: Optional[str],
) -> None:
    """Attach build-time models.dev capability to a provider discovery row."""
    # OpenAI-compatible discovery rows may omit model_type when the request
    # already filters to LLMs; treat that legacy shape as an LLM row.
    if model.get("model_type") not in {None, "llm", "chat"}:
        return
    model_name = str(model.get("id") or model.get("model_name") or "").strip()
    if not model_name:
        return
    capability = resolve_reasoning_capability(model_name, base_url, provider_hint)
    if capability is not None:
        model["reasoning_capability"] = capability


def _apply_model_reasoning_default(
    model_data: Dict[str, Any], provider_hint: Optional[str]
) -> None:
    """Persist an enabled model's reasoning default without enabling it implicitly.

    The value is kept in the existing ``extra_params`` JSONB column, so this
    also upgrades old/custom model IDs without requiring a schema migration.
    New models keep the switch disabled unless the caller explicitly enables
    it.
    """
    if model_data.get("model_type") not in {"llm", "chat"}:
        return
    extra_params = dict(model_data.get("extra_params") or {})
    enabled = extra_params.get("enable_thinking")
    if enabled is not True:
        if enabled is False:
            extra_params.pop("reasoning_effort", None)
            extra_params.pop("reasoning_budget_tokens", None)
            model_data["extra_params"] = extra_params or None
        return
    model_name = add_repo_to_name(
        model_data.get("model_repo", ""), model_data.get("model_name", "")
    )
    capability = resolve_reasoning_capability(
        model_name=model_name,
        base_url=model_data.get("base_url"),
        provider_hint=provider_hint or model_data.get("model_factory"),
    )
    if isinstance(capability, dict) and capability.get("status") == "supported":
        levels = capability.get("levels") or list(COMMON_REASONING_LEVELS)
    else:
        # Keep a provider-agnostic profile for unknown/custom model IDs. The
        # provider remains the source of truth if it rejects a concrete value.
        levels = list(COMMON_REASONING_LEVELS)
    if extra_params.get("reasoning_effort") == "auto":
        return
    if extra_params.get("reasoning_effort") in levels:
        return
    extra_params["reasoning_effort"] = COMMON_REASONING_DEFAULT
    model_data["extra_params"] = extra_params
