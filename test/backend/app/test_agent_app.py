import atexit
from unittest.mock import patch, Mock, MagicMock, ANY
import os
import sys
import types
import warnings

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

# Filter out deprecation warnings from third-party libraries
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pyiceberg")
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning:pyiceberg.*")

# Dynamically determine the backend path - MUST BE FIRST
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.insert(0, backend_dir)

# Mock boto3 before importing backend modules
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.minio_client', minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Apply patches before importing any app modules (similar to test_config_app.py)
patches = [
    # Mock database sessions
    patch('backend.database.client.get_db_session', return_value=Mock())
]

for p in patches:
    p.start()

# Import target endpoints with all external dependencies patched
from apps.agent_app import agent_config_router, agent_runtime_router

# Mock external dependencies before importing the modules that use them
# Stub nexent.core.agents.agent_model.ToolConfig to satisfy type imports in consts.model
agent_model_stub = types.ModuleType("agent_model")


class ToolConfig:  # minimal stub for type reference
    pass


agent_model_stub.ToolConfig = ToolConfig

# Mock monitoring modules
monitoring_stub = types.ModuleType("monitor")
monitoring_manager_mock = pytest.importorskip("unittest.mock").MagicMock()

# Define a decorator that simply returns the original function unchanged


def pass_through_decorator(*args, **kwargs):
    def decorator(func):
        return func
    return decorator


monitoring_manager_mock.monitor_endpoint = pass_through_decorator
monitoring_manager_mock.monitor_llm_call = pass_through_decorator
monitoring_manager_mock.setup_fastapi_app = pytest.importorskip(
    "unittest.mock").MagicMock(return_value=True)
monitoring_manager_mock.configure = pytest.importorskip(
    "unittest.mock").MagicMock()
monitoring_manager_mock.add_span_event = pytest.importorskip(
    "unittest.mock").MagicMock()
monitoring_manager_mock.set_span_attributes = pytest.importorskip(
    "unittest.mock").MagicMock()

monitoring_stub.get_monitoring_manager = lambda: monitoring_manager_mock
monitoring_stub.monitoring_manager = monitoring_manager_mock
monitoring_stub.MonitoringManager = pytest.importorskip(
    "unittest.mock").MagicMock
monitoring_stub.MonitoringConfig = pytest.importorskip(
    "unittest.mock").MagicMock

