# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Conversation-only parameter patches validated against frozen outlet rules."""

from contracts.errors.exceptions import ModelOutletValidationError
from nexent.core.model_service.profiles.parameter_rules import (
    overlay_profile_parameters,
    patch_parameter_values,
)
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.protocol_parameters import (
    OUTLET_TOKEN_LIMIT_KEYS, without_outlet_token_limits,
)

from nexent.core.model_service.profiles.outlet_controls import ensure_outlet_parameter_rules


def merge_model_preferences(profile, preferences):
    """Do not discard invalid stored choices or apply creation defaults during a run."""
    if not isinstance(preferences, dict):
        raise ModelOutletValidationError("CONVERSATION_PREFERENCES_INVALID")
    profile = ensure_outlet_parameter_rules(profile)
    try:
        resolved = overlay_profile_parameters(profile, without_outlet_token_limits(preferences), scope="conversation")
        values = resolved.parameter_values
        output = values.get("max_output_tokens", values.get("max_tokens"))
        context = profile.capabilities.context
        limits = [value for value in (context.output_limit, context.combined_window) if value is not None]
        if type(output) is int and limits and output > min(limits):
            raise ModelOutletValidationError("PARAMETER_LIMIT_EXCEEDED", "/max_output_tokens")
        return resolved
    except ParameterValidationError as error:
        raise ModelOutletValidationError(error.category, error.path) from None


def read_model_preferences(conversation_id, user_id):
    from management.db.conversation.model_preferences import model_preferences

    saved = model_preferences(conversation_id, user_id)
    return {**saved, "model_parameter_preferences": {
        key: without_outlet_token_limits(values) if isinstance(values, dict) else values
        for key, values in saved["model_parameter_preferences"].items()
    }}


def _conversation_agent_entry(conversation_id, outlet_id, user_id, tenant_id):
    """Match the native runtime root while keeping Workbench/creator roots independent."""
    from contracts.errors.exceptions import ConversationNotFoundError
    from management.services.conversation.service import get_conversation_service

    conversation = get_conversation_service(conversation_id, user_id, tenant_id)
    if conversation is None:
        raise ConversationNotFoundError("Conversation not found")
    if (isinstance(conversation.get("workbench_config"), dict)
            or conversation.get("target") is not None or not conversation.get("agent_id")):
        return {}
    from types import SimpleNamespace
    from management.db.agent.repository import search_agent_info_by_agent_id
    from management.services.model.run_controls import _agent_record_for_run

    request = SimpleNamespace(agent_id=conversation["agent_id"], version_no=None, is_debug=False)
    agent = _agent_record_for_run(request, tenant_id, search_agent_info_by_agent_id)
    if agent.get("agent_origin") == "SYSTEM":
        return {}
    return (agent.get("model_params_override") or {}).get(str(outlet_id)) or {}


def _merge_conversation_preferences(profile, entry, values):
    from management.services.agent.model_parameters import merge_runtime_model_parameters

    try:
        return (merge_runtime_model_parameters(profile, entry, values) if entry
                else merge_model_preferences(profile, values))
    except ParameterValidationError as error:
        raise ModelOutletValidationError(error.category, error.path) from None


def patch_model_preferences(conversation_id, outlet_id, request, user_id, tenant_id):
    from management.db.conversation.model_preferences import model_preferences
    from management.db.model.outlets import get_resolved_model_record
    from nexent.core.model_service.registry import model_service_references

    # Check conversation access before reading an outlet or validating its fields.
    read_model_preferences(conversation_id, user_id)
    entry = _conversation_agent_entry(conversation_id, outlet_id, user_id, tenant_id)
    profile = get_resolved_model_record(outlet_id, tenant_id, registered_references=model_service_references())
    if profile is None or profile.identity.model_type != "llm":
        raise ModelOutletValidationError("MODEL_OUTLET_NOT_AVAILABLE")
    forbidden = request.parameter_values.keys() & OUTLET_TOKEN_LIMIT_KEYS
    if forbidden:
        raise ModelOutletValidationError("FIXED_PARAMETER", "/" + sorted(forbidden)[0])
    deleted = request.delete_parameters
    try:
        patch_parameter_values({}, request.parameter_values, deleted)
    except ParameterValidationError as error:
        raise ModelOutletValidationError(error.category, error.path) from None

    def resolve(saved):
        if not isinstance(saved, dict):
            raise ModelOutletValidationError("CONVERSATION_PREFERENCES_INVALID")
        updated = patch_parameter_values(without_outlet_token_limits(saved), request.parameter_values, deleted)
        _merge_conversation_preferences(profile, entry, updated)
        return updated

    return model_preferences(conversation_id, user_id, outlet_id=outlet_id, resolve_values=resolve)


