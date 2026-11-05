# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Profile endpoints preserve read authorization and validated discovery inputs."""

from unittest.mock import AsyncMock

import pytest

from test.backend.app.test_model_managment_app import client  # noqa: F401 - Shared app fixture.


@pytest.mark.parametrize("path,kind", [("model_profiles", "model"), ("provider_profiles", "provider")])
def test_profile_list_validates_inputs_and_forwards_pagination(client, mocker, path, kind):
    from management.api.model import model_managment as app

    payload = {"items": [], "total": 0, "catalog_revision": "revision", "page": 2, "page_size": 3}
    run = mocker.patch.object(app, "run_blocking", new=AsyncMock(return_value=payload))
    response = client.get(f"/model/{path}?query=qwen&page=2&page_size=3")
    assert response.status_code == 200 and response.json() == {"data": payload}
    assert run.call_args.args[2] == kind
    assert run.call_args.kwargs["query"] == "qwen"
    assert run.call_args.kwargs["page"] == 2 and run.call_args.kwargs["page_size"] == 3
    run.reset_mock()
    assert client.get(f"/model/{path}?page_size=101").status_code == 422
    run.assert_not_called()


def test_protocol_discovery_exposes_registered_choices(client):
    response = client.get("/model/profile_protocols")
    assert response.status_code == 200
    assert response.json()["data"]["items"] == [{"ref": "openai_chat_completions", "version": 1}]


@pytest.mark.parametrize("path", ["model_profiles", "provider_profiles", "profile_protocols"])
def test_profile_discovery_rejects_missing_model_read_permission(client, mocker, path):
    mocker.patch("permissions.depends.has_permission", return_value=False)
    response = client.get(f"/model/{path}")
    assert response.status_code == 403


def preview_body():
    return {"provider_info": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
            "request_model_id": "qwen3.5-plus", "parameter_values": {"enable_thinking": False}}


def test_invalid_header_values_are_not_echoed_in_schema_errors(client):
    response = client.post("/model/profile_previews", json={**preview_body(),
        "http_headers": {"x-private": ["controlled-private-header"]}})
    assert response.status_code == 422
    assert "controlled-private-header" not in response.text
    assert response.json()["detail"][0]["loc"] == ["body", "http_headers", "x-private"]


