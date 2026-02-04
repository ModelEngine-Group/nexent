"""
Unit tests for Dify Service Layer.

Tests the fetch_dify_datasets_impl function which handles API calls to Dify
for knowledge base operations.
"""
import json
import pytest
from unittest.mock import MagicMock, patch
import httpx


def _create_mock_client(mock_response):
    """
    Create a properly configured mock client that works with context manager.

    When using 'with httpx.Client() as client:', the __enter__ method is called.
    By default, MagicMock.__enter__ returns a new MagicMock, which breaks our tests.
    We need to configure __enter__ to return the mock_client itself.
    """
    mock_client = MagicMock()
    mock_client.get.return_value = mock_response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    return mock_client


class TestFetchDifyDatasetsImpl:
    """Test class for fetch_dify_datasets_impl function."""

    def test_fetch_dify_datasets_impl_success_single_dataset(self):
        """Test successful fetching of a single dataset from Dify API."""
        # Mock httpx.Client and response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "ds-123",
                    "name": "Test Knowledge Base",
                    "document_count": 10,
                    "created_at": 1704067200,
                    "updated_at": 1704153600,
                    "embedding_available": True,
                    "embedding_model": "text-embedding-3-small"
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client):
            from backend.services.dify_service import fetch_dify_datasets_impl

            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        # Verify structure
        assert result["count"] == 1
        assert len(result["indices"]) == 1
        assert result["indices"][0] == "ds-123"
        assert len(result["indices_info"]) == 1

        # Verify indices_info content
        info = result["indices_info"][0]
        assert info["name"] == "ds-123"
        assert info["display_name"] == "Test Knowledge Base"
        assert info["stats"]["base_info"]["doc_count"] == 10
        assert info["stats"]["base_info"]["process_source"] == "Dify"
        assert info["stats"]["base_info"]["embedding_model"] == "text-embedding-3-small"
        assert result["pagination"]["embedding_available"] is True

    def test_fetch_dify_datasets_impl_success_multiple_datasets(self):
        """Test successful fetching of multiple datasets from Dify API."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "ds-1",
                    "name": "Knowledge Base 1",
                    "document_count": 5,
                    "created_at": 1704067200,
                    "updated_at": 1704153600,
                    "embedding_available": True,
                    "embedding_model": "text-embedding-3-small"
                },
                {
                    "id": "ds-2",
                    "name": "Knowledge Base 2",
                    "document_count": 20,
                    "created_at": 1704240000,
                    "updated_at": 1704326400,
                    "embedding_available": False
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client):
            from backend.services.dify_service import fetch_dify_datasets_impl

            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        assert result["count"] == 2
        assert len(result["indices"]) == 2
        assert result["indices"] == ["ds-1", "ds-2"]
        assert len(result["indices_info"]) == 2

        # Check first dataset
        assert result["indices_info"][0]["display_name"] == "Knowledge Base 1"
        assert result["indices_info"][0]["stats"]["base_info"]["doc_count"] == 5

        # Check second dataset
        assert result["indices_info"][1]["display_name"] == "Knowledge Base 2"
        assert result["indices_info"][1]["stats"]["base_info"]["doc_count"] == 20
        assert result["pagination"]["embedding_available"] is False

    def test_fetch_dify_datasets_impl_empty_response(self):
        """Test fetching when Dify API returns empty dataset list."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client):
            from backend.services.dify_service import fetch_dify_datasets_impl

            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        assert result["count"] == 0
        assert result["indices"] == []
        assert result["indices_info"] == []
        assert result["pagination"]["embedding_available"] is False

    def test_fetch_dify_datasets_impl_invalid_api_base_none(self):
        """Test ValueError when dify_api_base is None."""
        from backend.services.dify_service import fetch_dify_datasets_impl

        with pytest.raises(ValueError) as excinfo:
            fetch_dify_datasets_impl(
                dify_api_base=None,
                api_key="test-api-key"
            )

        assert "dify_api_base is required and must be a non-empty string" in str(
            excinfo.value)

    def test_fetch_dify_datasets_impl_invalid_api_base_empty_string(self):
        """Test ValueError when dify_api_base is empty string."""
        from backend.services.dify_service import fetch_dify_datasets_impl

        with pytest.raises(ValueError) as excinfo:
            fetch_dify_datasets_impl(
                dify_api_base="",
                api_key="test-api-key"
            )

        assert "dify_api_base is required and must be a non-empty string" in str(
            excinfo.value)

    def test_fetch_dify_datasets_impl_invalid_api_base_not_string(self):
        """Test ValueError when dify_api_base is not a string."""
        from backend.services.dify_service import fetch_dify_datasets_impl

        with pytest.raises(ValueError) as excinfo:
            fetch_dify_datasets_impl(
                dify_api_base=12345,
                api_key="test-api-key"
            )

        assert "dify_api_base is required and must be a non-empty string" in str(
            excinfo.value)

    def test_fetch_dify_datasets_impl_invalid_api_key_none(self):
        """Test ValueError when api_key is None."""
        from backend.services.dify_service import fetch_dify_datasets_impl

        with pytest.raises(ValueError) as excinfo:
            fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key=None
            )

        assert "api_key is required and must be a non-empty string" in str(
            excinfo.value)

    def test_fetch_dify_datasets_impl_invalid_api_key_empty_string(self):
        """Test ValueError when api_key is empty string."""
        from backend.services.dify_service import fetch_dify_datasets_impl

        with pytest.raises(ValueError) as excinfo:
            fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key=""
            )

        assert "api_key is required and must be a non-empty string" in str(
            excinfo.value)

    def test_fetch_dify_datasets_impl_invalid_api_key_not_string(self):
        """Test ValueError when api_key is not a string."""
        from backend.services.dify_service import fetch_dify_datasets_impl

        with pytest.raises(ValueError) as excinfo:
            fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key=[]  # list is not a string
            )

        assert "api_key is required and must be a non-empty string" in str(
            excinfo.value)

    def test_fetch_dify_datasets_impl_url_normalization_trailing_slash(self):
        """Test that trailing slash is removed from API base URL."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client):
            from backend.services.dify_service import fetch_dify_datasets_impl

            fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com/",
                api_key="test-api-key"
            )

        # Verify URL is normalized (no trailing slash)
        mock_client.get.assert_called_once()
        called_url = mock_client.get.call_args[0][0]
        assert called_url == "https://dify.example.com/v1/datasets"
        assert not called_url.endswith("//")

    def test_fetch_dify_datasets_impl_http_error(self):
        """Test handling of HTTP status errors from Dify API."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found",
            request=MagicMock(),
            response=MagicMock(status_code=404)
        )
        mock_response.json = MagicMock()  # Should not be called

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client):
            from backend.services.dify_service import fetch_dify_datasets_impl

            with pytest.raises(Exception) as excinfo:
                fetch_dify_datasets_impl(
                    dify_api_base="https://dify.example.com",
                    api_key="test-api-key"
                )

            assert "Dify API HTTP error" in str(excinfo.value)

    def test_fetch_dify_datasets_impl_request_error(self):
        """Test handling of request errors (connection issues)."""
        mock_response = MagicMock()
        mock_request_error = httpx.RequestError(
            "Connection failed", request=MagicMock())
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock()  # Should not be called

        mock_client = MagicMock()
        mock_client.get.side_effect = mock_request_error
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client):
            from backend.services.dify_service import fetch_dify_datasets_impl

            with pytest.raises(Exception) as excinfo:
                fetch_dify_datasets_impl(
                    dify_api_base="https://dify.example.com",
                    api_key="test-api-key"
                )

            assert "Dify API request failed" in str(excinfo.value)

    def test_fetch_dify_datasets_impl_json_decode_error(self):
        """Test handling of invalid JSON response from Dify API."""
        mock_response = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError(
            "Invalid JSON", "", 0)
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client):
            from backend.services.dify_service import fetch_dify_datasets_impl

            with pytest.raises(Exception) as excinfo:
                fetch_dify_datasets_impl(
                    dify_api_base="https://dify.example.com",
                    api_key="test-api-key"
                )

            assert "Failed to parse Dify API response" in str(excinfo.value)

    def test_fetch_dify_datasets_impl_missing_data_key(self):
        """Test handling of response missing 'data' key."""
        mock_response = MagicMock()
        mock_response.json.return_value = {}  # Missing 'data' key
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client):
            from backend.services.dify_service import fetch_dify_datasets_impl

            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        # Should return empty result when data key is missing
        assert result["count"] == 0
        assert result["indices"] == []
        assert result["indices_info"] == []

    def test_fetch_dify_datasets_impl_dataset_without_id(self):
        """Test that datasets without ID are skipped."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "",  # Empty ID should be skipped
                    "name": "Invalid Dataset"
                },
                {
                    "id": "ds-valid",
                    "name": "Valid Dataset",
                    "document_count": 5
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client):
            from backend.services.dify_service import fetch_dify_datasets_impl

            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        assert result["count"] == 1
        assert result["indices"] == ["ds-valid"]
        assert result["indices_info"][0]["display_name"] == "Valid Dataset"

    def test_fetch_dify_datasets_impl_dataset_missing_optional_fields(self):
        """Test dataset with missing optional fields (document_count, etc.)."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "ds-minimal",
                    "name": "Minimal Dataset"
                    # No document_count, created_at, etc.
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client):
            from backend.services.dify_service import fetch_dify_datasets_impl

            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        assert result["count"] == 1
        info = result["indices_info"][0]
        assert info["name"] == "ds-minimal"
        assert info["stats"]["base_info"]["doc_count"] == 0
        assert info["stats"]["base_info"]["chunk_count"] == 0
        assert info["stats"]["base_info"]["embedding_model"] == ""

    def test_fetch_dify_datasets_impl_timestamp_conversion(self):
        """Test that Unix timestamps are converted to milliseconds."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "ds-1",
                    "name": "Test Dataset",
                    "document_count": 5,
                    "created_at": 1704067200,  # 2024-01-01 00:00:00 UTC
                    "updated_at": 1704153600   # 2024-01-02 00:00:00 UTC
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client):
            from backend.services.dify_service import fetch_dify_datasets_impl

            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        # Timestamps should be converted to milliseconds (multiply by 1000)
        info = result["indices_info"][0]
        assert info["stats"]["base_info"]["creation_date"] == 1704067200000
        assert info["stats"]["base_info"]["update_date"] == 1704153600000

    def test_fetch_dify_datasets_impl_timestamp_zero_for_missing(self):
        """Test that missing timestamps result in zero."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "ds-1",
                    "name": "Test Dataset",
                    "created_at": None,
                    "updated_at": None
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client):
            from backend.services.dify_service import fetch_dify_datasets_impl

            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        info = result["indices_info"][0]
        assert info["stats"]["base_info"]["creation_date"] == 0
        assert info["stats"]["base_info"]["update_date"] == 0

    def test_fetch_dify_datasets_impl_request_headers(self):
        """Test that correct headers are sent in API request."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client):
            from backend.services.dify_service import fetch_dify_datasets_impl

            fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="my-secret-api-key"
            )

        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args

        # Verify URL
        assert call_args[0][0] == "https://dify.example.com/v1/datasets"

        # Verify headers
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer my-secret-api-key"
        assert headers["Content-Type"] == "application/json"

    def test_fetch_dify_datasets_impl_http_client_timeout(self):
        """Test that HTTP client is configured with correct timeout."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = _create_mock_client(mock_response)

        with patch('backend.services.dify_service.httpx.Client', return_value=mock_client) as mock_client_class:
            from backend.services.dify_service import fetch_dify_datasets_impl

            fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        # Verify Client was instantiated with timeout=30, verify=False
        mock_client_class.assert_called_once_with(timeout=30, verify=False)
