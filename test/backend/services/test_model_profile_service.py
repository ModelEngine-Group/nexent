# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Profile discovery uses the actual local catalog without writes or qualification claims."""

import pytest
from contracts.errors.exceptions import ModelOutletValidationError
from management.services.model.profiles import list_atomic_profiles, list_profile_protocols


@pytest.mark.parametrize("name,kind", [
    ("GLM-V5.2", "llm"), ("route/GLM-v5.2", "llm"),
    ("GLM-4V", "vlm"), ("GLM-4.6V", "vlm"), ("Qwen3-VL-8B", "vlm"),
])
def test_glm_version_prefix_is_distinct_from_visual_suffix(name, kind):
    from contracts.model import _infer_model_type_from_name

    assert _infer_model_type_from_name(name) == kind


@pytest.mark.parametrize("request_id", ["GLM-V5.2", "zhipu/GLM-V5.2"])
def test_glm_optional_version_prefix_matches_without_rewriting_request_id(request_id):
    from management.services.model.profiles import build_outlet_draft

    profile, _ = build_outlet_draft(draft_request(
        request_model_id=request_id, provider_info={"base_url": "https://custom.invalid/v1"}), "tenant")
    assert profile.model_profile_key == "zhipuai/glm-5.2"
    assert profile.identity.request_model_id == request_id


@pytest.mark.parametrize("category,code,scope", [
    ("MODEL_NOT_FOUND", None, "connection"), ("MODEL_SERVICE_UNAVAILABLE", None, "connection"),
    ("MODEL_AUTHENTICATION_ERROR", None, "connection"), ("MODEL_NOT_FOUND", "model_not_found", "model"),
    ("MODEL_REQUEST_INVALID", None, "model"),
])
def test_probe_errors_separate_http_configuration_from_model_parameters(category, code, scope):
    from nexent.core.model_service.contracts import ModelError
    from management.services.model.profiles import _probe_diagnostic

    diagnostic = _probe_diagnostic(ModelError(category=category, provider_code=code, scope="provider", retryable=False,
        request_id="test-request", safe_message="Safe fixed message"))
    assert diagnostic["scope"] == scope
    assert diagnostic["request_id"] == "test-request"


def test_model_family_filter_and_deterministic_pages():
    first = list_atomic_profiles("model", family="QWEN", page_size=2)
    second = list_atomic_profiles("model", family="qwen", page=2, page_size=2)
    assert first["total"] > 2 and first["catalog_revision"] == second["catalog_revision"]
    assert not {x["key"] for x in first["items"]} & {x["key"] for x in second["items"]}
    assert all(x["family"] == "qwen" and x["qualification"] == "reference_only" for x in first["items"])
    assert list_atomic_profiles("model", query="not-an-existing-model")["items"] == []


def test_provider_search_returns_hints_without_credentials():
    result = list_atomic_profiles("provider", query="alibaba")
    assert any(x["key"] == "alibaba-cn" for x in result["items"])
    assert all(set(x) <= {"key", "name", "revision", "catalog_kind", "qualification",
                         "endpoint_hints", "suggested_base_url"} for x in result["items"])
    assert all(x["qualification"] == "reference_only" for x in result["items"])


@pytest.mark.parametrize("kwargs", [{"page": 0}, {"page": True}, {"page_size": 101},
                                    {"query": 1}, {"family": 1}])
def test_invalid_discovery_inputs_are_rejected(kwargs):
    with pytest.raises(ModelOutletValidationError):
        list_atomic_profiles("model", **kwargs)


def test_only_executable_protocols_are_advertised():
    result = list_profile_protocols()
    assert result["items"] == [{"ref": "openai_chat_completions", "version": 1}]
    assert {x["ref"] for x in result["authentication_schemes"]} == {"bearer_token_v1", "no_auth_v1"}


def draft_request(**updates):
    from contracts.model import ModelProfilePreviewRequest

    body = {"provider_info": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
            "request_model_id": "qwen3.5-plus"}
    body.update(updates)
    return ModelProfilePreviewRequest(**body)


