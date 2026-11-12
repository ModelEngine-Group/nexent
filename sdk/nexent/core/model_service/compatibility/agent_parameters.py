# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read historical Agent entries once into the current override structure."""

from copy import deepcopy

from nexent.core.model_service.profiles.protocol_parameters import OUTLET_TOKEN_LIMIT_KEYS, without_outlet_token_limits

from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError


AGENT_PARAMETER_KEYS = (
    "temperature", "top_p", "top_k", "enable_thinking", "reasoning_effort", "reasoning_budget_tokens",
)


def read_agent_parameter_entry(entry, *, profile=None):
    """Current entries preserve explicit values; historical nulls meant inheritance."""
    if not isinstance(entry, dict):
        raise ParameterValidationError("PARAMETER_OBJECT_REQUIRED", "/model_params_override")
    if "parameter_values" in entry:
        if not isinstance(entry["parameter_values"], dict):
            raise ParameterValidationError("PARAMETER_OBJECT_REQUIRED", "/parameter_values")
        if any(key in entry for key in (*AGENT_PARAMETER_KEYS, "extra_params")):
            raise ParameterValidationError("PARAMETER_UPDATE_CONFLICT", "/model_params_override")
        result = deepcopy(entry)
        result["parameter_values"] = without_outlet_token_limits(result["parameter_values"])
        for key in OUTLET_TOKEN_LIMIT_KEYS:
            result.pop(key, None)
        if isinstance(result.get("custom_overrides"), dict):
            result["custom_overrides"] = without_outlet_token_limits(result["custom_overrides"])
        return result
    extra = entry.get("extra_params") or {}
    if not isinstance(extra, dict):
        raise ParameterValidationError("PARAMETER_OBJECT_REQUIRED", "/extra_params")
    values = {key: entry[key] for key in AGENT_PARAMETER_KEYS if entry.get(key) is not None}
    values.update({key: value for key, value in extra.items() if key in AGENT_PARAMETER_KEYS and value is not None})
    result = {key: deepcopy(value) for key, value in entry.items() if key not in (*AGENT_PARAMETER_KEYS, "extra_params", *OUTLET_TOKEN_LIMIT_KEYS)}
    result["parameter_values"] = values
    if "__custom__" in extra:
        result["custom_overrides"] = without_outlet_token_limits(deepcopy(extra["__custom__"])) if isinstance(extra["__custom__"], dict) else deepcopy(extra["__custom__"])
    if profile is not None:
        _normalize_legacy_parameters(result, profile)
    return result


def _normalize_legacy_parameters(entry, profile):
    """Interpret old omission and body aliases using the saved outlet only."""
    values = entry["parameter_values"]
    rules = {rule["key"]: rule for rule in profile.parameter_rules}
    effort = rules.get("reasoning_effort", {})
    controls = profile.capabilities.reasoning.controls or ()
    explicit_auto = "auto" in effort.get("schema", {}).get("enum", ()) or any(
        control.mode == "effort" and control.parameter_key == "reasoning_effort" and "auto" in control.values
        for control in controls
    )
    if values.get("reasoning_effort") == "auto" and not explicit_auto:
        # Historical selectors saved auto to mean inheritance, not a provider value.
        values.pop("reasoning_effort")
    custom = entry.get("custom_overrides")
    if not isinstance(custom, dict):
        return
    for key in AGENT_PARAMETER_KEYS:
        binding = rules.get(key, {}).get("api_binding") or {}
        if (key in custom and custom[key] is not None and binding.get("path") == "/" + key
                and binding.get("transform_ref") == "identity_v1" and binding.get("transform_version") == 1):
            # Legacy custom body fields had precedence over ordinary aliases.
            # Mapped values still pass the normal scope, domain and fixed-value checks.
            values[key] = custom.pop(key)
    if not custom:
        entry.pop("custom_overrides", None)
