# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Conversation choices preserve explicit values, defaults, revisions and resource boundaries."""

from copy import deepcopy
from types import ModuleType
from unittest.mock import Mock

import pytest
from consts.exceptions import ModelOutletValidationError
from consts.model import ConversationModelPreferencePatch
from services import conversation_model_preferences_service as service
from services.model_profile_service import build_outlet_draft

from test.backend.services.test_model_profile_service import draft_request


@pytest.fixture
def profile():
    value, _ = build_outlet_draft(draft_request(parameter_values={"enable_thinking": True,
        "reasoning_budget_tokens": 64}), "tenant")
    return value


def test_zero_false_and_explicit_null_are_not_defaulted(profile):
    original = deepcopy(profile.model_dump())
    merged = service.merge_model_preferences(profile, {"temperature": 0})
    assert merged.parameter_values["temperature"] == 0
    assert merged.parameter_values["reasoning_budget_tokens"] == 64
    assert profile.model_dump() == original
    assert service.merge_model_preferences(profile, {"temperature": None}).parameter_values["temperature"] is None


def test_thinking_off_excludes_inherited_budget_but_rejects_explicit_conflict(profile):
    disabled = service.merge_model_preferences(profile, {"enable_thinking": False})
    assert disabled.parameter_values["enable_thinking"] is False
    assert "reasoning_budget_tokens" not in disabled.parameter_values
    original = deepcopy(profile.model_dump())
    with pytest.raises(ModelOutletValidationError) as error:
        service.merge_model_preferences(profile, {"enable_thinking": False, "reasoning_budget_tokens": 64})
    assert error.value.category == "PARAMETER_DEPENDENCY"
    assert profile.model_dump() == original


def test_missing_saved_value_is_not_replaced_with_a_creation_default(profile):
    data = profile.model_dump()
    for rule in data["parameter_rules"]:
        if rule["key"] == "temperature":
            rule["default_value"] = 0.9
    data["parameter_values"].pop("temperature", None)
    changed = profile.__class__.model_validate(data)
    assert "temperature" not in service.merge_model_preferences(changed, {}).parameter_values


@pytest.fixture
def persistence(monkeypatch, profile):
    import sys

    store = ModuleType("database.conversation_model_preferences_db")
    store.model_preferences = Mock(return_value={"version": 4,
        "model_parameter_preferences": {"42": {"temperature": 0.2}, "43": {"max_output_tokens": 10}}})
    outlet = ModuleType("database.model_outlet_db")
    outlet.get_resolved_model_record = Mock(return_value=profile)
    monkeypatch.setitem(sys.modules, "database.conversation_model_preferences_db", store)
    monkeypatch.setitem(sys.modules, "database.model_outlet_db", outlet)
    return store.model_preferences, outlet.get_resolved_model_record


def test_patch_updates_only_explicit_values_and_preserves_other_outlet_preferences(persistence):
    store, _ = persistence
    request = ConversationModelPreferencePatch(expected_version=4, parameter_values={"temperature": 0})
    service.patch_model_preferences(1, 42, request, "owner", "tenant")
    args = store.call_args
    assert args.args == (1, "owner") and args.kwargs["expected_version"] == 4
    assert args.kwargs["outlet_id"] == 42
    assert args.kwargs["resolve_values"]({"max_output_tokens": 100}) == {"temperature": 0, "max_output_tokens": 100}


def test_explicit_delete_removes_an_invalid_old_key_without_modifying_outlet(persistence):
    store, _ = persistence
    service.patch_model_preferences(1, 42, ConversationModelPreferencePatch(expected_version=4,
        delete_parameters=["retired"]), "owner", "tenant")
    assert store.call_args.kwargs["resolve_values"]({"retired": True}) == {}


@pytest.mark.parametrize("body", [{"parameter_values": {"temperature": 0}, "delete_parameters": ["temperature"]},
                                  {"delete_parameters": ["temperature", "temperature"]}])
def test_ambiguous_patch_is_rejected_before_update(persistence, body):
    store, _ = persistence
    with pytest.raises(ModelOutletValidationError):
        service.patch_model_preferences(1, 42, ConversationModelPreferencePatch(expected_version=4, **body), "owner", "tenant")
    assert store.call_count == 1


def test_other_tenant_or_missing_outlet_cannot_receive_preferences(persistence):
    store, outlet = persistence
    outlet.return_value = None
    with pytest.raises(ModelOutletValidationError):
        service.patch_model_preferences(1, 42, ConversationModelPreferencePatch(expected_version=4), "owner", "other-tenant")
    assert outlet.call_args.args == (42, "other-tenant") and store.call_count == 1


