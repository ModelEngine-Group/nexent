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



class TestChunkImageEndpoint:
    """The ViewImage proxy returns the picture bytes, not a JSON body."""

    FILE_ID = "142515840_4e779b95-bc61-4d2d-bec4-3405717e1836.png"
    PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    def test_view_image_requires_read_and_returns_png(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")) as mock_perm, \
             patch.object(aidp_chunk_routes, "get_aidp_image_impl",
                          return_value=self.PNG_BYTES) as view_image:
            response = client.get(
                f"/aidp-mgmt/knowledge-bases/kb-1/images/{self.FILE_ID}",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert response.headers["Content-Type"] == "image/png"
        assert response.content == self.PNG_BYTES
        mock_perm.assert_called_once()
        assert mock_perm.call_args.kwargs["required"] == "READ"
        view_image.assert_called_once_with(
            SERVER_URL, API_KEY, "kb-1", self.FILE_ID
        )

    def test_view_image_rejects_malformed_file_id(self):
        client = _client()
        response = client.get(
            "/aidp-mgmt/knowledge-bases/kb-1/images/not%20a%20file.png",
            headers=_bearer(),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_view_image_missing_file_id_suffix_rejected(self):
        client = _client()
        response = client.get(
            "/aidp-mgmt/knowledge-bases/kb-1/images/142515840_4e779b95-bc61-4d2d-bec4-3405717e1836",
            headers=_bearer(),
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


class TestFileSummaryEndpoints:
    """Summary config on KB creation and the file summary/retry proxies."""

    FILE_UUID = "fdde6c86-39b2-4ed5-9490-45a22d3931bc"

    def _create_kb(self, payload: dict):
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        body = {
            "name": "摘要知识库",
            "description": "summary",
            "embedding_model": "bge-m3",
            "ingroup_permission": "PRIVATE",
            **payload,
        }
        with patch.object(aidp_mgmt_app, "create_aidp_kb_impl",
                          return_value={"kds_id": "kb-summary"}) as create_kb, \
             patch.object(aidp_permission_service.aidp_permission_db,
                          "get_permission_by_kb_id", return_value=None), \
             patch.object(aidp_permission_service, "create_permission", return_value=1), \
             patch.object(aidp_permission_service, "update_resource_status", return_value=True):
            response = _client().post(
                "/aidp-mgmt/knowledge-bases", headers=_bearer(), json=body
            )
        return response, create_kb

    def test_create_requires_model_when_summary_enabled(self):
        response, create_kb = self._create_kb({"summary_enable": True})
        assert response.status_code == 422
        create_kb.assert_not_called()

    def test_create_forces_preview_and_trims_summary_model(self):
        response, create_kb = self._create_kb({
            "summary_enable": True,
            "summary_model": "  qwen3  ",
            "summary_preview": False,
        })
        assert response.status_code == HTTPStatus.OK
        payload = create_kb.call_args.args[2]
        assert payload["summary_enable"] is True
        assert payload["summary_preview"] is True
        assert payload["summary_model"] == "qwen3"

    def test_create_sends_explicit_false_summary_fields_when_disabled(self):
        response, create_kb = self._create_kb({
            "summary_enable": False,
            "summary_model": "qwen3",
        })
        assert response.status_code == HTTPStatus.OK
        payload = create_kb.call_args.args[2]
        assert payload["summary_enable"] is False
        assert payload["summary_preview"] is False
        assert "summary_model" not in payload

    def test_detail_normalizes_summary_fields_and_old_kbs(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        old = aidp_mgmt_app._normalize_kb_config_fields({})
        assert old["summary_enable"] is False
        assert old["summary_model"] == ""
        assert old["summary_preview"] is False

        enabled = aidp_mgmt_app._normalize_kb_config_fields({
            "kms_config_str": json.dumps({
                "summary_enable": "true",
                "summary_model": "qwen3",
                "summary_preview": "false",
            }),
        })
        assert enabled["summary_enable"] is True
        assert enabled["summary_model"] == "qwen3"
        assert enabled["summary_preview"] is False

    def test_summary_read_requires_read_and_forwards_file(self):
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        payload = {"result": {"summary_status": "pending"}}
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")) as mock_perm, \
             patch.object(aidp_summary_routes, "get_aidp_file_summary_impl",
                          return_value=payload) as get_summary:
            response = _client().get(
                f"/aidp-mgmt/knowledge-bases/kb-1/documents/{self.FILE_UUID}/summary",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == payload
        assert mock_perm.call_args.kwargs["required"] == "READ"
        get_summary.assert_called_once_with(
            SERVER_URL, API_KEY, "kb-1", self.FILE_UUID
        )

    def test_summary_read_denied_does_not_call_aidp(self):
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          side_effect=aidp_mgmt_app.HTTPException(
                              status_code=HTTPStatus.FORBIDDEN, detail="denied")), \
             patch.object(aidp_summary_routes, "get_aidp_file_summary_impl") as get_summary:
            response = _client().get(
                f"/aidp-mgmt/knowledge-bases/kb-1/documents/{self.FILE_UUID}/summary",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.FORBIDDEN
        get_summary.assert_not_called()

    def test_summary_edit_via_permission_save_forwards_three_fields(self):
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        result = {"success": True, "permissions_saved": True, "metadata_status": "updated"}
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "save_kb_settings",
                          return_value=result) as save_settings:
            response = _client().patch(
                "/aidp-mgmt/aidp-permissions/kb-1",
                headers=_bearer(),
                json={
                    "ingroup_permission": "PRIVATE",
                    "group_ids": [],
                    "summary_enable": True,
                    "summary_model": "  qwen3  ",
                    "summary_preview": False,
                },
            )

        assert response.status_code == HTTPStatus.OK
        metadata = save_settings.call_args.kwargs["metadata"]
        assert metadata == {
            "summary_enable": True,
            "summary_model": "qwen3",
            "summary_preview": True,
        }

    def test_summary_edit_requires_model_when_enabled(self):
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "save_kb_settings") as save_settings:
            response = _client().patch(
                "/aidp-mgmt/aidp-permissions/kb-1",
                headers=_bearer(),
                json={"ingroup_permission": "PRIVATE", "summary_enable": True},
            )

        assert response.status_code == 422
        save_settings.assert_not_called()

    def test_summary_edit_rejects_summary_fields_without_switch(self):
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "save_kb_settings") as save_settings:
            response = _client().patch(
                "/aidp-mgmt/aidp-permissions/kb-1",
                headers=_bearer(),
                json={"ingroup_permission": "PRIVATE", "summary_model": "qwen3"},
            )

        assert response.status_code == 422
        save_settings.assert_not_called()

    def test_summary_edit_disable_sends_explicit_false(self):
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "save_kb_settings",
                          return_value={"success": True, "permissions_saved": True,
                                        "metadata_status": "updated"}) as save_settings:
            response = _client().patch(
                "/aidp-mgmt/aidp-permissions/kb-1",
                headers=_bearer(),
                json={"ingroup_permission": "PRIVATE", "summary_enable": False,
                      "summary_model": "qwen3"},
            )

        assert response.status_code == HTTPStatus.OK
        metadata = save_settings.call_args.kwargs["metadata"]
        assert metadata["summary_enable"] is False
        assert metadata["summary_preview"] is False
        assert "summary_model" not in metadata

    def test_summary_edit_via_kb_patch_uses_same_fields(self):
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"summary_enable": True}) as update_kb, \
             patch.object(aidp_permission_service, "update_permission"):
            response = _client().put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"summary_enable": True, "summary_model": "qwen3"},
            )

        assert response.status_code == HTTPStatus.OK
        payload = update_kb.call_args.args[3]
        assert payload["summary_enable"] is True
        assert payload["summary_model"] == "qwen3"
        assert payload["summary_preview"] is True

    def test_summary_edit_via_kb_patch_requires_model(self):
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl") as update_kb:
            response = _client().put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"summary_enable": True},
            )

        assert response.status_code == 422
        update_kb.assert_not_called()


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

    def test_sync_tags_uses_the_path_kb_id(self):
        from ext_components.aidp.apps import aidp_chunk_routes

        with patch.object(self._perms(), "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_chunk_routes, "sync_chunk_tags_impl",
                          return_value={"task_id": 10086}) as sync_tags:
            response = _client().post(
                "/aidp-mgmt/knowledge-bases/7/tags/sync",
                headers=_bearer(),
            )
        assert response.status_code == HTTPStatus.OK
        assert sync_tags.call_args.args[2] == [7]
        assert response.json() == {"task_id": 10086}


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
