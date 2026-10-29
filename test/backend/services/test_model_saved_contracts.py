# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Saved configuration boundaries work before Agent or migration services load."""

from copy import deepcopy

import pytest
from nexent.core.model_service.compatibility.agent_parameters import read_agent_parameter_entry
from nexent.core.model_service.compatibility.invocation_options import LegacyInvocationOptions
from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.protocol_parameters import (
    ensure_outlet_sampling_rules, openai_chat_parameter_rules,
)
from nexent.core.model_service.registry import model_service_references
from nexent.core.models.capacity_budget import (
    CallerMaxTokensOverrideForbidden, CapacityReservePolicy, ContextBudgetCalculator,
    ContextBudgetCapacityMismatch, verify_context_budget_capacity,
)
from nexent.core.models.capacity_resolver import ModelCapacitySnapshot
from management.services.model.outlet_projection import project_saved_outlet
from test.sdk.core.model_service.conftest import protocol_profile  # noqa: F401


@pytest.mark.parametrize("entry", [None, [], {"parameter_values": []},
    {"parameter_values": {}, "temperature": 0}, {"extra_params": [1]}])
def test_invalid_agent_entries_are_rejected_without_mutation(entry):
    original = deepcopy(entry)
    with pytest.raises(ParameterValidationError):
        read_agent_parameter_entry(entry)
    assert entry == original


@pytest.mark.parametrize("custom", [{"flag": None, "max_tokens": 1}, "invalid-shape"])
def test_historical_agent_values_preserve_false_zero_and_custom_shape(custom):
    entry = {"temperature": 0, "top_p": None, "context_window_tokens": 10,
        "extra_params": {"enable_thinking": False, "__custom__": custom}}
    original = deepcopy(entry)
    result = read_agent_parameter_entry(entry)
    expected = {"flag": None} if isinstance(custom, dict) else custom
    assert result == {"parameter_values": {"temperature": 0, "enable_thinking": False},
                      "custom_overrides": expected}
    assert entry == original
    assert read_agent_parameter_entry(result) == result


def test_current_agent_entries_retire_only_outlet_token_limits():
    entry = {"parameter_values": {"temperature": 0, "max_output_tokens": 99},
             "context_window_tokens": 10, "custom_overrides": {"flag": False, "max_tokens": 1}}
    before = deepcopy(entry)
    assert read_agent_parameter_entry(entry) == {
        "parameter_values": {"temperature": 0}, "custom_overrides": {"flag": False}}
    assert entry == before


@pytest.fixture
def saved_profile(protocol_profile):
    data = protocol_profile.model_dump(mode="json")
    data["outlet_id"] = data["connection"]["credential_ref"]["model_id"] = 42
    refs = model_service_references()
    for key in ("auth", "code_converter", "native_converter"):
        data["bindings"][key] = refs[key][0].model_dump(mode="json")
    data["provenance"]["provider_metadata"]["migration"] = {
        "reviewed_revision": None, "unmatched_atoms": ["model", "provider"]}
    data["extra_api_parameters"] = [{"path": "/vendor/flag", "value": False}]
    return protocol_profile.__class__.model_validate(data)


def test_saved_projection_keeps_values_and_revision_without_catalog_recomposition(saved_profile):
    row = encode_resolved_model_profile(saved_profile, registered_references=model_service_references())
    before = deepcopy(row)
    result = project_saved_outlet(row)
    assert result["extra_params"] == {"enable_thinking": False, "__custom__": {"vendor": {"flag": False}}}
    assert result["migration_review_required"] is True
    assert result["migration_details"]["unmatched_atoms"] == ["model", "provider"]
    assert result["reasoning_capability"]["source"] == "operator"
    assert result["reasoning_capability"]["controls"][1]["type"] == "budget_tokens"
    assert row == before and "api_key" not in result
    data = saved_profile.model_dump(mode="json")
    data["provenance"]["provider_metadata"]["migration"]["reviewed_revision"] = saved_profile.config_revision
    reviewed = saved_profile.__class__.model_validate(data)
    row = encode_resolved_model_profile(reviewed, registered_references=model_service_references())
    assert project_saved_outlet(row)["migration_review_required"] is False
    row["config_revision"] += 1
    assert project_saved_outlet(row)["migration_review_required"] is True


