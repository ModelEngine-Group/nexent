import sys
import os
from unittest.mock import patch, MagicMock, AsyncMock, call

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from http import HTTPStatus

# Add backend directory to Python path for proper imports
# This ensures that backend modules can be imported correctly
project_root = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '../../../'))
backend_dir = os.path.join(project_root, 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Patch boto3 and other dependencies before importing anything from backend
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
minio_client_mock._ensure_bucket_exists = MagicMock()
minio_client_mock.client = MagicMock()

# Mock the entire MinIOStorageConfig class to avoid validation
minio_config_mock = MagicMock()
minio_config_mock.validate = MagicMock()

patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig',
      return_value=minio_config_mock).start()
patch('backend.database.client.MinioClient',
      return_value=minio_client_mock).start()
patch('database.client.MinioClient', return_value=minio_client_mock).start()
patch('backend.database.client.minio_client', minio_client_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Patch supabase to avoid import errors
supabase_mock = MagicMock()
sys.modules['supabase'] = supabase_mock

# Import backend modules after all patches are applied
# Use additional context manager to ensure MinioClient is properly mocked during import
with patch('backend.database.client.MinioClient', return_value=minio_client_mock), \
        patch('nexent.storage.minio_config.MinIOStorageConfig', return_value=minio_config_mock):
    from backend.apps.datamate_app import sync_datamate_knowledges, get_datamate_knowledge_base_files_endpoint, test_datamate_connection_endpoint as datamate_connection_endpoint


# Fixtures to replace setUp and tearDown
@pytest.fixture
def datamate_mocks():
    """Fixture to provide mocked dependencies for datamate app tests."""
    # Create fresh mocks for each test
    # Note: patch where the functions are imported (datamate_app), not where they're defined (service module)
    with patch('backend.apps.datamate_app.get_current_user_id') as mock_get_current_user_id, \
            patch('backend.apps.datamate_app.sync_datamate_knowledge_bases_and_create_records') as mock_sync_datamate, \
            patch('backend.apps.datamate_app.fetch_datamate_knowledge_base_file_list') as mock_fetch_files, \
            patch('backend.apps.datamate_app.check_datamate_connection') as mock_check_connection, \
            patch('backend.apps.datamate_app.logger') as mock_logger:

        # Set up async mocks for async functions
        mock_sync_datamate.return_value = AsyncMock()
        mock_fetch_files.return_value = AsyncMock()
        mock_check_connection.return_value = AsyncMock()

        yield {
            'get_current_user_id': mock_get_current_user_id,
            'sync_datamate': mock_sync_datamate,
            'fetch_files': mock_fetch_files,
            'check_connection': mock_check_connection,
            'logger': mock_logger
        }


class TestDataMateApp:
    """Test class for DataMate app endpoints."""

    @pytest.mark.asyncio
    async def test_sync_datamate_knowledges_success(self, datamate_mocks):
        """Test successful DataMate knowledge bases sync."""
        # Setup
        mock_auth_header = "Bearer test-token"
        expected_result = {
            "indices": ["kb1", "kb2"],
            "count": 2,
            "created_records": 5
        }

        # Mock user and tenant ID
        datamate_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id")

        # Mock service response
        datamate_mocks['sync_datamate'].return_value = expected_result

        # Create request with None datamate_url (default behavior)
        from backend.apps.datamate_app import SyncDatamateRequest
        request = SyncDatamateRequest(datamate_url=None)

        # Execute - call the endpoint with request body
        result = await sync_datamate_knowledges(
            authorization=mock_auth_header,
            request=request
        )

        # Assert
        assert result == expected_result
        datamate_mocks['get_current_user_id'].assert_called_once_with(
            mock_auth_header)
        datamate_mocks['sync_datamate'].assert_called_once_with(
            tenant_id="test_tenant_id",
            user_id="test_user_id",
            datamate_url=None
        )

    @pytest.mark.asyncio
    async def test_sync_datamate_knowledges_auth_error(self, datamate_mocks):
        """Test DataMate knowledge bases sync with authentication error."""
        # Setup
        mock_auth_header = "Bearer invalid-token"

        # Mock authentication failure
        datamate_mocks['get_current_user_id'].side_effect = Exception(
            "Invalid token")

        # Execute and Assert
        with pytest.raises(HTTPException) as exc_info:
            await sync_datamate_knowledges(authorization=mock_auth_header)

        assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "Error syncing DataMate knowledge bases and creating records" in str(
            exc_info.value.detail)
        # Error is logged in auth_utils, not here
        datamate_mocks['logger'].error.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_datamate_knowledges_service_error(self, datamate_mocks):
        """Test DataMate knowledge bases sync with service layer error."""
        # Setup
        mock_auth_header = "Bearer test-token"

        # Mock user and tenant ID
        datamate_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id")

        # Mock service exception
        service_error = RuntimeError("DataMate API unavailable")
        datamate_mocks['sync_datamate'].side_effect = service_error

        # Create request with None datamate_url
        from backend.apps.datamate_app import SyncDatamateRequest
        request = SyncDatamateRequest(datamate_url=None)

        # Execute and Assert
        with pytest.raises(HTTPException) as exc_info:
            await sync_datamate_knowledges(
                authorization=mock_auth_header,
                request=request
            )

        assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "Error syncing DataMate knowledge bases and creating records" in str(
            exc_info.value.detail)
        assert "DataMate API unavailable" in str(exc_info.value.detail)
        datamate_mocks['logger'].error.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_datamate_knowledge_base_files_success(self, datamate_mocks):
        """Test successful retrieval of DataMate knowledge base files."""
        # Setup
        mock_auth_header = "Bearer test-token"
        knowledge_base_id = "kb123"
        expected_result = {
            "status": "success",
            "files": [
                {"id": "file1", "name": "doc1.pdf"},
                {"id": "file2", "name": "doc2.txt"}
            ]
        }

        # Mock user and tenant ID
        datamate_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id")

        # Mock service response
        datamate_mocks['fetch_files'].return_value = expected_result

        # Execute
        result = await get_datamate_knowledge_base_files_endpoint(
            knowledge_base_id=knowledge_base_id,
            authorization=mock_auth_header
        )

        # Assert
        assert isinstance(result, JSONResponse)
        assert result.status_code == HTTPStatus.OK

        # Parse the JSON response body to verify content
        import json
        response_body = json.loads(result.body.decode())
        assert response_body == expected_result

        datamate_mocks['get_current_user_id'].assert_called_once_with(
            mock_auth_header)
        datamate_mocks['fetch_files'].assert_called_once_with(
            knowledge_base_id, "test_tenant_id")

    @pytest.mark.asyncio
    async def test_get_datamate_knowledge_base_files_auth_error(self, datamate_mocks):
        """Test DataMate knowledge base files retrieval with authentication error."""
        # Setup
        mock_auth_header = "Bearer invalid-token"
        knowledge_base_id = "kb123"

        # Mock authentication failure
        datamate_mocks['get_current_user_id'].side_effect = Exception(
            "Invalid token")

        # Execute and Assert
        with pytest.raises(HTTPException) as exc_info:
            await get_datamate_knowledge_base_files_endpoint(
                knowledge_base_id=knowledge_base_id,
                authorization=mock_auth_header
            )

        assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "Error fetching DataMate knowledge base files" in str(
            exc_info.value.detail)
        datamate_mocks['logger'].error.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_datamate_knowledge_base_files_service_error(self, datamate_mocks):
        """Test DataMate knowledge base files retrieval with service layer error."""
        # Setup
        mock_auth_header = "Bearer test-token"
        knowledge_base_id = "kb123"

        # Mock user and tenant ID
        datamate_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id")

        # Mock service exception
        service_error = RuntimeError("Knowledge base not found")
        datamate_mocks['fetch_files'].side_effect = service_error

        # Execute and Assert
        with pytest.raises(HTTPException) as exc_info:
            await get_datamate_knowledge_base_files_endpoint(
                knowledge_base_id=knowledge_base_id,
                authorization=mock_auth_header
            )

        assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "Error fetching DataMate knowledge base files" in str(
            exc_info.value.detail)
        assert "Knowledge base not found" in str(exc_info.value.detail)
        datamate_mocks['logger'].error.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_datamate_knowledge_base_files_empty_kb_id(self, datamate_mocks):
        """Test DataMate knowledge base files retrieval with empty knowledge base ID."""
        # Setup
        mock_auth_header = "Bearer test-token"
        knowledge_base_id = ""  # Empty ID

        # Mock user and tenant ID
        datamate_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id")

        # Mock service response
        expected_result = {
            "status": "success",
            "files": []
        }
        datamate_mocks['fetch_files'].return_value = expected_result

        # Execute
        result = await get_datamate_knowledge_base_files_endpoint(
            knowledge_base_id=knowledge_base_id,
            authorization=mock_auth_header
        )

        # Assert
        assert isinstance(result, JSONResponse)
        assert result.status_code == HTTPStatus.OK

        datamate_mocks['get_current_user_id'].assert_called_once_with(
            mock_auth_header)
        datamate_mocks['fetch_files'].assert_called_once_with(
            "", "test_tenant_id")

    @pytest.mark.asyncio
    async def test_sync_datamate_knowledges_none_auth_header(self, datamate_mocks):
        """Test DataMate knowledge bases sync with None authorization header."""
        # Setup
        mock_auth_header = None

        # Mock user and tenant ID for None auth (speed mode)
        datamate_mocks['get_current_user_id'].return_value = (
            "default_user", "default_tenant")

        # Mock service response
        expected_result = {
            "indices": [],
            "count": 0
        }
        datamate_mocks['sync_datamate'].return_value = expected_result

        # Create request with None datamate_url
        from backend.apps.datamate_app import SyncDatamateRequest
        request = SyncDatamateRequest(datamate_url=None)

        # Execute
        result = await sync_datamate_knowledges(
            authorization=mock_auth_header,
            request=request
        )

        # Assert
        assert result == expected_result
        datamate_mocks['get_current_user_id'].assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_get_datamate_knowledge_base_files_none_auth_header(self, datamate_mocks):
        """Test DataMate knowledge base files retrieval with None authorization header."""
        # Setup
        mock_auth_header = None
        knowledge_base_id = "kb123"

        # Mock user and tenant ID for None auth (speed mode)
        datamate_mocks['get_current_user_id'].return_value = (
            "default_user", "default_tenant")

        # Mock service response
        expected_result = {
            "status": "success",
            "files": [{"id": "file1", "name": "test.pdf"}]
        }
        datamate_mocks['fetch_files'].return_value = expected_result

        # Execute
        result = await get_datamate_knowledge_base_files_endpoint(
            knowledge_base_id=knowledge_base_id,
            authorization=mock_auth_header
        )

        # Assert
        assert isinstance(result, JSONResponse)
        assert result.status_code == HTTPStatus.OK

        datamate_mocks['get_current_user_id'].assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_sync_datamate_knowledges_custom_exception(self, datamate_mocks):
        """Test DataMate knowledge bases sync with custom service exception."""
        # Setup
        mock_auth_header = "Bearer test-token"

        # Mock user and tenant ID
        datamate_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id")

        # Mock custom service exception
        from backend.consts.exceptions import UnauthorizedError
        custom_error = UnauthorizedError("Custom auth error")
        datamate_mocks['sync_datamate'].side_effect = custom_error

        # Create request with None datamate_url
        from backend.apps.datamate_app import SyncDatamateRequest
        request = SyncDatamateRequest(datamate_url=None)

        # Execute and Assert
        with pytest.raises(HTTPException) as exc_info:
            await sync_datamate_knowledges(
                authorization=mock_auth_header,
                request=request
            )

        assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "Custom auth error" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_get_datamate_knowledge_base_files_custom_exception(self, datamate_mocks):
        """Test DataMate knowledge base files retrieval with custom service exception."""
        # Setup
        mock_auth_header = "Bearer test-token"
        knowledge_base_id = "kb123"

        # Mock user and tenant ID
        datamate_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id")

        # Mock custom service exception
        from backend.consts.exceptions import LimitExceededError
        custom_error = LimitExceededError("Rate limit exceeded")
        datamate_mocks['fetch_files'].side_effect = custom_error

        # Execute and Assert
        with pytest.raises(HTTPException) as exc_info:
            await get_datamate_knowledge_base_files_endpoint(
                knowledge_base_id=knowledge_base_id,
                authorization=mock_auth_header
            )

        assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "Rate limit exceeded" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_sync_datamate_knowledges_with_custom_datamate_url(self, datamate_mocks):
        """Test DataMate knowledge bases sync with custom datamate_url in request body."""
        # Setup
        mock_auth_header = "Bearer test-token"
        custom_datamate_url = "http://custom-datamate.example.com:8080"
        expected_result = {
            "indices": ["kb1", "kb2"],
            "count": 2,
            "created_records": 5
        }

        # Mock user and tenant ID
        datamate_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id")

        # Mock service response
        datamate_mocks['sync_datamate'].return_value = expected_result

        # Create request with custom datamate_url
        from backend.apps.datamate_app import SyncDatamateRequest
        request = SyncDatamateRequest(datamate_url=custom_datamate_url)

        # Execute - call the endpoint with request body
        result = await sync_datamate_knowledges(
            authorization=mock_auth_header,
            request=request
        )

        # Assert
        assert result == expected_result
        datamate_mocks['get_current_user_id'].assert_called_once_with(
            mock_auth_header)
        datamate_mocks['sync_datamate'].assert_called_once_with(
            tenant_id="test_tenant_id",
            user_id="test_user_id",
            datamate_url=custom_datamate_url
        )

    @pytest.mark.asyncio
    async def test_sync_datamate_kcknowledges_with_none_datamate_url(self, datamate_mocks):
        """Test DataMate knowledge bases sync with explicit None datamate_url."""
        # Setup
        mock_auth_header = "Bearer test-token"
        expected_result = {
            "indices": [],
            "count": 0
        }

        # Mock user and tenant ID
        datamate_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id")

        # Mock service response
        datamate_mocks['sync_datamate'].return_value = expected_result

        # Create request with explicit None datamate_url
        from backend.apps.datamate_app import SyncDatamateRequest
        request = SyncDatamateRequest(datamate_url=None)

        # Execute - call the endpoint with request body containing None
        result = await sync_datamate_knowledges(
            authorization=mock_auth_header,
            request=request
        )

        # Assert
        assert result == expected_result
        datamate_mocks['get_current_user_id'].assert_called_once_with(
            mock_auth_header)
        # When datamate_url is None, it should be passed as None to service
        datamate_mocks['sync_datamate'].assert_called_once_with(
            tenant_id="test_tenant_id",
            user_id="test_user_id",
            datamate_url=None
        )

    @pytest.mark.asyncio
    async def test_sync_datamate_knowledges_with_empty_datamate_url(self, datamate_mocks):
        """Test DataMate knowledge bases sync with empty string datamate_url."""
        # Setup
        mock_auth_header = "Bearer test-token"
        empty_datamate_url = ""
        expected_result = {
            "indices": [],
            "count": 0
        }

        # Mock user and tenant ID
        datamate_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id")

        # Mock service response - empty URL should be treated as no URL
        datamate_mocks['sync_datamate'].return_value = expected_result

        # Create request with empty string datamate_url
        from backend.apps.datamate_app import SyncDatamateRequest
        request = SyncDatamateRequest(datamate_url=empty_datamate_url)

        # Execute - call the endpoint with request body
        result = await sync_datamate_knowledges(
            authorization=mock_auth_header,
            request=request
        )

        # Assert
        assert result == expected_result
        datamate_mocks['sync_datamate'].assert_called_once_with(
            tenant_id="test_tenant_id",
            user_id="test_user_id",
            datamate_url=empty_datamate_url
        )

    @pytest.mark.asyncio
    async def test_sync_datamate_kcknowledges_with_https_datamate_url(self, datamate_mocks):
        """Test DataMate knowledge bases sync with HTTPS datamate_url."""
        # Setup
        mock_auth_header = "Bearer test-token"
        https_datamate_url = "https://secure-datamate.example.com"
        expected_result = {
            "indices": ["kb1"],
            "count": 1,
            "created_records": 1
        }

        # Mock user and tenant ID
        datamate_mocks['get_current_user_id'].return_value = (
            "test_user_id", "test_tenant_id")

        # Mock service response
        datamate_mocks['sync_datamate'].return_value = expected_result

        # Create request with HTTPS datamate_url
        from backend.apps.datamate_app import SyncDatamateRequest
        request = SyncDatamateRequest(datamate_url=https_datamate_url)

        # Execute - call the endpoint with request body
        result = await sync_datamate_knowledges(
            authorization=mock_auth_header,
            request=request
        )

        # Assert
        assert result == expected_result
        datamate_mocks['sync_datamate'].assert_called_once_with(
            tenant_id="test_tenant_id",
            user_id="test_user_id",
            datamate_url=https_datamate_url
        )


@pytest.mark.asyncio
async def test_datamate_connection_endpoint_success(datamate_mocks):
    """Test successful DataMate connection test."""
    # Setup
    mock_auth_header = "Bearer test-token"
    expected_result = JSONResponse(
        status_code=HTTPStatus.OK,
        content={"success": True, "message": "Connection successful"}
    )

    # Mock user and tenant ID
    datamate_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

    # Mock service response - connection successful
    datamate_mocks['check_connection'].return_value = (True, "")

    # Create request with None datamate_url (default behavior)
    from backend.apps.datamate_app import SyncDatamateRequest
    request = SyncDatamateRequest(datamate_url=None)

    # Execute
    result = await datamate_connection_endpoint(
        authorization=mock_auth_header,
        request=request
    )

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == HTTPStatus.OK

    # Parse the JSON response body to verify content
    import json
    response_body = json.loads(result.body.decode())
    assert response_body["success"] is True
    assert response_body["message"] == "Connection successful"

    datamate_mocks['get_current_user_id'].assert_called_once_with(
        mock_auth_header)
    datamate_mocks['check_connection'].assert_called_once_with(
        "test_tenant_id", None
    )


@pytest.mark.asyncio
async def test_datamate_connection_endpoint_connection_failed(datamate_mocks):
    """Test DataMate connection test when connection fails."""
    # Setup
    mock_auth_header = "Bearer test-token"

    # Mock user and tenant ID
    datamate_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

    # Mock service response - connection failed
    error_message = "Connection timeout"
    datamate_mocks['check_connection'].return_value = (False, error_message)

    # Create request with None datamate_url
    from backend.apps.datamate_app import SyncDatamateRequest
    request = SyncDatamateRequest(datamate_url=None)

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await datamate_connection_endpoint(
            authorization=mock_auth_header,
            request=request
        )

    assert exc_info.value.status_code == HTTPStatus.BAD_REQUEST
    assert f"Cannot connect to DataMate server: {error_message}" in str(
        exc_info.value.detail)

    datamate_mocks['get_current_user_id'].assert_called_once_with(
        mock_auth_header)
    datamate_mocks['check_connection'].assert_called_once_with(
        "test_tenant_id", None
    )


@pytest.mark.asyncio
async def test_datamate_connection_endpoint_auth_error(datamate_mocks):
    """Test DataMate connection test with authentication error."""
    # Setup
    mock_auth_header = "Bearer invalid-token"

    # Mock authentication failure
    datamate_mocks['get_current_user_id'].side_effect = Exception(
        "Invalid token")

    # Create request with None datamate_url
    from backend.apps.datamate_app import SyncDatamateRequest
    request = SyncDatamateRequest(datamate_url=None)

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await datamate_connection_endpoint(
            authorization=mock_auth_header,
            request=request
        )

    assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert "Error testing DataMate connection" in str(exc_info.value.detail)
    datamate_mocks['logger'].error.assert_not_called()


@pytest.mark.asyncio
async def test_datamate_connection_endpoint_service_error(datamate_mocks):
    """Test DataMate connection test with service layer error."""
    # Setup
    mock_auth_header = "Bearer test-token"

    # Mock user and tenant ID
    datamate_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

    # Mock service exception
    service_error = RuntimeError("DataMate API unavailable")
    datamate_mocks['check_connection'].side_effect = service_error

    # Create request with None datamate_url
    from backend.apps.datamate_app import SyncDatamateRequest
    request = SyncDatamateRequest(datamate_url=None)

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await datamate_connection_endpoint(
            authorization=mock_auth_header,
            request=request
        )

    assert exc_info.value.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert "Error testing DataMate connection" in str(exc_info.value.detail)
    assert "DataMate API unavailable" in str(exc_info.value.detail)
    datamate_mocks['logger'].error.assert_not_called()


@pytest.mark.asyncio
async def test_datamate_connection_endpoint_none_auth_header(datamate_mocks):
    """Test DataMate connection test with None authorization header."""
    # Setup
    mock_auth_header = None

    # Mock user and tenant ID for None auth (speed mode)
    datamate_mocks['get_current_user_id'].return_value = (
        "default_user", "default_tenant")

    # Mock service response - connection successful
    datamate_mocks['check_connection'].return_value = (True, "")

    # Create request with None datamate_url
    from backend.apps.datamate_app import SyncDatamateRequest
    request = SyncDatamateRequest(datamate_url=None)

    # Execute
    result = await datamate_connection_endpoint(
        authorization=mock_auth_header,
        request=request
    )

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == HTTPStatus.OK

    datamate_mocks['get_current_user_id'].assert_called_once_with(None)
    datamate_mocks['check_connection'].assert_called_once_with(
        "default_tenant", None
    )


@pytest.mark.asyncio
async def test_datamate_connection_endpoint_with_custom_url(datamate_mocks):
    """Test DataMate connection test with custom datamate_url in request body."""
    # Setup
    mock_auth_header = "Bearer test-token"
    custom_datamate_url = "http://custom-datamate.example.com:8080"

    # Mock user and tenant ID
    datamate_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

    # Mock service response - connection successful
    datamate_mocks['check_connection'].return_value = (True, "")

    # Create request with custom datamate_url
    from backend.apps.datamate_app import SyncDatamateRequest
    request = SyncDatamateRequest(datamate_url=custom_datamate_url)

    # Execute
    result = await datamate_connection_endpoint(
        authorization=mock_auth_header,
        request=request
    )

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == HTTPStatus.OK

    # Parse the JSON response body to verify content
    import json
    response_body = json.loads(result.body.decode())
    assert response_body["success"] is True

    datamate_mocks['get_current_user_id'].assert_called_once_with(
        mock_auth_header)
    datamate_mocks['check_connection'].assert_called_once_with(
        "test_tenant_id", custom_datamate_url
    )


@pytest.mark.asyncio
async def test_datamate_connection_endpoint_connection_disabled(datamate_mocks):
    """Test DataMate connection test when ModelEngine is disabled."""
    # Setup
    mock_auth_header = "Bearer test-token"

    # Mock user and tenant ID
    datamate_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

    # Mock service response - ModelEngine disabled
    datamate_mocks['check_connection'].return_value = (
        False, "ModelEngine is disabled")

    # Create request with None datamate_url
    from backend.apps.datamate_app import SyncDatamateRequest
    request = SyncDatamateRequest(datamate_url=None)

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await datamate_connection_endpoint(
            authorization=mock_auth_header,
            request=request
        )

    assert exc_info.value.status_code == HTTPStatus.BAD_REQUEST
    assert "Cannot connect to DataMate server: ModelEngine is disabled" in str(
        exc_info.value.detail)


@pytest.mark.asyncio
async def test_datamate_connection_endpoint_no_url_configured(datamate_mocks):
    """Test DataMate connection test when DataMate URL is not configured."""
    # Setup
    mock_auth_header = "Bearer test-token"

    # Mock user and tenant ID
    datamate_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

    # Mock service response - URL not configured
    datamate_mocks['check_connection'].return_value = (
        False, "DataMate URL not configured")

    # Create request with None datamate_url
    from backend.apps.datamate_app import SyncDatamateRequest
    request = SyncDatamateRequest(datamate_url=None)

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await datamate_connection_endpoint(
            authorization=mock_auth_header,
            request=request
        )

    assert exc_info.value.status_code == HTTPStatus.BAD_REQUEST
    assert "Cannot connect to DataMate server: DataMate URL not configured" in str(
        exc_info.value.detail)


@pytest.mark.asyncio
async def test_datamate_connection_endpoint_empty_request_body(datamate_mocks):
    """Test DataMate connection test with empty request body (None request)."""
    # Setup
    mock_auth_header = "Bearer test-token"

    # Mock user and tenant ID
    datamate_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

    # Mock service response - connection successful
    datamate_mocks['check_connection'].return_value = (True, "")

    # Execute with None request (empty body)
    result = await datamate_connection_endpoint(
        authorization=mock_auth_header,
        request=None
    )

    # Assert
    assert isinstance(result, JSONResponse)
    assert result.status_code == HTTPStatus.OK

    # Verify test_connection was called with None datamate_url when request is None
    datamate_mocks['check_connection'].assert_called_once_with(
        "test_tenant_id", None
    )


@pytest.mark.asyncio
async def test_datamate_connection_endpoint_empty_url_in_request(datamate_mocks):
    """Test DataMate connection test with empty string datamate_url in request."""
    # Setup
    mock_auth_header = "Bearer test-token"
    empty_datamate_url = ""

    # Mock user and tenant ID
    datamate_mocks['get_current_user_id'].return_value = (
        "test_user_id", "test_tenant_id")

    # Mock service response - URL not configured
    datamate_mocks['check_connection'].return_value = (
        False, "DataMate URL not configured")

    # Create request with empty string datamate_url
    from backend.apps.datamate_app import SyncDatamateRequest
    request = SyncDatamateRequest(datamate_url=empty_datamate_url)

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await datamate_connection_endpoint(
            authorization=mock_auth_header,
            request=request
        )

    assert exc_info.value.status_code == HTTPStatus.BAD_REQUEST

    # Verify test_connection was called with empty string datamate_url
    datamate_mocks['check_connection'].assert_called_once_with(
        "test_tenant_id", empty_datamate_url
    )
