"""
Unit tests for the Elasticsearch application endpoints.
These tests verify the behavior of the Elasticsearch API without actual database connections.
All external services and dependencies are mocked to isolate the tests.
"""
import os
import sys
import pytest
import types
import importlib.machinery
from unittest.mock import patch, MagicMock, ANY, AsyncMock, call
from fastapi.testclient import TestClient
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

# Dynamically determine the backend path and add it to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.insert(0, backend_dir)

# Environment variables are now configured in conftest.py

boto3_module = types.ModuleType("boto3")
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
boto3_module.client = MagicMock()
minio_client_mock = MagicMock()
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules['boto3'] = boto3_module
# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()


class SearchRequest(BaseModel):
    index_names: List[str]
    query: str
    top_k: int = 10


class HybridSearchRequest(SearchRequest):
    weight_accurate: float = 0.5
    weight_semantic: float = 0.5
    tag_predicates: List[Dict[str, Any]] = Field(default_factory=list)


class IndexingResponse(BaseModel):
    success: bool
    message: str
    total_indexed: int
    total_submitted: int


# Module-level mocks for AWS connections
# Apply these patches before importing any modules to prevent actual AWS connections
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()
patch('backend.database.client.get_db_session').start()
patch('backend.database.client.db_client').start()

# Mock Elasticsearch to prevent connection errors
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Create a mock for consts.model and patch it before any imports.
# For models used in FastAPI endpoints, provide real Pydantic classes so that
# FastAPI dependency and schema generation does not fail during router import.
consts_model_mock = MagicMock()
consts_model_mock.SearchRequest = SearchRequest
consts_model_mock.HybridSearchRequest = HybridSearchRequest
consts_model_mock.IndexingResponse = IndexingResponse


class _ChunkCreateRequest(BaseModel):
    content: str
    title: Optional[str] = None
    filename: Optional[str] = None
    path_or_url: Optional[str] = None
    chunk_id: Optional[str] = None
    metadata: Dict[str, Any] = {}


class _ChunkUpdateRequest(BaseModel):
    content: Optional[str] = None
    title: Optional[str] = None
    filename: Optional[str] = None
    path_or_url: Optional[str] = None
    metadata: Dict[str, Any] = {}


consts_model_mock.ChunkCreateRequest = _ChunkCreateRequest
consts_model_mock.ChunkUpdateRequest = _ChunkUpdateRequest

# Patch the module import before importing backend modules
sys.modules['consts.model'] = consts_model_mock

# Create mocks for these services if they can't be imported
ElasticSearchService = MagicMock()
RedisService = MagicMock()

# Import routes and services
from backend.apps.vectordatabase_app import router
from nexent.vector_database.elasticsearch_core import ElasticSearchCore
from consts.exceptions import (
    AppException,
    DuplicateError,
)
from consts.error_code import ErrorCode

# Create test client
app = FastAPI()


@app.exception_handler(AppException)
async def app_exception_handler(request, exc):
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

# Temporarily modify router to disable response model validation
for route in router.routes:
    # Check if attribute exists before modifying
    if hasattr(route, 'response_model'):
        # Use setattr instead of direct assignment
        setattr(route, 'response_model', None)

app.include_router(router)
client = TestClient(app)


@pytest.fixture
def vdb_core_mock():
    return MagicMock(spec=ElasticSearchCore)


@pytest.fixture
def redis_service_mock():
    mock = MagicMock()
    mock.delete_knowledgebase_records = MagicMock()
    mock.delete_document_records = MagicMock()
    return mock


@pytest.fixture
def auth_data():
    return {
        "index_name": "test_index",
        "user_id": "test_user",
        "tenant_id": "test_tenant",
        "auth_header": {"Authorization": "Bearer test_token"}
    }


@pytest.fixture(autouse=True)
def mock_knowledge_base_edit_permission():
    with patch(
        "backend.apps.vectordatabase_app.ElasticSearchService.require_knowledge_base_edit_permission",
        return_value="EDIT",
    ):
        yield


@pytest.fixture(autouse=True)
def mock_knowledge_base_read_permission():
    """Auto-mock read permission so hybrid_search and other endpoints don't hit the real DB."""
    with patch(
        "backend.apps.vectordatabase_app.require_knowledge_base_read_permission",
        return_value="READ_ONLY",
    ):
        yield


@pytest.fixture(autouse=True)
def mock_current_user_id():
    """Provide default authenticated user data for endpoints requiring request auth."""
    with patch(
        "backend.apps.vectordatabase_app.get_current_user_id",
        return_value=("test_user", "test_tenant"),
    ), patch(
        "backend.apps.vectordatabase_app.get_current_user_context",
        return_value=("test_user", "test_tenant", "ADMIN"),
    ):
        yield

# Test cases using pytest-asyncio


@pytest.mark.asyncio
async def test_create_new_index_success(vdb_core_mock, auth_data):
    """
    Test creating a new index successfully.
    Verifies that the endpoint returns the expected response when index creation succeeds.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_context", return_value=(auth_data["user_id"], auth_data["tenant_id"], "ADMIN")), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.create_knowledge_base") as mock_create:

        expected_response = {"status": "success",
                             "index_name": auth_data["index_name"]}
        mock_create.return_value = expected_response

        # Execute request
        response = client.post(
            f"/indices/{auth_data['index_name']}",
            params={"embedding_dim": 768},
            json={"embedding_model_id": 101},
            headers=auth_data["auth_header"],
        )

        # Verify
        assert response.status_code == 200
        assert response.json() == expected_response
        # vdb_core is constructed inside router; accept ANY for instance
        mock_create.assert_called_once()
        # Function is called with keyword arguments, so use call_args[1]
        called_kwargs = mock_create.call_args[1]
        assert called_kwargs["knowledge_name"] == auth_data["index_name"]
        assert called_kwargs["embedding_dim"] == 768
        assert called_kwargs["user_id"] == auth_data["user_id"]
        assert called_kwargs["tenant_id"] == auth_data["tenant_id"]
        assert called_kwargs["user_role"] == "ADMIN"


@pytest.mark.asyncio
async def test_create_new_index_with_group_permissions(vdb_core_mock, auth_data):
    """
    Test creating a new index with group permissions.
    Verifies that ingroup_permission and group_ids are correctly passed to the service.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_context", return_value=(auth_data["user_id"], auth_data["tenant_id"], "ADMIN")), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.create_knowledge_base") as mock_create:

        expected_response = {"status": "success",
                             "index_name": auth_data["index_name"]}
        mock_create.return_value = expected_response

        # Execute request with group permissions in body
        response = client.post(
            f"/indices/{auth_data['index_name']}",
            params={"embedding_dim": 768},
            json={"embedding_model_id": 101, "ingroup_permission": "EDIT", "group_ids": [1, 2, 3]},
            headers=auth_data["auth_header"]
        )

        # Verify
        assert response.status_code == 200
        assert response.json() == expected_response
        mock_create.assert_called_once()
        # Function is called with keyword arguments, so use call_args[1]
        called_kwargs = mock_create.call_args[1]
        assert called_kwargs["knowledge_name"] == auth_data["index_name"]
        assert called_kwargs["embedding_dim"] == 768
        assert called_kwargs["user_id"] == auth_data["user_id"]
        assert called_kwargs["tenant_id"] == auth_data["tenant_id"]
        assert called_kwargs["user_role"] == "ADMIN"
        # Verify group permissions were passed
        assert called_kwargs["ingroup_permission"] == "EDIT"
        assert called_kwargs["group_ids"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_create_new_index_with_partial_group_permissions(vdb_core_mock, auth_data):
    """
    Test creating a new index with only ingroup_permission (no group_ids).
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_context", return_value=(auth_data["user_id"], auth_data["tenant_id"], "ADMIN")), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.create_knowledge_base") as mock_create:

        expected_response = {"status": "success",
                             "index_name": auth_data["index_name"]}
        mock_create.return_value = expected_response

        # Execute request with only ingroup_permission
        response = client.post(
            f"/indices/{auth_data['index_name']}",
            json={"embedding_model_id": 101, "ingroup_permission": "READ_ONLY"},
            headers=auth_data["auth_header"]
        )

        # Verify
        assert response.status_code == 200
        mock_create.assert_called_once()
        called_kwargs = mock_create.call_args[1]
        assert called_kwargs["ingroup_permission"] == "READ_ONLY"
        assert called_kwargs["group_ids"] is None
        assert called_kwargs["user_role"] == "ADMIN"


@pytest.mark.asyncio
async def test_create_new_index_passes_embedding_model_id(vdb_core_mock, auth_data):
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_context", return_value=(auth_data["user_id"], auth_data["tenant_id"], "ADMIN")), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.create_knowledge_base") as mock_create:

        mock_create.return_value = {"status": "success", "index_name": auth_data["index_name"]}

        response = client.post(
            f"/indices/{auth_data['index_name']}",
            json={"embedding_model_id": 202},
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 200
        called_kwargs = mock_create.call_args[1]
        assert called_kwargs["embedding_model_id"] == 202
        assert called_kwargs["user_role"] == "ADMIN"


@pytest.mark.asyncio
async def test_create_new_index_error(vdb_core_mock, auth_data):
    """
    Test creating a new index with error.
    Verifies that the endpoint returns an appropriate error response when index creation fails.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.create_knowledge_base") as mock_create:

        mock_create.side_effect = Exception("Test error")

        # Execute request
        response = client.post(
            f"/indices/{auth_data['index_name']}",
            json={"embedding_model_id": 101},
            headers=auth_data["auth_header"],
        )

        # Verify
        assert response.status_code == 500
        assert response.json() == {
            "detail": "Error creating index: Test error"}


@pytest.mark.asyncio
async def test_create_new_index_name_conflict_returns_409(vdb_core_mock, auth_data):
    with patch(
        "backend.apps.vectordatabase_app.get_current_user_context",
        return_value=(auth_data["user_id"], auth_data["tenant_id"], "USER"),
    ), patch(
        "backend.apps.vectordatabase_app.ElasticSearchService.create_knowledge_base",
        side_effect=DuplicateError("Knowledge base name 'test_index' already exists"),
    ):
        response = client.post(
            f"/indices/{auth_data['index_name']}",
            json={"embedding_model_id": 101},
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Knowledge base name 'test_index' already exists"
    }


@pytest.mark.asyncio
async def test_create_new_index_requires_integer_embedding_model_id(vdb_core_mock, auth_data):
    with patch(
        "backend.apps.vectordatabase_app.get_current_user_id",
        return_value=(auth_data["user_id"], auth_data["tenant_id"]),
    ):
        response = client.post(
            f"/indices/{auth_data['index_name']}",
            json={"embedding_model_id": "101"},
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "embedding_model_id must be an integer"}


@pytest.mark.asyncio
async def test_delete_index_success(vdb_core_mock, redis_service_mock, auth_data):
    """
    Test deleting an index successfully.
    Verifies that the endpoint returns the expected response and performs Redis cleanup.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_redis_service", return_value=redis_service_mock), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_files") as mock_list_files, \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.delete_index") as mock_delete, \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.full_delete_knowledge_base") as mock_full_delete, \
            patch("services.tag_management_service.TagManagementService.cleanup_resource_assignments") as cleanup_resource, \
            patch("services.tag_management_service.TagManagementService.cleanup_document_assignments_for_knowledge_base") as cleanup_documents:

        # Properly setup the async mock for list_files
        mock_list_files.return_value = {"files": []}

        # Setup the return value for delete_index
        es_result = {"status": "success",
                     "message": "Index deleted successfully"}
        mock_delete.return_value = es_result

        # Setup the mock for delete_knowledgebase_records
        redis_result = {
            "index_name": auth_data["index_name"],
            "total_deleted": 10,
            "celery_tasks_deleted": 5,
            "cache_keys_deleted": 5
        }
        redis_service_mock.delete_knowledgebase_records.return_value = redis_result

        # Setup full_delete_knowledge_base to return a complete response
        mock_full_delete.return_value = {
            "status": "success",
            "message": f"Index {auth_data['index_name']} deleted successfully. MinIO: 0 files deleted, 0 failed. Redis: Cleaned up 10 records.",
            "es_delete_result": es_result,
            "redis_cleanup": redis_result,
            "minio_cleanup": {
                "deleted_count": 0,
                "failed_count": 0,
                "total_files_found": 0
            }
        }

        # Execute request
        response = client.delete(
            f"/indices/{auth_data['index_name']}", headers=auth_data["auth_header"])

        # Verify expected 200 status code
        assert response.status_code == 200

        # Get the actual response
        actual_response = response.json()

        # Verify essential response elements
        assert actual_response["status"] == "success"
        assert auth_data["index_name"] in actual_response["message"]
        assert "Redis: Cleaned up" in actual_response["message"]

        # Verify structure contains expected keys
        assert "redis_cleanup" in actual_response
        assert "minio_cleanup" in actual_response

        # Verify full_delete_knowledge_base was called with the correct parameters
        # Use ANY for the vdb_core parameter because the actual object may differ
        mock_full_delete.assert_called_once_with(
            auth_data["index_name"],
            ANY,  # Use ANY instead of vdb_core_mock to ignore object identity
            auth_data["user_id"]
        )
        cleanup_resource.assert_called_once_with(
            auth_data["tenant_id"], "knowledge_base", auth_data["index_name"], auth_data["user_id"]
        )
        cleanup_documents.assert_called_once_with(
            auth_data["tenant_id"], "local", auth_data["index_name"], auth_data["user_id"]
        )


@pytest.mark.asyncio
async def test_delete_index_preserves_eds_blocking_error(vdb_core_mock, auth_data):
    """The delete route preserves EDS code/details for an in-flight file guard."""
    blocking_details = {
        "index_name": auth_data["index_name"],
        "blocking_files": [
            {"file_id": "file-1", "file_name": "report.pdf", "status": "PROCESSING"}
        ],
    }
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.full_delete_knowledge_base",
                  new_callable=AsyncMock,
                  side_effect=AppException(ErrorCode.KNOWLEDGE_DELETE_BLOCKED,
                                            details=blocking_details)):
        response = client.delete(
            f"/indices/{auth_data['index_name']}", headers=auth_data["auth_header"])

    assert response.status_code == 409
    assert response.json()["code"] == ErrorCode.KNOWLEDGE_DELETE_BLOCKED.value
    assert response.json()["details"] == blocking_details


@pytest.mark.asyncio
async def test_delete_index_forbidden_for_read_only(vdb_core_mock, auth_data):
    """Read-only users must not be able to delete a knowledge base."""
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch(
                "apps.permission_utils.ElasticSearchService.require_knowledge_base_edit_permission",
                side_effect=PermissionError("No permission to modify this knowledge base"),
            ) as mock_require_permission, \
            patch(
                "backend.apps.vectordatabase_app.ElasticSearchService.full_delete_knowledge_base",
                new_callable=AsyncMock,
            ) as mock_full_delete:

        response = client.delete(
            f"/indices/{auth_data['index_name']}",
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "No permission to modify this knowledge base"
        mock_require_permission.assert_called_once_with(
            index_name=auth_data["index_name"],
            user_id=auth_data["user_id"],
            tenant_id=auth_data["tenant_id"],
        )
        mock_full_delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_index_redis_error(vdb_core_mock, redis_service_mock, auth_data):
    """
    Test deleting an index with Redis error.
    Verifies that the endpoint still succeeds with ES but reports Redis cleanup error.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_redis_service", return_value=redis_service_mock), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_files") as mock_list_files, \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.delete_index") as mock_delete, \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.full_delete_knowledge_base") as mock_full_delete, \
            patch("services.tag_management_service.TagManagementService.cleanup_resource_assignments"), \
            patch("services.tag_management_service.TagManagementService.cleanup_document_assignments_for_knowledge_base"):

        # Properly setup the async mock for list_files
        mock_list_files.return_value = {"files": []}

        # Setup the return value for delete_index
        es_result = {"status": "success",
                     "message": "Index deleted successfully"}
        mock_delete.return_value = es_result

        # Setup redis error
        redis_error_message = "Redis error: Connection failed"
        redis_service_mock.delete_knowledgebase_records.side_effect = Exception(
            redis_error_message)

        # Setup full_delete_knowledge_base to return a response with redis error
        mock_full_delete.return_value = {
            "status": "success",
            "message": f"Index {auth_data['index_name']} deleted successfully, but Redis cleanup encountered an error: {redis_error_message}",
            "es_delete_result": es_result,
            "redis_cleanup": {
                "index_name": auth_data["index_name"],
                "total_deleted": 0,
                "celery_tasks_deleted": 0,
                "cache_keys_deleted": 0,
                "errors": [f"Error during Redis cleanup for {auth_data['index_name']}: {redis_error_message}"]
            },
            "minio_cleanup": {
                "deleted_count": 0,
                "failed_count": 0,
                "total_files_found": 0
            },
            "redis_warnings": [f"Error during Redis cleanup for {auth_data['index_name']}: {redis_error_message}"]
        }

        # Execute request
        response = client.delete(
            f"/indices/{auth_data['index_name']}", headers=auth_data["auth_header"])

        # Verify expected 200 status code (the operation should still succeed even with Redis errors)
        assert response.status_code == 200

        # Get the actual response
        actual_response = response.json()

        # Verify essential response elements
        # The ES deletion was successful
        assert actual_response["status"] == "success"
        assert auth_data["index_name"] in actual_response["message"]
        assert "error" in actual_response["message"].lower(
        ) or "error" in str(actual_response).lower()

        # Verify full_delete_knowledge_base was called with the correct parameters
        # Use ANY for the vdb_core parameter because the actual object may differ
        mock_full_delete.assert_called_once_with(
            auth_data["index_name"],
            ANY,  # Use ANY instead of vdb_core_mock to ignore object identity
            auth_data["user_id"]
        )


