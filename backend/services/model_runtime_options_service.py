# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compile legacy request options against a detached saved outlet."""

from copy import deepcopy


def compile_model_runtime_profile(model_config, agent_config):
    """Use saved rules only; never re-resolve a model name against the catalog."""
    from nexent.core.model_service.compatibility.invocation_options import (
        LegacyInvocationOptions,
    )
    from nexent.core.model_service.profiles.request_parameters import (
        apply_extra_api_parameters,
    )

    profile = model_config.resolved_profile
    if profile is None:
        raise ValueError("MODEL_OUTLET_PROVISIONING_REQUIRED")
    rules = {rule["key"]: rule for rule in profile.parameter_rules}
    extra = deepcopy(model_config.extra_body or {})
    submitted = {}
    fields = ("temperature", "top_p", "enable_thinking", "reasoning_effort", "reasoning_budget_tokens")
    for key in fields:
        value = getattr(model_config, key)
        if key == "enable_thinking" and value is False and key not in profile.parameter_values:
            # The legacy boolean default alone is not an explicit provider override.
            continue
        if key not in rules:
            if key == "reasoning_effort" and value == "auto":
                # Let the shared resolver interpret the legacy omission sentinel.
                submitted[key] = value
                continue
            if value is not None and (key not in {"enable_thinking"} or value is True):
                raise ValueError("MODEL_OUTLET_OVERRIDE_UNDECLARED")
            continue
        if value is not None or key in {"temperature", "top_p"}:
            if not rules[key].get("api_binding") and value != profile.parameter_values.get(key):
                raise ValueError("MODEL_OUTLET_OVERRIDE_UNBOUND")
            submitted[key] = value
    budget = agent_config.context_budget_snapshot
    output = budget.requested_output_tokens if budget else (
        agent_config.requested_output_tokens or model_config.default_output_reserve_tokens
        or model_config.max_output_tokens
    )
    if output is not None:
        submitted["max_tokens"] = output

    # Custom legacy API fields override ordinary aliases, but never a resolved
    # output budget. Interpret only saved bindings, without provider inference.
    for key, rule in rules.items():
        binding = rule.get("api_binding")
        if not binding:
            continue
        tokens = [token.replace("~1", "/").replace("~0", "~") for token in binding["path"].split("/")[1:]]
        parent = extra
        ancestors = []
        for token in tokens[:-1]:
            if isinstance(parent, dict):
                ancestors.append((parent, token))
            parent = parent.get(token) if isinstance(parent, dict) else None
        if not isinstance(parent, dict) or tokens[-1] not in parent:
            continue
        value = parent.pop(tokens[-1])
        for container, token in reversed(ancestors):
            if container.get(token) == {}:
                container.pop(token)
            else:
                break
        if binding["transform_ref"] == "thinking_toggle_v1":
            if value not in {"enabled", "disabled"}:
                raise ValueError("MODEL_OUTLET_THINKING_FORMAT_INVALID")
            value = value == "enabled"
        submitted[key] = value
    resolved = LegacyInvocationOptions(parameters=submitted).resolve(profile)

    for key in fields:
        extra.pop(key, None)

    def leaves(value, prefix=""):
        for key, child in value.items():
            path = prefix + "/" + key.replace("~", "~0").replace("/", "~1")
            if isinstance(child, dict) and child:
                yield from leaves(child, path)
            else:
                yield {"path": path, "value": child}

    extras = list(leaves(extra))
    apply_extra_api_parameters({}, extras,
        parameter_paths=[rule["api_binding"]["path"] for rule in rules.values() if rule.get("api_binding")],
        protected_paths=("/api_key", "/authorization", "/headers", "/credentials", "/base_url"))
    data = resolved.model_dump()
    data["extra_api_parameters"] = extras
    return type(profile).model_validate(data)
