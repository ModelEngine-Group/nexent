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



class TestChunkEndpoints:
    """Semantic chunk proxy: READ for reads, EDIT for writes, contract fields only."""

    FILE_UUID = "fdde6c86-39b2-4ed5-9490-45a22d3931bc"

    def test_list_requires_read_and_forwards_file_scoped_paging(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        page = {
            "value": [{"chunk_id": 1, "chunk_text": "正文"}],
            # Real AIDP reports the current page's row count, not a global
            # total, and returns next_link on every page; the proxy derives
            # pagination from the page being full instead of either field.
            "total_count": 1,
            "next_link": "/next",
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")) as mock_perm, \
             patch.object(aidp_chunk_routes, "list_aidp_chunks_impl",
                          return_value=page) as list_chunks:
            response = client.get(
                f"/aidp-mgmt/knowledge-bases/kb-1/chunks?file_uuid={self.FILE_UUID}"
                "&page=2&page_size=20",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        mock_perm.assert_called_once()
        assert mock_perm.call_args.kwargs["required"] == "READ"
        list_chunks.assert_called_once_with(
            SERVER_URL, API_KEY, "kb-1", self.FILE_UUID, 2, 20
        )
        body = response.json()
        assert body["total_count"] == 21  # (page - 1) * page_size + len(rows)
        assert body["has_more"] is False  # a short page is the last page
        assert body["total_reliable"] is False

    def test_search_requires_read_and_forwards_file_name(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        result = {
            "value": [{"chunk_id": 1001, "chunk_text": "检索内容"}],
            "total_count": 1,
            "has_more": False,
            "total_reliable": True,
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")) as mock_perm, \
             patch.object(aidp_chunk_routes, "search_aidp_chunks_impl",
                          return_value=result) as search_chunks:
            response = client.get(
                f"/aidp-mgmt/knowledge-bases/kb-1/chunks/search"
                f"?file_uuid={self.FILE_UUID}&file_name=%E6%BC%94%E7%A4%BA.pdf"
                "&query=%E6%A3%80%E7%B4%A2&topk=5",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        mock_perm.assert_called_once()
        assert mock_perm.call_args.kwargs["required"] == "READ"
        search_chunks.assert_called_once_with(
            SERVER_URL, API_KEY, "kb-1", "演示.pdf", "检索", 5
        )
        assert response.json() == result

    def test_list_reports_more_from_total_when_page_is_full(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        rows = [{"chunk_id": index} for index in range(20)]
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_chunk_routes, "list_aidp_chunks_impl",
                          return_value={"value": rows, "total_count": 21}):
            response = client.get(
                f"/aidp-mgmt/knowledge-bases/kb-1/chunks?file_uuid={self.FILE_UUID}"
                "&page=1&page_size=20",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json()["has_more"] is True

    def test_list_derives_count_when_upstream_total_is_missing(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_chunk_routes, "list_aidp_chunks_impl",
                          return_value={"value": [{"chunk_id": 1}, {"chunk_id": 2}]}):
            response = client.get(
                f"/aidp-mgmt/knowledge-bases/kb-1/chunks?file_uuid={self.FILE_UUID}"
                "&page=3&page_size=2",
                headers=_bearer(),
            )

        body = response.json()
        assert body["total_reliable"] is False
        assert body["total_count"] == 6  # (page - 1) * page_size + rows
        assert body["has_more"] is True

    def test_list_rejects_malformed_upstream_payload(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_chunk_routes, "list_aidp_chunks_impl",
                          return_value={"total_count": 1}):
            response = client.get(
                f"/aidp-mgmt/knowledge-bases/kb-1/chunks?file_uuid={self.FILE_UUID}",
                headers=_bearer(),
            )

        assert response.status_code == 502
        assert response.json()["code"] == ErrorCode.AIDP_RESPONSE_ERROR.value

    def test_read_denied_does_not_call_aidp(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          side_effect=aidp_mgmt_app.HTTPException(
                              status_code=HTTPStatus.FORBIDDEN, detail="denied")), \
             patch.object(aidp_chunk_routes, "list_aidp_chunks_impl") as list_chunks:
            response = client.get(
                f"/aidp-mgmt/knowledge-bases/kb-1/chunks?file_uuid={self.FILE_UUID}",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.FORBIDDEN
        list_chunks.assert_not_called()

    def test_detail_requires_read_and_forwards_chunk_id(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        chunk = {"chunk_id": 7, "chunk_text": "完整文本", "page_ids": [1]}
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")) as mock_perm, \
             patch.object(aidp_chunk_routes, "get_aidp_chunk_impl",
                          return_value=chunk) as get_chunk:
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/7",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == chunk
        assert mock_perm.call_args.kwargs["required"] == "READ"
        get_chunk.assert_called_once_with(SERVER_URL, API_KEY, "kb-1", 7)

    def test_create_requires_edit_and_sends_trimmed_contract_fields(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")) as mock_perm, \
             patch.object(aidp_chunk_routes, "create_aidp_chunk_impl",
                          return_value={"chunk_id": "12"}) as create_chunk:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks",
                headers=_bearer(),
                json={"file_uuid": self.FILE_UUID, "chunk_text": "  新切片  "},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"chunk_id": "12"}
        assert mock_perm.call_args.kwargs["required"] == "EDIT"
        create_chunk.assert_called_once_with(
            SERVER_URL, API_KEY, "kb-1", self.FILE_UUID, "新切片"
        )

    @pytest.mark.parametrize("chunk_text", ["", "   ", "\n\t ", "x" * 10241])
    def test_create_rejects_invalid_text_without_calling_aidp(self, chunk_text):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_chunk_routes, "create_aidp_chunk_impl") as create_chunk:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks",
                headers=_bearer(),
                json={"file_uuid": self.FILE_UUID, "chunk_text": chunk_text},
            )

        assert response.status_code == 422
        create_chunk.assert_not_called()

    def test_create_rejects_extra_fields_without_calling_aidp(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_chunk_routes, "create_aidp_chunk_impl") as create_chunk:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks",
                headers=_bearer(),
                json={
                    "file_uuid": self.FILE_UUID,
                    "chunk_text": "文本",
                    "metadata": {"k": "v"},
                },
            )

        assert response.status_code == 422
        create_chunk.assert_not_called()

    def test_update_sends_only_chunk_text(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        updated = {
            "chunk_id": 5,
            "chunk_text": "改后文本",
            "chunk_type": "TEXT",
            "page_ids": [1],
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")) as mock_perm, \
             patch.object(aidp_chunk_routes, "get_aidp_chunk_impl",
                          return_value={"chunk_id": 5, "chunk_type": "TEXT"}) as get_chunk, \
             patch.object(aidp_chunk_routes, "update_aidp_chunk_impl",
                          return_value=updated) as update_chunk:
            response = client.patch(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/5",
                headers=_bearer(),
                json={"chunk_text": " 改后文本 "},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == updated
        assert mock_perm.call_args.kwargs["required"] == "EDIT"
        get_chunk.assert_called_once_with(SERVER_URL, API_KEY, "kb-1", 5)
        update_chunk.assert_called_once_with(
            SERVER_URL, API_KEY, "kb-1", 5, "改后文本"
        )

    @pytest.mark.parametrize("chunk_type", ["IMAGE", "image", "", None])
    def test_update_rejects_non_editable_chunk_without_patching(self, chunk_type):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        current = {"chunk_id": 5}
        if chunk_type is not None:
            current["chunk_type"] = chunk_type
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_chunk_routes, "get_aidp_chunk_impl",
                          return_value=current), \
             patch.object(aidp_chunk_routes, "update_aidp_chunk_impl") as update_chunk:
            response = client.patch(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/5",
                headers=_bearer(),
                json={"chunk_text": "文本"},
            )

        assert response.status_code == 400
        assert response.json()["message"] == "Only TEXT and TABLE chunks can be edited"
        update_chunk.assert_not_called()

    @pytest.mark.parametrize("chunk_type", ["TEXT", "text", " Text ", "TABLE", "table"])
    def test_update_accepts_editable_chunk_type_case_insensitively(self, chunk_type):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_chunk_routes, "get_aidp_chunk_impl",
                          return_value={"chunk_id": 5, "chunk_type": chunk_type}), \
             patch.object(aidp_chunk_routes, "update_aidp_chunk_impl",
                          return_value={"chunk_id": 5, "chunk_type": "TEXT"}) as update_chunk:
            response = client.patch(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/5",
                headers=_bearer(),
                json={"chunk_text": "文本"},
            )

        assert response.status_code == HTTPStatus.OK
        update_chunk.assert_called_once()

    @pytest.mark.parametrize("chunk_text", ["", "   ", "x" * 10241])
    def test_update_rejects_invalid_text_without_calling_aidp(self, chunk_text):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_chunk_routes, "update_aidp_chunk_impl") as update_chunk:
            response = client.patch(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks/5",
                headers=_bearer(),
                json={"chunk_text": chunk_text},
            )

        assert response.status_code == 422
        update_chunk.assert_not_called()

    def test_write_denied_does_not_call_aidp(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          side_effect=aidp_mgmt_app.HTTPException(
                              status_code=HTTPStatus.FORBIDDEN, detail="denied")), \
             patch.object(aidp_chunk_routes, "create_aidp_chunk_impl") as create_chunk:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/chunks",
                headers=_bearer(),
                json={"file_uuid": self.FILE_UUID, "chunk_text": "文本"},
            )

        assert response.status_code == HTTPStatus.FORBIDDEN
        create_chunk.assert_not_called()

    def test_remove_forwards_selected_ids(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")) as mock_perm, \
             patch.object(aidp_chunk_routes, "remove_aidp_chunks_impl",
                          return_value={}) as remove_chunks:
            response = client.request(
                "DELETE",
                "/aidp-mgmt/knowledge-bases/kb-1/chunks",
                headers=_bearer(),
                json={"chunk_ids": [3, 1, 2]},
            )

        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response.content == b""
        assert mock_perm.call_args.kwargs["required"] == "EDIT"
        remove_chunks.assert_called_once_with(SERVER_URL, API_KEY, "kb-1", [3, 1, 2])

    @pytest.mark.parametrize("chunk_ids", [[], list(range(2001)), [-1], [True], ["1"]])
    def test_remove_rejects_id_counts_outside_1_to_2000(self, chunk_ids):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_chunk_routes, "remove_aidp_chunks_impl") as remove_chunks:
            response = client.request(
                "DELETE",
                "/aidp-mgmt/knowledge-bases/kb-1/chunks",
                headers=_bearer(),
                json={"chunk_ids": chunk_ids},
            )

        assert response.status_code == 422
        remove_chunks.assert_not_called()

    def test_remove_accepts_the_2000_id_limit(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app
        from ext_components.aidp.services import aidp_permission_service

        chunk_ids = list(range(2000))
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_chunk_routes, "remove_aidp_chunks_impl",
                          return_value={}) as remove_chunks:
            response = client.request(
                "DELETE",
                "/aidp-mgmt/knowledge-bases/kb-1/chunks",
                headers=_bearer(),
                json={"chunk_ids": chunk_ids},
            )

        assert response.status_code == HTTPStatus.NO_CONTENT
        remove_chunks.assert_called_once_with(SERVER_URL, API_KEY, "kb-1", chunk_ids)

    def test_upstream_failure_is_not_reported_as_success(self):
        client = _client()
        from ext_components.aidp.apps import aidp_chunk_routes
        from ext_components.aidp.services import aidp_permission_service

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_chunk_routes, "remove_aidp_chunks_impl",
                          side_effect=aidp_chunk_routes.AppException(
                              aidp_chunk_routes.ErrorCode.AIDP_SERVICE_ERROR, "upstream down")):
            response = client.request(
                "DELETE",
                "/aidp-mgmt/knowledge-bases/kb-1/chunks",
                headers=_bearer(),
                json={"chunk_ids": [1]},
            )

        assert response.status_code == 502
        assert response.json()["code"] == ErrorCode.AIDP_SERVICE_ERROR.value
