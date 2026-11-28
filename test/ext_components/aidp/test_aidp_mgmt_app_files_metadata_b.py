# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP file summary and chunk metadata tests (split from the management suite)."""

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



class TestChunkMetadataBatchEndpoints:
    """Batch metadata edit and auto-tagging proxies added with the chunk contract."""

    @staticmethod
    def _perms():
        from ext_components.aidp.services import aidp_permission_service

        return aidp_permission_service

    def test_batch_metadata_rejects_empty_metadata_json(self):
        with patch.object(self._perms(), "require_permission",
                          return_value=MagicMock(permission="EDIT")):
            response = _client().patch(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/batch-metadata",
                headers=_bearer(),
                json={"od_id": 1, "metadata_json": {}, "chunk_id_list": [1]},
            )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_batch_metadata_requires_exactly_one_scope_list(self):
        with patch.object(self._perms(), "require_permission",
                          return_value=MagicMock(permission="EDIT")):
            both = _client().patch(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/batch-metadata",
                headers=_bearer(),
                json={
                    "od_id": 1,
                    "metadata_json": {"部门": "研发"},
                    "chunk_id_list": [1],
                    "file_uuid_list": ["a" * 32],
                },
            )
            neither = _client().patch(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/batch-metadata",
                headers=_bearer(),
                json={"od_id": 1, "metadata_json": {"部门": "研发"}},
            )
        assert both.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert neither.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_batch_metadata_rejects_more_than_300_ids_on_sync(self):
        with patch.object(self._perms(), "require_permission",
                          return_value=MagicMock(permission="EDIT")):
            response = _client().patch(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/batch-metadata",
                headers=_bearer(),
                json={
                    "od_id": 1,
                    "metadata_json": {"部门": "研发"},
                    "chunk_id_list": list(range(1, 302)),
                },
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST, response.json()

    def test_batch_metadata_forwards_sync_payload(self):
        from ext_components.aidp.apps import aidp_chunk_routes

        result = {
            "kds_id": 1,
            "od_id": 2,
            "total_chunks": 3,
            "updated_chunks": 3,
            "partial_failure": False,
        }
        with patch.object(self._perms(), "require_permission",
                          return_value=MagicMock(permission="EDIT")) as mock_perm, \
             patch.object(aidp_chunk_routes, "update_chunk_metadata_impl",
                          return_value=result) as edit_metadata:
            response = _client().patch(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/batch-metadata",
                headers=_bearer(),
                json={
                    "od_id": 2,
                    "metadata_json": {"部门": "研发"},
                    "tag": ["示例实体"],
                    "chunk_id_list": [1, 2, 3],
                },
            )
        assert response.status_code == HTTPStatus.OK
        mock_perm.assert_called_once()
        assert mock_perm.call_args.kwargs["required"] == "EDIT"
        assert edit_metadata.call_args.kwargs["od_id"] == 2
        assert edit_metadata.call_args.kwargs["metadata_json"] == {"部门": "研发"}
        assert edit_metadata.call_args.kwargs["tag"] == ["示例实体"]
        assert edit_metadata.call_args.kwargs["chunk_id_list"] == [1, 2, 3]
        assert response.json() == result

    def test_batch_metadata_accepts_null_deletion(self):
        from ext_components.aidp.apps import aidp_chunk_routes

        result = {
            "kds_id": 1,
            "od_id": 2,
            "total_chunks": 1,
            "updated_chunks": 1,
            "partial_failure": False,
        }
        with patch.object(self._perms(), "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_chunk_routes, "update_chunk_metadata_impl",
                          return_value=result) as edit_metadata:
            response = _client().patch(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/batch-metadata",
                headers=_bearer(),
                json={
                    "od_id": 2,
                    "metadata_json": {"部门": None},
                    "chunk_id_list": [1],
                },
            )
        assert response.status_code == HTTPStatus.OK
        assert edit_metadata.call_args.kwargs["metadata_json"] == {"部门": None}
        assert response.json() == result

    def test_batch_metadata_accepts_tag_only(self):
        from ext_components.aidp.apps import aidp_chunk_routes

        result = {
            "kds_id": 1,
            "od_id": 2,
            "total_chunks": 1,
            "updated_chunks": 1,
            "partial_failure": False,
        }
        with patch.object(self._perms(), "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_chunk_routes, "update_chunk_metadata_impl",
                          return_value=result) as edit_metadata:
            response = _client().patch(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/batch-metadata",
                headers=_bearer(),
                json={"od_id": 2, "tag": [], "chunk_id_list": [1]},
            )
        assert response.status_code == HTTPStatus.OK
        assert edit_metadata.call_args.kwargs["metadata_json"] is None
        assert edit_metadata.call_args.kwargs["tag"] == []
        assert response.json() == result

    def test_batch_metadata_rejects_missing_payload(self):
        with patch.object(self._perms(), "require_permission",
                          return_value=MagicMock(permission="EDIT")):
            response = _client().patch(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/batch-metadata",
                headers=_bearer(),
                json={"od_id": 1, "chunk_id_list": [1]},
            )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_batch_metadata_async_accepts_large_chunk_list(self):
        from ext_components.aidp.apps import aidp_chunk_routes

        result = {"task_id": 9, "task_type": "metadata_edit", "status": "pending"}
        with patch.object(self._perms(), "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_chunk_routes, "update_chunk_metadata_impl",
                          return_value=result) as edit_metadata:
            response = _client().patch(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/batch-metadata-async",
                headers=_bearer(),
                json={
                    "od_id": 2,
                    "metadata_json": {"部门": "研发"},
                    "chunk_id_list": list(range(1, 302)),
                },
            )
        assert response.status_code == HTTPStatus.OK
        assert edit_metadata.call_args.kwargs["async_mode"] is True
        assert response.json() == result


class TestOntologyChunkMetadataEndpoints:
    """Ontology-domain chunk metadata export/import/unbind/tag-sync proxies."""

    def _manager(self, user_role="SUPER_ADMIN"):
        return (
            patch(
                "ext_components.aidp.apps.aidp_ontology_validation.get_user_role_by_tenant",
                return_value={user_role},
            ),
            patch(
                "ext_components.aidp.apps.aidp_ontology_validation.has_any_role",
                return_value=True,
            ),
        )

    def test_export_forwards_kds_and_chunk(self):
        from ext_components.aidp.apps import aidp_ontology_metadata_routes

        result = {"od_id": 1, "kds_id": 2, "chunk_id": 3, "metadata_json": {"a": "b"}}
        role_patch, has_patch = self._manager()
        with role_patch, has_patch, \
             patch.object(aidp_ontology_metadata_routes.perms, "require_permission",
                          return_value=MagicMock()), \
             patch.object(aidp_ontology_metadata_routes, "export_chunk_metadata_impl",
                          return_value=result) as export_metadata:
            response = _client().post(
                "/aidp-mgmt/ontology/domains/1/chunks/metadata/export",
                headers=_bearer(),
                json={"kds_id": 2, "chunk_id": 3},
            )
        assert response.status_code == HTTPStatus.OK
        assert export_metadata.call_args.kwargs["kds_id"] == 2
        assert export_metadata.call_args.kwargs["chunk_id"] == 3
        assert response.json() == result

    def test_import_rejects_empty_metadata_json(self):
        role_patch, has_patch = self._manager()
        with role_patch, has_patch:
            response = _client().post(
                "/aidp-mgmt/ontology/domains/1/chunks/metadata/import",
                headers=_bearer(),
                json={"kds_id": 2, "metadata_json": {}, "chunk_id_list": [1]},
            )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_import_forwards_payload(self):
        from ext_components.aidp.apps import aidp_ontology_metadata_routes

        result = {
            "kds_id": 2,
            "domain_id": 1,
            "total_chunks": 2,
            "updated_chunks": 1,
            "partial_failure": True,
            "chunk_results": [
                {"chunk_id": 1, "success": True},
                {"chunk_id": 2, "success": False, "error_message": "x"},
            ],
        }
        role_patch, has_patch = self._manager()
        with role_patch, has_patch, \
             patch.object(aidp_ontology_metadata_routes.perms, "require_permission",
                          return_value=MagicMock()), \
             patch.object(aidp_ontology_metadata_routes, "import_chunk_metadata_impl",
                          return_value=result) as import_metadata:
            response = _client().post(
                "/aidp-mgmt/ontology/domains/1/chunks/metadata/import",
                headers=_bearer(),
                json={
                    "kds_id": 2,
                    "metadata_json": {"部门": "研发"},
                    "chunk_id_list": [1, 2],
                },
            )
        assert response.status_code == HTTPStatus.OK
        assert import_metadata.call_args.kwargs["chunk_id_list"] == [1, 2]
        assert response.json() == result

    def test_batch_unbind_sync_forwards_ids(self):
        from ext_components.aidp.apps import aidp_ontology_metadata_routes

        result = {
            "od_id": 1,
            "total_unbind": 2,
            "succeeded_unbind": 2,
            "failed_unbind": 0,
            "cleared_rows": 10,
            "partial_failure": False,
        }
        role_patch, has_patch = self._manager()
        with role_patch, has_patch, \
             patch.object(aidp_ontology_metadata_routes, "batch_unbind_metadata_sync_impl",
                          return_value=result) as unbind_metadata:
            response = _client().post(
                "/aidp-mgmt/ontology/domains/1/metadata/batch-unbind-sync",
                headers=_bearer(),
                json={"metadata_id_list": [1, 2]},
            )
        assert response.status_code == HTTPStatus.OK
        assert unbind_metadata.call_args.kwargs["metadata_ids"] == [1, 2]
        assert response.json() == result

    def test_ontology_tag_sync_forwards_kb_ids(self):
        from ext_components.aidp.apps import aidp_ontology_metadata_routes

        result = {"task_id": 42, "task_type": "ontology_auto_extract"}
        role_patch, has_patch = self._manager()
        with role_patch, has_patch, \
             patch.object(aidp_ontology_metadata_routes.perms, "require_permission",
                          return_value=MagicMock()), \
             patch.object(aidp_ontology_metadata_routes, "sync_ontology_tags_impl",
                          return_value=result) as sync_tags:
            response = _client().post(
                "/aidp-mgmt/ontology/tags/sync",
                headers=_bearer(),
                json={"kb_ids": [7, 8]},
            )
        assert response.status_code == HTTPStatus.OK
        assert sync_tags.call_args.kwargs["kb_ids"] == [7, 8]
        assert response.json() == result

    def test_ontology_chunk_metadata_rejects_non_manager(self):
        role_patch, _ = self._manager(user_role="USER")
        with role_patch, patch(
            "ext_components.aidp.apps.aidp_ontology_validation.has_any_role",
            return_value=False,
        ):
            response = _client().post(
                "/aidp-mgmt/ontology/domains/1/chunks/metadata/export",
                headers=_bearer(),
                json={"kds_id": 2, "chunk_id": 3},
            )
        assert response.status_code == HTTPStatus.FORBIDDEN
