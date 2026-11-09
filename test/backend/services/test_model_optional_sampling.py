# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Optional outlet sampling must round-trip without inventing provider defaults."""
from copy import deepcopy

import pytest

from contracts.errors.exceptions import ModelOutletValidationError
from contracts.model import ModelOutletPatchRequest, ModelProfilePreviewRequest
from management.services.model import profiles as service
from nexent.core.model_service.profiles.protocol_parameters import connectivity_request
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile


def make_profile():
    profile, _ = service.build_outlet_draft(ModelProfilePreviewRequest(
        selection_mode="manual", request_model_id="custom-model",
        provider_info={"base_url": "https://example.invalid/v1"},
        parameter_values={"temperature": 0.6, "top_p": 0.9}), "tenant")
    data = profile.model_dump(mode="json")
    for rule in data["parameter_rules"]:
        if rule["key"] in {"temperature", "top_p"}:
            rule["schema"] = {"type": "number", "minimum": 0,
                              "maximum": 2 if rule["key"] == "temperature" else 1}
            rule["default_value"] = data["parameter_values"][rule["key"]]
    return ResolvedModelProfile.model_validate(data)


@pytest.mark.parametrize("values", [{"temperature": None}, {"top_p": None},
                                    {"temperature": None, "top_p": None}])
def test_ac003_explicit_empty_draft_omits_sampling_on_wire(values):
    request = ModelProfilePreviewRequest(request_model_id="qwen3.8-flash",
        provider_info={"base_url": "https://example.invalid/v1"}, parameter_values=values)
    original = request.model_dump()
    profile, _ = service.build_outlet_draft(request, "tenant")
    body = connectivity_request(profile)[3]
    for key in values:
        assert key not in profile.parameter_values
        assert key not in body
    assert request.model_dump() == original


@pytest.mark.parametrize("key", ["temperature", "top_p"])
def test_ac003_clearing_saved_default_does_not_reappear_on_second_edit(key):
    profile = make_profile()
    original = deepcopy(profile.model_dump())
    changed = service.apply_outlet_patch(profile, ModelOutletPatchRequest(
        expected_revision=1, parameter_values={key: None}))
    assert key not in changed.parameter_values
    assert key not in connectivity_request(changed)[3]
    reopened = ResolvedModelProfile.model_validate_json(changed.model_dump_json())
    saved_again = service.apply_outlet_patch(reopened, ModelOutletPatchRequest(expected_revision=1))
    assert key not in saved_again.parameter_values
    assert key not in connectivity_request(saved_again)[3]
    other = "top_p" if key == "temperature" else "temperature"
    assert saved_again.parameter_values[other] == original["parameter_values"][other]
    assert profile.model_dump() == original


def test_ac004_explicit_zero_survives_other_sampling_clear():
    changed = service.apply_outlet_patch(make_profile(), ModelOutletPatchRequest(
        expected_revision=1, parameter_values={"temperature": 0, "top_p": None}))
    body = connectivity_request(changed)[3]
    assert body["temperature"] == 0
    assert "top_p" not in body


@pytest.mark.parametrize("key,value", [("temperature", -1), ("temperature", 2.1),
    ("top_p", 1.1), ("top_p", True), ("temperature", "0.7")])
def test_ac004_nonempty_values_keep_the_saved_domain(key, value):
    with pytest.raises(ModelOutletValidationError):
        service.apply_outlet_patch(make_profile(), ModelOutletPatchRequest(
            expected_revision=1, parameter_values={key: value}))


@pytest.mark.parametrize("change", ["fixed", "readonly"])
def test_ac004_empty_cannot_bypass_saved_fixed_or_readonly_rule(change):
    data = make_profile().model_dump(mode="json")
    rule = next(rule for rule in data["parameter_rules"] if rule["key"] == "temperature")
    if change == "fixed":
        rule["fixed_value"] = 0.6
    else:
        rule["editable"] = False
    profile = ResolvedModelProfile.model_validate(data)
    with pytest.raises(ModelOutletValidationError):
        service.apply_outlet_patch(profile, ModelOutletPatchRequest(
            expected_revision=1, parameter_values={"temperature": None}))


def test_ac005_reset_uses_only_declared_defaults():
    data = make_profile().model_dump(mode="json")
    for rule in data["parameter_rules"]:
        if rule["key"] in {"temperature", "top_p"}:
            rule.pop("default_value", None)
    profile = ResolvedModelProfile.model_validate(data)
    changed = service.apply_outlet_patch(profile, ModelOutletPatchRequest(expected_revision=1, reset_parameters=True))
    assert "temperature" not in changed.parameter_values
    assert "top_p" not in changed.parameter_values


def test_ac003_kimi_preference_and_old_required_rule_allow_empty_sampling():
    profile, _ = service.build_outlet_draft(ModelProfilePreviewRequest(
        request_model_id="kimi-k3", provider_info={"base_url":"https://gateway.invalid/v1"},
        parameter_values={"top_p":None}), "tenant")
    assert "top_p" not in profile.parameter_values
    assert "top_p" not in connectivity_request(profile)[3]
    data = profile.model_dump(mode="json")
    rule = next(r for r in data["parameter_rules"] if r["key"]=="top_p")
    rule["required"] = True
    data["parameter_values"]["top_p"] = 0.95
    old = ResolvedModelProfile.model_validate(data)
    cleared = service.apply_outlet_patch(old, ModelOutletPatchRequest(
        expected_revision=1, parameter_values={"top_p":None}))
    assert "top_p" not in cleared.parameter_values
    assert "top_p" not in connectivity_request(cleared)[3]
    assert next(r for r in cleared.parameter_rules if r["key"]=="top_p")["schema"] == rule["schema"]
