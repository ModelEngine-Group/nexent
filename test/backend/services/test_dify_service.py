"""
Unit tests for Dify Service Layer (backend/services/knowledge_base/dify_service.py).

Tests the service functions for Dify knowledge base operations.
"""
import sys
import os
from unittest.mock import patch, MagicMock
from http import HTTPStatus

import pytest

# Add backend directory to Python path for proper imports
project_root = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '../../../'))
backend_dir = os.path.join(project_root, 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


class TestFetchDifyDatasetsImpl:
    """Test class for fetch_dify_datasets_impl function."""

    def test_fetch_dify_datasets_success(self):
        """Test successful fetching of Dify datasets with valid response."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        # Mock httpx Client and response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "ds_123",
                    "name": "Test Knowledge Base",
                    "document_count": 10,
                    "created_at": 1704067200,
                    "updated_at": 1704153600,
                    "embedding_available": True,
                    "embedding_model": "text-embedding-3-small"
                },
                {
                    "id": "ds_456",
                    "name": "Another Knowledge Base",
                    "document_count": 5,
                    "created_at": 1703980800,
                    "updated_at": 1704326400,
                    "embedding_available": False,
                    "embedding_model": ""
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch('httpx.Client', return_value=mock_client):
            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        # Verify result structure
        assert result["count"] == 2
        assert len(result["indices"]) == 2
        assert result["indices"] == ["ds_123", "ds_456"]
        assert len(result["indices_info"]) == 2
        assert result["pagination"]["embedding_available"] == True

        # Verify first dataset transformation
        first_info = result["indices_info"][0]
        assert first_info["name"] == "ds_123"
        assert first_info["display_name"] == "Test Knowledge Base"
        assert first_info["stats"]["base_info"]["doc_count"] == 10
        assert first_info["stats"]["base_info"]["chunk_count"] == 0  # Dify doesn't provide this
        assert first_info["stats"]["base_info"]["process_source"] == "Dify"
        assert first_info["stats"]["base_info"]["embedding_model"] == "text-embedding-3-small"
        # Check timestamp conversion (seconds to milliseconds)
        assert first_info["stats"]["base_info"]["creation_date"] == 1704067200000
        assert first_info["stats"]["base_info"]["update_date"] == 1704153600000

        # Verify HTTP request
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "https://dify.example.com/v1/datasets"
        assert call_args[1]["headers"]["Authorization"] == "Bearer test-api-key"

    def test_fetch_dify_datasets_empty_list(self):
        """Test fetching Dify datasets when the list is empty."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        # Mock httpx Client and response
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch('httpx.Client', return_value=mock_client):
            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        # Verify empty result
        assert result["count"] == 0
        assert result["indices"] == []
        assert result["indices_info"] == []
        assert result["pagination"]["embedding_available"] == False

    def test_fetch_dify_datasets_url_normalization(self):
        """Test that trailing slash is removed from API base URL."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        # Mock httpx Client and response
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch('httpx.Client', return_value=mock_client):
            fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com/",  # With trailing slash
                api_key="test-api-key"
            )

        # Verify URL is normalized (trailing slash removed)
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "https://dify.example.com/v1/datasets"

    def test_fetch_dify_datasets_invalid_api_base_empty_string(self):
        """Test ValueError when dify_api_base is empty string."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        with pytest.raises(ValueError) as exc_info:
            fetch_dify_datasets_impl(
                dify_api_base="",
                api_key="test-api-key"
            )

        assert "dify_api_base is required and must be a non-empty string" in str(exc_info.value)

    def test_fetch_dify_datasets_invalid_api_base_none(self):
        """Test ValueError when dify_api_base is None."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        with pytest.raises(ValueError) as exc_info:
            fetch_dify_datasets_impl(
                dify_api_base=None,
                api_key="test-api-key"
            )

        assert "dify_api_base is required and must be a non-empty string" in str(exc_info.value)

    def test_fetch_dify_datasets_invalid_api_base_non_string(self):
        """Test ValueError when dify_api_base is not a string."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        with pytest.raises(ValueError) as exc_info:
            fetch_dify_datasets_impl(
                dify_api_base=12345,
                api_key="test-api-key"
            )

        assert "dify_api_base is required and must be a non-empty string" in str(exc_info.value)

    def test_fetch_dify_datasets_invalid_api_key_empty_string(self):
        """Test ValueError when api_key is empty string."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        with pytest.raises(ValueError) as exc_info:
            fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key=""
            )

        assert "api_key is required and must be a non-empty string" in str(exc_info.value)

    def test_fetch_dify_datasets_invalid_api_key_none(self):
        """Test ValueError when api_key is None."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        with pytest.raises(ValueError) as exc_info:
            fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key=None
            )

        assert "api_key is required and must be a non-empty string" in str(exc_info.value)

    def test_fetch_dify_datasets_request_error(self):
        """Test handling of httpx.RequestError."""
        import httpx
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        # Mock httpx Client to raise RequestError
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.RequestError("Connection failed", request=MagicMock())

        with patch('httpx.Client', return_value=mock_client):
            with pytest.raises(Exception) as exc_info:
                fetch_dify_datasets_impl(
                    dify_api_base="https://dify.example.com",
                    api_key="test-api-key"
                )

            assert "Dify API request failed: Connection failed" in str(exc_info.value)

    def test_fetch_dify_datasets_http_status_error(self):
        """Test handling of httpx.HTTPStatusError."""
        import httpx
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        # Create a mock response for HTTPStatusError
        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.UNAUTHORIZED
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"error": "Invalid API key"}

        # Mock httpx Client to raise HTTPStatusError
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "Unauthorized",
            request=MagicMock(),
            response=mock_response
        )

        with patch('httpx.Client', return_value=mock_client):
            with pytest.raises(Exception) as exc_info:
                fetch_dify_datasets_impl(
                    dify_api_base="https://dify.example.com",
                    api_key="invalid-api-key"
                )

            assert "Dify API HTTP error: Unauthorized" in str(exc_info.value)

    def test_fetch_dify_datasets_json_decode_error(self):
        """Test handling of JSONDecodeError."""
        import httpx
        import json
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        # Mock httpx Client to return invalid JSON
        mock_response = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch('httpx.Client', return_value=mock_client):
            with pytest.raises(Exception) as exc_info:
                fetch_dify_datasets_impl(
                    dify_api_base="https://dify.example.com",
                    api_key="test-api-key"
                )

            assert "Failed to parse Dify API response" in str(exc_info.value)

    def test_fetch_dify_datasets_missing_data_key(self):
        """Test handling of missing 'data' key in response."""
        import httpx
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        # Mock httpx Client to return response without 'data' key
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "unexpected format"}  # Missing 'data' key
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch('httpx.Client', return_value=mock_client):
            with pytest.raises(Exception) as exc_info:
                fetch_dify_datasets_impl(
                    dify_api_base="https://dify.example.com",
                    api_key="test-api-key"
                )

            assert "Unexpected Dify API response format: missing key 'data'" in str(exc_info.value)

    def test_fetch_dify_datasets_skips_datasets_without_id(self):
        """Test that datasets without ID are skipped in the result."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        # Mock httpx Client and response with one dataset missing ID
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "ds_123",
                    "name": "Valid Dataset",
                    "document_count": 10,
                    "created_at": 1704067200,
                    "updated_at": 1704153600,
                    "embedding_available": True
                },
                {
                    # Missing 'id' field
                    "name": "Invalid Dataset",
                    "document_count": 5,
                    "created_at": 1703980800,
                    "updated_at": 1704326400,
                    "embedding_available": False
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch('httpx.Client', return_value=mock_client):
            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        # Verify only the valid dataset is included
        assert result["count"] == 1
        assert result["indices"] == ["ds_123"]
        assert len(result["indices_info"]) == 1
        assert result["indices_info"][0]["display_name"] == "Valid Dataset"

    def test_fetch_dify_datasets_all_fields_populated(self):
        """Test that all fields from Dify API are correctly mapped."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        # Mock httpx Client and response with all fields
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "ds_full",
                    "name": "Full Dataset",
                    "document_count": 42,
                    "chunk_count": 420,  # Note: this field exists in Dify response but service ignores it
                    "created_at": 1704067200,
                    "updated_at": 1704153600,
                    "embedding_available": True,
                    "embedding_model": "text-embedding-3-large",
                    "description": "A test dataset"
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch('httpx.Client', return_value=mock_client):
            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        # Verify all fields
        dataset_info = result["indices_info"][0]

        assert dataset_info["name"] == "ds_full"
        assert dataset_info["display_name"] == "Full Dataset"

        base_info = dataset_info["stats"]["base_info"]
        assert base_info["doc_count"] == 42
        assert base_info["chunk_count"] == 0  # Service doesn't map chunk_count
        assert base_info["store_size"] == ""  # Dify doesn't provide this
        assert base_info["process_source"] == "Dify"
        assert base_info["embedding_model"] == "text-embedding-3-large"
        assert base_info["embedding_dim"] == 0  # Dify doesn't provide this
        assert base_info["creation_date"] == 1704067200000
        assert base_info["update_date"] == 1704153600000

        search_perf = dataset_info["stats"]["search_performance"]
        assert search_perf["total_search_count"] == 0
        assert search_perf["hit_count"] == 0

    def test_fetch_dify_datasets_timestamp_conversion(self):
        """Test that timestamps are correctly converted from seconds to milliseconds."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        # Mock httpx Client and response with specific timestamps
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "ds_ts",
                    "name": "Timestamp Test",
                    "document_count": 1,
                    "created_at": 1000000000,  # 2001-09-09 01:46:40 UTC
                    "updated_at": 2000000000,  # 2033-05-18 03:33:20 UTC
                    "embedding_available": False
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch('httpx.Client', return_value=mock_client):
            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        # Verify timestamp conversion (multiply by 1000)
        dataset_info = result["indices_info"][0]
        assert dataset_info["stats"]["base_info"]["creation_date"] == 1000000000000
        assert dataset_info["stats"]["base_info"]["update_date"] == 2000000000000

    def test_fetch_dify_datasets_zero_timestamps(self):
        """Test handling of zero timestamps."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl

        # Mock httpx Client and response with zero timestamps
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "ds_zero",
                    "name": "Zero Timestamp",
                    "document_count": 0,
                    "created_at": 0,
                    "updated_at": 0,
                    "embedding_available": False
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch('httpx.Client', return_value=mock_client):
            result = fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        # Verify zero timestamps remain zero
        dataset_info = result["indices_info"][0]
        assert dataset_info["stats"]["base_info"]["creation_date"] == 0
        assert dataset_info["stats"]["base_info"]["update_date"] == 0

    def test_fetch_dify_datasets_uses_context_manager(self):
        """Test that httpx.Client is used as a context manager."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl
        from unittest.mock import MagicMock, patch

        # Mock httpx Client and response
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_response

        # Create mock context manager
        mock_client_class = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch('httpx.Client', mock_client_class):
            fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        # Verify context manager methods were called
        mock_client_class.return_value.__enter__.assert_called_once()
        mock_client_class.return_value.__exit__.assert_called_once()

    def test_fetch_dify_datasets_custom_timeout(self):
        """Test that httpx.Client uses correct timeout (30 seconds)."""
        from backend.services.knowledge_base.dify_service import fetch_dify_datasets_impl
        from unittest.mock import MagicMock, patch

        # Mock httpx Client and response
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_response

        # Create mock context manager
        mock_client_class = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch('httpx.Client', mock_client_class):
            fetch_dify_datasets_impl(
                dify_api_base="https://dify.example.com",
                api_key="test-api-key"
            )

        # Verify Client was called with timeout=30, verify=False
        mock_client_class.assert_called_once_with(timeout=30, verify=False)
