"""
Unit tests for Dify App Layer (backend/apps/knowledge_base/dify_app.py).

Tests the API endpoints for Dify knowledge base operations.
"""
import sys
import os
from unittest.mock import patch, MagicMock, AsyncMock

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


@pytest.fixture
def dify_app_mocks():
    """Fixture to provide mocked dependencies for Dify app tests."""
    with patch('backend.apps.knowledge_base.dify_app.get_current_user_id') as mock_get_current_user_id, \
            patch('backend.apps.knowledge_base.dify_app.fetch_dify_datasets_impl') as mock_fetch_datasets, \
            patch('backend.apps.knowledge_base.dify_app.logger') as mock_logger:

        # Set up async mock for the service function
        mock_fetch_datasets.return_value = AsyncMock()

        yield {
            'get_current_user_id': mock_get_current_user_id,
            'fetch_datasets': mock_fetch_datasets,
            'logger': mock_logger
        }


class TestDifyApp:
    """Test class for Dify app endpoints."""

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_success(self, dify_app_mocks):
        """Test successful fetching of Dify datasets."""
        # Setup
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"
        expected_result = {
            "indices": ["dataset_1", "dataset_2"],
            "count": 2,
            "indices_info": [
                {
                    "name": "dataset_1",
                    "display_name": "Knowledge Base 1",
                    "stats": {
                        "base_info": {
                            "doc_count": 10,
                            "chunk_count": 100,
                            "store_size": "",
                            "process_source": "Dify",
                            "embedding_model": "text-embedding-3-small",
                            "embedding_dim": 1536,
                            "creation_date": 1704067200000,
                            "update_date": 1704153600000
                        },
                        "search_performance": {
                            "total_search_count": 50,
                            "hit_count": 45
                        }
                    }
                }
            ],
            "pagination": {
                "embedding_available": True
            }
        }

        # Mock user and tenant ID
        dify_app_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )

        # Mock service response
        dify_app_mocks['fetch_datasets'].return_value = expected_result

        # Import and execute endpoint
        from backend.apps.knowledge_base.dify_app import fetch_dify_datasets_api
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

        dify_app_mocks['get_current_user_id'].assert_called_once_with(
            mock_auth_header)
        dify_app_mocks['fetch_datasets'].assert_called_once_with(
            dify_api_base=dify_api_base,
            api_key=api_key
        )

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_auth_error(self, dify_app_mocks):
        """Test fetching Dify datasets with authentication error."""
        # Setup
        mock_auth_header = "Bearer invalid-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        # Mock authentication failure
        dify_app_mocks['get_current_user_id'].side_effect = Exception(
            "Invalid token")

        # Import and execute
        from backend.apps.knowledge_base.dify_app import fetch_dify_datasets_api

        # Execute and Assert
        with pytest.raises(HTTPException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "Error fetching Dify datasets" in str(
            exc_info.value.detail)
        dify_app_mocks['logger'].error.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_value_error(self, dify_app_mocks):
        """Test fetching Dify datasets with invalid parameters (ValueError)."""
        # Setup
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = ""  # Empty API key should cause ValueError

        # Mock user and tenant ID
        dify_app_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )

        # Mock service ValueError
        dify_app_mocks['fetch_datasets'].side_effect = ValueError(
            "api_key is required and must be a non-empty string")

        # Import and execute
        from backend.apps.knowledge_base.dify_app import fetch_dify_datasets_api

        # Execute and Assert
        with pytest.raises(HTTPException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        assert exc_info.value.status_code == HTTPStatus.BAD_REQUEST
        assert "api_key is required and must be a non-empty string" in str(
            exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_service_error(self, dify_app_mocks):
        """Test fetching Dify datasets with service layer error."""
        # Setup
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"

        # Mock user and tenant ID
        dify_app_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )

        # Mock service exception
        service_error = Exception("Dify API request failed: Connection timeout")
        dify_app_mocks['fetch_datasets'].side_effect = service_error

        # Import and execute
        from backend.apps.knowledge_base.dify_app import fetch_dify_datasets_api

        # Execute and Assert
        with pytest.raises(HTTPException) as exc_info:
            await fetch_dify_datasets_api(
                dify_api_base=dify_api_base,
                api_key=api_key,
                authorization=mock_auth_header
            )

        assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "Error fetching Dify datasets" in str(
            exc_info.value.detail)
        assert "Connection timeout" in str(exc_info.value.detail)
        dify_app_mocks['logger'].error.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_none_auth_header(self, dify_app_mocks):
        """Test fetching Dify datasets with None authorization header."""
        # Setup
        mock_auth_header = None
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"
        expected_result = {
            "indices": [],
            "count": 0,
            "indices_info": [],
            "pagination": {
                "embedding_available": False
            }
        }

        # Mock user and tenant ID for None auth (speed mode)
        dify_app_mocks['get_current_user_id'].return_value = (
            "default_user", "default_tenant"
        )

        # Mock service response
        dify_app_mocks['fetch_datasets'].return_value = expected_result

        # Import and execute
        from backend.apps.knowledge_base.dify_app import fetch_dify_datasets_api
        result = await fetch_dify_datasets_api(
            dify_api_base=dify_api_base,
            api_key=api_key,
            authorization=mock_auth_header
        )

        # Assert
        assert isinstance(result, JSONResponse)
        assert result.status_code == HTTPStatus.OK

        # Parse the JSON response body
        import json
        response_body = json.loads(result.body.decode())
        assert response_body == expected_result

        dify_app_mocks['get_current_user_id'].assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_empty_result(self, dify_app_mocks):
        """Test fetching Dify datasets when no datasets exist."""
        # Setup
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"
        expected_result = {
            "indices": [],
            "count": 0,
            "indices_info": [],
            "pagination": {
                "embedding_available": False
            }
        }

        # Mock user and tenant ID
        dify_app_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )

        # Mock service response with empty result
        dify_app_mocks['fetch_datasets'].return_value = expected_result

        # Import and execute
        from backend.apps.knowledge_base.dify_app import fetch_dify_datasets_api
        result = await fetch_dify_datasets_api(
            dify_api_base=dify_api_base,
            api_key=api_key,
            authorization=mock_auth_header
        )

        # Assert
        assert isinstance(result, JSONResponse)
        assert result.status_code == HTTPStatus.OK

        import json
        response_body = json.loads(result.body.decode())
        assert response_body["count"] == 0
        assert response_body["indices"] == []

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_multiple_datasets(self, dify_app_mocks):
        """Test fetching Dify datasets with multiple knowledge bases."""
        # Setup
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com"
        api_key = "test-api-key"
        expected_result = {
            "indices": ["ds_1", "ds_2", "ds_3"],
            "count": 3,
            "indices_info": [
                {
                    "name": "ds_1",
                    "display_name": "Knowledge Base 1",
                    "stats": {
                        "base_info": {
                            "doc_count": 5,
                            "chunk_count": 50,
                            "store_size": "1MB",
                            "process_source": "Dify",
                            "embedding_model": "text-embedding-3-small",
                            "embedding_dim": 1536,
                            "creation_date": 1704067200000,
                            "update_date": 1704153600000
                        },
                        "search_performance": {
                            "total_search_count": 10,
                            "hit_count": 8
                        }
                    }
                },
                {
                    "name": "ds_2",
                    "display_name": "Knowledge Base 2",
                    "stats": {
                        "base_info": {
                            "doc_count": 20,
                            "chunk_count": 200,
                            "store_size": "5MB",
                            "process_source": "Dify",
                            "embedding_model": "text-embedding-3-large",
                            "embedding_dim": 3072,
                            "creation_date": 1703980800000,
                            "update_date": 1704326400000
                        },
                        "search_performance": {
                            "total_search_count": 100,
                            "hit_count": 95
                        }
                    }
                },
                {
                    "name": "ds_3",
                    "display_name": "Knowledge Base 3",
                    "stats": {
                        "base_info": {
                            "doc_count": 0,
                            "chunk_count": 0,
                            "store_size": "0B",
                            "process_source": "Dify",
                            "embedding_model": "",
                            "embedding_dim": 0,
                            "creation_date": 0,
                            "update_date": 0
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
        dify_app_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )

        # Mock service response
        dify_app_mocks['fetch_datasets'].return_value = expected_result

        # Import and execute
        from backend.apps.knowledge_base.dify_app import fetch_dify_datasets_api
        result = await fetch_dify_datasets_api(
            dify_api_base=dify_api_base,
            api_key=api_key,
            authorization=mock_auth_header
        )

        # Assert
        assert isinstance(result, JSONResponse)
        assert result.status_code == HTTPStatus.OK

        import json
        response_body = json.loads(result.body.decode())
        assert response_body["count"] == 3
        assert len(response_body["indices"]) == 3
        assert len(response_body["indices_info"]) == 3

    @pytest.mark.asyncio
    async def test_fetch_dify_datasets_url_normalization(self, dify_app_mocks):
        """Test that API base URL is properly normalized (trailing slash removed)."""
        # Setup
        mock_auth_header = "Bearer test-token"
        dify_api_base = "https://dify.example.com/"  # With trailing slash
        api_key = "test-api-key"
        expected_result = {
            "indices": [],
            "count": 0,
            "indices_info": [],
            "pagination": {
                "embedding_available": False
            }
        }

        # Mock user and tenant ID
        dify_app_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id"
        )

        # Mock service response
        dify_app_mocks['fetch_datasets'].return_value = expected_result

        # Import and execute
        from backend.apps.knowledge_base.dify_app import fetch_dify_datasets_api
        result = await fetch_dify_datasets_api(
            dify_api_base=dify_api_base,
            api_key=api_key,
            authorization=mock_auth_header
        )

        # Assert - service should receive URL without trailing slash
        dify_app_mocks['fetch_datasets'].assert_called_once_with(
            dify_api_base="https://dify.example.com",  # Trailing slash removed
            api_key=api_key
        )
