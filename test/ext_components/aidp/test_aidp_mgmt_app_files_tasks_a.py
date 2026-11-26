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


class TestKnowledgeFilesEndpoint:
    """GET /knowledge-bases/{kds_id}/files - ingested files for the detail page."""

    def test_file_search_skips_count_and_reports_next_page(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "list_aidp_docs_impl",
                          return_value={"unexpected": True}), \
             patch.object(aidp_mgmt_app, "count_aidp_docs_impl", return_value=1):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/files",
                headers=_bearer(),
            )

        assert response.status_code in (HTTPStatus.INTERNAL_SERVER_ERROR, HTTPStatus.BAD_GATEWAY)
        assert response.json()["code"] == ErrorCode.AIDP_RESPONSE_ERROR.value

    def test_unfiltered_file_list_uses_cached_count(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="READ_ONLY")), \
             patch.object(aidp_mgmt_app, "list_aidp_docs_impl",
                          return_value={"value": [{"file_uuid": "f-1"}]}), \
             patch.object(aidp_mgmt_app, "count_aidp_docs_impl",
                          side_effect=aidp_mgmt_app.AppException(ErrorCode.AIDP_SERVICE_ERROR, "count down")):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/files?page=1&page_size=10",
                headers=_bearer(),
            )

        # Count failures propagate; the endpoint does not degrade to a
        # page-local total.
        assert response.status_code in (HTTPStatus.INTERNAL_SERVER_ERROR, HTTPStatus.BAD_GATEWAY)
        assert response.json()["code"] == ErrorCode.AIDP_SERVICE_ERROR.value

    def test_file_list_propagates_upstream_list_failure(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        list_error = aidp_mgmt_app.AppException(ErrorCode.AIDP_CONNECTION_ERROR, "AIDP is unavailable")
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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

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


