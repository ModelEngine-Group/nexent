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

# Register non-prefixed ``database`` / ``management.db.client`` stubs so that
# production modules (which import as ``from management.db.client import ...``)
# resolve to these mocks rather than loading real Minio/Postgres clients.
# Previous ``backend.*``-prefixed keys caused Python to create parallel
# module objects that broke mock patching.
_db_pkg = sys.modules.get("database") or _mod("database")
_db_pkg.__path__ = [os.path.join(BACKEND_DIR, "database")]
_db_client = _mod("management.db.client")
_db_client.MinioClient = MagicMock()
_db_client.PostgresClient = MagicMock()
_db_client.as_dict = lambda obj: dict(obj) if isinstance(obj, dict) else {}
_db_client.get_db_session = MagicMock()
_db_client.filter_property = MagicMock()
_db_client.db_client = MagicMock()
for mod in (_db_pkg, _db_client):
    sys.modules[mod.__name__] = mod

# Production modules under test
from ext_components.aidp.apps.aidp_mgmt_app import (  # noqa: E402
    CreateKbRequest,
    SetPermissionRequest,
    UpdateKbRequest,
    aidp_mgmt_router,
)
from management.utils.app_factory import register_exception_handlers

SERVER_URL = "http://aidp.example.com:30081"
API_KEY = "test-aidp-api-key"
USER_ID = "user-test"
TENANT_ID = "tenant-test"


def test_knowledge_base_api_models_do_not_expose_safety_guard():
    for model in (CreateKbRequest, UpdateKbRequest, SetPermissionRequest):
        assert "sensitive_intercept_enalbe" not in model.model_fields


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

    # Default: auth succeeds with the standard test user/tenant.
    monkeypatch.setattr(
        aidp_mgmt_app.auth_utils_module, "get_current_user_id",
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
    app = FastAPI()
    app.include_router(aidp_mgmt_router)
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


class TestAuthRequired:
    def test_missing_auth_returns_401(self):
        app = _build_app()
        client = TestClient(app)
        # Disable the autouse auth patch by replacing get_current_user_id.
        from ext_components.aidp.apps import aidp_mgmt_app

        def _raise(*_a, **_kw):
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="bad")

        original = aidp_mgmt_app.auth_utils_module.get_current_user_id
        aidp_mgmt_app.auth_utils_module.get_current_user_id = _raise
        try:
            response = client.get("/aidp-mgmt/knowledge-bases")
        finally:
            aidp_mgmt_app.auth_utils_module.get_current_user_id = original
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_missing_auth_for_set_permission_returns_401(self):
        app = _build_app()
        client = TestClient(app)
        from ext_components.aidp.apps import aidp_mgmt_app
        from fastapi import HTTPException

        def _raise(*_a, **_kw):
            raise HTTPException(status_code=401, detail="bad")

        original = aidp_mgmt_app.auth_utils_module.get_current_user_id
        aidp_mgmt_app.auth_utils_module.get_current_user_id = _raise
        try:
            response = client.patch(
                "/aidp-mgmt/aidp-permissions/kb-1",
                json={"ingroup_permission": "READ_ONLY", "group_ids": [1]},
            )
        finally:
            aidp_mgmt_app.auth_utils_module.get_current_user_id = original
        assert response.status_code == HTTPStatus.UNAUTHORIZED


# --- Permission matrix enforcement ---------------------------------------