# Ensure module hierarchy exists in sys.modules
sys.modules['nexent'] = types.ModuleType('nexent')
sys.modules['nexent.core'] = types.ModuleType('nexent.core')
sys.modules['nexent.core.agents'] = types.ModuleType('nexent.core.agents')
sys.modules['nexent.core.agents.agent_model'] = agent_model_stub
sys.modules['nexent.monitor'] = monitoring_stub
sys.modules['nexent.monitor.monitoring'] = monitoring_stub
sys.modules['database.client'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['database.agent_db'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['agents.create_agent_info'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['nexent.core.agents.run_agent'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['supabase'] = pytest.importorskip("unittest.mock").MagicMock()
sys.modules['utils.auth_utils'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['utils.config_utils'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['utils.thread_utils'] = pytest.importorskip(
    "unittest.mock").MagicMock()
# Mock utils.monitoring to return our monitoring_manager_mock
utils_monitoring_mock = pytest.importorskip("unittest.mock").MagicMock()
utils_monitoring_mock.monitoring_manager = monitoring_manager_mock
utils_monitoring_mock.setup_fastapi_app = pytest.importorskip(
    "unittest.mock").MagicMock(return_value=True)
sys.modules['utils.monitoring'] = utils_monitoring_mock
sys.modules['agents.agent_run_manager'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['services.agent_service'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['services.conversation_management_service'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['services.memory_config_service'] = pytest.importorskip(
    "unittest.mock").MagicMock()

# Now safe to import app modules after all mocks are set up

# Stop all patches at the end of the module


def stop_patches():
    for p in patches:
        p.stop()


atexit.register(stop_patches)

# Create FastAPI apps for runtime and config routers
runtime_app = FastAPI()
runtime_app.include_router(agent_runtime_router)
runtime_client = TestClient(runtime_app)

config_app = FastAPI()
config_app.include_router(agent_config_router)
config_client = TestClient(config_app)


@pytest.fixture
def mock_auth_header():
    return {"Authorization": "Bearer test_token"}


@pytest.fixture
def mock_conversation_id():
    return 123


@pytest.mark.asyncio
async def test_agent_run_api(mocker, mock_auth_header):
    """Test agent_run_api endpoint."""
    mock_run_agent_stream = mocker.patch(
        "apps.agent_app.run_agent_stream", new_callable=mocker.AsyncMock)

    # Mock the streaming response
    async def mock_stream():
        yield b"data: chunk1\n\n"
        yield b"data: chunk2\n\n"

    mock_run_agent_stream.return_value = StreamingResponse(
        mock_stream(), media_type="text/event-stream")

    response = runtime_client.post(
        "/agent/run",
        json={
            "agent_id": 1,
            "conversation_id": 123,
            "query": "test query",
            "history": [],
            "minio_files": [],
            "is_debug": False,
        },
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_run_agent_stream.assert_called_once()
    assert "text/event-stream" in response.headers["content-type"]

    # Check streamed content
    content = response.content.decode()
    assert "data: chunk1" in content
    assert "data: chunk2" in content


def test_agent_stop_api_success(mocker, mock_conversation_id):
    """Test agent_stop_api success case."""
    # Mock the authentication function to return user_id
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")

    mock_stop_tasks = mocker.patch("apps.agent_app.stop_agent_tasks")
    mock_stop_tasks.return_value = {"status": "success"}

    response = runtime_client.get(
        f"/agent/stop/{mock_conversation_id}",
        headers={"Authorization": "Bearer test_token"}
    )

    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with("Bearer test_token")
    mock_stop_tasks.assert_called_once_with(
        mock_conversation_id, "test_user_id")
    assert response.json()["status"] == "success"


def test_agent_stop_api_not_found(mocker, mock_conversation_id):
    """Test agent_stop_api not found case."""
    # Mock the authentication function to return user_id
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")

    mock_stop_tasks = mocker.patch("apps.agent_app.stop_agent_tasks")
    mock_stop_tasks.return_value = {"status": "error"}  # Simulate not found

    response = runtime_client.get(
        f"/agent/stop/{mock_conversation_id}",
        headers={"Authorization": "Bearer test_token"}
    )

    # The app should raise HTTPException for non-success status
    assert response.status_code == 400
    mock_get_user_id.assert_called_once_with("Bearer test_token")
    mock_stop_tasks.assert_called_once_with(
        mock_conversation_id, "test_user_id")
    assert "no running agent or preprocess tasks found" in response.json()[
        "detail"]


def test_search_agent_info_api_success(mocker, mock_auth_header):
    """Test search_agent_info_api success case without tenant_id query parameter (uses auth tenant_id) and default version_no=0."""
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.return_value = {"agent_id": 123, "name": "Test Agent"}

    # Test the endpoint without tenant_id query parameter and without version_no (defaults to 0)
    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 123},  # agent_id as body parameter, version_no defaults to 0
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    # Should use auth tenant_id when query parameter is not provided, and default version_no=0
    mock_get_agent_info.assert_called_once_with(123, "auth_tenant_id", 0)
    assert response.json()["agent_id"] == 123
    assert response.json()["name"] == "Test Agent"


def test_search_agent_info_api_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test search_agent_info_api success case with explicit tenant_id query parameter and default version_no=0."""
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=mocker.AsyncMock)
    # Mock return values - auth tenant_id is different from explicit tenant_id
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.return_value = {
        "agent_id": 456,
        "name": "Test Agent with Explicit Tenant",
        "display_name": "Display Name"
    }

    # Test the endpoint with explicit tenant_id query parameter
    explicit_tenant_id = "explicit_tenant_789"
    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 456},  # agent_id as body parameter, version_no defaults to 0
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    # Should use explicit tenant_id when provided, not auth tenant_id, and default version_no=0
    mock_get_agent_info.assert_called_once_with(456, explicit_tenant_id, 0)
    assert response.json()["agent_id"] == 456
    assert response.json()["name"] == "Test Agent with Explicit Tenant"
    assert response.json()["display_name"] == "Display Name"


def test_search_agent_info_api_exception(mocker, mock_auth_header):
    """Test search_agent_info_api exception handling without tenant_id query parameter and default version_no=0."""
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.side_effect = Exception("Test error")

    # Test the endpoint without tenant_id query parameter
    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 123},  # version_no defaults to 0
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_get_agent_info.assert_called_once_with(123, "auth_tenant_id", 0)
    assert "Agent search info error" in response.json()["detail"]


def test_search_agent_info_api_exception_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test search_agent_info_api exception handling with explicit tenant_id query parameter and default version_no=0."""
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=mocker.AsyncMock)
    # Mock return values and exception
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.side_effect = Exception("Test error with explicit tenant")

    # Test the endpoint with explicit tenant_id query parameter
    explicit_tenant_id = "explicit_tenant_999"
    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 789},  # version_no defaults to 0
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    # Should use explicit tenant_id even when exception occurs, and default version_no=0
    mock_get_agent_info.assert_called_once_with(789, explicit_tenant_id, 0)
    assert "Agent search info error" in response.json()["detail"]


def test_search_agent_info_api_with_version_no(mocker, mock_auth_header):
    """Test search_agent_info_api success case with explicit version_no parameter."""
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.return_value = {"agent_id": 123, "name": "Test Agent", "version_no": 2}

    # Test the endpoint with explicit version_no in body
    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 123, "version_no": 2},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    # Should use explicit version_no when provided
    mock_get_agent_info.assert_called_once_with(123, "auth_tenant_id", 2)
    assert response.json()["agent_id"] == 123
    assert response.json()["version_no"] == 2


def test_search_agent_info_api_with_version_no_and_tenant_id(mocker, mock_auth_header):
    """Test search_agent_info_api success case with both explicit version_no and tenant_id."""
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.return_value = {
        "agent_id": 456,
        "name": "Test Agent",
        "version_no": 3,
        "display_name": "Display Name"
    }

    # Test the endpoint with both explicit version_no and tenant_id
    explicit_tenant_id = "explicit_tenant_123"
    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 456, "version_no": 3},
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    # Should use both explicit tenant_id and version_no
    mock_get_agent_info.assert_called_once_with(456, explicit_tenant_id, 3)
    assert response.json()["agent_id"] == 456
    assert response.json()["version_no"] == 3


def test_search_agent_info_api_exception_with_version_no(mocker, mock_auth_header):
    """Test search_agent_info_api exception handling with explicit version_no."""
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.side_effect = Exception("Test error with version_no")

    # Test the endpoint with explicit version_no
    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 123, "version_no": 5},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_get_agent_info.assert_called_once_with(123, "auth_tenant_id", 5)
    assert "Agent search info error" in response.json()["detail"]


def test_get_creating_sub_agent_info_api_success(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_get_creating_agent = mocker.patch(
        "apps.agent_app.get_creating_sub_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_get_creating_agent.return_value = {"agent_id": 456}

    # Test the endpoint - this is a GET request
    response = config_client.get(
        "/agent/get_creating_sub_agent_id",
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_creating_agent.assert_called_once_with(
        mock_auth_header["Authorization"])
    assert response.json()["agent_id"] == 456


def test_get_creating_sub_agent_info_api_exception(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_get_creating_agent = mocker.patch(
        "apps.agent_app.get_creating_sub_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_get_creating_agent.side_effect = Exception("Test error")

    # Test the endpoint - this is a GET request
    response = config_client.get(
        "/agent/get_creating_sub_agent_id",
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    assert "Agent create error" in response.json()["detail"]


def test_update_agent_info_api_success(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_update_agent = mocker.patch(
        "apps.agent_app.update_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_update_agent.return_value = None

    # Test the endpoint
    response = config_client.post(
        "/agent/update",
        json={"agent_id": 123, "name": "Updated Agent",
              "display_name": "Updated Display Name"},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_update_agent.assert_called_once()
    assert response.json() == {}


def test_update_agent_info_api_exception(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_update_agent = mocker.patch(
        "apps.agent_app.update_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_update_agent.side_effect = Exception("Test error")

    # Test the endpoint
    response = config_client.post(
        "/agent/update",
        json={"agent_id": 123, "name": "Updated Agent",
              "display_name": "Updated Display Name"},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    assert "Agent update error" in response.json()["detail"]


def test_delete_agent_api_success(mocker, mock_auth_header):
    """Test delete_agent_api success case without tenant_id query parameter (uses auth tenant_id)."""
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_delete_agent = mocker.patch(
        "apps.agent_app.delete_agent_impl", new_callable=mocker.AsyncMock)
    # Mock return values
    mock_get_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_delete_agent.return_value = None

    # Test the endpoint without tenant_id query parameter
    response = config_client.request(
        "DELETE",
        "/agent",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"], ANY)
    # Should use auth tenant_id when query parameter is not provided
    mock_delete_agent.assert_called_once_with(123, "test_tenant", "test_user")
    assert response.json() == {}


def test_delete_agent_api_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test delete_agent_api success case with explicit tenant_id query parameter."""
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_delete_agent = mocker.patch(
        "apps.agent_app.delete_agent_impl", new_callable=mocker.AsyncMock)
    # Mock return values - auth tenant_id is different from explicit tenant_id
    mock_get_user_info.return_value = ("test_user", "auth_tenant", "en")
    mock_delete_agent.return_value = None

    # Test the endpoint with explicit tenant_id query parameter
    explicit_tenant_id = "explicit_tenant_123"
    response = config_client.request(
        "DELETE",
        "/agent",
        json={"agent_id": 456},
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"], ANY)
    # Should use explicit tenant_id when provided, not auth tenant_id
    mock_delete_agent.assert_called_once_with(456, explicit_tenant_id, "test_user")
    assert response.json() == {}


def test_delete_agent_api_exception(mocker, mock_auth_header):
    """Test delete_agent_api exception handling without tenant_id query parameter."""
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_delete_agent = mocker.patch(
        "apps.agent_app.delete_agent_impl", new_callable=mocker.AsyncMock)
    mock_logger = mocker.patch("apps.agent_app.logger")
    # Mock return values and exception
    mock_get_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_delete_agent.side_effect = Exception("Test error")

    # Test the endpoint without tenant_id query parameter
    response = config_client.request(
        "DELETE",
        "/agent",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"], ANY)
    mock_delete_agent.assert_called_once_with(123, "test_tenant", "test_user")
    assert "Agent delete error" in response.json()["detail"]
    # Verify error was logged
    mock_logger.error.assert_called_once_with("Agent delete error: Test error")


def test_delete_agent_api_exception_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test delete_agent_api exception handling with explicit tenant_id query parameter."""
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_delete_agent = mocker.patch(
        "apps.agent_app.delete_agent_impl", new_callable=mocker.AsyncMock)
    mock_logger = mocker.patch("apps.agent_app.logger")
    # Mock return values and exception
    mock_get_user_info.return_value = ("test_user", "auth_tenant", "en")
    mock_delete_agent.side_effect = Exception("Test error with explicit tenant")

    # Test the endpoint with explicit tenant_id query parameter
    explicit_tenant_id = "explicit_tenant_456"
    response = config_client.request(
        "DELETE",
        "/agent",
        json={"agent_id": 789},
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"], ANY)
    # Should use explicit tenant_id even when exception occurs
    mock_delete_agent.assert_called_once_with(789, explicit_tenant_id, "test_user")
    assert "Agent delete error" in response.json()["detail"]
    # Verify error was logged
    mock_logger.error.assert_called_once_with("Agent delete error: Test error with explicit tenant")


@pytest.mark.asyncio
async def test_export_agent_api_success(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_export_agent = mocker.patch(
        "apps.agent_app.export_agent_impl", new_callable=mocker.AsyncMock)
    mock_export_agent.return_value = '{"agent_id": 123, "name": "Test Agent"}'

    # Test the endpoint
    response = config_client.post(
        "/agent/export",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_export_agent.assert_called_once_with(
        123, mock_auth_header["Authorization"])
    assert response.json()["code"] == 0
    assert response.json()["message"] == "success"


@pytest.mark.asyncio
async def test_export_agent_api_exception(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_export_agent = mocker.patch(
        "apps.agent_app.export_agent_impl", new_callable=mocker.AsyncMock)
    mock_export_agent.side_effect = Exception("Test error")

    # Test the endpoint
    response = config_client.post(
        "/agent/export",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    assert "Agent export error" in response.json()["detail"]


def test_import_agent_api_success(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_import_agent = mocker.patch(
        "apps.agent_app.import_agent_impl", new_callable=mocker.AsyncMock)
    mock_import_agent.return_value = None

    # Test the endpoint - following the ExportAndImportDataFormat structure
    response = config_client.post(
        "/agent/import",
        json={
            "agent_info": {
                "agent_id": 123,
                "agent_info": {
                    "test_agent": {
                        "agent_id": 123,
                        "name": "Imported Agent",
                        "description": "Test description",
                        "business_description": "Test business",
                        "model_name": "gpt-4",
                        "max_steps": 10,
                        "provide_run_summary": True,
                        "duty_prompt": "Test duty prompt",
                        "constraint_prompt": "Test constraint prompt",
                        "few_shots_prompt": "Test few shots prompt",
                        "enabled": True,
                        "tools": [],
                        "managed_agents": []
                    }
                },
                "mcp_info": []
            }
        },
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_import_agent.assert_called_once()
    args, kwargs = mock_import_agent.call_args
    # The function signature is import_agent_impl(request.agent_info, authorization)
    assert args[1] == mock_auth_header["Authorization"]
    assert response.json() == {}


def test_import_agent_api_exception(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_import_agent = mocker.patch(
        "apps.agent_app.import_agent_impl", new_callable=mocker.AsyncMock)
    mock_import_agent.side_effect = Exception("Test error")

    # Test the endpoint - following the ExportAndImportDataFormat structure
    response = config_client.post(
        "/agent/import",
        json={
            "agent_info": {
                "agent_id": 123,
                "agent_info": {
                    "test_agent": {
                        "agent_id": 123,
                        "name": "Imported Agent",
                        "description": "Test description",
                        "business_description": "Test business",
                        "model_name": "gpt-4",
                        "max_steps": 10,
                        "provide_run_summary": True,
                        "duty_prompt": "Test duty prompt",
                        "constraint_prompt": "Test constraint prompt",
                        "few_shots_prompt": "Test few shots prompt",
                        "enabled": True,
                        "tools": [],
                        "managed_agents": []
                    }
                },
                "mcp_info": []
            }
        },
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    assert "Agent import error" in response.json()["detail"]


def test_list_all_agent_info_api_success(mocker, mock_auth_header):
    """Test list_all_agent_info_api success case without tenant_id query parameter (uses auth tenant_id)."""
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "apps.agent_app.list_all_agent_info_impl", new_callable=mocker.AsyncMock)
    # Mock return values
    mock_get_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_list_all_agent.return_value = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Test agent 1",
            "group_ids": [],
            "permission": "EDIT",
            "is_available": True,
            "unavailable_reasons": []
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Test agent 2",
            "group_ids": [1, 2, 3],
            "permission": "READ_ONLY",
            "is_available": True,
            "unavailable_reasons": []
        }
    ]

    # Test the endpoint without tenant_id query parameter
    response = config_client.get(
        "/agent/list",
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"], ANY)
    # Should use auth tenant_id when query parameter is not provided
    mock_list_all_agent.assert_called_once_with(tenant_id="test_tenant", user_id="test_user")
    assert len(response.json()) == 2
    assert response.json()[0]["agent_id"] == 1
    assert response.json()[0]["display_name"] == "Display Agent 1"
    assert response.json()[0]["group_ids"] == []
    assert response.json()[0]["permission"] == "EDIT"
    assert response.json()[1]["name"] == "Agent 2"
    assert response.json()[1]["display_name"] == "Display Agent 2"
    assert response.json()[1]["group_ids"] == [1, 2, 3]
    assert response.json()[1]["permission"] == "READ_ONLY"


def test_list_all_agent_info_api_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test list_all_agent_info_api success case with explicit tenant_id query parameter."""
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "apps.agent_app.list_all_agent_info_impl", new_callable=mocker.AsyncMock)
    # Mock return values - auth tenant_id is different from explicit tenant_id
    mock_get_user_info.return_value = ("test_user", "auth_tenant", "en")
    mock_list_all_agent.return_value = [
        {
            "agent_id": 3,
            "name": "Agent 3",
            "display_name": "Display Agent 3",
            "description": "Test agent 3",
            "group_ids": [4, 5],
            "permission": "EDIT",
            "is_available": True,
            "unavailable_reasons": []
        }
    ]

    # Test the endpoint with explicit tenant_id query parameter
    explicit_tenant_id = "explicit_tenant_123"
    response = config_client.get(
        "/agent/list",
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"], ANY)
    # Should use explicit tenant_id when provided, not auth tenant_id
    mock_list_all_agent.assert_called_once_with(tenant_id=explicit_tenant_id, user_id="test_user")
    assert len(response.json()) == 1
    assert response.json()[0]["agent_id"] == 3
    assert response.json()[0]["display_name"] == "Display Agent 3"
    assert response.json()[0]["group_ids"] == [4, 5]


def test_list_all_agent_info_api_exception(mocker, mock_auth_header):
    """Test list_all_agent_info_api exception handling without tenant_id query parameter."""
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "apps.agent_app.list_all_agent_info_impl", new_callable=mocker.AsyncMock)
    # Mock return values and exception
    mock_get_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_list_all_agent.side_effect = Exception("Test error")

    # Test the endpoint without tenant_id query parameter
    response = config_client.get(
        "/agent/list",
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"], ANY)
    mock_list_all_agent.assert_called_once_with(tenant_id="test_tenant", user_id="test_user")
    assert "Agent list error" in response.json()["detail"]


def test_list_all_agent_info_api_exception_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test list_all_agent_info_api exception handling with explicit tenant_id query parameter."""
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "apps.agent_app.list_all_agent_info_impl", new_callable=mocker.AsyncMock)
    # Mock return values and exception
    mock_get_user_info.return_value = ("test_user", "auth_tenant", "en")
    mock_list_all_agent.side_effect = Exception("Test error with explicit tenant")

    # Test the endpoint with explicit tenant_id query parameter
    explicit_tenant_id = "explicit_tenant_456"
    response = config_client.get(
        "/agent/list",
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"], ANY)
    # Should use explicit tenant_id even when exception occurs
    mock_list_all_agent.assert_called_once_with(tenant_id=explicit_tenant_id, user_id="test_user")
    assert "Agent list error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_export_agent_api_detailed(mocker, mock_auth_header):
    """Detailed testing of export_agent_api function, including ConversationResponse construction"""
    # Setup mocks using pytest-mock
    mock_export_agent = mocker.patch(
        "apps.agent_app.export_agent_impl", new_callable=mocker.AsyncMock)

    # Setup mocks - return complex JSON data
    agent_data = {
        "agent_id": 456,
        "name": "Complex Agent",
        "description": "Detailed testing",
        "tools": [{"id": 1, "name": "tool1"}, {"id": 2, "name": "tool2"}],
        "managed_agents": [789, 101],
        "other_fields": "some values"
    }
    mock_export_agent.return_value = agent_data

    # Test with complex data
    response = config_client.post(
        "/agent/export",
        json={"agent_id": 456},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_export_agent.assert_called_once_with(
        456, mock_auth_header["Authorization"])

    # Verify correct construction of ConversationResponse
    response_data = response.json()
    assert response_data["code"] == 0
    assert response_data["message"] == "success"
    assert response_data["data"] == agent_data


@pytest.mark.asyncio
async def test_export_agent_api_empty_response(mocker, mock_auth_header):
    """Test export_agent_api handling empty response"""
    # Setup mocks using pytest-mock
    mock_export_agent = mocker.patch(
        "apps.agent_app.export_agent_impl", new_callable=mocker.AsyncMock)

    # Setup mock to return empty data
    mock_export_agent.return_value = {}

    # Send request
    response = config_client.post(
        "/agent/export",
        json={"agent_id": 789},
        headers=mock_auth_header
    )

    # Verify
    assert response.status_code == 200
    mock_export_agent.assert_called_once_with(
        789, mock_auth_header["Authorization"])

    # Verify empty data can also be correctly wrapped in ConversationResponse
    response_data = response.json()
    assert response_data["code"] == 0
    assert response_data["message"] == "success"
    assert response_data["data"] == {}


def _alias_services_for_tests():
    """
    Provide fallback aliases for dynamic `services.agent_service` imports used by the routers.
    Map `backend.services.*` modules to `services.*` so mocker.patch can locate them.
    """
    import sys
    try:
        import backend.services as b_services
        import backend.services.agent_service as b_agent_service
        # Map both the package and submodule for compatibility
        sys.modules['services'] = b_services
        sys.modules['services.agent_service'] = b_agent_service
    except Exception:
        # If the project already supports direct imports, ignore the failure
        pass


def test_get_agent_call_relationship_api_success(mocker, mock_auth_header):
    # Patch authentication helper
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_user_id.return_value = ("user_id_x", "tenant_abc")

    # Patch the implementation referenced from the apps.agent_app namespace
    mock_impl = mocker.patch("apps.agent_app.get_agent_call_relationship_impl")
    mock_impl.return_value = {
        "agent_id": 1,
        "tree": {"tools": [], "sub_agents": []}
    }

    resp = config_client.get("/agent/call_relationship/1", headers=mock_auth_header)

    assert resp.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_impl.assert_called_once_with(1, "tenant_abc")
    data = resp.json()
    assert data["agent_id"] == 1
    assert "tree" in data and "tools" in data["tree"] and "sub_agents" in data["tree"]


def test_get_agent_call_relationship_api_exception(mocker, mock_auth_header):
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_user_id.return_value = ("user_id_x", "tenant_abc")

    # Patch the same implementation for the error path
    mock_impl = mocker.patch("apps.agent_app.get_agent_call_relationship_impl")
    mock_impl.side_effect = Exception("boom")

    resp = config_client.get("/agent/call_relationship/999", headers=mock_auth_header)

    assert resp.status_code == 500
    assert "Failed to get agent call relationship" in resp.json()["detail"]


def test_check_agent_name_batch_api_success(mocker, mock_auth_header):
    mock_impl = mocker.patch(
        "apps.agent_app.check_agent_name_conflict_batch_impl",
        new_callable=mocker.AsyncMock,
    )
    mock_impl.return_value = [{"name_conflict": True}]

    payload = {
        "items": [
            {"agent_id": 1, "name": "AgentA", "display_name": "Agent A"},
        ]
    }

    resp = config_client.post(
        "/agent/check_name", json=payload, headers=mock_auth_header
    )

    assert resp.status_code == 200
    mock_impl.assert_called_once()
    assert resp.json() == [{"name_conflict": True}]


def test_check_agent_name_batch_api_bad_request(mocker, mock_auth_header):
    mock_impl = mocker.patch(
        "apps.agent_app.check_agent_name_conflict_batch_impl",
        new_callable=mocker.AsyncMock,
    )
    mock_impl.side_effect = ValueError("bad payload")

    resp = config_client.post(
        "/agent/check_name",
        json={"items": [{"agent_id": 1, "name": "AgentA"}]},
        headers=mock_auth_header,
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "bad payload"


def test_check_agent_name_batch_api_error(mocker, mock_auth_header):
    mock_impl = mocker.patch(
        "apps.agent_app.check_agent_name_conflict_batch_impl",
        new_callable=mocker.AsyncMock,
    )
    mock_impl.side_effect = Exception("unexpected")

    resp = config_client.post(
        "/agent/check_name",
        json={"items": [{"agent_id": 1, "name": "AgentA"}]},
        headers=mock_auth_header,
    )

    assert resp.status_code == 500
    assert "Agent name batch check error" in resp.json()["detail"]


def test_regenerate_agent_name_batch_api_success(mocker, mock_auth_header):
    mock_impl = mocker.patch(
        "apps.agent_app.regenerate_agent_name_batch_impl",
        new_callable=mocker.AsyncMock,
    )
    mock_impl.return_value = [{"name": "NewName", "display_name": "New Display"}]

    payload = {
        "items": [
            {
                "agent_id": 1,
                "name": "AgentA",
                "display_name": "Agent A",
                "task_description": "desc",
            }
        ]
    }

    resp = config_client.post(
        "/agent/regenerate_name", json=payload, headers=mock_auth_header
    )

    assert resp.status_code == 200
    mock_impl.assert_called_once()
    assert resp.json() == [{"name": "NewName", "display_name": "New Display"}]


def test_regenerate_agent_name_batch_api_bad_request(mocker, mock_auth_header):
    mock_impl = mocker.patch(
        "apps.agent_app.regenerate_agent_name_batch_impl",
        new_callable=mocker.AsyncMock,
    )
    mock_impl.side_effect = ValueError("invalid")

    resp = config_client.post(
        "/agent/regenerate_name",
        json={"items": [{"agent_id": 1, "name": "AgentA"}]},
        headers=mock_auth_header,
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid"


def test_regenerate_agent_name_batch_api_error(mocker, mock_auth_header):
    mock_impl = mocker.patch(
        "apps.agent_app.regenerate_agent_name_batch_impl",
        new_callable=mocker.AsyncMock,
    )
    mock_impl.side_effect = Exception("boom")

    resp = config_client.post(
        "/agent/regenerate_name",
        json={"items": [{"agent_id": 1, "name": "AgentA"}]},
        headers=mock_auth_header,
    )

    assert resp.status_code == 500
    assert "Agent name batch regenerate error" in resp.json()["detail"]


def test_clear_agent_new_mark_api_success(mocker, mock_auth_header):
    """
    Test successful clearing of agent NEW mark via API endpoint.

    This test verifies that:
    1. The API correctly parses authorization header
    2. Calls get_current_user_info to extract user and tenant info
    3. Calls clear_agent_new_mark_impl with correct parameters
    4. Returns success response with affected_rows
    """
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_clear_agent_new_mark = mocker.patch(
        "apps.agent_app.clear_agent_new_mark_impl", new_callable=mocker.AsyncMock)

    # Mock the auth utility to return user info
    mock_get_user_info.return_value = ("test_user_id", "test_tenant_id", "extra_info")

    # Mock the service layer to return affected rows
    mock_clear_agent_new_mark.return_value = 1

    # Test the endpoint
    response = config_client.put(
        "/agent/clear_new/123",  # agent_id = 123
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["message"] == "Agent NEW mark cleared successfully"
    assert response_data["affected_rows"] == 1

    # Verify mocks were called correctly
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"])
    mock_clear_agent_new_mark.assert_called_once_with(123, "test_tenant_id", "test_user_id")


def test_clear_agent_new_mark_api_exception(mocker, mock_auth_header):
    """
    Test clear_agent_new_mark_api when service layer throws exception.

    This test verifies that:
    1. When clear_agent_new_mark_impl raises an exception
    2. The API catches it and logs the error
    3. Returns HTTP 500 with appropriate error message
    """
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_clear_agent_new_mark = mocker.patch(
        "apps.agent_app.clear_agent_new_mark_impl", new_callable=mocker.AsyncMock)
    mock_logger = mocker.patch("apps.agent_app.logger")

    # Mock the auth utility to return user info
    mock_get_user_info.return_value = ("test_user_id", "test_tenant_id", "extra_info")

    # Mock the service layer to raise an exception
    test_exception = Exception("Database connection failed")
    mock_clear_agent_new_mark.side_effect = test_exception

    # Test the endpoint
    response = config_client.put(
        "/agent/clear_new/456",  # agent_id = 456
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to clear agent NEW mark."

    # Verify error was logged
    mock_logger.error.assert_called_once_with("Failed to clear agent NEW mark: Database connection failed")

    # Verify service was still called with correct parameters
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"])
    mock_clear_agent_new_mark.assert_called_once_with(456, "test_tenant_id", "test_user_id")


# Agent Version Management API Tests
# ---------------------------------------------------------------------------


def test_publish_version_api_success(mocker, mock_auth_header):
    """Test successful version publishing"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_publish_version = mocker.patch("apps.agent_app.publish_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_publish_version.return_value = {
        "success": True,
        "message": "Version published successfully",
        "version_no": 1
    }
    
    response = config_client.post(
        "/agent/123/publish",
        json={
            "version_name": "v1.0.0",
            "release_note": "Initial release"
        },
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_publish_version.assert_called_once_with(
        agent_id=123,
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        version_name="v1.0.0",
        release_note="Initial release"
    )
    assert response.json()["success"] is True
    assert response.json()["version_no"] == 1


def test_publish_version_api_bad_request(mocker, mock_auth_header):
    """Test publish version with ValueError"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_publish_version = mocker.patch("apps.agent_app.publish_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_publish_version.side_effect = ValueError("Agent not found")
    
    response = config_client.post(
        "/agent/123/publish",
        json={
            "version_name": "v1.0.0",
            "release_note": "Initial release"
        },
        headers=mock_auth_header
    )
    
    assert response.status_code == 400
    assert response.json()["detail"] == "Agent not found"


def test_publish_version_api_exception(mocker, mock_auth_header):
    """Test publish version with general exception"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_publish_version = mocker.patch("apps.agent_app.publish_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_publish_version.side_effect = Exception("Database error")
    
    response = config_client.post(
        "/agent/123/publish",
        json={
            "version_name": "v1.0.0",
            "release_note": "Initial release"
        },
        headers=mock_auth_header
    )
    
    assert response.status_code == 500
    assert "Publish version error" in response.json()["detail"]


def test_compare_versions_api_success(mocker, mock_auth_header):
    """Test successful version comparison"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_compare_versions = mocker.patch("apps.agent_app.compare_versions_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_compare_versions.return_value = {
        "success": True,
        "message": "Versions compared successfully",
        "data": {
            "version_a": {"version_no": 1},
            "version_b": {"version_no": 2},
            "differences": []
        }
    }
    
    response = config_client.post(
        "/agent/123/versions/compare",
        json={
            "version_no_a": 1,
            "version_no_b": 2
        },
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_compare_versions.assert_called_once_with(
        agent_id=123,
        tenant_id="test_tenant_id",
        version_no_a=1,
        version_no_b=2
    )
    assert response.json()["success"] is True


def test_compare_versions_api_bad_request(mocker, mock_auth_header):
    """Test compare versions with ValueError"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_compare_versions = mocker.patch("apps.agent_app.compare_versions_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_compare_versions.side_effect = ValueError("Version not found")
    
    response = config_client.post(
        "/agent/123/versions/compare",
        json={
            "version_no_a": 1,
            "version_no_b": 2
        },
        headers=mock_auth_header
    )
    
    assert response.status_code == 400
    assert response.json()["detail"] == "Version not found"


def test_compare_versions_api_exception(mocker, mock_auth_header):
    """Test compare versions with general exception"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_compare_versions = mocker.patch("apps.agent_app.compare_versions_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_compare_versions.side_effect = Exception("Database error")
    
    response = config_client.post(
        "/agent/123/versions/compare",
        json={
            "version_no_a": 1,
            "version_no_b": 2
        },
        headers=mock_auth_header
    )
    
    assert response.status_code == 500
    assert "Compare versions error" in response.json()["detail"]


def test_get_version_list_api_success(mocker, mock_auth_header):
    """Test successful version list retrieval without explicit tenant_id (uses auth tenant_id)"""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_get_version_list = mocker.patch("apps.agent_app.get_version_list_impl")
    
    mock_get_user_info.return_value = ("test_user_id", "test_tenant_id", "en")
    mock_get_version_list.return_value = {
        "versions": [
            {"version_no": 1, "version_name": "v1.0.0", "status": "RELEASED"},
            {"version_no": 2, "version_name": "v2.0.0", "status": "RELEASED"}
        ]
    }
    
    response = config_client.get(
        "/agent/123/versions",
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"], ANY)
    mock_get_version_list.assert_called_once_with(
        agent_id=123,
        tenant_id="test_tenant_id"
    )
    assert len(response.json()["versions"]) == 2


def test_get_version_list_api_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test successful version list retrieval with explicit tenant_id query parameter"""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_get_version_list = mocker.patch("apps.agent_app.get_version_list_impl")
    
    mock_get_user_info.return_value = ("test_user_id", "auth_tenant_id", "en")
    mock_get_version_list.return_value = {
        "versions": [
            {"version_no": 1, "version_name": "v1.0.0", "status": "RELEASED"}
        ]
    }
    
    explicit_tenant_id = "explicit_tenant_456"
    response = config_client.get(
        "/agent/123/versions",
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"], ANY)
    # Should use explicit tenant_id when provided, not auth tenant_id
    mock_get_version_list.assert_called_once_with(
        agent_id=123,
        tenant_id=explicit_tenant_id
    )
    assert len(response.json()["versions"]) == 1


def test_get_version_list_api_exception(mocker, mock_auth_header):
    """Test get version list with exception without explicit tenant_id"""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_get_version_list = mocker.patch("apps.agent_app.get_version_list_impl")
    
    mock_get_user_info.return_value = ("test_user_id", "test_tenant_id", "en")
    mock_get_version_list.side_effect = Exception("Database error")
    
    response = config_client.get(
        "/agent/123/versions",
        headers=mock_auth_header
    )
    
    assert response.status_code == 500
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"], ANY)
    mock_get_version_list.assert_called_once_with(
        agent_id=123,
        tenant_id="test_tenant_id"
    )
    assert "Get version list error" in response.json()["detail"]


def test_get_version_list_api_exception_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test get version list with exception and explicit tenant_id"""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_get_version_list = mocker.patch("apps.agent_app.get_version_list_impl")
    
    mock_get_user_info.return_value = ("test_user_id", "auth_tenant_id", "en")
    mock_get_version_list.side_effect = Exception("Database error with explicit tenant")
    
    explicit_tenant_id = "explicit_tenant_789"
    response = config_client.get(
        "/agent/123/versions",
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )
    
    assert response.status_code == 500
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"], ANY)
    # Should use explicit tenant_id even when exception occurs
    mock_get_version_list.assert_called_once_with(
        agent_id=123,
        tenant_id=explicit_tenant_id
    )
    assert "Get version list error" in response.json()["detail"]


def test_get_version_api_success(mocker, mock_auth_header):
    """Test successful version retrieval"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_version = mocker.patch("apps.agent_app.get_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_version.return_value = {
        "version_no": 1,
        "version_name": "v1.0.0",
        "status": "RELEASED",
        "release_note": "Initial release"
    }
    
    response = config_client.get(
        "/agent/123/versions/1",
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_get_version.assert_called_once_with(
        agent_id=123,
        tenant_id="test_tenant_id",
        version_no=1
    )
    assert response.json()["version_no"] == 1


def test_get_version_api_not_found(mocker, mock_auth_header):
    """Test get version with ValueError (not found)"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_version = mocker.patch("apps.agent_app.get_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_version.side_effect = ValueError("Version not found")
    
    response = config_client.get(
        "/agent/123/versions/999",
        headers=mock_auth_header
    )
    
    assert response.status_code == 404
    assert response.json()["detail"] == "Version not found"


def test_get_version_api_exception(mocker, mock_auth_header):
    """Test get version with general exception"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_version = mocker.patch("apps.agent_app.get_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_version.side_effect = Exception("Database error")
    
    response = config_client.get(
        "/agent/123/versions/1",
        headers=mock_auth_header
    )
    
    assert response.status_code == 500
    assert "Get version detail error" in response.json()["detail"]


def test_get_version_detail_api_success(mocker, mock_auth_header):
    """Test successful version detail retrieval"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_version_detail = mocker.patch("apps.agent_app.get_version_detail_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_version_detail.return_value = {
        "version_no": 1,
        "version_name": "v1.0.0",
        "status": "RELEASED",
        "agent_snapshot": {"agent_id": 123, "name": "Test Agent"},
        "tool_snapshots": [],
        "relation_snapshots": []
    }
    
    response = config_client.get(
        "/agent/123/versions/1/detail",
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_get_version_detail.assert_called_once_with(
        agent_id=123,
        tenant_id="test_tenant_id",
        version_no=1
    )
    assert response.json()["version_no"] == 1
    assert "agent_snapshot" in response.json()


def test_get_version_detail_api_not_found(mocker, mock_auth_header):
    """Test get version detail with ValueError (not found)"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_version_detail = mocker.patch("apps.agent_app.get_version_detail_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_version_detail.side_effect = ValueError("Version not found")
    
    response = config_client.get(
        "/agent/123/versions/999/detail",
        headers=mock_auth_header
    )
    
    assert response.status_code == 404
    assert response.json()["detail"] == "Version not found"


def test_get_version_detail_api_exception(mocker, mock_auth_header):
    """Test get version detail with general exception"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_version_detail = mocker.patch("apps.agent_app.get_version_detail_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_version_detail.side_effect = Exception("Database error")
    
    response = config_client.get(
        "/agent/123/versions/1/detail",
        headers=mock_auth_header
    )
    
    assert response.status_code == 500
    assert "Get version detail error" in response.json()["detail"]


def test_rollback_version_api_success(mocker, mock_auth_header):
    """Test successful version rollback"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_rollback_version = mocker.patch("apps.agent_app.rollback_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_rollback_version.return_value = {
        "success": True,
        "message": "Successfully rolled back to version 1",
        "version_no": 1
    }
    
    response = config_client.post(
        "/agent/123/versions/1/rollback",
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_rollback_version.assert_called_once_with(
        agent_id=123,
        tenant_id="test_tenant_id",
        target_version_no=1
    )
    assert response.json()["success"] is True


def test_rollback_version_api_bad_request(mocker, mock_auth_header):
    """Test rollback version with ValueError"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_rollback_version = mocker.patch("apps.agent_app.rollback_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_rollback_version.side_effect = ValueError("Version not found")
    
    response = config_client.post(
        "/agent/123/versions/999/rollback",
        headers=mock_auth_header
    )
    
    assert response.status_code == 400
    assert response.json()["detail"] == "Version not found"


def test_rollback_version_api_exception(mocker, mock_auth_header):
    """Test rollback version with general exception"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_rollback_version = mocker.patch("apps.agent_app.rollback_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_rollback_version.side_effect = Exception("Database error")
    
    response = config_client.post(
        "/agent/123/versions/1/rollback",
        headers=mock_auth_header
    )
    
    assert response.status_code == 500
    assert "Rollback version error" in response.json()["detail"]


def test_update_version_status_api_success(mocker, mock_auth_header):
    """Test successful version status update"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_update_version_status = mocker.patch("apps.agent_app.update_version_status_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_update_version_status.return_value = {
        "success": True,
        "message": "Version status updated successfully"
    }
    
    response = config_client.patch(
        "/agent/123/versions/1/status",
        json={"status": "DISABLED"},
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_update_version_status.assert_called_once_with(
        agent_id=123,
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        version_no=1,
        status="DISABLED"
    )
    assert response.json()["success"] is True


def test_update_version_status_api_bad_request(mocker, mock_auth_header):
    """Test update version status with ValueError"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_update_version_status = mocker.patch("apps.agent_app.update_version_status_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_update_version_status.side_effect = ValueError("Invalid status")
    
    response = config_client.patch(
        "/agent/123/versions/1/status",
        json={"status": "INVALID"},
        headers=mock_auth_header
    )
    
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid status"


def test_update_version_status_api_exception(mocker, mock_auth_header):
    """Test update version status with general exception"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_update_version_status = mocker.patch("apps.agent_app.update_version_status_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_update_version_status.side_effect = Exception("Database error")
    
    response = config_client.patch(
        "/agent/123/versions/1/status",
        json={"status": "DISABLED"},
        headers=mock_auth_header
    )
    
    assert response.status_code == 500
    assert "Update version status error" in response.json()["detail"]


def test_delete_version_api_success(mocker, mock_auth_header):
    """Test successful version deletion"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_delete_version = mocker.patch("apps.agent_app.delete_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_delete_version.return_value = {
        "success": True,
        "message": "Version 1 deleted successfully"
    }
    
    response = config_client.delete(
        "/agent/123/versions/1",
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_delete_version.assert_called_once_with(
        agent_id=123,
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        version_no=1
    )
    assert response.json()["success"] is True


def test_delete_version_api_bad_request(mocker, mock_auth_header):
    """Test delete version with ValueError"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_delete_version = mocker.patch("apps.agent_app.delete_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_delete_version.side_effect = ValueError("Cannot delete draft version")
    
    response = config_client.delete(
        "/agent/123/versions/0",
        headers=mock_auth_header
    )
    
    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot delete draft version"


def test_delete_version_api_exception(mocker, mock_auth_header):
    """Test delete version with general exception"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_delete_version = mocker.patch("apps.agent_app.delete_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_delete_version.side_effect = Exception("Database error")
    
    response = config_client.delete(
        "/agent/123/versions/1",
        headers=mock_auth_header
    )
    
    assert response.status_code == 500
    assert "Delete version error" in response.json()["detail"]


def test_get_current_version_api_success(mocker, mock_auth_header):
    """Test successful current version retrieval"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_current_version = mocker.patch("apps.agent_app.get_current_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_current_version.return_value = {
        "version_no": 1,
        "version_name": "v1.0.0",
        "status": "RELEASED"
    }
    
    response = config_client.get(
        "/agent/123/current_version",
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_get_current_version.assert_called_once_with(
        agent_id=123,
        tenant_id="test_tenant_id"
    )
    assert response.json()["version_no"] == 1


def test_get_current_version_api_not_found(mocker, mock_auth_header):
    """Test get current version with ValueError (not found)"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_current_version = mocker.patch("apps.agent_app.get_current_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_current_version.side_effect = ValueError("No published version found")
    
    response = config_client.get(
        "/agent/123/current_version",
        headers=mock_auth_header
    )
    
    assert response.status_code == 404
    assert response.json()["detail"] == "No published version found"


def test_get_current_version_api_exception(mocker, mock_auth_header):
    """Test get current version with general exception"""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_current_version = mocker.patch("apps.agent_app.get_current_version_impl")
    
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_current_version.side_effect = Exception("Database error")
    
    response = config_client.get(
        "/agent/123/current_version",
        headers=mock_auth_header
    )
    
    assert response.status_code == 500
    assert "Get current version error" in response.json()["detail"]


def test_list_published_agents_api_success(mocker, mock_auth_header):
    """Test successful published agents list retrieval"""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_published_agents = mocker.patch(
        "apps.agent_app.list_published_agents_impl", new_callable=mocker.AsyncMock)
    
    mock_get_user_info.return_value = ("test_user_id", "test_tenant_id", "en")
    mock_list_published_agents.return_value = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "published_version_no": 1,
            "version_name": "v1.0.0"
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "published_version_no": 2,
            "version_name": "v2.0.0"
        }
    ]
    
    response = config_client.get(
        "/agent/published_list",
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    mock_get_user_info.assert_called_once_with(mock_auth_header["Authorization"], ANY)
    mock_list_published_agents.assert_called_once_with(
        tenant_id="test_tenant_id",
        user_id="test_user_id"
    )
    assert len(response.json()) == 2
    assert response.json()[0]["agent_id"] == 1


def test_list_published_agents_api_exception(mocker, mock_auth_header):
    """Test list published agents with exception"""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_published_agents = mocker.patch(
        "apps.agent_app.list_published_agents_impl", new_callable=mocker.AsyncMock)
    
    mock_get_user_info.return_value = ("test_user_id", "test_tenant_id", "en")
    mock_list_published_agents.side_effect = Exception("Database error")
    
    response = config_client.get(
        "/agent/published_list",
        headers=mock_auth_header
    )
    
    assert response.status_code == 500
    assert "Published agents list error" in response.json()["detail"]