def test_preview_reaches_actual_composer_with_trusted_tenant(client, mocker):
    from management.api.model import model_managment as app

    async def run(_name, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    mocker.patch.object(app, "run_blocking", new=run)
    response = client.post("/model/profile_previews", json=preview_body())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["selected"] == {"model": "alibaba/qwen3.5-plus", "provider": "alibaba-cn"}
    assert data["parameter_values"] == {"enable_thinking": False}
    assert "api_key" not in response.text
    invalid = {**preview_body(), "parameter_values": {"enable_thinking": "wrong"}}
    response = client.post("/model/profile_previews", json=invalid)
    assert response.status_code == 400
    assert response.json()["detail"]["details"]["category"] == "PARAMETER_VALUE_INVALID"
    assert "wrong" not in response.text
    assert client.post("/model/profile_previews", json={**preview_body(), "catalog_revision": "stale"}).status_code == 409
    assert client.post("/model/profile_previews", json={**preview_body(), "tenant_id": "other"}).status_code == 422


def test_save_passes_trusted_owner_and_excludes_credentials_from_audit(client, mocker):
    from management.api.model import model_managment as app

    run = mocker.patch.object(app, "run_blocking", new=AsyncMock(return_value={"model_id": 42, "config_revision": 1}))
    audit = mocker.patch.object(app, "record_security_event")
    body = {**preview_body(), "catalog_revision": "revision", "api_key": "controlled-key"}
    response = client.post("/model/outlets", json=body)
    assert response.status_code == 200
    assert run.call_args.args[-2:] == ("test_user", "test_tenant")
    assert run.call_args.args[2].api_key == "controlled-key"
    assert "controlled-key" not in repr(audit.call_args)
    assert "controlled-key" not in response.text


def test_outlet_get_does_not_expose_foreign_or_missing_record(client, mocker):
    from management.api.model import model_managment as app

    run = mocker.patch.object(app, "run_blocking", new=AsyncMock(return_value=None))
    assert client.get("/model/outlets/42").status_code == 404
    assert run.call_args.args[-2:] == (42, "test_tenant")
    run.reset_mock()
    assert client.get("/model/outlets/0").status_code == 422
    run.assert_not_called()


@pytest.mark.parametrize("path", ["profile_previews", "outlets"])
def test_profile_operations_require_permission(client, mocker, path):
    mocker.patch("permissions.depends.has_permission", return_value=False)
    assert client.post(f"/model/{path}", json=preview_body()).status_code == 403


def test_patch_preserves_omitted_credential_and_trusted_identity(client, mocker):
    from management.api.model import model_managment as app

    run = mocker.patch.object(app, "run_blocking", new=AsyncMock(return_value={"model_id": 42, "config_revision": 2}))
    audit = mocker.patch.object(app, "record_security_event")
    response = client.patch("/model/outlets/42", json={"expected_revision": 1,
        "parameter_values": {"enable_thinking": False}})
    assert response.status_code == 200
    assert run.call_args.args[2] == 42
    request = run.call_args.args[3]
    assert "api_key" not in request.model_fields_set
    assert run.call_args.args[-2:] == ("test_user", "test_tenant")
    assert audit.call_args.kwargs["details"] == {"model_id": 42, "config_revision": 2}


@pytest.mark.parametrize("exception,status", [("missing", 404), ("stale", 409), ("invalid", 422)])
def test_patch_maps_domain_errors(client, mocker, exception, status):
    from management.api.model import model_managment as app
    from contracts.errors.exceptions import ModelOutletConflictError, ModelOutletValidationError

    failures = {"missing": LookupError(), "stale": ModelOutletConflictError(),
                "invalid": ModelOutletValidationError(category="PARAMETER_VALUE_INVALID", path="enable_thinking")}
    mocker.patch.object(app, "run_blocking", new=AsyncMock(side_effect=failures[exception]))
    response = client.patch("/model/outlets/42", json={"expected_revision": 1})
    assert response.status_code == status


def test_probe_returns_unavailable_as_result_and_passes_owner(client, mocker):
    invoke = mocker.patch("management.services.model.profiles.validate_model_outlet", new=AsyncMock(
        return_value={"ok": False, "error": {"category": "AUTHENTICATION_ERROR"},
                      "check_scope": "connection_only", "model_id": 42, "config_revision": 1}))
    response = client.post("/model/outlet_validations", json={"outlet_id": 42, "expected_revision": 1})
    assert response.status_code == 200 and response.json()["data"]["ok"] is False
    assert invoke.call_args.args[1] == "test_tenant"
    invoke.reset_mock()
    assert client.post("/model/outlet_validations", json={}).status_code == 422
    assert client.post("/model/outlet_validations", json={"outlet_id": 42, "tenant_id": "other"}).status_code == 422
    invoke.assert_not_awaited()


@pytest.mark.parametrize("method,path,body", [
    ("patch", "/model/outlets/42", {"expected_revision": 1}),
    ("post", "/model/outlet_validations", {"outlet_id": 42}),
])
def test_outlet_mutations_require_permission(client, mocker, method, path, body):
    mocker.patch("permissions.depends.has_permission", return_value=False)
    assert getattr(client, method)(path, json=body).status_code == 403


def test_migration_review_passes_authenticated_owner_and_exact_revision(client, mocker):
    from management.api.model import model_managment as app

    run = mocker.patch.object(app, "run_blocking", new=AsyncMock(return_value={
        "model_id": 42, "config_revision": 7, "migration_review_required": False}))
    mocker.patch.object(app, "record_security_event")
    response = client.post("/model/outlets/42/migration_reviews", json={"expected_revision": 7})
    assert response.status_code == 200
    assert run.call_args.args[2] == 42 and run.call_args.args[3].expected_revision == 7
    assert run.call_args.args[-2:] == ("test_user", "test_tenant")


def test_migration_review_requires_admin_role_even_with_update_permission(client, mocker):
    from management.api.model import model_managment as app
    from permissions.models import CurrentUser

    # The shared fixture overrides the authentication dependency directly.
    client.app.dependency_overrides[app.authenticate] = lambda: CurrentUser("developer", "test_tenant", "DEV")
    run = mocker.patch.object(app, "run_blocking", new=AsyncMock())
    assert client.post("/model/outlets/42/migration_reviews", json={"expected_revision": 1}).status_code == 403
    run.assert_not_awaited()


@pytest.mark.parametrize("failure,status", [("stale", 409), ("missing", 404), ("invalid", 422)])
def test_review_maps_revision_and_record_failures(client, mocker, failure, status):
    from management.api.model import model_managment as app
    from contracts.errors.exceptions import ModelOutletConflictError, ModelOutletValidationError

    run = mocker.patch.object(app, "run_blocking", new=AsyncMock())
    if failure == "missing":
        run.return_value = None
    elif failure == "stale":
        run.side_effect = ModelOutletConflictError()
    else:
        run.side_effect = ModelOutletValidationError(category="MIGRATION_NOT_APPLICABLE")
    assert client.post("/model/outlets/42/migration_reviews", json={"expected_revision": 1}).status_code == status
    run.reset_mock()
    assert client.post("/model/outlets/42/migration_reviews", json={"expected_revision": True}).status_code == 422
    run.assert_not_awaited()


@pytest.mark.parametrize('kind,status', [('stale', 409), ('invalid', 400)])
def test_create_rejects_version_or_configuration_without_audit(client, mocker, kind, status):
    from management.api.model import model_managment as app
    from contracts.errors.exceptions import ModelOutletConflictError, ModelOutletValidationError

    error = ModelOutletConflictError() if kind == 'stale' else ModelOutletValidationError('PARAMETER_UNKNOWN', '/unknown')
    mocker.patch.object(app, 'run_blocking', new=AsyncMock(side_effect=error))
    audit = mocker.patch.object(app, 'record_security_event')
    response = client.post('/model/outlets', json={**preview_body(), 'catalog_revision': 'revision'})
    assert response.status_code == status
    audit.assert_not_called()
    if kind == 'invalid':
        assert response.json()['detail']['details'] == {'category': 'PARAMETER_UNKNOWN', 'field': '/unknown'}


@pytest.mark.parametrize('kind,status', [('missing', 404), ('stale', 409), ('invalid', 422)])
def test_validation_distinguishes_selection_version_and_configuration_errors(client, mocker, kind, status):
    from contracts.errors.exceptions import ModelOutletConflictError, ModelOutletValidationError

    errors = {'missing': LookupError(), 'stale': ModelOutletConflictError(),
              'invalid': ModelOutletValidationError('PROFILE_STORAGE_INVALID')}
    invoke = mocker.patch('management.services.model.profiles.validate_model_outlet', new=AsyncMock(side_effect=errors[kind]))
    response = client.post('/model/outlet_validations', json={'outlet_id': 42, 'expected_revision': 1})
    assert response.status_code == status
    assert invoke.call_args.args[1] == 'test_tenant'


def test_duplicate_create_has_distinct_business_code_without_success_audit(client, mocker):
    from management.api.model import model_managment as app
    from contracts.errors.exceptions import DuplicateError

    mocker.patch.object(app, 'run_blocking', new=AsyncMock(side_effect=DuplicateError()))
    audit = mocker.patch.object(app, 'record_security_event')
    response = client.post('/model/outlets', json={**preview_body(), 'catalog_revision': 'revision'})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'MODEL_DISPLAY_NAME_CONFLICT'
    assert response.json()['detail']['details'] == {'field': 'display_name'}
    audit.assert_not_called()


def test_aeu_saved_preview_uses_trusted_tenant_and_never_writes(client, mocker):
    from management.api.model import model_managment as app
    result = {"field_specs": [], "parameter_values": {"temperature": 0.4}}
    run = mocker.patch.object(app, "run_blocking", new=AsyncMock(return_value=result))
    response = client.post("/model/outlets/42/profile_previews", json={"expected_revision": 7,
        "parameter_values": {"temperature": 0.4}})
    assert response.status_code == 200 and response.json()["data"] == result
    assert run.call_args.args[0] == "model-outlet-preview"
    assert run.call_args.args[2] == 42
    assert run.call_args.args[3].expected_revision == 7
    assert run.call_args.args[4] == "test_tenant"
    mocker.patch("permissions.depends.has_permission", return_value=False)
    assert client.post("/model/outlets/42/profile_previews", json={"expected_revision": 7}).status_code == 403


@pytest.mark.parametrize("error,status", [(LookupError("MODEL_OUTLET_NOT_FOUND"), 404)])
def test_aeu_saved_preview_does_not_expose_missing_or_foreign_rows(client, mocker, error, status):
    from management.api.model import model_managment as app
    mocker.patch.object(app, "run_blocking", new=AsyncMock(side_effect=error))
    response = client.post("/model/outlets/42/profile_previews", json={"expected_revision": 7})
    assert response.status_code == status


def test_aeu_catalog_only_preview_does_not_weaken_creation_validation(client, mocker):
    from management.api.model import model_managment as app
    from management.services.model.profiles import get_model_profile_catalog
    async def run(_name, fn, *args, **kwargs):
        return fn(*args, **kwargs)
    mocker.patch.object(app, "run_blocking", new=run)
    catalog = get_model_profile_catalog()
    key = "alibaba/qwen3.7-plus"
    body = {"provider_info": {"base_url": ""}, "request_model_id": "", "display_name": "",
            "model_profile": {"key": key, "revision": catalog.models[key].revision}}
    response = client.post("/model/profile_previews", json=body)
    assert response.status_code == 200
    assert response.json()["data"]["selected"]["model"] == key
    assert client.post("/model/outlets", json=body).status_code == 422