class TestPermissionEnforcement:
    def test_get_kb_without_access_returns_404(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        original_require = aidp_permission_service.require_permission
        aidp_permission_service.require_permission = MagicMock(
            side_effect=aidp_mgmt_app.HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail="not found",
            )
        )
        try:
            response = client.get("/aidp-mgmt/knowledge-bases/kb-1", headers=_bearer())
        finally:
            aidp_permission_service.require_permission = original_require
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_get_kb_with_readonly_returns_metadata(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        decision = MagicMock()
        decision.permission = "READ_ONLY"
        original_require = aidp_permission_service.require_permission
        aidp_permission_service.require_permission = MagicMock(return_value=decision)

        with patch.object(aidp_mgmt_app, "get_aidp_kb_impl") as mock_get, \
             patch.object(aidp_mgmt_app.aidp_permission_db, "get_permission_by_kb_id", return_value=None), \
             patch.object(aidp_mgmt_app, "count_aidp_docs_impl", return_value=12):
            mock_get.return_value = {"kds_name": "name", "description": "desc"}
            try:
                response = client.get(
                    "/aidp-mgmt/knowledge-bases/kb-1", headers=_bearer()
                )
            finally:
                aidp_permission_service.require_permission = original_require
        assert response.status_code == HTTPStatus.OK
        assert response.json()["permission"] == "READ_ONLY"
        assert response.json()["document_count"] == 12
        assert "document_count_reliable" not in response.json()

    def test_update_kb_without_edit_returns_403(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        original_require = aidp_permission_service.require_permission
        aidp_permission_service.require_permission = MagicMock(
            side_effect=aidp_mgmt_app.HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail="denied",
            )
        )
        try:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"name": "new"},
            )
        finally:
            aidp_permission_service.require_permission = original_require
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_delete_kb_runs_and_soft_deletes(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        original_require = aidp_permission_service.require_permission
        aidp_permission_service.require_permission = MagicMock(
            return_value=MagicMock(permission="EDIT")
        )
        try:
            soft_delete = MagicMock(return_value=True)
            cleanup_documents = MagicMock(return_value=0)
            with patch.object(aidp_mgmt_app, "delete_aidp_kb_impl", return_value=True), \
                 patch.object(aidp_mgmt_app.perms, "soft_delete_permission", soft_delete), \
                 patch.object(
                     aidp_mgmt_app,
                     "_cleanup_document_assignments_for_deleted_knowledge_base",
                     cleanup_documents,
                 ):
                response = client.delete(
                    "/aidp-mgmt/knowledge-bases/kb-1", headers=_bearer()
                )
        finally:
            aidp_permission_service.require_permission = original_require
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"success": True}
        soft_delete.assert_called_once()
        cleanup_documents.assert_called_once_with("tenant-test", "kb-1", "user-test")

    def test_set_permission_private_clears_groups(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        original_require = aidp_permission_service.require_permission
        aidp_permission_service.require_permission = MagicMock(
            return_value=MagicMock(permission="EDIT")
        )
        try:
            update_perm = MagicMock(return_value=True)
            with patch.object(aidp_mgmt_app.perms, "update_permission", update_perm), \
                 patch.object(aidp_mgmt_app.perms, "_validate_group_ids_strict") as mock_validate:
                response = client.patch(
                    "/aidp-mgmt/aidp-permissions/kb-1",
                    headers=_bearer(),
                    json={"ingroup_permission": "PRIVATE", "group_ids": [1, 2]},
                )
        finally:
            aidp_permission_service.require_permission = original_require
        assert response.status_code == HTTPStatus.OK
        # validation must NOT be called for PRIVATE; group_ids is forced to []
        mock_validate.assert_not_called()
        kwargs = update_perm.call_args.kwargs
        assert kwargs["group_ids"] == []

    def test_set_permission_requires_groups_when_not_private(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        original_require = aidp_permission_service.require_permission
        aidp_permission_service.require_permission = MagicMock(
            return_value=MagicMock(permission="EDIT")
        )
        try:
            response = client.patch(
                "/aidp-mgmt/aidp-permissions/kb-1",
                headers=_bearer(),
                json={"ingroup_permission": "READ_ONLY", "group_ids": []},
            )
        finally:
            aidp_permission_service.require_permission = original_require
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_set_permission_rejects_cross_tenant_group(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        original_require = aidp_permission_service.require_permission
        aidp_permission_service.require_permission = MagicMock(
            return_value=MagicMock(permission="EDIT")
        )
        try:
            with patch.object(
                aidp_permission_service, "_validate_group_ids_strict",
                side_effect=aidp_mgmt_app.HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST, detail="invalid group",
                ),
            ):
                response = client.patch(
                    "/aidp-mgmt/aidp-permissions/kb-1",
                    headers=_bearer(),
                    json={"ingroup_permission": "EDIT", "group_ids": [1, 999]},
                )
        finally:
            aidp_permission_service.require_permission = original_require
        assert response.status_code == HTTPStatus.BAD_REQUEST


# --- Create KB ------------------------------------------------------------


class TestCreateKnowledgeBase:
    def _patch_create(self, aidp_result=None):
        if aidp_result is None:
            aidp_result = {"kds_id": "kb-new", "name": "kb"}
        return patch(
            "ext_components.aidp.apps.aidp_mgmt_app.create_aidp_kb_impl",
            return_value=aidp_result,
        )

    def test_create_persists_permission_and_returns_edit(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with self._patch_create(), \
             patch.object(aidp_permission_service.aidp_permission_db, "get_permission_by_kb_id", return_value=None), \
             patch.object(aidp_permission_service, "create_permission", return_value=1) as mock_create, \
             patch.object(aidp_permission_service, "update_resource_status", return_value=True) as mock_status, \
             patch.object(aidp_permission_service, "_validate_group_ids_strict", side_effect=lambda g, t: list(g)):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={"embedding_model": "bge-m3",
                    "name": "New KB",
                    "description": "A test knowledge base",
                    "ingroup_permission": "EDIT",
                    "group_ids": [1, 2],
                },
            )
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["permission"] == "EDIT"
        assert body["kds_id"] == "kb-new"
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["kb_id"] == "kb-new"
        assert kwargs["ingroup_permission"] == "EDIT"
        assert sorted(kwargs["group_ids"]) == [1, 2]
        # status was flipped to ACTIVE on success
        assert mock_status.call_args.kwargs["status"] == "ACTIVE"

    def test_create_returns_409_when_active_record_exists(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with self._patch_create(), \
             patch.object(aidp_permission_service, "_validate_group_ids_strict", side_effect=lambda g, t: list(g)), \
             patch.object(aidp_permission_service.aidp_permission_db, "get_permission_by_kb_id", return_value={"id": 1}):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={"embedding_model": "bge-m3",
                    "name": "New KB",
                    "description": "A test knowledge base",
                    "ingroup_permission": "READ_ONLY",
                    "group_ids": [1],
                },
            )
        assert response.status_code == HTTPStatus.CONFLICT

    def test_create_rolls_back_aidp_when_db_fails(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        delete_mock = MagicMock(return_value=True)
        with self._patch_create(), \
             patch.object(aidp_permission_service, "_validate_group_ids_strict", side_effect=lambda g, t: list(g)), \
             patch.object(aidp_permission_service.aidp_permission_db, "get_permission_by_kb_id", return_value=None), \
             patch.object(aidp_permission_service, "create_permission", side_effect=RuntimeError("db down")), \
             patch.object(aidp_mgmt_app, "delete_aidp_kb_impl", delete_mock):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={"embedding_model": "bge-m3",
                    "name": "New KB",
                    "description": "A test knowledge base",
                    "ingroup_permission": "READ_ONLY",
                    "group_ids": [1],
                },
            )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        delete_mock.assert_called_once()

    def test_create_requires_groups_for_non_private(self):
        client = _client()
        response = client.post(
            "/aidp-mgmt/knowledge-bases",
            headers=_bearer(),
            json={"embedding_model": "bge-m3", "name": "New KB", "description": "A test knowledge base", "ingroup_permission": "EDIT"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_create_requires_description(self):
        response = _client().post(
            "/aidp-mgmt/knowledge-bases",
            headers=_bearer(),
            json={"embedding_model": "bge-m3", "name": "New KB", "ingroup_permission": "PRIVATE"},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.parametrize(
        "legacy_field,value",
        [
            ("is_multimodal", True),
            ("vision_model", "legacy-vlm"),
            ("smartsplit", 1),
            ("llm_model_name", "legacy-llm"),
        ],
    )
    def test_create_rejects_legacy_fields(self, legacy_field, value):
        payload = {
            "name": "New KB",
            "description": "A test knowledge base",
            "ingroup_permission": "PRIVATE",
            legacy_field: value,
        }
        response = _client().post(
            "/aidp-mgmt/knowledge-bases",
            headers=_bearer(),
            json=payload,
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


# --- List KBs -------------------------------------------------------------


class TestListKnowledgeBases:
    def test_list_returns_empty_when_no_rows(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "_current_accessible_rows", return_value=[]):
            response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["total_count"] == 0
        assert body["has_more"] is False

    @pytest.mark.parametrize("owner_id,expected_name", [
        ("user_id", None),
        ("missing-owner", None),
        (USER_ID, "admin@nexent.com"),
    ])
    def test_list_creator_uses_only_persisted_owner(self, monkeypatch, owner_id, expected_name):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        with patch.object(
            aidp_mgmt_app,
            "_current_accessible_rows",
            return_value=[
                {
                    "kb_id": "kb-legacy",
                    "owner_user_id": owner_id,
                    "creator_name": expected_name,
                    "permission": "EDIT",
                    "ingroup_permission": "PRIVATE",
                    "group_ids": [],
                }
            ],
        ), patch.object(
            aidp_mgmt_app,
            "get_aidp_kb_impl",
            return_value={"kds_name": "Legacy KB", "description": "desc"},
        ):
            response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())

        assert response.status_code == HTTPStatus.OK
        assert response.json()["value"][0]["creator_name"] == expected_name
        assert response.json()["value"][0]["created_by"] == owner_id

    def test_list_marks_kb_unavailable_when_aidp_detail_fails(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_mgmt_app, "_current_accessible_rows", return_value=[
                 {
                     "kb_id": "kb-1", "owner_user_id": USER_ID, "tenant_id": TENANT_ID,
                     "ingroup_permission": "EDIT", "group_ids": [],
                     "resource_status": "ACTIVE", "permission": "EDIT",
                 }
             ]), \
             patch.object(aidp_mgmt_app, "get_aidp_kb_impl",
                          side_effect=AppException(ErrorCode.AIDP_SERVICE_ERROR, "down")), \
             patch.object(aidp_permission_service, "update_resource_status") as mock_status:
            from contracts.errors.codes import ErrorCode as _E
            response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["value"][0]["resource_status"] == "UNAVAILABLE"
        mock_status.assert_not_called()

    def test_list_intersects_before_pagination_and_fetches_only_visible_detail(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from types import SimpleNamespace

        remote_items = [
            {"kds_id": "kb-1"},
            {"kds_id": "kb-2"},
            {"kds_id": "kb-3"},
            {"kds_id": "remote-only"},
        ]
        intersected_rows = [
            {"kb_id": "kb-1", "permission": "EDIT"},
            {"kb_id": "kb-2", "permission": "READ_ONLY"},
            {"kb_id": "kb-3", "permission": "EDIT"},
        ]
        with patch.object(
            aidp_mgmt_app,
            "resolve_current_aidp_access",
            return_value=SimpleNamespace(accessible_rows=intersected_rows),
        ) as mock_snapshot, patch.object(
            aidp_mgmt_app,
            "get_aidp_kb_impl",
            return_value={"kds_name": "Second KB"},
        ) as mock_detail:
            response = client.get(
                "/aidp-mgmt/knowledge-bases?page=2&page_size=1",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["total_count"] == 3
        assert body["has_more"] is True
        assert [item["kds_id"] for item in body["value"]] == ["kb-2"]
        mock_snapshot.assert_called_once_with(
            server_url=aidp_mgmt_app.AIDP_SERVER_URL,
            api_key=aidp_mgmt_app.AIDP_API_KEY,
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            aidp_tenant_id="aidp",
            keyword=None,
        )
        mock_detail.assert_called_once_with(
            aidp_mgmt_app.AIDP_SERVER_URL,
            aidp_mgmt_app.AIDP_API_KEY,
            "kb-2",
        )

    def test_list_forwards_trimmed_keyword_to_aidp(self):
        """A keyword is trimmed before it reaches AIDP."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from types import SimpleNamespace

        with patch.object(
            aidp_mgmt_app,
            "resolve_current_aidp_access",
            return_value=SimpleNamespace(accessible_rows=[]),
        ) as mock_snapshot:
            response = client.get(
                "/aidp-mgmt/knowledge-bases?keyword=%20report%20",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert mock_snapshot.call_args.kwargs["keyword"] == "report"

    def test_list_treats_blank_keyword_as_unfiltered(self):
        """A whitespace-only keyword must not narrow the listing."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from types import SimpleNamespace

        with patch.object(
            aidp_mgmt_app,
            "resolve_current_aidp_access",
            return_value=SimpleNamespace(accessible_rows=[]),
        ) as mock_snapshot:
            response = client.get(
                "/aidp-mgmt/knowledge-bases?keyword=%20%20",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert mock_snapshot.call_args.kwargs["keyword"] is None

    def test_list_skips_detail_when_catalog_row_has_card_metadata(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        complete_row = {
            "kb_id": "kb-1",
            "kds_id": "kb-1",
            "kds_name": "Catalog KB",
            "description": "From catalog",
            "created_at": "2026-01-01T00:00:00Z",
            "create_time": 1767225600,
            "caption_enable": 0,
            "document_count": 8,
            "permission": "EDIT",
        }
        with patch.object(
            aidp_mgmt_app,
            "_current_accessible_rows",
            return_value=[complete_row],
        ), patch.object(aidp_mgmt_app, "get_aidp_kb_impl") as mock_detail:
            response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())

        assert response.status_code == HTTPStatus.OK
        item = response.json()["value"][0]
        assert item["description"] == "From catalog"
        assert item["created_at"] == "2026-01-01T00:00:00Z"
        assert "updated_at" not in item
        assert "document_count" not in item
        assert "chunk_count" not in item
        assert "document_count_reliable" not in item
        mock_detail.assert_not_called()



# Use a lazy import for AppException at module load to avoid breaking the
# fastapi exception handler fixture.
from contracts.errors.exceptions import AppException
from contracts.errors.codes import ErrorCode


# --- Update KB ------------------------------------------------------------


class TestUpdateKnowledgeBase:
    def test_update_rejects_empty_payload(self):
        client = _client()
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")):
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={},
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_calls_aidp_with_payload(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_permission_service, "update_permission",
                          return_value=True) as mock_update_permission, \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl", return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"name": "new"},
            )
        assert response.status_code == HTTPStatus.OK
        mock_update.assert_called_once()
        call_args = mock_update.call_args
        # Production signature: update_aidp_kb_impl(server_url, api_key, kds_id, payload)
        positional = call_args.args
        assert positional[2] == "kb-1"
        assert positional[3] == {"name": "new"}
        mock_update_permission.assert_called_once_with(
            kb_id="kb-1",
            tenant_id="tenant-test",
            kds_name="new",
            updated_by="user-test",
        )


# --- Upload documents ----------------------------------------------------


class TestUploadDocuments:
    def test_upload_calls_aidp_with_files(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        files = [
            ("files", ("doc.txt", io.BytesIO(b"hello"), "text/plain")),
        ]
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "upload_aidp_docs_impl", return_value={
                 "summary": {"total": 1, "success": 0, "failed": 1},
                 "success_list": [],
                 "failed_list": [{
                     "file_name": "doc.txt",
                     "reason_zh": "文件内容为空",
                     "reason_en": "File content is empty",
                 }],
             }) as mock_upload:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents",
                headers=_bearer(),
                files=files,
            )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["failed_list"][0]["reason_en"] == "File content is empty"
        mock_upload.assert_called_once()

    def test_upload_rejects_more_than_fifty_files_without_calling_aidp(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        files = [
            ("files", (f"doc-{index}.txt", io.BytesIO(b"hello"), "text/plain"))
            for index in range(51)
        ]
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "upload_aidp_docs_impl") as mock_upload:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents",
                headers=_bearer(),
                files=files,
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["summary"] == {"total": 51, "success": 0, "failed": 51}
        assert body["failed_list"][0]["reason_zh"] == "单次最多上传 50 个文件"
        mock_upload.assert_not_called()

    def test_upload_merges_oversized_file_with_aidp_result(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        files = [
            ("files", ("valid.pdf", io.BytesIO(b"ok"), "application/pdf")),
            ("files", ("large.txt", io.BytesIO(b"x"), "text/plain")),
        ]
        aidp_result = {
            "summary": {"total": 1, "success": 1, "failed": 0},
            "success_list": [{"file_name": "valid.pdf"}],
            "failed_list": [],
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "AIDP_SMALL_FILE_MAX_SIZE_BYTES", 0), \
             patch.object(aidp_mgmt_app, "upload_aidp_docs_impl",
                          return_value=aidp_result) as mock_upload:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents",
                headers=_bearer(),
                files=files,
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["summary"] == {"total": 2, "success": 1, "failed": 1}
        assert body["failed_list"][0]["file_name"] == "large.txt"
        assert mock_upload.call_args.args[3][0].filename == "valid.pdf"

    def test_upload_applies_twenty_mb_limit_to_json_md_and_html(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        files = [
            ("files", ("large.json", io.BytesIO(b"xx"), "application/json")),
            ("files", ("large.md", io.BytesIO(b"xx"), "text/markdown")),
            ("files", ("large.html", io.BytesIO(b"xx"), "text/html")),
            ("files", ("valid.pdf", io.BytesIO(b"xx"), "application/pdf")),
        ]
        aidp_result = {
            "summary": {"total": 1, "success": 1, "failed": 0},
            "success_list": [{"file_name": "valid.pdf"}],
            "failed_list": [],
        }
        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="EDIT"),
        ), patch.object(
            aidp_mgmt_app, "AIDP_SMALL_FILE_MAX_SIZE_BYTES", 1
        ), patch.object(
            aidp_mgmt_app, "AIDP_OTHER_FILE_MAX_SIZE_BYTES", 10
        ), patch.object(
            aidp_mgmt_app, "upload_aidp_docs_impl", return_value=aidp_result
        ) as mock_upload:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents",
                headers=_bearer(),
                files=files,
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["summary"] == {"total": 4, "success": 1, "failed": 3}
        assert {item["file_name"] for item in body["failed_list"]} == {
            "large.json",
            "large.md",
            "large.html",
        }
        assert [file.filename for file in mock_upload.call_args.args[3]] == ["valid.pdf"]


# --- Remove/download documents -------------------------------------------


class TestAidpDocumentFileOperations:
    def test_remove_forwards_only_uuids(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        aidp_result = {
            "summary": {"total": 2, "success": 1, "failed": 1},
            "success_list": [{"file_uuid": "00000000-0000-4000-8000-000000000001"}],
            "failed_list": [{"file_uuid": "00000000-0000-4000-8000-000000000002"}],
        }
        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="EDIT"),
        ), patch.object(
            aidp_mgmt_app,
            "remove_aidp_docs_impl",
            return_value=aidp_result,
        ) as mock_remove:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/remove",
                headers=_bearer(),
                json={
                    "file_uuids": [
                        "00000000-0000-4000-8000-000000000001",
                        "00000000-0000-4000-8000-000000000002",
                    ]
                },
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == aidp_result
        assert mock_remove.call_args.args[3] == [
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
        ]

    def test_remove_requires_file_uuids(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "remove_aidp_docs_impl") as mock_remove:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/remove",
                headers=_bearer(),
                json={},
            )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        mock_remove.assert_not_called()

    def test_remove_requires_standard_file_uuid(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "remove_aidp_docs_impl") as mock_remove:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/remove",
                headers=_bearer(),
                json={"file_uuids": ["uuid-1"]},
            )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        mock_remove.assert_not_called()

    def test_download_returns_binary_response(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        mock_response = httpx.Response(
            200,
            headers={
                "Content-Type": "text/plain",
                "Content-Disposition": 'attachment; filename="a.txt"',
                "X-File-Size": "5",
            },
            content=b"hello",
            request=httpx.Request("POST", SERVER_URL),
        )

        async def stream_document(*args):
            return mock_response

        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="READ_ONLY"),
        ), patch.object(
            aidp_mgmt_app,
            "stream_aidp_doc_impl",
            side_effect=stream_document,
        ) as mock_download:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/download",
                headers=_bearer(),
                json={"file_uuid": "00000000-0000-4000-8000-000000000001"},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.content == b"hello"
        assert response.headers["content-type"].startswith("text/plain")
        assert response.headers["content-disposition"] == 'attachment; filename="a.txt"'
        assert response.headers["x-file-size"] == "5"
        assert mock_download.call_args.args == (
            SERVER_URL,
            API_KEY,
            "kb-1",
            "00000000-0000-4000-8000-000000000001",
        )
        assert "x-file-name" not in response.headers

    def test_preview_streams_original_document_inline(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        docx_mime = (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        )
        mock_response = httpx.Response(
            200,
            headers={
                "Content-Type": docx_mime,
                # AIDP reports the name it served in this header; for a format
                # it did not convert, it is the uploaded one.
                "X-File-Name": "report.docx",
                "Content-Disposition": 'attachment; filename="report.docx"',
                "X-File-Size": "11",
            },
            content=b"docx-bytes!",
            request=httpx.Request("GET", SERVER_URL),
        )

        async def stream_document(*args):
            return mock_response

        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="READ_ONLY"),
        ), patch.object(
            aidp_mgmt_app,
            "stream_aidp_preview_impl",
            side_effect=stream_document,
        ) as mock_stream:
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/"
                "00000000-0000-4000-8000-000000000001/preview",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        # The original bytes and content type reach the browser untouched: the
        # frontend renders the Office format itself.
        assert response.content == b"docx-bytes!"
        assert response.headers["content-type"] == docx_mime
        # The frontend picks its renderer from the served name, and the
        # disposition is rebuilt as inline instead of forwarding the upstream
        # attachment header.
        assert response.headers["x-file-name"] == "report.docx"
        assert response.headers["content-disposition"] == (
            'inline; filename="report.docx"; filename*=UTF-8\'\'report.docx'
        )
        assert mock_stream.call_args.args == (
            SERVER_URL,
            API_KEY,
            "kb-1",
            "00000000-0000-4000-8000-000000000001",
        )

    def test_preview_reports_the_converted_file_name(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        # AIDP answers an unsupported format with a PDF conversion, so the
        # served name replaces the uploaded extension. The frontend needs the
        # header to know it has to render a PDF.
        mock_response = httpx.Response(
            200,
            headers={
                "Content-Type": "application/pdf",
                "X-File-Name": "sheet.pdf",
                "Content-Disposition": 'attachment; filename="sheet.pdf"',
                "X-File-Size": "8",
            },
            content=b"%PDF-1.4",
            request=httpx.Request("GET", SERVER_URL),
        )

        async def stream_document(*args):
            return mock_response

        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="READ_ONLY"),
        ), patch.object(
            aidp_mgmt_app,
            "stream_aidp_preview_impl",
            side_effect=stream_document,
        ):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/"
                "00000000-0000-4000-8000-000000000001/preview",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert response.content == b"%PDF-1.4"
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["x-file-name"] == "sheet.pdf"
        assert response.headers["content-disposition"] == (
            'inline; filename="sheet.pdf"; filename*=UTF-8\'\'sheet.pdf'
        )

    def test_preview_uri_encodes_a_non_ascii_served_name(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        # httpx decodes header bytes into text, so AIDP's Chinese name arrives as
        # real Unicode - which response headers (latin-1 on the wire) cannot
        # carry. Forwarding it unchanged raised UnicodeEncodeError and answered
        # 500, so the preview failed for every non-ASCII file name.
        mock_response = httpx.Response(
            200,
            headers=[
                (b"content-type", b"application/pdf"),
                (b"x-file-name", "报告.pdf".encode()),
                (b"x-file-size", b"8"),
            ],
            content=b"%PDF-1.4",
            request=httpx.Request("GET", SERVER_URL),
        )

        async def stream_document(*args):
            return mock_response

        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="READ_ONLY"),
        ), patch.object(
            aidp_mgmt_app,
            "stream_aidp_preview_impl",
            side_effect=stream_document,
        ):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/"
                "00000000-0000-4000-8000-000000000001/preview",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert response.content == b"%PDF-1.4"
        # The name travels URI-encoded so it stays within latin-1; the frontend
        # decodes it, and the extension survives encoding unchanged.
        assert response.headers["x-file-name"] == "%E6%8A%A5%E5%91%8A.pdf"
        assert response.headers["content-disposition"] == (
            'inline; filename="__.pdf"; filename*=UTF-8\'\'%E6%8A%A5%E5%91%8A.pdf'
        )

    def test_preview_falls_back_when_aidp_omits_headers(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        mock_response = httpx.Response(
            200,
            content=b"raw",
            request=httpx.Request("GET", SERVER_URL),
        )

        async def stream_document(*args):
            return mock_response

        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="READ_ONLY"),
        ), patch.object(
            aidp_mgmt_app,
            "stream_aidp_preview_impl",
            side_effect=stream_document,
        ):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/"
                "00000000-0000-4000-8000-000000000001/preview",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert response.headers["content-type"] == "application/octet-stream"
        # Without a served name the stream is still served inline, and the
        # viewer falls back to the uploaded name for its renderer choice.
        assert response.headers["content-disposition"] == "inline"
        assert "x-file-name" not in response.headers

    def test_preview_requires_standard_file_uuid(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "stream_aidp_preview_impl") as mock_stream:
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/uuid-1/preview",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        mock_stream.assert_not_called()

    def test_preview_without_read_returns_403(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        original_require = aidp_permission_service.require_permission
        aidp_permission_service.require_permission = MagicMock(
            side_effect=aidp_mgmt_app.HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail="denied",
            )
        )
        try:
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/"
                "00000000-0000-4000-8000-000000000001/preview",
                headers=_bearer(),
            )
        finally:
            aidp_permission_service.require_permission = original_require
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize(
        "file_name, expected",
        [
            ("a.txt", 'inline; filename="a.txt"; filename*=UTF-8\'\'a.txt'),
            # Quotes and backslashes cannot appear in the ASCII fallback.
            (
                'a"b\\c.txt',
                'inline; filename="a_b_c.txt"; filename*=UTF-8\'\'a%22b%5Cc.txt',
            ),
            # Non-ASCII names only survive in the RFC 5987 parameter.
            (
                "报告.pdf",
                'inline; filename="__.pdf"; filename*=UTF-8\'\'%E6%8A%A5%E5%91%8A.pdf',
            ),
        ],
    )
    def test_build_inline_disposition_escapes_the_name(self, file_name, expected):
        from ext_components.aidp.apps import aidp_mgmt_app

        assert aidp_mgmt_app._build_inline_disposition(file_name) == expected

    def test_remove_does_not_invalidate_cache_when_no_file_succeeds(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        aidp_result = {
            "summary": {"total": 1, "success": 0, "failed": 1},
            "success_list": [],
            "failed_list": [{"file_uuid": "00000000-0000-4000-8000-000000000001"}],
        }
        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="EDIT"),
        ), patch.object(
            aidp_mgmt_app,
            "remove_aidp_docs_impl",
            return_value=aidp_result,
        ), patch.object(aidp_mgmt_app, "invalidate_aidp_kb_detail_cache") as mock_kb_cache, patch.object(
            aidp_mgmt_app, "invalidate_aidp_doc_count_cache"
        ) as mock_count_cache:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/remove",
                headers=_bearer(),
                json={"file_uuids": ["00000000-0000-4000-8000-000000000001"]},
            )

        assert response.status_code == HTTPStatus.OK
        mock_kb_cache.assert_not_called()
        mock_count_cache.assert_not_called()

