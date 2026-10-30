# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Operator thinking presets retain frozen bindings, domains and reset behavior."""

import pytest

from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from nexent.core.model_service.profiles.thinking_configuration import (
    configure_thinking,
    configure_thinking_degree,
)


def without_reasoning(profile):
    data = profile.model_dump(mode="json")
    keys = {"enable_thinking", "reasoning_effort", "reasoning_budget_tokens"}
    data["parameter_rules"] = [rule for rule in data["parameter_rules"] if rule["key"] not in keys]
    data["parameter_values"] = {key: value for key, value in data["parameter_values"].items() if key not in keys}
    data["capabilities"]["reasoning"] = {"status": "unknown", "controls": None, "response_paths": []}
    return ResolvedModelProfile.model_validate(data)


@pytest.mark.parametrize("preset,path,transform", [
    ("enable_thinking", "/enable_thinking", "identity_v1"),
    ("thinking_type", "/thinking/type", "thinking_toggle_v1"),
    ("chat_template", "/chat_template_kwargs/enable_thinking", "identity_v1"),
])
def test_explicit_switch_format_is_registered_and_reset_restores_unknown(openai_profile, preset, path, transform):
    original = without_reasoning(openai_profile)
    changed = configure_thinking(original, preset)
    rule = next(rule for rule in changed.parameter_rules if rule["key"] == "enable_thinking")
    assert rule["api_binding"] == {"path": path, "transform_ref": transform, "transform_version": 1}
    assert changed.capabilities.reasoning.status == "supported"
    assert changed.provenance.provider_metadata["operator_thinking"]["preset"] == preset
    restored = configure_thinking(changed, "profile_default")
    assert restored.model_dump() == original.model_dump()
    assert original.capabilities.reasoning.status == "unknown"


def test_existing_switch_preserves_domain_and_order_across_format_changes(openai_profile):
    original = openai_profile.model_dump()
    first = configure_thinking(openai_profile, "thinking_type")
    second = configure_thinking(first, "chat_template")
    assert len([rule for rule in second.parameter_rules if rule["key"] == "enable_thinking"]) == 1
    assert len([item for item in second.provenance.overrides if item.source == "operator_thinking_v1"]) == 1
    restored = configure_thinking(second, "profile_default")
    assert restored.model_dump() == original
    assert configure_thinking(openai_profile, None) is openai_profile
    assert configure_thinking(openai_profile, "profile_default") is openai_profile


@pytest.mark.parametrize("mode,key,path", [
    ("effort", "reasoning_effort", "/reasoning_effort"),
    ("budget_tokens", "reasoning_budget_tokens", "/thinking_budget"),
])
def test_degree_preset_on_unknown_profile_has_control_and_can_be_reset(openai_profile, mode, key, path):
    original = without_reasoning(openai_profile)
    changed = configure_thinking_degree(configure_thinking(original, "enable_thinking"), mode)
    rule = next(rule for rule in changed.parameter_rules if rule["key"] == key)
    assert rule["api_binding"]["path"] == path
    assert rule["condition"] == {"key": "enable_thinking", "op": "eq", "value": True}
    assert changed.capabilities.reasoning.status == "supported"
    assert any(control.mode == mode for control in changed.capabilities.reasoning.controls)
    restored = configure_thinking_degree(changed, "default")
    assert not any(rule["key"] == key for rule in restored.parameter_rules)
    assert restored.capabilities.reasoning.status == "supported"
    assert configure_thinking_degree(original, None) is original


def test_degree_reset_without_operator_switch_restores_original_status(openai_profile):
    data = openai_profile.model_dump()
    data["capabilities"]["reasoning"].update(status="unknown", controls=None)
    original = ResolvedModelProfile.model_validate(data)
    changed = configure_thinking_degree(original, "effort")
    reset = configure_thinking_degree(changed, "default")
    assert reset.capabilities.reasoning.status == "unknown"
    assert reset.parameter_values == original.parameter_values
    assert reset.provenance.overrides == original.provenance.overrides


@pytest.mark.parametrize("function,value,category", [
    (configure_thinking, "arbitrary_field", "THINKING_FORMAT_UNKNOWN"),
    (configure_thinking_degree, "arbitrary_mode", "THINKING_MODE_UNKNOWN"),
])
def test_unknown_operator_presets_are_rejected_without_mutating_profile(openai_profile, function, value, category):
    before = openai_profile.model_dump()
    with pytest.raises(ParameterValidationError, match=category):
        function(openai_profile, value)
    assert openai_profile.model_dump() == before


def test_declared_budget_binding_and_domain_survive_operator_selection(openai_profile):
    original = next(rule for rule in openai_profile.parameter_rules if rule["key"] == "reasoning_budget_tokens")
    selected = configure_thinking_degree(openai_profile, "budget_tokens")
    actual = next(rule for rule in selected.parameter_rules if rule["key"] == "reasoning_budget_tokens")
    assert actual == original
    assert configure_thinking_degree(selected, "default").parameter_rules == openai_profile.parameter_rules


def test_switching_degree_does_not_silently_discard_fixed_budget(openai_profile):
    data = openai_profile.model_dump()
    data["parameter_values"].update(enable_thinking=True, reasoning_budget_tokens=4096)
    next(rule for rule in data["parameter_rules"] if rule["key"] == "reasoning_budget_tokens")["editable"] = False
    fixed = ResolvedModelProfile.model_validate(data)
    with pytest.raises(ParameterValidationError, match="FIXED_PARAMETER"):
        configure_thinking_degree(fixed, "effort")
    assert fixed.parameter_values["reasoning_budget_tokens"] == 4096


@pytest.mark.parametrize("preset", ["enable_thinking", "thinking_type", "chat_template"])
@pytest.mark.parametrize("mode", ["effort", "budget_tokens"])
def test_aeu_coupled_reset_removes_dependencies_in_order_and_is_idempotent(openai_profile, preset, mode):
    from nexent.core.model_service.profiles.thinking_configuration import configure_outlet_policy

    original = configure_outlet_policy(without_reasoning(openai_profile))
    configured = configure_outlet_policy(original, thinking_control=preset, thinking_mode=mode)
    restored = configure_outlet_policy(configured, thinking_control="profile_default", thinking_mode="default")
    assert restored.parameter_rules == original.parameter_rules
    assert restored.parameter_values == original.parameter_values
    assert restored.capabilities == original.capabilities
    assert configure_outlet_policy(restored, thinking_control="profile_default", thinking_mode="default").model_dump() == restored.model_dump()