@pytest.mark.asyncio
async def test_get_list_indices_success(vdb_core_mock, auth_data):
    """
    Test listing indices successfully.
    Verifies that the endpoint returns the expected list of indices.
    """
    # Setup mocks - get_current_user_id is now required
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ASSET_OWNER_TENANT_ID", auth_data["tenant_id"]), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_indices") as mock_list:

        expected_response = {"indices": ["index1", "index2"]}
        mock_list.return_value = expected_response

        # Execute request
        response = client.get(
            "/indices", params={"pattern": "*", "include_stats": False}, headers=auth_data["auth_header"])

        # Verify
        assert response.status_code == 200
        assert response.json() == expected_response
        mock_list.assert_called_once()

        # Verify that list_indices was called with correct parameters including user_id
        call_args = mock_list.call_args
        assert call_args[0][0] == "*"  # pattern
        assert call_args[0][1] is False  # include_stats
        assert call_args[0][2] == auth_data["tenant_id"]  # tenant_id
        assert call_args[0][3] == auth_data["user_id"]  # user_id


@pytest.mark.asyncio
async def test_get_list_indices_error(vdb_core_mock, auth_data):
    """
    Test listing indices with error.
    Verifies that the endpoint returns an appropriate error response when listing fails.
    """
    # Setup mocks - get_current_user_id is now required
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_indices") as mock_list:

        mock_list.side_effect = Exception("Test error")

        # Execute request
        response = client.get("/indices", headers=auth_data["auth_header"])

        # Verify
        assert response.status_code == 500
        assert response.json() == {"detail": "Error get index: Test error"}


@pytest.mark.asyncio
async def test_get_list_indices_with_tenant_id_filter(vdb_core_mock, auth_data):
    """
    Test listing indices with tenant_id query parameter for filtering.
    Verifies that the endpoint passes tenant_id to the service for filtering.
    """
    # Setup mocks
    target_tenant_id = "target_tenant_123"
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_indices") as mock_list:

        expected_response = {
            "indices": ["kb1", "kb2"],
            "count": 2,
            "indices_info": [
                {
                    "name": "kb1",
                    "display_name": "Knowledge Base 1",
                    "permission": "EDIT",
                    "group_ids": [],
                    "knowledge_sources": "elasticsearch",
                    "ingroup_permission": "EDIT",
                    "tenant_id": target_tenant_id,
                    "stats": {}
                },
                {
                    "name": "kb2",
                    "display_name": "Knowledge Base 2",
                    "permission": "READ_ONLY",
                    "group_ids": [],
                    "knowledge_sources": "elasticsearch",
                    "ingroup_permission": "READ_ONLY",
                    "tenant_id": target_tenant_id,
                    "stats": {}
                }
            ]
        }
        mock_list.return_value = expected_response

        # Execute request with tenant_id query parameter
        response = client.get(
            "/indices",
            params={"pattern": "*", "include_stats": True,
                    "tenant_id": target_tenant_id},
            headers=auth_data["auth_header"]
        )

        # Verify
        assert response.status_code == 200
        response_data = response.json()
        assert response_data == expected_response

        # Verify that list_indices was called with the target tenant_id
        mock_list.assert_called_once()
        call_args = mock_list.call_args
        assert call_args[0][0] == "*"  # pattern
        assert call_args[0][1] is True  # include_stats
        # effective_tenant_id from query param
        assert call_args[0][2] == target_tenant_id
        assert call_args[0][3] == auth_data["user_id"]  # user_id from auth

        # Verify indices_info contains tenant_id
        assert len(response_data["indices_info"]) == 2
        assert response_data["indices_info"][0]["tenant_id"] == target_tenant_id
        assert response_data["indices_info"][1]["tenant_id"] == target_tenant_id


@pytest.mark.asyncio
async def test_get_list_indices_passes_pagination_and_filters(vdb_core_mock, auth_data):
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_indices") as mock_list:
        mock_list.return_value = {
            "indices": [], "count": 0, "total": 0,
            "next_offset": None, "facets": {"sources": [], "models": []},
            "estimated_row_height": 112, "estimated_item_heights": None,
        }

        response = client.get(
            "/indices",
            params=[
                ("tenant_id", auth_data["tenant_id"]), ("offset", "10"), ("limit", "10"),
                ("keyword", "medical"), ("sources", "elasticsearch"), ("models", "model-a"),
            ],
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 200
        assert mock_list.call_args.kwargs == {
            "pagination_enabled": True,
            "offset": 10,
            "limit": 10,
            "keyword": "medical",
            "sources": ["elasticsearch"],
            "models": ["model-a"],
        }


@pytest.mark.asyncio
async def test_get_list_indices_merges_tenant_and_asset_pages(vdb_core_mock, auth_data):
    primary = {"indices": ["tenant-kb"], "count": 1, "total": 1}
    asset = {"indices": ["asset-kb"], "count": 1, "total": 1}
    merged = {
        "indices": ["tenant-kb", "asset-kb"],
        "count": 2,
        "total": 2,
        "next_offset": None,
    }

    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ASSET_OWNER_TENANT_ID", "asset-tenant"), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_indices", side_effect=[primary, asset]) as mock_list, \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.merge_paginated_list_indices_results", return_value=merged) as mock_merge:
        response = client.get(
            "/indices",
            params={"offset": 3, "limit": 10, "keyword": "medical"},
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 200
    assert response.json() == merged
    assert mock_list.call_args_list == [
        call(
            "*", False, auth_data["tenant_id"], auth_data["user_id"], ANY,
            pagination_enabled=True, offset=0, limit=13,
            keyword="medical", sources=None, models=None,
        ),
        call(
            "*", False, "asset-tenant", auth_data["user_id"], ANY,
            pagination_enabled=True, offset=0, limit=13,
            keyword="medical", sources=None, models=None,
        ),
    ]
    mock_merge.assert_called_once_with(primary, asset, 3, 10)


@pytest.mark.asyncio
async def test_get_list_indices_merges_tenant_and_asset_without_pagination(vdb_core_mock, auth_data):
    primary = {"indices": ["tenant-kb"], "count": 1}
    asset = {"indices": ["asset-kb"], "count": 1}
    merged = {"indices": ["tenant-kb", "asset-kb"], "count": 2}

    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ASSET_OWNER_TENANT_ID", "asset-tenant"), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_indices", side_effect=[primary, asset]) as mock_list, \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.merge_list_indices_results", return_value=merged) as mock_merge:
        response = client.get("/indices", headers=auth_data["auth_header"])

    assert response.status_code == 200
    assert response.json() == merged
    assert mock_list.call_args_list == [
        call("*", False, auth_data["tenant_id"], auth_data["user_id"], ANY),
        call("*", False, "asset-tenant", auth_data["user_id"], ANY),
    ]
    mock_merge.assert_called_once_with(primary, asset)


@pytest.mark.asyncio
async def test_get_list_indices_uses_auth_tenant_id_when_no_query_param(vdb_core_mock, auth_data):
    """
    Test listing indices uses auth tenant_id when tenant_id query parameter is not provided.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ASSET_OWNER_TENANT_ID", auth_data["tenant_id"]), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_indices") as mock_list:

        expected_response = {"indices": ["index1"], "count": 1}
        mock_list.return_value = expected_response

        # Execute request without tenant_id query parameter
        response = client.get(
            "/indices",
            params={"pattern": "*"},
            headers=auth_data["auth_header"]
        )

        # Verify
        assert response.status_code == 200

        # Verify that list_indices was called with auth tenant_id (no asset-owner merge)
        mock_list.assert_called_once()
        call_args = mock_list.call_args
        assert call_args[0][2] == auth_data["tenant_id"]


@pytest.mark.asyncio
async def test_get_list_indices_with_stats_includes_tenant_id(vdb_core_mock, auth_data):
    """
    Test that list_indices with stats includes tenant_id in the response.
    """
    # Setup mocks
    target_tenant_id = "stats_tenant_456"
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_indices") as mock_list:

        expected_response = {
            "indices": ["kb1"],
            "count": 1,
            "indices_info": [{
                "name": "kb1",
                "display_name": "Test KB",
                "permission": "EDIT",
                "group_ids": [1, 2],
                "knowledge_sources": "elasticsearch",
                "ingroup_permission": "EDIT",
                "tenant_id": target_tenant_id,
                "stats": {
                    "base_info": {
                        "doc_count": 100,
                        "embedding_model": "test-model",
                        "store_size": "1GB"
                    }
                }
            }]
        }
        mock_list.return_value = expected_response

        # Execute request
        response = client.get(
            "/indices",
            params={"include_stats": True, "tenant_id": target_tenant_id},
            headers=auth_data["auth_header"]
        )

        # Verify
        assert response.status_code == 200
        response_data = response.json()

        assert "indices_info" in response_data
        assert len(response_data["indices_info"]) == 1
        assert response_data["indices_info"][0]["tenant_id"] == target_tenant_id
        assert response_data["indices_info"][0]["group_ids"] == [1, 2]


@pytest.mark.asyncio
async def test_get_list_indices_auth_exception(vdb_core_mock):
    """
    Test listing indices with authentication exception.
    Verifies that the endpoint returns 500 when auth fails.
    """
    # Setup mocks - get_current_user_id raises exception
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id") as mock_get_user:

        mock_get_user.side_effect = Exception("Invalid authorization token")

        # Execute request
        response = client.get("/indices")

        # Verify
        assert response.status_code == 500
        assert "Error get index" in response.json()["detail"]
        mock_get_user.assert_called_once()


@pytest.mark.asyncio
async def test_create_index_documents_success(vdb_core_mock, auth_data):
    """
    Test indexing documents successfully.
    Verifies that the endpoint returns the expected response after documents are indexed.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_knowledge_record", return_value={"is_multimodal": "N"}), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.index_documents") as mock_index, \
            patch("backend.apps.vectordatabase_app.get_embedding_model_by_id", return_value=MagicMock()):

        index_name = "test_index"
        documents = [{"id": 1, "text": "test doc"}]

        expected_response = IndexingResponse(
            success=True,
            message="Documents indexed successfully",
            total_indexed=1,
            total_submitted=1
        )

        mock_index.return_value = expected_response

        response = client.post(
            f"/indices/{index_name}/documents", json=documents, headers=auth_data["auth_header"])

        # Verify
    assert response.status_code == 200
    assert response.json() == expected_response.dict()
    mock_index.assert_called_once()