# --- Models list (auth only, no per-KB permission) ------------------------


class TestListModels:
    def test_list_models_returns_aidp_response(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "list_aidp_models_impl",
                          return_value={"models": []}) as mock_models:
            response = client.get("/aidp-mgmt/models", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        mock_models.assert_called_once()


# ---------------------------------------------------------------------------
# _auth edge cases (lines 128-129, 131)
# ---------------------------------------------------------------------------


class TestAuthEdgeCases:
    def test_unauthorized_error_from_get_current_user_id_returns_401(self, monkeypatch):
        """get_current_user_id raises UnauthorizedError -> _auth catches and returns 401."""
        from ext_components.aidp.apps import aidp_mgmt_app
        from contracts.errors.exceptions import UnauthorizedError

        monkeypatch.setattr(
            aidp_mgmt_app.auth_utils_module, "get_current_user_id",
            lambda *_a, **_kw: (_ for _ in ()).throw(
                UnauthorizedError("invalid token")
            ),
        )
        client = _client()
        response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_empty_tenant_id_returns_401(self, monkeypatch):
        """get_current_user_id returns empty tenant -> _auth returns 401."""
        from ext_components.aidp.apps import aidp_mgmt_app

        monkeypatch.setattr(
            aidp_mgmt_app.auth_utils_module, "get_current_user_id",
            lambda *_a, **_kw: ("user-1", ""),
        )
        client = _client()
        response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())
        assert response.status_code == HTTPStatus.UNAUTHORIZED


