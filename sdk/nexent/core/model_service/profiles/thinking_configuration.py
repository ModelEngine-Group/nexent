# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Finite operator-selected thinking switch bindings; never infer them from model names."""

from copy import deepcopy

from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile


THINKING_FORMATS = {
    "enable_thinking": ("/enable_thinking", "identity_v1"),
    "thinking_type": ("/thinking/type", "thinking_toggle_v1"),
    "chat_template": ("/chat_template_kwargs/enable_thinking", "identity_v1"),
}


def configure_thinking(profile, preset):
    """Apply a declared operator format while retaining the frozen original for reset."""
    if preset is None:
        return profile
    if preset != "profile_default" and preset not in THINKING_FORMATS:
        raise ParameterValidationError("THINKING_FORMAT_UNKNOWN", "/thinking_control")
    data = profile.model_dump(mode="json")
    metadata = data["provenance"]["provider_metadata"]
    reasoning = data["capabilities"]["reasoning"]
    saved = metadata.get("operator_thinking")
    if saved is None and preset == "profile_default":
        return profile
    if saved is None:
        saved = {"original_rule_index": next((index for index, rule in enumerate(data["parameter_rules"]) if rule["key"] == "enable_thinking"), len(data["parameter_rules"])),
                 "original_rule": next((deepcopy(rule) for rule in data["parameter_rules"]
                                       if rule["key"] == "enable_thinking"), None),
                 "original_status": reasoning["status"], "original_controls": deepcopy(reasoning.get("controls"))}
    data["provenance"]["overrides"] = [item for item in data["provenance"]["overrides"]
                                            if item["source"] != "operator_thinking_v1"]
    data["parameter_rules"] = [rule for rule in data["parameter_rules"] if rule["key"] != "enable_thinking"]
    if preset == "profile_default":
        if saved["original_rule"] is not None:
            data["parameter_rules"].insert(saved.get("original_rule_index", len(data["parameter_rules"])), saved["original_rule"])
        else:
            data["parameter_values"].pop("enable_thinking", None)
        reasoning.update(status=saved["original_status"], controls=saved["original_controls"])
        metadata.pop("operator_thinking", None)
    else:
        path, transform = THINKING_FORMATS[preset]
        rule = deepcopy(saved["original_rule"]) if saved["original_rule"] is not None else {
            "key": "enable_thinking", "schema": {"type": "boolean"}, "visible": True,
            "editable": True, "required": False, "allowed_scopes": ["outlet", "conversation"],
            "ui_group": "reasoning", "owner": "combination",
        }
        rule["source"] = {"ref": "operator_thinking_v1", "version": 1, "preset": preset}
        rule["api_binding"] = {"path": path, "transform_ref": transform, "transform_version": 1}
        data["parameter_rules"].insert(saved.get("original_rule_index", len(data["parameter_rules"])), rule)
        controls = [control for control in reasoning.get("controls") or [] if control["mode"] != "toggle"]
        toggle_values = next((control["values"] for control in saved["original_controls"] or [] if control["mode"] == "toggle"), [False, True])
        reasoning.update(status="supported", controls=[{"mode": "toggle", "parameter_key": "enable_thinking", "values": toggle_values}, *controls])
        metadata["operator_thinking"] = {**saved, "preset": preset, "version": 1}
        data["provenance"]["overrides"].append({"path": "/reasoning/controls", "source": "operator_thinking_v1",
            "original_value": saved["original_controls"], "reason": "User explicitly selected a registered thinking field format",
            "evidence": "operator_thinking_v1:" + preset})
    return ResolvedModelProfile.model_validate(data)


