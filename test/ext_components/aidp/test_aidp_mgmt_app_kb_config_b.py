# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP management route tests (split by feature from the original suite)."""

from test.ext_components.aidp.test_aidp_mgmt_app import *  # noqa: F401,F403
from test.ext_components.aidp.test_aidp_mgmt_app import (  # noqa: F401
    _bearer,
    _build_app,
    _client,
    _isolated_imports,
    configure_aidp_constants,
)

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException

import pytest

pytestmark = pytest.mark.usefixtures("configure_aidp_constants")


class TestCreateKnowledgeBaseEdgeCases:
    def test_user_create_normalizes_shared_permission_to_private(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_create_with_aidp_group_validation_error(self):
        from ext_components.aidp.services import aidp_permission_service
        """_validate_group_ids_strict raises AidpGroupValidationError -> 400. Covers line 307-311."""
        client = _client()
        from ext_components.aidp.consts.aidp_exceptions import AidpGroupValidationError

        with patch.object(aidp_mgmt_app, "create_aidp_kb_impl",
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
        from ext_components.aidp.services import aidp_permission_service
        """PRIVATE permission: group validation skipped, valid_group_ids=[] (line 313)."""
        client = _client()

        with patch.object(aidp_mgmt_app, "create_aidp_kb_impl",
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
        from ext_components.aidp.services import aidp_permission_service
        """AppException from create_aidp_kb_impl is re-raised directly (line 323)."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "create_aidp_kb_impl",
                    side_effect=aidp_mgmt_app.AppException(aidp_mgmt_app.ErrorCode.AIDP_AUTH_ERROR, "unauthorized")), \
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
        from ext_components.aidp.services import aidp_permission_service
        """IntegrityError during create_permission -> _raise_aidp_conflict -> 409 (line 363)."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from sqlalchemy.exc import IntegrityError

        with patch.object(aidp_mgmt_app, "create_aidp_kb_impl",
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
        from ext_components.aidp.services import aidp_permission_service
        """Generic exception from create_aidp_kb_impl -> AppException with AIDP_SERVICE_ERROR (502)."""
        client = _client()

        with patch.object(aidp_mgmt_app, "create_aidp_kb_impl",
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
        from ext_components.aidp.services import aidp_permission_service
        """AIDP returns response without kds_id -> AppException AIDP_SERVICE_ERROR (502)."""
        client = _client()

        with patch.object(aidp_mgmt_app, "create_aidp_kb_impl",
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
        from ext_components.aidp.services import aidp_permission_service
        """DB fails -> AIDP rollback succeeds -> 500 returned (HTTPException from handler)."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        delete_mock = MagicMock(return_value=True)
        with patch.object(aidp_mgmt_app, "create_aidp_kb_impl",
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
        from ext_components.aidp.services import aidp_permission_service
        """DB fails -> AIDP rollback also fails -> ORPHANED status + 500."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "create_aidp_kb_impl",
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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "get_aidp_kb_impl",
                          side_effect=aidp_mgmt_app.AppException(ErrorCode.AIDP_SERVICE_ERROR, "down")), \
             patch.object(aidp_mgmt_app, "count_aidp_docs_impl",
                          side_effect=aidp_mgmt_app.AppException(ErrorCode.AIDP_SERVICE_ERROR, "count down")), \
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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")):
            response = client.patch(
                "/aidp-mgmt/aidp-permissions/kb-1",
                headers=_bearer(),
                json={"ingroup_permission": "INVALID_VAL", "group_ids": [1]},
            )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_set_permission_group_validation_error(self):
        from ext_components.aidp.services import aidp_permission_service
        """_validate_group_ids_strict raises AidpGroupValidationError -> 400."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
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
        from ext_components.aidp.services import aidp_permission_service
        """Helper: POST create and capture create_permission kwargs."""
        client = _client()

        with patch.object(aidp_mgmt_app, "create_aidp_kb_impl",
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
        from ext_components.aidp.services import aidp_permission_service
        """body.name set -> perms.update_permission called with kds_name."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        """body.name not set, aidp result has no kds_name ->
        perms.update_permission NOT called with kds_name."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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