# ---------------------------------------------------------------------------
# _infer_is_multimodal and _raise_aidp_conflict helpers
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_infer_is_multimodal_with_non_dict(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        assert aidp_mgmt_app._infer_is_multimodal("not a dict") is False
        assert aidp_mgmt_app._infer_is_multimodal(None) is False
        assert aidp_mgmt_app._infer_is_multimodal(42) is False

    def test_infer_is_multimodal_caption_enable_variants(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        assert aidp_mgmt_app._infer_is_multimodal({"caption_enable": 1}) is True
        assert aidp_mgmt_app._infer_is_multimodal({"caption_enable": "1"}) is True
        assert aidp_mgmt_app._infer_is_multimodal({"caption_enable": True}) is True
        assert aidp_mgmt_app._infer_is_multimodal({"caption_enable": 0}) is False
        assert aidp_mgmt_app._infer_is_multimodal({}) is False

    def test_raise_aidp_conflict_translates_to_http_409(self):
        from ext_components.aidp.apps import aidp_mgmt_app
        from fastapi import HTTPException
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(HTTPException) as exc_info:
            aidp_mgmt_app._raise_aidp_conflict(
                IntegrityError("INSERT", {}, Exception("dup"))
            )
        assert exc_info.value.status_code == HTTPStatus.CONFLICT



# ---------------------------------------------------------------------------
# Count endpoint (lines 279-281)
# ---------------------------------------------------------------------------


class TestCountEndpoint:
    def test_count_knowledge_bases_returns_total(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "_current_accessible_rows", return_value=[{}] * 5):
            response = client.get("/aidp-mgmt/knowledge-bases/count", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        assert response.json()["total_count"] == 5


# ---------------------------------------------------------------------------
# List KB - detail fetch success with ACTIVE status (line 230)
# ---------------------------------------------------------------------------


class TestListKbsActiveStatus:
    def test_list_marks_kb_active_when_detail_fetch_succeeds(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_mgmt_app, "_current_accessible_rows", return_value=[
                 {
                     "kb_id": "kb-1", "owner_user_id": USER_ID, "tenant_id": TENANT_ID,
                     "ingroup_permission": "EDIT", "group_ids": [],
                     "resource_status": "ACTIVE", "permission": "EDIT",
                 }
             ]), \
             patch.object(aidp_mgmt_app, "get_aidp_kb_impl",
                          return_value={"kds_name": "name", "description": "desc", "document_count": 3,
                                        "chunk_count": 10, "embedding_model": "model"}):
            response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["value"][0]["resource_status"] == "ACTIVE"
        assert body["value"][0]["kds_name"] == "name"


# ---------------------------------------------------------------------------
# Create KB - edge cases (lines 294, 307-313, 322-326, 333, 363, 368-373)
# ---------------------------------------------------------------------------


class TestCreateKnowledgeBaseEdgeCases:
    def test_user_create_normalizes_shared_permission_to_private(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_mgmt_app, "get_user_role_by_tenant", return_value="USER"), \
             patch.object(aidp_mgmt_app, "create_aidp_kb_impl", return_value={"kds_id": "kb-user"}), \
             patch.object(aidp_permission_service.aidp_permission_db,
                          "get_permission_by_kb_id", return_value=None), \
             patch.object(aidp_permission_service, "create_permission", return_value=1) as mock_perm, \
             patch.object(aidp_permission_service, "update_resource_status", return_value=True):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={"embedding_model": "bge-m3", "name": "User KB", "description": "A test knowledge base",
                      "ingroup_permission": "EDIT", "group_ids": [1]},
            )

        assert response.status_code == HTTPStatus.OK
        perm_kwargs = mock_perm.call_args.kwargs
        assert perm_kwargs["ingroup_permission"] == "PRIVATE"
        assert perm_kwargs["group_ids"] == []

    def test_create_rejects_invalid_ingroup_permission(self):
        client = _client()
        response = client.post(
            "/aidp-mgmt/knowledge-bases",
            headers=_bearer(),
            json={"embedding_model": "bge-m3", "name": "KB", "description": "A test knowledge base",
                  "ingroup_permission": "INVALID_VALUE", "group_ids": [1]},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_create_with_aidp_group_validation_error(self):
        """_validate_group_ids_strict raises AidpGroupValidationError -> 400. Covers line 307-311."""
        client = _client()
        from ext_components.aidp.services import aidp_permission_service
        from ext_components.aidp.consts.aidp_exceptions import AidpGroupValidationError

        with patch("ext_components.aidp.apps.aidp_mgmt_app.create_aidp_kb_impl",
                    return_value={"kds_id": "kb-new"}), \
             patch.object(aidp_permission_service, "_validate_group_ids_strict",
                          side_effect=AidpGroupValidationError(invalid_ids=[999], tenant_id="t")):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={"embedding_model": "bge-m3", "name": "KB", "description": "A test knowledge base",
                      "ingroup_permission": "EDIT", "group_ids": [999]},
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_create_private_skips_group_validation(self):
        """PRIVATE permission: group validation skipped, valid_group_ids=[] (line 313)."""
        client = _client()
        from ext_components.aidp.services import aidp_permission_service

        with patch("ext_components.aidp.apps.aidp_mgmt_app.create_aidp_kb_impl",
                    return_value={"kds_id": "kb-priv"}) as mock_create, \
             patch.object(aidp_permission_service.aidp_permission_db,
                          "get_permission_by_kb_id", return_value=None), \
             patch.object(aidp_permission_service, "create_permission", return_value=1) as mock_perm, \
             patch.object(aidp_permission_service, "update_resource_status", return_value=True):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={"embedding_model": "bge-m3", "name": "Private KB", "description": "A test knowledge base",
                      "ingroup_permission": "PRIVATE"},
            )
        assert response.status_code == HTTPStatus.OK
        # No group validation was called
        perm_kwargs = mock_perm.call_args.kwargs
        assert perm_kwargs["group_ids"] == []

    def test_create_app_exception_from_aidp_reraised(self):
        """AppException from create_aidp_kb_impl is re-raised directly (line 323)."""
        client = _client()
        from ext_components.aidp.services import aidp_permission_service

        with patch("ext_components.aidp.apps.aidp_mgmt_app.create_aidp_kb_impl",
                    side_effect=AppException(ErrorCode.AIDP_AUTH_ERROR, "unauthorized")), \
             patch.object(aidp_permission_service, "_validate_group_ids_strict",
                          side_effect=lambda g, t: list(g)):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={"embedding_model": "bge-m3", "name": "KB", "description": "A test knowledge base",
                      "ingroup_permission": "READ_ONLY", "group_ids": [1]},
            )
        # AIDP_AUTH_ERROR maps to 502
        assert response.status_code == 502

    def test_create_integrity_error_on_permission_insert(self):
        """IntegrityError during create_permission -> _raise_aidp_conflict -> 409 (line 363)."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service
        from sqlalchemy.exc import IntegrityError

        with patch("ext_components.aidp.apps.aidp_mgmt_app.create_aidp_kb_impl",
                    return_value={"kds_id": "kb-dup"}), \
             patch.object(aidp_permission_service, "_validate_group_ids_strict",
                          side_effect=lambda g, t: list(g)), \
             patch.object(aidp_permission_service.aidp_permission_db,
                          "get_permission_by_kb_id", return_value=None), \
             patch.object(aidp_permission_service, "create_permission",
                          side_effect=IntegrityError("INSERT", {}, Exception("dup"))):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={"embedding_model": "bge-m3", "name": "KB", "description": "A test knowledge base",
                      "ingroup_permission": "READ_ONLY", "group_ids": [1]},
            )
        assert response.status_code == HTTPStatus.CONFLICT

    def test_create_generic_exception_from_aidp(self):
        """Generic exception from create_aidp_kb_impl -> AppException with AIDP_SERVICE_ERROR (502)."""
        client = _client()
        from ext_components.aidp.services import aidp_permission_service

        with patch("ext_components.aidp.apps.aidp_mgmt_app.create_aidp_kb_impl",
                    side_effect=RuntimeError("AIDP exploded")), \
             patch.object(aidp_permission_service, "_validate_group_ids_strict",
                          side_effect=lambda g, t: list(g)):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={"embedding_model": "bge-m3", "name": "KB", "description": "A test knowledge base",
                      "ingroup_permission": "READ_ONLY", "group_ids": [1]},
            )
        # AIDP_SERVICE_ERROR maps to 502 in ERROR_CODE_HTTP_STATUS
        assert response.status_code == 502

    def test_create_no_kds_id_from_aidp(self):
        """AIDP returns response without kds_id -> AppException AIDP_SERVICE_ERROR (502)."""
        client = _client()
        from ext_components.aidp.services import aidp_permission_service

        with patch("ext_components.aidp.apps.aidp_mgmt_app.create_aidp_kb_impl",
                    return_value={"name": "kb"}), \
             patch.object(aidp_permission_service, "_validate_group_ids_strict",
                          side_effect=lambda g, t: list(g)):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={"embedding_model": "bge-m3", "name": "KB", "description": "A test knowledge base",
                      "ingroup_permission": "READ_ONLY", "group_ids": [1]},
            )
        # AIDP_SERVICE_ERROR maps to 502
        assert response.status_code == 502

    def test_create_rollback_success_returns_500(self):
        """DB fails -> AIDP rollback succeeds -> 500 returned (HTTPException from handler)."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        delete_mock = MagicMock(return_value=True)
        with patch("ext_components.aidp.apps.aidp_mgmt_app.create_aidp_kb_impl",
                    return_value={"kds_id": "kb-new"}), \
             patch.object(aidp_permission_service, "_validate_group_ids_strict",
                          side_effect=lambda g, t: list(g)), \
             patch.object(aidp_permission_service.aidp_permission_db,
                          "get_permission_by_kb_id", return_value=None), \
             patch.object(aidp_permission_service, "create_permission",
                          side_effect=RuntimeError("db down")), \
             patch.object(aidp_mgmt_app, "delete_aidp_kb_impl", delete_mock):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={"embedding_model": "bge-m3", "name": "KB", "description": "A test knowledge base",
                      "ingroup_permission": "READ_ONLY", "group_ids": [1]},
            )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        delete_mock.assert_called_once()

    def test_create_rollback_failure_marks_orphaned(self):
        """DB fails -> AIDP rollback also fails -> ORPHANED status + 500."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch("ext_components.aidp.apps.aidp_mgmt_app.create_aidp_kb_impl",
                    return_value={"kds_id": "kb-new"}), \
             patch.object(aidp_permission_service, "_validate_group_ids_strict",
                          side_effect=lambda g, t: list(g)), \
             patch.object(aidp_permission_service.aidp_permission_db,
                          "get_permission_by_kb_id", return_value=None), \
             patch.object(aidp_permission_service, "create_permission",
                          side_effect=RuntimeError("db down")), \
             patch.object(aidp_mgmt_app, "delete_aidp_kb_impl",
                          side_effect=RuntimeError("rollback failed")), \
             patch.object(aidp_permission_service, "update_resource_status") as mock_status:
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={"embedding_model": "bge-m3", "name": "KB", "description": "A test knowledge base",
                      "ingroup_permission": "READ_ONLY", "group_ids": [1]},
            )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        mock_status.assert_called_once()
        assert mock_status.call_args.kwargs["status"] == "ORPHANED"


# ---------------------------------------------------------------------------
# Get KB - AppException fetch failure (lines 403-410)
# ---------------------------------------------------------------------------


class TestGetKbFetchFailure:
    def test_get_kb_marks_unavailable_on_aidp_error(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "get_aidp_kb_impl",
                          side_effect=AppException(ErrorCode.AIDP_SERVICE_ERROR, "down")), \
             patch.object(aidp_mgmt_app, "count_aidp_docs_impl",
                          side_effect=AppException(ErrorCode.AIDP_SERVICE_ERROR, "count down")), \
             patch.object(aidp_mgmt_app.aidp_permission_db, "get_permission_by_kb_id", return_value=None), \
             patch.object(aidp_permission_service, "update_resource_status") as mock_status:
            response = client.get("/aidp-mgmt/knowledge-bases/kb-1", headers=_bearer())
        # The detail view degrades instead of failing: the count fetch only
        # runs for ACTIVE knowledge bases, so a downed AIDP detail + count no
        # longer escalates into a 5xx detail response.
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["resource_status"] == "UNAVAILABLE"
        assert "document_count" not in body
        assert "document_count_reliable" not in body
        mock_status.assert_called_once()


# ---------------------------------------------------------------------------
# Set permission - edge cases (lines 519, 535)
# ---------------------------------------------------------------------------


class TestSetPermissionEdgeCases:
    def test_user_cannot_change_private_kb_to_shared_permission(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_mgmt_app, "get_user_role_by_tenant", return_value="USER"), \
             patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_permission_service, "update_permission") as mock_update:
            response = client.patch(
                "/aidp-mgmt/aidp-permissions/kb-user",
                headers=_bearer(),
                json={"ingroup_permission": "READ_ONLY", "group_ids": [1]},
            )

        assert response.status_code == HTTPStatus.FORBIDDEN
        mock_update.assert_not_called()

    def test_set_permission_rejects_unsupported_value(self):
        client = _client()
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")):
            response = client.patch(
                "/aidp-mgmt/aidp-permissions/kb-1",
                headers=_bearer(),
                json={"ingroup_permission": "INVALID_VAL", "group_ids": [1]},
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_set_permission_group_validation_error(self):
        """_validate_group_ids_strict raises AidpGroupValidationError -> 400."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service
        from ext_components.aidp.consts.aidp_exceptions import AidpGroupValidationError

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_permission_service, "_validate_group_ids_strict",
                          side_effect=AidpGroupValidationError(invalid_ids=[999], tenant_id="t")):
            response = client.patch(
                "/aidp-mgmt/aidp-permissions/kb-1",
                headers=_bearer(),
                json={"ingroup_permission": "EDIT", "group_ids": [999]},
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST


# ---------------------------------------------------------------------------
# Create KB kds_name fallback chain (line 355)
# ---------------------------------------------------------------------------


class TestCreateKnowledgeBaseKdsName:
    """Covers the kds_name fallback chain in create_knowledge_base:
    body.name -> aidp_result.kds_name -> aidp_result.name -> ''
    """

    def _run_create(self, aidp_result, body_name="KB"):
        """Helper: POST create and capture create_permission kwargs."""
        client = _client()
        from ext_components.aidp.services import aidp_permission_service

        with patch("ext_components.aidp.apps.aidp_mgmt_app.create_aidp_kb_impl",
                    return_value=aidp_result), \
             patch.object(aidp_permission_service.aidp_permission_db,
                          "get_permission_by_kb_id", return_value=None), \
             patch.object(aidp_permission_service, "create_permission",
                          return_value=1) as mock_perm, \
             patch.object(aidp_permission_service, "update_resource_status",
                          return_value=True), \
             patch.object(aidp_permission_service, "_validate_group_ids_strict",
                          side_effect=lambda g, t: list(g)):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={"embedding_model": "bge-m3", "name": body_name, "description": "A test knowledge base",
                      "ingroup_permission": "READ_ONLY",
                      "group_ids": [1]},
            )
        assert response.status_code == HTTPStatus.OK
        return mock_perm.call_args.kwargs

    def test_create_passes_kds_name_from_body_name(self):
        """body.name is used as kds_name."""
        kwargs = self._run_create({"kds_id": "kb-1"}, body_name="My KB")
        assert kwargs["kds_name"] == "My KB"

    def test_create_falls_back_to_aidp_result_kds_name(self):
        """body.name empty -> falls back to aidp_result['kds_name']."""
        kwargs = self._run_create({"kds_id": "kb-1", "kds_name": "AIDP Name"},
                                  body_name="")
        assert kwargs["kds_name"] == "AIDP Name"

    def test_create_falls_back_to_aidp_result_name(self):
        """body.name empty, aidp_result has no kds_name -> falls back to aidp_result['name']."""
        kwargs = self._run_create({"kds_id": "kb-1", "name": "AIDP Display"},
                                  body_name="")
        assert kwargs["kds_name"] == "AIDP Display"

    def test_create_falls_back_to_empty_string(self):
        """All fallbacks empty -> kds_name is ''."""
        kwargs = self._run_create({"kds_id": "kb-1"}, body_name="")
        assert kwargs["kds_name"] == ""


