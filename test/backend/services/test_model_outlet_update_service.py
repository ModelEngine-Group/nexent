# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Saved-outlet updates preserve omitted fields and enforce rules and revisions."""

from unittest.mock import Mock

import pytest
from contracts.errors.exceptions import ModelOutletConflictError, ModelOutletValidationError
from contracts.model import ModelOutletPatchRequest
from management.services.model.profiles import apply_outlet_patch, build_outlet_draft, update_model_outlet

from test.backend.services.test_model_profile_service import draft_request, outlet_database  # noqa: F401


@pytest.fixture
def saved_profile():
    profile, _ = build_outlet_draft(draft_request(parameter_values={"enable_thinking": True,
                                               "reasoning_budget_tokens": 64}), "tenant")
    data = profile.model_dump()
    data["outlet_id"] = data["connection"]["credential_ref"]["model_id"] = 42
    return profile.__class__.model_validate(data)


def test_partial_parameter_update_does_not_drop_unmentioned_values(saved_profile):
    updated = apply_outlet_patch(saved_profile, ModelOutletPatchRequest(expected_revision=1,
        parameter_values={"reasoning_budget_tokens": 32}))
    assert updated.parameter_values == {"enable_thinking": True, "reasoning_budget_tokens": 32}
    assert saved_profile.parameter_values["reasoning_budget_tokens"] == 64


def test_dependency_failure_requires_explicit_delete(saved_profile):
    with pytest.raises(ModelOutletValidationError) as caught:
        apply_outlet_patch(saved_profile, ModelOutletPatchRequest(expected_revision=1,
            parameter_values={"enable_thinking": False}))
    assert caught.value.category == "PARAMETER_DEPENDENCY"
    updated = apply_outlet_patch(saved_profile, ModelOutletPatchRequest(expected_revision=1,
        parameter_values={"enable_thinking": False}, delete_parameters=["reasoning_budget_tokens"]))
    assert updated.parameter_values == {"enable_thinking": False}


@pytest.mark.parametrize("body", [
    {"parameter_values": {"enable_thinking": None}},
    {"parameter_values": {"unknown": False}},
    {"delete_parameters": ["enable_thinking", "enable_thinking"]},
    {"delete_parameters": ["enable_thinking"], "parameter_values": {"enable_thinking": False}},
    {"connection": None}, {"connection": {"base_url": "file:///tmp/model"}},
    {"extra_api_parameters": None},
])
def test_invalid_patch_is_rejected_before_mutating_snapshot(saved_profile, body):
    before = saved_profile.model_dump()
    with pytest.raises(ModelOutletValidationError):
        apply_outlet_patch(saved_profile, ModelOutletPatchRequest(expected_revision=1, **body))
    assert saved_profile.model_dump() == before


def test_update_uses_saved_rules_keeps_omitted_key_and_cas(outlet_database, saved_profile, monkeypatch):
    import management.services.model.profiles as service

    db, _ = outlet_database
    db.get_resolved_model_record.return_value = saved_profile
    db.update_resolved_model_record = Mock(return_value=2)
    monkeypatch.setattr(service, "get_model_profile_catalog", lambda: pytest.fail("No live catalog update"))
    result = update_model_outlet(42, ModelOutletPatchRequest(expected_revision=1,
        parameter_values={"reasoning_budget_tokens": 32}), "user", "tenant")
    assert result["config_revision"] == result["profile"]["config_revision"] == 2
    assert db.update_resolved_model_record.call_args.args[1:] == (1, "user", "tenant")
    assert "api_key" not in db.update_resolved_model_record.call_args.kwargs
    assert result["has_credential"] is True


def test_explicit_credential_delete_is_not_omission(outlet_database, saved_profile):
    db, _ = outlet_database
    db.get_resolved_model_record.return_value = saved_profile
    db.update_resolved_model_record = Mock(return_value=2)
    update_model_outlet(42, ModelOutletPatchRequest(expected_revision=1, api_key=None), "user", "tenant")
    assert db.update_resolved_model_record.call_args.kwargs["api_key"] is None


def test_stale_or_missing_outlet_never_writes(outlet_database, saved_profile):
    db, _ = outlet_database
    db.get_resolved_model_record.return_value = saved_profile
    db.update_resolved_model_record = Mock()
    with pytest.raises(ModelOutletConflictError):
        update_model_outlet(42, ModelOutletPatchRequest(expected_revision=2), "user", "tenant")
    db.get_resolved_model_record.return_value = None
    with pytest.raises(LookupError):
        update_model_outlet(42, ModelOutletPatchRequest(expected_revision=1), "user", "other")
    db.update_resolved_model_record.assert_not_called()
