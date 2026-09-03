"""
Unit tests for backend.apps.agent_app module.

Tests all agent management API endpoints including runtime and configuration operations.
"""
import atexit
from unittest.mock import AsyncMock, patch, Mock, MagicMock, ANY

import importlib.machinery
import os
import sys
import types
import warnings

import pytest
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from consts.const import AGENT_PROMPTS_HIDDEN_FLAG, ASSET_OWNER_TENANT_ID
from consts.exceptions import ForbiddenError, UnauthorizedError, ValidationError
from consts.model import NL2AgentRunRequest
from services.agent_draft_permission_service import AgentDraftEditError
from services.nl2agent_service import Nl2AgentDraftSaveError

# Filter out deprecation warnings from third-party libraries
warnings.filterwarnings(
    "ignore", category=DeprecationWarning, module="pyiceberg")
pytestmark = pytest.mark.filterwarnings(
    "ignore::DeprecationWarning:pyiceberg.*")

# Dynamically determine the backend path - MUST BE FIRST
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.insert(0, backend_dir)

# Mock boto3 before importing backend modules
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules['boto3'] = boto3_module

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate',
      lambda self: None).start()
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

# Mock external dependencies before importing the modules that use them
# Stub nexent.core.agents.agent_model.ToolConfig to satisfy type imports in consts.model
agent_model_stub = types.ModuleType("agent_model")


class ToolConfig:  # minimal stub for type reference
    pass


agent_model_stub.ToolConfig = ToolConfig

# Define a decorator that simply returns the original function unchanged


def pass_through_decorator(*args, **kwargs):
    def decorator(func):
        return func
    return decorator


monitoring_stub = types.ModuleType("monitor")
monitoring_manager_mock = MagicMock()
monitoring_manager_mock.monitor_endpoint = pass_through_decorator
monitoring_manager_mock.monitor_llm_call = pass_through_decorator
monitoring_manager_mock.setup_fastapi_app = MagicMock(return_value=True)
monitoring_manager_mock.configure = MagicMock()
monitoring_manager_mock.add_span_event = MagicMock()
monitoring_manager_mock.set_span_attributes = MagicMock()

monitoring_stub.get_monitoring_manager = lambda: monitoring_manager_mock
monitoring_stub.monitoring_manager = monitoring_manager_mock
monitoring_stub.MonitoringManager = MagicMock
monitoring_stub.MonitoringConfig = MagicMock

# Mock all external dependencies that agent_app.py imports
# These must be in sys.modules BEFORE we import apps.agent_app
sys.modules['nexent'] = types.ModuleType('nexent')
sys.modules['nexent.core'] = types.ModuleType('nexent.core')
sys.modules['nexent.core.agents'] = types.ModuleType('nexent.core.agents')
sys.modules['nexent.core.agents.agent_model'] = agent_model_stub
sys.modules['nexent.monitor'] = monitoring_stub
sys.modules['nexent.monitor.monitoring'] = monitoring_stub
sys.modules['database.client'] = MagicMock()
sys.modules['database.agent_db'] = MagicMock()
sys.modules['agents.create_agent_info'] = MagicMock()
sys.modules['nexent.core.agents.run_agent'] = MagicMock()
sys.modules['utils.auth_utils'] = MagicMock()
sys.modules['utils.config_utils'] = MagicMock()
sys.modules['utils.thread_utils'] = MagicMock()
sys.modules['utils.monitoring'] = MagicMock()
sys.modules['utils.monitoring'].monitoring_manager = monitoring_manager_mock
sys.modules['utils.monitoring'].setup_fastapi_app = MagicMock(
    return_value=True)
sys.modules['agents.agent_run_manager'] = MagicMock()
sys.modules['management.services.agent.service'] = MagicMock()
sys.modules['management.services.skill.service'] = MagicMock()
sys.modules['services.conversation_management_service'] = MagicMock()
sys.modules['services.memory_config_service'] = MagicMock()
sys.modules['services.agent_version_service'] = MagicMock()
sys.modules['services.prompt_service'] = MagicMock()

# Now safe to import app modules after all mocks are set up
from apps.agent_app import (
    agent_config_router,
    agent_runtime_router,
    nl2agent_run_api,
)



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


# Agent Runtime API Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_run_api(mocker, mock_auth_header):
    """Test agent_run_api endpoint."""
    mock_run_agent_stream = mocker.patch(
        "apps.agent_app.run_agent_stream", new_callable=AsyncMock)

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


@pytest.mark.asyncio
async def test_nl2agent_run_api_streams_for_existing_draft(
    mocker, mock_auth_header
):
    mocker.patch(
        "apps.agent_app.get_current_user_info",
        return_value=("user-a", "tenant-a", "en"),
    )

    async def mock_stream():
        yield 'data: {"type":"final_answer","content":"done"}\n\n'

    create_stream = mocker.patch(
        "apps.agent_app.create_nl2agent_stream",
        new_callable=AsyncMock,
        return_value=mock_stream(),
    )

    response = await nl2agent_run_api(
        nl2agent_request=NL2AgentRunRequest(
            query="Build a weather agent",
            history=[],
            minio_files=[],
            agent_id=42,
        ),
        http_request=MagicMock(),
        authorization=mock_auth_header["Authorization"],
    )

    chunks = [chunk async for chunk in response.body_iterator]

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    assert "final_answer" in "".join(chunks)
    request = create_stream.call_args.kwargs["request"]
    assert request.query == "Build a weather agent"
    assert request.agent_id == 42
    assert (
        create_stream.call_args.kwargs["authorization"]
        == mock_auth_header["Authorization"]
    )
    assert not hasattr(request, "conversation_id")
    assert create_stream.call_args.kwargs["tenant_id"] == "tenant-a"
    assert create_stream.call_args.kwargs["language"] == "en"


@pytest.mark.asyncio
async def test_northbound_agent_run_api_uses_internal_identity(mocker):
    mocker.patch(
        "apps.agent_app.verify_internal_runtime_jwt",
        return_value=("user-a", "tenant-a"),
    )
    run_agent = mocker.patch(
        "apps.agent_app.run_agent_stream",
        new_callable=AsyncMock,
    )

    async def mock_stream():
        yield b"data: done\n\n"

    run_agent.return_value = StreamingResponse(
        mock_stream(),
        media_type="text/event-stream",
    )
    response = runtime_client.post(
        "/agent/internal/northbound/run",
        json={"agent_id": 1, "conversation_id": 123, "query": "hello"},
        headers={"Authorization": "Bearer internal-token"},
    )

    assert response.status_code == 200
    call_kwargs = run_agent.call_args.kwargs
    assert call_kwargs["user_id"] == "user-a"
    assert call_kwargs["tenant_id"] == "tenant-a"
    assert call_kwargs["skip_user_save"] is True
    assert call_kwargs["http_request"] is None