def configure_thinking_degree(profile, mode):
    """Register an operator-selected degree preset, preserving declared wire mappings."""
    if mode is None:
        return profile
    if mode not in {"default", "effort", "budget_tokens"}:
        raise ParameterValidationError("THINKING_MODE_UNKNOWN", "/thinking_mode")
    data = profile.model_dump(mode="json")
    metadata = data["provenance"]["provider_metadata"]
    reasoning = data["capabilities"]["reasoning"]
    keys = {"reasoning_effort", "reasoning_budget_tokens"}
    saved = metadata.get("operator_thinking_degree")
    if saved is None:
        saved = {
            "rules": [{"index": i, "rule": deepcopy(rule)}
                      for i, rule in enumerate(data["parameter_rules"]) if rule["key"] in keys],
            "controls": [deepcopy(control) for control in reasoning.get("controls") or []
                         if control["mode"] in {"effort", "budget_tokens"}],
            "status": reasoning["status"],
        }
    original_keys = {item["rule"]["key"] for item in saved["rules"]}
    for key in keys - original_keys:
        data["parameter_values"].pop(key, None)
    data["parameter_rules"] = [rule for rule in data["parameter_rules"] if rule["key"] not in keys]
    for original in saved["rules"]:
        data["parameter_rules"].insert(original["index"], deepcopy(original["rule"]))
    controls = [control for control in reasoning.get("controls") or []
                if control["mode"] not in {"effort", "budget_tokens"}]
    controls.extend(deepcopy(saved["controls"]))
    reasoning["controls"] = controls or None
    data["provenance"]["overrides"] = [item for item in data["provenance"]["overrides"]
                                        if item["source"] != "operator_thinking_degree_v1"]
    if mode == "default":
        original_keys = {item["rule"]["key"] for item in saved["rules"]}
        for key in keys - original_keys:
            data["parameter_values"].pop(key, None)
        if "operator_thinking" not in metadata:
            reasoning["status"] = saved["status"]
        metadata["operator_thinking_degree"] = {**saved, "mode": "default", "version": 1}
        return ResolvedModelProfile.model_validate(data)

    key = "reasoning_effort" if mode == "effort" else "reasoning_budget_tokens"
    opposite = "reasoning_budget_tokens" if mode == "effort" else "reasoning_effort"
    if opposite in data["parameter_values"]:
        original = next((item["rule"] for item in saved["rules"] if item["rule"]["key"] == opposite), None)
        if original and (not original["editable"] or original["required"]):
            raise ParameterValidationError("FIXED_PARAMETER", "/" + opposite)
        data["parameter_values"].pop(opposite)
    existing = next((rule for rule in data["parameter_rules"] if rule["key"] == key), None)
    # A pinned provider binding and its fixed domain always win over generic presets.
    if existing is None or not existing.get("api_binding"):
        control = next((control for control in controls if control["mode"] == mode), None)
        if mode == "effort":
            values = control["values"] if control else ["low", "medium", "high"]
            schema = {"type": ["string", "null"] if None in values else "string", "enum": values}
            control = {"mode": mode, "parameter_key": key, "values": values}
            path = "/reasoning_effort"
        else:
            schema = {"type": "integer"}
            if control:
                if control.get("min") is not None:
                    schema["minimum"] = control["min"]
                if control.get("max") is not None:
                    schema["maximum"] = control["max"]
            else:
                schema["minimum"] = 1
            control = control or {"mode": mode, "parameter_key": key, "min": 1}
            path = "/thinking_budget"
        rule = {"key": key, "schema": schema, "visible": True, "editable": True,
                "required": False, "allowed_scopes": ["outlet", "conversation"],
                "ui_group": "reasoning", "owner": "combination",
                "source": {"ref": "operator_thinking_degree_v1", "version": 1, "preset": mode},
                "condition": {"key": "enable_thinking", "op": "eq", "value": True},
                "api_binding": {"path": path, "transform_ref": "identity_v1", "transform_version": 1}}
        data["parameter_rules"] = [item for item in data["parameter_rules"] if item["key"] != key] + [rule]
        reasoning["controls"] = [item for item in controls if item["mode"] != mode] + [control]
    reasoning["status"] = "supported"
    metadata["operator_thinking_degree"] = {**saved, "mode": mode, "version": 1}
    data["provenance"]["overrides"].append({
        "path": "/reasoning/controls", "source": "operator_thinking_degree_v1",
        "original_value": saved["controls"], "reason": "User selected a registered thinking degree preset",
        "evidence": "operator_thinking_degree_v1:" + mode})
    return ResolvedModelProfile.model_validate(data)


def configure_outlet_policy(profile, *, thinking_control=None, thinking_mode=None, has_credential=None):
    """Apply the same finite allowed policy changes in services and persistence guards."""
    from nexent.core.model_service.profiles.protocol_parameters import ensure_outlet_sampling_rules

    result = configure_thinking_degree(configure_thinking(ensure_outlet_sampling_rules(profile), thinking_control), thinking_mode)
    if has_credential is not None:
        data = result.model_dump(mode="json")
        data["bindings"]["auth"] = {"ref": "bearer_token_v1" if has_credential else "no_auth_v1", "version": 1}
        kind = "model_record" if has_credential else "none"
        data["connection"]["credential_ref"]["kind"] = kind
        data["connection_rules"]["credential_kind"] = kind
        result = ResolvedModelProfile.model_validate(data)
    return result
