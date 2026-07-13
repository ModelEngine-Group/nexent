"""
Unit tests for AIDP Management App Layer.

Tests the 8 FastAPI endpoints in backend/apps/aidp_mgmt_app.py
that proxy AIDP knowledge base CRUD and document management.
"""
import io
import sys
import os
import types
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# -------------------- Bootstrap module stubs --------------------
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Stub nexent SDK modules so imports don't pull optional runtime deps.
_def = lambda name, **attrs: types.ModuleType(name)
nexent_pkg = _def("nexent"); nexent_pkg.__path__ = []
nexent_utils_pkg = _def("nexent.utils"); nexent_utils_pkg.__path__ = []
nexent_http_mgr = _def("nexent.utils.http_client_manager")
nexent_http_mgr.http_client_manager = MagicMock()

for _mod in [nexent_pkg, nexent_utils_pkg, nexent_http_mgr]:
    sys.modules.setdefault(_mod.__name__, _mod)

# Stub backend package hierarchy
backend_pkg = sys.modules.get("backend") or _def("backend")
backend_pkg.__path__ = [backend_dir]
backend_db_pkg = _def("backend.database"); backend_db_pkg.__path__ = [os.path.join(backend_dir, "database")]
backend_db_client_pkg = _def("backend.database.client"); backend_db_client_pkg.MinioClient = MagicMock()

for _mod in [backend_pkg, backend_db_pkg, backend_db_client_pkg]:
    sys.modules.setdefault(_mod.__name__, _mod)

# Now safe to import backend modules under test
from backend.apps.aidp_mgmt_app import aidp_mgmt_router
from backend.apps.app_factory import register_exception_handlers
from consts.error_code import ErrorCode
from consts.exceptions import AppException
from backend.services.aidp_service import (
    count_aidp_kbs_impl,
    create_aidp_kb_impl,
    delete_aidp_kb_impl,
    fetch_aidp_knowledge_bases_impl,
    get_aidp_kb_impl,
    list_aidp_docs_impl,
    update_aidp_kb_impl,
    upload_aidp_docs_impl,
)

# -------------------- Helpers --------------------

SERVER_URL = "http://aidp.example.com:30081"
API_KEY = "test-aidp-api-key"
KDS_ID = "kb-test-001"


def _build_app() -> FastAPI:
    """Build a FastAPI app with aidp_mgmt_router and exception handlers."""
    app = FastAPI()
    app.include_router(aidp_mgmt_router)
    register_exception_handlers(app)
    return app


# ==================== GET /knowledge-bases ====================


