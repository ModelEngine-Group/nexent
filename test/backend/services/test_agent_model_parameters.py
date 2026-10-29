# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AC-PARAM-LAYERS: explicit Agent overrides sit between outlet and session values."""

from copy import deepcopy

import pytest
from contracts.errors.exceptions import ModelOutletValidationError
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from management.services.agent.model_parameters import merge_agent_model_parameters
from management.services.conversation.model_preferences import merge_model_preferences
from management.services.model.profiles import build_outlet_draft
from test.backend.services.test_model_profile_service import draft_request


@pytest.fixture
def profile():
    value, _ = build_outlet_draft(draft_request(parameter_values={"enable_thinking": True,
        "reasoning_budget_tokens": 64, "temperature": 0.8, "max_output_tokens": 2048}), "tenant")
    return value


def test_session_overrides_agent_then_outlet_and_clearing_restores_inheritance(profile):
    original = deepcopy(profile.model_dump())
    agent = merge_agent_model_parameters(profile, {"temperature": 0.4})
    assert agent.parameter_values["temperature"] == 0.4
    assert agent.parameter_values["reasoning_budget_tokens"] == 64
    assert merge_model_preferences(agent, {"temperature": 0}).parameter_values["temperature"] == 0
    assert merge_model_preferences(agent, {}).parameter_values["temperature"] == 0.4
    assert merge_agent_model_parameters(profile, {}).parameter_values["temperature"] == 0.8
    assert profile.model_dump() == original


def test_agent_false_and_top_k_reach_the_profile_without_changing_outlet(profile):
    data = profile.model_dump()
    data["parameter_rules"].append({"key": "top_k", "schema": {"type": "integer", "minimum": 0},
        "visible": True, "editable": True, "required": False, "allowed_scopes": ["outlet", "conversation"],
        "ui_group": "sampling", "owner": "model", "source": {}, "api_binding": {"path": "/top_k", "transform_ref": "identity_v1", "transform_version": 1}})
    profile = profile.__class__.model_validate(data)
    agent = merge_agent_model_parameters(profile, {"extra_params": {"top_k": 0, "enable_thinking": False}})
    assert agent.parameter_values["top_k"] == 0
    assert agent.parameter_values["enable_thinking"] is False
    assert "reasoning_budget_tokens" not in agent.parameter_values
    assert profile.parameter_values["enable_thinking"] is True


@pytest.mark.parametrize("entry", [{"temperature": "invalid"}, {"extra_params": [1]}, {"extra_params": {"top_k": 5}}])
def test_invalid_agent_configuration_is_rejected(profile, entry):
    with pytest.raises(ParameterValidationError):
        merge_agent_model_parameters(profile, entry)


def test_session_reenables_thinking_with_the_inherited_outlet_budget(profile):
    from management.services.agent.model_parameters import merge_runtime_model_parameters

    result = merge_runtime_model_parameters(profile, {"extra_params": {"enable_thinking": False}},
                                            {"enable_thinking": True})
    assert result.parameter_values["enable_thinking"] is True
    assert result.parameter_values["reasoning_budget_tokens"] == 64
    assert merge_runtime_model_parameters(profile, {}, {"context_window_tokens":100}).parameter_values == result.parameter_values


def test_parent_and_child_keep_their_own_override_when_sharing_one_outlet(profile):
    from types import SimpleNamespace
    from management.services.agent.model_parameters import bind_agent_model_profiles

    data = profile.model_dump()
    data["outlet_id"] = 42
    data["connection"]["credential_ref"]["model_id"] = 42
    profile = profile.__class__.model_validate(data)
    base = SimpleNamespace(cite_name="shared", resolved_profile=profile)
    child = SimpleNamespace(agent_id=2, version_no=3, model_name="shared", worker_agents=[])
    root = SimpleNamespace(agent_id=1, version_no=0, model_name="shared", worker_agents=[child])
    configs = [base]
    bind_agent_model_profiles(configs, root, {"model_params_override":{"42":{"temperature":0.4}}},
        lambda agent_id,version: {"model_params_override":{"42":{"temperature":0.2}}})
    by_name = {item.cite_name:item for item in configs}
    assert root.model_name != child.model_name
    assert by_name[root.model_name].resolved_profile.parameter_values["temperature"] == 0.4
    assert by_name[child.model_name].resolved_profile.parameter_values["temperature"] == 0.2
    assert base.resolved_profile.parameter_values["temperature"] == 0.8


def test_old_outlet_session_sampling_uses_registered_rules_without_recomposing(profile, monkeypatch):
    """UI-SESSION-15: only missing protocol declarations are added, never persisted."""
    from management.services.agent.model_parameters import merge_runtime_model_parameters
    from management.services.model import profiles as model_profile_service
    data = profile.model_dump(mode="json")
    data["parameter_rules"] = [rule for rule in data["parameter_rules"] if rule["key"] not in {"temperature", "top_p"}]
    for key in ("temperature", "top_p"):
        data["parameter_values"].pop(key, None)
    old = profile.__class__.model_validate(data)
    before = old.model_dump()
    monkeypatch.setattr(model_profile_service, "get_model_profile_catalog", lambda: pytest.fail("must not recompose TOML"))
    result = merge_runtime_model_parameters(old, {"temperature": 0.5}, {"temperature": 0.23, "top_p": 0.79})
    assert result.parameter_values["temperature"] == 0.23
    assert result.parameter_values["top_p"] == 0.79
    assert result.capabilities == old.capabilities
    assert old.model_dump() == before
    with pytest.raises(ModelOutletValidationError):
        merge_model_preferences(old, {"unregistered_sampling": 1})


