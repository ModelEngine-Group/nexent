"""Helpers for keeping agent-owned reasoning settings independent from models."""

from copy import deepcopy
from typing import Optional

from database.model_management_db import get_model_by_model_id
from utils.model_name_utils import add_repo_to_name


REASONING_EFFORT_VALUES = {
    "auto",
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
}
COMMON_REASONING_LEVELS = {"low", "medium", "high"}


def _resolve_model_reasoning_capability(model_info: Optional[dict]) -> Optional[dict]:
    """Resolve capability metadata for an agent snapshot when needed."""
    if not isinstance(model_info, dict):
        return None
    capability = model_info.get("reasoning_capability")
    if isinstance(capability, dict):
        return capability
    try:
        from configs.model_catalog_loader import resolve_reasoning_capability
    except ImportError:
        return None
    return resolve_reasoning_capability(
        model_name=add_repo_to_name(
            model_info.get("model_repo", ""), model_info.get("model_name", "")
        ),
        base_url=model_info.get("base_url"),
        provider_hint=model_info.get("model_factory"),
    )


def reasoning_snapshot_from_model(model_info: Optional[dict]) -> dict:
    """Return the agent-owned reasoning settings copied from a model row."""
    model_extra = (model_info or {}).get("extra_params")
    model_extra = model_extra if isinstance(model_extra, dict) else {}
    enabled = model_extra.get("enable_thinking")
    if not isinstance(enabled, bool):
        enabled = isinstance(model_extra.get("reasoning_effort"), str)

    snapshot = {"enable_thinking": enabled}
    if enabled:
        effort = model_extra.get("reasoning_effort")
        capability = _resolve_model_reasoning_capability(model_info)
        if isinstance(capability, dict) and capability.get("status") == "supported":
            levels = set(capability.get("levels") or []) or COMMON_REASONING_LEVELS
        else:
            levels = COMMON_REASONING_LEVELS
        snapshot["reasoning_effort"] = (
            effort
            if effort == "auto"
            or (effort in REASONING_EFFORT_VALUES and effort in levels)
            else "auto"
        )
    return snapshot


def snapshot_agent_reasoning_config(
    model_ids: Optional[list[int]],
    requested_overrides: Optional[dict],
    existing_overrides: Optional[dict],
    tenant_id: str,
) -> Optional[dict]:
    """Snapshot reasoning settings while preserving explicit agent overrides.

    Only missing reasoning keys are filled from the model. Explicit agent
    values always win, so later model edits do not leak into an agent's
    configuration.
    """
    override_map = deepcopy(
        requested_overrides
        if requested_overrides is not None
        else existing_overrides or {}
    )
    if not isinstance(override_map, dict):
        override_map = {}

    for model_id in model_ids or []:
        model_key = str(model_id)
        entry = override_map.get(model_key)
        if not isinstance(entry, dict):
            entry = {}
        else:
            entry = deepcopy(entry)

        extra_params = entry.get("extra_params")
        extra_params = (
            deepcopy(extra_params) if isinstance(extra_params, dict) else {}
        )

        has_reasoning_override = (
            "enable_thinking" in extra_params
            or "reasoning_effort" in extra_params
            or "reasoning_effort" in entry
        )
        if not has_reasoning_override:
            model_info = get_model_by_model_id(model_id, tenant_id=tenant_id)
            extra_params.update(reasoning_snapshot_from_model(model_info))
        elif extra_params.get("enable_thinking") is True and not isinstance(
            extra_params.get("reasoning_effort"), str
        ):
            extra_params["reasoning_effort"] = "auto"
        elif extra_params.get("enable_thinking") is False:
            extra_params.pop("reasoning_effort", None)

        entry["extra_params"] = extra_params
        override_map[model_key] = entry

    return override_map or None
