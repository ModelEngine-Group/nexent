# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Reuse current W1/W2 contracts at the compatibility request boundary."""

from types import SimpleNamespace

import pytest
from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
from nexent.core.model_service.compatibility.invocation_options import LegacyInvocationOptions
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from nexent.core.models.capacity_budget import (
    CallerMaxTokensOverrideForbidden,
    CapacityReservePolicy,
    ContextBudgetCalculator,
    ContextBudgetCapacityMismatch,
    ContextBudgetFingerprintMismatch,
)
from nexent.core.models.capacity_resolver import ModelCapacitySnapshot


@pytest.fixture
def budget():
    capacity = ModelCapacitySnapshot(
        provider="alibaba", model_name="qwen3.5-plus", context_window_tokens=32768,
        max_input_tokens=None, max_output_tokens=8192, default_output_reserve_tokens=4096,
        requested_output_tokens=4096, provider_input_limit_tokens=28672, tokenizer_family=None,
        counting_mode="estimated", unknown_capabilities=[], field_sources={},
        capability_profile_version=None, fingerprint="w1-test",
    )
    return ContextBudgetCalculator().calculate_context_budget(
        capacity_snapshot=capacity, reserve_policy=CapacityReservePolicy(),
    ).model_dump()


@pytest.fixture
def model(openai_profile, budget):
    snapshot = openai_profile.model_dump()
    snapshot["parameter_rules"] = [rule for rule in snapshot["parameter_rules"] if rule["key"] != "max_output_tokens"]
    snapshot["parameter_rules"].append({
        "key": "max_output_tokens", "schema": {"type": "integer", "minimum": 1},
        "visible": True, "editable": True, "required": False,
        "allowed_scopes": ["outlet"], "ui_group": "generation", "owner": "provider",
        "source": {"ref": "controlled_fixture", "version": 1},
        "default_value": 2048,
        "api_binding": {"path": "/max_tokens", "transform_ref": "identity_v1", "transform_version": 1},
    })
    snapshot["parameter_values"]["max_output_tokens"] = 2048
    return LegacyChatModel(
        ResolvedModelProfile.model_validate(snapshot), SimpleNamespace(),
        context_budget_snapshot=budget,
        capacity_snapshot={"capacity_fingerprint": "w1-test", "provider": "alibaba", "model_name": "qwen3.5-plus"},
    )


def test_budget_fills_declared_output_cap_without_changing_outlet(model, mocker):
    stream = mocker.patch.object(model.service, "stream", create=True, side_effect=RuntimeError("prepared"))
    with pytest.raises(RuntimeError, match="prepared"):
        model([{"role": "user", "content": "hello"}])
    request, effective = stream.call_args.args
    assert effective.parameter_values["max_output_tokens"] == 4096
    assert model.profile.parameter_values["max_output_tokens"] == 2048
    assert request.messages[0].content_parts == [{"type": "text", "text": "hello"}]


@pytest.mark.parametrize("overrides", [{"max_tokens": 4095}, {"max_output_tokens": 4097}])
def test_caller_cannot_override_trusted_output_cap(model, overrides):
    with pytest.raises(CallerMaxTokensOverrideForbidden):
        model([{"role": "user", "content": "hello"}], **overrides)
    assert model.last_attempt_id is None


@pytest.mark.parametrize("field,value", [
    ("capacity_fingerprint", "stale"), ("provider", "foreign"), ("model_name", "foreign"),
])
def test_stale_or_cross_model_capacity_rejected_before_send(model, field, value):
    model.capacity_snapshot[field] = value
    with pytest.raises(ContextBudgetCapacityMismatch):
        model([{"role": "user", "content": "hello"}])
    assert model.last_attempt_id is None


def test_budget_identity_checked_even_without_active_capacity(model):
    model.capacity_snapshot = None
    snapshot = model.profile.model_dump()
    snapshot["identity"]["request_model_id"] = "another-model"
    model.profile = ResolvedModelProfile.model_validate(snapshot)
    with pytest.raises(ContextBudgetCapacityMismatch):
        model([{"role": "user", "content": "hello"}])


def test_corrupted_budget_and_invalid_type_rejected(model, budget):
    budget["requested_output_tokens"] = 1
    with pytest.raises(ContextBudgetFingerprintMismatch):
        model([{"role": "user", "content": "hello"}], context_budget_snapshot=budget)
    with pytest.raises(TypeError):
        model([{"role": "user", "content": "hello"}], context_budget_snapshot="invalid")


def test_undeclared_output_binding_is_not_created(model):
    snapshot = model.profile.model_dump()
    snapshot["parameter_rules"] = [r for r in snapshot["parameter_rules"] if r["key"] != "max_output_tokens"]
    snapshot["parameter_values"].pop("max_output_tokens")
    model.profile = ResolvedModelProfile.model_validate(snapshot)
    with pytest.raises(ParameterValidationError, match="LEGACY_OUTPUT_BINDING_REQUIRED"):
        model([{"role": "user", "content": "hello"}])


def test_constructor_detaches_budget_input(model, budget):
    budget["field_sources"]["requested_output_tokens"] = "changed"
    assert model.context_budget_snapshot.field_sources["requested_output_tokens"] != "changed"


def test_builtin_profile_binds_trusted_answer_budget(openai_profile, budget):
    effective = LegacyInvocationOptions({}, context_budget_snapshot=budget).resolve(openai_profile)
    request = ModelRequest(request_id="builtin-budget", outlet_id=effective.outlet_id,
        config_revision=effective.config_revision,
        messages=[ModelMessage(semantic_role="user", content_parts=[{"type": "text", "text": "hello"}])])
    body = OpenAIChatAdapter().prepare_http_request(request, effective).json_body
    assert body["max_tokens"] == budget["requested_output_tokens"]
    assert "max_completion_tokens" not in body
    assert "max_output_tokens" not in openai_profile.parameter_values


@pytest.mark.parametrize("value", [0, -1, 65537, True, 1.5])
def test_builtin_profile_rejects_invalid_answer_budget(openai_profile, value):
    with pytest.raises(ParameterValidationError):
        LegacyInvocationOptions({"max_tokens": value}).resolve(openai_profile)


@pytest.mark.parametrize("provider", ["ALIBABA", "Alibaba"])
def test_migrated_provider_casing_preserves_budget_identity(model, provider):
    model.capacity_snapshot["provider"] = provider
    effective = LegacyInvocationOptions(
        {}, context_budget_snapshot=model.context_budget_snapshot,
        capacity_snapshot=model.capacity_snapshot,
    ).resolve(model.profile)
    assert effective.parameter_values["max_output_tokens"] == 4096
    assert model.capacity_snapshot["provider"] == provider
    assert model.context_budget_snapshot.provider == "alibaba"
