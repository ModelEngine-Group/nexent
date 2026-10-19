# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Apply explicit per-Agent values to an immutable saved model outlet."""

from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError


AGENT_PARAMETER_KEYS = (
    "temperature", "top_p", "top_k", "enable_thinking", "reasoning_effort", "reasoning_budget_tokens",
)


def merge_agent_model_parameters(profile, entry):
    """Preserve omitted defaults and legacy custom fields; never copy defaults into storage."""
    from nexent.core.model_service.compatibility.invocation_options import LegacyInvocationOptions

    if not isinstance(entry, dict):
        raise ParameterValidationError("PARAMETER_OBJECT_REQUIRED", "/model_params_override")
    extra = entry.get("extra_params") or {}
    if not isinstance(extra, dict):
        raise ParameterValidationError("PARAMETER_OBJECT_REQUIRED", "/extra_params")
    parameters = {key: entry[key] for key in AGENT_PARAMETER_KEYS if entry.get(key) is not None}
    parameters.update({key: value for key, value in extra.items()
                       if key in AGENT_PARAMETER_KEYS and value is not None})
    window = entry.get("context_window_tokens")
    if window is not None and (type(window) is not int or window <= 0):
        raise ParameterValidationError("PARAMETER_VALUE_INVALID", "/context_window_tokens")
    resolved = LegacyInvocationOptions(parameters, custom_overrides=extra.get("__custom__")).resolve(profile)
    reserve = resolved.parameter_values.get("max_output_tokens", profile.context_configuration.output_reserve_tokens)
    if window is not None and type(reserve) is int and window <= reserve:
        raise ParameterValidationError("PARAMETER_CONTEXT_TOO_SMALL", "/context_window_tokens")
    return resolved


def merge_runtime_model_parameters(profile, entry, preferences):
    """Merge all explicit layers before excluding inactive inherited reasoning values."""
    from services.conversation_model_preferences_service import merge_model_preferences

    if not isinstance(preferences, dict):
        from consts.exceptions import ModelOutletValidationError

        raise ModelOutletValidationError("CONVERSATION_PREFERENCES_INVALID")
    # Check the Agent layer even when a session happens to mask an invalid value.
    merge_agent_model_parameters(profile, entry)
    combined = dict(entry)
    extra = dict(entry.get("extra_params") or {})
    for key, value in preferences.items():
        if key in {"temperature", "top_p"}:
            combined[key] = value
            extra.pop(key, None)
        else:
            extra[key] = value
    combined["extra_params"] = extra
    resolved = merge_agent_model_parameters(profile, combined)
    # Validate the session's own scope and unknown fields, including values that
    # are identical to inherited fixed settings.
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