# ---------------------------------------------------------------------------
# Update KB kds_name sync (lines 438-449)
# ---------------------------------------------------------------------------


class TestUpdateKnowledgeBaseKdsNameSync:
    """Covers kds_name sync to permission table on update_knowledge_base."""

    def test_update_syncs_kds_name_to_database_when_name_changes(self):
        """body.name set -> perms.update_permission called with kds_name."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"kds_name": "Updated Name", "ok": True}), \
             patch.object(aidp_mgmt_app.perms, "update_permission",
                          return_value=True) as mock_update_perm:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"name": "Updated Name"},
            )
        assert response.status_code == HTTPStatus.OK
        mock_update_perm.assert_called_once()
        kwargs = mock_update_perm.call_args.kwargs
        assert kwargs["kds_name"] == "Updated Name"

    def test_update_skips_sync_when_no_name_change(self):
        """body.name not set, aidp result has no kds_name ->
        perms.update_permission NOT called with kds_name."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"description": "updated desc"}), \
             patch.object(aidp_mgmt_app.perms, "update_permission",
                          return_value=True) as mock_update_perm:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"description": "updated desc"},
            )
        assert response.status_code == HTTPStatus.OK
        # kds_name is None/empty in both result and body -> sync skipped
        mock_update_perm.assert_not_called()


