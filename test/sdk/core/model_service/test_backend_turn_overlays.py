# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Turn controls must update the frozen outlet used by the HTTP adapter."""

import pytest
from types import SimpleNamespace

from nexent.core.agents.agent_model import ModelConfig
from contracts.errors.exceptions import ModelOutletValidationError

from management.services.agent.preparation.run import apply_root_model_preferences


@pytest.fixture
def sampling_profile(openai_profile):
    data = openai_profile.model_dump()
    data["parameter_rules"] = [rule for rule in data["parameter_rules"] if rule["key"] != "temperature"]
    data["parameter_rules"].append({
        "key": "temperature", "schema": {"type": "number", "minimum": 0, "maximum": 2},
        "visible": True, "editable": True, "required": False,
        "allowed_scopes": ["outlet", "conversation"], "ui_group": "sampling", "owner": "provider",
        "source": {"ref": "controlled_rule", "version": 1},
        "api_binding": {"path": "/temperature", "transform_ref": "identity_v1", "transform_version": 1}})
    return openai_profile.__class__.model_validate(data)


def configured(profile):
    return ModelConfig(cite_name="selected", model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, resolved_profile=profile,
        enable_thinking=False, reasoning_capability={"status": "supported", "control": "toggle"})


def apply_preferences(config, values):
    connection = config.resolved_profile.connection
    connection = connection.model_copy(update={"credential_ref": connection.credential_ref.model_copy(update={"model_id": 42})})
    profile = config.resolved_profile.model_copy(update={"outlet_id": 42, "connection": connection})
    model = config.model_copy(update={"resolved_profile": profile})
    models = [model]
    agent = SimpleNamespace(model_name=model.cite_name)
    apply_root_model_preferences(models, agent, {"42": values})
    assert models[0] is model and agent.model_name == models[-1].cite_name
    return models[-1]


@pytest.mark.parametrize("value", [0, 0.4])
def test_sampling_overlay_changes_request_profile_without_mutating_saved_outlet(sampling_profile, value):
    openai_profile = sampling_profile
    original = openai_profile.model_dump()
    result = apply_preferences(configured(openai_profile), {"temperature": value})
    assert result.resolved_profile.parameter_values["temperature"] == value
    assert openai_profile.model_dump() == original


def test_thinking_disable_updates_profile_and_clears_dependent_budget(openai_profile):
    data = openai_profile.model_dump()
    data["parameter_values"].update(enable_thinking=True, reasoning_budget_tokens=64)
    original = openai_profile.__class__.model_validate(data)
    base = configured(original)
    base.enable_thinking = True
    base.reasoning_budget_tokens = 64
    result = apply_preferences(base, {"enable_thinking": False})
    assert result.resolved_profile.parameter_values["enable_thinking"] is False
    assert "reasoning_budget_tokens" not in result.resolved_profile.parameter_values
    assert original.parameter_values["enable_thinking"] is True
    assert original.parameter_values["reasoning_budget_tokens"] == 64


def test_profile_constraints_reject_invalid_sampling_without_mutating_original(sampling_profile):
    openai_profile = sampling_profile
    original = openai_profile.model_dump()

    # Global request bounds are checked before narrower outlet declarations.
    with pytest.raises(ModelOutletValidationError):
        apply_preferences(configured(openai_profile), {"temperature": 100})
    assert openai_profile.model_dump() == original


def test_profile_sampling_bounds_still_apply_inside_global_request_bounds(sampling_profile):
    data = sampling_profile.model_dump()
    next(rule for rule in data["parameter_rules"] if rule["key"] == "temperature")["schema"]["maximum"] = 0.5
    profile = type(sampling_profile).model_validate(data)
    original = profile.model_dump()
    with pytest.raises(ModelOutletValidationError):
        apply_preferences(configured(profile), {"temperature": 0.6})
    assert profile.model_dump() == original
