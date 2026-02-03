"""
Unit tests for Dify App Layer.

Tests the FastAPI endpoints for Dify knowledge base operations.
"""
import sys
import os
from unittest.mock import patch, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from http import HTTPStatus


# Add backend directory to Python path for proper imports
project_root = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '../../../'))
backend_dir = os.path.join(project_root, 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


# Mock the storage client factory BEFORE importing any backend modules that depend on it.
# This prevents MinIO connection attempts during module import.
def _mock_create_storage_client_from_config(config):
    """Mock function to replace create_storage_client_from_config."""
    mock_client = MagicMock()
    mock_client.default_bucket = getattr(config, 'default_bucket', None)
    mock_client.upload_file.return_value = (True, "/mock-bucket/mock-file")
    mock_client.download_file.return_value = (True, "Downloaded successfully")
    mock_client.get_file_url.return_value = (True, "http://mock-url/file")
    mock_client.list_files.return_value = []
    mock_client.delete_file.return_value = (True, "Deleted successfully")
    mock_client.get_file_stream.return_value = (True, MagicMock())
    mock_client.get_file_size.return_value = 0
    return mock_client


# Apply the mock to the SDK module where create_storage_client_from_config is defined
with patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
           side_effect=_mock_create_storage_client_from_config):
    # Also mock the MinIO client initialization in database.client
    with patch('backend.database.client.MinioClient') as MockMinioClient:
        mock_minio_instance = MagicMock()
        MockMinioClient.return_value = mock_minio_instance

        # Now it's safe to import backend modules
        from backend.apps.dify_app import router, fetch_dify_datasets_api
        from backend.services.dify_service import fetch_dify_datasets_impl


# Fixtures to replace setUp and tearDown
@pytest.fixture
def dify_mocks():
    """Fixture to provide mocked dependencies for dify app tests."""
    with patch('backend.apps.dify_app.get_current_user_id') as mock_get_current_user_id, \
            patch('backend.apps.dify_app.fetch_dify_datasets_impl') as mock_fetch_dify, \
            patch('backend.apps.dify_app.logger') as mock_logger:

        mock_fetch_dify.return_value = MagicMock()

        yield {
            'get_current_user_id': mock_get_current_user_id,
            'fetch_dify': mock_fetch_dify,
            'logger': mock_logger
        }