def test_read_returns_invalid_values_and_diagnostic_for_explicit_repair(persistence):
    store, _ = persistence
    store.return_value = {"version": 4, "model_parameter_preferences": {"42": {"retired": False}}}
    result = service.read_model_preference_view(1, 42, "owner", "tenant")
    assert result["parameter_values"] == {"retired": False}
    assert result["issues"] == [{"category": "PARAMETER_UNKNOWN", "field": "/retired"}]


@pytest.mark.parametrize("limit_field", ["output_limit", "combined_window"])
def test_output_preferences_respect_saved_capacity_limits_without_changing_defaults(profile, limit_field):
    data = profile.model_dump()
    data["capabilities"]["context"].update(combined_window=200000, input_limit=None, output_limit=None)
    data["capabilities"]["context"][limit_field] = 1024
    limited = profile.__class__.model_validate(data)
    assert service.merge_model_preferences(limited, {"max_output_tokens": 1024}).parameter_values["max_output_tokens"] == 1024
    with pytest.raises(ModelOutletValidationError) as error:
        service.merge_model_preferences(limited, {"max_output_tokens": 1025})
    assert error.value.category == "PARAMETER_LIMIT_EXCEEDED"
    assert limited.parameter_values == profile.parameter_values


def test_changed_capacity_reports_invalid_saved_preference_without_deleting_it(persistence, profile):
    store, outlet = persistence
    data = profile.model_dump()
    data["capabilities"]["context"]["output_limit"] = 1024
    outlet.return_value = profile.__class__.model_validate(data)
    store.return_value = {"version": 4, "model_parameter_preferences": {"42": {"max_output_tokens": 1025}}}
    result = service.read_model_preference_view(1, 42, "owner", "tenant")
    assert result["parameter_values"] == {"max_output_tokens": 1025}
    assert result["issues"] == [{"category": "PARAMETER_LIMIT_EXCEEDED", "field": "/max_output_tokens"}]


@pytest.mark.parametrize("locked", ["editable", "allowed_scopes"])
def test_conversation_cannot_store_locked_value_even_when_identical_to_outlet(profile, locked):
    data = profile.model_dump()
    for rule in data["parameter_rules"]:
        if rule["key"] == "enable_thinking":
            rule[locked] = False if locked == "editable" else ["outlet"]
    original = profile.__class__.model_validate(data)
    with pytest.raises(ModelOutletValidationError) as error:
        service.merge_model_preferences(original, {"enable_thinking": True})
    assert error.value.category == "PARAMETER_NOT_EDITABLE"


@pytest.mark.parametrize("values", [{"temperature": 0, "top_p": 1}, {"enable_thinking": False}])
def test_su_ac_02_first_turn_uses_same_profile_validation(persistence, profile, monkeypatch, values):
    from management.services.model import run_controls
    monkeypatch.setattr(run_controls, "validate_selected_model", Mock())
    service.validate_model_preferences({"42": values}, "tenant", allowed_model_ids=[42])
    assert profile.parameter_values["enable_thinking"] is True


@pytest.mark.parametrize("key", ["0", "-1", "1.5", "042", "true"])
def test_su_ac_05_invalid_outlet_identity_rejected_before_lookup(persistence, monkeypatch, key):
    from management.services.model import run_controls
    lookup = Mock()
    monkeypatch.setattr(run_controls, "validate_selected_model", lookup)
    with pytest.raises(ModelOutletValidationError):
        service.validate_model_preferences({key: {"temperature": 0}}, "tenant")
    lookup.assert_not_called()


def test_su_ac_05_draft_cannot_bypass_agent_scope(persistence, monkeypatch):
    from consts.exceptions import ForbiddenError
    from management.services.model import run_controls
    lookup = Mock()
    monkeypatch.setattr(run_controls, "validate_selected_model", lookup)
    with pytest.raises(ForbiddenError):
        service.validate_model_preferences({"42": {"temperature": 0}}, "tenant", allowed_model_ids=[43])
    lookup.assert_not_called()


def test_su_ac_05_draft_rejects_dependency_conflicts(persistence, monkeypatch):
    from management.services.model import run_controls
    monkeypatch.setattr(run_controls, "validate_selected_model", Mock())
    with pytest.raises(ModelOutletValidationError):
        service.validate_model_preferences({"42": {"enable_thinking": False, "reasoning_budget_tokens": 64}}, "tenant")
