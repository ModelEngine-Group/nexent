# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Turn controls must update the frozen outlet used by the HTTP adapter."""

import pytest
from nexent.core.agents.agent_model import ModelConfig
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError

from management.services.model.run_controls import overlay_root_model


@pytest.fixture
def sampling_profile(openai_profile):
    data = openai_profile.model_dump()
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


@pytest.mark.parametrize("value", [0, 0.4])
def test_sampling_overlay_changes_request_profile_without_mutating_saved_outlet(sampling_profile, value):
    openai_profile = sampling_profile
    original = openai_profile.model_dump()
    result = overlay_root_model(configured(openai_profile), {"temperature": value}, "root")
    assert result.temperature == value
    assert result.resolved_profile.parameter_values["temperature"] == value
    assert openai_profile.model_dump() == original


def test_thinking_disable_updates_profile_and_clears_dependent_budget(openai_profile):
    data = openai_profile.model_dump()
    data["parameter_values"].update(enable_thinking=True, reasoning_budget_tokens=64)
    original = openai_profile.__class__.model_validate(data)
    base = configured(original)
    base.enable_thinking = True
    base.reasoning_budget_tokens = 64
    result = overlay_root_model(base, {"deep_thinking": False}, "root")
    assert result.resolved_profile.parameter_values["enable_thinking"] is False
    assert "reasoning_budget_tokens" not in result.resolved_profile.parameter_values
    assert original.parameter_values["enable_thinking"] is True
    assert original.parameter_values["reasoning_budget_tokens"] == 64


def test_profile_constraints_reject_invalid_sampling_without_mutating_original(sampling_profile):
    openai_profile = sampling_profile
    original = openai_profile.model_dump()
    with pytest.raises(ParameterValidationError):
        overlay_root_model(configured(openai_profile), {"temperature": 100}, "root")
    assert openai_profile.model_dump() == original