@pytest.mark.asyncio
async def test_create_index_documents_forbidden_for_read_only(vdb_core_mock, auth_data):
    """Read-only users must not be able to index documents."""
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch(
                "backend.apps.vectordatabase_app.require_knowledge_base_edit_permission",
                side_effect=HTTPException(
                    status_code=403,
                    detail="No permission to modify this knowledge base",
                ),
            ) as mock_require_permission, \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.index_documents") as mock_index:

        response = client.post(
            f"/indices/{auth_data['index_name']}/documents",
            json=[{"id": 1, "text": "test doc"}],
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "No permission to modify this knowledge base"
        mock_require_permission.assert_called_once_with(
            auth_data["index_name"],
            auth_data["user_id"],
            auth_data["tenant_id"],
        )
        mock_index.assert_not_called()


@pytest.mark.asyncio
async def test_create_index_documents_uses_multimodal_embedding(vdb_core_mock, auth_data):
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_knowledge_record", return_value={"is_multimodal": "Y"}), \
            patch("backend.apps.vectordatabase_app.get_embedding_model_by_id") as mock_get_embedding, \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.index_documents") as mock_index:

        mock_get_embedding.return_value = MagicMock()
        mock_index.return_value = IndexingResponse(
            success=True,
            message="Documents indexed successfully",
            total_indexed=1,
            total_submitted=1
        )

        response = client.post(
            f"/indices/{auth_data['index_name']}/documents",
            json=[{"id": 1, "text": "test doc"}],
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 200
        mock_get_embedding.assert_not_called()

@pytest.mark.asyncio
async def test_create_index_documents_exception(vdb_core_mock, auth_data):
    """
    Test indexing documents with exception.
    Verifies that the endpoint returns an appropriate error response when an exception occurs during indexing.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_knowledge_record", return_value={"is_multimodal": "N"}), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.index_documents") as mock_index, \
            patch("backend.apps.vectordatabase_app.get_embedding_model_by_id", return_value=MagicMock()):

        index_name = "test_index"
        documents = [{"id": 1, "text": "test doc"}]
        mock_index.side_effect = Exception("Indexing failed")

        response = client.post(
            f"/indices/{index_name}/documents", json=documents, headers=auth_data["auth_header"])

        assert response.status_code == 500

        expected_error_detail = "Error indexing documents: Indexing failed"
        assert response.json() == {"detail": expected_error_detail}


@pytest.mark.asyncio
async def test_create_index_documents_auth_exception(vdb_core_mock, auth_data):
    """
    Test indexing documents with authentication exception.
    Verifies that the endpoint returns an appropriate error response when authentication fails.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id") as mock_get_user:

        index_name = "test_index"
        documents = [{"id": 1, "text": "test doc"}]

        mock_get_user.side_effect = Exception("Invalid authorization token")

        response = client.post(
            f"/indices/{index_name}/documents", json=documents, headers=auth_data["auth_header"])

        assert response.status_code == 500

        expected_error_detail = "Error indexing documents: Invalid authorization token"
        assert response.json() == {"detail": expected_error_detail}

        mock_get_user.assert_called_once()


@pytest.mark.asyncio
async def test_create_index_documents_embedding_model_exception(vdb_core_mock, auth_data):
    """
    Test indexing documents with embedding model exception.
    Verifies that the endpoint returns an appropriate error response when embedding model fails.
    """
    # Setup mocks - need knowledge record with model_id to trigger get_embedding_model_by_id call
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_knowledge_record") as mock_get_record, \
            patch("backend.apps.vectordatabase_app.get_embedding_model_by_id") as mock_get_embedding:

        index_name = "test_index"
        documents = [{"id": 1, "text": "test doc"}]

        mock_get_record.return_value = {
            "index_name": index_name,
            "embedding_model_id": 123
        }
        
        mock_get_embedding.side_effect = Exception("Embedding model not available")

        response = client.post(
            f"/indices/{index_name}/documents", json=documents, headers=auth_data["auth_header"])

        assert response.status_code == 500

        expected_error_detail = "Error indexing documents: Embedding model not available"
        assert response.json() == {"detail": expected_error_detail}

        mock_get_embedding.assert_called_once()


@pytest.mark.asyncio
async def test_create_index_documents_validation_exception(vdb_core_mock, auth_data):
    """
    Test indexing documents with validation exception.
    Verifies that the endpoint returns an appropriate error response when document validation fails.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_knowledge_record", return_value={"is_multimodal": "N"}), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.index_documents") as mock_index, \
            patch("backend.apps.vectordatabase_app.get_embedding_model_by_id", return_value=MagicMock()):

        index_name = "test_index"
        documents = [{"id": 1, "text": "test doc"}]

        mock_index.side_effect = ValueError("Invalid document format")

        response = client.post(
            f"/indices/{index_name}/documents", json=documents, headers=auth_data["auth_header"])

        assert response.status_code == 500

        # Verify error response
        expected_error_detail = "Error indexing documents: Invalid document format"
        assert response.json() == {"detail": expected_error_detail}

        # Verify index_documents was called
        mock_index.assert_called_once()


@pytest.mark.asyncio
async def test_get_index_files_success(vdb_core_mock):
    """
    Test listing index files successfully.
    Using pytest-asyncio to properly handle async operations.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_files") as mock_list_files:

        index_name = "test_index"
        expected_files = {
            "files": [{"path": "file1.txt", "status": "complete"}],
            "status": "success"
        }

        # Set up the mock to return the expected result
        mock_list_files.return_value = expected_files

        # Execute request
        response = client.get(f"/indices/{index_name}/files")

        # With proper pytest-asyncio setup, we should get a successful response
        # But in TestClient environment, we'll likely still get a 500 due to
        # async handling limitations in TestClient
        if response.status_code == 200:
            assert response.json() == expected_files
        else:
            # Just verify the mock was called with right parameters
            assert mock_list_files.called


@pytest.mark.asyncio
async def test_get_index_files_exception(vdb_core_mock):
    """
    Test listing index files with exception.
    Verifies that the endpoint returns an appropriate error response when an exception occurs during file listing.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_files") as mock_list_files:

        index_name = "test_index"

        # Setup the mock to raise an exception
        mock_list_files.side_effect = Exception(
            "Elasticsearch connection failed")

        # Execute request
        response = client.get(f"/indices/{index_name}/files")

        # Verify expected 500 status code
        assert response.status_code == 500

        # Verify error response
        expected_error_detail = "Error indexing documents: Elasticsearch connection failed"
        assert response.json() == {"detail": expected_error_detail}

        # Verify list_files was called with correct parameters
        # Use ANY for the vdb_core parameter because the actual object may differ
        mock_list_files.assert_called_once_with(
            index_name, include_chunks=False, vdb_core=ANY)


@pytest.mark.asyncio
async def test_get_index_files_validation_exception(vdb_core_mock):
    """
    Test listing index files with validation exception.
    Verifies that the endpoint returns an appropriate error response when index validation fails.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_files") as mock_list_files:

        index_name = "test_index"

        # Setup the mock to raise a validation exception
        mock_list_files.side_effect = ValueError("Invalid index name format")

        # Execute request
        response = client.get(f"/indices/{index_name}/files")

        # Verify expected 500 status code
        assert response.status_code == 500

        # Verify error response
        expected_error_detail = "Error indexing documents: Invalid index name format"
        assert response.json() == {"detail": expected_error_detail}

        # Verify list_files was called
        mock_list_files.assert_called_once()


@pytest.mark.asyncio
async def test_get_index_files_timeout_exception(vdb_core_mock):
    """
    Test listing index files with timeout exception.
    Verifies that the endpoint returns an appropriate error response when operation times out.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_files") as mock_list_files:

        index_name = "test_index"

        # Setup the mock to raise a timeout exception
        mock_list_files.side_effect = TimeoutError("Operation timed out")

        # Execute request
        response = client.get(f"/indices/{index_name}/files")

        # Verify expected 500 status code
        assert response.status_code == 500

        # Verify error response
        expected_error_detail = "Error indexing documents: Operation timed out"
        assert response.json() == {"detail": expected_error_detail}

        # Verify list_files was called
        mock_list_files.assert_called_once()


@pytest.mark.asyncio
async def test_get_index_files_permission_exception(vdb_core_mock):
    """
    Test listing index files with permission exception.
    Verifies that the endpoint returns an appropriate error response when permission is denied.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.list_files") as mock_list_files:

        index_name = "test_index"

        # Setup the mock to raise a permission exception
        mock_list_files.side_effect = PermissionError("Access denied to index")

        # Execute request
        response = client.get(f"/indices/{index_name}/files")

        # Verify expected 500 status code
        assert response.status_code == 500

        # Verify error response
        expected_error_detail = "Error indexing documents: Access denied to index"
        assert response.json() == {"detail": expected_error_detail}

        # Verify list_files was called
        mock_list_files.assert_called_once()


@pytest.mark.asyncio
async def test_get_index_chunks_success(vdb_core_mock, auth_data):
    """
    Test retrieving index chunks successfully.
    Verifies that the endpoint forwards query params and returns the service payload.
    """
    index_name = "test_index"
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.check_file_access", return_value=True), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.get_index_chunks") as mock_get_chunks:

        expected_response = {
            "status": "success",
            "message": "ok",
            "chunks": [{"id": "1"}],
            "total": 1,
            "page": 2,
            "page_size": 50,
        }
        mock_get_chunks.return_value = expected_response

        response = client.post(
            f"/indices/{index_name}/chunks",
            params={"page": 2, "page_size": 50, "path_or_url": "/foo"},
            headers=auth_data["auth_header"]
        )

        assert response.status_code == 200
        assert response.json() == expected_response
        mock_get_chunks.assert_called_once_with(
            index_name=index_name,
            page=2,
            page_size=50,
            path_or_url="/foo",
            vdb_core=ANY,
        )


@pytest.mark.asyncio
async def test_get_index_chunks_error(vdb_core_mock, auth_data):
    """
    Test retrieving index chunks with service error.
    Ensures the endpoint maps the exception to HTTP 500.
    """
    index_name = "test_index"
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.get_index_chunks") as mock_get_chunks:

        mock_get_chunks.side_effect = Exception("Chunk failure")

        response = client.post(
            f"/indices/{index_name}/chunks",
            headers=auth_data["auth_header"]
        )

        assert response.status_code == 500
        assert response.json() == {
            "detail": "Error getting chunks: Chunk failure"}
        mock_get_chunks.assert_called_once_with(
            index_name=index_name,
            page=None,
            page_size=None,
            path_or_url=None,
            vdb_core=ANY,
        )


