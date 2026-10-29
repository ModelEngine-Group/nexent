# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Conversation-only parameter patches validated against frozen outlet rules."""

from contracts.errors.exceptions import ModelOutletValidationError
from nexent.core.model_service.profiles.parameter_rules import (
    overlay_profile_parameters,
    patch_parameter_values,
)
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.protocol_parameters import (
    OUTLET_TOKEN_LIMIT_KEYS, ensure_outlet_sampling_rules, without_outlet_token_limits,
)


def merge_model_preferences(profile, preferences):
    """Do not discard invalid stored choices or apply creation defaults during a run."""
    if not isinstance(preferences, dict):
        raise ModelOutletValidationError("CONVERSATION_PREFERENCES_INVALID")
    profile = ensure_outlet_sampling_rules(profile)
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


def patch_model_preferences(conversation_id, outlet_id, request, user_id, tenant_id):
    from management.db.conversation.model_preferences import model_preferences
    from management.db.model.outlets import get_resolved_model_record
    from nexent.core.model_service.registry import model_service_references

    # Check conversation access before reading an outlet or validating its fields.
    read_model_preferences(conversation_id, user_id)
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
        merge_model_preferences(profile, updated)
        return updated

    return model_preferences(conversation_id, user_id, expected_version=request.expected_version,
        outlet_id=outlet_id, resolve_values=resolve)


def read_model_preference_view(conversation_id, outlet_id, user_id, tenant_id):
    from management.db.model.outlets import get_resolved_model_record
    from nexent.core.model_service.registry import model_service_references

    saved = read_model_preferences(conversation_id, user_id)
    profile = get_resolved_model_record(outlet_id, tenant_id, registered_references=model_service_references())
    if profile is None or profile.identity.model_type != "llm":
        raise ModelOutletValidationError("MODEL_OUTLET_NOT_AVAILABLE")
    profile = ensure_outlet_sampling_rules(profile)
    values = saved["model_parameter_preferences"].get(str(outlet_id), {})
    if isinstance(values, dict):
        values = without_outlet_token_limits(values)
    issues = []
    try:
        merge_model_preferences(profile, values)
    except ModelOutletValidationError as error:
        issues.append({"category": error.category, "field": error.path})
    return {"version": saved["version"], "parameter_values": values, "defaults": profile.parameter_values,
            "output_limit": profile.capabilities.context.output_limit,
            "field_specs": profile.parameter_rules, "config_revision": profile.config_revision, "issues": issues}


def validate_model_preferences(preferences, tenant_id, *, allowed_model_ids=None):
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
        merge_model_preferences(profile, values)


def patch_model_selection(conversation_id, request, user_id, tenant_id):
    """Both Agent chat modes save selection through the same ownership and CAS path."""
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
    return model_preferences(conversation_id, user_id, expected_version=request.expected_version,
        selected_model_id=request.selected_model_id)
