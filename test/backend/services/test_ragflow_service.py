"""
Unit tests for RAGFlow Service.
"""
import json
import sys
import types
from unittest.mock import MagicMock, patch

import httpx
import pytest

# -- Stub nexent.utils.http_client_manager to avoid pulling in the full SDK --
_mock_nexent_utils = types.ModuleType("nexent.utils")
_mock_nexent_utils_http = types.ModuleType("nexent.utils.http_client_manager")
_mock_nexent_utils_http.http_client_manager = MagicMock()
_mock_nexent = types.ModuleType("nexent")
_mock_nexent.utils = _mock_nexent_utils

_MODULE_STUBS = {
    "nexent": _mock_nexent,
    "nexent.utils": _mock_nexent_utils,
    "nexent.utils.http_client_manager": _mock_nexent_utils_http,
}
for _k, _v in _MODULE_STUBS.items():
    sys.modules.setdefault(_k, _v)

from backend.services.ragflow_service import (  # noqa: E402
    _validate_ragflow_config,
    _format_dataset_item,
    fetch_ragflow_datasets_impl,
)
from consts.error_code import ErrorCode  # noqa: E402
from consts.exceptions import AppException  # noqa: E402


# ---------------------------------------------------------------------------
# _validate_ragflow_config
# ---------------------------------------------------------------------------

class TestValidateRAGFlowConfig:
    def test_valid_config_does_not_raise(self):
        """Should not raise for valid URL and API key."""
        _validate_ragflow_config("http://localhost:9380", "test_api_key")

    def test_empty_url_raises(self):
        with pytest.raises(AppException) as excinfo:
            _validate_ragflow_config("", "test_api_key")
        assert excinfo.value.error_code == ErrorCode.RAGFLOW_CONFIG_INVALID
        assert "RAGFlow API URL is required" in str(excinfo.value)

    def test_none_url_raises(self):
        with pytest.raises(AppException) as excinfo:
            _validate_ragflow_config(None, "test_api_key")  # type: ignore[arg-type]
        assert excinfo.value.error_code == ErrorCode.RAGFLOW_CONFIG_INVALID

    def test_non_string_url_raises(self):
        with pytest.raises(AppException):
            _validate_ragflow_config(123, "test_api_key")  # type: ignore[arg-type]

    def test_empty_api_key_raises(self):
        with pytest.raises(AppException) as excinfo:
            _validate_ragflow_config("http://localhost:9380", "")
        assert excinfo.value.error_code == ErrorCode.RAGFLOW_CONFIG_INVALID
        assert "RAGFlow API key is required" in str(excinfo.value)

    def test_none_api_key_raises(self):
        with pytest.raises(AppException) as excinfo:
            _validate_ragflow_config("http://localhost:9380", None)  # type: ignore[arg-type]
        assert excinfo.value.error_code == ErrorCode.RAGFLOW_CONFIG_INVALID

    def test_non_string_api_key_raises(self):
        with pytest.raises(AppException):
            _validate_ragflow_config("http://localhost:9380", 456)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _format_dataset_item
# ---------------------------------------------------------------------------

class TestFormatDatasetItem:
    def test_format_complete_dataset(self):
        ds = {
            "id": "abc123",
            "name": "Test KB",
            "description": "A test knowledge base",
            "doc_num": 42,
            "chunk_num": 1000,
            "create_time": 1710268800,
            "update_time": 1710355200,
        }
        result = _format_dataset_item(ds)
        assert result["id"] == "abc123"
        assert result["name"] == "Test KB"
        assert result["description"] == "A test knowledge base"
        assert result["doc_count"] == 42
        assert result["chunk_count"] == 1000
        assert result["create_time"] == "1710268800"
        assert result["update_time"] == "1710355200"

    def test_format_uses_document_count_fallback(self):
        """When doc_num is 0, fall back to document_count."""
        ds = {
            "id": "abc",
            "name": "Test",
            "description": "",
            "doc_num": 0,
            "document_count": 5,
            "chunk_num": 0,
            "chunk_count": 50,
            "create_time": "",
            "update_time": "",
        }
        result = _format_dataset_item(ds)
        assert result["doc_count"] == 5
        assert result["chunk_count"] == 50

    def test_format_missing_fields_default_to_empty(self):
        ds: dict = {}
        result = _format_dataset_item(ds)
        assert result["id"] == ""
        assert result["name"] == ""
        assert result["description"] == ""
        assert result["doc_count"] == 0
        assert result["chunk_count"] == 0
        assert result["create_time"] == ""
        assert result["update_time"] == ""

    def test_format_chunk_num_fallback(self):
        """chunk_num takes priority, falls back to chunk_count."""
        ds = {
            "id": "1",
            "name": "KB",
            "description": "",
            "doc_num": 10,
            "chunk_num": 100,
            "chunk_count": 200,
            "create_time": "t1",
            "update_time": "t2",
        }
        result = _format_dataset_item(ds)
        assert result["chunk_count"] == 100  # chunk_num takes priority

    def test_format_create_date_fallback(self):
        """When create_time is empty, fall back to create_date."""
        ds = {
            "id": "1", "name": "KB", "description": "",
            "doc_num": 1, "chunk_num": 1,
            "create_time": "", "create_date": "2024-01-01",
            "update_time": "", "update_date": "2024-06-01",
        }
        result = _format_dataset_item(ds)
        assert result["create_time"] == "2024-01-01"
        assert result["update_time"] == "2024-06-01"


# ---------------------------------------------------------------------------
# fetch_ragflow_datasets_impl
# ---------------------------------------------------------------------------