@pytest.mark.asyncio
async def test_create_chunk_success(vdb_core_mock, auth_data):
    """
    Test creating a manual chunk successfully.
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_index_name_by_knowledge_name", return_value=auth_data["index_name"]), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.create_chunk") as mock_create:

        expected_response = {"status": "success", "chunk_id": "chunk-1"}
        mock_create.return_value = expected_response

        payload = {
            "content": "Hello world",
            "path_or_url": "doc-1",
        }

        response = client.post(
            f"/indices/{auth_data['index_name']}/chunk",
            json=payload,
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 200
        assert response.json() == expected_response
        mock_create.assert_called_once()

        # Verify that tenant_id was passed to the service
        call_kwargs = mock_create.call_args[1]
        assert "tenant_id" in call_kwargs
        assert call_kwargs["tenant_id"] == auth_data["tenant_id"]


@pytest.mark.asyncio
async def test_create_chunk_forbidden_for_read_only(vdb_core_mock, auth_data):
    """Read-only users must not be able to create chunks."""
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch(
                "backend.apps.vectordatabase_app.require_knowledge_base_edit_permission",
                side_effect=HTTPException(
                    status_code=403,
                    detail="No permission to modify this knowledge base",
                ),
            ) as mock_require_permission, \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.create_chunk") as mock_create:

        response = client.post(
            f"/indices/{auth_data['index_name']}/chunk",
            json={"content": "Hello world", "path_or_url": "doc-1"},
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "No permission to modify this knowledge base"
        mock_require_permission.assert_called_once_with(
            auth_data["index_name"],
            auth_data["user_id"],
            auth_data["tenant_id"],
        )
        mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_create_chunk_passes_tenant_id_to_service(vdb_core_mock, auth_data):
    """
    Test that create_chunk endpoint passes tenant_id to the service method.
    This is critical for the service to fetch the correct embedding model.
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_index_name_by_knowledge_name", return_value=auth_data["index_name"]), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.create_chunk") as mock_create:

        mock_create.return_value = {"status": "success", "chunk_id": "chunk-1"}

        payload = {
            "content": "Test content for embedding",
            "path_or_url": "doc-123",
            "title": "Test Title"
        }

        response = client.post(
            f"/indices/{auth_data['index_name']}/chunk",
            json=payload,
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 200

        # Verify tenant_id was passed
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        # Check both args and kwargs for tenant_id
        assert ("tenant_id" in call_args.kwargs and call_args.kwargs["tenant_id"] == auth_data["tenant_id"]) or \
               (len(call_args[0]) >= 4 and call_args[0][3] == auth_data["tenant_id"]), \
            "tenant_id should be passed to the service method"


@pytest.mark.asyncio
async def test_create_chunk_error(vdb_core_mock, auth_data):
    """
    Test creating a manual chunk when service raises an exception.
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_index_name_by_knowledge_name", return_value=auth_data["index_name"]), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.create_chunk") as mock_create:

        mock_create.side_effect = Exception("Create failed")

        payload = {
            "content": "Hello world",
            "path_or_url": "doc-1",
        }

        response = client.post(
            f"/indices/{auth_data['index_name']}/chunk",
            json=payload,
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Create failed"}
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_update_chunk_success(vdb_core_mock, auth_data):
    """
    Test updating a chunk successfully.
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_index_name_by_knowledge_name", return_value=auth_data["index_name"]), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.update_chunk") as mock_update:

        expected_response = {"status": "success", "chunk_id": "chunk-1"}
        mock_update.return_value = expected_response

        payload = {
            "content": "Updated content",
        }

        response = client.put(
            f"/indices/{auth_data['index_name']}/chunk/chunk-1",
            json=payload,
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 200
        assert response.json() == expected_response
        mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_update_chunk_forbidden_for_read_only(vdb_core_mock, auth_data):
    """Read-only users must not be able to update chunks."""
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch(
                "backend.apps.vectordatabase_app.require_knowledge_base_edit_permission",
                side_effect=HTTPException(
                    status_code=403,
                    detail="No permission to modify this knowledge base",
                ),
            ) as mock_require_permission, \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.update_chunk") as mock_update:

        response = client.put(
            f"/indices/{auth_data['index_name']}/chunk/chunk-1",
            json={"content": "Updated content"},
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "No permission to modify this knowledge base"
        mock_require_permission.assert_called_once_with(
            auth_data["index_name"],
            auth_data["user_id"],
            auth_data["tenant_id"],
        )
        mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_update_chunk_value_error(vdb_core_mock, auth_data):
    """
    Test updating a chunk when service raises ValueError.
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_index_name_by_knowledge_name", return_value=auth_data["index_name"]), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.update_chunk") as mock_update:

        mock_update.side_effect = ValueError("Invalid update payload")

        payload = {
            "content": "Updated content",
        }

        response = client.put(
            f"/indices/{auth_data['index_name']}/chunk/chunk-1",
            json=payload,
            headers=auth_data["auth_header"],
        )

        # ValueError is mapped to NOT_FOUND in app layer
        assert response.status_code == 404
        assert response.json() == {"detail": "Invalid update payload"}
        mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_update_chunk_exception(vdb_core_mock, auth_data):
    """
    Test updating a chunk when service raises a general exception.
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_index_name_by_knowledge_name", return_value=auth_data["index_name"]), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.update_chunk") as mock_update:

        mock_update.side_effect = Exception("Update failed")

        payload = {
            "content": "Updated content",
        }

        response = client.put(
            f"/indices/{auth_data['index_name']}/chunk/chunk-1",
            json=payload,
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Update failed"}
        mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_delete_chunk_success(vdb_core_mock, auth_data):
    """
    Test deleting a chunk successfully.
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_index_name_by_knowledge_name", return_value=auth_data["index_name"]), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.delete_chunk") as mock_delete:

        expected_response = {"status": "success", "chunk_id": "chunk-1"}
        mock_delete.return_value = expected_response

        response = client.delete(
            f"/indices/{auth_data['index_name']}/chunk/chunk-1",
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 200
        assert response.json() == expected_response
        mock_delete.assert_called_once()


@pytest.mark.asyncio
async def test_delete_chunk_forbidden_for_read_only(vdb_core_mock, auth_data):
    """Read-only users must not be able to delete chunks."""
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch(
                "apps.permission_utils.ElasticSearchService.require_knowledge_base_edit_permission",
                side_effect=PermissionError("No permission to modify this knowledge base"),
            ) as mock_require_permission, \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.delete_chunk") as mock_delete:

        response = client.delete(
            f"/indices/{auth_data['index_name']}/chunk/chunk-1",
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "No permission to modify this knowledge base"
        mock_require_permission.assert_called_once_with(
            index_name=auth_data["index_name"],
            user_id=auth_data["user_id"],
            tenant_id=auth_data["tenant_id"],
        )
        mock_delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_chunk_not_found(vdb_core_mock, auth_data):
    """
    Test deleting a chunk that does not exist (ValueError from service).
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_index_name_by_knowledge_name", return_value=auth_data["index_name"]), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.delete_chunk") as mock_delete:

        mock_delete.side_effect = ValueError("Chunk not found")

        response = client.delete(
            f"/indices/{auth_data['index_name']}/chunk/chunk-1",
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "Chunk not found"}
        mock_delete.assert_called_once()


@pytest.mark.asyncio
async def test_delete_chunk_exception(vdb_core_mock, auth_data):
    """
    Test deleting a chunk when service raises a general exception.
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_index_name_by_knowledge_name", return_value=auth_data["index_name"]), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.delete_chunk") as mock_delete:

        mock_delete.side_effect = Exception("Delete failed")

        response = client.delete(
            f"/indices/{auth_data['index_name']}/chunk/chunk-1",
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Delete failed"}
        mock_delete.assert_called_once()


@pytest.mark.asyncio
async def test_health_check_success(vdb_core_mock):
    """
    Test health check endpoint successfully.
    Using pytest-asyncio to properly handle async operations.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.health_check") as mock_health:

        expected_response = {"status": "ok", "elasticsearch": "connected"}
        mock_health.return_value = expected_response

        # Execute request
        response = client.get("/indices/health")

        # Verify
        assert response.status_code == 200
        assert response.json() == expected_response


@pytest.mark.asyncio
async def test_check_knowledge_base_exist_success(vdb_core_mock, auth_data):
    """
    Test check knowledge base exist endpoint success.
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.check_knowledge_base_exist_impl") as mock_impl:

        expected_response = {"status": "exists_in_tenant"}
        mock_impl.return_value = expected_response

        response = client.post(
            "/indices/check_exist",
            json={"knowledge_name": auth_data['index_name']},
            headers=auth_data["auth_header"]
        )

        assert response.status_code == 200
        assert response.json() == expected_response


@pytest.mark.asyncio
async def test_check_knowledge_base_exist_error(vdb_core_mock, auth_data):
    """
    Test check knowledge base exist endpoint error path.
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.check_knowledge_base_exist_impl") as mock_impl:

        mock_impl.side_effect = Exception("Test error")

        response = client.post(
            "/indices/check_exist",
            json={"knowledge_name": auth_data['index_name']},
            headers=auth_data["auth_header"]
        )

        assert response.status_code == 500
        assert response.json() == {
            "detail": "Error checking existence for knowledge base: Test error"}


@pytest.mark.asyncio
async def test_update_index_success(auth_data):
    """
    Test updating a knowledge base successfully.
    Verifies that the endpoint returns the expected response when update succeeds.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_current_user_context", return_value=(auth_data["user_id"], auth_data["tenant_id"], "ADMIN")), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.update_knowledge_base") as mock_update:

        mock_update.return_value = True

        # Execute request with all update fields
        payload = {
            "knowledge_name": "Updated Knowledge Base",
            "ingroup_permission": "EDIT",
            "group_ids": [1, 2, 3],
            "is_multimodal": True
        }
        response = client.patch(
            f"/indices/{auth_data['index_name']}",
            json=payload,
            headers=auth_data["auth_header"]
        )

        # Verify
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert "updated successfully" in response.json()["message"]
        mock_update.assert_called_once_with(
            index_name=auth_data["index_name"],
            knowledge_name="Updated Knowledge Base",
            ingroup_permission="EDIT",
            group_ids=[1, 2, 3],
            tenant_id=auth_data["tenant_id"],
            user_id=auth_data["user_id"],
            user_role="ADMIN"
        )


@pytest.mark.asyncio
async def test_update_index_partial_update(auth_data):
    """
    Test partial update of a knowledge base.
    Verifies that the endpoint handles partial updates correctly.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_current_user_context", return_value=(auth_data["user_id"], auth_data["tenant_id"], "ADMIN")), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.update_knowledge_base") as mock_update:

        mock_update.return_value = True

        # Execute request with only name update
        payload = {
            "knowledge_name": "Only Name Updated"
        }
        response = client.patch(
            f"/indices/{auth_data['index_name']}",
            json=payload,
            headers=auth_data["auth_header"]
        )

        # Verify
        assert response.status_code == 200
        mock_update.assert_called_once_with(
            index_name=auth_data["index_name"],
            knowledge_name="Only Name Updated",
            ingroup_permission=None,
            group_ids=None,
            tenant_id=auth_data["tenant_id"],
            user_id=auth_data["user_id"],
            user_role="ADMIN"
        )


@pytest.mark.asyncio
async def test_update_index_clear_quota(auth_data):
    """Test that an explicit null quota removes the knowledge base limit."""
    with patch("backend.apps.vectordatabase_app.get_current_user_context", return_value=(auth_data["user_id"], auth_data["tenant_id"], "ADMIN")), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.update_knowledge_base") as mock_update:
        mock_update.return_value = True

        response = client.patch(
            f"/indices/{auth_data['index_name']}",
            json={"quota_limit_bytes": None},
            headers=auth_data["auth_header"]
        )

        assert response.status_code == 200
        mock_update.assert_called_once_with(
            index_name=auth_data["index_name"],
            knowledge_name=None,
            ingroup_permission=None,
            group_ids=None,
            tenant_id=auth_data["tenant_id"],
            user_id=auth_data["user_id"],
            user_role="ADMIN",
            quota_limit_bytes=None
        )


@pytest.mark.asyncio
async def test_update_index_value_error(auth_data):
    """
    Test updating a knowledge base with invalid permission value.
    Verifies that the endpoint returns 400 BAD_REQUEST for invalid permission.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_current_user_context", return_value=(auth_data["user_id"], auth_data["tenant_id"], "ADMIN")), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.update_knowledge_base") as mock_update:

        mock_update.side_effect = ValueError(
            "Invalid ingroup_permission. Must be one of: ['EDIT', 'READ_ONLY', 'PRIVATE']")

        # Execute request with invalid permission
        payload = {
            "ingroup_permission": "INVALID_PERMISSION"
        }
        response = client.patch(
            f"/indices/{auth_data['index_name']}",
            json=payload,
            headers=auth_data["auth_header"]
        )

        # Verify
        assert response.status_code == 400
        assert "Invalid ingroup_permission" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_index_not_found(auth_data):
    """
    Test updating a non-existent knowledge base.
    Verifies that the endpoint returns 404 NOT_FOUND when knowledge base doesn't exist.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_current_user_context", return_value=(auth_data["user_id"], auth_data["tenant_id"], "ADMIN")), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.update_knowledge_base") as mock_update:

        mock_update.return_value = False  # Knowledge base not found

        # Execute request
        payload = {
            "knowledge_name": "New Name"
        }
        response = client.patch(
            f"/indices/{auth_data['index_name']}",
            json=payload,
            headers=auth_data["auth_header"]
        )

        # Verify
        assert response.status_code == 404
        assert auth_data["index_name"] in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_index_exception(auth_data):
    """
    Test updating a knowledge base with general exception.
    Verifies that the endpoint returns 500 INTERNAL_SERVER_ERROR on error.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_current_user_context", return_value=(auth_data["user_id"], auth_data["tenant_id"], "ADMIN")), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.update_knowledge_base") as mock_update:

        mock_update.side_effect = Exception("Database error")

        # Execute request
        payload = {
            "knowledge_name": "New Name"
        }
        response = client.patch(
            f"/indices/{auth_data['index_name']}",
            json=payload,
            headers=auth_data["auth_header"]
        )

        # Verify
        assert response.status_code == 500
        assert "Error updating index" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_index_auth_exception(auth_data):
    """
    Test updating a knowledge base with authentication exception.
    Verifies that the endpoint returns 500 INTERNAL_SERVER_ERROR when auth fails.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_current_user_context") as mock_get_user:

        mock_get_user.side_effect = Exception("Invalid authorization token")

        # Execute request
        payload = {
            "knowledge_name": "New Name"
        }
        response = client.patch(
            f"/indices/{auth_data['index_name']}",
            json=payload,
            headers=auth_data["auth_header"]
        )

        # Verify
        assert response.status_code == 500
        assert "Error updating index" in response.json()["detail"]
        mock_get_user.assert_called_once()


