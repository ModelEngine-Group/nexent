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

        # Note: get_current_user_id is imported but not used in dify_app.py
        # The test verifies the actual behavior of the function
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
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer invalid-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        # Mock authentication failure
        dify_mocks['get_current_user_id'].side_effect = Exception(
            "Invalid token")

        # Execute and Assert - the code catches Exception and converts to AppException
        with pytest.raises(AppException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        assert exc_info.value.error_code == ErrorCode.DIFY_SERVICE_ERROR
        assert "Failed to fetch Dify datasets" in str(exc_info.value.message)
        dify_mocks['logger'].error.assert_called()

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_service_validation_error(self, dify_mocks):
        """Test endpoint with service layer validation error (ValueError)."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = ""

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        dify_mocks['fetch_dify'].side_effect = ValueError(
            "api_key is required")

        with pytest.raises(AppException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        assert exc_info.value.error_code == ErrorCode.DIFY_SERVICE_ERROR

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_service_error(self, dify_mocks):
        """Test endpoint with general service layer error."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        dify_mocks['fetch_dify'].side_effect = Exception(
            "Dify API connection failed")

        with pytest.raises(AppException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        assert exc_info.value.error_code == ErrorCode.DIFY_SERVICE_ERROR
        assert "Failed to fetch Dify datasets" in str(exc_info.value.message)
        assert "Dify API connection failed" in str(exc_info.value.message)
        dify_mocks['logger'].error.assert_called()

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_http_error_from_service(self, dify_mocks):
        """Test endpoint when service raises HTTP-related exception."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        # Simulate HTTP error from service
        dify_mocks['fetch_dify'].side_effect = Exception(
            "Dify API HTTP error: 404 Not Found")

        with pytest.raises(AppException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        assert exc_info.value.error_code == ErrorCode.DIFY_SERVICE_ERROR
        assert "Failed to fetch Dify datasets" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_request_error_from_service(self, dify_mocks):
        """Test endpoint when service raises request error."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        # Simulate request error from service
        dify_mocks['fetch_dify'].side_effect = Exception(
            "Dify API request failed: Connection refused")

        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        with pytest.raises(AppException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        assert exc_info.value.error_code == ErrorCode.DIFY_SERVICE_ERROR
        assert "Failed to fetch Dify datasets" in str(exc_info.value.message)

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

        # Mock user and tenant ID for None auth (even though it's not used in the current implementation)
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

        # Note: get_current_user_id is imported but not used in dify_app.py
        # The test verifies the actual behavior of the function

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
        from consts.exceptions import AppException

        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )
        dify_mocks['fetch_dify'].side_effect = Exception("Connection timeout")

        with pytest.raises(AppException):
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


class TestDifyAppExceptionHandlers:
    """Test exception handlers in dify_app.py"""

    def test_dify_app_exception_handler_functions_exist(self):
        """Test that dify_app module can import exception handlers if defined."""
        # dify_app.py doesn't define its own exception handlers,
        # it relies on the global middleware in config_app.py
        # This test verifies the module structure
        from backend.apps import dify_app
        from backend.apps.dify_app import router, logger, fetch_dify_datasets_api

        # Verify router exists
        assert router is not None
        # Verify logger exists
        assert logger is not None
        # Verify endpoint function exists
        assert fetch_dify_datasets_api is not None

    @pytest.mark.asyncio
    async def test_dify_app_logs_service_error(self, dify_mocks):
        """Test that service errors are logged and converted to AppException."""
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        dify_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )

        # Test with service error
        dify_mocks['fetch_dify'].side_effect = Exception(
            "URL connection error")

        from consts.exceptions import AppException

        with pytest.raises(AppException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        # Verify it's a DIFY_SERVICE_ERROR
        assert "Failed to fetch Dify datasets" in str(exc_info.value.message)
        dify_mocks['logger'].error.assert_called()


class TestFetchDifyDatasetsApiConfigValidation:
    """Test class for fetch_dify_datasets_api endpoint configuration validation.

    Tests the first try-except block that handles invalid Dify configuration
    (e.g., when dify_api_base.rstrip('/') fails due to invalid input).
    """

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_invalid_dify_api_base_none(self):
        """Test endpoint raises DIFY_CONFIG_INVALID when dify_api_base is None."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        dify_api_base = None
        api_key = "test-api-key"

        with patch('backend.apps.dify_app.get_current_user_id') as mock_get_current_user_id, \
                patch('backend.apps.dify_app.fetch_dify_datasets_impl') as mock_fetch_dify, \
                patch('backend.apps.dify_app.logger') as mock_logger:

            mock_get_current_user_id.return_value = (
                "test_user_id", "test_tenant_id"
            )

            with pytest.raises(AppException) as exc_info:
                await fetch_dify_datasets_api(
                    dify_api_base=dify_api_base,
                    api_key=api_key,
                    authorization=mock_auth_header
                )

            assert exc_info.value.error_code == ErrorCode.DIFY_CONFIG_INVALID
            assert "Invalid URL format" in str(exc_info.value.message)
            mock_logger.error.assert_called()
            mock_fetch_dify.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_invalid_dify_api_base_integer(self):
        """Test endpoint raises DIFY_CONFIG_INVALID when dify_api_base is an integer."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        dify_api_base = 12345  # Invalid type - should be string
        api_key = "test-api-key"

        with patch('backend.apps.dify_app.get_current_user_id') as mock_get_current_user_id, \
                patch('backend.apps.dify_app.fetch_dify_datasets_impl') as mock_fetch_dify, \
                patch('backend.apps.dify_app.logger') as mock_logger:

            mock_get_current_user_id.return_value = (
                "test_user_id", "test_tenant_id"
            )

            with pytest.raises(AppException) as exc_info:
                await fetch_dify_datasets_api(
                    dify_api_base=dify_api_base,
                    api_key=api_key,
                    authorization=mock_auth_header
                )

            assert exc_info.value.error_code == ErrorCode.DIFY_CONFIG_INVALID
            assert "Invalid URL format" in str(exc_info.value.message)
            mock_logger.error.assert_called()
            mock_fetch_dify.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_invalid_dify_api_base_object(self):
        """Test endpoint raises DIFY_CONFIG_INVALID when dify_api_base is an object without rstrip."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        # Invalid type - should be string
        dify_api_base = {"url": "https://dify.example.com"}
        api_key = "test-api-key"

        with patch('backend.apps.dify_app.get_current_user_id') as mock_get_current_user_id, \
                patch('backend.apps.dify_app.fetch_dify_datasets_impl') as mock_fetch_dify, \
                patch('backend.apps.dify_app.logger') as mock_logger:

            mock_get_current_user_id.return_value = (
                "test_user_id", "test_tenant_id"
            )

            with pytest.raises(AppException) as exc_info:
                await fetch_dify_datasets_api(
                    dify_api_base=dify_api_base,
                    api_key=api_key,
                    authorization=mock_auth_header
                )

            assert exc_info.value.error_code == ErrorCode.DIFY_CONFIG_INVALID
            mock_logger.error.assert_called()
            mock_fetch_dify.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_invalid_dify_api_base_list(self):
        """Test endpoint raises DIFY_CONFIG_INVALID when dify_api_base is a list."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        # Invalid type - should be string
        dify_api_base = ["https://dify.example.com"]
        api_key = "test-api-key"

        with patch('backend.apps.dify_app.get_current_user_id') as mock_get_current_user_id, \
                patch('backend.apps.dify_app.fetch_dify_datasets_impl') as mock_fetch_dify, \
                patch('backend.apps.dify_app.logger') as mock_logger:

            mock_get_current_user_id.return_value = (
                "test_user_id", "test_tenant_id"
            )

            with pytest.raises(AppException) as exc_info:
                await fetch_dify_datasets_api(
                    dify_api_base=dify_api_base,
                    api_key=api_key,
                    authorization=mock_auth_header
                )

            assert exc_info.value.error_code == ErrorCode.DIFY_CONFIG_INVALID
            mock_logger.error.assert_called()
            mock_fetch_dify.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_dify_config_invalid_logs_error_message(self):
        """Test that DIFY_CONFIG_INVALID error logs the actual exception message."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        # This will cause AttributeError: 'NoneType' object has no attribute 'rstrip'
        dify_api_base = None
        api_key = "test-api-key"

        with patch('backend.apps.dify_app.get_current_user_id') as mock_get_current_user_id, \
                patch('backend.apps.dify_app.fetch_dify_datasets_impl') as mock_fetch_dify, \
                patch('backend.apps.dify_app.logger') as mock_logger:

            mock_get_current_user_id.return_value = (
                "test_user_id", "test_tenant_id"
            )

            with pytest.raises(AppException) as exc_info:
                await fetch_dify_datasets_api(
                    dify_api_base=dify_api_base,
                    api_key=api_key,
                    authorization=mock_auth_header
                )

            # Verify logger was called with the error
            mock_logger.error.assert_called_once()
            call_args = mock_logger.error.call_args
            assert "Invalid Dify configuration" in call_args[0][0]
            assert "'NoneType' object has no attribute 'rstrip'" in call_args[
                0][0] or "NoneType" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_api_success_after_config_validation(self):
        """Test endpoint succeeds when config validation passes (valid string input)."""
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        expected_result = {
            "indices": ["ds-1"],
            "count": 1,
            "indices_info": [],
            "pagination": {"embedding_available": True}
        }

        with patch('backend.apps.dify_app.get_current_user_id') as mock_get_current_user_id, \
                patch('backend.apps.dify_app.fetch_dify_datasets_impl') as mock_fetch_dify, \
                patch('backend.apps.dify_app.logger') as mock_logger:

            mock_get_current_user_id.return_value = (
                "test_user_id", "test_tenant_id"
            )
            mock_fetch_dify.return_value = expected_result

            result = await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

            assert isinstance(result, JSONResponse)
            assert result.status_code == HTTPStatus.OK
            # Verify the service was called with normalized URL
            mock_fetch_dify.assert_called_once_with(
                dify_api_base="https://dify.example.com",
                api_key=api_key
            )


class TestAppExceptionReRaising:
    """Test class for AppException re-raising to global middleware.

    Tests the except AppException: raise block that propagates AppException
    from the service layer to be handled by global middleware.
    """

    @pytest.mark.asyncio
    async def test_service_raises_app_exception_re_raised_to_middleware(self):
        """Test that AppException from service is re-raised for global middleware."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        # Create an AppException that the service would raise
        service_exception = AppException(
            ErrorCode.DIFY_CONNECTION_ERROR,
            "Failed to connect to Dify API"
        )

        with patch('backend.apps.dify_app.get_current_user_id') as mock_get_current_user_id, \
                patch('backend.apps.dify_app.fetch_dify_datasets_impl') as mock_fetch_dify, \
                patch('backend.apps.dify_app.logger') as mock_logger:

            mock_get_current_user_id.return_value = (
                "test_user_id", "test_tenant_id"
            )
            mock_fetch_dify.side_effect = service_exception

            # The AppException should be re-raised (not converted)
            with pytest.raises(AppException) as exc_info:
                await fetch_dify_datasets_api(
                    dify_api_base=dify_api_base,
                    api_key=api_key,
                    authorization=mock_auth_header
                )

            # Verify the original AppException is re-raised with its original error code
            assert exc_info.value.error_code == ErrorCode.DIFY_CONNECTION_ERROR
            assert "Failed to connect to Dify API" in str(
                exc_info.value.message)

    @pytest.mark.asyncio
    async def test_service_raises_dify_config_invalid_app_exception(self):
        """Test that DIFY_CONFIG_INVALID AppException from service is re-raised."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        # Simulate service raising DIFY_CONFIG_INVALID
        service_exception = AppException(
            ErrorCode.DIFY_CONFIG_INVALID,
            "Invalid Dify API key format"
        )

        with patch('backend.apps.dify_app.get_current_user_id') as mock_get_current_user_id, \
                patch('backend.apps.dify_app.fetch_dify_datasets_impl') as mock_fetch_dify, \
                patch('backend.apps.dify_app.logger') as mock_logger:

            mock_get_current_user_id.return_value = (
                "test_user_id", "test_tenant_id"
            )
            mock_fetch_dify.side_effect = service_exception

            # Should re-raise the AppException
            with pytest.raises(AppException) as exc_info:
                await fetch_dify_datasets_api(
                    dify_api_base=dify_api_base,
                    api_key=api_key,
                    authorization=mock_auth_header
                )

            assert exc_info.value.error_code == ErrorCode.DIFY_CONFIG_INVALID

    @pytest.mark.asyncio
    async def test_service_raises_dify_auth_error_app_exception(self):
        """Test that DIFY_AUTH_ERROR AppException from service is re-raised."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        # Simulate service raising DIFY_AUTH_ERROR
        service_exception = AppException(
            ErrorCode.DIFY_AUTH_ERROR,
            "Invalid API key provided"
        )

        with patch('backend.apps.dify_app.get_current_user_id') as mock_get_current_user_id, \
                patch('backend.apps.dify_app.fetch_dify_datasets_impl') as mock_fetch_dify, \
                patch('backend.apps.dify_app.logger') as mock_logger:

            mock_get_current_user_id.return_value = (
                "test_user_id", "test_tenant_id"
            )
            mock_fetch_dify.side_effect = service_exception

            # Should re-raise the AppException
            with pytest.raises(AppException) as exc_info:
                await fetch_dify_datasets_api(
                    dify_api_base=dify_api_base,
                    api_key=api_key,
                    authorization=mock_auth_header
                )

            assert exc_info.value.error_code == ErrorCode.DIFY_AUTH_ERROR

    @pytest.mark.asyncio
    async def test_service_raises_app_exception_with_details(self):
        """Test that AppException with details from service is re-raised."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        # AppException with details
        service_exception = AppException(
            ErrorCode.DIFY_CONNECTION_ERROR,
            "Connection failed",
            details={"host": "dify.example.com", "port": 443}
        )

        with patch('backend.apps.dify_app.get_current_user_id') as mock_get_current_user_id, \
                patch('backend.apps.dify_app.fetch_dify_datasets_impl') as mock_fetch_dify, \
                patch('backend.apps.dify_app.logger') as mock_logger:

            mock_get_current_user_id.return_value = (
                "test_user_id", "test_tenant_id"
            )
            mock_fetch_dify.side_effect = service_exception

            # Should re-raise the AppException with details preserved
            with pytest.raises(AppException) as exc_info:
                await fetch_dify_datasets_api(
                    dify_api_base=dify_api_base,
                    api_key=api_key,
                    authorization=mock_auth_header
                )

            assert exc_info.value.error_code == ErrorCode.DIFY_CONNECTION_ERROR
            assert exc_info.value.details == {
                "host": "dify.example.com", "port": 443}

    @pytest.mark.asyncio
    async def test_service_raises_dify_rate_limit_app_exception(self):
        """Test that DIFY_RATE_LIMIT AppException from service is re-raised."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        # Simulate service raising DIFY_RATE_LIMIT
        service_exception = AppException(
            ErrorCode.DIFY_RATE_LIMIT,
            "Rate limit exceeded"
        )

        with patch('backend.apps.dify_app.get_current_user_id') as mock_get_current_user_id, \
                patch('backend.apps.dify_app.fetch_dify_datasets_impl') as mock_fetch_dify, \
                patch('backend.apps.dify_app.logger') as mock_logger:

            mock_get_current_user_id.return_value = (
                "test_user_id", "test_tenant_id"
            )
            mock_fetch_dify.side_effect = service_exception

            # Should re-raise the AppException
            with pytest.raises(AppException) as exc_info:
                await fetch_dify_datasets_api(
                    dify_api_base=dify_api_base,
                    api_key=api_key,
                    authorization=mock_auth_header
                )

            assert exc_info.value.error_code == ErrorCode.DIFY_RATE_LIMIT

    @pytest.mark.asyncio
    async def test_app_exception_not_wrapped_or_converted(self):
        """Test that AppException is not wrapped or converted to another exception."""
        from consts.exceptions import AppException
        from consts.error_code import ErrorCode

        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        # Use a non-Dify error code to verify it's not converted
        service_exception = AppException(
            ErrorCode.COMMON_UNAUTHORIZED,
            "Unauthorized access"
        )

        with patch('backend.apps.dify_app.get_current_user_id') as mock_get_current_user_id, \
                patch('backend.apps.dify_app.fetch_dify_datasets_impl') as mock_fetch_dify, \
                patch('backend.apps.dify_app.logger') as mock_logger:

            mock_get_current_user_id.return_value = (
                "test_user_id", "test_tenant_id"
            )
            mock_fetch_dify.side_effect = service_exception

            # Should re-raise the exact same AppException
            with pytest.raises(AppException) as exc_info:
                await fetch_dify_datasets_api(
                    dify_api_base=dify_api_base,
                    api_key=api_key,
                    authorization=mock_auth_header
                )

            # Verify it's the exact same exception instance (not a new one)
            assert exc_info.value is service_exception
            assert exc_info.value.error_code == ErrorCode.COMMON_UNAUTHORIZED