# ---------------------------------------------------------------------------
# Document list - all-status history data source
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Dedicated detail-page endpoints: ingested files, upload tasks, retry
# ---------------------------------------------------------------------------


class TestKnowledgeFilesEndpoint:
    """GET /knowledge-bases/{kds_id}/files - ingested files for the detail page."""

    def test_file_search_skips_count_and_reports_next_page(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        page = {
            "value": [{"file_uuid": "f-1", "file_name": "制度手册.pdf"}],
            "next_link": "/next-page",
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "list_aidp_docs_impl",
                          return_value=page) as list_docs, \
             patch.object(aidp_mgmt_app, "_load_cached_doc_count",
                          side_effect=AssertionError("keyword search must not call Count")):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/files?page=2&page_size=1&keyword=%E5%88%B6%E5%BA%A6",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["value"] == page["value"]
        assert body["has_more"] is True
        assert body["total_count"] == 2  # (page - 1) * page_size + rows
        assert body["total_reliable"] is False
        assert body["processing_count"] == 0
        list_docs.assert_called_once_with(
            SERVER_URL, API_KEY, "kb-1", 2, 1, "制度"
        )

    def test_file_list_stops_on_short_filtered_page(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        page = {
            "value": [{"file_uuid": "f-1"}, {"file_uuid": "f-2"}],
            # The live service returns next_link on every page, including the
            # last one, so its presence must not keep "next" enabled.
            "next_link": "/next-page",
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "list_aidp_docs_impl",
                          return_value=page):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/files?page=1&page_size=5&keyword=x",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["has_more"] is False
        assert body["total_reliable"] is False

    def test_file_list_reports_more_on_full_filtered_page(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        page = {
            "value": [{"file_uuid": "f-1"}, {"file_uuid": "f-2"}],
            "next_link": "/next-page",
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "list_aidp_docs_impl",
                          return_value=page):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/files?page=1&page_size=2&keyword=x",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json()["has_more"] is True

    def test_file_list_rejects_malformed_payload(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "list_aidp_docs_impl",
                          return_value={"unexpected": True}), \
             patch.object(aidp_mgmt_app, "count_aidp_docs_impl", return_value=1):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/files",
                headers=_bearer(),
            )

        assert response.status_code == AppException(
            ErrorCode.AIDP_RESPONSE_ERROR
        ).http_status
        assert response.json()["code"] == ErrorCode.AIDP_RESPONSE_ERROR.value

    def test_unfiltered_file_list_uses_cached_count(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        rows = [{"file_uuid": f"f-{index}"} for index in range(10)]
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "list_aidp_docs_impl",
                          return_value={"value": rows}) as list_docs, \
             patch.object(aidp_mgmt_app, "count_aidp_docs_impl",
                          return_value=12) as count_docs:
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/files?page=1&page_size=10",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["total_count"] == 12
        assert body["total_reliable"] is True
        assert body["has_more"] is True  # 12 > 1 * 10 with a full page
        assert body["processing_count"] == 0
        list_docs.assert_called_once_with(SERVER_URL, API_KEY, "kb-1", 1, 10, None)
        count_docs.assert_called_once_with(SERVER_URL, API_KEY, "kb-1")

    def test_file_list_propagates_count_failure(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "list_aidp_docs_impl",
                          return_value={"value": [{"file_uuid": "f-1"}]}), \
             patch.object(aidp_mgmt_app, "count_aidp_docs_impl",
                          side_effect=AppException(ErrorCode.AIDP_SERVICE_ERROR, "count down")):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/files?page=1&page_size=10",
                headers=_bearer(),
            )

        # Count failures propagate; the endpoint does not degrade to a
        # page-local total.
        assert response.status_code == AppException(ErrorCode.AIDP_SERVICE_ERROR).http_status
        assert response.json()["code"] == ErrorCode.AIDP_SERVICE_ERROR.value

    def test_file_list_propagates_upstream_list_failure(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        list_error = AppException(ErrorCode.AIDP_CONNECTION_ERROR, "AIDP is unavailable")
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "list_aidp_docs_impl",
                          side_effect=list_error), \
             patch.object(aidp_mgmt_app, "count_aidp_docs_impl", return_value=0):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/files",
                headers=_bearer(),
            )

        assert response.status_code == list_error.http_status
        assert response.json()["code"] == ErrorCode.AIDP_CONNECTION_ERROR.value