def test_preview_matches_exact_sources_and_preserves_endpoint_and_model_id():
    from management.services.model.profiles import build_outlet_draft, preview_model_profile

    request = draft_request(parameter_values={"enable_thinking": False})
    preview = preview_model_profile(request, "tenant")
    assert preview["selected"] == {"model": "alibaba/qwen3.5-plus", "provider": "alibaba-cn"}
    assert preview["parameter_values"] == {"enable_thinking": False}
    profile, candidates = build_outlet_draft(request, "tenant")
    assert profile.identity.tenant_id == "tenant" and profile.identity.model_type == "llm"
    assert profile.connection.base_url == request.provider_info.base_url
    assert profile.identity.request_model_id == request.request_model_id
    assert candidates["providers"] == ["alibaba-cn"]


def test_manual_selection_does_not_rewrite_custom_request_identity():
    from management.services.model.profiles import (
        build_outlet_draft,
        get_model_profile_catalog,
    )

    catalog = get_model_profile_catalog()
    key = "alibaba/qwen3.5-plus"
    request = draft_request(selection_mode="manual", request_model_id="tenant-exact-model",
        provider_info={"base_url": "https://custom.invalid/v1", "provider_id": "tenant-provider"},
        model_profile={"key": key, "revision": catalog.models[key].revision})
    profile, _ = build_outlet_draft(request, "tenant")
    assert profile.provider_key is None and profile.model_profile_key == key
    assert profile.identity.request_model_id == "tenant-exact-model"
    assert profile.identity.provider_id == "tenant-provider"


def test_unmatched_custom_service_returns_unknown_capabilities():
    from management.services.model.profiles import build_outlet_draft

    profile, candidates = build_outlet_draft(draft_request(
        request_model_id="unlisted", provider_info={"base_url": "https://custom.invalid/v1"}), "tenant")
    assert profile.capabilities.tools.status == profile.capabilities.reasoning.status == "unknown"
    assert candidates == {"models": [], "providers": []}


@pytest.mark.parametrize("values", [{"enable_thinking": "yes"}, {"reasoning_budget_tokens": 81921},
                                   {"messages": "forbidden"}])
def test_preview_rejects_invalid_or_undeclared_parameter_values(values):
    from management.services.model.profiles import build_outlet_draft

    with pytest.raises(ModelOutletValidationError) as caught:
        build_outlet_draft(draft_request(parameter_values=values), "tenant")
    assert caught.value.category.startswith("PARAMETER_")
    assert str(caught.value) == "MODEL_OUTLET_INVALID"


@pytest.mark.parametrize("url", ["file:///tmp/models", "https://user:secret@custom.invalid/v1", "https://host.invalid:invalid"])
def test_invalid_connection_rejected_without_echoing_values(url):
    from management.services.model.profiles import build_outlet_draft

    with pytest.raises(ModelOutletValidationError) as caught:
        build_outlet_draft(draft_request(provider_info={"base_url": url}), "tenant")
    assert url not in str(caught.value)


def test_save_requires_current_preview_revision_and_manual_atom_revision():
    from contracts.errors.exceptions import ModelOutletConflictError
    from management.services.model.profiles import build_outlet_draft

    with pytest.raises(ModelOutletValidationError):
        build_outlet_draft(draft_request(), "tenant", require_revision=True)
    with pytest.raises(ModelOutletConflictError):
        build_outlet_draft(draft_request(catalog_revision="stale"), "tenant")
    with pytest.raises(ModelOutletConflictError):
        build_outlet_draft(draft_request(selection_mode="manual",
            model_profile={"key": "alibaba/qwen3.5-plus", "revision": "stale"}), "tenant")


def test_client_cannot_supply_capabilities_or_tenant_identity():
    from pydantic import ValidationError

    for fields in ({"capabilities": {"tools": True}}, {"tenant_id": "other"}, {"bindings": {}}):
        with pytest.raises(ValidationError):
            draft_request(**fields)


