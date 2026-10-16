"""Resolve request-scoped root controls without mutating independent models."""

from typing import Any

from nexent.core.agents.agent_model import AgentConfig, ModelConfig

from consts.exceptions import RunModelControlsError
from database.model_management_db import get_model_by_model_id
from management.services.model.reasoning import reasoning_controls


def validate_selected_model(model_id: int, tenant_id: str) -> dict[str, Any]:
    """Validate an explicit ID without revealing other tenants' records."""
    record = get_model_by_model_id(model_id, tenant_id)
    return validate_selected_record(record)


def validate_selected_record(record: dict | None) -> dict[str, Any]:
    """Apply identical preflight policy to records resolved by existing callers."""
    if not record or record.get("delete_flag") == "Y":
        raise RunModelControlsError("model_not_available")
    if record.get("model_type", "llm") not in {"llm", "chat"}:
        raise RunModelControlsError("model_type_invalid")
    if str(record.get("connect_status", "available")).lower() != "available":
        raise RunModelControlsError("model_unavailable")
    return record


def overlay_root_model(base: ModelConfig, values: dict[str, Any], alias: str) -> ModelConfig:
    """Apply only present fields and validate active effort/budget intent."""
    root = base.model_copy(deep=True)
    root.cite_name = alias
    if not any(k in values for k in ("deep_thinking", "thinking_effort", "reasoning_budget_tokens")):
        for key in ("temperature", "top_p"):
            if values.get(key) is not None:
                setattr(root, key, values[key])
        return root
    enabled = values.get("deep_thinking", base.enable_thinking)
    effort = values.get("thinking_effort")
    budget = values.get("reasoning_budget_tokens")
    controls = reasoning_controls(base.reasoning_capability)
    effort_control = next((c for c in controls if c.get("type") == "effort"), None)
    budget_control = next((c for c in controls if c.get("type") == "budget_tokens"), None)
    if enabled:
        if not controls:
            raise RunModelControlsError("model_controls_invalid")
        if effort not in (None, "auto") and budget not in (None, 0):
            raise RunModelControlsError("model_controls_invalid")
        if effort not in (None, "auto"):
            if not effort_control or effort not in effort_control.get("values", []):
                raise RunModelControlsError("model_controls_invalid")
            root.reasoning_effort = effort
            root.reasoning_budget_tokens = None
        elif effort == "auto":
            # Resolve against the immutable model/Agent defaults, never last turn.
            root.reasoning_effort = base.reasoning_effort
        if budget is not None:
            if not budget_control or (budget > 0 and not budget_control["min"] <= budget <= budget_control["max"]):
                raise RunModelControlsError("model_controls_invalid")
            root.reasoning_budget_tokens = budget or base.reasoning_budget_tokens
            root.reasoning_effort = None
        elif budget_control and effort == "auto":
            root.reasoning_effort = None
    else:
        root.reasoning_effort = None
        root.reasoning_budget_tokens = None
    if "deep_thinking" in values:
        root.enable_thinking = enabled
    extra = dict(root.extra_body or {})
    if "deep_thinking" in values:
        extra["enable_thinking"] = enabled
    if any(k in values for k in ("deep_thinking", "thinking_effort", "reasoning_budget_tokens")):
        extra.pop("reasoning_effort", None)
        extra.pop("reasoning_budget_tokens", None)
    root.extra_body = extra or None
    for key in ("temperature", "top_p"):
        if values.get(key) is not None:
            setattr(root, key, values[key])
    return root


def resolve_creator_model(
    model_list: list[ModelConfig], agent: AgentConfig, tenant_id: str,
    model_id: int | None, values: dict[str, Any] | None, default_record: dict | None,
) -> dict:
    """Bind a creator root to its actual record, preserving all other aliases."""
    record = validate_selected_model(model_id, tenant_id) if model_id is not None else default_record or {}
    if record:
        from agents.create_agent_info import create_model_config_from_record
        base = create_model_config_from_record(record)
    else:
        base = next((m for m in model_list if m.cite_name == record.get("display_name")), None)
    if base is None:
        if model_id is not None:
            raise RunModelControlsError("model_not_available")
        base = next((m for m in model_list if m.cite_name == agent.model_name), None)
    if base is None:
        raise RunModelControlsError("model_not_available")
    if model_id is not None or values:
        root = overlay_root_model(base, values or {}, "creator_root_model")
        model_list.append(root)
        agent.model_name = root.cite_name
    return record


def preflight_turn_controls(request, tenant_id: str, agent_record: dict | None = None) -> None:
    """Reject invalid intent before conversation creation or draft persistence."""
    model_id = request.model_id
    values = getattr(request, "_runtime_generation_config", None)
    if values is None:
        values = request.generation_config.model_dump(exclude_unset=True) if request.generation_config else {}
    if model_id is None:
        if not values and getattr(request, "reasoning_effort", None) is None and getattr(request, "reasoning_budget_tokens", None) is None:
            return
        configured = (agent_record or {}).get("model_ids") or []
        if configured:
            model_id = configured[0]
        else:
            from consts.const import MODEL_CONFIG_MAPPING
            from utils.config_utils import tenant_config_manager
            default_record = tenant_config_manager.get_model_config(MODEL_CONFIG_MAPPING["llm"], tenant_id)
            model_id = (default_record or {}).get("model_id")
        if model_id is None:
            raise RunModelControlsError("model_not_available")
    record = validate_selected_model(model_id, tenant_id)
    from agents.create_agent_info import create_model_config_from_record
    base = create_model_config_from_record(record)
    if agent_record:
        override = (agent_record.get("model_params_override") or {}).get(str(model_id), {})
        extra = override.get("extra_params") or {}
        for source, target in (("enable_thinking", "enable_thinking"),
                               ("reasoning_effort", "reasoning_effort"),
                               ("reasoning_budget_tokens", "reasoning_budget_tokens")):
            if source in extra:
                setattr(base, target, extra[source])
    values = dict(values)
    for attr, key in (("reasoning_effort", "thinking_effort"), ("reasoning_budget_tokens", "reasoning_budget_tokens")):
        value = getattr(request, attr, None)
        if value is not None:
            if key in values and values[key] != value:
                raise RunModelControlsError("model_controls_invalid")
            values[key] = value
    overlay_root_model(base, values, "preflight_root")