class TestUploadTasksEndpoint:
    """GET /knowledge-bases/{kds_id}/upload-tasks - AIDP file history view."""

    def test_upload_task_query_forwards_filters_and_uses_aidp_stats(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        history = {
            "value": [{
                "file_uuid": "f-2", "file_name": "制度手册.pdf", "status": 4,
                # The upstream API owns the 30-day retention window; the proxy
                # must not apply a second local timestamp filter.
                "created_at": "2000-01-01T00:00:00Z",
            }],
            "total_count": 12,
            "next_link": "/next-page",
            "total_record_count": 31,
            "processing_record_count": 3,
            "failed_record_count": 2,
            "success_record_count": 24,
            "waiting_record_count": 2,
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "_resolve_doc_history_channel",
                          return_value={"fs_id": "fs-1", "src_dir": "/aidp/knowledge/kb-1"}), \
             patch.object(aidp_mgmt_app, "list_aidp_doc_history_impl",
                          return_value=history) as list_history:
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks?page=2&page_size=7&keyword=%E5%88%B6%E5%BA%A6&status=4",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["value"] == history["value"]
        # Filtered pagination uses the row count: the live service always
        # returns next_link and total_record_count has not been verified for
        # status-filtered queries.
        assert body["total_count"] == 8  # (page - 1) * page_size + rows
        assert body["total_reliable"] is False
        assert body["has_more"] is False
        assert body["stats"] == {
            "total": 31,
            "extracting": 3,
            "failed": 2,
            "success": 24,
            "queued": 2,
        }
        assert body["retention_days"] == 30
        list_history.assert_called_once_with(
            SERVER_URL, API_KEY, "fs-1", "/aidp/knowledge/kb-1", "kb-1", None,
            2, 7, 4, "制度",
        )

    def test_filtered_upload_task_short_page_disables_next_page(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        # Keyword-only queries (status omitted/0) can trust the filtered
        # total_record_count; a short page is the last page.
        history = {
            "value": [{"file_uuid": "f-1", "file_name": "制度手册.pdf", "status": 1}],
            "total_count": 1,
            "next_link": "/next-page",
            "total_record_count": 1,
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "_resolve_doc_history_channel",
                          return_value={"fs_id": "fs-1", "src_dir": "/aidp/knowledge/kb-1"}), \
             patch.object(aidp_mgmt_app, "list_aidp_doc_history_impl",
                          return_value=history):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks?page=1&page_size=10&keyword=%E5%88%B6%E5%BA%A6",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["total_reliable"] is True
        assert body["has_more"] is False
        assert body["total_count"] == 1
        assert body["stats"]["total"] == 1

    def test_unfiltered_upload_task_query_trusts_global_total(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        # Without keyword/status filters total_record_count matches the listed
        # set, so the unfiltered list keeps the reliable global total and the
        # page-jump pagination it enables.
        history = {
            "value": [{"file_uuid": "f-1", "file_name": "制度手册.pdf", "status": 1}],
            "total_count": 1,
            "next_link": "/next-page",
            "total_record_count": 31,
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "_resolve_doc_history_channel",
                          return_value={"fs_id": "fs-1", "src_dir": "/aidp/knowledge/kb-1"}), \
             patch.object(aidp_mgmt_app, "list_aidp_doc_history_impl",
                          return_value=history) as list_history:
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks?page=1&page_size=10&status=0",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["total_count"] == 31
        assert body["total_reliable"] is True
        assert body["has_more"] is True
        assert body["stats"]["total"] == 31
        list_history.assert_called_once_with(
            SERVER_URL, API_KEY, "fs-1", "/aidp/knowledge/kb-1", "kb-1", None,
            1, 10, 0, None,
        )

    def test_filtered_upload_task_full_page_reports_more(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        history = {
            "value": [
                {"file_uuid": f"f-{index}", "file_name": "制度手册.pdf", "status": 1}
                for index in range(10)
            ],
            "next_link": "/next-page",
            "total_record_count": 31,
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "_resolve_doc_history_channel",
                          return_value={"fs_id": "fs-1", "src_dir": "/aidp/knowledge/kb-1"}), \
             patch.object(aidp_mgmt_app, "list_aidp_doc_history_impl",
                          return_value=history):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks?page=1&page_size=10&keyword=%E5%88%B6%E5%BA%A6",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["total_reliable"] is True
        assert body["has_more"] is True

    def test_filtered_upload_task_exact_full_last_page_disables_next(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        history = {
            "value": [
                {"file_uuid": f"f-{index}", "file_name": "制度手册.pdf", "status": 1}
                for index in range(10)
            ],
            "next_link": "/next-page",
            "total_record_count": 10,
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "_resolve_doc_history_channel",
                          return_value={"fs_id": "fs-1", "src_dir": "/aidp/knowledge/kb-1"}), \
             patch.object(aidp_mgmt_app, "list_aidp_doc_history_impl",
                          return_value=history):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks?page=1&page_size=10&keyword=%E5%88%B6%E5%BA%A6",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["total_reliable"] is True
        assert body["total_count"] == 10
        assert body["has_more"] is False

    def test_unfiltered_upload_task_last_page_ignores_next_link(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        history = {
            "value": [
                {"file_uuid": f"f-{index}", "file_name": "制度手册.pdf", "status": 1}
                for index in range(10)
            ],
            # The live service returns next_link even on the last page.
            "next_link": "/next-page",
            "total_record_count": 20,
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "_resolve_doc_history_channel",
                          return_value={"fs_id": "fs-1", "src_dir": "/aidp/knowledge/kb-1"}), \
             patch.object(aidp_mgmt_app, "list_aidp_doc_history_impl",
                          return_value=history):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks?page=2&page_size=10&status=0",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["total_count"] == 20
        assert body["total_reliable"] is True
        assert body["has_more"] is False

    def test_upload_task_listing_survives_unresolvable_channel(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "_resolve_doc_history_channel",
                          return_value=None), \
             patch.object(aidp_mgmt_app, "list_aidp_doc_history_impl",
                          side_effect=AssertionError("no channel means no history scan")):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["value"] == []
        assert body["total_count"] == 0
        assert body["has_more"] is False
        assert body["total_reliable"] is False
        assert body["stats"] == {
            "total": 0, "extracting": 0, "failed": 0, "success": 0, "queued": 0,
        }
        assert body["retention_days"] == 30


class TestUploadTaskRetryEndpoint:
    """POST /knowledge-bases/{kds_id}/upload-tasks/retry."""

    def test_retry_delegates_selected_file_validation_to_aidp(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        file_uuid = "00000000-0000-4000-8000-000000000003"
        upstream_result = {
            "success_list": [{"file_uuid": file_uuid}],
            "failed_list": [],
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "list_aidp_doc_history_impl",
                          side_effect=AssertionError("retry must not scan history")), \
             patch.object(aidp_mgmt_app, "retry_aidp_docs_impl",
                          return_value=upstream_result) as retry_docs:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks/retry",
                headers=_bearer(),
                json={"file_uuids": [file_uuid]},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == upstream_result
        retry_docs.assert_called_once_with(SERVER_URL, API_KEY, "kb-1", [file_uuid])

    def test_retry_requires_edit_permission(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        # Exercise the real permission matrix: a DEV user who matched the
        # record's group resolves to READ_ONLY, which must not satisfy the
        # endpoint's EDIT requirement.
        readonly_row = {
            "kb_id": "kb-1",
            "owner_user_id": "another-owner",
            "ingroup_permission": "READ_ONLY",
            "group_ids": [7],
        }
        with patch.object(aidp_permission_service, "_get_permission_record",
                          return_value=readonly_row), \
             patch.object(aidp_permission_service, "_get_user_role",
                          return_value="DEV"), \
             patch.object(aidp_permission_service, "_get_user_groups",
                          return_value=[7]), \
             patch.object(aidp_mgmt_app, "retry_aidp_docs_impl") as retry_docs:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks/retry",
                headers=_bearer(),
                json={"file_uuids": ["00000000-0000-4000-8000-000000000003"]},
            )
        assert response.status_code == HTTPStatus.FORBIDDEN
        retry_docs.assert_not_called()

    def test_retry_dedupes_file_uuids(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        first = "00000000-0000-4000-8000-000000000003"
        second = "00000000-0000-4000-8000-000000000004"
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "retry_aidp_docs_impl",
                          return_value={"success_list": [], "failed_list": []}) as retry_docs:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks/retry",
                headers=_bearer(),
                json={"file_uuids": [first, second, first]},
            )

        assert response.status_code == HTTPStatus.OK
        retry_docs.assert_called_once_with(SERVER_URL, API_KEY, "kb-1", [first, second])

    def test_retry_rejects_empty_uuid_list(self):
        client = _client()
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")):
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks/retry",
                headers=_bearer(),
                json={"file_uuids": []},
            )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_retry_invalidates_detail_and_count_caches(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "retry_aidp_docs_impl",
                          return_value={"success_list": [], "failed_list": []}), \
             patch.object(aidp_mgmt_app, "invalidate_aidp_kb_detail_cache") as kb_cache, \
             patch.object(aidp_mgmt_app, "invalidate_aidp_doc_count_cache") as count_cache:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks/retry",
                headers=_bearer(),
                json={"file_uuids": ["00000000-0000-4000-8000-000000000003"]},
            )

        assert response.status_code == HTTPStatus.OK
        kb_cache.assert_called_once_with(SERVER_URL, API_KEY, "kb-1")
        count_cache.assert_called_once_with(SERVER_URL, API_KEY, "kb-1")


class TestUpdateKbConfigurationFields:
    """VLM / chunk settings carried by UpdateKbRequest (detail settings modal)."""

    def test_update_forwards_vlm_and_chunk_settings(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        payload = {
            "chunk_mode": 1,
            "chunk_token_num": 512,
            "chunk_overlap_num": 51,
            "topk": 5,
            "caption_enable": 1,
            "vlm_model": "qwen2-vl-7b",
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json=payload,
            )

        assert response.status_code == HTTPStatus.OK
        mock_update.assert_called_once()
        assert mock_update.call_args.args[2] == "kb-1"
        assert mock_update.call_args.args[3] == payload

    def test_update_rejects_out_of_range_chunk_settings(self):
        client = _client()
        from ext_components.aidp.services import aidp_permission_service

        payloads = [
            {"chunk_mode": 2},
            {"chunk_token_num": 255},
            {"chunk_token_num": 4097},
            {"chunk_overlap_num": 1.5},
            {"chunk_token_num": 512, "chunk_overlap_num": 257},
        ]
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")):
            for payload in payloads:
                response = client.put(
                    "/aidp-mgmt/knowledge-bases/kb-1",
                    headers=_bearer(),
                    json=payload,
                )
                assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    # ---- Knowledge graph settings (detail information tab) ----

    def test_update_sends_only_edited_graph_fields_with_enabled_flag(self):
        """A partial graph_config edit forwards only the edited fields in
        AIDP string format, and echoes is_exist_graph=true which AIDP
        requires alongside any graph_config PATCH."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        current_graph = {
            "domain": "通用",
            "prompt_language": "中文",
            "prompt_text": "default prompt",
            "llm_model_name": "qwen-max",
            "retrieve_subgraph_hop": "2",
            "no_think_mode": "是",
            "synonym_merge_enable": "否",
            "disambiguation_enable": "是",
        }
        current = {
            "kds_id": "kb-1",
            "is_exist_graph": True,
            "graph_config": json.dumps(current_graph, ensure_ascii=False),
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "_load_cached_kb_detail",
                          return_value=current), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"graph_config": {
                    "llm_model_name": "gpt-4o",
                    "retrieve_subgraph_hop": 3,
                    "no_think_mode": False,
                }},
            )

        assert response.status_code == HTTPStatus.OK
        mock_update.assert_called_once()
        payload = mock_update.call_args.args[3]
        # AIDP merges graph_config server-side, so only the edited fields are
        # sent; resending stored ones can make AIDP reject the PATCH.
        assert payload["graph_config"] == json.dumps(
            {
                "llm_model_name": "gpt-4o",
                "retrieve_subgraph_hop": "3",
                "no_think_mode": "否",
            },
            ensure_ascii=False,
        )
        # AIDP requires is_exist_graph=true alongside any graph_config edit.
        assert payload["is_exist_graph"] is True

    def test_update_forwards_graph_disable(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        current = {"kds_id": "kb-1", "is_exist_graph": True}
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "_load_cached_kb_detail",
                          return_value=current), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"is_exist_graph": False},
            )

        assert response.status_code == HTTPStatus.OK
        mock_update.assert_called_once()
        assert mock_update.call_args.args[3] == {"is_exist_graph": False}

    def test_update_rejects_graph_reenable(self):
        """The graph switch is one-way: re-enabling is permanently rejected."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        current = {"kds_id": "kb-1", "is_exist_graph": True}
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "_load_cached_kb_detail",
                          return_value=current), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"is_exist_graph": True},
            )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "cannot be re-enabled" in response.json()["message"]
        mock_update.assert_not_called()

    def test_update_rejects_graph_config_when_graph_disabled(self):
        """Once the graph is off its configuration is locked for updates."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        current = {"kds_id": "kb-1", "is_exist_graph": False}
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "_load_cached_kb_detail",
                          return_value=current), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"graph_config": {"llm_model_name": "gpt-4o"}},
            )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "graph settings are locked" in response.json()["message"]
        mock_update.assert_not_called()

    @pytest.mark.parametrize("graph_updates", [
        {"retrieve_subgraph_hop": 4},      # out of range
        {"retrieve_subgraph_hop": "2"},    # string instead of int
        {"retrieve_subgraph_hop": True},   # bool is an int subclass
        {"llm_model_name": "   "},         # blank model name
        {"no_think_mode": "是"},           # string instead of bool
        {"domain": "通用"},                # non-editable graph field
    ])
    def test_update_rejects_invalid_graph_values(self, graph_updates):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        current = {"kds_id": "kb-1", "is_exist_graph": True, "graph_config": "{}"}
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "_load_cached_kb_detail",
                          return_value=current), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"graph_config": graph_updates},
            )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        mock_update.assert_not_called()


class TestNormalizeKbConfigFields:
    """_normalize_kb_config_fields - kms_config_str merge and alias mapping."""

    def test_merges_kms_config_str_and_maps_topk(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "kds_id": "kb-1",
            "kms_config_str": (
                '{"chunk_mode": 1, "embedding_model": "bge-m3", '
                '"top_k": 5, "similarity": 0.6, "chunk_token_num": 512}'
            ),
            "caption_enable": 1,
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["chunk_mode"] == 1
        assert out["embedding_model"] == "bge-m3"
        assert out["chunk_token_num"] == 512
        assert out["topk"] == 5
        assert out["similarity"] == 0.6
        assert out["is_multimodal"] is True

    def test_top_level_values_win_and_bad_json_is_tolerated(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "topk": 7,
            "is_multimodal": False,
            "kms_config_str": "not valid json",
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["topk"] == 7
        assert out["is_multimodal"] is False
        assert out["kms_config_str"] == "not valid json"

    def test_non_dict_detail_passes_through(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        assert aidp_mgmt_app._normalize_kb_config_fields(None) is None
        assert aidp_mgmt_app._normalize_kb_config_fields("x") == "x"

    def test_normalizes_graph_config_flags_and_lifts_llm_model(self):
        """AIDP serializes graph toggles as 是/否 and the hop as a string; the
        detail view expects native booleans, an int hop and a top-level LLM."""
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "graph_config": json.dumps({
                "llm_model_name": "qwen-max",
                "retrieve_subgraph_hop": "2",
                "no_think_mode": "是",
                "synonym_merge_enable": "否",
                "disambiguation_enable": "是",
            }, ensure_ascii=False),
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        graph = out["graph_config"]
        assert isinstance(graph, dict)
        assert graph["retrieve_subgraph_hop"] == 2
        assert graph["no_think_mode"] is True
        assert graph["synonym_merge_enable"] is False
        assert graph["disambiguation_enable"] is True
        assert out["llm_model_name"] == "qwen-max"

    def test_top_level_llm_model_wins_over_graph_config(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "llm_model_name": "top-model",
            "graph_config": json.dumps(
                {"llm_model_name": "nested-model"}, ensure_ascii=False
            ),
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["llm_model_name"] == "top-model"
        assert out["graph_config"]["llm_model_name"] == "nested-model"

    def test_bad_graph_config_string_is_tolerated(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {"graph_config": "not valid json"}
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["graph_config"] == "not valid json"
        assert "llm_model_name" not in out


# ---------------------------------------------------------------------------
# Coverage completion: tag cleanup delegation, doc-history channel helpers,
# graph-config degraded storage, response-shape guards and normalization
# edge branches
# ---------------------------------------------------------------------------


def test_cleanup_document_assignments_delegates_to_tag_management(monkeypatch):
    """The delete flow keeps document assignment usage in sync."""
    from importlib import import_module

    tag_service = import_module("management.services.tag.library")
    from ext_components.aidp.apps import aidp_mgmt_app

    sentinel = MagicMock()
    monkeypatch.setattr(tag_service, "TagManagementService", sentinel)

    aidp_mgmt_app._cleanup_document_assignments_for_deleted_knowledge_base(
        "tenant-1", "kb-9", "user-1"
    )

    sentinel.cleanup_document_assignments_for_knowledge_base.assert_called_once_with(
        "tenant-1", "aidp", "kb-9", "user-1"
    )


class TestHistoryFallbackLogging:
    """The history fallback is reported once per knowledge base."""

    def test_warns_once_then_degrades_to_debug(self, caplog):
        from ext_components.aidp.apps import aidp_mgmt_app

        caplog.set_level(logging.DEBUG)
        aidp_mgmt_app._HISTORY_FALLBACK_REPORTED.discard("kb-fb")
        try:
            aidp_mgmt_app._log_history_fallback("kb-fb", "reason-one")
            aidp_mgmt_app._log_history_fallback("kb-fb", "reason-two")
        finally:
            aidp_mgmt_app._HISTORY_FALLBACK_REPORTED.discard("kb-fb")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(warnings) == 1
        assert "kb-fb" in warnings[0].getMessage()
        assert "reason-one" in warnings[0].getMessage()
        assert len(debugs) == 1
        assert "reason-two" in debugs[0].getMessage()


class TestResolveDocHistoryChannel:
    """Channel resolution feeds the upload-task history endpoint."""

    def test_returns_the_channel_selected_for_the_knowledge_base(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        channels = [{"fs_id": "fs-1", "src_dir": "/aidp/knowledge/kb-1"}]
        with patch.object(aidp_mgmt_app, "get_cached_aidp_channels",
                          return_value=channels) as mock_cache, \
             patch.object(aidp_mgmt_app, "select_aidp_channel",
                          return_value=channels[0]) as mock_select:
            channel = aidp_mgmt_app._resolve_doc_history_channel(
                SERVER_URL, API_KEY, "kb-1"
            )

        assert channel == channels[0]
        assert mock_cache.call_args.kwargs["kds_id"] == "kb-1"
        assert mock_select.call_args.args == (channels, "kb-1")

    def test_returns_none_and_reports_channel_shape_when_no_channel_matches(
        self, caplog
    ):
        from ext_components.aidp.apps import aidp_mgmt_app

        caplog.set_level(logging.WARNING)
        aidp_mgmt_app._HISTORY_FALLBACK_REPORTED.discard("kb-noch")
        try:
            with patch.object(aidp_mgmt_app, "get_cached_aidp_channels",
                              return_value=[{"name": "channel-a"}]), \
                 patch.object(aidp_mgmt_app, "select_aidp_channel",
                              return_value=None):
                channel = aidp_mgmt_app._resolve_doc_history_channel(
                    SERVER_URL, API_KEY, "kb-noch"
                )
        finally:
            aidp_mgmt_app._HISTORY_FALLBACK_REPORTED.discard("kb-noch")

        assert channel is None
        message = caplog.records[-1].getMessage()
        assert "kb-noch" in message
        # The reported reason must make the channel payload shape visible.
        assert "'name'" in message


class TestUpdateGraphConfigDegradedStorage:
    """The stored graph_config shape never leaks into the PATCH payload."""

    @pytest.mark.parametrize(
        "stored",
        ["not valid json", "[1, 2]", None, {"domain": "通用"}],
    )
    def test_stored_config_shape_does_not_affect_patch_payload(self, stored):
        """Only edited fields are sent, so unparseable or legacy stored
        configs cannot break or pollute the update."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        current = {"kds_id": "kb-1", "is_exist_graph": True}
        if stored is not None:
            current["graph_config"] = stored
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "_load_cached_kb_detail",
                          return_value=current), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"graph_config": {"llm_model_name": "gpt-4o"}},
            )

        assert response.status_code == HTTPStatus.OK
        payload = mock_update.call_args.args[3]
        assert payload["graph_config"] == json.dumps(
            {"llm_model_name": "gpt-4o"}, ensure_ascii=False
        )
        assert payload["is_exist_graph"] is True