@pytest.fixture
def outlet_database(monkeypatch):
    import sys
    from types import ModuleType
    from unittest.mock import Mock

    import management.services.model.profiles as service

    monkeypatch.setattr(service, "_backfill_new_outlet", Mock(return_value=[]))
    database = ModuleType("management.db.model.outlets")
    database.create_resolved_model_record = Mock(return_value=42)
    database.get_resolved_model_record = Mock()
    database.has_model_outlet_credential = Mock(return_value=True)
    legacy = ModuleType("management.db.model.repository")
    legacy.get_models_by_display_name = Mock(return_value=[])
    legacy.get_model_by_model_id = Mock(return_value={"http_headers": {}})
    monkeypatch.setitem(sys.modules, "management.db.model.outlets", database)
    monkeypatch.setitem(sys.modules, "management.db.model.repository", legacy)
    return database, legacy


def test_save_recomposes_instead_of_trusting_preview_and_separates_credentials(outlet_database):
    from contracts.model import ModelOutletCreateRequest
    from management.services.model.profiles import (
        create_model_outlet,
        get_model_profile_catalog,
    )

    database, legacy = outlet_database
    request = ModelOutletCreateRequest(**draft_request().model_dump(), api_key="controlled-key")
    request.catalog_revision = get_model_profile_catalog().revision
    result = create_model_outlet(request, "user", "tenant")
    saved = database.create_resolved_model_record.call_args.args[0]
    assert saved.identity.tenant_id == "tenant" and saved.outlet_id is None
    assert database.create_resolved_model_record.call_args.kwargs["api_key"] == "controlled-key"
    assert result["model_id"] == result["profile"]["connection"]["credential_ref"]["model_id"] == 42
    assert result["profile"]["outlet_id"] == 42 and result["config_revision"] == 1
    assert "controlled-key" not in repr(result)
    legacy.get_models_by_display_name.assert_called_once_with("qwen3.5-plus", "tenant")


def test_custom_header_credentials_are_stored_separately_and_only_names_are_returned(outlet_database):
    from contracts.model import ModelOutletCreateRequest
    from management.services.model.profiles import create_model_outlet, get_model_profile_catalog

    database, _ = outlet_database
    request = ModelOutletCreateRequest(**draft_request(http_headers={"x-gateway": "controlled-header"}).model_dump())
    request.catalog_revision = get_model_profile_catalog().revision
    result = create_model_outlet(request, "user", "tenant")
    assert database.create_resolved_model_record.call_args.kwargs["http_headers"] == {"x-gateway": "controlled-header"}
    assert result["http_header_names"] == ["x-gateway"]
    assert "controlled-header" not in repr(result)
    assert "controlled-header" not in repr(database.create_resolved_model_record.call_args.args[0].model_dump())


def test_duplicate_display_name_fails_before_insert(outlet_database):
    from contracts.errors.exceptions import DuplicateError
    from contracts.model import ModelOutletCreateRequest
    from management.services.model.profiles import (
        create_model_outlet,
        get_model_profile_catalog,
    )

    database, legacy = outlet_database
    legacy.get_models_by_display_name.return_value = [{"model_id": 99}]
    request = ModelOutletCreateRequest(**draft_request().model_dump())
    request.catalog_revision = get_model_profile_catalog().revision
    with pytest.raises(DuplicateError):
        create_model_outlet(request, "user", "tenant")
    database.create_resolved_model_record.assert_not_called()


def test_saved_outlet_read_uses_tenant_database_without_catalog(outlet_database, monkeypatch):
    import management.services.model.profiles as service

    database, _ = outlet_database
    profile, _ = service.build_outlet_draft(draft_request(), "tenant")
    database.get_resolved_model_record.return_value = profile
    monkeypatch.setattr(service, "get_model_profile_catalog", lambda: pytest.fail("Must not recompose saved outlet"))
    result = service.get_model_outlet(42, "tenant")
    database.get_resolved_model_record.assert_called_once()
    assert database.get_resolved_model_record.call_args.args == (42, "tenant")
    assert result["profile"]["identity"]["tenant_id"] == "tenant"
    database.get_resolved_model_record.return_value = None
    assert service.get_model_outlet(42, "other") is None


def test_no_auth_selection_uses_none_credential_kind():
    from management.services.model.profiles import build_outlet_draft

    profile, _ = build_outlet_draft(draft_request(authentication_scheme="no_auth_v1"), "tenant")
    assert profile.bindings.auth.ref == "no_auth_v1"
    assert profile.connection.credential_ref.kind == profile.connection_rules.credential_kind == "none"


