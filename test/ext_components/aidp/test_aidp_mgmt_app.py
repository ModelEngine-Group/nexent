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
import os
import sys
import types
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

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


class _MinIOStorageConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


nexent_storage_factory.MinIOStorageConfig = _MinIOStorageConfig

for mod in (nexent_pkg, nexent_utils, nexent_http_mgr, nexent_storage,
            nexent_storage_factory):
    sys.modules.setdefault(mod.__name__, mod)

backend_pkg = sys.modules.get("backend") or _mod("backend")
backend_pkg.__path__ = [BACKEND_DIR]
backend_db_pkg = _mod("backend.database")
backend_db_pkg.__path__ = [os.path.join(BACKEND_DIR, "database")]
backend_db_client = _mod("backend.database.client")
backend_db_client.MinioClient = MagicMock()
backend_db_client.PostgresClient = MagicMock()
backend_db_client.as_dict = lambda obj: dict(obj) if isinstance(obj, dict) else {}
backend_db_client.get_db_session = MagicMock()
for mod in (backend_pkg, backend_db_pkg, backend_db_client):
    sys.modules.setdefault(mod.__name__, mod)

# Production modules under test
from backend.ext_components.aidp.apps.aidp_mgmt_app import (  # noqa: E402
    aidp_mgmt_router,
)
from backend.apps.app_factory import register_exception_handlers  # noqa: E402

SERVER_URL = "http://aidp.example.com:30081"
API_KEY = "test-aidp-api-key"
USER_ID = "user-test"
TENANT_ID = "tenant-test"


# --- Fixtures -------------------------------------------------------------


@pytest.fixture(autouse=True)
def configure_aidp_constants(monkeypatch):
    """Pin AIDP credentials and auth helper behaviour for every test."""
    from backend.ext_components.aidp.apps import aidp_mgmt_app

    monkeypatch.setattr(aidp_mgmt_app, "AIDP_SERVER_URL", SERVER_URL)
    monkeypatch.setattr(aidp_mgmt_app, "AIDP_API_KEY", API_KEY)

    # Default: auth succeeds with the standard test user/tenant.
    monkeypatch.setattr(
        aidp_mgmt_app.auth_utils_module, "get_current_user_id",
        lambda *_a, **_kw: (USER_ID, TENANT_ID),
    )
    yield


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(aidp_mgmt_router)
    register_exception_handlers(app)
    return app


def _client():
    return TestClient(_build_app())


def _bearer() -> dict:
    return {"Authorization": "Bearer fake-token"}


# --- Auth (401) -----------------------------------------------------------