class TestSetPermissionBlankName:
    def test_set_permission_rejects_blank_name(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "save_kb_settings") as mock_save:
            response = client.patch(
                "/aidp-mgmt/aidp-permissions/kb-1",
                headers=_bearer(),
                json={"ingroup_permission": "PRIVATE", "name": "   "},
            )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "blank" in response.json()["message"]
        mock_save.assert_not_called()


class TestNormalizeKbConfigFieldsEdgeCases:
    """Merge precedence and graph normalization edge branches."""

    def test_blank_or_non_string_kms_config_str_is_ignored(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        for raw in ("   ", 123, None):
            detail = {"kms_config_str": raw, "kds_id": "kb-1"}
            out = aidp_mgmt_app._normalize_kb_config_fields(detail)
            assert "chunk_mode" not in out

    def test_top_level_value_wins_over_kms_config_str(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "kms_config_str": '{"embedding_model": "nested"}',
            "embedding_model": "top-level",
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["embedding_model"] == "top-level"

    def test_kms_config_str_fills_none_valued_top_level_keys(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "kms_config_str": '{"embedding_model": "nested"}',
            "embedding_model": None,
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["embedding_model"] == "nested"

    def test_non_digit_hop_is_kept_verbatim(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "graph_config": json.dumps({"retrieve_subgraph_hop": "auto"}),
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["graph_config"]["retrieve_subgraph_hop"] == "auto"

    def test_blank_nested_llm_model_is_not_lifted(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "graph_config": json.dumps(
                {"llm_model_name": "   ", "no_think_mode": "是"}, ensure_ascii=False
            ),
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert "llm_model_name" not in out
        assert out["graph_config"]["no_think_mode"] is True

    def test_kms_config_str_with_non_dict_json_is_ignored(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {"kms_config_str": "[1, 2]"}
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert "chunk_mode" not in out


class TestDeleteKnowledgeBaseFailure:
    """An upstream delete failure leaves local permission state untouched."""

    def test_delete_reports_failure_and_skips_local_cleanup(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "delete_aidp_kb_impl",
                          return_value=False), \
             patch.object(aidp_permission_service, "soft_delete_permission") as mock_soft:
            response = client.delete(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"success": False}
        mock_soft.assert_not_called()


_install_module_stubs = capture_module_stubs(_modules_before_stubs)


@pytest.fixture(autouse=True)
def _isolated_imports(monkeypatch):
    _install_module_stubs(monkeypatch)
