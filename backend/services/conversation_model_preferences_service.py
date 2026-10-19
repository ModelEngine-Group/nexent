# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Conversation-only parameter patches validated against frozen outlet rules."""

from consts.exceptions import ModelOutletValidationError
from nexent.core.model_service.profiles.parameter_rules import (
    compile_parameter_rules,
    overlay_saved_parameter_values,
)
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError


def merge_model_preferences(profile, preferences):
    """Do not discard invalid stored choices or apply creation defaults during a run."""
    if not isinstance(preferences, dict):
        raise ModelOutletValidationError("CONVERSATION_PREFERENCES_INVALID")
    try:
        inherited = dict(profile.parameter_values)
        # Turning thinking off excludes inherited effort/budget, while an explicitly
        # contradictory user choice remains a validation error.
        if preferences.get("enable_thinking") is False:
            for rule in profile.parameter_rules:
                if (rule.get("condition") == {"key": "enable_thinking", "op": "eq", "value": True}
                        and rule["key"] not in preferences):
                    inherited.pop(rule["key"], None)
        values = overlay_saved_parameter_values(compile_parameter_rules(profile.parameter_rules), preferences,
            scope="conversation", saved_values=inherited)
        output = values.get("max_output_tokens", values.get("max_tokens"))
        context = profile.capabilities.context
        limits = [value for value in (context.output_limit, context.combined_window) if value is not None]
        if type(output) is int and limits and output > min(limits):
            raise ModelOutletValidationError("PARAMETER_LIMIT_EXCEEDED", "/max_output_tokens")
        data = profile.model_dump(mode="json")
        data["parameter_values"] = values
        return profile.__class__.model_validate(data)
    except ParameterValidationError as error:
        raise ModelOutletValidationError(error.category, error.path) from None


def read_model_preferences(conversation_id, user_id):
    from database.conversation_model_preferences_db import model_preferences

    return model_preferences(conversation_id, user_id)


def patch_model_preferences(conversation_id, outlet_id, request, user_id, tenant_id):
    from database.conversation_model_preferences_db import model_preferences
    from database.model_outlet_db import get_resolved_model_record
    from nexent.core.model_service.registry import model_service_references

    # Check conversation access before reading an outlet or validating its fields.
    read_model_preferences(conversation_id, user_id)
    profile = get_resolved_model_record(outlet_id, tenant_id, registered_references=model_service_references())
    if profile is None or profile.identity.model_type != "llm":
        raise ModelOutletValidationError("MODEL_OUTLET_NOT_AVAILABLE")
    deleted = request.delete_parameters
    if len(deleted) != len(set(deleted)) or set(deleted) & request.parameter_values.keys():
        raise ModelOutletValidationError("PARAMETER_UPDATE_CONFLICT")

    def resolve(saved):
        if not isinstance(saved, dict):
            raise ModelOutletValidationError("CONVERSATION_PREFERENCES_INVALID")
        updated = dict(saved)
        for key in deleted:
            updated.pop(key, None)
        updated.update(request.parameter_values)
        merge_model_preferences(profile, updated)
        return updated

    return model_preferences(conversation_id, user_id, expected_version=request.expected_version,
        outlet_id=outlet_id, resolve_values=resolve)


def read_model_preference_view(conversation_id, outlet_id, user_id, tenant_id):
    from database.model_outlet_db import get_resolved_model_record
    from nexent.core.model_service.registry import model_service_references

    saved = read_model_preferences(conversation_id, user_id)
    profile = get_resolved_model_record(outlet_id, tenant_id, registered_references=model_service_references())
    if profile is None or profile.identity.model_type != "llm":
        raise ModelOutletValidationError("MODEL_OUTLET_NOT_AVAILABLE")
    values = saved["model_parameter_preferences"].get(str(outlet_id), {})
    issues = []
    try:
        merge_model_preferences(profile, values)
    except ModelOutletValidationError as error:
        issues.append({"category": error.category, "field": error.path})
    return {"version": saved["version"], "parameter_values": values, "defaults": profile.parameter_values,
            "field_specs": profile.parameter_rules, "config_revision": profile.config_revision, "issues": issues}