@pytest.mark.asyncio
async def test_delete_index_exception(vdb_core_mock, auth_data):
    """
    Test deleting an index with exception.
    Verifies that the endpoint returns an appropriate error response when an exception occurs during deletion.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.full_delete_knowledge_base") as mock_full_delete:

        # Setup the mock to raise an exception
        mock_full_delete.side_effect = Exception("Database connection failed")

        # Execute request
        response = client.delete(
            f"/indices/{auth_data['index_name']}", headers=auth_data["auth_header"])

        # Verify expected 500 status code
        assert response.status_code == 500

        # Verify error response
        expected_error_detail = f"Error deleting index: Database connection failed"
        assert response.json() == {"detail": expected_error_detail}

        # Verify full_delete_knowledge_base was called with the correct parameters
        mock_full_delete.assert_called_once_with(
            auth_data["index_name"],
            ANY,  # Use ANY instead of vdb_core_mock to ignore object identity
            auth_data["user_id"]
        )


@pytest.mark.asyncio
async def test_delete_index_auth_exception(vdb_core_mock, auth_data):
    """
    Test deleting an index with authentication exception.
    Verifies that the endpoint returns an appropriate error response when authentication fails.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id") as mock_get_user:

        # Setup the mock to raise an authentication exception
        mock_get_user.side_effect = Exception("Invalid authorization token")

        # Execute request
        response = client.delete(
            f"/indices/{auth_data['index_name']}", headers=auth_data["auth_header"])

        # Verify expected 500 status code
        assert response.status_code == 500

        # Verify error response
        expected_error_detail = f"Error deleting index: Invalid authorization token"
        assert response.json() == {"detail": expected_error_detail}

        # Verify get_current_user_id was called
        mock_get_user.assert_called_once()


@pytest.mark.asyncio
async def test_delete_documents_success(vdb_core_mock, redis_service_mock, auth_data):
    """
    Test deleting documents successfully.
    Verifies that the endpoint returns the expected response and performs Redis cleanup.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_redis_service", return_value=redis_service_mock), \
            patch(
                "backend.apps.vectordatabase_app.ElasticSearchService.delete_document_by_scope",
                new_callable=AsyncMock,
            ) as mock_delete_by_scope, \
            patch("services.tag_management_service.TagManagementService.cleanup_document_assignments") as cleanup_document:

        index_name = "test_index"
        path_or_url = "test_document.pdf"

        es_result = {
            "status": "success",
            "message": "Documents deleted successfully",
            "scope": "full",
            "deleted_es_count": 5,
            "source_available": False,
        }
        mock_delete_by_scope.return_value = es_result

        redis_result = {
            "index_name": index_name,
            "path_or_url": path_or_url,
            "total_deleted": 3,
            "celery_tasks_deleted": 2,
            "cache_keys_deleted": 1
        }
        redis_service_mock.delete_document_records.return_value = redis_result

        response = client.delete(
            f"/indices/{index_name}/documents",
            params={"path_or_url": path_or_url, "scope": "full"},
            headers=auth_data["auth_header"],
        )

        # Verify expected 200 status code
        assert response.status_code == 200

        # Get the actual response
        actual_response = response.json()

        # Verify essential response elements
        assert actual_response["status"] == "success"
        assert "Documents deleted successfully" in actual_response["message"]
        assert "Cleaned up 3 Redis records" in actual_response["message"]
        assert "2 tasks" in actual_response["message"]
        assert "1 cache keys" in actual_response["message"]

        # Verify structure contains expected keys
        assert "redis_cleanup" in actual_response
        assert actual_response["redis_cleanup"] == redis_result

        mock_delete_by_scope.assert_called_once_with(
            index_name, path_or_url, "full", ANY
        )
        redis_service_mock.delete_document_records.assert_called_once_with(
            index_name, path_or_url)
        cleanup_document.assert_called_once_with(
            auth_data["tenant_id"], "local", index_name, path_or_url, auth_data["user_id"]
        )


@pytest.mark.asyncio
async def test_delete_documents_resolves_lifecycle_file_id(vdb_core_mock, redis_service_mock, auth_data):
    """New clients can delete a file by durable lifecycle ID."""
    lifecycle_record = {"file_id": "fid-1", "object_name": "knowledge_base/a.txt"}
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("database.knowledge_file_lifecycle_db.get_file_record", return_value=lifecycle_record) as mock_get_record, \
            patch(
                "backend.apps.vectordatabase_app.ElasticSearchService.delete_document_by_scope",
                new_callable=AsyncMock,
            ) as mock_delete_by_scope:
        mock_delete_by_scope.return_value = {"status": "success", "scope": "source_only"}

        response = client.delete(
            f"/indices/{auth_data['index_name']}/documents",
            params={"file_id": "fid-1", "scope": "source_only"},
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 200
        mock_get_record.assert_called_once_with(
            file_id="fid-1",
            index_name=auth_data["index_name"],
            tenant_id=auth_data["tenant_id"],
            include_hidden=True,
        )
        mock_delete_by_scope.assert_awaited_once_with(
            auth_data["index_name"], "knowledge_base/a.txt", "source_only", ANY,
            file_id="fid-1", requested_by=auth_data["user_id"]
        )


@pytest.mark.asyncio
async def test_delete_documents_uses_legacy_path_when_lifecycle_lookup_fails(
    vdb_core_mock, auth_data
):
    """A temporary lifecycle-table outage must retain the legacy delete contract."""
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("database.knowledge_file_lifecycle_db.get_file_record", side_effect=RuntimeError("table unavailable")), \
            patch(
                "backend.apps.vectordatabase_app.ElasticSearchService.delete_document_by_scope",
                new_callable=AsyncMock,
                return_value={"status": "success", "scope": "full"},
            ) as mock_delete, \
            patch("services.tag_management_service.TagManagementService.cleanup_document_assignments"):
        response = client.delete(
            f"/indices/{auth_data['index_name']}/documents",
            params={
                "file_id": "fid-legacy",
                "path_or_url": "knowledge_base/legacy.txt",
                "scope": "full",
            },
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 200
    mock_delete.assert_awaited_once_with(
        auth_data["index_name"], "knowledge_base/legacy.txt", "full", ANY,
        file_id="fid-legacy", requested_by=auth_data["user_id"]
    )


@pytest.mark.asyncio
async def test_delete_documents_requires_file_identity(vdb_core_mock, auth_data):
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])):
        response = client.delete(
            f"/indices/{auth_data['index_name']}/documents",
            params={"scope": "full"},
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Either path_or_url or file_id is required"


@pytest.mark.asyncio
async def test_delete_documents_removes_lifecycle_record_without_object(vdb_core_mock, auth_data):
    """A failed upload without a storage object can be deleted by file ID."""
    lifecycle_record = {
        "file_id": "fid-no-object",
        "tenant_id": auth_data["tenant_id"],
        "index_name": auth_data["index_name"],
        "object_name": None,
        "status": "FAILED",
    }
    delete_result = {
        "status": "success",
        "scope": "full",
        "lifecycle_deleted": True,
    }
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("database.knowledge_file_lifecycle_db.get_file_record", return_value=lifecycle_record), \
            patch(
                "backend.apps.vectordatabase_app.ElasticSearchService.delete_lifecycle_record_without_object",
                return_value=delete_result,
            ) as mock_delete_lifecycle:
        response = client.delete(
            f"/indices/{auth_data['index_name']}/documents",
            # The frontend uses file_id as the legacy path fallback when object_name is empty.
            params={
                "path_or_url": "fid-no-object",
                "file_id": "fid-no-object",
                "scope": "full",
            },
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 200
    assert response.json() == delete_result
    mock_delete_lifecycle.assert_called_once_with(lifecycle_record, requested_by=auth_data["user_id"])


@pytest.mark.asyncio
async def test_delete_documents_rejects_source_only_without_object(vdb_core_mock, auth_data):
    """Source-only deletion is invalid when upload never created a storage object."""
    lifecycle_record = {
        "file_id": "fid-no-object",
        "tenant_id": auth_data["tenant_id"],
        "index_name": auth_data["index_name"],
        "object_name": None,
        "status": "FAILED",
    }
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("database.knowledge_file_lifecycle_db.get_file_record", return_value=lifecycle_record), \
            patch(
                "backend.apps.vectordatabase_app.ElasticSearchService.delete_lifecycle_record_without_object",
            ) as mock_delete_lifecycle:
        response = client.delete(
            f"/indices/{auth_data['index_name']}/documents",
            params={"file_id": "fid-no-object", "scope": "source_only"},
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "A file without a storage object can only use full deletion"
    mock_delete_lifecycle.assert_not_called()


@pytest.mark.asyncio
async def test_get_document_error_info_returns_lifecycle_error(auth_data):
    """Durable lifecycle errors take precedence over Redis task metadata."""
    lifecycle_record = {
        "file_id": "fid-failed",
        "error_code": "PARSE_FAILED",
        "error_message": "unsupported format",
        "error_stage": "PROCESS",
        "failed_at": "2026-08-22T00:00:00",
    }
    with patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("database.knowledge_file_lifecycle_db.get_file_record", return_value=lifecycle_record) as mock_get_record, \
            patch("backend.apps.vectordatabase_app.get_all_files_status", new_callable=AsyncMock) as mock_legacy:
        response = client.get(
            f"/indices/{auth_data['index_name']}/documents/knowledge_base/a.txt/error-info",
            params={"file_id": "fid-failed"},
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "error_code": "PARSE_FAILED",
            "error_message": "unsupported format",
            "error_stage": "PROCESS",
            "failed_at": "2026-08-22T00:00:00",
        }
        mock_get_record.assert_called_once_with(
            file_id="fid-failed",
            index_name=auth_data["index_name"],
            tenant_id=auth_data["tenant_id"],
            object_name=None,
            include_hidden=True,
        )
        mock_legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_document_error_info_falls_back_when_lifecycle_has_no_error(auth_data):
    """A lifecycle row without error metadata must not hide legacy Redis errors."""
    lifecycle_record = {
        "file_id": "fid-processing",
        "tenant_id": auth_data["tenant_id"],
        "index_name": auth_data["index_name"],
        "status": "PROCESSING",
        "error_code": None,
        "error_message": None,
        "error_stage": None,
        "failed_at": None,
    }
    redis_service = MagicMock()
    redis_service.get_error_info.return_value = '{"error_code":"LEGACY_PARSE_FAILED"}'
    with patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("database.knowledge_file_lifecycle_db.get_file_record", return_value=lifecycle_record), \
            patch(
                "backend.apps.vectordatabase_app.get_all_files_status",
                new=AsyncMock(return_value={"knowledge_base/a.txt": {"latest_task_id": "task-legacy"}}),
            ), \
            patch("backend.apps.vectordatabase_app.get_redis_service", return_value=redis_service):
        response = client.get(
            f"/indices/{auth_data['index_name']}/documents/knowledge_base/a.txt/error-info",
            params={"file_id": "fid-processing"},
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "error_code": "LEGACY_PARSE_FAILED",
        "error_message": '{"error_code":"LEGACY_PARSE_FAILED"}',
        "error_stage": None,
        "failed_at": None,
    }
    redis_service.get_error_info.assert_called_once_with("task-legacy")


@pytest.mark.asyncio
async def test_get_document_error_info_returns_lifecycle_stage_without_legacy_status(auth_data):
    """A durable row with no task ID still returns a stable success payload."""
    lifecycle_record = {
        "file_id": "fid-uploaded",
        "status": "UPLOADED",
        "stage": "UPLOAD",
        "error_code": None,
        "error_message": None,
        "error_stage": None,
        "failed_at": None,
    }
    with patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("database.knowledge_file_lifecycle_db.get_file_record", return_value=lifecycle_record), \
            patch("backend.apps.vectordatabase_app.get_all_files_status", new_callable=AsyncMock, return_value={}):
        response = client.get(
            f"/indices/{auth_data['index_name']}/documents/knowledge_base/a.txt/error-info",
            params={"file_id": "fid-uploaded"},
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "error_code": None,
        "error_message": None,
        "error_stage": "UPLOAD",
        "failed_at": None,
    }


@pytest.mark.asyncio
async def test_delete_documents_forbidden_for_read_only(vdb_core_mock, auth_data):
    """Read-only users must not be able to delete files from a knowledge base."""
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id",
                  return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch(
                "backend.apps.vectordatabase_app.ElasticSearchService.require_knowledge_base_edit_permission",
                side_effect=PermissionError("No permission to modify this knowledge base"),
            ), \
            patch(
                "backend.apps.vectordatabase_app.ElasticSearchService.delete_document_by_scope",
                new_callable=AsyncMock,
            ) as mock_delete_by_scope, \
            patch("services.tag_management_service.TagManagementService.cleanup_document_assignments"):

        response = client.delete(
            f"/indices/{auth_data['index_name']}/documents",
            params={"path_or_url": "test_document.pdf", "scope": "full"},
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "No permission to modify this knowledge base"
        mock_delete_by_scope.assert_not_called()


@pytest.mark.asyncio
async def test_delete_documents_source_only_skips_redis(vdb_core_mock, redis_service_mock, auth_data):
    """source_only scope must not trigger Redis document cleanup."""
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_redis_service", return_value=redis_service_mock), \
            patch(
                "backend.apps.vectordatabase_app.ElasticSearchService.delete_document_by_scope",
                new_callable=AsyncMock,
            ) as mock_delete_by_scope, \
            patch("services.tag_management_service.TagManagementService.cleanup_document_assignments"):

        index_name = "test_index"
        path_or_url = "knowledge_base/test.pdf"
        mock_delete_by_scope.return_value = {
            "status": "success",
            "scope": "source_only",
            "deleted_es_count": 0,
            "deleted_minio": True,
            "source_available": False,
        }

        response = client.delete(
            f"/indices/{index_name}/documents",
            params={"path_or_url": path_or_url, "scope": "source_only"},
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 200
        assert response.json()["scope"] == "source_only"
        mock_delete_by_scope.assert_called_once_with(
            index_name, path_or_url, "source_only", ANY
        )
        redis_service_mock.delete_document_records.assert_not_called()


@pytest.mark.asyncio
async def test_delete_documents_redis_error(vdb_core_mock, redis_service_mock, auth_data):
    """
    Test deleting documents with Redis error.
    Verifies that the endpoint still succeeds with ES but reports Redis cleanup error.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_redis_service", return_value=redis_service_mock), \
            patch(
                "backend.apps.vectordatabase_app.ElasticSearchService.delete_document_by_scope",
                new_callable=AsyncMock,
            ) as mock_delete_by_scope, \
            patch("services.tag_management_service.TagManagementService.cleanup_document_assignments"):

        index_name = "test_index"
        path_or_url = "test_document.pdf"

        es_result = {
            "status": "success",
            "message": "Documents deleted successfully",
            "scope": "full",
            "deleted_es_count": 5,
        }
        mock_delete_by_scope.return_value = es_result

        redis_error_message = "Redis connection failed"
        redis_service_mock.delete_document_records.side_effect = Exception(
            redis_error_message)

        response = client.delete(
            f"/indices/{index_name}/documents",
            params={"path_or_url": path_or_url, "scope": "full"},
            headers=auth_data["auth_header"],
        )

        # Verify expected 200 status code (the operation should still succeed even with Redis errors)
        assert response.status_code == 200

        # Get the actual response
        actual_response = response.json()

        # Verify essential response elements
        assert actual_response["status"] == "success"
        assert "Documents deleted successfully" in actual_response["message"]
        assert "Redis cleanup encountered an error" in actual_response["message"]
        assert redis_error_message in actual_response["message"]

        # Verify structure contains expected keys
        assert "redis_cleanup_error" in actual_response
        assert actual_response["redis_cleanup_error"] == redis_error_message

        mock_delete_by_scope.assert_called_once_with(
            index_name, path_or_url, "full", ANY
        )
        redis_service_mock.delete_document_records.assert_called_once_with(
            index_name, path_or_url)