def test_projection_reports_invalid_and_non_profile_rows():
    assert project_saved_outlet({"model_type": "llm"}) is None
    failure = {"category": "LEGACY_OUTLET_INVALID"}
    assert project_saved_outlet({"resolved_profile": {"migration_error": failure}}) == {
        "migration_status": "failed", "migration_diagnostic": failure}
    assert project_saved_outlet({"profile_schema_version": 1}) == {
        "migration_status": "failed", "migration_diagnostic": {"category": "PROFILE_STORAGE_INVALID"}}


def test_protocol_sampling_upgrade_preserves_provider_restrictions(protocol_profile):
    data = protocol_profile.model_dump(mode="json")
    data["parameter_rules"].extend(r for r in openai_chat_parameter_rules() if r["key"] == "temperature")
    data["parameter_rules"] = [r for r in data["parameter_rules"] if r["key"] != "top_p"]
    rule = next(r for r in data["parameter_rules"] if r["key"] == "temperature")
    rule.update(source={"ref": "openai_chat_protocol_parameters_v1", "version": 1},
                visible=False, allowed_scopes=["outlet"])
    old = protocol_profile.__class__.model_validate(data)
    updated = ensure_outlet_sampling_rules(old)
    fields = {r["key"]: r for r in updated.parameter_rules}
    assert fields["temperature"]["visible"] and "conversation" in fields["temperature"]["allowed_scopes"]
    assert fields["top_p"]["api_binding"]["path"] == "/top_p"
    assert next(r for r in old.parameter_rules if r["key"] == "temperature")["visible"] is False
    rule["source"] = {"ref": "operator_rule", "version": 1}
    restricted = protocol_profile.__class__.model_validate(data)
    assert next(r for r in ensure_outlet_sampling_rules(restricted).parameter_rules
                if r["key"] == "temperature") == rule


@pytest.fixture
def budget(protocol_profile):
    capacity = ModelCapacitySnapshot(provider=protocol_profile.identity.provider_id,
        model_name=protocol_profile.identity.request_model_id, context_window_tokens=32768,
        max_input_tokens=None, max_output_tokens=8192, default_output_reserve_tokens=4096,
        requested_output_tokens=4096, provider_input_limit_tokens=28672, tokenizer_family=None,
        counting_mode="estimated", unknown_capabilities=[], field_sources={},
        capability_profile_version=None, fingerprint="controlled-capacity")
    return ContextBudgetCalculator().calculate_context_budget(
        capacity_snapshot=capacity, reserve_policy=CapacityReservePolicy())


@pytest.mark.parametrize("field,key", [("capacity_fingerprint", "w1_fingerprint"),
    ("provider", "provider"), ("model_name", "model_name")])
def test_stale_budget_identity_reports_exact_mismatched_field(budget, field, key):
    with pytest.raises(ContextBudgetCapacityMismatch) as error:
        verify_context_budget_capacity(budget_snapshot=budget, capacity_snapshot={field: "foreign"})
    assert error.value.field == key
    assert error.value.expected == "foreign"
    assert error.value.actual == getattr(budget, key)


def test_budget_alias_uses_trusted_limit_and_rejects_caller_override(protocol_profile, budget):
    for capacity in (None, {}, {"provider": budget.provider.upper(), "model_name": budget.model_name}):
        verify_context_budget_capacity(budget_snapshot=budget, capacity_snapshot=capacity)
    original = deepcopy(protocol_profile.model_dump())
    result = LegacyInvocationOptions({}, context_budget_snapshot=budget).resolve(protocol_profile)
    assert result.parameter_values["max_output_tokens"] == budget.requested_output_tokens
    assert protocol_profile.model_dump() == original
    with pytest.raises(CallerMaxTokensOverrideForbidden) as error:
        LegacyInvocationOptions({"max_tokens": 1}, context_budget_snapshot=budget).resolve(protocol_profile)
    assert error.value.snapshot_value == budget.requested_output_tokens and error.value.caller_value == 1
    with pytest.raises(TypeError, match="context_budget_snapshot"):
        LegacyInvocationOptions({}, context_budget_snapshot="invalid").resolve(protocol_profile)
