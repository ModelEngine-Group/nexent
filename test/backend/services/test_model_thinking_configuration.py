# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AC-PARAM-FORM: explicit thinking formats are frozen, validated and sent consistently."""

import pytest
from contracts.model import ModelOutletPatchRequest, ModelProfilePreviewRequest
from contracts.errors.exceptions import ModelOutletValidationError
from management.services.model.profiles import apply_outlet_patch, build_outlet_draft, list_atomic_profiles
from nexent.core.model_service.registry import model_service_references


@pytest.mark.parametrize("preset,path,value", [
    ("enable_thinking", "/enable_thinking", False),
    ("thinking_type", "/thinking/type", "disabled"),
    ("chat_template", "/chat_template_kwargs/enable_thinking", False),
])
def test_explicit_thinking_binding_preserves_false_and_survives_storage(preset, path, value):
    request = ModelProfilePreviewRequest(provider_info={"base_url": "https://custom.invalid/v1"},
        request_model_id="qwen3.8", thinking_control=preset, parameter_values={"enable_thinking": False})
    profile, _ = build_outlet_draft(request, "tenant")
    assert profile.parameter_values["enable_thinking"] is False
    assert profile.capabilities.reasoning.controls[0].mode == "toggle"
    rule = next(rule for rule in profile.parameter_rules if rule["key"] == "enable_thinking")
    assert rule["api_binding"]["path"] == path
    assert rule["allowed_scopes"] == ["outlet", "conversation"]
    from nexent.core.model_service.parameter_transforms import transform_parameter
    assert transform_parameter(rule["api_binding"], False) == value
    from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile, decode_resolved_model_profile
    stored = encode_resolved_model_profile(profile, registered_references=model_service_references())
    stored["model_id"] = 42
    restored = decode_resolved_model_profile(stored, registered_references=model_service_references())
    assert restored.parameter_values["enable_thinking"] is False
    assert restored.capabilities.reasoning.controls[0].mode == "toggle"
    from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
    from nexent.core.model_service.contracts import ModelMessage, ModelRequest
    prepared = OpenAIChatAdapter().prepare_http_request(ModelRequest(request_id="thinking-test", outlet_id=42,
        config_revision=restored.config_revision, messages=[ModelMessage(semantic_role="user_input",
        content_parts=[{"type":"text","text":"hello"}])]), restored)
    actual = prepared.json_body
    for part in path.strip("/").split("/"):
        actual = actual[part]
    assert actual == value


def test_edit_restores_the_original_without_reloading_atoms():
    profile, _ = build_outlet_draft(ModelProfilePreviewRequest(provider_info={"base_url": "https://custom.invalid/v1"},
        request_model_id="custom-model"), "tenant")
    original = profile.model_dump()
    changed = apply_outlet_patch(profile, ModelOutletPatchRequest(expected_revision=1,
        thinking_control="thinking_type", parameter_values={"enable_thinking": True}))
    restored = apply_outlet_patch(changed, ModelOutletPatchRequest(expected_revision=1,
        thinking_control="profile_default"))
    assert restored.capabilities.reasoning == profile.capabilities.reasoning
    assert "enable_thinking" not in restored.parameter_values
    assert restored.parameter_rules == profile.parameter_rules
    assert profile.model_dump() == original


def test_invalid_toggle_does_not_become_a_truthy_string():
    with pytest.raises(ModelOutletValidationError):
        build_outlet_draft(ModelProfilePreviewRequest(provider_info={"base_url":"https://custom.invalid/v1"},
            request_model_id="custom", thinking_control="enable_thinking", parameter_values={"enable_thinking":"false"}), "tenant")


def test_smaller_context_automatically_bounds_hidden_limits_without_exposing_more_fields():
    profile, _ = build_outlet_draft(ModelProfilePreviewRequest(provider_info={"base_url":"https://custom.invalid/v1"},
        request_model_id="custom", context_limits={"combined_window":200000,"input_limit":180000,"output_limit":16000},
        parameter_values={"max_output_tokens":4096}), "tenant")
    updated = apply_outlet_patch(profile, ModelOutletPatchRequest(expected_revision=1, context_limits={"combined_window":8000}))
    assert updated.capabilities.context.combined_window == 8000
    assert updated.capabilities.context.input_limit == 8000
    assert updated.capabilities.context.output_limit == 8000
    assert updated.parameter_values["max_output_tokens"] == 4096
    assert profile.capabilities.context.input_limit == 180000


