# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Legacy aliases preserve declared bindings without changing persisted defaults."""

import pytest
from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
from nexent.core.model_service.compatibility.invocation_options import (
    LegacyInvocationOptions,
)
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from smolagents.models import CODEAGENT_RESPONSE_FORMAT


@pytest.fixture
def declared_profile(openai_profile):
    snapshot = openai_profile.model_dump()
    for key, schema in (
        ("response_format", {"type": "object", "required": ["type"], "properties": {
            "type": {"enum": ["json_object", "json_schema"]},
        }}),
    ):
        snapshot["parameter_rules"].append({
            "key": key, "schema": schema, "visible": False, "editable": True,
            "required": False, "allowed_scopes": ["outlet"], "ui_group": "legacy",
            "owner": "provider", "source": {"ref": "controlled_protocol_fixture", "version": 1},
            "api_binding": {"path": "/" + key, "transform_ref": "identity_v1", "transform_version": 1},
        })
    return ResolvedModelProfile.model_validate(snapshot)


def test_code_stop_and_structured_format_use_existing_adapter_bindings(declared_profile):
    stops = ["Observation:", "Calling tools:"]
    profile = LegacyInvocationOptions({}, stops, CODEAGENT_RESPONSE_FORMAT).resolve(declared_profile)
    request = ModelRequest(
        request_id="legacy", outlet_id=profile.outlet_id, config_revision=profile.config_revision,
        messages=[ModelMessage(semantic_role="user", content_parts=[{"type": "text", "text": "code"}])],
    )
    body = OpenAIChatAdapter().prepare_http_request(request, profile).json_body
    assert body["stop"] == stops and body["response_format"] == CODEAGENT_RESPONSE_FORMAT
    assert "stop" not in declared_profile.parameter_values
    assert "response_format" not in declared_profile.parameter_values
    stops.append("changed")
    assert profile.parameter_values["stop"] == ["Observation:", "Calling tools:"]


def test_none_aliases_preserve_saved_defaults_and_absence(declared_profile):
    snapshot = declared_profile.model_dump()
    snapshot["parameter_values"]["stop"] = ["saved"]
    original = ResolvedModelProfile.model_validate(snapshot)
    result = LegacyInvocationOptions({}).resolve(original)
    assert result.parameter_values["stop"] == ["saved"]
    assert "response_format" not in result.parameter_values


@pytest.mark.parametrize("stops", [["x"], []])
def test_identical_duplicate_alias_is_allowed_but_conflict_rejected(declared_profile, stops):
    result = LegacyInvocationOptions({"stop": stops}, stops).resolve(declared_profile)
    assert result.parameter_values["stop"] == stops
    with pytest.raises(ParameterValidationError, match="LEGACY_PARAMETER_CONFLICT"):
        LegacyInvocationOptions({"stop": ["other"]}, stops).resolve(declared_profile)


@pytest.mark.parametrize("options", [
    LegacyInvocationOptions({}, [1]), LegacyInvocationOptions({}, [""]),
    LegacyInvocationOptions({}, response_format={"type": "arbitrary"}),
    LegacyInvocationOptions({"messages": []}),
])
def test_invalid_or_undeclared_options_are_rejected(declared_profile, options):
    with pytest.raises(ParameterValidationError):
        options.resolve(declared_profile)


def test_protocol_capability_does_not_invent_stop_or_format_rules(openai_profile):
    data = openai_profile.model_dump()
    data["parameter_rules"] = [rule for rule in data["parameter_rules"] if rule["key"] != "stop"]
    openai_profile = ResolvedModelProfile.model_validate(data)
    for options in (LegacyInvocationOptions({}, ["stop"]), LegacyInvocationOptions({}, response_format={"type": "json_object"})):
        with pytest.raises(ParameterValidationError, match="PARAMETER_UNKNOWN"):
            options.resolve(openai_profile)


@pytest.mark.parametrize("stops", [["Observation:", "Calling tools:"], ["<end_plan>"], "END", []])
def test_builtin_profile_accepts_actual_code_and_planning_stops(openai_profile, stops):
    profile = LegacyInvocationOptions({}, stop_sequences=stops).resolve(openai_profile)
    request = ModelRequest(request_id="builtin-stop", outlet_id=profile.outlet_id,
        config_revision=profile.config_revision,
        messages=[ModelMessage(semantic_role="user", content_parts=[{"type": "text", "text": "hello"}])])
    assert OpenAIChatAdapter().prepare_http_request(request, profile).json_body["stop"] == stops
    assert "stop" not in openai_profile.parameter_values


@pytest.mark.parametrize("stops", [["ok", 1], [""], "", {"stop": "END"}])
def test_builtin_stop_rule_rejects_invalid_code_values(openai_profile, stops):
    with pytest.raises(ParameterValidationError):
        LegacyInvocationOptions({}, stop_sequences=stops).resolve(openai_profile)


def test_builtin_qwen35_does_not_claim_code_json_schema_support(openai_profile):
    with pytest.raises(ParameterValidationError, match="PARAMETER_UNKNOWN"):
        LegacyInvocationOptions({}, response_format=CODEAGENT_RESPONSE_FORMAT).resolve(openai_profile)


@pytest.mark.parametrize("custom", [[], 1, {1: True}, {"": True}])
def test_invalid_legacy_custom_container_rejected(declared_profile, custom):
    with pytest.raises(ParameterValidationError, match="LEGACY_CUSTOM_PARAMETERS_INVALID"):
        LegacyInvocationOptions({}, custom_overrides=custom).resolve(declared_profile)


def test_legacy_custom_overrides_preserve_false_zero_and_explicit_removal(declared_profile):
    data = declared_profile.model_dump()
    data["extra_api_parameters"] = [{"path": "/old", "value": "remove"}]
    original = ResolvedModelProfile.model_validate(data)
    updated = LegacyInvocationOptions({}, custom_overrides={"old": None, "flag": False, "count": 0}).resolve(original)
    assert updated.extra_api_parameters == [{"path": "/flag", "value": False}, {"path": "/count", "value": 0}]
    assert original.extra_api_parameters == [{"path": "/old", "value": "remove"}]


@pytest.mark.parametrize("custom", [{"messages": []}, {"api_key": "blocked"}, {"enable_thinking": False}])
def test_legacy_custom_cannot_override_protected_or_declared_paths(declared_profile, custom):
    with pytest.raises(ParameterValidationError):
        LegacyInvocationOptions({}, custom_overrides=custom).resolve(declared_profile)