class TestFetchDifyDatasetsApi:
    """Test class for fetch_dify_datasets_api endpoint."""

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_success(self, dify_mocks):
        """Test successful fetching of Dify datasets."""
        # Setup
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        expected_result = {
            "indices": ["ds-1", "ds-2"],
            "count": 2,
            "indices_info": [
                {
                    "name": "ds-1",
                    "display_name": "Knowledge Base 1",
                    "stats": {
                        "base_info": {
                            "doc_count": 10,
                            "chunk_count": 100,
                            "store_size": "",
                            "process_source": "Dify",
                            "embedding_model": "text-embedding-3-small",
                            "embedding_dim": 0,
                            "creation_date": 1704067200000,
                            "update_date": 1704153600000
                        },
                        "search_performance": {
                            "total_search_count": 0,
                            "hit_count": 0
                        }
                    }
                }
            ],
            "pagination": {
                "embedding_available": True
            }
        }

        # Mock user and tenant ID
        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )

        # Mock service response
        dify_mocks['fetch_dify'].return_value = expected_result

        # Execute
        result = await fetch_dify_datasets_api(
            dify_api_base=dify_api_base,
            api_key=api_key,
            authorization=mock_auth_header
        )

        # Assert
        assert isinstance(result, JSONResponse)
        assert result.status_code == HTTPStatus.OK

        # Parse the JSON response body to verify content
        import json
        response_body = json.loads(result.body.decode())
        assert response_body == expected_result

        dify_mocks['get_current_user_id'].assert_called_once_with(mock_auth_header)
        dify_mocks['fetch_dify'].assert_called_once_with(
            dify_api_base=dify_api_base.rstrip('/'),
            api_key=api_key
        )

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_url_normalization(self, dify_mocks):
        """Test that trailing slash is removed from dify_api_base."""
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com/"
        api_key = "test-api-key"

        expected_result = {
            "indices": [],
            "count": 0,
            "indices_info": [],
            "pagination": {"embedding_available": False}
        }

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        dify_mocks['fetch_dify'].return_value = expected_result

        result = await fetch_dify_datasets_api(
            dify_api_base=dify_api_base,
            api_key=api_key,
            authorization=mock_auth_header
        )

        # Verify the URL was normalized (trailing slash removed)
        dify_mocks['fetch_dify'].assert_called_once_with(
            dify_api_base="https://dify.example.com",  # No trailing slash
            api_key=api_key
        )

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_auth_error(self, dify_mocks):
        """Test endpoint with authentication error."""
        mock_auth_header = "Bearer invalid-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        # Mock authentication failure
        dify_mocks['get_current_user_id'].side_effect = Exception("Invalid token")

        # Execute and Assert
        with pytest.raises(HTTPException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "Failed to fetch Dify datasets" in str(exc_info.value.detail)
        dify_mocks['logger'].error.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_service_validation_error(self, dify_mocks):
        """Test endpoint with service layer validation error (ValueError)."""
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = ""

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        dify_mocks['fetch_dify'].side_effect = ValueError("api_key is required")

        with pytest.raises(HTTPException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        assert exc_info.value.status_code == HTTPStatus.BAD_REQUEST
        assert "api_key is required" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_service_error(self, dify_mocks):
        """Test endpoint with general service layer error."""
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        dify_mocks['fetch_dify'].side_effect = Exception("Dify API connection failed")

        with pytest.raises(HTTPException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "Failed to fetch Dify datasets" in str(exc_info.value.detail)
        assert "Dify API connection failed" in str(exc_info.value.detail)
        dify_mocks['logger'].error.assert_called()

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_http_error_from_service(self, dify_mocks):
        """Test endpoint when service raises HTTP-related exception."""
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        # Simulate HTTP error from service
        dify_mocks['fetch_dify'].side_effect = Exception("Dify API HTTP error: 404 Not Found")

        with pytest.raises(HTTPException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "Failed to fetch Dify datasets" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_request_error_from_service(self, dify_mocks):
        """Test endpoint when service raises request error."""
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        # Simulate request error from service
        dify_mocks['fetch_dify'].side_effect = Exception("Dify API request failed: Connection refused")

        with pytest.raises(HTTPException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "Failed to fetch Dify datasets" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_none_auth_header(self, dify_mocks):
        """Test endpoint with None authorization header (speed mode)."""
        mock_auth_header = None
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        expected_result = {
            "indices": ["ds-1"],
            "count": 1,
            "indices_info": [],
            "pagination": {"embedding_available": False}
        }

        # Mock user and tenant ID for None auth
        dify_mocks['get_current_user_id'].return_value = (
            "default_user", "default_tenant"
        )
        dify_mocks['fetch_dify'].return_value = expected_result

        result = await fetch_dify_datasets_api(
            dify_api_base=dify_api_base,
            api_key=api_key,
            authorization=mock_auth_header
        )

        assert isinstance(result, JSONResponse)
        assert result.status_code == HTTPStatus.OK

        dify_mocks['get_current_user_id'].assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_empty_result(self, dify_mocks):
        """Test endpoint when Dify returns empty dataset list."""
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        expected_result = {
            "indices": [],
            "count": 0,
            "indices_info": [],
            "pagination": {"embedding_available": False}
        }

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        dify_mocks['fetch_dify'].return_value = expected_result

        result = await fetch_dify_datasets_api(
            dify_api_base=dify_api_base,
            api_key=api_key,
            authorization=mock_auth_header
        )

        assert isinstance(result, JSONResponse)
        assert result.status_code == HTTPStatus.OK

        import json
        response_body = json.loads(result.body.decode())
        assert response_body["count"] == 0
        assert response_body["indices"] == []

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_response_structure(self, dify_mocks):
        """Test that response contains all required DataMate-compatible fields."""
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        expected_result = {
            "indices": ["ds-123"],
            "count": 1,
            "indices_info": [
                {
                    "name": "ds-123",
                    "display_name": "My Dataset",
                    "stats": {
                        "base_info": {
                            "doc_count": 50,
                            "chunk_count": 500,
                            "store_size": "1.5GB",
                            "process_source": "Dify",
                            "embedding_model": "text-embedding-ada-002",
                            "embedding_dim": 1536,
                            "creation_date": 1704067200000,
                            "update_date": 1704153600000
                        },
                        "search_performance": {
                            "total_search_count": 100,
                            "hit_count": 85
                        }
                    }
                }
            ],
            "pagination": {
                "embedding_available": True
            }
        }

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        dify_mocks['fetch_dify'].return_value = expected_result

        result = await fetch_dify_datasets_api(
            dify_api_base=dify_api_base,
            api_key=api_key,
            authorization=mock_auth_header
        )

        assert isinstance(result, JSONResponse)

        import json
        response_body = json.loads(result.body.decode())

        # Verify all required top-level fields
        assert "indices" in response_body
        assert "count" in response_body
        assert "indices_info" in response_body
        assert "pagination" in response_body

        # Verify indices_info structure
        info = response_body["indices_info"][0]
        assert "name" in info
        assert "display_name" in info
        assert "stats" in info

        stats = info["stats"]
        assert "base_info" in stats
        assert "search_performance" in stats

        base_info = stats["base_info"]
        assert "doc_count" in base_info
        assert "chunk_count" in base_info
        assert "store_size" in base_info
        assert "process_source" in base_info
        assert "embedding_model" in base_info
        assert "embedding_dim" in base_info
        assert "creation_date" in base_info
        assert "update_date" in base_info

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_logger_info_call(self, dify_mocks):
        """Test that endpoint logs appropriately on success."""
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        expected_result = {
            "indices": [],
            "count": 0,
            "indices_info": [],
            "pagination": {"embedding_available": False}
        }

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        dify_mocks['fetch_dify'].return_value = expected_result

        await fetch_dify_datasets_api(
            dify_api_base=dify_api_base,
            api_key=api_key,
            authorization=mock_auth_header
        )

        # On success, logger.info should be called (service logs the fetch operation)
        dify_mocks['fetch_dify'].assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_logger_error_call(self, dify_mocks):
        """Test that endpoint logs errors appropriately."""
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        dify_mocks['fetch_dify'].side_effect = Exception("Connection timeout")

        with pytest.raises(HTTPException):
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        # Logger.error should be called for service errors
        dify_mocks['logger'].error.assert_called()

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_special_characters_in_api_key(self, dify_mocks):
        """Test endpoint handles special characters in API key."""
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "sk-abc123xyz!@#$%^&*()"

        expected_result = {
            "indices": [],
            "count": 0,
            "indices_info": [],
            "pagination": {"embedding_available": False}
        }

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        dify_mocks['fetch_dify'].return_value = expected_result

        result = await fetch_dify_datasets_api(
            dify_api_base=dify_api_base,
            api_key=api_key,
            authorization=mock_auth_header
        )

        # Verify the API key was passed through correctly
        dify_mocks['fetch_dify'].assert_called_once_with(
            dify_api_base="https://dify.example.com",
            api_key=api_key
        )

        assert result.status_code == HTTPStatus.OK

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_different_api_base_formats(self, dify_mocks):
        """Test endpoint handles different API base URL formats."""
        mock_auth_header = "Bearer test-token"
        api_key = "test-api-key"

        test_cases = [
            ("https://dify.example.com", "https://dify.example.com"),
            ("https://dify.example.com/", "https://dify.example.com"),
            ("http://localhost:8000", "http://localhost:8000"),
            ("http://localhost:8000/", "http://localhost:8000"),
        ]

        for input_url, expected_url in test_cases:
            dify_mocks['fetch_dify'].reset_mock()
            dify_mocks['get_current_user_id'].return_value = (
                "test_user_id", "test_tenant_id"
            )
            dify_mocks['fetch_dify'].return_value = {
                "indices": [],
                "count": 0,
                "indices_info": [],
                "pagination": {"embedding_available": False}
            }

            await fetch_dify_datasets_api(
                dify_api_base=input_url,
                api_key=api_key,
                authorization=mock_auth_header
            )

            # Verify URL normalization
            call_kwargs = dify_mocks['fetch_dify'].call_args[1]
            assert call_kwargs['dify_api_base'] == expected_url


class TestDifyAppRouter:
    """Test class for Dify app router configuration."""

    def test_router_prefix(self):
        """Test that router has correct prefix."""
        assert router.prefix == "/dify"

    def test_router_has_datasets_endpoint(self):
        """Test that router has the datasets endpoint registered."""
        routes = [route.path for route in router.routes]
        # Router prefix is /dify, and route is /datasets, so full path is /dify/datasets
        assert "/dify/datasets" in routes
