# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AC-PARAM-LAYERS: explicit Agent overrides sit between outlet and session values."""

from copy import deepcopy

import pytest
from consts.exceptions import ModelOutletValidationError
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from services.agent_model_parameters import merge_agent_model_parameters
from services.conversation_model_preferences_service import merge_model_preferences
from services.model_profile_service import build_outlet_draft
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


@pytest.mark.parametrize("entry", [{"temperature": "invalid"}, {"context_window_tokens": 0},
    {"context_window_tokens": True}, {"extra_params": [1]}, {"context_window_tokens": 1}, {"extra_params": {"top_k": 5}}])
def test_invalid_agent_configuration_is_rejected(profile, entry):
    with pytest.raises(ParameterValidationError):
        merge_agent_model_parameters(profile, entry)


def test_session_reenables_thinking_with_the_inherited_outlet_budget(profile):
    from services.agent_model_parameters import merge_runtime_model_parameters

    result = merge_runtime_model_parameters(profile, {"extra_params": {"enable_thinking": False}},
                                            {"enable_thinking": True})
    assert result.parameter_values["enable_thinking"] is True
    assert result.parameter_values["reasoning_budget_tokens"] == 64
    with pytest.raises(ModelOutletValidationError) as error:
        merge_runtime_model_parameters(profile, {}, {"context_window_tokens": 100})
    assert error.value.category == "PARAMETER_UNKNOWN"


def test_parent_and_child_keep_their_own_override_when_sharing_one_outlet(profile):
    from types import SimpleNamespace
    from services.agent_model_parameters import bind_agent_model_profiles

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
