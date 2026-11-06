# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Custom-provider reasoning controls honor explicit restrictions, not missing data."""
import pytest

from contracts.model import ModelOutletPatchRequest, ModelProfilePreviewRequest
from contracts.errors.exceptions import ModelOutletValidationError
from management.services.model import profiles as service
from management.services.conversation.model_preferences import merge_model_preferences
from nexent.core.model_service.compatibility.invocation_options import LegacyInvocationOptions
from nexent.core.model_service.profiles.outlet_controls import ensure_outlet_parameter_rules
from nexent.core.model_service.profiles.protocol_parameters import connectivity_request


def make(model="qwen3.8-flash", **kw):
    return service.build_outlet_draft(ModelProfilePreviewRequest(
        request_model_id=model, provider_info={"base_url": "https://gateway.invalid/v1"}, **kw), "tenant")[0]


@pytest.mark.parametrize("model", ["qwen3.7-plus", "qwen3.7-max", "qwen3.8-flash", "qwen3.8-max", "glm-5.2", "MiniMax-M3", "kimi-k3"])
@pytest.mark.parametrize("enabled", [False, True])
def test_ac009_custom_model_can_configure_unknown_shutdown_support(model, enabled):
    profile = make(model, parameter_values={"enable_thinking": enabled})
    assert connectivity_request(profile)[3]["enable_thinking"] is enabled
    changed = service.apply_outlet_patch(profile, ModelOutletPatchRequest(
        expected_revision=1, parameter_values={"enable_thinking": not enabled}))
    assert connectivity_request(changed)[3]["enable_thinking"] is not enabled


@pytest.mark.parametrize("model", ["glm-5.3", "glm-5.3-flash", "qwen3.8-2.4t-a95b", "MiniMax-M2.7"])
def test_ac010_explicit_model_preference_disables_generic_toggle(model):
    profile = make(model)
    assert profile.capabilities.reasoning.can_disable is False
    assert not any(r["key"] == "enable_thinking" for r in profile.parameter_rules)
    with pytest.raises(ModelOutletValidationError):
        service.apply_outlet_patch(profile, ModelOutletPatchRequest(
            expected_revision=1, parameter_values={"enable_thinking": False}))


def test_ac010_unmatched_and_nonreasoning_models_do_not_gain_reasoning():
    for model in ["unlisted-model", "qwen3-coder-next"]:
        profile = make(model)
        assert not any(r["key"] == "enable_thinking" for r in profile.parameter_rules)


def test_ac009_legacy_outlet_and_conversation_share_the_same_compatible_binding():
    data = make().model_dump(mode="json")
    data["parameter_rules"] = [r for r in data["parameter_rules"] if r["key"] != "enable_thinking"]
    data["parameter_values"].pop("enable_thinking", None)
    data["capabilities"]["reasoning"]["controls"] = None
    legacy = make().__class__.model_validate(data)
    original = legacy.model_dump()
    normalized = ensure_outlet_parameter_rules(legacy)
    assert ensure_outlet_parameter_rules(normalized) == normalized
    for updated in [merge_model_preferences(legacy, {"enable_thinking": False}),
                    LegacyInvocationOptions({"enable_thinking": False}).resolve(legacy),
                    service.apply_outlet_patch(legacy, ModelOutletPatchRequest(
                        expected_revision=1, parameter_values={"enable_thinking": False}))]:
        assert connectivity_request(updated)[3]["enable_thinking"] is False
    assert legacy.model_dump() == original


def test_ac010_legacy_limitation_uses_only_the_explicit_shutdown_preference():
    data = make("glm-5.3").model_dump(mode="json")
    data["capabilities"]["reasoning"].pop("can_disable")
    legacy = make().__class__.model_validate(data)
    normalized = ensure_outlet_parameter_rules(legacy)
    assert normalized.capabilities.reasoning.can_disable is False
    assert normalized.parameter_values == legacy.parameter_values
    assert normalized.identity == legacy.identity
    assert normalized.connection == legacy.connection
    assert normalized.context_configuration == legacy.context_configuration
    with pytest.raises(ModelOutletValidationError):
        merge_model_preferences(legacy, {"enable_thinking": False})


