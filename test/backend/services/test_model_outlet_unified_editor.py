# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""AEU: one effective configuration for onboarding, editing, checking and save."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from contracts.errors.exceptions import ModelOutletConflictError, ModelOutletValidationError
from contracts.model import ModelOutletCreateRequest, ModelOutletPatchRequest, ModelProfilePreviewInput, ModelProfilePreviewRequest
from management.services.model import profiles as service
from nexent.core.model_service.profiles.protocol_parameters import connectivity_request
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile


def draft(provider="alibaba-cn", **changes):
    catalog = service.get_model_profile_catalog()
    model = "alibaba/qwen3.7-plus"
    data = dict(selection_mode="manual", request_model_id="qwen3.7-plus",
        model_profile={"key": model, "revision": catalog.models[model].revision},
        provider_profile={"key": provider, "revision": catalog.providers[provider].revision} if provider else None,
        catalog_revision=catalog.revision, provider_info={"base_url": "https://gateway.invalid/v1"},
        parameter_values={"temperature": 0.7, "top_p": 1.0, "enable_thinking": True,
                          "reasoning_budget_tokens": 1024} if provider else {"temperature": 0.7})
    data.update(changes)
    return ModelProfilePreviewRequest(**data)


def saved(request=None):
    profile, _ = service.build_outlet_draft(request or draft(), "tenant")
    data = profile.model_dump(mode="json")
    data["outlet_id"] = 42
    data["connection"]["credential_ref"]["model_id"] = 42
    return ResolvedModelProfile.model_validate(data)


def selection(request):
    return {"catalog_revision": request.catalog_revision,
            "model_profile": request.model_profile, "provider_profile": request.provider_profile}


def test_aeu_catalog_only_preview_matches_complete_configuration():
    request = draft(context_limits={})
    data = request.model_dump(exclude_unset=True)
    data["provider_info"]["base_url"] = ""
    data["request_model_id"] = ""
    data["display_name"] = ""
    incomplete = service.preview_model_profile(ModelProfilePreviewInput(**data), "tenant")
    complete = service.preview_model_profile(request, "tenant")
    for field in ("selected", "field_specs", "parameter_values", "capabilities"):
        assert incomplete[field] == complete[field]
    direct, _ = service.build_outlet_draft(request, "tenant")
    assert incomplete["capabilities"]["context"] == direct.capabilities.context.model_dump(mode="json")
    assert incomplete["capabilities"]["context"]["output_limit"] > 0
    explicit_clear = request.model_copy(update={"context_limits": request.context_limits.model_copy(update={"output_limit": None})})
    assert service.preview_model_profile(explicit_clear, "tenant")["capabilities"]["context"]["output_limit"] is None
    with pytest.raises(ValidationError):
        ModelOutletCreateRequest(**data)


def test_aeu_edit_preview_retains_frozen_rules_without_catalog(monkeypatch):
    profile = saved()
    monkeypatch.setattr(service, "_load_validation_outlet", lambda *_: (profile, "private", {}))
    monkeypatch.setattr(service, "get_model_profile_catalog", lambda: pytest.fail("No implicit catalog refresh"))
    patch = ModelOutletPatchRequest(expected_revision=1, parameter_values={"reasoning_budget_tokens": 512})
    preview = service.preview_outlet_patch(42, patch, "tenant")
    assert preview["field_specs"] == profile.parameter_rules
    assert preview["parameter_values"]["reasoning_budget_tokens"] == 512
    assert "private" not in str(preview)


def test_aeu_explicit_reselection_matches_create_and_preserves_identity():
    request = draft()
    old = saved(draft(provider=None))
    patch = ModelOutletPatchRequest(expected_revision=1, profile_selection=selection(request),
        parameter_values=request.parameter_values)
    changed = service.apply_outlet_patch(old, patch)
    created, _ = service.build_outlet_draft(request, "tenant")
    assert changed.parameter_rules == created.parameter_rules
    assert changed.parameter_values == created.parameter_values
    assert connectivity_request(changed)[3] == connectivity_request(created)[3]
    assert changed.outlet_id == old.outlet_id == 42
    assert changed.connection.credential_ref.model_id == 42
    assert changed.identity.tenant_id == "tenant"
    assert old.provider_key is None


