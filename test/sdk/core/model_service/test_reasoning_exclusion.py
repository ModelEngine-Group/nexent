# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exact provider declarations enforce exclusive reasoning controls without new machinery."""

import pytest

from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.profiles.composition import compose_provider_model_policy
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.outlet_resolution import construct_resolved_model_profile
from nexent.core.model_service.profiles.parameter_rules import overlay_profile_parameters, validate_saved_parameter_values
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.resolved_profile import ConnectionRules, ContextConfiguration, OutletConnection
from nexent.core.model_service.profiles.resolver import load_profile_catalog
from nexent.core.model_service.registry import model_service_references


@pytest.fixture
def resolve():
    catalog, refs = load_profile_catalog(), model_service_references()

    def policy(values):
        return compose_provider_model_policy(catalog, provider_key="alibaba-cn", request_model_id="qwen3.8-max",
            model_profile_key=None, base_bindings={key: refs[key][0].model_dump() for key in
                ("protocol", "auth", "adapter", "code_converter", "native_converter")},
            base_instruction=VersionedReference(ref="system_only_v1", version=1),
            registered_references=refs, submitted_values=values)

    def profile(values):
        return construct_resolved_model_profile(policy(values), catalog, tenant_id="tenant", display_name="controlled",
            model_type="llm", provider_id="alibaba",
            connection=OutletConnection(base_url="https://example.test/v1", ssl_verify=True, timeout_seconds=5,
                concurrency_limit=None, credential_ref={"kind":"model_record", "model_id":None}),
            connection_rules=ConnectionRules(credential_kind="model_record", relative_path="/chat/completions",
                method="POST", headers={}),
            context_configuration=ContextConfiguration(output_reserve_tokens=None, tokenizer_family=None,
                capacity_source="profile", capability_profile_version=None), registered_references=refs)
    return policy, profile


def test_exact_qwen_max_rejects_effort_and_budget_together_in_default_composition(resolve):
    policy, _ = resolve
    with pytest.raises(ParameterValidationError, match="PARAMETER_DEPENDENCY"):
        policy({"enable_thinking":True, "reasoning_effort":"low", "reasoning_budget_tokens":1024})


def test_exact_qwen_max_rejects_conflicting_saved_values_and_conversation_overlay(resolve):
    policy, profile = resolve
    with pytest.raises(ParameterValidationError, match="PARAMETER_DEPENDENCY"):
        validate_saved_parameter_values(policy({}).parameter_rules,
            {"enable_thinking":True, "reasoning_effort":"low", "reasoning_budget_tokens":1024})
    saved = profile({"enable_thinking":True, "reasoning_effort":"low"})
    with pytest.raises(ParameterValidationError, match="PARAMETER_DEPENDENCY"):
        overlay_profile_parameters(saved, {"reasoning_budget_tokens":1024}, scope="conversation")


@pytest.mark.parametrize("parameters,expected,absent", [
    ({"reasoning_effort":"low"}, "reasoning_effort", "thinking_budget"),
    ({"reasoning_budget_tokens":1024}, "thinking_budget", "reasoning_effort"),
])
def test_each_qwen_max_reasoning_control_alone_has_its_declared_wire_mapping(resolve, parameters, expected, absent):
    _, profile = resolve
    saved = profile({"enable_thinking":True, **parameters})
    request = ModelRequest(request_id="exclusive-controls", outlet_id=saved.outlet_id,
        config_revision=saved.config_revision, messages=[ModelMessage(semantic_role="user")])
    wire = OpenAIChatAdapter().prepare_http_request(request, saved).json_body
    assert wire[expected] == next(iter(parameters.values())) and absent not in wire


def test_disabling_thinking_drops_inherited_budget_with_composite_condition(resolve):
    _, profile = resolve
    saved = profile({"enable_thinking":True, "reasoning_budget_tokens":1024})
    updated = overlay_profile_parameters(saved, {"enable_thinking":False}, scope="conversation")
    assert updated.parameter_values == {"enable_thinking":False}
    assert saved.parameter_values == {"enable_thinking":True, "reasoning_budget_tokens":1024}
    with pytest.raises(ParameterValidationError, match="PARAMETER_DEPENDENCY"):
        overlay_profile_parameters(saved, {"enable_thinking":False, "reasoning_budget_tokens":1024}, scope="conversation")


@pytest.mark.parametrize("reverse", [False, True])
def test_disable_thinking_removes_transitive_inherited_values_in_dependency_order(openai_profile, reverse):
    from copy import deepcopy

    def declaration(key, schema, path, condition=None):
        return {"key":key, "schema":schema, "visible":True, "editable":True, "required":False,
            "allowed_scopes":["outlet","conversation"], "ui_group":"reasoning", "owner":"combination",
            "source":{"ref":"controlled-chain"}, "condition":condition,
            "api_binding":{"path":path,"transform_ref":"identity_v1","transform_version":1}}
    rules = [
        declaration("enable_thinking", {"type":"boolean"}, "/enable_thinking"),
        declaration("reasoning_budget_tokens", {"type":"integer"}, "/thinking_budget",
            {"key":"enable_thinking","op":"eq","value":True}),
        declaration("vendor_detail", {"type":"string"}, "/vendor_detail",
            {"key":"reasoning_budget_tokens","op":"exists","value":True}),
    ]
    data = openai_profile.model_dump()
    data["parameter_rules"] = list(reversed(rules)) if reverse else rules
    data["parameter_values"] = {"enable_thinking":True,"reasoning_budget_tokens":1024,"vendor_detail":"verbose"}
    data["capabilities"]["reasoning"]["controls"] = [
        {"mode":"toggle","parameter_key":"enable_thinking","values":[False,True]}]
    saved = type(openai_profile).model_validate(data)
    original = deepcopy(saved.parameter_values)
    updated = overlay_profile_parameters(saved, {"enable_thinking":False}, scope="conversation")
    assert updated.parameter_values == {"enable_thinking":False}
    assert saved.parameter_values == original
    with pytest.raises(ParameterValidationError, match="PARAMETER_DEPENDENCY"):
        overlay_profile_parameters(saved, {"enable_thinking":False,"vendor_detail":"explicit"}, scope="conversation")
