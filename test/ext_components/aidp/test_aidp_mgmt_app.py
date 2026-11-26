# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit tests for the v7.1 AIDP management endpoints.

These tests exercise the FastAPI router in ``backend/ext_components/aidp/apps/aidp_mgmt_app.py``
after the permission rewrite. Every handler now:
* parses the Authorization header via ``_auth``,
* enforces the permission matrix via ``require_permission``,
* delegates KB CRUD to the AIDP client while writing permission state to
  ``aidp_kb_permission_t``.

The tests stub the auth helper, the AIDP service layer, and the local DB
CRUD so we can validate request/response semantics without a real Postgres.
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import types
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from test.common.module_stubs import capture_module_stubs

_modules_before_stubs = sys.modules.copy()

# --- Module stubs --------------------------------------------------------

def _mod(name):
    m = types.ModuleType(name)
    m.__path__ = []
    return m


nexent_pkg = _mod("nexent")
# Keep unmocked SDK packages importable without relying on prior collection.
nexent_pkg.__path__ = [os.path.join(PROJECT_ROOT, "sdk", "nexent")]
nexent_utils = _mod("nexent.utils")
nexent_http_mgr = _mod("nexent.utils.http_client_manager")
nexent_http_mgr.http_client_manager = MagicMock()
nexent_storage = _mod("nexent.storage")
nexent_storage_factory = _mod("nexent.storage.storage_client_factory")
nexent_storage_factory.create_storage_client_from_config = MagicMock()

services_pkg = _mod("services")
services_pkg.__path__ = [os.path.join(BACKEND_DIR, "services")]
tag_management_service = _mod("management.services.tag.library")
tag_management_service.TagManagementService = MagicMock()


class _MinIOStorageConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


nexent_storage_factory.MinIOStorageConfig = _MinIOStorageConfig

for mod in (nexent_pkg, nexent_utils, nexent_http_mgr, nexent_storage,
            nexent_storage_factory, services_pkg, tag_management_service):
    sys.modules[mod.__name__] = mod

# Register non-prefixed ``database`` / ``infrastructure.rdb.client`` stubs so that
# production modules (which import as ``from infrastructure.rdb.client import ...``)
# resolve to these mocks rather than loading real Minio/Postgres clients.
# Previous ``backend.*``-prefixed keys caused Python to create parallel
# module objects that broke mock patching.
_db_pkg = sys.modules.get("database") or _mod("database")
_db_pkg.__path__ = [os.path.join(BACKEND_DIR, "database")]
_db_client = _mod("infrastructure.rdb.client")
_db_client.MinioClient = MagicMock()
_db_client.PostgresClient = MagicMock()
_db_client.as_dict = lambda obj: dict(obj) if isinstance(obj, dict) else {}
_db_client.get_db_session = MagicMock()
_db_client.filter_property = MagicMock()
_db_client.db_client = MagicMock()
for mod in (_db_pkg, _db_client):
    sys.modules[mod.__name__] = mod

# Production modules under test
from ext_components.aidp.apps import (
    aidp_chunk_routes,
    aidp_mgmt_app,
    aidp_mgmt_common,
    aidp_sensitive_word_routes,
    aidp_summary_routes,
)
from ext_components.aidp.apps.aidp_mgmt_app import (  # noqa: E402
    CreateKbRequest,
    SetPermissionRequest,
    UpdateKbRequest,
    aidp_mgmt_router,
)
from ext_components.aidp.consts.aidp_exceptions import AidpSensitiveWordError  # noqa: E402
from backend.http.server.app_factory import register_exception_handlers

SERVER_URL = "http://aidp.example.com:30081"
API_KEY = "test-aidp-api-key"
USER_ID = "user-test"
TENANT_ID = "tenant-test"


def test_knowledge_base_api_models_expose_the_sensitive_intercept_toggle():
    for model in (CreateKbRequest, UpdateKbRequest, SetPermissionRequest):
        assert "sensitive_intercept_enalbe" not in model.model_fields
    assert CreateKbRequest.model_fields["sensitive_intercept_enable"].default == 0
    assert "sensitive_intercept_enable" in UpdateKbRequest.model_fields


