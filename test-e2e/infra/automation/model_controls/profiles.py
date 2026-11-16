# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Frozen, synthetic profile fixtures for the shared conversation-control contract."""

from management.services.model.outlet_migration import build_legacy_outlet_snapshot
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile


def frozen_fixture_profile(record, capability):
    profile = build_legacy_outlet_snapshot(record, legacy_capability=capability, migrated_at="fixture")
    data = profile.model_dump(mode="json")
    budget = capability.get("control") == "budget_tokens"
    supported = capability.get("status") == "supported"
    fields = [
        ("temperature", {"type": ["number", "null"], "minimum": 0, "maximum": 2}, "/temperature"),
        ("top_p", {"type": ["number", "null"], "minimum": 0, "maximum": 1}, "/top_p"),
        ("enable_thinking", {"type": "boolean", **({"const": False} if not supported else {})}, "/enable_thinking"),
    ]
    if supported:
        fields.append(("reasoning_budget_tokens", {"type": "integer", "minimum": 1024, "maximum": 8192}, "/thinking_budget") if budget else
                      ("reasoning_effort", {"type": "string", "enum": capability["levels"]}, "/reasoning_effort"))
    replaced = {key for key, _, _ in fields} | {"reasoning_effort", "reasoning_budget_tokens"}
    data["parameter_rules"] = [rule for rule in data["parameter_rules"] if rule["key"] not in replaced]
    for key, schema, path in fields:
        rule = {"key": key, "schema": schema, "visible": True, "editable": True, "required": False,
                "allowed_scopes": ["outlet", "conversation"], "ui_group": "fixture",
                "owner": "combination", "source": {"rule_id": "conversation-profile-fixture"},
                "api_binding": {"path": path, "transform_ref": "identity_v1", "transform_version": 1}}
        if key.startswith("reasoning_"):
            rule["condition"] = {"key": "enable_thinking", "op": "eq", "value": True}
        data["parameter_rules"].append(rule)
    data["parameter_values"].pop("reasoning_effort" if budget else "reasoning_budget_tokens", None)
    if not supported:
        data["parameter_values"].update(enable_thinking=False)
        data["parameter_values"].pop("reasoning_effort", None)
        data["parameter_values"].pop("reasoning_budget_tokens", None)
    data["capabilities"]["reasoning"] = {"status": "supported" if supported else "unsupported", "controls":
        ([{"mode": "toggle", "parameter_key": "enable_thinking", "values": [False, True]},
          {"mode": "budget_tokens", "parameter_key": "reasoning_budget_tokens", "min": 1024, "max": 8192, "special_values": []}
          if budget else {"mode": "effort", "parameter_key": "reasoning_effort", "values": capability["levels"]}]
         if supported else None), "response_paths": []}
    return ResolvedModelProfile.model_validate(data)


def preference_values(generation):
    """Fixture intent only; product requests always carry canonical parameter names."""
    values = {key: value for key, value in (generation or {}).items() if value is not None}
    if "deep_thinking" in values:
        values["enable_thinking"] = values.pop("deep_thinking")
    effort = values.pop("thinking_effort", None)
    if effort not in (None, "auto"):
        values["reasoning_effort"] = effort
    if values.get("reasoning_budget_tokens") == 0:
        values.pop("reasoning_budget_tokens")
    if values.get("enable_thinking") is False:
        values.pop("reasoning_effort", None)
        values.pop("reasoning_budget_tokens", None)
    return values
