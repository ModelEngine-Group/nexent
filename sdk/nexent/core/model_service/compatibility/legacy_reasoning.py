# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Export historical request fields using the existing legacy translation methods."""

from copy import deepcopy

from nexent.core.models.openai_llm import OpenAIModel


class LegacyReasoningPolicy:
    """Share only pure translation methods, without constructing a model or client."""

    _reasoning_wire_profile = OpenAIModel._reasoning_wire_profile
    _base_reasoning_wire_profile = OpenAIModel._base_reasoning_wire_profile
    _translate_thinking_flag = OpenAIModel._translate_thinking_flag
    _apply_reasoning_control = OpenAIModel._apply_reasoning_control


def legacy_reasoning_wire_parameters(*, model_id, base_url, model_factory, capability=None,
                                     effort=None, budget=None, extra_body=None):
    """Export actual legacy body fields without allocating a client or sending a request."""
    policy = LegacyReasoningPolicy()
    policy.model_id = model_id
    policy.api_base_url = base_url
    policy.model_factory = (model_factory or "").lower()
    policy.reasoning_capability = deepcopy(capability)
    policy.reasoning_effort = effort
    policy.reasoning_budget_tokens = budget
    parameters = {}
    if extra_body:
        parameters["extra_body"] = policy._translate_thinking_flag(deepcopy(extra_body))
    policy._apply_reasoning_control(parameters)
    body = parameters.pop("extra_body", {})
    # The OpenAI SDK merges extra_body over ordinary completion parameters.
    return deepcopy({**parameters, **body})
