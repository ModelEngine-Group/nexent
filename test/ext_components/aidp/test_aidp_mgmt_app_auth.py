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


class TestAuthRequired:
    def test_missing_auth_returns_401(self):
        app = _build_app()
        client = TestClient(app)
        # Disable the autouse auth patch by replacing get_current_user_id.
        from ext_components.aidp.apps import aidp_mgmt_app

        def _raise(*_a, **_kw):
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="bad")

        original = aidp_mgmt_common.auth_utils_module.get_current_user_id
        aidp_mgmt_common.auth_utils_module.get_current_user_id = _raise
        try:
            response = client.get("/aidp-mgmt/knowledge-bases")
        finally:
            aidp_mgmt_common.auth_utils_module.get_current_user_id = original
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_missing_auth_for_set_permission_returns_401(self):
        app = _build_app()
        client = TestClient(app)
        from ext_components.aidp.apps import aidp_mgmt_app
        from fastapi import HTTPException

        def _raise(*_a, **_kw):
            raise HTTPException(status_code=401, detail="bad")

        original = aidp_mgmt_common.auth_utils_module.get_current_user_id
        aidp_mgmt_common.auth_utils_module.get_current_user_id = _raise
        try:
            response = client.patch(
                "/aidp-mgmt/aidp-permissions/kb-1",
                json={"ingroup_permission": "READ_ONLY", "group_ids": [1]},
            )
        finally:
            aidp_mgmt_common.auth_utils_module.get_current_user_id = original
        assert response.status_code == HTTPStatus.UNAUTHORIZED


# --- Permission matrix enforcement ---------------------------------------


class TestPermissionEnforcement:
    def test_get_kb_without_access_returns_404(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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