@pytest.mark.parametrize("path", ["/model", "/enable_thinking", "/headers/custom", "/api_key"])
def test_preview_extra_parameters_cannot_override_control_or_auth_fields(path):
    from management.services.model.profiles import build_outlet_draft

    with pytest.raises(ModelOutletValidationError):
        build_outlet_draft(draft_request(extra_api_parameters=[{"path": path, "value": "controlled-value"}]), "tenant")


def test_custom_extra_parameter_is_preserved_without_capability_claim():
    from management.services.model.profiles import build_outlet_draft

    extras = [{"path": "/custom_option", "value": False}]
    profile, _ = build_outlet_draft(draft_request(extra_api_parameters=extras), "tenant")
    assert profile.extra_api_parameters == extras
    assert "custom_option" not in profile.parameter_values


def test_unknown_sampling_preserves_legacy_calls_and_explicit_top_p_controls():
    from management.services.conversation.model_preferences import merge_model_preferences
    from management.services.model.profiles import build_outlet_draft

    from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
    from nexent.core.model_service.compatibility.invocation_options import LegacyInvocationOptions
    from nexent.core.model_service.contracts import ModelMessage, ModelRequest

    profile, _ = build_outlet_draft(draft_request(request_model_id="unlisted",
        provider_info={"base_url": "https://custom.invalid/v1"}), "tenant")
    declarations = {rule["key"]: rule for rule in profile.parameter_rules}
    assert profile.capabilities.sampling.temperature.status == "unknown"
    assert "temperature" not in profile.parameter_values
    assert declarations["temperature"]["visible"] is True
    assert declarations["temperature"]["allowed_scopes"] == ["outlet", "conversation"]
    assert declarations["top_p"]["visible"] is True
    assert declarations["top_p"]["allowed_scopes"] == ["outlet", "conversation"]
    assert "top_p" not in profile.parameter_values
    assert profile.capabilities.sampling.top_p.status == "unknown"
    assert merge_model_preferences(profile, {"top_p": 0.85}).parameter_values["top_p"] == 0.85
    invocation = LegacyInvocationOptions({"temperature": 0.5, "top_p": 0}).resolve(profile)
    request = ModelRequest(request_id="legacy-platform-call", outlet_id=profile.outlet_id,
        config_revision=profile.config_revision,
        messages=[ModelMessage(semantic_role="user", content_parts=[{"type": "text", "text": "title"}])])
    body = OpenAIChatAdapter().prepare_http_request(request, invocation).json_body
    assert body["temperature"] == 0.5 and body["top_p"] == 0
    assert merge_model_preferences(profile, {"temperature": 0.5}).parameter_values["temperature"] == 0.5


def test_preview_exposes_experience_defaults_before_user_overrides(monkeypatch):
    from dataclasses import replace

    from contracts.model import ModelProfilePreviewRequest
    from management.services.model import profiles as service

    from nexent.core.model_service.profiles.protocol_parameters import openai_chat_parameter_rules

    catalog = service.get_model_profile_catalog()
    rules = next(rule for rule in openai_chat_parameter_rules() if rule["key"] == "temperature")
    model_key, provider_key = "alibaba/qwen3.5-plus", "alibaba-cn"
    combo_key = provider_key + "/qwen3.5-plus"
    layers = []
    for collection, key, value in ((catalog.models, model_key, 0.2),
                                   (catalog.providers, provider_key, 0.4),
                                   (catalog.provider_models, combo_key, 0.6)):
        atom = collection[key]
        rule = {**rules, "default_value": value}
        layers.append({**collection, key: replace(atom, parameters=(*atom.parameters, rule))})
    monkeypatch.setattr(service, "get_model_profile_catalog", lambda: replace(catalog,
        models=layers[0], providers=layers[1], provider_models=layers[2]))
    request = ModelProfilePreviewRequest(provider_info={"base_url": "https://models.invalid/v1"},
        request_model_id="qwen3.5-plus", provider_profile={"key": provider_key, "revision": catalog.providers[provider_key].revision})
    preview = service.preview_model_profile(request, "tenant")
    assert preview["parameter_values"]["temperature"] == 0.6
    assert next(rule for rule in preview["field_specs"] if rule["key"] == "temperature")["default_value"] == 0.6
    request.parameter_values = {"temperature": 0.9}
    assert service.preview_model_profile(request, "tenant")["parameter_values"]["temperature"] == 0.9
    assert preview["parameter_values"]["temperature"] == 0.6


