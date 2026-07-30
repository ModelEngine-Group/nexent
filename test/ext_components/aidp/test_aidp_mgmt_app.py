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

# Register non-prefixed ``database`` / ``database.client`` stubs so that
# production modules (which import as ``from database.client import ...``)
# resolve to these mocks rather than loading real Minio/Postgres clients.
# Previous ``backend.*``-prefixed keys caused Python to create parallel
# module objects that broke mock patching.
_db_pkg = sys.modules.get("database") or _mod("database")
_db_pkg.__path__ = [os.path.join(BACKEND_DIR, "database")]
_db_client = sys.modules.get("database.client") or _mod("database.client")
_db_client.MinioClient = MagicMock()
_db_client.PostgresClient = MagicMock()
_db_client.as_dict = lambda obj: dict(obj) if isinstance(obj, dict) else {}
_db_client.get_db_session = MagicMock()
for mod in (_db_pkg, _db_client):
    sys.modules.setdefault(mod.__name__, mod)

# Production modules under test
from ext_components.aidp.apps.aidp_mgmt_app import (  # noqa: E402
    aidp_mgmt_router,
)
from apps.app_factory import register_exception_handlers  # noqa: E402

SERVER_URL = "http://aidp.example.com:30081"
API_KEY = "test-aidp-api-key"
USER_ID = "user-test"
TENANT_ID = "tenant-test"


# --- Fixtures -------------------------------------------------------------


@pytest.fixture(autouse=True)
def configure_aidp_constants(monkeypatch):
    """Pin AIDP credentials and auth helper behaviour for every test."""
    from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

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
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

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
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "count_accessible_kbs", return_value=0):
            response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["total_count"] == 0
        assert body["has_more"] is False

    def test_list_marks_kb_unavailable_when_aidp_detail_fails(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

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
            from consts.error_code import ErrorCode as _E  # noqa
            response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["value"][0]["resource_status"] == "UNAVAILABLE"
        mock_status.assert_called_once()


# Use a lazy import for AppException at module load to avoid breaking the
# fastapi exception handler fixture.
from consts.exceptions import AppException  # noqa: E402
from consts.error_code import ErrorCode  # noqa: E402


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
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

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
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

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
        from consts.exceptions import UnauthorizedError

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

    def test_serialize_permission_returns_dict(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        decision = MagicMock()
        decision.permission = "EDIT"
        decision.matched_group_ids = (1, 2)
        decision.is_management_role = True

        result = aidp_mgmt_app._serialize_permission(decision)
        assert result == {
            "permission": "EDIT",
            "matched_group_ids": [1, 2],
            "is_management_role": True,
        }


# ---------------------------------------------------------------------------
# Count endpoint (lines 279-281)
# ---------------------------------------------------------------------------


class TestCountEndpoint:
    def test_count_knowledge_bases_returns_total(self):
        client = _client()
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "count_accessible_kbs", return_value=5):
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

        with patch.object(aidp_permission_service, "count_accessible_kbs", return_value=1), \
             patch.object(aidp_permission_service, "get_accessible_kbs", return_value=[
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
    def test_create_rejects_invalid_ingroup_permission(self):
        client = _client()
        response = client.post(
            "/aidp-mgmt/knowledge-bases",
            headers=_bearer(),
            json={"name": "KB", "ingroup_permission": "INVALID_VALUE", "group_ids": [1]},
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
                json={"name": "KB", "ingroup_permission": "EDIT", "group_ids": [999]},
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
                json={"name": "Private KB", "ingroup_permission": "PRIVATE"},
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
                json={"name": "KB", "ingroup_permission": "READ_ONLY", "group_ids": [1]},
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
                json={"name": "KB", "ingroup_permission": "READ_ONLY", "group_ids": [1]},
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
                json={"name": "KB", "ingroup_permission": "READ_ONLY", "group_ids": [1]},
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
                json={"name": "KB", "ingroup_permission": "READ_ONLY", "group_ids": [1]},
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
                json={"name": "KB", "ingroup_permission": "READ_ONLY", "group_ids": [1]},
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
                json={"name": "KB", "ingroup_permission": "READ_ONLY", "group_ids": [1]},
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
             patch.object(aidp_permission_service, "update_resource_status") as mock_status:
            response = client.get("/aidp-mgmt/knowledge-bases/kb-1", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["resource_status"] == "UNAVAILABLE"
        mock_status.assert_called_once()


# ---------------------------------------------------------------------------
# List documents - count API failure fallback (lines 488-493, 504)
# ---------------------------------------------------------------------------


class TestListDocumentsCountFailure:
    def test_list_docs_falls_back_when_count_api_fails(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "list_aidp_docs_impl",
                          return_value={"value": [{"a": 1}, {"a": 2}]}), \
             patch.object(aidp_mgmt_app, "count_aidp_docs_impl",
                          side_effect=AppException(ErrorCode.AIDP_SERVICE_ERROR, "count failed")):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents",
                headers=_bearer(),
            )
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        # Falls back to page count
        assert body["total_count"] == 2
        assert body["total_reliable"] is False


# ---------------------------------------------------------------------------
# Set permission - edge cases (lines 519, 535)
# ---------------------------------------------------------------------------


class TestSetPermissionEdgeCases:
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
