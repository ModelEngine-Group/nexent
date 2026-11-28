# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP chunk, sensitive-word and file route tests (split from the management suite)."""

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



class TestSensitiveWordRoutes:
    """BE-SW-002/003: per-KB proxy shape, permissions and upstream errors."""

    def _permission(self, permission="EDIT"):
        from ext_components.aidp.services import aidp_permission_service

        return patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission=permission),
        )

    def test_list_forwards_the_kb_and_filters(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        result = {
            "value": [{"id": "1", "word": "暴力", "mode": "BLACK"}],
            "next_link": None,
            "total_count": 1,
        }
        with self._permission("READ_ONLY") as mock_permission, \
             patch.object(aidp_sensitive_word_routes, "list_sensitive_words_impl",
                          return_value=result) as mock_list:
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/sensitive-words",
                headers=_bearer(),
                params={"page": 2, "page_size": 20, "keyword": " 暴力 ", "mode": "BLACK"},
            )
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert "can_manage" not in body
        assert body["total_count"] == 1
        assert body["next_link"] is None
        mock_permission.assert_called_once_with(
            "kb-1", USER_ID, TENANT_ID, required="READ"
        )
        mock_list.assert_called_once_with(
            SERVER_URL, API_KEY, "kb-1", 2, 20, " 暴力 ", "BLACK"
        )

    def test_list_denial_does_not_call_aidp(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(
            aidp_permission_service,
            "require_permission",
            side_effect=aidp_mgmt_app.HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail="denied"
            ),
        ), patch.object(aidp_sensitive_word_routes, "list_sensitive_words_impl") as mock_list:
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/sensitive-words",
                headers=_bearer(),
            )
        assert response.status_code == HTTPStatus.FORBIDDEN
        mock_list.assert_not_called()

    def test_create_requires_edit_on_the_knowledge_base(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(
            aidp_permission_service,
            "require_permission",
            side_effect=aidp_mgmt_app.HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail="denied"
            ),
        ), patch.object(aidp_sensitive_word_routes, "create_sensitive_word_impl") as mock_create:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/sensitive-words",
                headers=_bearer(),
                json={"word": "暴力", "mode": "BLACK", "description": "desc"},
            )
        assert response.status_code == HTTPStatus.FORBIDDEN
        mock_create.assert_not_called()

    def test_create_trims_and_forwards_the_payload(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with self._permission() as mock_permission, \
             patch.object(aidp_sensitive_word_routes, "create_sensitive_word_impl",
                          return_value={"id": "sw-1"}) as mock_create:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/sensitive-words",
                headers=_bearer(),
                json={"word": "  暴力  ", "mode": "BLACK", "description": "  desc  "},
            )
        assert response.status_code == HTTPStatus.CREATED
        assert response.json() == {"id": "sw-1"}
        mock_permission.assert_called_once_with(
            "kb-1", USER_ID, TENANT_ID, required="EDIT"
        )
        mock_create.assert_called_once_with(
            SERVER_URL, API_KEY, "kb-1", "暴力", "BLACK", "desc"
        )

    def test_create_rejects_blank_description(self):
        response = _client().post(
            "/aidp-mgmt/knowledge-bases/kb-1/sensitive-words",
            headers=_bearer(),
            json={"word": "暴力", "mode": "BLACK", "description": "   "},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_update_sends_only_supplied_fields(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with self._permission() as mock_permission, \
             patch.object(aidp_sensitive_word_routes, "update_sensitive_word_impl",
                          return_value={}) as mock_update:
            response = client.patch(
                "/aidp-mgmt/knowledge-bases/kb-1/sensitive-words/sw-1",
                headers=_bearer(),
                json={"mode": "WHITE"},
            )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {}
        mock_permission.assert_called_once_with(
            "kb-1", USER_ID, TENANT_ID, required="EDIT"
        )
        mock_update.assert_called_once_with(
            SERVER_URL, API_KEY, "kb-1", "sw-1", {"mode": "WHITE"}
        )

    def test_update_rejects_an_empty_payload(self):
        response = _client().patch(
            "/aidp-mgmt/knowledge-bases/kb-1/sensitive-words/sw-1",
            headers=_bearer(),
            json={},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.parametrize(
        "upstream_code,message",
        [
            ("1022", "Sensitive word already exists in this knowledge base"),
            ("1004", "Sensitive word not found in this knowledge base"),
            ("1008", "Built-in sensitive words are read-only"),
            ("9999", "unexpected upstream failure"),
        ],
    )
    def test_upstream_business_codes_keep_the_message_and_generic_status(
        self, upstream_code, message
    ):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from contracts.errors.codes import ErrorCode

        with self._permission(), \
             patch.object(aidp_sensitive_word_routes, "create_sensitive_word_impl",
                          side_effect=AidpSensitiveWordError(
                              message,
                              upstream_code=upstream_code,
                              upstream_status=500,
                          )):
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/sensitive-words",
                headers=_bearer(),
                json={"word": "暴力", "mode": "BLACK", "description": "desc"},
            )
        assert response.status_code == HTTPStatus.BAD_GATEWAY
        body = response.json()
        assert body["code"] == ErrorCode.AIDP_SERVICE_ERROR.value
        assert body["message"] == message
        assert body["details"] == {
            "upstream_status": 500,
            "upstream_code": upstream_code,
        }

    def test_delete_returns_an_empty_204(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with self._permission() as mock_permission, \
             patch.object(aidp_sensitive_word_routes, "delete_sensitive_word_impl",
                          return_value=True) as mock_delete:
            response = client.delete(
                "/aidp-mgmt/knowledge-bases/kb-1/sensitive-words/sw-1",
                headers=_bearer(),
            )
        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response.content == b""
        mock_permission.assert_called_once_with(
            "kb-1", USER_ID, TENANT_ID, required="EDIT"
        )
        mock_delete.assert_called_once_with(SERVER_URL, API_KEY, "kb-1", "sw-1")

    def test_sensitive_word_routes_require_authentication(self):
        client = _client()
        base = "/aidp-mgmt/knowledge-bases/kb-1/sensitive-words"
        assert client.get(base).status_code == 401
        assert client.post(
            base,
            json={"word": "w", "mode": "BLACK", "description": "d"},
        ).status_code == 401
        assert client.delete(f"{base}/sw-1").status_code == 401
class TestFolderAndFilePathRoutes:
    """Folder tree/CRUD and file path operations forward the documented contract."""

    @pytest.fixture(autouse=True)
    def _allow_edit(self, monkeypatch):
        from ext_components.aidp.apps import aidp_mgmt_app

        monkeypatch.setattr(
            aidp_mgmt_app.perms,
            "require_permission",
            lambda *a, **kw: MagicMock(permission="EDIT"),
        )

    def test_folder_tree_forwards_path_paging_and_search(self, monkeypatch):
        from ext_components.aidp.apps import aidp_folder_routes

        captured = {}

        def fake_tree(server_url, api_key, kds_id, folder_path, page, page_size,
                      keyword, file_type, file_status, include_files):
            captured.update(
                server_url=server_url,
                kds_id=kds_id,
                folder_path=folder_path,
                page=page,
                page_size=page_size,
                keyword=keyword,
                file_type=file_type,
                file_status=file_status,
                include_files=include_files,
            )
            return {
                "folder_path": folder_path,
                "folders": [{"folder_name": "子目录", "folder_id": 7, "has_child_folders": False}],
                "files": {
                    "page": page,
                    "page_size": page_size,
                    "total": 1,
                    "value": [{"file_uuid": "u-1", "file_name": "a.pdf"}],
                },
            }

        monkeypatch.setattr(aidp_folder_routes, "get_aidp_folder_tree_impl", fake_tree)
        response = _client().get(
            "/aidp-mgmt/knowledge-bases/kb-1/folders/tree",
            params={
                "folder_path": "/docs/",
                "page": 2,
                "page_size": 20,
                "keyword": "制度",
                "file_type": "pdf",
                "file_status": "1",
            },
            headers=_bearer(),
        )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["folder_path"] == "/docs"
        assert body["folders"] == [{"folder_name": "子目录", "folder_id": 7, "has_child_folders": False}]
        assert body["files"]["total"] == 1
        assert captured == {
            "server_url": SERVER_URL,
            "kds_id": "kb-1",
            "folder_path": "/docs",
            "page": 2,
            "page_size": 20,
            "keyword": "制度",
            "file_type": "pdf",
            "file_status": "1",
            "include_files": True,
        }

    def test_folder_crud_routes_forward_the_path_contract(self, monkeypatch):
        from ext_components.aidp.apps import aidp_folder_routes

        calls = []

        def record(name):
            def inner(*args):
                calls.append((name, *args))
                return {"folder_path": "/docs/new"}

            return inner

        monkeypatch.setattr(
            aidp_folder_routes, "create_aidp_folder_impl", record("create")
        )
        monkeypatch.setattr(
            aidp_folder_routes, "rename_aidp_folder_impl", record("rename")
        )
        monkeypatch.setattr(
            aidp_folder_routes, "move_aidp_folder_impl", record("move")
        )
        monkeypatch.setattr(
            aidp_folder_routes,
            "delete_aidp_folder_impl",
            lambda *args: calls.append(("delete", *args)),
        )
        client = _client()

        created = client.post(
            "/aidp-mgmt/knowledge-bases/kb-1/folders",
            headers=_bearer(),
            json={"parent_folder": "/docs", "folder_name": "new"},
        )
        renamed = client.patch(
            "/aidp-mgmt/knowledge-bases/kb-1/folders",
            headers=_bearer(),
            json={
                "parent_folder": "/docs",
                "old_folder_name": "new",
                "new_folder_name": "renamed",
            },
        )
        moved = client.post(
            "/aidp-mgmt/knowledge-bases/kb-1/folders/move",
            headers=_bearer(),
            json={
                "parent_folder": "/docs",
                "folder_name": "renamed",
                "target_folder": "/archive",
            },
        )
        deleted = client.delete(
            "/aidp-mgmt/knowledge-bases/kb-1/folders",
            headers=_bearer(),
            params={"folder_path": "/docs/renamed"},
        )

        assert created.status_code == HTTPStatus.OK
        assert renamed.status_code == HTTPStatus.OK
        assert moved.status_code == HTTPStatus.OK
        assert deleted.status_code == HTTPStatus.NO_CONTENT
        assert calls == [
            ("create", SERVER_URL, API_KEY, "kb-1", "/docs", "new"),
            ("rename", SERVER_URL, API_KEY, "kb-1", "/docs", "new", "renamed"),
            ("move", SERVER_URL, API_KEY, "kb-1", "/docs", "renamed", "/archive", False),
            ("delete", SERVER_URL, API_KEY, "kb-1", "/docs/renamed"),
        ]

    def test_file_move_and_rename_forward_per_file_objects(self, monkeypatch):
        from ext_components.aidp.apps import aidp_folder_routes

        captured = {}
        monkeypatch.setattr(
            aidp_folder_routes,
            "move_aidp_files_impl",
            lambda *args: captured.setdefault("move", args) or {"summary": {}},
        )
        monkeypatch.setattr(
            aidp_folder_routes,
            "rename_aidp_file_impl",
            lambda *args: captured.setdefault("rename", args)
            or {"file_path": "/docs/b.pdf"},
        )
        client = _client()

        moved = client.post(
            "/aidp-mgmt/knowledge-bases/kb-1/files/move",
            headers=_bearer(),
            json={
                "file_uuids": ["11111111111141118111111111111111"],
                "target_folder": "/docs",
            },
        )
        renamed = client.patch(
            "/aidp-mgmt/knowledge-bases/kb-1/files",
            headers=_bearer(),
            json={
                "file_uuid": "11111111111141118111111111111111",
                "new_file_name": "b.pdf",
            },
        )

        assert moved.status_code == HTTPStatus.OK
        assert renamed.status_code == HTTPStatus.OK
        assert captured["move"] == (
            SERVER_URL,
            API_KEY,
            "kb-1",
            ["11111111111141118111111111111111"],
            "/docs",
        )
        assert captured["rename"] == (
            SERVER_URL,
            API_KEY,
            "kb-1",
            "11111111111141118111111111111111",
            "b.pdf",
        )

    def test_upload_forwards_target_folder_and_relative_paths(self, monkeypatch):
        from ext_components.aidp.apps import aidp_mgmt_app

        captured = {}

        def fake_upload(server_url, api_key, kds_id, files, target_folder, relative_paths):
            captured.update(
                kds_id=kds_id,
                target_folder=target_folder,
                relative_paths=relative_paths,
                names=[file.filename for file in files],
            )
            return {
                "summary": {"total": 2, "success": 2, "failed": 0},
                "success_list": [],
                "failed_list": [],
            }

        monkeypatch.setattr(aidp_mgmt_app, "upload_aidp_docs_impl", fake_upload)
        response = _client().post(
            "/aidp-mgmt/knowledge-bases/kb-1/documents",
            headers=_bearer(),
            data={
                "target_folder": "/docs/",
                "relative_paths": ["合同/2026/a.txt", "b.txt"],
            },
            files=[
                ("files", ("a.txt", b"a", "text/plain")),
                ("files", ("b.txt", b"b", "text/plain")),
            ],
        )

        assert response.status_code == HTTPStatus.OK
        assert captured == {
            "kds_id": "kb-1",
            "target_folder": "/docs",
            "relative_paths": ["合同/2026", ""],
            "names": ["a.txt", "b.txt"],
        }

    def test_folder_path_validation_rejects_traversal(self):
        client = _client()
        tree = client.get(
            "/aidp-mgmt/knowledge-bases/kb-1/folders/tree",
            headers=_bearer(),
            params={"folder_path": "/docs/../secret"},
        )
        create = client.post(
            "/aidp-mgmt/knowledge-bases/kb-1/folders",
            headers=_bearer(),
            json={"parent_folder": "/docs", "folder_name": "../escape"},
        )
        self_move = client.post(
            "/aidp-mgmt/knowledge-bases/kb-1/folders/move",
            headers=_bearer(),
            json={
                "parent_folder": "/docs",
                "folder_name": "a",
                "target_folder": "/docs/a/child",
            },
        )

        assert tree.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert create.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert self_move.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
