# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Apply explicit per-Agent values to an immutable saved model outlet."""

from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.outlet_controls import ensure_outlet_parameter_rules


def merge_agent_model_parameters(profile, entry):
    from nexent.core.model_service.profiles.runtime_parameters import merge_agent_parameters

    return merge_agent_parameters(profile, entry)


def _apply_agent_parameters(profile, entry):
    from nexent.core.model_service.profiles.parameter_rules import overlay_profile_parameters
    from nexent.core.model_service.profiles.request_parameters import overlay_extra_api_parameters

    resolved = overlay_profile_parameters(ensure_outlet_parameter_rules(profile), entry["parameter_values"], scope="outlet")
    if entry.get("custom_overrides") is not None:
        data = resolved.model_dump(mode="json")
        data["extra_api_parameters"] = overlay_extra_api_parameters(resolved, entry["custom_overrides"])
        resolved = resolved.__class__.model_validate(data)
    return resolved


def merge_runtime_model_parameters(profile, entry, preferences):
    from contracts.errors.exceptions import ModelOutletValidationError
    from nexent.core.model_service.profiles.runtime_parameters import merge_agent_parameters, merge_runtime_parameters

    merge_agent_parameters(profile, entry)
    try:
        return merge_runtime_parameters(profile, entry, preferences)
    except ParameterValidationError as error:
        raise ModelOutletValidationError(error.category, error.path) from None


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
                model_list.append(private)
                config.model_name = private.cite_name
        for child in getattr(config, "worker_agents", []):
            bind(child)

    bind(root_config, root_info)
