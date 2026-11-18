# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Apply Agent and conversation values to an immutable saved model profile."""

from nexent.core.model_service.compatibility.agent_parameters import read_agent_parameter_entry
from nexent.core.model_service.profiles.outlet_controls import ensure_outlet_parameter_rules
from nexent.core.model_service.profiles.parameter_rules import overlay_profile_parameters
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.protocol_parameters import without_outlet_token_limits
from nexent.core.model_service.profiles.request_parameters import overlay_extra_api_parameters


def _apply_agent_parameters(profile, canonical):
    resolved = overlay_profile_parameters(
        profile, canonical["parameter_values"], scope="outlet",
    )
    if canonical.get("custom_overrides") is not None:
        data = resolved.model_dump(mode="json")
        data["extra_api_parameters"] = overlay_extra_api_parameters(resolved, canonical["custom_overrides"])
        resolved = resolved.__class__.model_validate(data)
    return resolved


def merge_agent_parameters(profile, entry):
    profile = ensure_outlet_parameter_rules(profile)
    return _apply_agent_parameters(profile, read_agent_parameter_entry(entry, profile=profile))


def merge_conversation_parameters(profile, preferences):
    if not isinstance(preferences, dict):
        raise ParameterValidationError("CONVERSATION_PREFERENCES_INVALID")
    profile = ensure_outlet_parameter_rules(profile)
    resolved = overlay_profile_parameters(profile, without_outlet_token_limits(preferences), scope="conversation")
    output = resolved.parameter_values.get("max_output_tokens", resolved.parameter_values.get("max_tokens"))
    context = profile.capabilities.context
    limits = [value for value in (context.output_limit, context.combined_window) if value is not None]
    if type(output) is int and limits and output > min(limits):
        raise ParameterValidationError("PARAMETER_LIMIT_EXCEEDED", "/max_output_tokens")
    return resolved


def merge_runtime_parameters(profile, entry, preferences):
    if not isinstance(preferences, dict):
        raise ParameterValidationError("CONVERSATION_PREFERENCES_INVALID")
    profile = ensure_outlet_parameter_rules(profile)
    canonical = read_agent_parameter_entry(entry, profile=profile)
    preferences = without_outlet_token_limits(preferences)
    session = merge_conversation_parameters(_apply_agent_parameters(profile, canonical), preferences)
    inherited = {key: value for key, value in canonical["parameter_values"].items()
                 if key in session.parameter_values}
    return _apply_agent_parameters(profile, {
        **canonical, "parameter_values": {**inherited, **preferences},
    })