class TestListKnowledgeBases:
    """Tests for GET /aidp-mgmt/knowledge-bases."""

    def test_list_kbs_success(self):
        app = _build_app()
        client = TestClient(app)
        expected = {
            "value": [
                {"kds_id": "kb-1", "kds_name": "KB One"},
                {"kds_id": "kb-2", "kds_name": "KB Two"},
            ],
            "total_count": 2,
            "next_link": None,
        }

        with patch("backend.apps.aidp_mgmt_app.fetch_aidp_knowledge_bases_impl") as mock:
            mock.return_value = expected
            response = client.get(
                "/aidp-mgmt/knowledge-bases",
                params={"server_url": SERVER_URL, "api_key": API_KEY, "page": 1, "page_size": 10},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == expected
        mock.assert_called_once_with(
            server_url=SERVER_URL,
            api_key=API_KEY,
            page=1,
            page_size=10,
        )

    def test_list_kbs_custom_pagination(self):
        app = _build_app()
        client = TestClient(app)
        expected = {"value": [], "total_count": 0, "next_link": None}

        with patch("backend.apps.aidp_mgmt_app.fetch_aidp_knowledge_bases_impl") as mock:
            mock.return_value = expected
            response = client.get(
                "/aidp-mgmt/knowledge-bases",
                params={"server_url": SERVER_URL, "api_key": API_KEY, "page": 3, "page_size": 50},
            )

        assert response.status_code == HTTPStatus.OK
        mock.assert_called_once_with(
            server_url=SERVER_URL,
            api_key=API_KEY,
            page=3,
            page_size=50,
        )

    def test_list_kbs_app_exception_passthrough(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.fetch_aidp_knowledge_bases_impl") as mock:
            mock.side_effect = AppException(ErrorCode.AIDP_AUTH_ERROR, "auth failed")
            response = client.get(
                "/aidp-mgmt/knowledge-bases",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
            )

        assert response.status_code == HTTPStatus.BAD_GATEWAY  # 502 for AIDP_AUTH_ERROR

    def test_list_kbs_unexpected_error_wraps_aidp_service_error(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.fetch_aidp_knowledge_bases_impl") as mock:
            mock.side_effect = RuntimeError("unexpected")
            response = client.get(
                "/aidp-mgmt/knowledge-bases",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
            )

        assert response.status_code == HTTPStatus.BAD_GATEWAY


# ==================== GET /knowledge-bases/count ====================


class TestCountKnowledgeBases:
    """Tests for GET /aidp-mgmt/knowledge-bases/count."""

    def test_count_kbs_success(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.count_aidp_kbs_impl") as mock:
            mock.return_value = 42
            response = client.get(
                "/aidp-mgmt/knowledge-bases/count",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"total_count": 42}
        mock.assert_called_once_with(server_url=SERVER_URL, api_key=API_KEY)

    def test_count_kbs_zero(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.count_aidp_kbs_impl") as mock:
            mock.return_value = 0
            response = client.get(
                "/aidp-mgmt/knowledge-bases/count",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"total_count": 0}

    def test_count_kbs_app_exception_passthrough(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.count_aidp_kbs_impl") as mock:
            mock.side_effect = AppException(ErrorCode.AIDP_CONNECTION_ERROR, "timeout")
            response = client.get(
                "/aidp-mgmt/knowledge-bases/count",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
            )

        assert response.status_code == HTTPStatus.BAD_GATEWAY

    def test_count_kbs_unexpected_error(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.count_aidp_kbs_impl") as mock:
            mock.side_effect = ValueError("bad value")
            response = client.get(
                "/aidp-mgmt/knowledge-bases/count",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
            )

        assert response.status_code == HTTPStatus.BAD_GATEWAY


# ==================== POST /knowledge-bases ====================


class TestCreateKnowledgeBase:
    """Tests for POST /aidp-mgmt/knowledge-bases."""

    def test_create_kb_minimal_payload(self):
        app = _build_app()
        client = TestClient(app)
        created = {"kds_id": "kb-new", "kds_name": "New KB"}

        with patch("backend.apps.aidp_mgmt_app.create_aidp_kb_impl") as mock:
            mock.return_value = created
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
                json={"name": "New KB"},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == created
        mock.assert_called_once_with(
            server_url=SERVER_URL,
            api_key=API_KEY,
            payload={"name": "New KB"},
        )

    def test_create_kb_full_payload(self):
        app = _build_app()
        client = TestClient(app)
        created = {"kds_id": "kb-new", "kds_name": "Full KB"}

        with patch("backend.apps.aidp_mgmt_app.create_aidp_kb_impl") as mock:
            mock.return_value = created
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
                json={
                    "name": "Full KB",
                    "description": "A full knowledge base",
                    "embedding_model": "bge-large-zh",
                    "is_multimodal": True,
                    "vision_model": "qwen-vl-max",
                },
            )

        assert response.status_code == HTTPStatus.OK
        call_payload = mock.call_args.kwargs["payload"]
        assert call_payload["name"] == "Full KB"
        assert call_payload["description"] == "A full knowledge base"
        assert call_payload["embedding_model"] == "bge-large-zh"
        assert call_payload["is_multimodal"] is True
        assert call_payload["vision_model"] == "qwen-vl-max"

    def test_create_kb_excludes_none_fields(self):
        """None fields in request should be excluded via model_dump(exclude_none=True)."""
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.create_aidp_kb_impl") as mock:
            mock.return_value = {"kds_id": "kb-1"}
            client.post(
                "/aidp-mgmt/knowledge-bases",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
                json={"name": "KB"},
            )

        call_payload = mock.call_args.kwargs["payload"]
        assert "description" not in call_payload
        assert "embedding_model" not in call_payload

    def test_create_kb_config_invalid_error(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.create_aidp_kb_impl") as mock:
            mock.side_effect = AppException(ErrorCode.AIDP_CONFIG_INVALID, "bad config")
            response = client.post(
                "/aidp-mgmt/knowledge-bases",
                params={"server_url": "", "api_key": API_KEY},
                json={"name": "KB"},
            )

        assert response.status_code == HTTPStatus.BAD_REQUEST


# ==================== GET /knowledge-bases/{kds_id} ====================


class TestGetKnowledgeBase:
    """Tests for GET /aidp-mgmt/knowledge-bases/{kds_id}."""

    def test_get_kb_success(self):
        app = _build_app()
        client = TestClient(app)
        detail = {
            "kds_id": KDS_ID,
            "kds_name": "Test KB",
            "description": "A test KB",
            "document_count": 10,
            "state": 4,
        }

        with patch("backend.apps.aidp_mgmt_app.get_aidp_kb_impl") as mock:
            mock.return_value = detail
            response = client.get(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == detail
        mock.assert_called_once_with(
            server_url=SERVER_URL,
            api_key=API_KEY,
            kds_id=KDS_ID,
        )

    def test_get_kb_service_error(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.get_aidp_kb_impl") as mock:
            mock.side_effect = AppException(ErrorCode.AIDP_SERVICE_ERROR, "error")
            response = client.get(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
            )

        assert response.status_code == HTTPStatus.BAD_GATEWAY


# ==================== PUT /knowledge-bases/{kds_id} ====================


class TestUpdateKnowledgeBase:
    """Tests for PUT /aidp-mgmt/knowledge-bases/{kds_id}."""

    def test_update_kb_name_only(self):
        app = _build_app()
        client = TestClient(app)
        updated = {"kds_id": KDS_ID, "kds_name": "Renamed KB"}

        with patch("backend.apps.aidp_mgmt_app.update_aidp_kb_impl") as mock:
            mock.return_value = updated
            response = client.put(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
                json={"name": "Renamed KB"},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == updated
        mock.assert_called_once_with(
            server_url=SERVER_URL,
            api_key=API_KEY,
            kds_id=KDS_ID,
            payload={"name": "Renamed KB"},
        )

    def test_update_kb_description_only(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.update_aidp_kb_impl") as mock:
            mock.return_value = {"kds_id": KDS_ID}
            response = client.put(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
                json={"description": "Updated desc"},
            )

        assert response.status_code == HTTPStatus.OK
        call_payload = mock.call_args.kwargs["payload"]
        assert call_payload == {"description": "Updated desc"}

    def test_update_kb_both_fields(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.update_aidp_kb_impl") as mock:
            mock.return_value = {"kds_id": KDS_ID}
            response = client.put(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
                json={"name": "New Name", "description": "New Desc"},
            )

        assert response.status_code == HTTPStatus.OK

    def test_update_kb_empty_body_returns_validation_error(self):
        """Empty body (no name, no description) should raise AppException(COMMON_VALIDATION_ERROR)."""
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.update_aidp_kb_impl"):
            response = client.put(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
                json={},
            )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_kb_service_error(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.update_aidp_kb_impl") as mock:
            mock.side_effect = AppException(ErrorCode.AIDP_SERVICE_ERROR, "fail")
            response = client.put(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
                json={"name": "X"},
            )

        assert response.status_code == HTTPStatus.BAD_GATEWAY


# ==================== DELETE /knowledge-bases/{kds_id} ====================


class TestDeleteKnowledgeBase:
    """Tests for DELETE /aidp-mgmt/knowledge-bases/{kds_id}."""

    def test_delete_kb_success(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.delete_aidp_kb_impl") as mock:
            mock.return_value = True
            response = client.delete(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"success": True}
        mock.assert_called_once_with(
            server_url=SERVER_URL,
            api_key=API_KEY,
            kds_id=KDS_ID,
        )

    def test_delete_kb_auth_error(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.delete_aidp_kb_impl") as mock:
            mock.side_effect = AppException(ErrorCode.AIDP_AUTH_ERROR, "unauthorized")
            response = client.delete(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
            )

        assert response.status_code == HTTPStatus.BAD_GATEWAY

    def test_delete_kb_unexpected_error(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.delete_aidp_kb_impl") as mock:
            mock.side_effect = Exception("boom")
            response = client.delete(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
            )

        assert response.status_code == HTTPStatus.BAD_GATEWAY


# ==================== POST /knowledge-bases/{kds_id}/documents ====================


class TestUploadDocuments:
    """Tests for POST /aidp-mgmt/knowledge-bases/{kds_id}/documents."""

    def test_upload_docs_success(self):
        app = _build_app()
        client = TestClient(app)
        upload_result = {"success_count": 2, "failed_count": 0, "errors": []}

        with patch("backend.apps.aidp_mgmt_app.upload_aidp_docs_impl") as mock:
            mock.return_value = upload_result
            response = client.post(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}/documents",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
                files=[
                    ("files", ("doc1.pdf", b"pdf-content", "application/pdf")),
                    ("files", ("doc2.txt", b"text-content", "text/plain")),
                ],
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == upload_result
        mock.assert_called_once()
        call_kwargs = mock.call_args.kwargs
        assert call_kwargs["server_url"] == SERVER_URL
        assert call_kwargs["api_key"] == API_KEY
        assert call_kwargs["kds_id"] == KDS_ID
        assert len(call_kwargs["files"]) == 2

    def test_upload_docs_single_file(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.upload_aidp_docs_impl") as mock:
            mock.return_value = {"success_count": 1}
            response = client.post(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}/documents",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
                files=[("files", ("readme.md", b"# Hello", "text/markdown"))],
            )

        assert response.status_code == HTTPStatus.OK

    def test_upload_docs_rate_limit(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.upload_aidp_docs_impl") as mock:
            mock.side_effect = AppException(ErrorCode.AIDP_RATE_LIMIT, "slow down")
            response = client.post(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}/documents",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
                files=[("files", ("a.pdf", b"data", "application/pdf"))],
            )

        assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS  # 429

    def test_upload_docs_no_files_returns_422(self):
        """FastAPI should reject missing files with 422."""
        app = _build_app()
        client = TestClient(app)

        response = client.post(
            f"/aidp-mgmt/knowledge-bases/{KDS_ID}/documents",
            params={"server_url": SERVER_URL, "api_key": API_KEY},
        )

        assert response.status_code == 422


# ==================== GET /knowledge-bases/{kds_id}/documents ====================


class TestListDocuments:
    """Tests for GET /aidp-mgmt/knowledge-bases/{kds_id}/documents."""

    def test_list_docs_success(self):
        app = _build_app()
        client = TestClient(app)
        expected = {
            "value": [
                {"file_ino_no": "f-1", "file_name": "doc1.pdf", "file_size": 1024},
                {"file_ino_no": "f-2", "file_name": "doc2.txt", "file_size": 512},
            ],
            "total_count": 2,
        }

        with patch("backend.apps.aidp_mgmt_app.list_aidp_docs_impl") as mock:
            mock.return_value = expected
            response = client.get(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}/documents",
                params={"server_url": SERVER_URL, "api_key": API_KEY, "page": 1, "page_size": 10},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == expected
        mock.assert_called_once_with(
            server_url=SERVER_URL,
            api_key=API_KEY,
            kds_id=KDS_ID,
            page=1,
            page_size=10,
        )

    def test_list_docs_custom_pagination(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.list_aidp_docs_impl") as mock:
            mock.return_value = {"value": [], "total_count": 0}
            response = client.get(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}/documents",
                params={"server_url": SERVER_URL, "api_key": API_KEY, "page": 5, "page_size": 20},
            )

        assert response.status_code == HTTPStatus.OK
        mock.assert_called_once_with(
            server_url=SERVER_URL,
            api_key=API_KEY,
            kds_id=KDS_ID,
            page=5,
            page_size=20,
        )

    def test_list_docs_service_error(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.list_aidp_docs_impl") as mock:
            mock.side_effect = AppException(ErrorCode.AIDP_SERVICE_ERROR, "error")
            response = client.get(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}/documents",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
            )

        assert response.status_code == HTTPStatus.BAD_GATEWAY

    def test_list_docs_unexpected_error(self):
        app = _build_app()
        client = TestClient(app)

        with patch("backend.apps.aidp_mgmt_app.list_aidp_docs_impl") as mock:
            mock.side_effect = TypeError("type err")
            response = client.get(
                f"/aidp-mgmt/knowledge-bases/{KDS_ID}/documents",
                params={"server_url": SERVER_URL, "api_key": API_KEY},
            )

        assert response.status_code == HTTPStatus.BAD_GATEWAY


# ==================== Validation & Param Tests ====================


class TestParamValidation:
    """Tests for FastAPI query parameter validation across endpoints."""

    def test_list_kbs_missing_server_url_returns_422(self):
        app = _build_app()
        client = TestClient(app)

        response = client.get(
            "/aidp-mgmt/knowledge-bases",
            params={"api_key": API_KEY},
        )

        assert response.status_code == 422

    def test_list_kbs_missing_api_key_returns_422(self):
        app = _build_app()
        client = TestClient(app)

        response = client.get(
            "/aidp-mgmt/knowledge-bases",
            params={"server_url": SERVER_URL},
        )

        assert response.status_code == 422

    def test_list_kbs_page_below_min_returns_422(self):
        app = _build_app()
        client = TestClient(app)

        response = client.get(
            "/aidp-mgmt/knowledge-bases",
            params={"server_url": SERVER_URL, "api_key": API_KEY, "page": 0},
        )

        assert response.status_code == 422

    def test_list_kbs_page_size_above_max_returns_422(self):
        app = _build_app()
        client = TestClient(app)

        response = client.get(
            "/aidp-mgmt/knowledge-bases",
            params={"server_url": SERVER_URL, "api_key": API_KEY, "page_size": 101},
        )

        assert response.status_code == 422

    def test_create_kb_missing_name_returns_422(self):
        """CreateKbRequest requires 'name' field."""
        app = _build_app()
        client = TestClient(app)

        response = client.post(
            "/aidp-mgmt/knowledge-bases",
            params={"server_url": SERVER_URL, "api_key": API_KEY},
            json={"description": "no name"},
        )

        assert response.status_code == 422
