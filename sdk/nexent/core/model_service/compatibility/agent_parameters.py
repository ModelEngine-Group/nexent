# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read historical Agent entries once into the current override structure."""

from copy import deepcopy

from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError


AGENT_PARAMETER_KEYS = (
    "temperature", "top_p", "top_k", "enable_thinking", "reasoning_effort", "reasoning_budget_tokens",
)


def read_agent_parameter_entry(entry):
    """Current entries preserve explicit values; historical nulls meant inheritance."""
    if not isinstance(entry, dict):
        raise ParameterValidationError("PARAMETER_OBJECT_REQUIRED", "/model_params_override")
    if "parameter_values" in entry:
        if not isinstance(entry["parameter_values"], dict):
            raise ParameterValidationError("PARAMETER_OBJECT_REQUIRED", "/parameter_values")
        if any(key in entry for key in (*AGENT_PARAMETER_KEYS, "extra_params")):
            raise ParameterValidationError("PARAMETER_UPDATE_CONFLICT", "/model_params_override")
        return deepcopy(entry)
    extra = entry.get("extra_params") or {}
    if not isinstance(extra, dict):
        raise ParameterValidationError("PARAMETER_OBJECT_REQUIRED", "/extra_params")
    values = {key: entry[key] for key in AGENT_PARAMETER_KEYS if entry.get(key) is not None}
    values.update({key: value for key, value in extra.items() if key in AGENT_PARAMETER_KEYS and value is not None})
    result = {key: deepcopy(value) for key, value in entry.items() if key not in (*AGENT_PARAMETER_KEYS, "extra_params")}
    result["parameter_values"] = values
    if "__custom__" in extra:
        result["custom_overrides"] = deepcopy(extra["__custom__"])
    return result
