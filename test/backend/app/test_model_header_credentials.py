# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Model response boundaries exclude stored credentials without altering internal rows."""

from copy import deepcopy

import pytest

from test.backend.app.test_model_managment_app import auth_header, client  # noqa: F401


@pytest.mark.parametrize("method,path,body,service,envelope", [
    ("get", "/model/list", None, "list_models_for_tenant", False),
    ("get", "/model/llm_list", None, "list_llm_models_for_tenant", False),
    ("post", "/model/provider/list", {"provider": "fixture", "model_type": "llm"},
     "list_provider_models_for_tenant", False),
    ("post", "/model/provider/create", {"provider": "fixture", "model_type": "llm"},
     "create_provider_models_for_tenant", False),
    ("post", "/model/manage/list", {"tenant_id": "test_tenant"}, "list_models_for_admin", True),
    ("post", "/model/manage/provider/list", {"tenant_id": "test_tenant", "provider": "fixture", "model_type": "llm"},
     "list_provider_models_for_tenant", False),
    ("post", "/model/manage/provider/create", {"tenant_id": "test_tenant", "provider": "fixture"},
     "create_provider_models_for_tenant", False),
])
def test_model_responses_exclude_header_credentials(client, auth_header, mocker, method, path, body, service, envelope):
    row = {"model_id": 42, "model_name": "fixture-model", "model_type": "llm",
           "api_key": "synthetic-api-secret",
           "http_headers": {"Authorization": "Bearer synthetic-header-secret", "X-API-Key": "synthetic-x-key"},
           "extra": [{"http_headers": {"X-Secret": "synthetic-nested-secret"}, "keep": False}],
           "temperature": 0}
    payload = {"models": [row], "total": 1, "page": 1, "page_size": 20} if envelope else [row]
    before = deepcopy(payload)
    mocker.patch("management.api.model.model_managment." + service, return_value=payload)
    response = getattr(client, method)(path, headers=auth_header, **({"json": body} if body is not None else {}))
    assert response.status_code == 200
    public = response.json()["data"]
    public_row = public["models"][0] if envelope else public[0]
    assert "http_headers" not in public_row and "api_key" not in public_row
    assert public_row["extra"] == [{"keep": False}]
    assert public_row["temperature"] == 0 and public_row["model_name"] == row["model_name"]
    assert "synthetic-" not in response.text
    assert payload == before, "Internal credentials must remain usable by model services"


@pytest.mark.parametrize("headers", [None, {}, {"X-Request-ID": "fixture"}])
def test_sanitizer_omits_header_field_even_when_empty_or_noncredential(headers):
    from management.api.model.model_managment import _sanitize_model_credentials

    payload = {"models": [{"http_headers": headers, "api_key": None, "enabled": False}], "total": 1}
    before = deepcopy(payload)
    assert _sanitize_model_credentials(payload) == {"models": [{"enabled": False}], "total": 1}
    assert payload == before
