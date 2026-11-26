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


class TestUploadDocuments:
    def test_upload_calls_aidp_with_files(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        files = [
            ("files", ("doc.txt", io.BytesIO(b"hello"), "text/plain")),
        ]
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "upload_aidp_docs_impl", return_value={
                 "summary": {"total": 1, "success": 0, "failed": 1},
                 "success_list": [],
                 "failed_list": [{
                     "file_name": "doc.txt",
                     "reason_zh": "文件内容为空",
                     "reason_en": "File content is empty",
                 }],
             }) as mock_upload:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents",
                headers=_bearer(),
                files=files,
            )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["failed_list"][0]["reason_en"] == "File content is empty"
        mock_upload.assert_called_once()

    def test_upload_rejects_more_than_fifty_files_without_calling_aidp(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        files = [
            ("files", (f"doc-{index}.txt", io.BytesIO(b"hello"), "text/plain"))
            for index in range(51)
        ]
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "upload_aidp_docs_impl") as mock_upload:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents",
                headers=_bearer(),
                files=files,
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["summary"] == {"total": 51, "success": 0, "failed": 51}
        assert body["failed_list"][0]["reason_zh"] == "单次最多上传 50 个文件"
        mock_upload.assert_not_called()

    def test_upload_merges_oversized_file_with_aidp_result(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        files = [
            ("files", ("valid.pdf", io.BytesIO(b"ok"), "application/pdf")),
            ("files", ("large.txt", io.BytesIO(b"x"), "text/plain")),
        ]
        aidp_result = {
            "summary": {"total": 1, "success": 1, "failed": 0},
            "success_list": [{"file_name": "valid.pdf"}],
            "failed_list": [],
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "AIDP_SMALL_FILE_MAX_SIZE_BYTES", 0), \
             patch.object(aidp_mgmt_app, "upload_aidp_docs_impl",
                          return_value=aidp_result) as mock_upload:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents",
                headers=_bearer(),
                files=files,
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["summary"] == {"total": 2, "success": 1, "failed": 1}
        assert body["failed_list"][0]["file_name"] == "large.txt"
        assert mock_upload.call_args.args[3][0].filename == "valid.pdf"

    def test_upload_applies_twenty_mb_limit_to_json_md_and_html(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        files = [
            ("files", ("large.json", io.BytesIO(b"xx"), "application/json")),
            ("files", ("large.md", io.BytesIO(b"xx"), "text/markdown")),
            ("files", ("large.html", io.BytesIO(b"xx"), "text/html")),
            ("files", ("valid.pdf", io.BytesIO(b"xx"), "application/pdf")),
        ]
        aidp_result = {
            "summary": {"total": 1, "success": 1, "failed": 0},
            "success_list": [{"file_name": "valid.pdf"}],
            "failed_list": [],
        }
        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="EDIT"),
        ), patch.object(
            aidp_mgmt_app, "AIDP_SMALL_FILE_MAX_SIZE_BYTES", 1
        ), patch.object(
            aidp_mgmt_app, "AIDP_OTHER_FILE_MAX_SIZE_BYTES", 10
        ), patch.object(
            aidp_mgmt_app, "upload_aidp_docs_impl", return_value=aidp_result
        ) as mock_upload:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents",
                headers=_bearer(),
                files=files,
            )

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["summary"] == {"total": 4, "success": 1, "failed": 3}
        assert {item["file_name"] for item in body["failed_list"]} == {
            "large.json",
            "large.md",
            "large.html",
        }
        assert [file.filename for file in mock_upload.call_args.args[3]] == ["valid.pdf"]


# --- Remove/download documents -------------------------------------------