def test_aeu_incompatible_values_are_reported_without_changing_saved_values():
    request = draft(provider=None, parameter_values={"temperature": 0.7, "enable_thinking": True, "reasoning_effort": "high"},
                    thinking_mode="effort", thinking_control="enable_thinking")
    old = saved(request)
    before = deepcopy(old.model_dump())
    replacement = draft()
    with pytest.raises(ModelOutletValidationError) as error:
        service.apply_outlet_patch(old, ModelOutletPatchRequest(expected_revision=1,
            profile_selection=selection(replacement)))
    assert error.value.path == "/reasoning_effort"
    assert old.model_dump() == before
    changed = service.apply_outlet_patch(old, ModelOutletPatchRequest(expected_revision=1,
        profile_selection=selection(replacement), delete_parameters=["reasoning_effort"],
        thinking_mode="budget_tokens", parameter_values={"enable_thinking": True, "reasoning_budget_tokens": 512}))
    assert "reasoning_effort" not in changed.parameter_values
    assert changed.parameter_values["reasoning_budget_tokens"] == 512


def test_aeu_reselection_rejects_stale_catalog():
    old = saved()
    picked = selection(draft())
    picked["catalog_revision"] = "stale"
    with pytest.raises(ModelOutletConflictError):
        service.apply_outlet_patch(old, ModelOutletPatchRequest(expected_revision=1, profile_selection=picked))


def test_aeu_saved_preview_rejects_stale_revision_and_wrong_tenant(monkeypatch):
    old = saved()
    def load(model_id, tenant):
        if model_id != 42 or tenant != "tenant":
            raise LookupError("MODEL_OUTLET_NOT_FOUND")
        return old, None, {}
    monkeypatch.setattr(service, "_load_validation_outlet", load)
    with pytest.raises(ModelOutletConflictError):
        service.preview_outlet_patch(42, ModelOutletPatchRequest(expected_revision=2), "tenant")
    with pytest.raises(LookupError):
        service.preview_outlet_patch(42, ModelOutletPatchRequest(expected_revision=1), "other")


def test_aeu_switch_to_custom_retains_registered_controls_as_manual_configuration():
    original = saved()
    request = draft(provider=None)
    changed = service.apply_outlet_patch(original, ModelOutletPatchRequest(expected_revision=1,
        profile_selection=selection(request), thinking_control="profile_default", thinking_mode="budget_tokens"))
    assert changed.provider_key is None
    assert changed.parameter_values["enable_thinking"] is True
    assert changed.parameter_values["reasoning_budget_tokens"] == 1024
    assert connectivity_request(original)[3] == connectivity_request(changed)[3]
    assert changed.provenance.provider_metadata["operator_thinking"]["preset"] == "enable_thinking"
    assert next(rule for rule in changed.parameter_rules if rule["key"] == "reasoning_budget_tokens")["source"]["ref"] == "operator_thinking_degree_v1"


def test_aeu_restore_frozen_defaults_preserves_fixed_values_and_explicit_zero(monkeypatch):
    profile = saved()
    data = profile.model_dump(mode="json")
    for rule in data["parameter_rules"]:
        if rule["key"] == "temperature":
            rule["default_value"] = 0
        if rule["key"] == "top_p":
            rule["fixed_value"] = 0.95
    data["parameter_values"].update(temperature=1.2, top_p=0.95)
    original = ResolvedModelProfile.model_validate(data)
    monkeypatch.setattr(service, "get_model_profile_catalog", lambda: pytest.fail("Reset must retain the saved version"))
    changed = service.apply_outlet_patch(original, ModelOutletPatchRequest(expected_revision=1, reset_parameters=True))
    assert changed.parameter_values["temperature"] == 0
    assert changed.parameter_values["top_p"] == 0.95
    assert original.parameter_values["temperature"] == 1.2
    assert changed.provenance.atomic_refs == original.provenance.atomic_refs
    with pytest.raises(ModelOutletValidationError):
        service.apply_outlet_patch(original, ModelOutletPatchRequest(expected_revision=1,
            reset_parameters=True, parameter_values={"top_p": 0.5}))
    with pytest.raises(ModelOutletValidationError):
        service.apply_outlet_patch(original, ModelOutletPatchRequest(expected_revision=1,
            reset_parameters=True, delete_parameters=["temperature"]))
