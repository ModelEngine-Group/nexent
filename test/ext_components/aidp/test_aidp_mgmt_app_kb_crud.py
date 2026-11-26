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

import pytest

pytestmark = pytest.mark.usefixtures("configure_aidp_constants")


class TestCreateKnowledgeBase:
    def _patch_create(self, aidp_result=None):
        if aidp_result is None:
            aidp_result = {"kds_id": "kb-new", "name": "kb"}
        return patch(
            "ext_components.aidp.apps.aidp_mgmt_app.create_aidp_kb_impl",
            return_value=aidp_result,
        )

    def test_create_persists_permission_and_returns_edit(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "_current_accessible_rows", return_value=[
                 {
                     "kb_id": "kb-1", "owner_user_id": USER_ID, "tenant_id": TENANT_ID,
                     "ingroup_permission": "EDIT", "group_ids": [],
                     "resource_status": "ACTIVE", "permission": "EDIT",
                 }
             ]), \
             patch.object(aidp_mgmt_app, "get_aidp_kb_impl",
                          side_effect=aidp_mgmt_app.AppException(ErrorCode.AIDP_SERVICE_ERROR, "down")), \
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
            "bind_lib_id": 0,
            "bind_lib_type": "none",
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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")):
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={},
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_calls_aidp_with_payload(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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