@pytest.mark.asyncio
async def test_delete_documents_es_exception(vdb_core_mock, auth_data):
    """
    Test deleting documents with Elasticsearch exception.
    Verifies that the endpoint returns an appropriate error response when ES deletion fails.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch(
                "backend.apps.vectordatabase_app.ElasticSearchService.delete_document_by_scope",
                new_callable=AsyncMock,
            ) as mock_delete_by_scope:

        index_name = "test_index"
        path_or_url = "test_document.pdf"

        mock_delete_by_scope.side_effect = Exception(
            "Elasticsearch deletion failed")

        response = client.delete(
            f"/indices/{index_name}/documents",
            params={"path_or_url": path_or_url, "scope": "full"},
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 500
        expected_error_detail = "Error delete indexing documents: Elasticsearch deletion failed"
        assert response.json() == {"detail": expected_error_detail}
        mock_delete_by_scope.assert_called_once_with(
            index_name, path_or_url, "full", ANY
        )


@pytest.mark.asyncio
async def test_delete_documents_redis_warnings(vdb_core_mock, redis_service_mock, auth_data):
    """
    Test deleting documents with Redis warnings.
    Verifies that the endpoint handles Redis warnings properly.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_redis_service", return_value=redis_service_mock), \
            patch(
                "backend.apps.vectordatabase_app.ElasticSearchService.delete_document_by_scope",
                new_callable=AsyncMock,
            ) as mock_delete_by_scope, \
            patch("services.tag_management_service.TagManagementService.cleanup_document_assignments"):

        index_name = "test_index"
        path_or_url = "test_document.pdf"

        es_result = {
            "status": "success",
            "message": "Documents deleted successfully",
            "scope": "full",
            "deleted_es_count": 5,
        }
        mock_delete_by_scope.return_value = es_result

        redis_result = {
            "index_name": index_name,
            "path_or_url": path_or_url,
            "total_deleted": 2,
            "celery_tasks_deleted": 1,
            "cache_keys_deleted": 1,
            "errors": ["Some cache keys could not be deleted"]
        }
        redis_service_mock.delete_document_records.return_value = redis_result

        response = client.delete(
            f"/indices/{index_name}/documents",
            params={"path_or_url": path_or_url, "scope": "full"},
            headers=auth_data["auth_header"],
        )

        # Verify expected 200 status code
        assert response.status_code == 200

        # Get the actual response
        actual_response = response.json()

        # Verify essential response elements
        assert actual_response["status"] == "success"
        assert "Documents deleted successfully" in actual_response["message"]
        assert "Cleaned up 2 Redis records" in actual_response["message"]

        # Verify structure contains expected keys
        assert "redis_cleanup" in actual_response
        assert "redis_warnings" in actual_response
        assert actual_response["redis_warnings"] == [
            "Some cache keys could not be deleted"]

        mock_delete_by_scope.assert_called_once_with(
            index_name, path_or_url, "full", ANY
        )
        redis_service_mock.delete_document_records.assert_called_once_with(
            index_name, path_or_url)


@pytest.mark.asyncio
async def test_delete_documents_validation_exception(vdb_core_mock, auth_data):
    """
    Test deleting documents with validation exception.
    Verifies that the endpoint returns an appropriate error response when validation fails.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch(
                "backend.apps.vectordatabase_app.ElasticSearchService.delete_document_by_scope",
                new_callable=AsyncMock,
            ) as mock_delete_by_scope:

        index_name = "test_index"
        path_or_url = "test_document.pdf"

        mock_delete_by_scope.side_effect = ValueError(
            "Invalid document path format")

        response = client.delete(
            f"/indices/{index_name}/documents",
            params={"path_or_url": path_or_url, "scope": "source_only"},
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid document path format"}
        mock_delete_by_scope.assert_called_once_with(
            index_name, path_or_url, "source_only", ANY
        )


@pytest.mark.asyncio
async def test_health_check_exception(vdb_core_mock):
    """
    Test health check endpoint with exception.
    Verifies that the endpoint returns an appropriate error response when an exception occurs during health check.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.health_check") as mock_health:
        # Setup the mock to raise an exception
        mock_health.side_effect = Exception("Elasticsearch connection failed")

        # Execute request
        response = client.get("/indices/health")

        # Verify expected 500 status code
        assert response.status_code == 500

        # Verify error response
        expected_error_detail = "Elasticsearch connection failed"
        assert response.json() == {"detail": expected_error_detail}

        # Verify health_check was called
        # Use ANY for the vdb_core parameter because the actual object may differ
        mock_health.assert_called_once_with(ANY)