def test_model_list_includes_detached_base_configuration_without_connection():
    import json

    from management.services.model.profiles import get_model_profile_catalog

    result = list_atomic_profiles("model", query="qwen3.7-max")
    item = next(item for item in result["items"] if item["key"] == "alibaba/qwen3.7-max")
    configuration = item["configuration"]
    assert configuration["capabilities"]["context"]["combined_window"] == 1000000
    assert configuration["capabilities"]["context"]["output_limit"] == 65536
    assert configuration["capabilities"]["reasoning"]["status"] == "supported"
    json.dumps(result)
    configuration["capabilities"]["context"]["combined_window"] = 1
    assert get_model_profile_catalog().models[item["key"]].capabilities["context"]["combined_window"] == 1000000


def test_model_base_configuration_preserves_explicit_default_values(monkeypatch):
    from dataclasses import replace

    from management.services.model import profiles as service

    catalog = service.get_model_profile_catalog()
    key = "alibaba/qwen3.7-max"
    parameters = ({"key": "temperature", "default_value": 0},
                  {"key": "enable_thinking", "fixed_value": False},
                  {"key": "custom_nullable", "default_value": None},
                  {"key": "no_default"})
    atom = replace(catalog.models[key], parameters=parameters)
    monkeypatch.setattr(service, "get_model_profile_catalog", lambda: replace(catalog, models={key: atom}))
    configuration = service.list_atomic_profiles("model")["items"][0]["configuration"]
    assert configuration["parameter_values"] == {"temperature": 0, "enable_thinking": False, "custom_nullable": None}
    assert len(configuration["field_specs"]) == 4


def test_edit_old_outlet_adds_only_missing_sampling_rules_without_catalog_lookup(monkeypatch):
    from contracts.model import ModelOutletPatchRequest
    from management.services.model import profiles as service
    from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile

    profile, _ = service.build_outlet_draft(draft_request(request_model_id="old",
        provider_info={"base_url": "https://custom.invalid/v1"}), "tenant")
    data = profile.model_dump(mode="json")
    data["parameter_rules"] = [rule for rule in data["parameter_rules"] if rule["key"] not in {"temperature", "top_p"}]
    before = ResolvedModelProfile.model_validate(data)
    monkeypatch.setattr(service, "get_model_profile_catalog", lambda: pytest.fail("must not read TOML for an old outlet"))
    request = ModelOutletPatchRequest(expected_revision=before.config_revision,
        parameter_values={"temperature": 0.7, "top_p": 1})
    result = service.apply_outlet_patch(before, request)
    assert result.parameter_values["temperature"] == 0.7
    assert result.parameter_values["top_p"] == 1
    assert result.identity == before.identity
    assert result.capabilities == before.capabilities
    assert all(rule in result.parameter_rules for rule in before.parameter_rules)


@pytest.mark.parametrize("key,scheme,kind", [(None, "no_auth_v1", "none"),
    ("", "no_auth_v1", "none"), ("  ", "no_auth_v1", "none"),
    ("controlled-key", "bearer_token_v1", "model_record")])
def test_optional_key_controls_authentication_for_create_and_explicit_edit(key, scheme, kind):
    """UI-AUTH-11: the key controls auth; omitted patch keys preserve it."""
    from contracts.model import ModelOutletCreateRequest, ModelOutletPatchRequest
    from management.services.model.profiles import build_outlet_draft, apply_outlet_patch

    request = ModelOutletCreateRequest(**draft_request().model_dump(), api_key=key)
    profile, _ = build_outlet_draft(request, "tenant")
    assert profile.bindings.auth.ref == scheme
    assert profile.connection.credential_ref.kind == kind
    original, _ = build_outlet_draft(draft_request(), "tenant")
    changed = apply_outlet_patch(original, ModelOutletPatchRequest(expected_revision=1, api_key=key))
    assert changed.bindings.auth.ref == scheme
    assert changed.connection.credential_ref.kind == kind
    retained = apply_outlet_patch(changed, ModelOutletPatchRequest(expected_revision=1))
    assert retained.bindings.auth == changed.bindings.auth
    assert retained.connection.credential_ref == changed.connection.credential_ref