class TestAuthRequired:
    def test_missing_auth_returns_401(self):
        app = _build_app()
        client = TestClient(app)
        # Disable the autouse auth patch by replacing get_current_user_id.
        from backend.ext_components.aidp.apps import aidp_mgmt_app

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
        from backend.ext_components.aidp.apps import aidp_mgmt_app
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
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

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
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

        decision = MagicMock()
        decision.permission = "READ_ONLY"
        original_require = aidp_permission_service.require_permission
        aidp_permission_service.require_permission = MagicMock(return_value=decision)

        with patch.object(aidp_mgmt_app, "get_aidp_kb_impl") as mock_get:
            mock_get.return_value = {"kds_name": "name", "description": "desc"}
            try:
                response = client.get(
                    "/aidp-mgmt/knowledge-bases/kb-1", headers=_bearer()
                )
            finally:
                aidp_permission_service.require_permission = original_require
        assert response.status_code == HTTPStatus.OK
        assert response.json()["permission"] == "READ_ONLY"

    def test_update_kb_without_edit_returns_403(self):
        client = _client()
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

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
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

        original_require = aidp_permission_service.require_permission
        aidp_permission_service.require_permission = MagicMock(
            return_value=MagicMock(permission="EDIT")
        )
        try:
            soft_delete = MagicMock(return_value=True)
            with patch.object(aidp_mgmt_app, "delete_aidp_kb_impl", return_value=True), \
                 patch.object(aidp_mgmt_app.perms, "soft_delete_permission", soft_delete):
                response = client.delete(
                    "/aidp-mgmt/knowledge-bases/kb-1", headers=_bearer()
                )
        finally:
            aidp_permission_service.require_permission = original_require
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"success": True}
        soft_delete.assert_called_once()

    def test_set_permission_private_clears_groups(self):
        client = _client()
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

        original_require = aidp_permission_service.require_permission
        aidp_permission_service.require_permission = MagicMock(
            return_value=MagicMock(permission="EDIT")
        )
        try:
            update_perm = MagicMock(return_value=True)
            with patch.object(aidp_mgmt_app.perms, "update_permission", update_perm), \
                 patch.object(aidp_mgmt_app, "_validate_group_ids_strict") as mock_validate:
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
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

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
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

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
            "backend.ext_components.aidp.apps.aidp_mgmt_app.create_aidp_kb_impl",
            return_value=aidp_result,
        )

    def test_create_persists_permission_and_returns_edit(self):
        client = _client()
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

        with self._patch_create(), \
             patch.object(aidp_permission_service.aidp_permission_db, "get_permission_by_kb_id", return_value=None), \
             patch.object(aidp_permission_service, "create_permission", return_value=1) as mock_create, \
             patch.object(aidp_permission_service, "update_resource_status", return_value=True) as mock_status, \
             patch.object(aidp_permission_service, "_validate_group_ids_strict", side_effect=lambda g, t: list(g)):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={
                    "name": "New KB",
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
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

        with self._patch_create(), \
             patch.object(aidp_permission_service, "_validate_group_ids_strict", side_effect=lambda g, t: list(g)), \
             patch.object(aidp_permission_service.aidp_permission_db, "get_permission_by_kb_id", return_value={"id": 1}):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={
                    "name": "New KB",
                    "ingroup_permission": "READ_ONLY",
                    "group_ids": [1],
                },
            )
        assert response.status_code == HTTPStatus.CONFLICT

    def test_create_rolls_back_aidp_when_db_fails(self):
        client = _client()
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

        delete_mock = MagicMock(return_value=True)
        with self._patch_create(), \
             patch.object(aidp_permission_service, "_validate_group_ids_strict", side_effect=lambda g, t: list(g)), \
             patch.object(aidp_permission_service.aidp_permission_db, "get_permission_by_kb_id", return_value=None), \
             patch.object(aidp_permission_service, "create_permission", side_effect=RuntimeError("db down")), \
             patch.object(aidp_mgmt_app, "delete_aidp_kb_impl", delete_mock):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={
                    "name": "New KB",
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
            json={"name": "New KB", "ingroup_permission": "EDIT"},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST


# --- List KBs -------------------------------------------------------------


class TestListKnowledgeBases:
    def test_list_returns_empty_when_no_rows(self):
        client = _client()
        from backend.ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "count_accessible_kbs", return_value=0):
            response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["total_count"] == 0
        assert body["has_more"] is False

    def test_list_marks_kb_unavailable_when_aidp_detail_fails(self):
        client = _client()
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "count_accessible_kbs", return_value=1), \
             patch.object(aidp_permission_service, "get_accessible_kbs", return_value=[
                 {
                     "kb_id": "kb-1", "owner_user_id": USER_ID, "tenant_id": TENANT_ID,
                     "ingroup_permission": "EDIT", "group_ids": [],
                     "resource_status": "ACTIVE", "permission": "EDIT",
                 }
             ]), \
             patch.object(aidp_mgmt_app, "get_aidp_kb_impl",
                          side_effect=AppException(ErrorCode.AIDP_SERVICE_ERROR, "down")), \
             patch.object(aidp_permission_service, "update_resource_status") as mock_status:
            from backend.consts.error_code import ErrorCode as _E  # noqa
            response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["value"][0]["resource_status"] == "UNAVAILABLE"
        mock_status.assert_called_once()


# Use a lazy import for AppException at module load to avoid breaking the
# fastapi exception handler fixture.
from backend.consts.exceptions import AppException  # noqa: E402
from backend.consts.error_code import ErrorCode  # noqa: E402


# --- Update KB ------------------------------------------------------------


class TestUpdateKnowledgeBase:
    def test_update_rejects_empty_payload(self):
        client = _client()
        from backend.ext_components.aidp.services import aidp_permission_service

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
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
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


# --- Upload documents ----------------------------------------------------


class TestUploadDocuments:
    def test_upload_calls_aidp_with_files(self):
        client = _client()
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

        files = [
            ("files", ("doc.txt", io.BytesIO(b"hello"), "text/plain")),
        ]
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "upload_aidp_docs_impl", return_value={"uploaded": 1}) as mock_upload:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents",
                headers=_bearer(),
                files=files,
            )
        assert response.status_code == HTTPStatus.OK
        mock_upload.assert_called_once()


# --- List documents ------------------------------------------------------


class TestListDocuments:
    def test_list_documents_uses_count_api(self):
        client = _client()
        from backend.ext_components.aidp.apps import aidp_mgmt_app
        from backend.ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "list_aidp_docs_impl",
                          return_value={"value": [{"name": "a"}]}), \
             patch.object(aidp_mgmt_app, "count_aidp_docs_impl", return_value=42):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents",
                headers=_bearer(),
            )
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["total_count"] == 42
        assert body["has_more"] is True


# --- Models list (auth only, no per-KB permission) ------------------------


class TestListModels:
    def test_list_models_returns_aidp_response(self):
        client = _client()
        from backend.ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "list_aidp_models_impl",
                          return_value={"models": []}) as mock_models:
            response = client.get("/aidp-mgmt/models", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        mock_models.assert_called_once()