@pytest.mark.asyncio
async def test_northbound_agent_run_api_rejects_invalid_token(mocker):
    mocker.patch(
        "apps.agent_app.verify_internal_runtime_jwt",
        side_effect=UnauthorizedError("Invalid internal runtime token"),
    )

    response = runtime_client.post(
        "/agent/internal/northbound/run",
        json={"agent_id": 1, "conversation_id": 123, "query": "hello"},
        headers={"Authorization": "Bearer invalid"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ForbiddenError("forbidden"), 403),
        (ValidationError("invalid"), 422),
    ],
)
def test_northbound_agent_run_api_maps_domain_errors(
    mocker,
    error,
    expected_status,
):
    mocker.patch(
        "apps.agent_app.verify_internal_runtime_jwt",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch(
        "apps.agent_app.run_agent_stream",
        new_callable=AsyncMock,
        side_effect=error,
    )

    response = runtime_client.post(
        "/agent/internal/northbound/run",
        json={"agent_id": 1, "conversation_id": 123, "query": "hello"},
        headers={"Authorization": "Bearer internal-token"},
    )

    assert response.status_code == expected_status


def test_northbound_agent_run_api_maps_unexpected_error(mocker):
    mocker.patch(
        "apps.agent_app.verify_internal_runtime_jwt",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch(
        "apps.agent_app.run_agent_stream",
        new_callable=AsyncMock,
        side_effect=RuntimeError("unexpected"),
    )

    response = runtime_client.post(
        "/agent/internal/northbound/run",
        json={"agent_id": 1, "conversation_id": 123, "query": "hello"},
        headers={"Authorization": "Bearer internal-token"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Agent run error."


@pytest.mark.asyncio
async def test_northbound_agent_stop_api_uses_internal_identity(mocker):
    mocker.patch(
        "apps.agent_app.verify_internal_runtime_jwt",
        return_value=("user-a", "tenant-a"),
    )
    stop_agent = mocker.patch(
        "apps.agent_app.stop_agent_tasks",
        return_value={"message": "stopped"},
    )

    response = runtime_client.post(
        "/agent/internal/northbound/stop/123",
        headers={"Authorization": "Bearer internal-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "stopped"}
    stop_agent.assert_called_once_with(123, "user-a")


def test_northbound_agent_stop_api_rejects_invalid_token(mocker):
    mocker.patch(
        "apps.agent_app.verify_internal_runtime_jwt",
        side_effect=UnauthorizedError("Invalid internal runtime token"),
    )

    response = runtime_client.post(
        "/agent/internal/northbound/stop/123",
        headers={"Authorization": "Bearer invalid"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid internal runtime token"


@pytest.mark.asyncio
async def test_nl2agent_run_api_streams_without_persistent_ids(
    mocker, mock_auth_header
):
    mocker.patch(
        "apps.agent_app.get_current_user_info",
        return_value=("user-a", "tenant-a", "en"),
    )

    async def mock_stream():
        yield 'data: {"type":"final_answer","content":"done"}\n\n'

    create_stream = mocker.patch(
        "apps.agent_app.create_nl2agent_stream",
        new_callable=AsyncMock,
        return_value=mock_stream(),
    )

    response = await nl2agent_run_api(
        nl2agent_request=NL2AgentRunRequest(
            query="Build a weather agent",
            history=[],
            minio_files=[],
            agent_id=42,
        ),
        http_request=MagicMock(),
        authorization=mock_auth_header["Authorization"],
    )

    chunks = [chunk async for chunk in response.body_iterator]

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    assert "final_answer" in "".join(chunks)
    request = create_stream.call_args.kwargs["request"]
    assert request.query == "Build a weather agent"
    assert request.agent_id == 42
    assert (
        create_stream.call_args.kwargs["authorization"]
        == mock_auth_header["Authorization"]
    )
    assert not hasattr(request, "conversation_id")
    assert create_stream.call_args.kwargs["tenant_id"] == "tenant-a"
    assert create_stream.call_args.kwargs["language"] == "en"


@pytest.mark.asyncio
async def test_nl2agent_run_api_maps_authentication_failure_to_401(mocker):
    mocker.patch(
        "apps.agent_app.get_current_user_info",
        side_effect=UnauthorizedError("Invalid access token"),
    )
    create_stream = mocker.patch(
        "apps.agent_app.create_nl2agent_stream",
        new_callable=AsyncMock,
    )

    with pytest.raises(HTTPException) as exc_info:
        await nl2agent_run_api(
            nl2agent_request=NL2AgentRunRequest(
                query="Build an assistant",
                agent_id=42,
            ),
            http_request=MagicMock(),
            authorization="Bearer invalid-token",
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid access token"
    create_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_nl2agent_run_api_hides_internal_startup_errors(mocker):
    mocker.patch(
        "apps.agent_app.get_current_user_info",
        return_value=("user-a", "tenant-a", "en"),
    )
    mocker.patch(
        "apps.agent_app.create_nl2agent_stream",
        new_callable=AsyncMock,
        side_effect=RuntimeError("private model configuration"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await nl2agent_run_api(
            nl2agent_request=NL2AgentRunRequest(
                query="Build an assistant",
                agent_id=42,
            ),
            http_request=MagicMock(),
            authorization="Bearer tenant-token",
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "NL2Agent run error."
    assert "private model configuration" not in exc_info.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (AgentDraftEditError("agent_not_found"), 404, "agent_not_found"),
        (AgentDraftEditError("agent_not_draft"), 400, "agent_not_draft"),
        (AgentDraftEditError("agent_deleted"), 403, "agent_deleted"),
        (AgentDraftEditError("agent_read_only"), 403, "agent_read_only"),
        (
            Nl2AgentDraftSaveError("agent_context_mismatch"),
            400,
            "agent_context_mismatch",
        ),
    ],
)
async def test_nl2agent_run_api_maps_draft_identity_errors(
    mocker,
    error,
    expected_status,
    expected_code,
):
    mocker.patch(
        "apps.agent_app.get_current_user_info",
        return_value=("user-a", "tenant-a", "en"),
    )
    mocker.patch(
        "apps.agent_app.create_nl2agent_stream",
        new_callable=AsyncMock,
        side_effect=error,
    )

    with pytest.raises(HTTPException) as exc_info:
        await nl2agent_run_api(
            nl2agent_request=NL2AgentRunRequest(
                query="Continue configuring the Agent",
                agent_id=42,
            ),
            http_request=MagicMock(),
            authorization="Bearer tenant-token",
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail["code"] == expected_code


@pytest.mark.asyncio
async def test_nl2agent_run_api_requires_agent_id():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/agent/nl2agent/run",
            json={"query": "Build an assistant"},
        )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "agent_id"


async def test_agent_run_api_error_debug_mode(mocker, mock_auth_header):
    """Test agent_run_api error case in debug mode - should expose actual error."""
    mock_run_agent_stream = mocker.patch(
        "apps.agent_app.run_agent_stream", new_callable=AsyncMock)
    mock_run_agent_stream.side_effect = Exception("Test error")

    response = runtime_client.post(
        "/agent/run",
        json={
            "agent_id": 1,
            "conversation_id": 123,
            "query": "test query",
            "history": [],
            "minio_files": [],
            "is_debug": True,  # Debug mode
        },
        headers=mock_auth_header
    )

    assert response.status_code == 500
    # In debug mode, actual error should be exposed
    assert "Test error" in response.json()["detail"]


async def test_agent_run_api_error_normal_mode(mocker, mock_auth_header):
    """Test agent_run_api error case in normal mode - should show generic error."""
    mock_run_agent_stream = mocker.patch(
        "apps.agent_app.run_agent_stream", new_callable=AsyncMock)
    mock_run_agent_stream.side_effect = Exception("Test internal error")

    response = runtime_client.post(
        "/agent/run",
        json={
            "agent_id": 1,
            "conversation_id": 123,
            "query": "test query",
            "history": [],
            "minio_files": [],
            "is_debug": False,  # Normal mode
        },
        headers=mock_auth_header
    )

    assert response.status_code == 500
    # In normal mode, generic error message should be shown
    assert response.json()["detail"] == "Agent run error."
    # Actual error should NOT be exposed in normal mode
    assert "Test internal error" not in response.json()["detail"]


def test_agent_run_api_exception(mocker, mock_auth_header):
    """Test agent_run_api exception handling."""
    mock_run_agent_stream = mocker.patch(
        "apps.agent_app.run_agent_stream", new_callable=AsyncMock)
    mock_logger = mocker.patch("apps.agent_app.logger")
    mock_run_agent_stream.side_effect = Exception("Test error")

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

    assert response.status_code == 500
    assert "Agent run error" in response.json()["detail"]
    mock_logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_agent_run_api_maps_forbidden_conversation_to_403(mocker):
    from consts.exceptions import ForbiddenError
    from consts.model import AgentRequest
    from fastapi import HTTPException
    from starlette.requests import Request

    from apps.agent_app import agent_run_api

    mock_run_agent_stream = mocker.patch(
        "apps.agent_app.run_agent_stream",
        new_callable=AsyncMock,
    )
    mock_run_agent_stream.side_effect = ForbiddenError("Conversation is not accessible")

    request = AgentRequest(
        agent_id=1,
        conversation_id=123,
        query="test query",
        history=[],
        minio_files=[],
        is_debug=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await agent_run_api(
            agent_request=request,
            http_request=Request({"type": "http", "headers": []}),
            authorization="Bearer token",
            resume=False,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Conversation is not accessible"


@pytest.mark.asyncio
async def test_agent_run_api_maps_scope_validation_to_422(mocker):
    from consts.exceptions import ValidationError
    from consts.model import AgentRequest
    from starlette.requests import Request

    from apps.agent_app import agent_run_api

    mock_run_agent_stream = mocker.patch(
        "apps.agent_app.run_agent_stream",
        new_callable=AsyncMock,
        side_effect=ValidationError("Selected knowledge bases are incompatible"),
    )
    request = AgentRequest(
        agent_id=1,
        query="test query",
        knowledge_scope={
            "local": {"mode": "disabled", "knowledge_ids": []},
            "aidp": {"mode": "disabled", "kds_ids": []},
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        await agent_run_api(
            agent_request=request,
            http_request=Request({"type": "http", "headers": []}),
            authorization="Bearer token",
            resume=False,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Selected knowledge bases are incompatible"


def test_agent_stop_api_success(mocker, mock_conversation_id):
    """Test agent_stop_api success case."""
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


def test_agent_stop_api_exception(mocker, mock_conversation_id):
    """Test agent_stop_api exception handling - exception propagates without catch."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")

    mock_stop_tasks = mocker.patch("apps.agent_app.stop_agent_tasks")
    mock_stop_tasks.side_effect = Exception("Stop error")

    # The endpoint doesn't catch exceptions, so they propagate
    # This test verifies the function raises the exception as expected
    with pytest.raises(Exception, match="Stop error"):
        runtime_client.get(
            f"/agent/stop/{mock_conversation_id}",
            headers={"Authorization": "Bearer test_token"}
        )


# Agent Configuration API Tests
# ---------------------------------------------------------------------------


def test_search_agent_info_api_success(mocker, mock_auth_header):
    """Test search_agent_info_api success case without tenant_id query parameter."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=AsyncMock)
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.return_value = {"agent_id": 123, "name": "Test Agent"}

    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    # Should use auth tenant_id when query parameter is not provided, and default version_no=0
    mock_get_agent_info.assert_called_once_with(
        123, "auth_tenant_id", 0, "user_id")
    assert response.json()["agent_id"] == 123
    assert response.json()["name"] == "Test Agent"


def test_search_agent_info_api_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test search_agent_info_api success case with explicit tenant_id query parameter."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=AsyncMock)
    # Mock return values - auth tenant_id is different from explicit tenant_id
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.return_value = {
        "agent_id": 456,
        "name": "Test Agent with Explicit Tenant",
        "display_name": "Display Name"
    }

    explicit_tenant_id = "explicit_tenant_789"
    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 456},
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    # Should use explicit tenant_id when provided, not auth tenant_id, and default version_no=0
    mock_get_agent_info.assert_called_once_with(
        456, explicit_tenant_id, 0, "user_id")
    assert response.json()["agent_id"] == 456


def test_search_agent_info_api_exception(mocker, mock_auth_header):
    """Test search_agent_info_api exception handling."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=AsyncMock)
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.side_effect = Exception("Test error")

    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    assert response.status_code == 500
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_get_agent_info.assert_called_once_with(
        123, "auth_tenant_id", 0, "user_id")
    assert "Agent search info error" in response.json()["detail"]


def test_search_agent_info_api_exception_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test search_agent_info_api exception handling with explicit tenant_id query parameter and default version_no=0."""
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=AsyncMock)
    # Mock return values and exception
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.side_effect = Exception(
        "Test error with explicit tenant")

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
    mock_get_agent_info.assert_called_once_with(
        789, explicit_tenant_id, 0, "user_id")
    assert "Agent search info error" in response.json()["detail"]


def test_search_agent_info_api_with_version_no(mocker, mock_auth_header):
    """Test search_agent_info_api success case with explicit version_no parameter."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=AsyncMock)
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.return_value = {
        "agent_id": 123, "name": "Test Agent", "version_no": 2}

    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 123, "version_no": 2},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_get_agent_info.assert_called_once_with(
        123, "auth_tenant_id", 2, "user_id")


def test_search_agent_info_api_masks_asset_owner_prompts(mocker, mock_auth_header):
    """Non-asset-owner callers see masked prompts for asset-owner-scoped agents."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=AsyncMock)
    mock_get_user_id.return_value = ("user_id", "regular_tenant")
    mock_get_agent_info.return_value = {
        "agent_id": 1,
        "tenant_id": ASSET_OWNER_TENANT_ID,
        "duty_prompt": "secret duty",
        "constraint_prompt": "secret constraint",
        "few_shots_prompt": "secret few",
    }

    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 1},
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["duty_prompt"] is None
    assert body["constraint_prompt"] is None
    assert body["few_shots_prompt"] is None
    assert body[AGENT_PROMPTS_HIDDEN_FLAG] is True


# get_agent_by_name_api Tests
# ---------------------------------------------------------------------------


def test_get_agent_by_name_api_success(mocker, mock_auth_header):
    """Test get_agent_by_name_api success case."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_by_name = mocker.patch(
        "apps.agent_app.get_agent_by_name_impl")
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_by_name.return_value = {"agent_id": 123, "version_no": 1}

    response = config_client.get(
        "/agent/by-name/TestAgent",
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_get_agent_by_name.assert_called_once_with(
        "TestAgent", "auth_tenant_id")
    assert response.json()["agent_id"] == 123
    assert response.json()["version_no"] == 1


def test_get_agent_by_name_api_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test get_agent_by_name_api with explicit tenant_id."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_by_name = mocker.patch(
        "apps.agent_app.get_agent_by_name_impl")
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_by_name.return_value = {"agent_id": 123, "version_no": 1}

    explicit_tenant_id = "explicit_tenant_123"
    response = config_client.get(
        "/agent/by-name/TestAgent",
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_get_agent_by_name.assert_called_once_with(
        "TestAgent", explicit_tenant_id)


def test_get_agent_by_name_api_exception(mocker, mock_auth_header):
    """Test get_agent_by_name_api exception handling."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=AsyncMock)
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")

    response = config_client.get(
        "/agent/by-name/NonExistentAgent",
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Agent not found" in response.json()["detail"]


# get_creating_sub_agent_info_api Tests
# ---------------------------------------------------------------------------


def test_get_creating_sub_agent_info_api_success(mocker, mock_auth_header):
    """Test get_creating_sub_agent_info_api success case."""
    mock_get_creating_agent = mocker.patch(
        "apps.agent_app.get_creating_sub_agent_info_impl", new_callable=AsyncMock)
    mock_get_creating_agent.return_value = {"agent_id": 456}

    response = config_client.get(
        "/agent/get_creating_sub_agent_id",
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_get_creating_agent.assert_called_once_with(
        mock_auth_header["Authorization"])
    assert response.json()["agent_id"] == 456


def test_get_creating_sub_agent_info_api_exception(mocker, mock_auth_header):
    """Test get_creating_sub_agent_info_api exception handling."""
    mock_get_creating_agent = mocker.patch(
        "apps.agent_app.get_creating_sub_agent_info_impl", new_callable=AsyncMock)
    mock_get_creating_agent.side_effect = Exception("Test error")

    response = config_client.get(
        "/agent/get_creating_sub_agent_id",
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Agent create error" in response.json()["detail"]


# update_agent_info_api Tests
# ---------------------------------------------------------------------------


def test_update_agent_info_api_success(mocker, mock_auth_header):
    """Test update_agent_info_api success case."""
    mock_update_agent = mocker.patch(
        "apps.agent_app.update_agent_info_impl", new_callable=AsyncMock)
    mock_update_agent.return_value = None

    response = config_client.post(
        "/agent/update",
        json={"agent_id": 123, "name": "Updated Agent",
              "display_name": "Updated Display Name"},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_update_agent.assert_called_once()
    assert response.json() == {}


def test_update_agent_info_api_with_result(mocker, mock_auth_header):
    """Test update_agent_info_api returns result when provided."""
    mock_update_agent = mocker.patch(
        "apps.agent_app.update_agent_info_impl", new_callable=AsyncMock)
    mock_update_agent.return_value = {"updated": True, "agent_id": 123}

    response = config_client.post(
        "/agent/update",
        json={"agent_id": 123, "name": "Updated Agent"},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    assert response.json()["updated"] is True


def test_update_agent_info_api_exception(mocker, mock_auth_header):
    """Test update_agent_info_api exception handling."""
    mock_update_agent = mocker.patch(
        "apps.agent_app.update_agent_info_impl", new_callable=AsyncMock)
    mock_update_agent.side_effect = Exception("Test error")

    response = config_client.post(
        "/agent/update",
        json={"agent_id": 123, "name": "Updated Agent"},
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Agent update error" in response.json()["detail"]


# delete_agent_api Tests
# ---------------------------------------------------------------------------


def test_delete_agent_api_success(mocker, mock_auth_header):
    """Test delete_agent_api success case without tenant_id query parameter."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_delete_agent = mocker.patch(
        "apps.agent_app.delete_agent_impl", new_callable=AsyncMock)
    # Mock return values
    mock_get_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_delete_agent.return_value = None

    response = config_client.request(
        "DELETE",
        "/agent",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_get_user_info.assert_called_once_with(
        mock_auth_header["Authorization"], ANY)
    mock_delete_agent.assert_called_once_with(123, "test_tenant", "test_user")
    assert response.json() == {}


def test_delete_agent_api_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test delete_agent_api success case with explicit tenant_id query parameter."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_delete_agent = mocker.patch(
        "apps.agent_app.delete_agent_impl", new_callable=AsyncMock)
    # Mock return values - auth tenant_id is different from explicit tenant_id
    mock_get_user_info.return_value = ("test_user", "auth_tenant", "en")
    mock_delete_agent.return_value = None

    explicit_tenant_id = "explicit_tenant_123"
    response = config_client.request(
        "DELETE",
        "/agent",
        json={"agent_id": 456},
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_delete_agent.assert_called_once_with(
        456, explicit_tenant_id, "test_user")


def test_delete_agent_api_exception(mocker, mock_auth_header):
    """Test delete_agent_api exception handling."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_delete_agent = mocker.patch(
        "apps.agent_app.delete_agent_impl", new_callable=AsyncMock)
    mock_logger = mocker.patch("apps.agent_app.logger")
    mock_get_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_delete_agent.side_effect = Exception("Test error")

    response = config_client.request(
        "DELETE",
        "/agent",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Agent delete error" in response.json()["detail"]
    mock_logger.error.assert_called_once_with("Agent delete error: Test error")


def test_delete_agent_api_exception_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test delete_agent_api exception handling with explicit tenant_id query parameter."""
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_delete_agent = mocker.patch(
        "apps.agent_app.delete_agent_impl", new_callable=AsyncMock)
    mock_logger = mocker.patch("apps.agent_app.logger")
    # Mock return values and exception
    mock_get_user_info.return_value = ("test_user", "auth_tenant", "en")
    mock_delete_agent.side_effect = Exception(
        "Test error with explicit tenant")

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
    mock_get_user_info.assert_called_once_with(
        mock_auth_header["Authorization"], ANY)
    # Should use explicit tenant_id even when exception occurs
    mock_delete_agent.assert_called_once_with(
        789, explicit_tenant_id, "test_user")
    assert "Agent delete error" in response.json()["detail"]
    # Verify error was logged
    mock_logger.error.assert_called_once_with(
        "Agent delete error: Test error with explicit tenant")


def test_export_agent_api_success(mocker, mock_auth_header):
    """Test export_agent_api success case returning JSON."""
    mock_export_agent = mocker.patch(
        "apps.agent_app.export_agent_with_skills_impl", new_callable=AsyncMock)
    mock_export_agent.return_value = {"agent_id": 123, "name": "Test Agent"}

    response = config_client.post(
        "/agent/export",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_export_agent.assert_called_once_with(
        123, mock_auth_header["Authorization"])
    assert response.json()["code"] == 0
    assert response.json()["message"] == "success"


def test_export_agent_api_success_with_zip(mocker, mock_auth_header):
    """Test export_agent_api success case returning ZIP file."""
    mock_export_agent = mocker.patch(
        "apps.agent_app.export_agent_with_skills_impl", new_callable=AsyncMock)
    mock_export_agent.return_value = {
        "_zip": True,
        "data": b"PK\x03\x04test zip content",
        "filename": "agent_export.zip"
    }

    response = config_client.post(
        "/agent/export",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment; filename=\"agent_export.zip\"" in response.headers["content-disposition"]
    assert response.content == b"PK\x03\x04test zip content"


def test_export_agent_api_success_with_zip_default_filename(mocker, mock_auth_header):
    """Test export_agent_api ZIP response with default filename."""
    mock_export_agent = mocker.patch(
        "apps.agent_app.export_agent_with_skills_impl", new_callable=AsyncMock)
    mock_export_agent.return_value = {
        "_zip": True,
        "data": b"PK\x03\x04minimal zip",
    }

    response = config_client.post(
        "/agent/export",
        json={"agent_id": 456},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment; filename=\"agent_export.zip\"" in response.headers["content-disposition"]


def test_export_agent_api_exception(mocker, mock_auth_header):
    """Test export_agent_api exception handling."""
    mock_export_agent = mocker.patch(
        "apps.agent_app.export_agent_with_skills_impl", new_callable=AsyncMock)
    mock_export_agent.side_effect = Exception("Test error")

    response = config_client.post(
        "/agent/export",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Agent export error" in response.json()["detail"]


# import_agent_api Tests
# ---------------------------------------------------------------------------


def test_check_skills_api_returns_conflicts(mocker, mock_auth_header):
    """Skill conflict precheck returns service results without importing data."""
    mock_check = mocker.patch("apps.agent_app.check_skill_conflicts_impl")
    mock_check.return_value = [{
        "skill_name": "SkillA",
        "suggested_new_name": "SkillA 副本",
    }]

    response = config_client.post(
        "/agent/check_skills",
        json={"skill_names": ["SkillA", "SkillB"]},
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    assert response.json() == {
        "skill_conflicts": [{
            "skill_name": "SkillA",
            "suggested_new_name": "SkillA 副本",
        }]
    }
    mock_check.assert_called_once_with(
        ["SkillA", "SkillB"],
        mock_auth_header["Authorization"],
    )


def test_check_skills_api_error(mocker, mock_auth_header):
    """Skill conflict precheck maps unexpected failures to a server error."""
    mocker.patch(
        "apps.agent_app.check_skill_conflicts_impl",
        side_effect=Exception("database unavailable"),
    )

    response = config_client.post(
        "/agent/check_skills",
        json={"skill_names": ["SkillA"]},
        headers=mock_auth_header,
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Agent skill conflict check error."


def test_import_agent_api_success_without_skills(mocker, mock_auth_header):
    """Test import_agent_api success case without skills."""
    mock_import_agent = mocker.patch(
        "apps.agent_app.import_agent_impl", new_callable=AsyncMock)
    mock_import_agent.return_value = {123: 456}

    response = config_client.post(
        "/agent/import",
        json={
            "agent_info": {
                "agent_id": 123,
                "agent_info": {
                    "test_agent": {
                        "agent_id": 123,
                        "name": "ImportedAgent",
                        "description": "Test description",
                        "business_description": "Business desc",
                        "max_steps": 10,
                        "provide_run_summary": True,
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

    assert response.status_code == 200
    mock_import_agent.assert_called_once()
    assert response.json() == {
        "agent_id": 456,
        "agent_id_mapping": {"123": 456},
    }


def test_import_agent_api_success_with_skills(mocker, mock_auth_header):
    """Test import_agent_api success case with skills."""
    mock_import_with_skills = mocker.patch(
        "apps.agent_app.import_agent_with_skills_impl", new_callable=AsyncMock)
    mock_import_with_skills.return_value = {123: 456}

    response = config_client.post(
        "/agent/import",
        json={
            "agent_info": {
                "agent_id": 123,
                "agent_info": {
                    "test_agent": {
                        "agent_id": 123,
                        "name": "ImportedAgent",
                        "description": "Test description",
                        "business_description": "Business desc",
                        "max_steps": 10,
                        "provide_run_summary": True,
                        "enabled": True,
                        "tools": [],
                        "managed_agents": []
                    }
                },
                "mcp_info": []
            },
            "skills": [{"skill_name": "test_skill", "skill_zip_base64": "dGVzdA=="}],
            "skill_resolutions": [{
                "skill_name": "test_skill",
                "action": "rename",
                "new_name": "test_skill 副本"
            }],
            "force_import": True
        },
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_import_with_skills.assert_called_once()
    args, kwargs = mock_import_with_skills.call_args
    assert kwargs["force_import"] is True
    assert kwargs["skill_resolutions"][0].new_name == "test_skill 副本"


def test_import_agent_api_duplicate_error(mocker, mock_auth_header):
    """Test import_agent_api with SkillDuplicateError."""
    from consts.exceptions import SkillDuplicateError
    mock_import_agent = mocker.patch(
        "apps.agent_app.import_agent_impl", new_callable=AsyncMock)
    mock_import_agent.side_effect = SkillDuplicateError(
        duplicate_names=["skill1", "skill2"],
        skill_conflicts=[{
            "skill_name": "skill1",
            "suggested_new_name": "skill1 副本",
        }],
    )

    response = config_client.post(
        "/agent/import",
        json={
            "agent_info": {
                "agent_id": 123,
                "agent_info": {
                    "test_agent": {
                        "agent_id": 123,
                        "name": "TestAgent",
                        "description": "Test description",
                        "business_description": "Business desc",
                        "max_steps": 10,
                        "provide_run_summary": True,
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

    assert response.status_code == 409
    assert response.json()["detail"]["type"] == "skill_duplicate"
    assert "skill1" in response.json()["detail"]["duplicate_skills"]
    assert response.json()["detail"]["skill_conflicts"][0]["suggested_new_name"] == "skill1 副本"


def test_import_agent_api_exception(mocker, mock_auth_header):
    """Test import_agent_api exception handling."""
    mock_import_agent = mocker.patch(
        "apps.agent_app.import_agent_impl", new_callable=AsyncMock)
    mock_import_agent.side_effect = Exception("Test error")

    response = config_client.post(
        "/agent/import",
        json={
            "agent_info": {
                "agent_id": 123,
                "agent_info": {
                    "test_agent": {
                        "agent_id": 123,
                        "name": "TestAgent",
                        "description": "Test description",
                        "business_description": "Business desc",
                        "max_steps": 10,
                        "provide_run_summary": True,
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

    assert response.status_code == 500
    assert "Agent import error" in response.json()["detail"]


# list_all_agent_info_api Tests
# ---------------------------------------------------------------------------


def test_list_all_agent_info_api_success(mocker, mock_auth_header):
    """Test list_all_agent_info_api success case without tenant_id."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "apps.agent_app.list_all_agent_info_impl", new_callable=AsyncMock)
    # Mock return values
    mock_get_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_list_all_agent.return_value = [
        {"agent_id": 1, "name": "Agent 1", "display_name": "Display Agent 1"},
        {"agent_id": 2, "name": "Agent 2", "display_name": "Display Agent 2"}
    ]

    response = config_client.get(
        "/agent/list",
        headers=mock_auth_header
    )

    assert response.status_code == 200
    assert mock_list_all_agent.call_count == 2
    mock_list_all_agent.assert_any_call(
        tenant_id="test_tenant", user_id="test_user")
    mock_list_all_agent.assert_any_call(
        tenant_id=ASSET_OWNER_TENANT_ID, user_id="test_user")
    assert len(response.json()) == 4


def test_list_all_agent_info_api_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test list_all_agent_info_api success case with explicit tenant_id."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "apps.agent_app.list_all_agent_info_impl", new_callable=AsyncMock)
    # Mock return values - auth tenant_id is different from explicit tenant_id
    mock_get_user_info.return_value = ("test_user", "auth_tenant", "en")
    mock_list_all_agent.return_value = [{"agent_id": 3, "name": "Agent 3"}]

    explicit_tenant_id = "explicit_tenant_123"
    response = config_client.get(
        "/agent/list",
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_list_all_agent.assert_called_once_with(
        tenant_id=explicit_tenant_id, user_id="test_user")
    assert response.json() == [{"agent_id": 3, "name": "Agent 3"}]


def test_list_all_agent_info_api_asset_owner_tenant_single_query(mocker, mock_auth_header):
    """Asset-owner tenant callers only query their own tenant (no merge)."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "apps.agent_app.list_all_agent_info_impl", new_callable=AsyncMock)
    mock_get_user_info.return_value = ("ao_user", ASSET_OWNER_TENANT_ID, "en")
    mock_list_all_agent.return_value = [{"agent_id": 1, "name": "AO Agent"}]

    response = config_client.get("/agent/list", headers=mock_auth_header)

    assert response.status_code == 200
    mock_list_all_agent.assert_called_once_with(
        tenant_id=ASSET_OWNER_TENANT_ID, user_id="ao_user"
    )
    assert len(response.json()) == 1


def test_list_all_agent_info_api_exception(mocker, mock_auth_header):
    """Test list_all_agent_info_api exception handling."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "apps.agent_app.list_all_agent_info_impl", new_callable=AsyncMock)
    # Mock return values and exception
    mock_get_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_list_all_agent.side_effect = Exception("Test error")

    response = config_client.get(
        "/agent/list",
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Agent list error" in response.json()["detail"]


def test_list_all_agent_info_api_exception_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test list_all_agent_info_api exception handling with explicit tenant_id query parameter."""
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "apps.agent_app.list_all_agent_info_impl", new_callable=AsyncMock)
    # Mock return values and exception
    mock_get_user_info.return_value = ("test_user", "auth_tenant", "en")
    mock_list_all_agent.side_effect = Exception(
        "Test error with explicit tenant")

    # Test the endpoint with explicit tenant_id query parameter
    explicit_tenant_id = "explicit_tenant_456"
    response = config_client.get(
        "/agent/list",
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    mock_get_user_info.assert_called_once_with(
        mock_auth_header["Authorization"], ANY)
    # With explicit tenant_id, list_all_agent_info_impl is called once (no ASSET_OWNER merge)
    mock_list_all_agent.assert_called_once_with(
        tenant_id=explicit_tenant_id, user_id="test_user")
    assert "Agent list error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_export_agent_api_detailed(mocker, mock_auth_header):
    """Detailed testing of export_agent_api function, including ConversationResponse construction"""
    # Setup mocks using pytest-mock
    mock_export_agent = mocker.patch(
        "apps.agent_app.export_agent_with_skills_impl", new_callable=AsyncMock)

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
        "apps.agent_app.export_agent_with_skills_impl", new_callable=AsyncMock)

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
    Provide fallback aliases for dynamic `management.services.agent.service` imports used by the routers.
    Map `backend.services.*` modules to `services.*` so mocker.patch can locate them.
    """
    import sys
    try:
        import backend.services as b_services
        import management.services.agent.service as b_agent_service
        # Map both the package and submodule for compatibility
        sys.modules['services'] = b_services
        sys.modules['management.services.agent.service'] = b_agent_service
    except Exception:
        # If the project already supports direct imports, ignore the failure
        pass


def test_get_agent_call_relationship_api_success(mocker, mock_auth_header):
    """Test get_agent_call_relationship_api success case."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_impl = mocker.patch("apps.agent_app.get_agent_call_relationship_impl")
    mock_get_user_id.return_value = ("user_id_x", "tenant_abc")
    mock_impl.return_value = {
        "agent_id": 1,
        "tree": {"tools": [], "sub_agents": []}
    }

    resp = config_client.get(
        "/agent/call_relationship/1", headers=mock_auth_header)

    assert resp.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_impl.assert_called_once_with(1, "tenant_abc")
    data = resp.json()
    assert data["agent_id"] == 1


def test_get_agent_call_relationship_api_exception(mocker, mock_auth_header):
    """Test get_agent_call_relationship_api exception handling."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_impl = mocker.patch("apps.agent_app.get_agent_call_relationship_impl")
    mock_get_user_id.return_value = ("user_id_x", "tenant_abc")
    mock_impl.side_effect = Exception("boom")

    resp = config_client.get(
        "/agent/call_relationship/999", headers=mock_auth_header)

    assert resp.status_code == 500
    assert "Failed to get agent call relationship" in resp.json()["detail"]


# check_agent_name_batch_api Tests
# ---------------------------------------------------------------------------


def test_check_agent_name_batch_api_success(mocker, mock_auth_header):
    """Test check_agent_name_batch_api success case."""
    mock_impl = mocker.patch(
        "apps.agent_app.check_agent_name_conflict_batch_impl",
        new_callable=AsyncMock,
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
    """Test check_agent_name_batch_api with ValueError."""
    mock_impl = mocker.patch(
        "apps.agent_app.check_agent_name_conflict_batch_impl",
        new_callable=AsyncMock,
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
    """Test check_agent_name_batch_api with general exception."""
    mock_impl = mocker.patch(
        "apps.agent_app.check_agent_name_conflict_batch_impl",
        new_callable=AsyncMock,
    )
    mock_impl.side_effect = Exception("unexpected")

    resp = config_client.post(
        "/agent/check_name",
        json={"items": [{"agent_id": 1, "name": "AgentA"}]},
        headers=mock_auth_header,
    )

    assert resp.status_code == 500
    assert "Agent name batch check error" in resp.json()["detail"]


# regenerate_agent_name_batch_api Tests
# ---------------------------------------------------------------------------


def test_regenerate_agent_name_batch_api_success(mocker, mock_auth_header):
    """Test regenerate_agent_name_batch_api success case."""
    mock_impl = mocker.patch(
        "apps.agent_app.regenerate_agent_name_batch_impl",
        new_callable=AsyncMock,
    )
    mock_impl.return_value = [
        {"name": "NewName", "display_name": "New Display"}]

    payload = {
        "items": [
            {"agent_id": 1, "name": "AgentA",
                "display_name": "Agent A", "task_description": "desc"},
        ]
    }

    resp = config_client.post(
        "/agent/regenerate_name", json=payload, headers=mock_auth_header
    )

    assert resp.status_code == 200
    mock_impl.assert_called_once()
    assert resp.json() == [{"name": "NewName", "display_name": "New Display"}]


def test_regenerate_agent_name_batch_api_bad_request(mocker, mock_auth_header):
    """Test regenerate_agent_name_batch_api with ValueError."""
    mock_impl = mocker.patch(
        "apps.agent_app.regenerate_agent_name_batch_impl",
        new_callable=AsyncMock,
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
    """Test regenerate_agent_name_batch_api with general exception."""
    mock_impl = mocker.patch(
        "apps.agent_app.regenerate_agent_name_batch_impl",
        new_callable=AsyncMock,
    )
    mock_impl.side_effect = Exception("boom")

    resp = config_client.post(
        "/agent/regenerate_name",
        json={"items": [{"agent_id": 1, "name": "AgentA"}]},
        headers=mock_auth_header,
    )

    assert resp.status_code == 500
    assert "Agent name batch regenerate error" in resp.json()["detail"]


# clear_agent_new_mark_api Tests
# ---------------------------------------------------------------------------


def test_clear_agent_new_mark_api_success(mocker, mock_auth_header):
    """Test clear_agent_new_mark_api success case."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_clear_agent_new_mark = mocker.patch(
        "apps.agent_app.clear_agent_new_mark_impl", new_callable=AsyncMock)

    mock_get_user_info.return_value = (
        "test_user_id", "test_tenant_id", "extra_info")
    mock_clear_agent_new_mark.return_value = 1

    response = config_client.put(
        "/agent/clear_new/123",
        headers=mock_auth_header
    )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["message"] == "Agent NEW mark cleared successfully"
    assert response_data["affected_rows"] == 1
    mock_clear_agent_new_mark.assert_called_once_with(
        123, "test_tenant_id", "test_user_id")


def test_clear_agent_new_mark_api_exception(mocker, mock_auth_header):
    """Test clear_agent_new_mark_api exception handling."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_clear_agent_new_mark = mocker.patch(
        "apps.agent_app.clear_agent_new_mark_impl", new_callable=AsyncMock)
    mock_logger = mocker.patch("apps.agent_app.logger")

    mock_get_user_info.return_value = (
        "test_user_id", "test_tenant_id", "extra_info")
    mock_clear_agent_new_mark.side_effect = Exception(
        "Database connection failed")

    response = config_client.put(
        "/agent/clear_new/456",
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to clear agent NEW mark."
    mock_logger.error.assert_called_once()


# Agent Version Management API Tests
# ---------------------------------------------------------------------------


def test_publish_version_api_success(mocker, mock_auth_header):
    """Test publish_version_api success case."""
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
    mock_publish_version.assert_called_once_with(
        agent_id=123,
        tenant_id="test_tenant_id",
        user_id="test_user_id",
        version_name="v1.0.0",
        release_note="Initial release"
    )
    assert response.json()["success"] is True


def test_publish_version_api_ignores_publish_as_a2a_request_field(mocker, mock_auth_header):
    """Test publish_version_api does not accept publish_as_a2a as an API option."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_publish_version = mocker.patch("apps.agent_app.publish_version_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_publish_version.return_value = {"success": True, "version_no": 1}

    response = config_client.post(
        "/agent/123/publish",
        json={
            "version_name": "v1.0.0",
            "release_note": "Release",
            "publish_as_a2a": True
        },
        headers=mock_auth_header
    )

    assert response.status_code == 200
    _, kwargs = mock_publish_version.call_args
    assert "publish_as_a2a" not in kwargs


def test_publish_version_api_bad_request(mocker, mock_auth_header):
    """Test publish_version_api with ValueError."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_publish_version = mocker.patch("apps.agent_app.publish_version_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_publish_version.side_effect = ValueError("Agent not found")

    response = config_client.post(
        "/agent/123/publish",
        json={"version_name": "v1.0.0", "release_note": "Release"},
        headers=mock_auth_header
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Agent not found"


def test_publish_version_api_exception(mocker, mock_auth_header):
    """Test publish_version_api with general exception."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_publish_version = mocker.patch("apps.agent_app.publish_version_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_publish_version.side_effect = Exception("Database error")

    response = config_client.post(
        "/agent/123/publish",
        json={"version_name": "v1.0.0", "release_note": "Release"},
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Publish version error" in response.json()["detail"]


def test_compare_versions_api_success(mocker, mock_auth_header):
    """Test compare_versions_api success case."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_compare_versions = mocker.patch(
        "apps.agent_app.compare_versions_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_compare_versions.return_value = {
        "success": True,
        "data": {"version_a": {}, "version_b": {}, "differences": []}
    }

    response = config_client.post(
        "/agent/123/versions/compare",
        json={"version_no_a": 1, "version_no_b": 2},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_compare_versions.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant_id", version_no_a=1, version_no_b=2
    )
    assert response.json()["success"] is True


def test_compare_versions_api_bad_request(mocker, mock_auth_header):
    """Test compare_versions_api with ValueError."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_compare_versions = mocker.patch(
        "apps.agent_app.compare_versions_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_compare_versions.side_effect = ValueError("Version not found")

    response = config_client.post(
        "/agent/123/versions/compare",
        json={"version_no_a": 1, "version_no_b": 2},
        headers=mock_auth_header
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Version not found"


def test_compare_versions_api_exception(mocker, mock_auth_header):
    """Test compare_versions_api with general exception."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_compare_versions = mocker.patch(
        "apps.agent_app.compare_versions_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_compare_versions.side_effect = Exception("Database error")

    response = config_client.post(
        "/agent/123/versions/compare",
        json={"version_no_a": 1, "version_no_b": 2},
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Compare versions error" in response.json()["detail"]


def test_get_version_list_api_success(mocker, mock_auth_header):
    """Test get_version_list_api success case."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_get_version_list = mocker.patch(
        "apps.agent_app.get_version_list_impl")

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
    mock_get_version_list.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant_id")
    assert len(response.json()["versions"]) == 2


def test_get_version_list_api_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test get_version_list_api with explicit tenant_id."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_get_version_list = mocker.patch(
        "apps.agent_app.get_version_list_impl")

    mock_get_user_info.return_value = ("test_user_id", "auth_tenant_id", "en")
    mock_get_version_list.return_value = {"versions": []}

    explicit_tenant_id = "explicit_tenant_456"
    response = config_client.get(
        "/agent/123/versions",
        params={"tenant_id": explicit_tenant_id},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_get_version_list.assert_called_once_with(
        agent_id=123, tenant_id=explicit_tenant_id)


def test_get_version_list_api_exception(mocker, mock_auth_header):
    """Test get_version_list_api with exception."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_get_version_list = mocker.patch(
        "apps.agent_app.get_version_list_impl")

    mock_get_user_info.return_value = ("test_user_id", "test_tenant_id", "en")
    mock_get_version_list.side_effect = Exception("Database error")

    response = config_client.get(
        "/agent/123/versions",
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Get version list error" in response.json()["detail"]


def test_get_version_api_success(mocker, mock_auth_header):
    """Test get_version_api success case."""
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
    mock_get_version.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant_id", version_no=1)
    assert response.json()["version_no"] == 1


def test_get_version_api_not_found(mocker, mock_auth_header):
    """Test get_version_api with ValueError (not found)."""
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
    """Test get_version_api with general exception."""
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
    """Test get_version_detail_api success case."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_version_detail = mocker.patch(
        "apps.agent_app._get_version_detail_or_draft")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_version_detail.return_value = {
        "version_no": 1,
        "version_name": "v1.0.0",
        "agent_snapshot": {"agent_id": 123, "name": "Test Agent"},
        "tool_snapshots": [],
        "relation_snapshots": []
    }

    response = config_client.get(
        "/agent/123/versions/1/detail",
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_get_version_detail.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant_id", version_no=1
    )
    assert "agent_snapshot" in response.json()


def test_get_version_detail_api_draft_version_success(mocker, mock_auth_header):
    """Test get_version_detail_api with draft version_no=0."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_version_detail = mocker.patch(
        "apps.agent_app._get_version_detail_or_draft")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_version_detail.return_value = {
        "agent_id": 123,
        "name": "Draft Agent",
        "version": {
            "version_name": "Draft",
            "version_status": "DRAFT",
        },
        "tools": [],
    }

    response = config_client.get(
        "/agent/123/versions/0/detail",
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_get_version_detail.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant_id", version_no=0
    )
    assert response.json()["name"] == "Draft Agent"


def test_get_version_detail_api_not_found(mocker, mock_auth_header):
    """Test get_version_detail_api with ValueError (not found)."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_version_detail = mocker.patch(
        "apps.agent_app._get_version_detail_or_draft")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_version_detail.side_effect = ValueError("Version not found")

    response = config_client.get(
        "/agent/123/versions/999/detail",
        headers=mock_auth_header
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Version not found"


def test_get_version_detail_api_exception(mocker, mock_auth_header):
    """Test get_version_detail_api with general exception."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_version_detail = mocker.patch(
        "apps.agent_app._get_version_detail_or_draft")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_version_detail.side_effect = Exception("Database error")

    response = config_client.get(
        "/agent/123/versions/1/detail",
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Get version detail error" in response.json()["detail"]


def test_rollback_version_api_success(mocker, mock_auth_header):
    """Test rollback_version_api success case."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_rollback_version = mocker.patch(
        "apps.agent_app.rollback_version_impl")

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
    mock_rollback_version.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant_id", target_version_no=1
    )
    assert response.json()["success"] is True


def test_rollback_version_api_bad_request(mocker, mock_auth_header):
    """Test rollback_version_api with ValueError."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_rollback_version = mocker.patch(
        "apps.agent_app.rollback_version_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_rollback_version.side_effect = ValueError("Version not found")

    response = config_client.post(
        "/agent/123/versions/999/rollback",
        headers=mock_auth_header
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Version not found"


def test_rollback_version_api_exception(mocker, mock_auth_header):
    """Test rollback_version_api with general exception."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_rollback_version = mocker.patch(
        "apps.agent_app.rollback_version_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_rollback_version.side_effect = Exception("Database error")

    response = config_client.post(
        "/agent/123/versions/1/rollback",
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Rollback version error" in response.json()["detail"]


def test_update_version_status_api_success(mocker, mock_auth_header):
    """Test update_version_status_api success case."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_update_version_status = mocker.patch(
        "apps.agent_app.update_version_status_impl")

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
    mock_update_version_status.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant_id", user_id="test_user_id",
        version_no=1, status="DISABLED"
    )
    assert response.json()["success"] is True


def test_update_version_status_api_bad_request(mocker, mock_auth_header):
    """Test update_version_status_api with ValueError."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_update_version_status = mocker.patch(
        "apps.agent_app.update_version_status_impl")

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
    """Test update_version_status_api with general exception."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_update_version_status = mocker.patch(
        "apps.agent_app.update_version_status_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_update_version_status.side_effect = Exception("Database error")

    response = config_client.patch(
        "/agent/123/versions/1/status",
        json={"status": "DISABLED"},
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Update version status error" in response.json()["detail"]


def test_update_version_api_success(mocker, mock_auth_header):
    """Test update_version_api success case."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_update_version = mocker.patch("apps.agent_app.update_version_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_update_version.return_value = {
        "message": "Version updated successfully",
        "version_no": 1
    }

    response = config_client.put(
        "/agent/123/versions/1",
        json={"version_name": "Updated Version",
              "release_note": "Updated note"},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_update_version.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant_id", user_id="test_user_id",
        version_no=1, version_name="Updated Version", release_note="Updated note"
    )
    assert response.json()["version_no"] == 1


def test_update_version_api_bad_request(mocker, mock_auth_header):
    """Test update_version_api with ValueError."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_update_version = mocker.patch("apps.agent_app.update_version_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_update_version.side_effect = ValueError("No changes to update")

    response = config_client.put(
        "/agent/123/versions/1",
        json={"version_name": "Updated Version"},
        headers=mock_auth_header
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "No changes to update"


def test_update_version_api_exception(mocker, mock_auth_header):
    """Test update_version_api with general exception."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_update_version = mocker.patch("apps.agent_app.update_version_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_update_version.side_effect = Exception("Database error")

    response = config_client.put(
        "/agent/123/versions/1",
        json={"version_name": "Updated Version"},
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Update version error" in response.json()["detail"]


def test_delete_version_api_success(mocker, mock_auth_header):
    """Test delete_version_api success case."""
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
    mock_delete_version.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant_id", user_id="test_user_id", version_no=1
    )
    assert response.json()["success"] is True


def test_delete_version_api_bad_request(mocker, mock_auth_header):
    """Test delete_version_api with ValueError."""
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
    """Test delete_version_api with general exception."""
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
    """Test get_current_version_api success case."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_current_version = mocker.patch(
        "apps.agent_app.get_current_version_impl")

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
    mock_get_current_version.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant_id")
    assert response.json()["version_no"] == 1


def test_get_current_version_api_not_found(mocker, mock_auth_header):
    """Test get_current_version_api with ValueError (not found)."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_current_version = mocker.patch(
        "apps.agent_app.get_current_version_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_current_version.side_effect = ValueError(
        "No published version found")

    response = config_client.get(
        "/agent/123/current_version",
        headers=mock_auth_header
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "No published version found"


def test_get_current_version_api_exception(mocker, mock_auth_header):
    """Test get_current_version_api with general exception."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_current_version = mocker.patch(
        "apps.agent_app.get_current_version_impl")

    mock_get_user_id.return_value = ("test_user_id", "test_tenant_id")
    mock_get_current_version.side_effect = Exception("Database error")

    response = config_client.get(
        "/agent/123/current_version",
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Get current version error" in response.json()["detail"]


def test_list_published_agents_api_success(mocker, mock_auth_header):
    """Test list_published_agents_api success case."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_published_agents = mocker.patch(
        "apps.agent_app.list_published_agents_impl", new_callable=AsyncMock)

    mock_get_user_info.return_value = ("test_user_id", "test_tenant_id", "en")
    mock_list_published_agents.side_effect = [
        [{"agent_id": 1, "name": "Agent 1", "published_version_no": 1}],
        [{"agent_id": 2, "name": "Asset Agent", "published_version_no": 1}],
    ]

    response = config_client.get(
        "/agent/published_list",
        headers=mock_auth_header
    )

    assert response.status_code == 200
    assert mock_list_published_agents.call_count == 2
    mock_list_published_agents.assert_any_call(
        tenant_id="test_tenant_id", user_id="test_user_id"
    )
    mock_list_published_agents.assert_any_call(
        tenant_id=ASSET_OWNER_TENANT_ID, user_id="test_user_id"
    )
    assert len(response.json()) == 2


def test_list_published_agents_api_asset_owner_tenant_single_query(mocker, mock_auth_header):
    """Asset-owner tenant callers only query published agents once (no merge)."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_published_agents = mocker.patch(
        "apps.agent_app.list_published_agents_impl", new_callable=AsyncMock)
    mock_get_user_info.return_value = ("ao_user", ASSET_OWNER_TENANT_ID, "en")
    mock_list_published_agents.return_value = [
        {"agent_id": 1, "name": "AO Agent", "published_version_no": 1},
    ]

    response = config_client.get("/agent/published_list", headers=mock_auth_header)

    assert response.status_code == 200
    mock_list_published_agents.assert_called_once_with(
        tenant_id=ASSET_OWNER_TENANT_ID, user_id="ao_user"
    )
    assert len(response.json()) == 1


def test_list_published_agents_api_exception(mocker, mock_auth_header):
    """Test list_published_agents_api with exception."""
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_published_agents = mocker.patch(
        "apps.agent_app.list_published_agents_impl", new_callable=AsyncMock)

    mock_get_user_info.return_value = ("test_user_id", "test_tenant_id", "en")
    mock_list_published_agents.side_effect = Exception("Database error")

    response = config_client.get(
        "/agent/published_list",
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Published agents list error" in response.json()["detail"]

# ---------------------------------------------------------------------------
# get_agent_knowledge_capabilities_api Tests
# ---------------------------------------------------------------------------


def test_get_agent_knowledge_capabilities_api_success(mocker, mock_auth_header):
    """get_agent_knowledge_capabilities_api returns the resolved capability tree."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_caps = mocker.patch(
        "apps.agent_app.get_agent_knowledge_capabilities")
    mock_get_user_id.return_value = ("user-1", "tenant-1")
    mock_caps.return_value = {
        "local": [{"index_name": "idx-a"}],
        "aidp": [],
    }

    response = config_client.get(
        "/agent/7/knowledge-capabilities",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["message"] == "success"
    assert body["data"] == mock_caps.return_value
    mock_caps.assert_called_once_with(
        agent_id=7, tenant_id="tenant-1", version_no=None, user_id="user-1")


def test_get_agent_knowledge_capabilities_api_with_version(mocker, mock_auth_header):
    """version_no query parameter is forwarded to the resolver."""
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_caps = mocker.patch(
        "apps.agent_app.get_agent_knowledge_capabilities")
    mock_get_user_id.return_value = ("user-1", "tenant-1")
    mock_caps.return_value = {}

    response = config_client.get(
        "/agent/7/knowledge-capabilities",
        params={"version_no": 3},
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_caps.assert_called_once_with(
        agent_id=7, tenant_id="tenant-1", version_no=3, user_id="user-1")


def test_get_agent_knowledge_capabilities_api_value_error(mocker, mock_auth_header):
    """ValueError from the resolver maps to 404."""
    mocker.patch("apps.agent_app.get_current_user_id",
                 return_value=("user-1", "tenant-1"))
    mocker.patch(
        "apps.agent_app.get_agent_knowledge_capabilities",
        side_effect=ValueError("agent not found"),
    )

    response = config_client.get(
        "/agent/404/knowledge-capabilities",
        headers=mock_auth_header,
    )

    assert response.status_code == 404
    assert "agent not found" in response.json()["detail"]


@pytest.mark.parametrize(
    ("error", "expected_status", "detail"),
    [
        (ForbiddenError("You do not have permission"), 403, "You do not have permission"),
        (ValueError("Agent icon is invalid"), 400, "Agent icon is invalid"),
        (RuntimeError("storage unavailable"), 500, "Agent icon upload error."),
    ],
)
def test_upload_agent_icon_api_error_mapping(mocker, mock_auth_header, error, expected_status, detail):
    mocker.patch("apps.agent_app.get_current_user_id", return_value=("user-1", "tenant-1"))
    mocker.patch("apps.agent_app.upload_agent_icon_impl", new_callable=AsyncMock, side_effect=error)

    response = config_client.post(
        "/agent/7/icon",
        files={"file": ("icon.png", b"png-content", "image/png")},
        headers=mock_auth_header,
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == detail


def test_upload_agent_icon_api_success(mocker, mock_auth_header):
    mocker.patch("apps.agent_app.get_current_user_id", return_value=("user-1", "tenant-1"))
    upload_impl = mocker.patch(
        "apps.agent_app.upload_agent_icon_impl",
        new_callable=AsyncMock,
        return_value={"icon_url": "/api/agent/7/icon", "content_type": "image/png"},
    )

    response = config_client.post(
        "/agent/7/icon",
        files={"file": ("icon.png", b"png-content", "image/png")},
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    assert response.json() == {
        "icon_url": "/api/agent/7/icon",
        "content_type": "image/png",
    }
    upload_impl.assert_awaited_once_with(
        agent_id=7,
        content=b"png-content",
        tenant_id="tenant-1",
        user_id="user-1",
    )


def test_get_agent_icon_api_success(mocker, mock_auth_header):
    mocker.patch("apps.agent_app.get_current_user_id", return_value=("user-1", "tenant-1"))
    get_impl = mocker.patch(
        "apps.agent_app.get_agent_icon_impl",
        new_callable=AsyncMock,
        return_value=(b"image-bytes", "image/webp"),
    )

    response = config_client.get("/agent/7/icon", headers=mock_auth_header)

    assert response.status_code == 200
    assert response.content == b"image-bytes"
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "private, max-age=3600"
    get_impl.assert_awaited_once_with(
        agent_id=7,
        tenant_id="tenant-1",
        user_id="user-1",
    )


def test_get_agent_icon_api_not_found(mocker, mock_auth_header):
    mocker.patch("apps.agent_app.get_current_user_id", return_value=("user-1", "tenant-1"))
    mocker.patch(
        "apps.agent_app.get_agent_icon_impl",
        new_callable=AsyncMock,
        side_effect=FileNotFoundError("Agent icon not found"),
    )

    response = config_client.get("/agent/7/icon", headers=mock_auth_header)

    assert response.status_code == 404
    assert response.json()["detail"] == "Agent icon not found"


def test_get_agent_icon_api_internal_error(mocker, mock_auth_header):
    mocker.patch("apps.agent_app.get_current_user_id", return_value=("user-1", "tenant-1"))
    mocker.patch(
        "apps.agent_app.get_agent_icon_impl",
        new_callable=AsyncMock,
        side_effect=RuntimeError("storage unavailable"),
    )

    response = config_client.get("/agent/7/icon", headers=mock_auth_header)

    assert response.status_code == 500
    assert response.json()["detail"] == "Agent icon retrieval error."