def test_old_protocol_v1_visibility_is_normalized_without_relaxing_model_rules(profile):
    """UI-SESSION-15: preserve non-protocol visibility and fixed restrictions."""
    from nexent.core.model_service.profiles.protocol_parameters import ensure_outlet_sampling_rules
    from management.services.agent.model_parameters import merge_runtime_model_parameters
    data = profile.model_dump(mode="json")
    rule = next(item for item in data["parameter_rules"] if item["key"] == "temperature")
    rule.update(source={"ref": "openai_chat_protocol_parameters_v1", "version": 1}, visible=False, allowed_scopes=["outlet"])
    old = profile.__class__.model_validate(data)
    result = merge_runtime_model_parameters(old, {}, {"temperature": 0.23})
    normalized = next(item for item in result.parameter_rules if item["key"] == "temperature")
    assert normalized["visible"] and "conversation" in normalized["allowed_scopes"]
    assert result.parameter_values["temperature"] == 0.23
    assert old.parameter_rules != result.parameter_rules
    rule["source"] = {"ref": "custom_model", "version": 1}
    custom = profile.__class__.model_validate(data)
    normalized = ensure_outlet_sampling_rules(custom)
    assert next(r for r in normalized.parameter_rules if r["key"] == "temperature") == next(r for r in custom.parameter_rules if r["key"] == "temperature")
    rule["source"] = {"ref": "openai_chat_protocol_parameters_v1", "version": 1}
    rule["fixed_value"] = 0.8
    fixed = profile.__class__.model_validate(data)
    assert next(r for r in ensure_outlet_sampling_rules(fixed).parameter_rules if r["key"] == "temperature") == next(r for r in fixed.parameter_rules if r["key"] == "temperature")


def test_current_agent_values_preserve_explicit_values_and_avoid_legacy_adapter(profile, monkeypatch):
    from nexent.core.model_service.compatibility import invocation_options
    def forbidden(*args, **kwargs):
        raise AssertionError("Canonical Agent parameters entered legacy invocation adaptation")
    monkeypatch.setattr(invocation_options.LegacyInvocationOptions, "resolve", forbidden)
    result = merge_agent_model_parameters(profile, {"parameter_values": {"temperature": 0, "enable_thinking": False}})
    assert result.parameter_values["temperature"] == 0
    assert result.parameter_values["enable_thinking"] is False
    assert "reasoning_budget_tokens" not in result.parameter_values
    assert profile.parameter_values["reasoning_budget_tokens"] == 64


def test_read_historical_entry_is_immutable_and_current_shape_is_unambiguous():
    from nexent.core.model_service.compatibility.agent_parameters import read_agent_parameter_entry
    old = {"temperature": 0, "top_p": None, "context_window_tokens": 4096,
           "extra_params": {"enable_thinking": False, "__custom__": {"flag": None}}}
    original = deepcopy(old)
    current = read_agent_parameter_entry(old)
    assert current == {"parameter_values": {"temperature": 0, "enable_thinking": False},
                       "custom_overrides": {"flag": None}}
    assert read_agent_parameter_entry(current) == current
    assert old == original
    with pytest.raises(ParameterValidationError, match="PARAMETER_UPDATE_CONFLICT"):
        read_agent_parameter_entry({"parameter_values": {}, "temperature": 0.3})


@pytest.mark.parametrize("values", [{"not_declared": 1}, {"temperature": "bad"},
    {"enable_thinking": False, "reasoning_budget_tokens": 32}])
def test_current_agent_invalid_values_are_not_hidden_by_session_overrides(profile, values):
    from management.services.agent.model_parameters import merge_runtime_model_parameters
    with pytest.raises(ParameterValidationError):
        merge_runtime_model_parameters(profile, {"parameter_values": values}, {"temperature": 0.1})


def test_agent_read_projection_normalizes_only_profile_llm_without_writing_versions(monkeypatch):
    from management.services.agent import read
    records = {1: {"model_type": "llm", "profile_schema_version": 1, "display_name": "LLM"},
               2: {"model_type": "vlm", "display_name": "Vision"}}
    monkeypatch.setattr(read, "get_valid_model_ids", lambda ids, tenant: ids)
    monkeypatch.setattr(read, "resolve_model_record", lambda model_id, *args: records[model_id])
    monkeypatch.setattr(read, "is_model_configured", lambda record: True)
    old = {"model_ids": [1, 2], "model_params_override": {
        "1": {"temperature": 0, "extra_params": {"enable_thinking": False}},
        "2": {"temperature": 0.3, "extra_params": {"vision_option": True}}}}
    before = deepcopy(old)
    view = read.project_agent_models(old, "tenant", detail=True).fields
    assert view["model_params_override"]["1"] == {"parameter_values": {"temperature": 0, "enable_thinking": False}}
    assert view["model_params_override"]["2"] == before["model_params_override"]["2"]
    assert old == before


@pytest.mark.parametrize("window", [0, True, 1, 64000])
def test_scb03_historical_agent_length_values_inherit_outlet(profile, window):
    from management.services.agent.model_parameters import merge_runtime_model_parameters
    entry={"context_window_tokens":window,"parameter_values":{"temperature":0,"max_output_tokens":999999},"custom_overrides":{"max_tokens":1}}
    result=merge_runtime_model_parameters(profile,entry,{"max_output_tokens":3})
    assert result.parameter_values["max_output_tokens"] == 2048
    assert result.parameter_values["temperature"] == 0
    assert result.parameter_values["reasoning_budget_tokens"] == 64
    assert profile.parameter_values["max_output_tokens"] == 2048
