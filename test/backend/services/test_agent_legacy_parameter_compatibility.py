# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Historical Agent reasoning values must not block valid conversation controls."""

from copy import deepcopy

import pytest

from management.services.agent.model_parameters import merge_agent_model_parameters, merge_runtime_model_parameters
from nexent.core.model_service.compatibility.agent_parameters import read_agent_parameter_entry
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from test.sdk.core.model_service.conftest import protocol_profile  # noqa: F401


@pytest.fixture
def effort_profile(protocol_profile):
    data = protocol_profile.model_dump(mode="json")
    data["parameter_rules"] = [r for r in data["parameter_rules"] if r["key"] != "reasoning_budget_tokens"]
    data["parameter_rules"].append({
        "key": "reasoning_effort", "schema": {"type": "string", "enum": ["low", "medium", "high"]},
        "visible": True, "editable": True, "required": False, "allowed_scopes": ["outlet", "conversation"],
        "ui_group": "reasoning", "owner": "model", "source": {},
        "condition": {"key": "enable_thinking", "op": "eq", "value": True},
        "api_binding": {"path": "/reasoning_effort", "transform_ref": "identity_v1", "transform_version": 1},
    })
    data["parameter_values"] = {"enable_thinking": True, "reasoning_effort": "medium"}
    data["capabilities"]["reasoning"]["controls"] = [
        {"mode": "toggle", "parameter_key": "enable_thinking", "values": [False, True]},
        {"mode": "effort", "parameter_key": "reasoning_effort", "values": ["low", "medium", "high"]},
    ]
    return protocol_profile.__class__.model_validate(data)


def historical_entry():
    return {"extra_params": {"enable_thinking": True, "reasoning_effort": "auto",
                             "__custom__": {"enable_thinking": False}}}


@pytest.mark.parametrize("preferences", [{}, {"enable_thinking": True, "reasoning_effort": "low"},
                                         {"enable_thinking": False}])
def test_legacy_agent_allows_inheritance_low_and_disabled_without_mutating_saved_data(effort_profile, preferences):
    entry = historical_entry()
    before, outlet_before = deepcopy(entry), deepcopy(effort_profile.model_dump())
    resolved = merge_runtime_model_parameters(effort_profile, entry, preferences)
    enabled = preferences.get("enable_thinking", False)
    assert resolved.parameter_values["enable_thinking"] is enabled
    assert resolved.parameter_values.get("reasoning_effort") == ("low" if enabled else None)
    assert not resolved.extra_api_parameters
    assert entry == before and effort_profile.model_dump() == outlet_before


def test_legacy_auto_inherits_instead_of_becoming_an_explicit_provider_value(effort_profile):
    resolved = merge_agent_model_parameters(effort_profile, {"extra_params": {"reasoning_effort": "auto"}})
    assert resolved.parameter_values["reasoning_effort"] == "medium"


@pytest.mark.parametrize("entry", [
    {"parameter_values": {"reasoning_effort": "auto"}},
    {"parameter_values": {}, "custom_overrides": {"enable_thinking": False}},
    {"extra_params": {"reasoning_effort": "unsupported"}},
    {"extra_params": {"__custom__": {"messages": [], "api_key": "fixture-only"}}},
])
def test_current_values_and_unrecognized_or_protected_legacy_fields_remain_strict(effort_profile, entry):
    with pytest.raises(ParameterValidationError):
        merge_agent_model_parameters(effort_profile, entry)


def test_legacy_custom_known_value_keeps_its_original_precedence_and_validation(effort_profile):
    entry = {"extra_params": {"reasoning_effort": "high", "__custom__": {"reasoning_effort": "low"}}}
    assert merge_agent_model_parameters(effort_profile, entry).parameter_values["reasoning_effort"] == "low"
    entry["extra_params"]["__custom__"]["reasoning_effort"] = "invalid"
    with pytest.raises(ParameterValidationError):
        merge_agent_model_parameters(effort_profile, entry)


def test_normalization_is_idempotent_and_does_not_hide_invalid_canonical_values(effort_profile):
    current = read_agent_parameter_entry(historical_entry(), profile=effort_profile)
    assert current == {"parameter_values": {"enable_thinking": False}}
    assert read_agent_parameter_entry(current, profile=effort_profile) == current
    bad = {"parameter_values": {"reasoning_effort": "auto"}}
    assert read_agent_parameter_entry(bad, profile=effort_profile) == bad


def test_explicit_auto_is_preserved_when_the_outlet_declares_it(effort_profile):
    data = effort_profile.model_dump(mode="json")
    next(r for r in data["parameter_rules"] if r["key"] == "reasoning_effort")["schema"]["enum"].append("auto")
    data["capabilities"]["reasoning"]["controls"][1]["values"].append("auto")
    changed = effort_profile.__class__.model_validate(data)
    assert merge_agent_model_parameters(changed, {"extra_params": {"reasoning_effort": "auto"}}).parameter_values[
        "reasoning_effort"] == "auto"


def test_custom_without_a_declared_identity_binding_is_not_reinterpreted(effort_profile):
    data = effort_profile.model_dump(mode="json")
    next(r for r in data["parameter_rules"] if r["key"] == "enable_thinking")["api_binding"]["path"] = "/thinking/enabled"
    changed = effort_profile.__class__.model_validate(data)
    # It remains an ordinary custom body field, not an alias for /thinking/enabled.
    resolved = merge_agent_model_parameters(changed, {"extra_params": {"__custom__": {"enable_thinking": False}}})
    assert resolved.parameter_values["enable_thinking"] is True
    assert resolved.extra_api_parameters == [{"path": "/enable_thinking", "value": False}]


@pytest.fixture
def saved_effort_row(effort_profile):
    from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
    from nexent.core.model_service.registry import model_service_references

    data = effort_profile.model_dump(mode="json")
    data["outlet_id"] = data["connection"]["credential_ref"]["model_id"] = 42
    refs = model_service_references()
    for key in ("auth", "code_converter", "native_converter"):
        data["bindings"][key] = refs[key][0].model_dump(mode="json")
    return encode_resolved_model_profile(effort_profile.__class__.model_validate(data), registered_references=refs)


def test_read_and_explicit_save_share_legacy_conversion_without_rewriting_history(monkeypatch, saved_effort_row):
    from management.services.agent import read, reasoning

    old = {"model_ids": [42], "model_params_override": {"42": historical_entry()}}
    before = deepcopy(old)
    monkeypatch.setattr(read, "get_valid_model_ids", lambda ids, tenant: ids)
    monkeypatch.setattr(read, "resolve_model_record", lambda *args: saved_effort_row)
    monkeypatch.setattr(read, "is_model_configured", lambda record: True)
    monkeypatch.setattr(reasoning, "get_model_by_model_id", lambda *args, **kwargs: saved_effort_row)
    expected = {"42": {"parameter_values": {"enable_thinking": False}}}
    assert read.project_agent_models(old, "tenant", detail=True).fields["model_params_override"] == expected
    assert reasoning.snapshot_agent_reasoning_config([42], old["model_params_override"], None, "tenant") == expected
    assert old == before


def test_legacy_custom_bound_fields_cannot_bypass_fixed_outlet_policy(effort_profile):
    data = effort_profile.model_dump(mode="json")
    rule = next(r for r in data["parameter_rules"] if r["key"] == "enable_thinking")
    rule.update(editable=False, fixed_value=True)
    locked = effort_profile.__class__.model_validate(data)
    with pytest.raises(ParameterValidationError, match="FIXED_PARAMETER"):
        merge_agent_model_parameters(locked, {"extra_params": {"__custom__": {"enable_thinking": False}}})