class TestKnowledgeBaseSensitiveIntercept:
    """BE-SW-001: the KB toggle keeps 0/1 intact across the whole chain."""

    @pytest.mark.parametrize("value", [0, 1])
    def test_create_forwards_the_toggle(self, value):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(
            aidp_mgmt_app, "create_aidp_kb_impl",
            return_value={"kds_id": "kb-new", "name": "kb"},
        ) as mock_create, \
             patch.object(aidp_permission_service.aidp_permission_db, "get_permission_by_kb_id",
                          return_value=None), \
             patch.object(aidp_permission_service, "create_permission", return_value=1), \
             patch.object(aidp_permission_service, "update_resource_status", return_value=True):
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                headers=_bearer(),
                json={
                    "name": "New KB",
                    "description": "A test knowledge base",
                    "embedding_model": "bge-m3",
                    "ingroup_permission": "PRIVATE",
                    "sensitive_intercept_enable": value,
                },
            )
        assert response.status_code == HTTPStatus.OK
        payload = mock_create.call_args.args[2]
        assert payload["sensitive_intercept_enable"] == value

    def test_create_defaults_the_toggle_to_disabled(self):
        from ext_components.aidp.apps.aidp_mgmt_app import CreateKbRequest

        body = CreateKbRequest(
            name="New KB",
            description="A test knowledge base",
            embedding_model="bge-m3",
        )
        assert body.sensitive_intercept_enable == 0

    @pytest.mark.parametrize("value", [0, 1])
    def test_update_forwards_only_the_supplied_toggle(self, value):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"sensitive_intercept_enable": value},
            )
        assert response.status_code == HTTPStatus.OK
        assert mock_update.call_args.args[3] == {
            "sensitive_intercept_enable": value
        }

    @pytest.mark.parametrize(
        "detail,expected",
        [
            ({"kds_name": "kb"}, 0),
            ({"kds_name": "kb", "sensitive_intercept_enable": 1}, 1),
            ({"kds_name": "kb", "sensitive_intercept_enable": 0}, 0),
            ({"kds_name": "kb", "sensitive_intercept_enable": "是"}, 1),
            ({"kds_name": "kb", "kms_config_str": '{"sensitive_intercept_enable": 1}'}, 1),
        ],
    )
    def test_detail_echoes_the_toggle(self, detail, expected):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "get_aidp_kb_impl", return_value=detail), \
             patch.object(aidp_mgmt_app.aidp_permission_db, "get_permission_by_kb_id",
                          return_value=None), \
             patch.object(aidp_mgmt_app, "count_aidp_docs_impl", return_value=0):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1", headers=_bearer()
            )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["sensitive_intercept_enable"] == expected


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