@pytest.mark.parametrize("changes", [{"combined_window":4096}, {"combined_window":100000,"output_limit":4096}])
def test_output_size_cannot_exceed_context_or_profile_limit(changes):
    with pytest.raises(ModelOutletValidationError) as error:
        build_outlet_draft(ModelProfilePreviewRequest(provider_info={"base_url":"https://custom.invalid/v1"},
            request_model_id="custom", context_limits=changes, parameter_values={"max_output_tokens":8192}), "tenant")
    assert error.value.category == "PARAMETER_LIMIT_EXCEEDED"


@pytest.mark.parametrize("mode,key,value,wire", [
    ("effort", "reasoning_effort", "medium", "reasoning_effort"),
    ("budget_tokens", "reasoning_budget_tokens", 4096, "thinking_budget"),
])
def test_degree_presets_roundtrip_and_build_the_declared_request(mode, key, value, wire):
    from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
    from nexent.core.model_service.contracts import ModelMessage, ModelRequest
    from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile, decode_resolved_model_profile

    profile, _ = build_outlet_draft(ModelProfilePreviewRequest(
        provider_info={"base_url": "https://custom.invalid/v1"}, request_model_id="custom-degree",
        thinking_control="enable_thinking", thinking_mode=mode,
        parameter_values={"enable_thinking": True, key: value}), "tenant")
    stored = encode_resolved_model_profile(profile, registered_references=model_service_references())
    stored["model_id"] = 42
    restored = decode_resolved_model_profile(stored, registered_references=model_service_references())
    prepared = OpenAIChatAdapter().prepare_http_request(ModelRequest(
        request_id="degree", outlet_id=42, config_revision=restored.config_revision,
        messages=[ModelMessage(semantic_role="user_input", content_parts=[{"type": "text", "text": "hello"}])]), restored)
    assert prepared.json_body[wire] == value
    assert prepared.json_body["enable_thinking"] is True
    assert restored.provenance.provider_metadata["operator_thinking_degree"]["mode"] == mode


def test_degree_type_switch_and_reset_remove_only_operator_degree_values():
    profile, _ = build_outlet_draft(ModelProfilePreviewRequest(
        provider_info={"base_url": "https://custom.invalid/v1"}, request_model_id="custom-degree",
        thinking_control="enable_thinking", thinking_mode="effort",
        parameter_values={"enable_thinking": True, "reasoning_effort": "low"}), "tenant")
    changed = apply_outlet_patch(profile, ModelOutletPatchRequest(expected_revision=1,
        thinking_mode="budget_tokens", delete_parameters=["reasoning_effort"],
        parameter_values={"reasoning_budget_tokens": 1234}))
    assert "reasoning_effort" not in changed.parameter_values
    assert changed.parameter_values["reasoning_budget_tokens"] == 1234
    reset = apply_outlet_patch(changed, ModelOutletPatchRequest(expected_revision=1,
        thinking_mode="default", delete_parameters=["reasoning_budget_tokens"]))
    assert reset.parameter_values == {"enable_thinking": True}
    assert reset.provenance.provider_metadata["operator_thinking_degree"]["mode"] == "default"
    from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile, decode_resolved_model_profile
    stored = encode_resolved_model_profile(reset, registered_references=model_service_references())
    stored["model_id"] = 42
    reloaded = decode_resolved_model_profile(stored, registered_references=model_service_references())
    assert reloaded.provenance.provider_metadata["operator_thinking_degree"]["mode"] == "default"


def test_registered_profile_budget_mapping_and_limit_are_preserved():
    profile, _ = build_outlet_draft(ModelProfilePreviewRequest(
        provider_info={"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
        provider_profile={"key": "alibaba-cn", "revision": next(item['revision'] for item in list_atomic_profiles('provider', page_size=100)['items'] if item['key'] == 'alibaba-cn')},
        request_model_id="qwen3.5-plus", thinking_mode="budget_tokens"), "tenant")
    rule = next(rule for rule in profile.parameter_rules if rule["key"] == "reasoning_budget_tokens")
    assert rule["schema"]["maximum"] == 81920
    assert "minimum" not in rule["schema"]
    assert rule["api_binding"]["path"] == "/thinking_budget"
    assert rule["source"]["ref"] == "alibaba_cn_qwen35_plus_thinking_v1"


def test_invalid_custom_effort_value_is_rejected():
    with pytest.raises(ModelOutletValidationError):
        build_outlet_draft(ModelProfilePreviewRequest(
            provider_info={"base_url": "https://custom.invalid/v1"}, request_model_id="custom-degree",
            thinking_control="enable_thinking", thinking_mode="effort",
            parameter_values={"enable_thinking": True, "reasoning_effort": "invented"}), "tenant")