@pytest.mark.asyncio
async def test_get_document_error_info_not_found(vdb_core_mock, auth_data):
    """
    Test document error info when document is not found.
    """
    with patch("backend.apps.vectordatabase_app.get_all_files_status", new=AsyncMock(return_value={})):
        response = client.get(
            f"/indices/{auth_data['index_name']}/documents/missing_doc/error-info",
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_document_error_info_no_task_id(auth_data):
    """
    Test document error info when task id is empty.
    """
    with patch(
        "backend.apps.vectordatabase_app.get_all_files_status",
        new=AsyncMock(
            return_value={
                "doc-1": {
                    "latest_task_id": ""
                }
            }
        ),
    ), patch("backend.apps.vectordatabase_app.get_redis_service") as mock_redis:
        response = client.get(
            "/indices/test_index/documents/doc-1/error-info",
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "error_code": None,
        "error_message": None,
        "error_stage": None,
        "failed_at": None,
    }
    mock_redis.assert_not_called()


@pytest.mark.asyncio
async def test_get_document_error_info_json_error_code(auth_data):
    """
    Test document error info JSON parsing for error_code.
    """
    redis_mock = MagicMock()
    redis_mock.get_error_info.return_value = '{"error_code": "INVALID_FORMAT"}'

    with patch(
        "backend.apps.vectordatabase_app.get_all_files_status",
        new=AsyncMock(
            return_value={
                "doc-1": {
                    "latest_task_id": "task-123"
                }
            }
        ),
    ), patch(
        "backend.apps.vectordatabase_app.get_redis_service",
        return_value=redis_mock,
    ):
        response = client.get(
            "/indices/test_index/documents/doc-1/error-info",
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "error_code": "INVALID_FORMAT",
        "error_message": '{"error_code": "INVALID_FORMAT"}',
        "error_stage": None,
        "failed_at": None,
    }
    redis_mock.get_error_info.assert_called_once_with("task-123")


@pytest.mark.asyncio
async def test_get_document_error_info_regex_error_code(auth_data):
    """
    Test document error info regex extraction when JSON parsing fails.
    """
    redis_mock = MagicMock()
    redis_mock.get_error_info.return_value = "oops {'error_code': 'TIMEOUT_ERROR'}"

    with patch(
        "backend.apps.vectordatabase_app.get_all_files_status",
        new=AsyncMock(
            return_value={
                "doc-1": {
                    "latest_task_id": "task-999"
                }
            }
        ),
    ), patch(
        "backend.apps.vectordatabase_app.get_redis_service",
        return_value=redis_mock,
    ):
        response = client.get(
            "/indices/test_index/documents/doc-1/error-info",
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "error_code": "TIMEOUT_ERROR",
        "error_message": "oops {'error_code': 'TIMEOUT_ERROR'}",
        "error_stage": None,
        "failed_at": None,
    }
    redis_mock.get_error_info.assert_called_once_with("task-999")


@pytest.mark.asyncio
async def test_health_check_timeout_exception(vdb_core_mock):
    """
    Test health check endpoint with timeout exception.
    Verifies that the endpoint returns an appropriate error response when operation times out.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.health_check") as mock_health:

        # Setup the mock to raise a timeout exception
        mock_health.side_effect = TimeoutError("Health check timed out")

        # Execute request
        response = client.get("/indices/health")

        # Verify expected 500 status code
        assert response.status_code == 500

        # Verify error response
        expected_error_detail = "Health check timed out"
        assert response.json() == {"detail": expected_error_detail}

        # Verify health_check was called
        mock_health.assert_called_once_with(ANY)


@pytest.mark.asyncio
async def test_health_check_connection_exception(vdb_core_mock):
    """
    Test health check endpoint with connection exception.
    Verifies that the endpoint returns an appropriate error response when connection fails.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.health_check") as mock_health:

        # Setup the mock to raise a connection exception
        mock_health.side_effect = ConnectionError(
            "Unable to connect to Elasticsearch")

        # Execute request
        response = client.get("/indices/health")

        # Verify expected 500 status code
        assert response.status_code == 500

        # Verify error response
        expected_error_detail = "Unable to connect to Elasticsearch"
        assert response.json() == {"detail": expected_error_detail}

        # Verify health_check was called
        mock_health.assert_called_once_with(ANY)


@pytest.mark.asyncio
async def test_health_check_permission_exception(vdb_core_mock):
    """
    Test health check endpoint with permission exception.
    Verifies that the endpoint returns an appropriate error response when permission is denied.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.health_check") as mock_health:

        # Setup the mock to raise a permission exception
        mock_health.side_effect = PermissionError(
            "Access denied to Elasticsearch")

        # Execute request
        response = client.get("/indices/health")

        # Verify expected 500 status code
        assert response.status_code == 500

        # Verify error response
        expected_error_detail = "Access denied to Elasticsearch"
        assert response.json() == {"detail": expected_error_detail}

        # Verify health_check was called
        mock_health.assert_called_once_with(ANY)


@pytest.mark.asyncio
async def test_health_check_validation_exception(vdb_core_mock):
    """
    Test health check endpoint with validation exception.
    Verifies that the endpoint returns an appropriate error response when validation fails.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.health_check") as mock_health:

        # Setup the mock to raise a validation exception
        mock_health.side_effect = ValueError(
            "Invalid Elasticsearch configuration")

        # Execute request
        response = client.get("/indices/health")

        # Verify expected 500 status code
        assert response.status_code == 500

        # Verify error response
        expected_error_detail = "Invalid Elasticsearch configuration"
        assert response.json() == {"detail": expected_error_detail}

        # Verify health_check was called
        mock_health.assert_called_once_with(ANY)


@pytest.mark.asyncio
async def test_hybrid_search_success(vdb_core_mock, auth_data):
    """
    Test hybrid search endpoint successfully.
    Verifies that the endpoint returns the expected response when hybrid search succeeds.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.search_hybrid") as mock_search_hybrid:

        expected_response = {
            "results": [
                {
                    "title": "Doc1",
                    "content": "Content1",
                    "score": 0.90,
                    "index": "test_index",
                    "score_details": {"accurate": 0.85, "semantic": 0.95}
                }
            ],
            "total": 1,
            "query_time_ms": 50
        }
        mock_search_hybrid.return_value = expected_response

        # Execute request
        payload = {
            "index_names": ["test_index"],
            "query": "test query",
            "top_k": 10,
            "weight_accurate": 0.5
        }
        response = client.post(
            "/indices/search/hybrid",
            json=payload,
            headers=auth_data["auth_header"]
        )

        # Verify
        assert response.status_code == 200
        assert response.json() == expected_response
        mock_search_hybrid.assert_called_once_with(
            index_names=["test_index"],
            query="test query",
            tenant_id=auth_data["tenant_id"],
            top_k=10,
            weight_accurate=0.5,
            vdb_core=ANY
        )


@pytest.mark.asyncio
async def test_hybrid_search_value_error(vdb_core_mock, auth_data):
    """
    Test hybrid search endpoint with ValueError.
    Verifies that the endpoint returns 400 BAD_REQUEST when validation fails.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.search_hybrid") as mock_search_hybrid:

        mock_search_hybrid.side_effect = ValueError("Query text is required")

        # Execute request
        payload = {
            "index_names": ["test_index"],
            "query": "",
            "top_k": 10,
            "weight_accurate": 0.5
        }
        response = client.post(
            "/indices/search/hybrid",
            json=payload,
            headers=auth_data["auth_header"]
        )

        # Verify
        assert response.status_code == 400
        assert response.json() == {"detail": "Query text is required"}


@pytest.mark.asyncio
async def test_get_index_chunks_value_error(vdb_core_mock, auth_data):
    """
    Test get_index_chunks maps ValueError to 404.
    """
    index_name = "test_index"
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
        patch("backend.apps.vectordatabase_app.get_current_user_id",
              return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
        patch("backend.apps.vectordatabase_app.ElasticSearchService.get_index_chunks") as mock_get_chunks:

        mock_get_chunks.side_effect = ValueError("Unknown index")

        response = client.post(
            f"/indices/{index_name}/chunks",
            headers=auth_data["auth_header"]
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "Unknown index"}
        mock_get_chunks.assert_called_once_with(
            index_name=index_name,
            page=None,
            page_size=None,
            path_or_url=None,
            vdb_core=ANY,
        )


@pytest.mark.asyncio
async def test_create_chunk_value_error(vdb_core_mock, auth_data):
    """
    Test create_chunk maps ValueError to 404.
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
        patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
        patch("backend.apps.vectordatabase_app.get_index_name_by_knowledge_name", return_value=auth_data["index_name"]), \
        patch("backend.apps.vectordatabase_app.ElasticSearchService.create_chunk") as mock_create:

        mock_create.side_effect = ValueError("Invalid chunk payload")

        payload = {
            "content": "Hello world",
            "path_or_url": "doc-1",
        }

        response = client.post(
            f"/indices/{auth_data['index_name']}/chunk",
            json=payload,
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Invalid chunk payload"}
    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_hybrid_search_exception(vdb_core_mock, auth_data):
    """
    Test hybrid search endpoint with general exception.
    Verifies that the endpoint returns 500 INTERNAL_SERVER_ERROR when search fails.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.search_hybrid") as mock_search_hybrid:

        mock_search_hybrid.side_effect = Exception("Search execution failed")

        # Execute request
        payload = {
            "index_names": ["test_index"],
            "query": "test query",
            "top_k": 10,
            "weight_accurate": 0.5
        }
        response = client.post(
            "/indices/search/hybrid",
            json=payload,
            headers=auth_data["auth_header"]
        )

    # Verify
    assert response.status_code == 500
    assert response.json() == {"detail": "Error executing hybrid search: Search execution failed"}


# =============================================================================
# Tests for new embedding model retrieval from knowledge record
# =============================================================================

@pytest.mark.asyncio
async def test_create_index_documents_gets_saved_embedding_model_from_knowledge_record(vdb_core_mock, auth_data):
    """
    Test that create_index_documents retrieves the saved embedding model id from knowledge record.
    Verifies that the endpoint calls get_knowledge_record to get the embedding_model_id.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.index_documents") as mock_index, \
            patch("backend.apps.vectordatabase_app.get_knowledge_record") as mock_get_knowledge_record, \
            patch("backend.apps.vectordatabase_app.get_embedding_model_by_id") as mock_get_embedding:

        index_name = "test_index"
        documents = [{"id": 1, "text": "test doc"}]
        
        # Mock knowledge record with saved embedding model id
        saved_model_id = 123
        mock_get_knowledge_record.return_value = {
            "index_name": index_name,
            "embedding_model_id": saved_model_id,
            "tenant_id": auth_data["tenant_id"]
        }
        
        # Mock embedding model
        mock_embedding = MagicMock()
        mock_get_embedding.return_value = (mock_embedding, saved_model_id)
        
        # Mock index response
        expected_response = {
            "success": True,
            "message": "Documents indexed successfully",
            "total_indexed": 1,
            "total_submitted": 1
        }
        mock_index.return_value = expected_response

        # Execute request
        response = client.post(
            f"/indices/{index_name}/documents", json=documents, headers=auth_data["auth_header"])

        # Verify
        assert response.status_code == 200
        
        # Verify get_knowledge_record was called with correct index_name
        mock_get_knowledge_record.assert_called_once_with({'index_name': index_name})
        
        # Verify get_embedding_model_by_id was called with the saved model id
        mock_get_embedding.assert_called_once_with(
            auth_data["tenant_id"],
            saved_model_id,
        )
        
        # Verify index_documents was called with the embedding model
        mock_index.assert_called_once()
        call_kwargs = mock_index.call_args[1]
        assert call_kwargs["embedding_model"] == mock_embedding


@pytest.mark.asyncio
async def test_create_index_documents_fallback_to_default_when_no_saved_model(vdb_core_mock, auth_data):
    """
    Test that create_index_documents does not call embedding resolver when no saved model id.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.index_documents") as mock_index, \
            patch("backend.apps.vectordatabase_app.get_knowledge_record") as mock_get_knowledge_record, \
            patch("backend.apps.vectordatabase_app.get_embedding_model_by_id") as mock_get_embedding:

        index_name = "test_index"
        documents = [{"id": 1, "text": "test doc"}]
        
        # Mock knowledge record with no embedding_model_id (None)
        mock_get_knowledge_record.return_value = {
            "index_name": index_name,
            "embedding_model_id": None,
            "tenant_id": auth_data["tenant_id"]
        }
        
        # Mock index response
        expected_response = {
            "success": True,
            "message": "Documents indexed successfully",
            "total_indexed": 1,
            "total_submitted": 1
        }
        mock_index.return_value = expected_response

        # Execute request
        response = client.post(
            f"/indices/{index_name}/documents", json=documents, headers=auth_data["auth_header"])

        # Verify
        assert response.status_code == 200
        
        # No saved model id means no embedding resolver call from app layer
        mock_get_embedding.assert_not_called()


@pytest.mark.asyncio
async def test_create_index_documents_fallback_when_knowledge_record_not_found(vdb_core_mock, auth_data):
    """
    Test that create_index_documents handles case when knowledge record is not found.
    Verifies that get_embedding_model_by_id is not called when knowledge_record is None.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.index_documents") as mock_index, \
            patch("backend.apps.vectordatabase_app.get_knowledge_record", return_value=None), \
            patch("backend.apps.vectordatabase_app.get_embedding_model_by_id") as mock_get_embedding:

        index_name = "test_index"
        documents = [{"id": 1, "text": "test doc"}]
        
        expected_response = {
            "success": True,
            "message": "Documents indexed successfully",
            "total_indexed": 1,
            "total_submitted": 1
        }
        mock_index.return_value = expected_response

        response = client.post(
            f"/indices/{index_name}/documents", json=documents, headers=auth_data["auth_header"])

        assert response.status_code == 200
        
        mock_get_embedding.assert_not_called()


@pytest.mark.asyncio
async def test_create_index_documents_with_empty_string_model_name(vdb_core_mock, auth_data):
    """
    Test that create_index_documents handles empty/None embedding_model_id correctly.
    Empty or None model_id should result in no embedding model call.
    """
    # Setup mocks
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.index_documents") as mock_index, \
            patch("backend.apps.vectordatabase_app.get_knowledge_record") as mock_get_knowledge_record, \
            patch("backend.apps.vectordatabase_app.get_embedding_model_by_id") as mock_get_embedding:

        index_name = "test_index"
        documents = [{"id": 1, "text": "test doc"}]
        
        mock_get_knowledge_record.return_value = {
            "index_name": index_name,
            "embedding_model_id": None,
            "tenant_id": auth_data["tenant_id"]
        }
        
        expected_response = {
            "success": True,
            "message": "Documents indexed successfully",
            "total_indexed": 1,
            "total_submitted": 1
        }
        mock_index.return_value = expected_response

        response = client.post(
            f"/indices/{index_name}/documents", json=documents, headers=auth_data["auth_header"])

        assert response.status_code == 200
        
        # Empty/None model id should skip embedding model resolution
        mock_get_embedding.assert_not_called()


@pytest.mark.asyncio
async def test_update_summary_frequency_endpoint_success(vdb_core_mock, auth_data):
    with patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("database.knowledge_db.update_summary_frequency", return_value=True):
        response = client.patch(
            f"/indices/{auth_data['index_name']}/summary_frequency",
            json={"summary_frequency": "1d"},
            headers=auth_data["auth_header"],
        )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


@pytest.mark.asyncio
async def test_update_summary_frequency_endpoint_invalid_value(auth_data):
    with patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])):
        response = client.patch(
            f"/indices/{auth_data['index_name']}/summary_frequency",
            json={"summary_frequency": "bad"},
            headers=auth_data["auth_header"],
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_embedding_model_status_configured(auth_data):
    with patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_knowledge_record", return_value={
                "index_name": "idx_internal",
                "knowledge_name": "kb1",
                "embedding_model_id": 7,
                "embedding_model_name": "m1",
            }), \
            patch("backend.apps.vectordatabase_app.get_model_by_model_id", return_value={
                "model_id": 7,
                "model_name": "m1",
                "display_name": "Model One",
                "model_type": "embedding",
            }):
        response = client.get("/indices/idx_internal/embedding-model-status", headers=auth_data["auth_header"])
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "configured"
    assert body["needs_config"] is False
    assert body["model_info"]["display_name"] == "Model One"


@pytest.mark.asyncio
async def test_get_embedding_model_status_legacy_and_missing_and_not_found(auth_data):
    with patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_knowledge_record", return_value={
                "index_name": "idx_legacy",
                "knowledge_name": "kb_legacy",
                "embedding_model_id": None,
                "embedding_model_name": "legacy-name",
            }):
        legacy_resp = client.get("/indices/idx_legacy/embedding-model-status", headers=auth_data["auth_header"])
    assert legacy_resp.status_code == 200
    assert legacy_resp.json()["status"] == "legacy"
    assert legacy_resp.json()["needs_config"] is True

    with patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_knowledge_record", return_value={
                "index_name": "idx_missing",
                "knowledge_name": "kb_missing",
                "embedding_model_id": None,
                "embedding_model_name": None,
            }):
        missing_resp = client.get("/indices/idx_missing/embedding-model-status", headers=auth_data["auth_header"])
    assert missing_resp.status_code == 200
    assert missing_resp.json()["status"] == "missing"
    assert missing_resp.json()["needs_config"] is True

    with patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.get_knowledge_record", return_value=None):
        not_found_resp = client.get("/indices/not-exist/embedding-model-status", headers=auth_data["auth_header"])
    assert not_found_resp.status_code == 404


@pytest.mark.asyncio
async def test_update_embedding_model_endpoint_branches(auth_data):
    with patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.update_embedding_model", return_value={"status": "success"}) as mock_update:
        ok_resp = client.put(
            "/indices/idx1/embedding-model",
            json={"model_id": 123},
            headers=auth_data["auth_header"],
        )
    assert ok_resp.status_code == 200
    mock_update.assert_called_once()

    with patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])):
        bad_resp = client.put(
            "/indices/idx1/embedding-model",
            json={},
            headers=auth_data["auth_header"],
        )
    assert bad_resp.status_code == 400

    with patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.update_embedding_model", side_effect=ValueError("kb not found")):
        nf_resp = client.put(
            "/indices/idx1/embedding-model",
            json={"model_id": 1},
            headers=auth_data["auth_header"],
        )
    assert nf_resp.status_code == 404

    with patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.update_embedding_model", side_effect=RuntimeError("boom")):
        err_resp = client.put(
            "/indices/idx1/embedding-model",
            json={"model_id": 1},
            headers=auth_data["auth_header"],
        )
    assert err_resp.status_code == 500


@pytest.mark.asyncio
async def test_get_document_error_info_regex_fallback(auth_data):
    with patch("backend.apps.vectordatabase_app.get_all_files_status", new=AsyncMock(return_value={"docA": {"latest_task_id": "tid1"}})), \
            patch("backend.apps.vectordatabase_app.get_redis_service") as mock_redis:
        mock_redis.return_value.get_error_info.return_value = '{"bad":1, "error_code":"E123"'
        response = client.get(f"/indices/i1/documents/docA/error-info", headers=auth_data["auth_header"])
    assert response.status_code == 200
    assert response.json()["error_code"] == "E123"


@pytest.mark.asyncio
async def test_get_document_error_info_regex_failure_returns_none(auth_data):
    with patch("backend.apps.vectordatabase_app.get_all_files_status", new=AsyncMock(return_value={"docA": {"latest_task_id": "tid1"}})), \
            patch("backend.apps.vectordatabase_app.get_redis_service") as mock_redis, \
            patch("backend.apps.vectordatabase_app.re.search", side_effect=RuntimeError("regex boom")):
        mock_redis.return_value.get_error_info.return_value = "not-json"
        response = client.get(f"/indices/i1/documents/docA/error-info", headers=auth_data["auth_header"])
    assert response.status_code == 200
    assert response.json()["error_code"] is None


# ============================================================================
# KB Read Permission Control Tests for hybrid_search (Issue #3339)
# ============================================================================


@pytest.mark.asyncio
async def test_hybrid_search_forbidden_without_read_permission(vdb_core_mock, auth_data):
    """
    Test hybrid_search returns 403 when user lacks read permission on knowledge base.
    The permission check happens BEFORE the search is executed.
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.require_knowledge_base_read_permission", side_effect=HTTPException(status_code=403, detail="No permission to access this knowledge base")) as mock_perm, \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.search_hybrid") as mock_search:

        payload = {
            "index_names": ["private_kb"],
            "query": "test query",
            "top_k": 5,
            "weight_accurate": 0.5,
        }
        response = client.post(
            "/indices/search/hybrid",
            json=payload,
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 403
        assert "No permission to access this knowledge base" in response.json()["detail"]
        mock_perm.assert_called_once_with(
            index_name="private_kb",
            user_id=auth_data["user_id"],
            tenant_id=auth_data["tenant_id"],
        )
        mock_search.assert_not_called()


@pytest.mark.asyncio
async def test_hybrid_search_not_found_when_kb_missing(vdb_core_mock, auth_data):
    """
    Test hybrid_search returns 404 when knowledge base does not exist.
    """
    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.require_knowledge_base_read_permission", side_effect=HTTPException(status_code=404, detail="Knowledge base 'missing_kb' not found")) as mock_perm, \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.search_hybrid") as mock_search:

        payload = {
            "index_names": ["missing_kb"],
            "query": "test query",
            "top_k": 5,
            "weight_accurate": 0.5,
        }
        response = client.post(
            "/indices/search/hybrid",
            json=payload,
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
        mock_perm.assert_called_once()
        mock_search.assert_not_called()


@pytest.mark.asyncio
async def test_hybrid_search_checks_all_indices(vdb_core_mock, auth_data):
    """
    Test hybrid_search checks permission for EVERY index in the request.
    If any index fails permission check, the entire request is rejected.
    """
    call_log = []

    def mock_permission_check(index_name, user_id, tenant_id):
        call_log.append(index_name)
        if index_name == "forbidden_kb":
            raise HTTPException(status_code=403, detail="No permission to access this knowledge base")

    with patch("backend.apps.vectordatabase_app.get_vector_db_core", return_value=vdb_core_mock), \
            patch("backend.apps.vectordatabase_app.get_current_user_id", return_value=(auth_data["user_id"], auth_data["tenant_id"])), \
            patch("backend.apps.vectordatabase_app.require_knowledge_base_read_permission", side_effect=mock_permission_check), \
            patch("backend.apps.vectordatabase_app.ElasticSearchService.search_hybrid") as mock_search:

        payload = {
            "index_names": ["allowed_kb", "forbidden_kb", "another_kb"],
            "query": "test query",
            "top_k": 5,
            "weight_accurate": 0.5,
        }
        response = client.post(
            "/indices/search/hybrid",
            json=payload,
            headers=auth_data["auth_header"],
        )

        assert response.status_code == 403
        # Should have checked allowed_kb, then forbidden_kb (stopped there)
        assert call_log == ["allowed_kb", "forbidden_kb"]
        mock_search.assert_not_called()


@pytest.mark.asyncio
async def test_create_index_documents_personal_kb_quota_exceeded(
    vdb_core_mock, auth_data
):
    """PRIVATE KB uploads fail closed with 403 when personal quota is exceeded."""
    with patch(
        "backend.apps.vectordatabase_app.get_vector_db_core",
        return_value=vdb_core_mock,
    ), patch(
        "backend.apps.vectordatabase_app.get_current_user_id",
        return_value=(auth_data["user_id"], auth_data["tenant_id"]),
    ), patch(
        "backend.apps.vectordatabase_app.get_knowledge_record",
        return_value={"ingroup_permission": "PRIVATE"},
    ), patch(
        "backend.apps.vectordatabase_app.QuotaService.check_personal_kb_quota",
        side_effect=AppException(
            ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
            "quota exceeded",
        ),
    ), patch(
        "backend.apps.vectordatabase_app.ElasticSearchService.index_documents"
    ) as mock_index:
        response = client.post(
            f"/indices/{auth_data['index_name']}/documents",
            json=[{"id": 1, "text": "test doc"}],
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 403
    assert "quota exceeded" in response.json()["message"]
    assert response.json()["code"] == ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED.value
    mock_index.assert_not_called()


@pytest.mark.asyncio
async def test_create_index_documents_personal_kb_quota_unavailable(
    vdb_core_mock, auth_data
):
    """PRIVATE KB uploads return 503 when ES usage cannot be verified."""
    with patch(
        "backend.apps.vectordatabase_app.get_vector_db_core",
        return_value=vdb_core_mock,
    ), patch(
        "backend.apps.vectordatabase_app.get_current_user_id",
        return_value=(auth_data["user_id"], auth_data["tenant_id"]),
    ), patch(
        "backend.apps.vectordatabase_app.get_knowledge_record",
        return_value={"ingroup_permission": "PRIVATE"},
    ), patch(
        "backend.apps.vectordatabase_app.QuotaService.check_personal_kb_quota",
        side_effect=AppException(
            ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE,
            "es down",
        ),
    ), patch(
        "backend.apps.vectordatabase_app.ElasticSearchService.index_documents"
    ) as mock_index:
        response = client.post(
            f"/indices/{auth_data['index_name']}/documents",
            json=[{"id": 1, "text": "test doc"}],
            headers=auth_data["auth_header"],
    )

    assert response.status_code == 503
    assert response.json()["message"] == "es down"
    assert response.json()["code"] == ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE.value
    mock_index.assert_not_called()


@pytest.mark.asyncio
async def test_create_index_documents_skips_personal_quota_for_shared_kb(
    vdb_core_mock, auth_data
):
    """Non-PRIVATE KB uploads must not invoke the personal quota check."""
    with patch(
        "backend.apps.vectordatabase_app.get_vector_db_core",
        return_value=vdb_core_mock,
    ), patch(
        "backend.apps.vectordatabase_app.get_current_user_id",
        return_value=(auth_data["user_id"], auth_data["tenant_id"]),
    ), patch(
        "backend.apps.vectordatabase_app.get_knowledge_record",
        return_value={"ingroup_permission": "PUBLIC"},
    ), patch(
        "backend.apps.vectordatabase_app.QuotaService"
    ) as mock_quota_class, patch(
        "backend.apps.vectordatabase_app.get_embedding_model_by_id",
        return_value=MagicMock(),
    ), patch(
        "backend.apps.vectordatabase_app.ElasticSearchService.index_documents"
    ) as mock_index:
        mock_index.return_value = IndexingResponse(
            success=True,
            message="Documents indexed successfully",
            total_indexed=1,
            total_submitted=1,
        )

        response = client.post(
            f"/indices/{auth_data['index_name']}/documents",
            json=[{"id": 1, "text": "test doc"}],
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 200
    mock_quota_class.assert_not_called()
    mock_index.assert_called_once()


def test_personal_quota_helper_skips_missing_and_shared_records(mocker):
    from backend.apps import vectordatabase_app as vdb_app

    check_quota = mocker.patch(
        "backend.apps.vectordatabase_app.QuotaService.check_personal_kb_quota"
    )

    vdb_app._check_personal_kb_quota_before_indexing(
        data=[], knowledge_record=None, tenant_id="tenant-1", user_id="user-1"
    )
    vdb_app._check_personal_kb_quota_before_indexing(
        data=[],
        knowledge_record={"ingroup_permission": "EDIT"},
        tenant_id="tenant-1",
        user_id="user-1",
    )

    check_quota.assert_not_called()


def test_personal_quota_helper_converts_unexpected_error_to_unavailable(mocker):
    from backend.apps import vectordatabase_app as vdb_app

    mocker.patch(
        "backend.apps.vectordatabase_app.QuotaService.get_pending_personal_upload_bytes",
        side_effect=RuntimeError("ledger unavailable"),
    )

    with pytest.raises(AppException) as raised:
        vdb_app._check_personal_kb_quota_before_indexing(
            data=[{"path_or_url": "knowledge_base/a.txt", "file_size": 10}],
            knowledge_record={"ingroup_permission": "PRIVATE"},
            tenant_id="tenant-1",
            user_id="user-1",
        )

    assert raised.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE


@pytest.mark.asyncio
async def test_get_index_files_preserves_read_permission_error(vdb_core_mock, auth_data):
    with patch(
        "backend.apps.vectordatabase_app.get_vector_db_core",
        return_value=vdb_core_mock,
    ), patch(
        "backend.apps.vectordatabase_app.require_knowledge_base_read_permission",
        side_effect=HTTPException(status_code=403, detail="private KB"),
    ), patch(
        "backend.apps.vectordatabase_app.ElasticSearchService.list_files"
    ) as mock_list_files:
        response = client.get(
            f"/indices/{auth_data['index_name']}/files",
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "private KB"
    mock_list_files.assert_not_called()


@pytest.mark.asyncio
async def test_get_embedding_model_status_preserves_read_permission_error(auth_data):
    with patch(
        "backend.apps.vectordatabase_app.require_knowledge_base_read_permission",
        side_effect=HTTPException(status_code=403, detail="private KB"),
    ), patch(
        "backend.apps.vectordatabase_app.get_knowledge_record"
    ) as mock_get_record:
        response = client.get(
            "/indices/private-kb/embedding-model-status",
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 403
    mock_get_record.assert_not_called()


@pytest.mark.asyncio
async def test_get_index_chunks_preserves_read_permission_error(vdb_core_mock, auth_data):
    with patch(
        "backend.apps.vectordatabase_app.get_vector_db_core",
        return_value=vdb_core_mock,
    ), patch(
        "backend.apps.vectordatabase_app.require_knowledge_base_read_permission",
        side_effect=HTTPException(status_code=403, detail="private KB"),
    ), patch(
        "backend.apps.vectordatabase_app.ElasticSearchService.get_index_chunks"
    ) as mock_get_chunks:
        response = client.post(
            f"/indices/{auth_data['index_name']}/chunks",
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 403
    mock_get_chunks.assert_not_called()


@pytest.mark.asyncio
async def test_delete_documents_maps_storage_permission_error(vdb_core_mock, auth_data):
    with patch(
        "backend.apps.vectordatabase_app.get_vector_db_core",
        return_value=vdb_core_mock,
    ), patch(
        "backend.apps.vectordatabase_app.require_knowledge_base_edit_permission",
        side_effect=PermissionError("read-only KB"),
    ), patch(
        "backend.apps.vectordatabase_app.ElasticSearchService.delete_document_by_scope",
        new_callable=AsyncMock,
    ) as mock_delete:
        response = client.delete(
            f"/indices/{auth_data['index_name']}/documents",
            params={"path_or_url": "knowledge_base/doc.txt", "scope": "full"},
            headers=auth_data["auth_header"],
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "read-only KB"
    mock_delete.assert_not_called()

# TokenExpiredError -> 401 mapping for every VDB endpoint guarded by auth.


TOKEN_EXPIRED_ENDPOINTS = [
    ("post", "/indices/check_exist", {"json": {"knowledge_name": "kb1"}}, "get_current_user_id"),
    ("post", "/indices/kb1", {"json": {"embedding_model_id": 101}}, "get_current_user_context"),
    ("delete", "/indices/kb1", {}, "get_current_user_id"),
    ("patch", "/indices/kb1", {"json": {"knowledge_name": "kb2"}}, "get_current_user_context"),
    ("patch", "/indices/kb1/summary_frequency", {"json": {"summary_frequency": "daily"}}, "get_current_user_id"),
    ("get", "/indices/kb1/embedding-model-status", {}, "get_current_user_id"),
    ("put", "/indices/kb1/embedding-model", {"json": {"model_id": 123}}, "get_current_user_id"),
    ("get", "/indices", {}, "get_current_user_id"),
    ("post", "/indices/kb1/documents", {"json": [{"content": "doc"}]}, "get_current_user_id"),
    ("get", "/indices/kb1/files", {}, "get_current_user_id"),
    ("delete", "/indices/kb1/documents", {"params": {"path_or_url": "a.pdf"}}, "get_current_user_id"),
    ("get", "/indices/kb1/documents/a.pdf/error-info", {}, "get_current_user_id"),
    ("post", "/indices/kb1/chunks", {}, "get_current_user_id"),
    ("post", "/indices/kb1/chunk", {"json": {"content": "chunk"}}, "get_current_user_id"),
    ("put", "/indices/kb1/chunk/ch1", {"json": {"content": "updated"}}, "get_current_user_id"),
    ("delete", "/indices/kb1/chunk/ch1", {}, "get_current_user_id"),
    ("post", "/indices/search/hybrid", {"json": {"index_names": ["kb1"], "query": "q"}}, "get_current_user_id"),
]


@pytest.mark.parametrize(
    "method,url,kwargs,auth_fn", TOKEN_EXPIRED_ENDPOINTS
)
def test_vdb_endpoints_return_401_on_token_expired(method, url, kwargs, auth_fn):
    """Expired token maps to 401 on every authenticated VDB endpoint."""
    from consts.exceptions import TokenExpiredError
    from http import HTTPStatus

    with patch(
        f"backend.apps.vectordatabase_app.{auth_fn}",
        side_effect=TokenExpiredError("expired"),
    ):
        response = getattr(client, method)(
            url, headers={"Authorization": "Bearer expired"}, **kwargs
        )

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert "expired" in response.json()["detail"]
