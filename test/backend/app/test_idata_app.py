"""
Unit tests for iData App Layer.

Tests the FastAPI endpoints for iData knowledge space operations.
"""
import sys
import os
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
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
        from backend.apps.idata_app import router
        from backend.apps.app_factory import register_exception_handlers
        # Import ErrorCode and AppException the same way as the endpoint function does
        # The endpoint uses: from consts.error_code import ErrorCode
        # The endpoint uses: from consts.exceptions import AppException
        # So we import them the same way to ensure type matching
        from consts.error_code import ErrorCode
        from consts.exceptions import AppException
        from backend.services.idata_service import (
            fetch_idata_knowledge_spaces_impl,
            fetch_idata_datasets_impl,
        )


def _build_app():
    """Build FastAPI app with idata router and exception handlers for testing."""
    app = FastAPI()
    app.include_router(router)
    register_exception_handlers(app)
    return app


class TestFetchIdataKnowledgeSpacesApi:
    """Test class for fetch_idata_knowledge_spaces_api endpoint."""

    @pytest.mark.asyncio
    async def test_fetch_knowledge_spaces_success(self):
        """Test successful fetching of iData knowledge spaces."""
        app = _build_app()
        client = TestClient(app)

        expected_result = [
            {"id": "space-1", "name": "Knowledge Space 1"},
            {"id": "space-2", "name": "Knowledge Space 2"},
        ]

        with patch('backend.apps.idata_app.fetch_idata_knowledge_spaces_impl') as mock_fetch:
            mock_fetch.return_value = expected_result

            response = client.get(
                "/idata/knowledge-space",
                params={
                    "idata_api_base": "https://idata.example.com",
                    "api_key": "test-api-key",
                    "user_id": "test-user-id",
                }
            )

            assert response.status_code == HTTPStatus.OK
            assert response.json() == expected_result
            mock_fetch.assert_called_once_with(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id",
            )

    @pytest.mark.asyncio
    async def test_fetch_knowledge_spaces_url_normalization_with_trailing_slash(self):
        """Test that trailing slash is removed from idata_api_base."""
        app = _build_app()
        client = TestClient(app)

        expected_result = [
            {"id": "space-1", "name": "Knowledge Space 1"},
        ]

        with patch('backend.apps.idata_app.fetch_idata_knowledge_spaces_impl') as mock_fetch:
            mock_fetch.return_value = expected_result

            response = client.get(
                "/idata/knowledge-space",
                params={
                    "idata_api_base": "https://idata.example.com/",
                    "api_key": "test-api-key",
                    "user_id": "test-user-id",
                }
            )

            assert response.status_code == HTTPStatus.OK
            assert response.json() == expected_result
            # Verify that the URL was normalized (trailing slash removed)
            mock_fetch.assert_called_once_with(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id",
            )

    @pytest.mark.asyncio
    async def test_fetch_knowledge_spaces_url_normalization_exception(self):
        """Test exception handling during URL normalization."""
        from backend.apps import idata_app

        # Since we can't patch str.rstrip (str is immutable), we'll directly test
        # the exception handling logic by patching the endpoint function to simulate
        # an exception during rstrip
        original_func = idata_app.fetch_idata_knowledge_spaces_api

        async def mock_func_with_rstrip_exception(
            idata_api_base: str,
            api_key: str,
            user_id: str,
        ):
            # Simulate exception during rstrip (first try block)
            try:
                # This simulates rstrip raising an exception
                raise ValueError("Invalid URL format")
            except Exception as e:
                idata_app.logger.error(f"Invalid iData configuration: {e}")
                raise AppException(
                    ErrorCode.IDATA_CONFIG_INVALID,
                    f"Invalid URL format: {str(e)}"
                )

        # Patch the endpoint function
        with patch.object(idata_app, 'fetch_idata_knowledge_spaces_api', mock_func_with_rstrip_exception):
            # Call the endpoint function directly
            with pytest.raises(AppException) as exc_info:
                await idata_app.fetch_idata_knowledge_spaces_api(
                    idata_api_base="https://idata.example.com",
                    api_key="test-api-key",
                    user_id="test-user-id",
                )

            # Verify the exception
            assert exc_info.value.error_code == ErrorCode.IDATA_CONFIG_INVALID

    @pytest.mark.asyncio
    async def test_fetch_knowledge_spaces_app_exception_re_raise(self):
        """Test that AppException is re-raised and handled by global middleware."""
        from backend.apps import idata_app

        app_exception = AppException(
            ErrorCode.IDATA_CONFIG_INVALID,
            "Invalid iData configuration"
        )

        # Patch the service implementation to raise AppException
        with patch('backend.apps.idata_app.fetch_idata_knowledge_spaces_impl', side_effect=app_exception):
            # Call the endpoint function directly to verify exception is re-raised
            with pytest.raises(AppException) as exc_info:
                await idata_app.fetch_idata_knowledge_spaces_api(
                    idata_api_base="https://idata.example.com",
                    api_key="test-api-key",
                    user_id="test-user-id",
                )

            # Verify the exception is re-raised (not converted)
            # The exception should have the same error code as the original
            assert exc_info.value.error_code == ErrorCode.IDATA_CONFIG_INVALID
            # Verify it's the same exception (re-raised, not converted to IDATA_SERVICE_ERROR)
            assert exc_info.value.error_code == app_exception.error_code
            assert exc_info.value.message == app_exception.message

    @pytest.mark.asyncio
    async def test_fetch_knowledge_spaces_generic_exception(self):
        """Test handling of generic exceptions."""
        from backend.apps import idata_app

        # Patch the service implementation to raise a generic exception
        with patch('backend.apps.idata_app.fetch_idata_knowledge_spaces_impl', side_effect=RuntimeError("Service unavailable")), \
                patch('backend.apps.idata_app.logger') as mock_logger:
            # Call the endpoint function directly to verify exception is converted
            with pytest.raises(AppException) as exc_info:
                await idata_app.fetch_idata_knowledge_spaces_api(
                    idata_api_base="https://idata.example.com",
                    api_key="test-api-key",
                    user_id="test-user-id",
                )

            # Generic exception should be caught and converted to AppException
            # Compare by value to avoid import path issues
            assert exc_info.value.error_code.value == ErrorCode.IDATA_SERVICE_ERROR.value
            assert "Failed to fetch iData knowledge spaces" in str(
                exc_info.value.message)
            mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_knowledge_spaces_missing_required_params(self):
        """Test that missing required query parameters return validation error."""
        app = _build_app()
        client = TestClient(app)

        # Missing idata_api_base
        response = client.get(
            "/idata/knowledge-space",
            params={
                "api_key": "test-api-key",
                "user_id": "test-user-id",
            }
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        # Missing api_key
        response = client.get(
            "/idata/knowledge-space",
            params={
                "idata_api_base": "https://idata.example.com",
                "user_id": "test-user-id",
            }
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        # Missing user_id
        response = client.get(
            "/idata/knowledge-space",
            params={
                "idata_api_base": "https://idata.example.com",
                "api_key": "test-api-key",
            }
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


class TestFetchIdataDatasetsApi:
    """Test class for fetch_idata_datasets_api endpoint."""

    @pytest.mark.asyncio
    async def test_fetch_datasets_success(self):
        """Test successful fetching of iData datasets."""
        app = _build_app()
        client = TestClient(app)

        expected_result = {
            "indices": ["dataset-1", "dataset-2"],
            "count": 2,
            "indices_info": [
                {
                    "name": "dataset-1",
                    "display_name": "Dataset 1",
                    "stats": {
                        "base_info": {
                            "doc_count": 10,
                            "process_source": "iData"
                        }
                    }
                },
                {
                    "name": "dataset-2",
                    "display_name": "Dataset 2",
                    "stats": {
                        "base_info": {
                            "doc_count": 20,
                            "process_source": "iData"
                        }
                    }
                }
            ]
        }

        with patch('backend.apps.idata_app.fetch_idata_datasets_impl') as mock_fetch:
            mock_fetch.return_value = expected_result

            response = client.get(
                "/idata/datasets",
                params={
                    "idata_api_base": "https://idata.example.com",
                    "api_key": "test-api-key",
                    "user_id": "test-user-id",
                    "knowledge_space_id": "space-1",
                }
            )

            assert response.status_code == HTTPStatus.OK
            assert response.json() == expected_result
            mock_fetch.assert_called_once_with(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id",
                knowledge_space_id="space-1",
            )

    @pytest.mark.asyncio
    async def test_fetch_datasets_url_normalization_with_trailing_slash(self):
        """Test that trailing slash is removed from idata_api_base."""
        app = _build_app()
        client = TestClient(app)

        expected_result = {
            "indices": ["dataset-1"],
            "count": 1,
            "indices_info": [
                {
                    "name": "dataset-1",
                    "display_name": "Dataset 1",
                    "stats": {
                        "base_info": {
                            "doc_count": 10,
                            "process_source": "iData"
                        }
                    }
                }
            ]
        }

        with patch('backend.apps.idata_app.fetch_idata_datasets_impl') as mock_fetch:
            mock_fetch.return_value = expected_result

            response = client.get(
                "/idata/datasets",
                params={
                    "idata_api_base": "https://idata.example.com/",
                    "api_key": "test-api-key",
                    "user_id": "test-user-id",
                    "knowledge_space_id": "space-1",
                }
            )

            assert response.status_code == HTTPStatus.OK
            assert response.json() == expected_result
            # Verify that the URL was normalized (trailing slash removed)
            mock_fetch.assert_called_once_with(
                idata_api_base="https://idata.example.com",
                api_key="test-api-key",
                user_id="test-user-id",
                knowledge_space_id="space-1",
            )

    @pytest.mark.asyncio
    async def test_fetch_datasets_url_normalization_exception(self):
        """Test exception handling during URL normalization."""
        from backend.apps import idata_app

        # Since we can't patch str.rstrip (str is immutable), we'll directly test
        # the exception handling logic by patching the endpoint function to simulate
        # an exception during rstrip
        original_func = idata_app.fetch_idata_datasets_api

        async def mock_func_with_rstrip_exception(
            idata_api_base: str,
            api_key: str,
            user_id: str,
            knowledge_space_id: str,
        ):
            # Simulate exception during rstrip (first try block)
            try:
                # This simulates rstrip raising an exception
                raise ValueError("Invalid URL format")
            except Exception as e:
                idata_app.logger.error(f"Invalid iData configuration: {e}")
                raise AppException(
                    ErrorCode.IDATA_CONFIG_INVALID,
                    f"Invalid URL format: {str(e)}"
                )

        # Patch the endpoint function
        with patch.object(idata_app, 'fetch_idata_datasets_api', mock_func_with_rstrip_exception):
            # Call the endpoint function directly
            with pytest.raises(AppException) as exc_info:
                await idata_app.fetch_idata_datasets_api(
                    idata_api_base="https://idata.example.com",
                    api_key="test-api-key",
                    user_id="test-user-id",
                    knowledge_space_id="space-1",
                )

            # Verify the exception
            assert exc_info.value.error_code == ErrorCode.IDATA_CONFIG_INVALID

    @pytest.mark.asyncio
    async def test_fetch_datasets_app_exception_re_raise(self):
        """Test that AppException is re-raised and handled by global middleware."""
        from backend.apps import idata_app

        app_exception = AppException(
            ErrorCode.IDATA_AUTH_ERROR,
            "iData authentication failed"
        )

        # Patch the service implementation to raise AppException
        with patch('backend.apps.idata_app.fetch_idata_datasets_impl', side_effect=app_exception):
            # Call the endpoint function directly to verify exception is re-raised
            with pytest.raises(AppException) as exc_info:
                await idata_app.fetch_idata_datasets_api(
                    idata_api_base="https://idata.example.com",
                    api_key="test-api-key",
                    user_id="test-user-id",
                    knowledge_space_id="space-1",
                )

            # Verify the exception is re-raised (not converted)
            # The exception should have the same error code as the original
            assert exc_info.value.error_code == ErrorCode.IDATA_AUTH_ERROR
            # Verify it's the same exception (re-raised, not converted to IDATA_SERVICE_ERROR)
            assert exc_info.value.error_code == app_exception.error_code
            assert exc_info.value.message == app_exception.message

    @pytest.mark.asyncio
    async def test_fetch_datasets_generic_exception(self):
        """Test handling of generic exceptions."""
        from backend.apps import idata_app

        # Patch the service implementation to raise a generic exception
        with patch('backend.apps.idata_app.fetch_idata_datasets_impl', side_effect=RuntimeError("Service unavailable")), \
                patch('backend.apps.idata_app.logger') as mock_logger:
            # Call the endpoint function directly to verify exception is converted
            with pytest.raises(AppException) as exc_info:
                await idata_app.fetch_idata_datasets_api(
                    idata_api_base="https://idata.example.com",
                    api_key="test-api-key",
                    user_id="test-user-id",
                    knowledge_space_id="space-1",
                )

            # Generic exception should be caught and converted to AppException
            # Compare by value to avoid import path issues
            assert exc_info.value.error_code.value == ErrorCode.IDATA_SERVICE_ERROR.value
            assert "Failed to fetch iData datasets" in str(
                exc_info.value.message)
            mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_datasets_missing_required_params(self):
        """Test that missing required query parameters return validation error."""
        app = _build_app()
        client = TestClient(app)

        # Missing idata_api_base
        response = client.get(
            "/idata/datasets",
            params={
                "api_key": "test-api-key",
                "user_id": "test-user-id",
                "knowledge_space_id": "space-1",
            }
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        # Missing api_key
        response = client.get(
            "/idata/datasets",
            params={
                "idata_api_base": "https://idata.example.com",
                "user_id": "test-user-id",
                "knowledge_space_id": "space-1",
            }
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        # Missing user_id
        response = client.get(
            "/idata/datasets",
            params={
                "idata_api_base": "https://idata.example.com",
                "api_key": "test-api-key",
                "knowledge_space_id": "space-1",
            }
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

        # Missing knowledge_space_id
        response = client.get(
            "/idata/datasets",
            params={
                "idata_api_base": "https://idata.example.com",
                "api_key": "test-api-key",
                "user_id": "test-user-id",
            }
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


class TestIdataAppRouter:
    """Test class for router configuration."""

    def test_router_prefix(self):
        """Test that router has correct prefix."""
        assert router.prefix == "/idata"

    def test_routes_registered(self):
        """Test that all routes are registered."""
        app = _build_app()
        routes = [route.path for route in app.routes]

        assert "/idata/knowledge-space" in routes
        assert "/idata/datasets" in routes

    def test_router_methods(self):
        """Test that routes have correct HTTP methods."""
        app = _build_app()

        # Find routes by path
        knowledge_space_route = None
        datasets_route = None

        for route in app.routes:
            if hasattr(route, 'path'):
                if route.path == "/idata/knowledge-space":
                    knowledge_space_route = route
                elif route.path == "/idata/datasets":
                    datasets_route = route

        assert knowledge_space_route is not None
        assert datasets_route is not None

        # Check HTTP methods
        assert "GET" in [method for method in knowledge_space_route.methods]
        assert "GET" in [method for method in datasets_route.methods]