class TestFetchRAGFlowDatasetsImpl:
    def _mock_client(self, status_code=200, json_data=None, raise_for_status=None):
        """Create a mock HTTP client with the given response."""
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = json_data or {}
        if raise_for_status:
            mock_response.raise_for_status.side_effect = raise_for_status
        return mock_response

    def test_fetch_success(self):
        mock_resp = self._mock_client(json_data={
            "code": 0,
            "message": "Success",
            "data": [
                {"id": "ds1", "name": "KB 1", "description": "First KB",
                 "doc_num": 10, "chunk_num": 100,
                 "create_time": 1000, "update_time": 2000},
                {"id": "ds2", "name": "KB 2", "description": "Second KB",
                 "doc_num": 5, "chunk_num": 50,
                 "create_time": 3000, "update_time": 4000},
            ],
        })

        with patch(
            "nexent.utils.http_client_manager.http_client_manager.get_sync_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_get_client.return_value = mock_client

            result = fetch_ragflow_datasets_impl("http://localhost:9380", "test_key")

        assert "data" in result
        assert len(result["data"]) == 2
        assert result["data"][0]["id"] == "ds1"
        assert result["data"][0]["name"] == "KB 1"
        assert result["data"][1]["id"] == "ds2"

    def test_fetch_strips_trailing_slash(self):
        mock_resp = self._mock_client(json_data={
            "code": 0, "message": "Success", "data": [],
        })

        with patch(
            "nexent.utils.http_client_manager.http_client_manager.get_sync_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_get_client.return_value = mock_client

            fetch_ragflow_datasets_impl("http://localhost:9380/", "test_key")

        # Verify the URL was constructed without double slash
        call_url = mock_client.get.call_args[0][0]
        assert call_url == "http://localhost:9380/api/v1/datasets"

    def test_fetch_validates_config_first(self):
        """Should raise AppException for invalid config before making HTTP call."""
        with pytest.raises(AppException) as excinfo:
            fetch_ragflow_datasets_impl("", "")
        assert excinfo.value.error_code == ErrorCode.RAGFLOW_CONFIG_INVALID

    def test_fetch_api_error_code(self):
        """RAGFlow API returns error code != 0."""
        mock_resp = self._mock_client(json_data={
            "code": 102,
            "message": "Authentication failed",
        })

        with patch(
            "nexent.utils.http_client_manager.http_client_manager.get_sync_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_get_client.return_value = mock_client

            with pytest.raises(AppException) as excinfo:
                fetch_ragflow_datasets_impl("http://localhost:9380", "test_key")

        assert excinfo.value.error_code == ErrorCode.RAGFLOW_SERVICE_ERROR
        assert "error code 102" in str(excinfo.value)

    def test_fetch_request_error(self):
        """httpx.RequestError is translated to RAGFLOW_CONNECTION_ERROR."""
        with patch(
            "nexent.utils.http_client_manager.http_client_manager.get_sync_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.get.side_effect = httpx.RequestError(
                "Connection refused", request=MagicMock()
            )
            mock_get_client.return_value = mock_client

            with pytest.raises(AppException) as excinfo:
                fetch_ragflow_datasets_impl("http://localhost:9380", "test_key")

        assert excinfo.value.error_code == ErrorCode.RAGFLOW_CONNECTION_ERROR
        assert "RAGFlow API request failed" in str(excinfo.value)

    def test_fetch_http_401_auth_error(self):
        """HTTP 401 is translated to RAGFLOW_AUTH_ERROR."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        http_error = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=mock_resp
        )
        mock_resp.raise_for_status.side_effect = http_error

        with patch(
            "nexent.utils.http_client_manager.http_client_manager.get_sync_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_get_client.return_value = mock_client

            with pytest.raises(AppException) as excinfo:
                fetch_ragflow_datasets_impl("http://localhost:9380", "test_key")

        assert excinfo.value.error_code == ErrorCode.RAGFLOW_AUTH_ERROR
        assert "RAGFlow authentication failed" in str(excinfo.value)

    def test_fetch_http_403_forbidden(self):
        """HTTP 403 is translated to RAGFLOW_AUTH_ERROR."""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        http_error = httpx.HTTPStatusError(
            "Forbidden", request=MagicMock(), response=mock_resp
        )
        mock_resp.raise_for_status.side_effect = http_error

        with patch(
            "nexent.utils.http_client_manager.http_client_manager.get_sync_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_get_client.return_value = mock_client

            with pytest.raises(AppException) as excinfo:
                fetch_ragflow_datasets_impl("http://localhost:9380", "test_key")

        assert excinfo.value.error_code == ErrorCode.RAGFLOW_AUTH_ERROR

    def test_fetch_http_500_server_error(self):
        """HTTP 500 is translated to RAGFLOW_SERVICE_ERROR."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        http_error = httpx.HTTPStatusError(
            "Internal Server Error", request=MagicMock(), response=mock_resp
        )
        mock_resp.raise_for_status.side_effect = http_error

        with patch(
            "nexent.utils.http_client_manager.http_client_manager.get_sync_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_get_client.return_value = mock_client

            with pytest.raises(AppException) as excinfo:
                fetch_ragflow_datasets_impl("http://localhost:9380", "test_key")

        assert excinfo.value.error_code == ErrorCode.RAGFLOW_SERVICE_ERROR
        assert "HTTP error 500" in str(excinfo.value)

    def test_fetch_json_decode_error(self):
        """JSON decode error is translated to RAGFLOW_RESPONSE_ERROR."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)

        with patch(
            "nexent.utils.http_client_manager.http_client_manager.get_sync_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_get_client.return_value = mock_client

            with pytest.raises(AppException) as excinfo:
                fetch_ragflow_datasets_impl("http://localhost:9380", "test_key")

        assert excinfo.value.error_code == ErrorCode.RAGFLOW_RESPONSE_ERROR
        assert "Failed to parse RAGFlow API response" in str(excinfo.value)