def read_model_preference_view(conversation_id, outlet_id, user_id, tenant_id):
    from management.db.model.outlets import get_resolved_model_record
    from nexent.core.model_service.registry import model_service_references

    saved = read_model_preferences(conversation_id, user_id)
    entry = _conversation_agent_entry(conversation_id, outlet_id, user_id, tenant_id)
    profile = get_resolved_model_record(outlet_id, tenant_id, registered_references=model_service_references())
    if profile is None or profile.identity.model_type != "llm":
        raise ModelOutletValidationError("MODEL_OUTLET_NOT_AVAILABLE")
    profile = ensure_outlet_parameter_rules(profile)
    values = saved["model_parameter_preferences"].get(str(outlet_id), {})
    if isinstance(values, dict):
        values = without_outlet_token_limits(values)
    issues = []
    defaults = profile.parameter_values
    try:
        if entry:
            from management.services.agent.model_parameters import merge_agent_model_parameters

            defaults = merge_agent_model_parameters(profile, entry).parameter_values
        _merge_conversation_preferences(profile, entry, values)
    except (ModelOutletValidationError, ParameterValidationError) as error:
        issues.append({"category": error.category, "field": error.path})
    return {"parameter_values": values, "defaults": defaults,
            "reasoning_status": profile.capabilities.reasoning.status,
            "reasoning_can_disable": profile.capabilities.reasoning.can_disable,
            "output_limit": profile.capabilities.context.output_limit,
            "field_specs": profile.parameter_rules, "config_revision": profile.config_revision, "issues": issues}


def validate_model_preferences(preferences, tenant_id, *, allowed_model_ids=None, agent_overrides=None):
    """Validate first-turn drafts with the same frozen rules as preference PATCH."""
    from contracts.errors.exceptions import ForbiddenError
    from management.db.model.outlets import get_resolved_model_record
    from management.services.model.run_controls import validate_selected_model
    from nexent.core.model_service.registry import model_service_references

    if not isinstance(preferences, dict):
        raise ModelOutletValidationError("CONVERSATION_PREFERENCES_INVALID")
    for key, values in preferences.items():
        if not isinstance(key, str) or not key.isdecimal() or str(int(key)) != key or int(key) <= 0:
            raise ModelOutletValidationError("CONVERSATION_PREFERENCES_INVALID")
        outlet_id = int(key)
        if allowed_model_ids and outlet_id not in allowed_model_ids:
            raise ForbiddenError("The selected model is not configured for this Agent")
        validate_selected_model(outlet_id, tenant_id)
        profile = get_resolved_model_record(outlet_id, tenant_id, registered_references=model_service_references())
        if profile is None or profile.identity.model_type != "llm":
            raise ModelOutletValidationError("MODEL_OUTLET_NOT_AVAILABLE")
        if not isinstance(values, dict):
            raise ModelOutletValidationError("CONVERSATION_PREFERENCES_INVALID")
        forbidden = values.keys() & OUTLET_TOKEN_LIMIT_KEYS
        if forbidden:
            raise ModelOutletValidationError("FIXED_PARAMETER", "/" + sorted(forbidden)[0])
        entry = (agent_overrides or {}).get(key)
        if entry:
            from management.services.agent.model_parameters import merge_runtime_model_parameters

            merge_runtime_model_parameters(profile, entry, values)
        else:
            merge_model_preferences(profile, values)


def patch_model_selection(conversation_id, request, user_id, tenant_id):
    """Both Agent chat modes save selection through the same ownership and row-lock path."""
    from types import SimpleNamespace
    from contracts.errors.exceptions import ConversationNotFoundError
    from management.db.agent.repository import search_agent_info_by_agent_id
    from management.db.conversation.model_preferences import model_preferences
    from management.services.conversation.service import get_conversation_service
    from management.services.model.run_controls import validate_agent_model_selection

    conversation = get_conversation_service(conversation_id, user_id, tenant_id)
    if conversation is None:
        raise ConversationNotFoundError("Conversation not found")
    workbench = isinstance(conversation.get("workbench_config"), dict)
    selection = SimpleNamespace(model_id=request.selected_model_id, workbench=None,
        entrypoint="workbench" if workbench else None, is_debug=False,
        agent_id=conversation.get("agent_id"), version_no=None)
    validate_agent_model_selection(selection, tenant_id, search_agent_info_by_agent_id)
    return model_preferences(conversation_id, user_id, selected_model_id=request.selected_model_id)
