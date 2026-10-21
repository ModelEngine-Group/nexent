# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Fallback request declarations for the registered OpenAI chat protocol."""


def openai_chat_parameter_rules():
    """Declare wire fields without assigning provider capability or request defaults."""
    fields = {
        "temperature": ({"type": ["number", "null"]}, "/temperature", True),
        "top_p": ({"type": ["number", "null"], "minimum": 0, "maximum": 1}, "/top_p", True),
        "max_output_tokens": ({"type": "integer", "minimum": 1}, "/max_tokens", True),
        "stop": ({"type": ["string", "array"], "items": {"type": "string"}}, "/stop", False),
        "response_format": ({"type": "object"}, "/response_format", False),
    }
    return [{"key": key, "schema": schema, "visible": visible, "editable": True, "required": False,
        "allowed_scopes": ["outlet", "conversation"] if visible else ["outlet"],
        "ui_group": "advanced" if visible else "runtime", "owner": "provider",
        "source": {"ref": "openai_chat_protocol_parameters_v2", "version": 2},
        "api_binding": {"path": path, "transform_ref": "identity_v1", "transform_version": 1}}
        for key, (schema, path, visible) in fields.items()]


def ensure_outlet_sampling_rules(profile):
    """Add only registered sampling declarations for older outlet or session edits."""
    if profile.bindings.protocol.ref != "openai_chat_completions":
        return profile
    from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile

    data = profile.model_dump(mode="json")
    # Upgrade only the known v1 protocol UI restriction. Model/provider rules,
    # fixed values, schema bounds and wire bindings remain authoritative.
    for rule in data["parameter_rules"]:
        if (rule["key"] in {"temperature", "top_p"}
                and rule.get("source") == {"ref": "openai_chat_protocol_parameters_v1", "version": 1}
                and rule.get("editable") is True and "fixed_value" not in rule
                and rule.get("api_binding") == {"path": "/" + rule["key"],
                    "transform_ref": "identity_v1", "transform_version": 1}):
            rule["visible"] = True
            rule["allowed_scopes"] = list(dict.fromkeys([*rule["allowed_scopes"], "conversation"]))
            rule["source"] = {"ref": "openai_chat_protocol_parameters_v2", "version": 2}
    keys = {rule["key"] for rule in data["parameter_rules"]}
    data["parameter_rules"].extend(rule for rule in openai_chat_parameter_rules()
                                   if rule["key"] in {"temperature", "top_p"} and rule["key"] not in keys)
    return ResolvedModelProfile.model_validate(data)