@pytest.mark.parametrize("key", ["********", "***", "********suffix", "prefix********"])
def test_masked_credential_is_rejected_before_composition_or_patch(key):
    """UI-AUTH-13: no placeholder may reach persistence or the model transport."""
    from contracts.model import ModelOutletCreateRequest, ModelOutletPatchRequest
    from management.services.model.profiles import build_outlet_draft, apply_outlet_patch

    with pytest.raises(ModelOutletValidationError):
        build_outlet_draft(ModelOutletCreateRequest(**draft_request().model_dump(), api_key=key), "tenant")
    profile, _ = build_outlet_draft(draft_request(), "tenant")
    with pytest.raises(ModelOutletValidationError):
        apply_outlet_patch(profile, ModelOutletPatchRequest(expected_revision=1, api_key=key))


def test_saved_outlet_draft_view_upgrades_only_registered_sampling_rules(outlet_database):
    import management.services.model.profiles as service
    from nexent.core.model_service.profiles.protocol_parameters import openai_chat_parameter_rules

    database, _ = outlet_database
    profile, _ = service.build_outlet_draft(draft_request(), "tenant")
    data = profile.model_dump(mode="json")
    rules = openai_chat_parameter_rules()
    for rule in rules:
        if rule["key"] in {"temperature", "top_p"}:
            rule["visible"] = False
            rule["allowed_scopes"] = ["outlet"]
            rule["source"] = {"ref": "openai_chat_protocol_parameters_v1", "version": 1}
    data["parameter_rules"] = [rule for rule in data["parameter_rules"] if rule["key"] not in {r["key"] for r in rules}] + rules
    database.get_resolved_model_record.return_value = type(profile).model_validate(data)
    result = service.get_model_outlet(42, "tenant")
    sampling = [rule for rule in result["field_specs"] if rule["key"] in {"temperature", "top_p"}]
    assert len(sampling) == 2
    assert all(rule["visible"] and "conversation" in rule["allowed_scopes"] for rule in sampling)
    assert all(rule["source"]["version"] == 2 for rule in sampling)
    assert result["profile"]["parameter_values"] == data["parameter_values"]
    assert all(not rule["visible"] for rule in data["parameter_rules"] if rule["key"] in {"temperature", "top_p"})


@pytest.mark.parametrize("ambiguous", [False, True])
def test_ac_fix_09_unmatched_and_ambiguous_models_use_protocol_fallback(monkeypatch, ambiguous):
    from dataclasses import replace
    from management.services.model import profiles as service

    catalog = service.get_model_profile_catalog()
    keys = ["alibaba/qwen3.5-plus", "zhipuai/glm-5.2"]
    request_id = "ambiguous-onboarding-model" if ambiguous else "unlisted-onboarding-model"
    if ambiguous:
        models = dict(catalog.models)
        for key in keys:
            models[key] = replace(models[key], aliases=(*models[key].aliases, request_id))
        catalog = replace(catalog, models=models)
    monkeypatch.setattr(service, "get_model_profile_catalog", lambda: catalog)
    preview = service.preview_model_profile(draft_request(
        request_model_id=request_id, provider_info={"base_url": "https://custom.invalid/v1"}), "tenant")
    assert preview["selected"]["model"] is None
    assert preview["matched_profile"] is False
    assert preview["candidates"]["models"] == (sorted(keys) if ambiguous else [])
    assert {"temperature", "top_p"}.issubset({rule["key"] for rule in preview["field_specs"]})
    assert preview["capabilities"]["reasoning"]["status"] == "unknown"
    assert preview["capabilities"]["context"]["output_limit"] is None
