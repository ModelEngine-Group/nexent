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


class TestAidpDocumentFileOperations:
    def test_remove_forwards_only_uuids(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        aidp_result = {
            "summary": {"total": 2, "success": 1, "failed": 1},
            "success_list": [{"file_uuid": "00000000000040008000000000000001"}],
            "failed_list": [{"file_uuid": "00000000000040008000000000000002"}],
        }
        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="EDIT"),
        ), patch.object(
            aidp_mgmt_app,
            "remove_aidp_docs_impl",
            return_value=aidp_result,
        ) as mock_remove:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/remove",
                headers=_bearer(),
                json={
                    "file_uuids": [
                        "00000000000040008000000000000001",
                        "00000000000040008000000000000002",
                    ]
                },
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == aidp_result
        assert mock_remove.call_args.args[3] == [
            "00000000000040008000000000000001",
            "00000000000040008000000000000002",
        ]

    def test_remove_requires_file_uuids(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "remove_aidp_docs_impl") as mock_remove:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/remove",
                headers=_bearer(),
                json={},
            )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        mock_remove.assert_not_called()

    def test_remove_requires_standard_file_uuid(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "remove_aidp_docs_impl") as mock_remove:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/remove",
                headers=_bearer(),
                json={"file_uuids": ["uuid-1"]},
            )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        mock_remove.assert_not_called()

    def test_download_returns_binary_response(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        mock_response = httpx.Response(
            200,
            headers={
                "Content-Type": "text/plain",
                "Content-Disposition": 'attachment; filename="a.txt"',
                "X-File-Size": "5",
            },
            content=b"hello",
            request=httpx.Request("POST", SERVER_URL),
        )

        async def stream_document(*args):
            return mock_response

        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="READ_ONLY"),
        ), patch.object(
            aidp_mgmt_app,
            "stream_aidp_doc_impl",
            side_effect=stream_document,
        ) as mock_download:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/download",
                headers=_bearer(),
                json={"file_uuid": "00000000000040008000000000000001"},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.content == b"hello"
        assert response.headers["content-type"].startswith("text/plain")
        assert response.headers["content-disposition"] == 'attachment; filename="a.txt"'
        assert response.headers["x-file-size"] == "5"
        assert mock_download.call_args.args == (
            SERVER_URL,
            API_KEY,
            "kb-1",
            "00000000000040008000000000000001",
        )
        assert "x-file-name" not in response.headers

    def test_preview_streams_original_document_inline(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        docx_mime = (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        )
        mock_response = httpx.Response(
            200,
            headers={
                "Content-Type": docx_mime,
                # AIDP reports the name it served in this header; for a format
                # it did not convert, it is the uploaded one.
                "X-File-Name": "report.docx",
                "Content-Disposition": 'attachment; filename="report.docx"',
                "X-File-Size": "11",
            },
            content=b"docx-bytes!",
            request=httpx.Request("GET", SERVER_URL),
        )

        async def stream_document(*args):
            return mock_response

        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="READ_ONLY"),
        ), patch.object(
            aidp_mgmt_app,
            "stream_aidp_preview_impl",
            side_effect=stream_document,
        ) as mock_stream:
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/"
                "00000000000040008000000000000001/preview",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        # The original bytes and content type reach the browser untouched: the
        # frontend renders the Office format itself.
        assert response.content == b"docx-bytes!"
        assert response.headers["content-type"] == docx_mime
        # The frontend picks its renderer from the served name, and the
        # disposition is rebuilt as inline instead of forwarding the upstream
        # attachment header.
        assert response.headers["x-file-name"] == "report.docx"
        assert response.headers["content-disposition"] == (
            'inline; filename="report.docx"; filename*=UTF-8\'\'report.docx'
        )
        assert mock_stream.call_args.args == (
            SERVER_URL,
            API_KEY,
            "kb-1",
            "00000000000040008000000000000001",
        )

    def test_preview_reports_the_converted_file_name(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        # AIDP answers an unsupported format with a PDF conversion, so the
        # served name replaces the uploaded extension. The frontend needs the
        # header to know it has to render a PDF.
        mock_response = httpx.Response(
            200,
            headers={
                "Content-Type": "application/pdf",
                "X-File-Name": "sheet.pdf",
                "Content-Disposition": 'attachment; filename="sheet.pdf"',
                "X-File-Size": "8",
            },
            content=b"%PDF-1.4",
            request=httpx.Request("GET", SERVER_URL),
        )

        async def stream_document(*args):
            return mock_response

        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="READ_ONLY"),
        ), patch.object(
            aidp_mgmt_app,
            "stream_aidp_preview_impl",
            side_effect=stream_document,
        ):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/"
                "00000000000040008000000000000001/preview",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert response.content == b"%PDF-1.4"
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["x-file-name"] == "sheet.pdf"
        assert response.headers["content-disposition"] == (
            'inline; filename="sheet.pdf"; filename*=UTF-8\'\'sheet.pdf'
        )

    def test_preview_uri_encodes_a_non_ascii_served_name(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        # httpx decodes header bytes into text, so AIDP's Chinese name arrives as
        # real Unicode - which response headers (latin-1 on the wire) cannot
        # carry. Forwarding it unchanged raised UnicodeEncodeError and answered
        # 500, so the preview failed for every non-ASCII file name.
        mock_response = httpx.Response(
            200,
            headers=[
                (b"content-type", b"application/pdf"),
                (b"x-file-name", "报告.pdf".encode()),
                (b"x-file-size", b"8"),
            ],
            content=b"%PDF-1.4",
            request=httpx.Request("GET", SERVER_URL),
        )

        async def stream_document(*args):
            return mock_response

        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="READ_ONLY"),
        ), patch.object(
            aidp_mgmt_app,
            "stream_aidp_preview_impl",
            side_effect=stream_document,
        ):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/"
                "00000000000040008000000000000001/preview",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert response.content == b"%PDF-1.4"
        # The name travels URI-encoded so it stays within latin-1; the frontend
        # decodes it, and the extension survives encoding unchanged.
        assert response.headers["x-file-name"] == "%E6%8A%A5%E5%91%8A.pdf"
        assert response.headers["content-disposition"] == (
            'inline; filename="__.pdf"; filename*=UTF-8\'\'%E6%8A%A5%E5%91%8A.pdf'
        )

    def test_preview_falls_back_when_aidp_omits_headers(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        mock_response = httpx.Response(
            200,
            content=b"raw",
            request=httpx.Request("GET", SERVER_URL),
        )

        async def stream_document(*args):
            return mock_response

        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="READ_ONLY"),
        ), patch.object(
            aidp_mgmt_app,
            "stream_aidp_preview_impl",
            side_effect=stream_document,
        ):
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/"
                "00000000000040008000000000000001/preview",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert response.headers["content-type"] == "application/octet-stream"
        # Without a served name the stream is still served inline, and the
        # viewer falls back to the uploaded name for its renderer choice.
        assert response.headers["content-disposition"] == "inline"
        assert "x-file-name" not in response.headers

    def test_preview_requires_standard_file_uuid(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "stream_aidp_preview_impl") as mock_stream:
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/uuid-1/preview",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        mock_stream.assert_not_called()

    def test_preview_without_read_returns_403(self):
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
            response = client.get(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/"
                "00000000000040008000000000000001/preview",
                headers=_bearer(),
            )
        finally:
            aidp_permission_service.require_permission = original_require
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize(
        "file_name, expected",
        [
            ("a.txt", 'inline; filename="a.txt"; filename*=UTF-8\'\'a.txt'),
            # Quotes and backslashes cannot appear in the ASCII fallback.
            (
                'a"b\\c.txt',
                'inline; filename="a_b_c.txt"; filename*=UTF-8\'\'a%22b%5Cc.txt',
            ),
            # Non-ASCII names only survive in the RFC 5987 parameter.
            (
                "报告.pdf",
                'inline; filename="__.pdf"; filename*=UTF-8\'\'%E6%8A%A5%E5%91%8A.pdf',
            ),
        ],
    )
    def test_build_inline_disposition_escapes_the_name(self, file_name, expected):
        from ext_components.aidp.apps import aidp_mgmt_app

        assert aidp_mgmt_app._build_inline_disposition(file_name) == expected

    def test_remove_does_not_invalidate_cache_when_no_file_succeeds(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        aidp_result = {
            "summary": {"total": 1, "success": 0, "failed": 1},
            "success_list": [],
            "failed_list": [{"file_uuid": "00000000000040008000000000000001"}],
        }
        with patch.object(
            aidp_permission_service,
            "require_permission",
            return_value=MagicMock(permission="EDIT"),
        ), patch.object(
            aidp_mgmt_app,
            "remove_aidp_docs_impl",
            return_value=aidp_result,
        ), patch.object(aidp_mgmt_app, "invalidate_aidp_kb_detail_cache") as mock_kb_cache, patch.object(
            aidp_mgmt_app, "invalidate_aidp_doc_count_cache"
        ) as mock_count_cache:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/documents/remove",
                headers=_bearer(),
                json={"file_uuids": ["00000000000040008000000000000001"]},
            )

        assert response.status_code == HTTPStatus.OK
        mock_kb_cache.assert_not_called()
        mock_count_cache.assert_not_called()

# --- Models list (auth only, no per-KB permission) ------------------------