@pytest.mark.parametrize("settings", [
    {"description": "   "},
    {"embedding_model": ""},
    {"embedding_model": "   "},
    {"chunk_token_num": True},
    {"chunk_token_num": 255},
    {"chunk_token_num": 4097},
    {"chunk_overlap_num": 1.5},
    {"chunk_token_num": 512, "chunk_overlap_num": 257},
    {"topk": 1.5},
    {"caption_enable": 1, "vlm_model": ""},
])
def test_creation_rejects_invalid_settings_in_request_model(settings):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CreateKbRequest(**{"name": "kb", "description": "test", "embedding_model": "bge-m3", **settings})


def test_creation_requires_embedding_and_trims_description():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CreateKbRequest(name="kb", description="test")
    body = CreateKbRequest(name="kb", description="  test  ", embedding_model="/models/bge-m3")
    assert body.description == "test"
    assert body.chunk_token_num == 512
    assert body.chunk_overlap_num == 51
    assert body.similarity == 0.0
    assert body.vlm_model == ""




@pytest.mark.parametrize("metadata,remote_fails", [
    ({}, False),
    ({"name": "Renamed"}, False),
    ({"description": ""}, False),
    ({"description": "New description"}, True),
])
def test_unified_save_commits_permissions_before_optional_aidp(monkeypatch, metadata, remote_fails):
    from contracts.errors.codes import ErrorCode
    from contracts.errors.exceptions import AppException
    from ext_components.aidp.apps import aidp_mgmt_app
    from ext_components.aidp.services import aidp_kb_update_service as service

    events = []
    monkeypatch.setattr(aidp_mgmt_app.perms, "require_permission", lambda *a, **kw: None)

    def save_local(**kwargs):
        events.append(("local", kwargs))
        return True

    def save_remote(server_url, api_key, kb_id, payload):
        assert events[0][0] == "local"
        assert events[0][1]["ingroup_permission"] == "PRIVATE"
        events.append(("remote", payload))
        if remote_fails:
            raise AppException(ErrorCode.AIDP_CONNECTION_ERROR, "Unavailable")
        return {"kds_name": payload.get("name", "Original"), **payload}

    monkeypatch.setattr(service.perms, "update_permission", save_local)
    monkeypatch.setattr(service, "update_aidp_kb_impl", save_remote)
    response = _client().patch(
        "/aidp-mgmt/aidp-permissions/kb-1", headers=_bearer(),
        json={"ingroup_permission": "PRIVATE", "group_ids": [], **metadata},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["permissions_saved"] is True
    assert result["metadata_status"] == ("failed" if remote_fails else "updated" if metadata else "unchanged")
    assert [payload for kind, payload in events if kind == "remote"] == ([metadata] if metadata else [])


def test_unified_save_local_failure_prevents_aidp(monkeypatch):
    from ext_components.aidp.apps import aidp_mgmt_app
    from ext_components.aidp.services import aidp_kb_update_service as service

    monkeypatch.setattr(aidp_mgmt_app.perms, "require_permission", lambda *a, **kw: None)
    monkeypatch.setattr(service.perms, "update_permission", lambda **kw: False)
    remote_calls = []
    monkeypatch.setattr(service, "update_aidp_kb_impl", lambda *a: remote_calls.append(a))
    response = _client().patch(
        "/aidp-mgmt/aidp-permissions/kb-1", headers=_bearer(),
        json={"ingroup_permission": "PRIVATE", "description": "Changed"},
    )
    assert response.status_code == 404
    assert remote_calls == []


# --- Fixtures -------------------------------------------------------------


@pytest.fixture(autouse=True)
def configure_aidp_constants(monkeypatch, _isolated_imports):
    """Pin AIDP credentials and auth helper behaviour for every test."""
    from ext_components.aidp.apps import aidp_mgmt_app
    from ext_components.aidp.services import aidp_access_service

    aidp_access_service.invalidate_aidp_catalog_cache()
    aidp_access_service.invalidate_aidp_kb_detail_cache()
    aidp_access_service.invalidate_aidp_doc_count_cache()

    monkeypatch.setattr(aidp_mgmt_app, "AIDP_SERVER_URL", SERVER_URL)
    monkeypatch.setattr(aidp_mgmt_app, "AIDP_API_KEY", API_KEY)
    monkeypatch.setattr(aidp_mgmt_common, "AIDP_SERVER_URL", SERVER_URL)
    monkeypatch.setattr(aidp_mgmt_common, "AIDP_API_KEY", API_KEY)

    # Default: auth succeeds with the standard test user/tenant.
    monkeypatch.setattr(
        aidp_mgmt_common.auth_utils_module, "get_current_user_id",
        lambda *_a, **_kw: (USER_ID, TENANT_ID),
    )
    # Existing management tests exercise the shared-KB path. Individual
    # USER-policy tests override this role explicitly below.
    monkeypatch.setattr(
        aidp_mgmt_app, "get_user_role_by_tenant", lambda *_a, **_kw: "DEV"
    )
    yield
    aidp_access_service.invalidate_aidp_catalog_cache()
    aidp_access_service.invalidate_aidp_kb_detail_cache()
    aidp_access_service.invalidate_aidp_doc_count_cache()


def _build_app() -> FastAPI:
    from ext_components.aidp.apps.aidp_ontology_app import aidp_ontology_router

    app = FastAPI()
    app.include_router(aidp_mgmt_router)
    app.include_router(aidp_ontology_router)
    register_exception_handlers(app)
    return app


def _client():
    return TestClient(_build_app())


def _bearer() -> dict:
    return {"Authorization": "Bearer fake-token"}


def test_detail_creator_comes_from_nexent_owner_in_current_tenant(monkeypatch):
    from ext_components.aidp.apps import aidp_mgmt_app as module
    monkeypatch.setattr(module.perms, "require_permission", lambda *a, **kw: MagicMock(permission="EDIT"))
    monkeypatch.setattr(module, "get_aidp_kb_impl", lambda *a: {"kds_name": "资料库", "user_name": "remote-user"})
    monkeypatch.setattr(module, "count_aidp_docs_impl", lambda *a: 7)
    monkeypatch.setattr(module.aidp_permission_db, "get_permission_by_kb_id",
                        lambda *a: {"owner_user_id": "local-owner", "group_ids": [],
                                    "creator_name": "admin@example.test"})
    result = _client().get("/aidp-mgmt/knowledge-bases/kb-1", headers=_bearer()).json()
    assert result["creator_name"] == "admin@example.test"
    assert result["created_by"] == "local-owner"
    assert result["document_count"] == 7
    assert "document_count_reliable" not in result


def test_empty_service_query_requests_all_categories(monkeypatch):
    from ext_components.aidp.apps import aidp_mgmt_app as module
    lookup = MagicMock(return_value={"models": [], "service": ""})
    monkeypatch.setattr(module, "list_aidp_models_impl", lookup)
    response = _client().get("/aidp-mgmt/models?app=KnowledgeBase&service=", headers=_bearer())
    assert response.status_code == 200
    assert lookup.call_args.args[2:] == ("", "KnowledgeBase")


def test_graph_template_route_is_authenticated_and_not_a_knowledge_base_id(monkeypatch):
    from ext_components.aidp.apps import aidp_mgmt_app as module
    lookup = MagicMock(return_value={"value": [{"param_key": "domain"}]})
    monkeypatch.setattr(module, "get_aidp_graph_template_impl", lookup)
    result = _client().get("/aidp-mgmt/knowledge-bases/graph-template?language=english", headers=_bearer())
    assert result.status_code == 200 and result.json()["value"][0]["param_key"] == "domain"
    lookup.assert_called_once_with(SERVER_URL, API_KEY, "english")
    assert _client().get("/aidp-mgmt/knowledge-bases/graph-template").status_code == 401


# --- Auth (401) -----------------------------------------------------------


_install_module_stubs = capture_module_stubs(_modules_before_stubs)


@pytest.fixture(autouse=True)
def _isolated_imports(monkeypatch):
    _install_module_stubs(monkeypatch)