@pytest.mark.parametrize("preset,path", [("thinking_type", "thinking"), ("chat_template", "chat_template_kwargs")])
def test_ac009_explicit_custom_format_is_preserved(preset, path):
    profile = make(thinking_control=preset, parameter_values={"enable_thinking": False})
    normalized = ensure_outlet_parameter_rules(profile)
    body = connectivity_request(normalized)[3]
    assert "enable_thinking" not in body
    assert body[path] == ({"type": "disabled"} if preset == "thinking_type" else {"enable_thinking": False})
    assert normalized == profile


def test_ac010_explicit_format_cannot_bypass_a_model_shutdown_restriction():
    with pytest.raises(ModelOutletValidationError):
        make("glm-5.3", thinking_control="thinking_type", parameter_values={"enable_thinking": False})

@pytest.mark.parametrize("model", ["glm-5.2", "kimi-k3"])
def test_ac011_provider_preferences_record_the_documented_hybrid_override(model):
    catalog = service.get_model_profile_catalog()
    atom = catalog.providers["alibaba-cn"]
    profile = make(model, provider_profile={"key": atom.key, "revision": atom.revision},
                   parameter_values={"enable_thinking": False})
    assert profile.provider_key == "alibaba-cn"
    assert profile.capabilities.reasoning.can_disable is True
    assert connectivity_request(profile)[3]["enable_thinking"] is False

@pytest.mark.parametrize("restriction", ["fixed", "readonly"])
def test_ac010_existing_toggle_constraints_survive_compatible_completion(restriction):
    data = make(parameter_values={"enable_thinking": False}).model_dump(mode="json")
    rule = next(r for r in data["parameter_rules"] if r["key"] == "enable_thinking")
    if restriction == "fixed":
        rule.pop("default_value", None)
        rule["fixed_value"] = False
    else:
        rule["editable"] = False
    profile = make().__class__.model_validate(data)
    assert ensure_outlet_parameter_rules(profile) == profile
    with pytest.raises(ModelOutletValidationError):
        service.apply_outlet_patch(profile, ModelOutletPatchRequest(
            expected_revision=1, parameter_values={"enable_thinking": True}))


def test_ac010_old_off_setting_remains_readable_and_can_be_corrected():
    profile = make("glm-5.3", thinking_control="thinking_type", parameter_values={"enable_thinking": True})
    data = profile.model_dump(mode="json")
    data["parameter_values"]["enable_thinking"] = False
    old = profile.__class__.model_validate(data)
    normalized = ensure_outlet_parameter_rules(old)
    assert normalized.parameter_values["enable_thinking"] is False
    assert normalized.capabilities.reasoning.can_disable is False
    assert normalized.parameter_rules == old.parameter_rules
    repaired = service.apply_outlet_patch(old, ModelOutletPatchRequest(
        expected_revision=1, parameter_values={"enable_thinking": True}))
    assert connectivity_request(repaired)[3]["thinking"] == {"type": "enabled"}
    with pytest.raises(ModelOutletValidationError):
        service.apply_outlet_patch(repaired, ModelOutletPatchRequest(
            expected_revision=1, parameter_values={"enable_thinking": False}))
    with pytest.raises(ModelOutletValidationError):
        merge_model_preferences(old, {})


def test_ac009_untouched_custom_toggle_does_not_force_an_unqualified_upstream_parameter():
    profile = make()
    assert any(r["key"] == "enable_thinking" for r in profile.parameter_rules)
    assert "enable_thinking" not in profile.parameter_values
    assert "enable_thinking" not in connectivity_request(profile)[3]
    changed = service.apply_outlet_patch(profile, ModelOutletPatchRequest(expected_revision=1, reset_parameters=True))
    assert "enable_thinking" not in connectivity_request(changed)[3]
