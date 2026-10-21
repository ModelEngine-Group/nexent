# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Apply explicit per-Agent values to an immutable saved model outlet."""

from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.protocol_parameters import ensure_outlet_sampling_rules


def merge_agent_model_parameters(profile, entry):
    """Read a current/historical entry at the boundary, then apply canonical values."""
    from nexent.core.model_service.compatibility.agent_parameters import read_agent_parameter_entry
    return _apply_agent_parameters(profile, read_agent_parameter_entry(entry))


def _apply_agent_parameters(profile, entry):
    from nexent.core.model_service.profiles.parameter_rules import overlay_profile_parameters
    from nexent.core.model_service.profiles.request_parameters import overlay_extra_api_parameters

    window = entry.get("context_window_tokens")
    if window is not None and (type(window) is not int or window <= 0):
        raise ParameterValidationError("PARAMETER_VALUE_INVALID", "/context_window_tokens")
    resolved = overlay_profile_parameters(ensure_outlet_sampling_rules(profile), entry["parameter_values"], scope="outlet")
    if entry.get("custom_overrides") is not None:
        data = resolved.model_dump(mode="json")
        data["extra_api_parameters"] = overlay_extra_api_parameters(resolved, entry["custom_overrides"])
        resolved = resolved.__class__.model_validate(data)
    reserve = resolved.parameter_values.get("max_output_tokens", profile.context_configuration.output_reserve_tokens)
    if window is not None and type(reserve) is int and window <= reserve:
        raise ParameterValidationError("PARAMETER_CONTEXT_TOO_SMALL", "/context_window_tokens")
    return resolved


def merge_runtime_model_parameters(profile, entry, preferences):
    """Validate each explicit layer, then merge without any legacy-format round trip."""
    from nexent.core.model_service.compatibility.agent_parameters import read_agent_parameter_entry
    from services.conversation_model_preferences_service import merge_model_preferences

    if not isinstance(preferences, dict):
        from consts.exceptions import ModelOutletValidationError
        raise ModelOutletValidationError("CONVERSATION_PREFERENCES_INVALID")
    canonical = read_agent_parameter_entry(entry)
    _apply_agent_parameters(profile, canonical)
    combined = {**canonical, "parameter_values": {**canonical["parameter_values"], **preferences}}
    try:
        resolved = _apply_agent_parameters(profile, combined)
    except ParameterValidationError as error:
        from consts.exceptions import ModelOutletValidationError
        raise ModelOutletValidationError(error.category, error.path) from None
    return merge_model_preferences(resolved, preferences)


def bind_agent_model_profiles(model_list, root_config, root_info, load_agent_info):
    """Give each Agent's selected outlet an independent parameter view."""
    from copy import deepcopy
    from uuid import uuid4

    from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile

    originals = {model.cite_name: model for model in model_list}

    def bind(config, info=None):
        model = originals.get(config.model_name)
        profile = getattr(model, "resolved_profile", None)
        if isinstance(profile, ResolvedModelProfile):
            if info is None:
                info = load_agent_info(config.agent_id, config.version_no)
            entry = ((info or {}).get("model_params_override") or {}).get(str(profile.outlet_id))
            if entry:
                resolved = merge_agent_model_parameters(profile, entry)
                private = deepcopy(model)
                private.cite_name = "agent_model_" + uuid4().hex
                private.resolved_profile = resolved
                for key in ("temperature", "top_p", "enable_thinking", "reasoning_effort", "reasoning_budget_tokens"):
                    value = resolved.parameter_values.get(key)
                    setattr(private, key, value is True if key == "enable_thinking" else value)
                if entry.get("context_window_tokens") is not None:
                    private.context_window_tokens = entry["context_window_tokens"]
                model_list.append(private)
                config.model_name = private.cite_name
        for child in getattr(config, "worker_agents", []):
            bind(child)

    bind(root_config, root_info)
