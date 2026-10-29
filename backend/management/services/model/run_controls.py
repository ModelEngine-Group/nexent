# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resolve request-scoped root controls without mutating independent models."""

from collections.abc import Callable
from typing import Any

from nexent.core.agents.agent_model import AgentConfig, ModelConfig

from contracts.errors.exceptions import RunModelControlsError
from management.db.model.repository import get_model_by_model_id


def _agent_record_for_run(request, tenant_id: str, lookup: Callable[..., dict]) -> dict:
    """Resolve the same version while retaining the caller's Agent lookup boundary."""
    from management.db.agent.repository import query_current_version_no

    return lookup(
        agent_id=request.agent_id,
        tenant_id=tenant_id,
        version_no=request.version_no if request.version_no is not None
        else (query_current_version_no(request.agent_id, tenant_id) or 0),
    )


def validate_agent_model_selection(request, tenant_id: str, lookup: Callable[..., dict]) -> None:
    """Validate selected catalog models and native Agent associations before writes."""
    selected_id = request.model_id
    if selected_id is None:
        return
    validate_selected_model(selected_id, tenant_id)
    if request.entrypoint != "workbench" and not request.is_debug and request.agent_id:
        configured = _agent_record_for_run(request, tenant_id, lookup).get("model_ids") or []
        if configured and selected_id not in configured:
            from contracts.errors.exceptions import ForbiddenError

            raise ForbiddenError("The selected model is not configured for this Agent")


def preflight_agent_turn_controls(request, tenant_id: str, lookup: Callable[..., dict]) -> None:
    """Preflight only explicit model controls using the native Agent's defaults."""
    if request.model_id is None and not request.model_parameter_preferences and not getattr(request, "_runtime_model_parameter_preferences", {}):
        return
    root_record = None
    if request.entrypoint != "workbench" and request.agent_id:
        root_record = _agent_record_for_run(request, tenant_id, lookup)
    preflight_turn_controls(request, tenant_id, root_record)


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
    return record


def preflight_turn_controls(request, tenant_id: str, agent_record: dict | None = None) -> None:
    """Validate the single preference format before any conversation write."""
    from contracts.errors.exceptions import ModelOutletValidationError
    from management.services.conversation.model_preferences import validate_model_preferences

    model_id = request.model_id
    if model_id is None and getattr(request, "_runtime_model_parameter_preferences", {}):
        configured = (agent_record or {}).get("model_ids") or []
        if configured:
            model_id = configured[0]
        else:
            from contracts.constants.constants import MODEL_CONFIG_MAPPING
            from management.services.configuration.tenant.settings import tenant_config_manager
            default = tenant_config_manager.get_model_config(MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id)
            model_id = (default or {}).get("model_id")
    if model_id is not None:
        validate_selected_model(model_id, tenant_id)
    allowed = (agent_record or {}).get("model_ids") or None
    preferences = request.model_parameter_preferences
    if not preferences and model_id is not None:
        saved = getattr(request, "_runtime_model_parameter_preferences", {})
        values = saved.get(str(model_id))
        if values is not None:
            preferences = {str(model_id): values}
    try:
        validate_model_preferences(preferences, tenant_id, allowed_model_ids=allowed)
    except ModelOutletValidationError as error:
        raise RunModelControlsError("model_controls_invalid") from error


def resolve_creator_model(
    model_list: list[ModelConfig], agent: AgentConfig, tenant_id: str,
    model_id: int | None, preferences: dict | None, default_record: dict | None,
) -> dict:
    """Select a creator root and use the shared profile preference merger."""
    from management.services.agent.preparation.run import apply_root_model_preferences
    from management.services.model.run_bindings import create_model_config_from_record

    record = validate_selected_model(model_id, tenant_id) if model_id is not None else default_record or {}
    if record:
        root = create_model_config_from_record(record).model_copy(deep=True, update={"cite_name": "creator_root_model"})
        model_list.append(root)
        agent.model_name = root.cite_name
    elif not any(model.cite_name == agent.model_name for model in model_list):
        raise RunModelControlsError("model_not_available")
    apply_root_model_preferences(model_list, agent, preferences)
    return record
