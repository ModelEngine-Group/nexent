# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
Unit tests for management.api.agent.agent module.

Tests all agent management API endpoints including runtime and configuration operations.
"""
from contracts.authentication import AuthenticatedIdentity
import atexit
import json
from http import HTTPStatus
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

from contracts.constants.constants import AGENT_PROMPTS_HIDDEN_FLAG
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, ForbiddenError, TenantResourceLimitError, UnauthorizedError, ValidationError, tenant_resource_limit_error_payload
from contracts.agent import NL2AgentRunRequest
from contracts.errors.exceptions import AgentDraftEditError, AgentRunAlreadyActiveError
from management.services.agent.nl2agent import Nl2AgentDraftSaveError
from infrastructure.agentos_identity import ServicePrincipal
# Load the Runtime dependencies before the local SDK stubs.
import runtime.agentos.ephemeral
import management.services.model.adapter
from management.api import northbound
from management.api.agent.creator import nl2agent_run_api, require_agent_create_permission, router as agent_creator_router
from nexent.monitor import AgentRunMetadata, agent_monitoring_context

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
patch('infrastructure.object_storage.client.MinioClient', return_value=minio_mock).start()
patch('infrastructure.object_storage.client.MinioClient', return_value=minio_mock).start()
patch('infrastructure.object_storage.client.minio_client', minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Apply patches before importing any app modules (similar to test_config_app.py)
patches = [
    # Mock database sessions
    patch('infrastructure.rdb.client.get_db_session', return_value=Mock())
]

for p in patches:
    p.start()

# Import target endpoints with all external dependencies patched

# Mock external dependencies before importing the modules that use them
# Stub agent model types used by contracts.agent and Workbench knowledge services.
agent_model_stub = types.ModuleType("agent_model")


class ToolConfig:  # minimal stub for type reference
    pass


class AgentConfig:  # minimal stub for type reference
    pass


agent_model_stub.ToolConfig = ToolConfig
agent_model_stub.AgentConfig = AgentConfig

# Define a decorator that simply returns the original function unchanged


def pass_through_decorator(*args, **kwargs):
    def decorator(func):
        return func
    return decorator


monitoring_stub = types.ModuleType("monitor")
monitoring_stub.agent_monitoring_context = MagicMock()
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
monitoring_stub.AgentRunMetadata = AgentRunMetadata
monitoring_stub.agent_monitoring_context = agent_monitoring_context

# Mock all external dependencies that agent_app.py imports
# These must be in sys.modules BEFORE we import management.api.agent.agent
sys.modules['nexent'] = types.ModuleType('nexent')
sys.modules['nexent.core'] = types.ModuleType('nexent.core')
sys.modules['nexent.core.agents'] = types.ModuleType('nexent.core.agents')
sys.modules['nexent.core.agents.contracts.config'] = agent_model_stub
sys.modules['nexent.monitor'] = monitoring_stub
sys.modules['nexent.monitor.monitoring'] = monitoring_stub
sys.modules['infrastructure.rdb.client'] = MagicMock()
sys.modules["infrastructure.object_storage.client"] = sys.modules["infrastructure.rdb.client"]
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["infrastructure.rdb.client"])
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["infrastructure.rdb.client"])
sys.modules['management.db.agent.repository'] = MagicMock()
sys.modules["management.services.agent.preparation.run"] = MagicMock()
sys.modules["management.services.agent.preparation.tools"] = MagicMock()

sys.modules['nexent.core.agents.orchestration.entry'] = MagicMock()
sys.modules['management.services.permission.identity.session'] = MagicMock()
sys.modules['management.services.permission.identity.session'].get_current_user_id.return_value = ('test_user', 'test_tenant')
sys.modules['management.services.configuration.tenant.settings'] = MagicMock()
sys.modules['utils.thread_utils'] = MagicMock()
sys.modules['infrastructure.trace.bootstrap'] = MagicMock()
sys.modules['infrastructure.trace.bootstrap'].monitoring_manager = monitoring_manager_mock
sys.modules['infrastructure.trace.bootstrap'].setup_fastapi_app = MagicMock(
    return_value=True)
sys.modules['management.services.agent.lifecycle'] = MagicMock()
sys.modules['management.services.agent.lifecycle'].AgentRunAlreadyActiveError = AgentRunAlreadyActiveError
sys.modules['management.services.agent.service'] = MagicMock()
sys.modules['management.services.agent.subscription'] = MagicMock()
sys.modules['management.services.skill.service'] = MagicMock()
sys.modules['management.services.conversation.service'] = MagicMock()
sys.modules['management.services.configuration.user.memory'] = MagicMock()
sys.modules['management.services.agent.versions'] = MagicMock()
sys.modules['management.services.agent.prompt_generation'] = MagicMock()

from importlib.machinery import ModuleSpec as _SDKModuleSpec
from pathlib import Path as _SDKPath
for _package in ("nexent", "nexent.core", "nexent.core.agents", "nexent.core.models", "nexent.core.agents.contracts"):
    if _package in sys.modules:
        sys.modules[_package].__path__ = [str(_SDKPath(__file__).resolve().parents[3] / "sdk" / _package.replace(".", "/"))]
        sys.modules[_package].__spec__ = _SDKModuleSpec(_package, loader=None, is_package=True)
        sys.modules[_package].__package__ = _package

# Now safe to import app modules after all mocks are set up
from management.api.agent.agent import agent_config_router, get_workbench_bootstrap_api
from management.api.agent import conversation_run
from backend.http.server.app_factory import register_exception_handlers



# Create FastAPI apps for runtime and config routers
runtime_app = FastAPI()
runtime_app.include_router(conversation_run.router)
config_creator_app = FastAPI()
config_creator_app.include_router(agent_creator_router)
config_creator_app.dependency_overrides[require_agent_create_permission] = lambda: None
runtime_client = TestClient(runtime_app)

config_app = FastAPI()
config_app.include_router(agent_config_router)
config_client = TestClient(config_app)


@pytest.fixture
def mock_auth_header():
    return {"Authorization": "Bearer test_token"}


@pytest.fixture(autouse=True)
def conversation_identity(mocker):
    return mocker.patch.object(conversation_run, "get_current_user_id", return_value=("test_user", "test_tenant"))


# Agent Runtime API Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), [("POST", "/agent/run"), ("GET", "/agent/stop/123")])
def test_conversation_endpoints_reject_invalid_authentication(mocker, method, path):
    mocker.patch.object(conversation_run, "get_current_user_id", side_effect=UnauthorizedError("invalid"))
    run = mocker.patch.object(conversation_run, "forward_conversation_run")
    stop = mocker.patch.object(conversation_run, "forward_scoped_stop")
    request = {"json": {"query": "hello"}} if method == "POST" else {}
    response = runtime_client.request(method, path, headers={"Authorization": "Bearer invalid"}, **request)
    assert response.status_code == 401
    run.assert_not_awaited()
    stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_run_api(mocker, mock_auth_header):
    """Test agent_run_api endpoint."""
    mock_run_agent_stream = mocker.patch(
        "management.api.agent.conversation_run.forward_conversation_run", new_callable=AsyncMock)

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

    content = response.content.decode()
    assert "data: chunk1" in content
    assert "data: chunk2" in content


@pytest.mark.parametrize(("expected_code", "message", "retry_after"), [
    ("RUNTIME_CAPACITY_FULL", "Agent runtime is at capacity.", "1"),
    ("RUNTIME_QUEUE_TIMEOUT", "Agent runtime queue wait timed out.", "3"),
])
def test_ut_be_tlm_027_agent_run_overload_is_json_before_sse(mocker, mock_auth_header, expected_code, message, retry_after):
    from contracts.errors.exceptions import RuntimeUpstreamError

    body = {"code": expected_code, "message": message, "retryable": True}
    mocker.patch.object(
        conversation_run, "forward_conversation_run",
        side_effect=RuntimeUpstreamError(
            429, json.dumps(body).encode(), {"Retry-After": retry_after, "Content-Type": "application/json"},
        ),
    )
    response = runtime_client.post("/agent/run", json={"agent_id": 1, "query": "test", "is_debug": True},
                                   headers=mock_auth_header)
    assert response.status_code == 429
    assert response.headers["retry-after"] == retry_after
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == body


@pytest.mark.parametrize(("error_code", "reason", "expected_status"), [
    (ErrorCode.CHAT_METADATA_TOO_LARGE, "METADATA_TOO_LARGE", 413),
    (ErrorCode.CHAT_METADATA_INVALID, "INVALID_METADATA_TYPE", 422),
])
def test_agent_run_preserves_runtime_metadata_app_exceptions(mocker, error_code, reason, expected_status):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(conversation_run.router)
    client = TestClient(app, raise_server_exceptions=False)
    mocker.patch.object(conversation_run, "forward_conversation_run",
                        side_effect=AppException(error_code, details={"reason": reason}))

    response = client.post("/agent/run", json={"agent_id": 1, "query": "test", "is_debug": True})

    assert response.status_code == expected_status
    assert response.json()["code"] == error_code.value
    assert response.json()["details"] == {"reason": reason}


@pytest.mark.asyncio
async def test_workbench_bootstrap_is_unavailable_when_disabled(mocker):
    mocker.patch("management.api.agent.agent.ENABLE_AGENT_WORKBENCH", False)

    with pytest.raises(HTTPException) as exc_info:
        await get_workbench_bootstrap_api(authorization="Bearer test-token")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == {"code": "WORKBENCH_DISABLED"}


@pytest.fixture(autouse=True)
def creator_history_boundary(mocker, monkeypatch):
    mocker.patch("permissions.resource_access.get_current_user_context", return_value=("test_user", "test_tenant", ("DEV",)))
    from contracts.agent import SystemAgentRef
    from management.services.conversation import creator_execution
    mocker.patch.object(creator_execution.system_agent_provider, "get_creator_ref", return_value=SystemAgentRef("shared", "nl2agent_main", 77, 0))
    mocker.patch.object(creator_execution, "authorize_target", side_effect=lambda target, *_: target)
    mocker.patch.object(creator_execution, "prepare_creation_history", return_value=(42, 1))
    from test.common.creator_runtime_boundary import isolate_creator_runtime
    return isolate_creator_runtime(monkeypatch, creator_execution)


@pytest.mark.asyncio
async def test_nl2agent_run_api_streams_for_existing_draft(
    mocker, mock_auth_header
):
    mocker.patch(
        "management.api.agent.creator.get_current_user_info",
        return_value=("user-a", "tenant-a", "en"),
    )

    async def mock_stream():
        yield 'data: {"type":"final_answer","content":"done"}\n\n'

    from contracts.agentos import AgentVersionReference

    prepared = Mock()
    compile_run = mocker.patch("management.api.agent.creator.prepare_nl2agent_snapshot", return_value=prepared)
    create_stream = mocker.patch("management.api.agent.creator.create_nl2agent_stream", return_value=mock_stream())

    response = await nl2agent_run_api(
        nl2agent_request=NL2AgentRunRequest(
            query="Build a weather agent",
            history=[],
            minio_files=[],
            agent_id=42,
        ),
        http_request=MagicMock(),
        authorization=mock_auth_header["Authorization"],
        resume=False,
    )

    chunks = [chunk async for chunk in response.body_iterator]

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    assert "final_answer" in "".join(chunks)
    request, actor, language = compile_run.call_args.args
    assert request.query == "Build a weather agent"
    assert request.agent_id == 42
    prepared.model_copy.assert_called_once_with(update={"system_agent": AgentVersionReference(agent_id=77, version_no=0)})
    create_stream.assert_called_once_with(prepared.model_copy.return_value, ServicePrincipal("user-a", "tenant-a"))
    assert request.conversation_id is None
    assert request.persist_history is True
    assert actor == ServicePrincipal("user-a", "tenant-a")
    assert language == "en"


@pytest.mark.asyncio
async def test_nl2agent_workbench_creation_returns_persistent_conversation_id(
    mocker, mock_auth_header, creator_history_boundary
):
    mocker.patch("management.api.agent.creator.ENABLE_AGENT_WORKBENCH", True)
    mocker.patch(
        "management.api.agent.creator.get_current_user_info",
        return_value=("user-a", "tenant-a", "en"),
    )
    async def mock_stream():
        yield 'data: {"type":"final_answer","content":"done"}\n\n'

    mocker.patch("management.api.agent.creator.prepare_nl2agent_snapshot", return_value=Mock())
    mocker.patch("management.api.agent.creator.create_nl2agent_stream", return_value=mock_stream())
    prepare = mocker.patch(
        "management.services.conversation.creator_execution.prepare_creation_history", return_value=(42, 1)
    )
    response = await nl2agent_run_api(
        nl2agent_request=NL2AgentRunRequest(
            query="Build a weather agent",
            agent_id=17,
            persist_history=True,
            workbench_config={
                "schema_version": 3, "mode": "agent_create",
                "generation_config": {"deep_thinking": False},
                "agent_mounts": [], "skill_mounts": [],
            },
        ),
        http_request=MagicMock(),
        authorization=mock_auth_header["Authorization"],
        resume=False,
    )
    assert response.headers["conversation_id"] == "42"
    assert prepare.call_args.kwargs["agent_id"] == 77
    assert prepare.call_args.kwargs["target"] == {"type": "agent", "id": 17}
    chunks = [chunk async for chunk in response.body_iterator]
    assert chunks
    assistant = creator_history_boundary.save.call_args.args[0]
    assert assistant.role == "assistant" and assistant.message_idx == 1
    assert creator_history_boundary.save.call_args.kwargs["status"] == "streaming"
    creator_history_boundary.checkpoint.assert_called_once()
    assert creator_history_boundary.checkpoint.call_args.kwargs == {
        "message_id": 101, "conversation_id": 42, "user_id": "user-a",
    }
    creator_history_boundary.launch.assert_awaited_once()


@pytest.mark.asyncio
async def test_northbound_run_uses_authenticated_context_and_preserves_metadata(mocker):
    context = AuthenticatedIdentity("user-a", "tenant-a")
    auth = mocker.patch.object(northbound, "_get_northbound_context", return_value=context)
    start = mocker.patch.object(northbound, "start_streaming_chat", return_value=StreamingResponse(iter(())))

    app = FastAPI()
    app.include_router(northbound.router)
    response = TestClient(app).post(
        "/nb/v1/chat/run",
        json={"agent_name": "test", "conversation_id": 123, "query": "hello", "metadata": {"project": "alpha"}},
        headers={"Authorization": "Bearer key"},
    )

    assert response.status_code == 200
    auth.assert_awaited_once()
    options = start.await_args.kwargs
    assert options["ctx"] is context and options["conversation_id"] == 123
    assert options["metadata"] == {"project": "alpha"}
    assert options["query"] == "hello" and options["final_answer_mode"] == "complete"


@pytest.mark.parametrize(("error", "expected_status", "detail"), [
    (PermissionError("forbidden"), 403, "forbidden"),
    (ValueError("invalid"), 400, "invalid"),
    (RuntimeError("unexpected sensitive failure"), 500, "Internal Server Error"),
    (AppException(ErrorCode.CHAT_METADATA_TOO_LARGE, details={"reason": "METADATA_TOO_LARGE"}), 413, None),
])
def test_northbound_run_maps_errors(mocker, error, expected_status, detail):
    mocker.patch.object(northbound, "_get_northbound_context", return_value=AuthenticatedIdentity("user-a", "tenant-a"))
    mocker.patch.object(northbound, "start_streaming_chat", side_effect=error)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(northbound.router)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/nb/v1/chat/run", json={"agent_name": "test", "query": "hello"},
    )

    assert response.status_code == expected_status
    if detail is None:
        assert response.json()["code"] == ErrorCode.CHAT_METADATA_TOO_LARGE.value
        assert response.json()["details"] == {"reason": "METADATA_TOO_LARGE"}
    else:
        assert response.json()["message"] == detail


@pytest.mark.parametrize(("method", "path"), [
    ("POST", "/nb/v1/chat/run"), ("GET", "/nb/v1/chat/stop/123"),
])
def test_northbound_run_and_stop_reject_unauthenticated_requests(mocker, method, path):
    mocker.patch.object(northbound, "_get_northbound_context", side_effect=HTTPException(401, "Invalid API key"))
    start = mocker.patch.object(northbound, "start_streaming_chat")
    stop = mocker.patch.object(northbound, "stop_chat")
    app = FastAPI()
    app.include_router(northbound.router)
    request = {"json": {"agent_name": "test", "query": "hello"}} if method == "POST" else {}
    response = TestClient(app).request(method, path, **request)

    assert response.status_code == 401
    start.assert_not_awaited()
    stop.assert_not_awaited()


def test_northbound_stop_uses_authenticated_context(mocker):
    actor = AuthenticatedIdentity("user-a", "tenant-a")
    mocker.patch.object(northbound, "_get_northbound_context", return_value=actor)
    stop = mocker.patch.object(northbound, "stop_chat", return_value={"message": "stopped"})
    app = FastAPI()
    app.include_router(northbound.router)
    response = TestClient(app).get("/nb/v1/chat/stop/123")

    assert response.json() == {"message": "stopped"}
    stop.assert_awaited_once_with(ctx=actor, conversation_id=123, meta_data=None)


def test_conversation_dispatch_preserves_identity_and_request_context(mocker, mock_auth_header):
    forward = mocker.patch.object(conversation_run, "forward_conversation_run", return_value=StreamingResponse(iter(())))
    response = runtime_client.post(
        "/agent/run", json={"query": "question", "agent_id": 7, "conversation_id": 42},
        headers={**mock_auth_header, "x-user-timezone": "Asia/Shanghai"}, cookies={"NEXT_LOCALE": "en"},
    )

    assert response.status_code == 200
    payload, owner, tenant = forward.await_args.args
    assert (owner, tenant) == ("test_user", "test_tenant")
    assert payload.request["conversation_id"] == 42
    assert payload.language == "en" and payload.timezone == "Asia/Shanghai"


@pytest.mark.asyncio
@pytest.mark.parametrize("run_found", [False, True])
async def test_cursorless_resume_uses_existing_projection_before_legacy_runtime(mocker, run_found):
    from contracts.agentos import AgentLegacyResume, CompatibilityConversationRun
    from management.services.agent import prepared_turn
    from management.services.agent import runtime_client as forwarder

    client = mocker.patch.object(forwarder, "_agentos_client").return_value
    client.resume_legacy = AsyncMock(return_value=object())
    existing = object() if run_found else None
    resume = mocker.patch.object(prepared_turn, "resume_cursorless", return_value=existing)
    payload = CompatibilityConversationRun(request={"query": "", "conversation_id": 42}, resume=True)
    result = await forwarder.forward_conversation_run(payload, "actor", "tenant")

    resume.assert_awaited_once_with(42, "actor", "tenant", client)
    if run_found:
        assert result is existing
        client.resume_legacy.assert_not_awaited()
    else:
        assert result is client.resume_legacy.return_value
        client.resume_legacy.assert_awaited_once_with(AgentLegacyResume(conversation_id=42), "actor", "tenant")


@pytest.mark.asyncio
@pytest.mark.parametrize("conversation_id,is_debug", [(None, False), (0, False), (-1, False), (42, True)])
async def test_invalid_resume_never_reaches_runtime(mocker, conversation_id, is_debug):
    from contracts.agentos import CompatibilityConversationRun
    from management.services.agent import runtime_client as forwarder

    client = mocker.patch.object(forwarder, "_agentos_client")
    payload = CompatibilityConversationRun(
        request={"query": "", "conversation_id": conversation_id, "is_debug": is_debug}, resume=True,
    )
    with pytest.raises(HTTPException) as error:
        await forwarder.forward_conversation_run(payload, "actor", "tenant")

    assert (error.value.status_code, error.value.detail) == (422, {"code": "AGENTOS_INVALID_RESUME_REQUEST"})
    client.assert_not_called()


@pytest.mark.asyncio
async def test_background_dispatch_checks_owner_before_opening_runtime(mocker):
    from contracts.agentos import BackgroundRun
    from management.services.agent import background
    from management.services.agent import runtime_client as forwarder

    owner = mocker.patch.object(background, "conversation_belongs_to", return_value=False)
    client = mocker.patch.object(forwarder, "_agentos_client")
    actor = ServicePrincipal("user-a", "tenant-a")
    payload = BackgroundRun(run_id="a" * 32, request={"query": "hello", "agent_id": 1, "conversation_id": 123})

    with pytest.raises(HTTPException) as error:
        await background.dispatch_background(payload, actor)

    assert error.value.status_code == 404
    owner.assert_called_once_with(123, user_id="user-a", tenant_id="tenant-a")
    client.assert_not_called()


@pytest.mark.asyncio
async def test_nl2agent_run_api_streams_without_persistent_ids(
    mocker, mock_auth_header
):
    mocker.patch(
        "management.api.agent.creator.get_current_user_info",
        return_value=("user-a", "tenant-a", "en"),
    )

    async def mock_stream():
        yield 'data: {"type":"final_answer","content":"done"}\n\n'

    prepared = object()
    compile_run = mocker.patch("management.api.agent.creator.prepare_nl2agent_snapshot", return_value=prepared)
    create_stream = mocker.patch("management.api.agent.creator.create_nl2agent_stream", return_value=mock_stream())

    response = await nl2agent_run_api(
        nl2agent_request=NL2AgentRunRequest(
            query="Build a weather agent",
            history=[],
            minio_files=[],
            agent_id=42,
            persist_history=False,
        ),
        http_request=MagicMock(),
        authorization=mock_auth_header["Authorization"],
        resume=False,
    )

    chunks = [chunk async for chunk in response.body_iterator]

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    assert "final_answer" in "".join(chunks)
    request, actor, language = compile_run.call_args.args
    assert request.query == "Build a weather agent"
    assert request.agent_id == 42
    create_stream.assert_called_once_with(prepared, ServicePrincipal("user-a", "tenant-a"))
    assert request.conversation_id is None
    assert request.persist_history is False
    assert "conversation_id" not in response.headers
    assert actor == ServicePrincipal("user-a", "tenant-a")
    assert language == "en"


@pytest.mark.asyncio
async def test_nl2agent_run_api_maps_authentication_failure_to_401(mocker):
    mocker.patch(
        "management.api.agent.creator.get_current_user_info",
        side_effect=UnauthorizedError("Invalid access token"),
    )
    create_stream = mocker.patch("management.api.agent.creator.create_nl2agent_stream")

    with pytest.raises(HTTPException) as exc_info:
        await nl2agent_run_api(
            nl2agent_request=NL2AgentRunRequest(
                query="Build an assistant",
                agent_id=42,
            ),
            http_request=MagicMock(),
            authorization="Bearer invalid-token",
            resume=False,
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid access token"
    create_stream.assert_not_called()


@pytest.mark.asyncio
async def test_nl2agent_run_api_hides_internal_startup_errors(mocker):
    mocker.patch(
        "management.api.agent.creator.get_current_user_info",
        return_value=("user-a", "tenant-a", "en"),
    )
    mocker.patch(
        "management.api.agent.creator.prepare_nl2agent_snapshot",
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
            resume=False,
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
        "management.api.agent.creator.get_current_user_info",
        return_value=("user-a", "tenant-a", "en"),
    )
    mocker.patch(
        "management.api.agent.creator.prepare_nl2agent_snapshot",
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
            resume=False,
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail["code"] == expected_code


@pytest.mark.asyncio
async def test_nl2agent_run_api_requires_target_for_new_conversation(mocker):
    mocker.patch("management.api.agent.creator.get_current_user_info", return_value=("user", "tenant", "en"))
    mocker.patch("management.services.conversation.creator_execution.system_agent_provider.get_creator_ref")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=config_creator_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/agent/nl2agent/run",
            json={"query": "Build an assistant"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Workbench creation session."


@pytest.mark.parametrize("is_debug", [True, False])
def test_agent_run_unexpected_errors_omit_exception_details(mocker, mock_auth_header, is_debug):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(conversation_run.router)
    client = TestClient(app, raise_server_exceptions=False)
    mocker.patch.object(conversation_run, "forward_conversation_run", side_effect=RuntimeError("private fixture error"))

    response = client.post(
        "/agent/run", json={"agent_id": 1, "query": "test", "is_debug": is_debug}, headers=mock_auth_header,
    )

    assert response.status_code == 500
    assert "private fixture error" not in response.text


@pytest.mark.parametrize(("error", "status"), [
    (ForbiddenError("Conversation is not accessible"), 403),
    (ValidationError("Selected knowledge bases are incompatible"), 422),
])
def test_agent_run_maps_scope_errors(mocker, mock_auth_header, error, status):
    mocker.patch.object(conversation_run, "forward_conversation_run", side_effect=error)
    response = runtime_client.post(
        "/agent/run", json={"agent_id": 1, "conversation_id": 123, "query": "test query"}, headers=mock_auth_header,
    )
    assert response.status_code == status
    assert response.json()["detail"] == str(error)


@pytest.mark.parametrize("cancelled", [True, False])
def test_agent_stop_looks_up_and_stops_only_the_scoped_run(mocker, mock_auth_header, cancelled):
    from contracts.agentos import AgentRunState, AgentStop
    from management.services.conversation import creator_runtime

    run_id = "a" * 32
    mocker.patch.object(creator_runtime, "stop_creator", return_value=None)
    active = mocker.patch.object(conversation_run, "forward_active_run", return_value=run_id)
    stop = mocker.patch.object(conversation_run, "forward_scoped_stop", return_value=AgentRunState(
        run_id=run_id, conversation_id=123, status="running" if cancelled else "completed",
        latest_event_id=None, cancellation_requested=cancelled,
    ))
    response = runtime_client.get("/agent/stop/123", headers=mock_auth_header)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["cancellation_requested"] is cancelled
    active.assert_awaited_once_with(123, "test_user", "test_tenant")
    stop.assert_awaited_once_with(AgentStop(run_id=run_id, conversation_id=123), "test_user", "test_tenant")


def test_agent_stop_hides_runtime_transport_error(mocker, mock_auth_header):
    from contracts.errors.exceptions import RuntimeServiceUnavailableError

    mocker.patch.object(conversation_run, "forward_scoped_stop", side_effect=RuntimeServiceUnavailableError("internal address"))
    response = runtime_client.get("/agent/stop/" + "a" * 32, headers=mock_auth_header)

    assert response.status_code == 503
    assert "internal address" not in response.text


# Agent Configuration API Tests
# ---------------------------------------------------------------------------


def test_search_agent_info_api_success(mocker, mock_auth_header):
    """Test search_agent_info_api success case without tenant_id query parameter."""
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "management.api.agent.agent.get_agent_info_impl", new_callable=AsyncMock)
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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "management.api.agent.agent.get_agent_info_impl", new_callable=AsyncMock)
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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "management.api.agent.agent.get_agent_info_impl", new_callable=AsyncMock)
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


def test_search_agent_info_api_maps_system_agent_forbidden_without_disclosure(
    mocker,
    mock_auth_header,
):
    """UT-BE-SAL-010: ordinary detail returns a non-disclosing 403 response."""
    mocker.patch(
        "management.api.agent.agent.get_current_user_id",
        return_value=("user_id", "auth_tenant_id"),
    )
    mock_get_agent_info = mocker.patch(
        "management.api.agent.agent.get_agent_info_impl",
        new_callable=AsyncMock,
    )
    mock_get_agent_info.side_effect = ForbiddenError("Agent is not accessible")

    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 7},
        headers=mock_auth_header,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Agent is not accessible"}
    assert "workbench_main" not in response.text
    assert "auth_tenant_id" not in response.text


def test_search_agent_info_api_exception_with_explicit_tenant_id(mocker, mock_auth_header):
    """Test search_agent_info_api exception handling with explicit tenant_id query parameter and default version_no=0."""
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "management.api.agent.agent.get_agent_info_impl", new_callable=AsyncMock)
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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "management.api.agent.agent.get_agent_info_impl", new_callable=AsyncMock)
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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "management.api.agent.agent.get_agent_info_impl", new_callable=AsyncMock)
    mock_get_user_id.return_value = ("user_id", "regular_tenant")
    mock_get_agent_info.return_value = {
        "agent_id": 1,
        "tenant_id": ASSET_OWNER_TENANT_ID,
        "prompt": "Responsibilities and secret constraints/examples",
    }

    response = config_client.post(
        "/agent/search_info",
        json={"agent_id": 1},
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["prompt"] is None
    assert "constraint_prompt" not in body
    assert "few_shots_prompt" not in body
    assert body[AGENT_PROMPTS_HIDDEN_FLAG] is True


# get_agent_by_name_api Tests
# ---------------------------------------------------------------------------


def test_get_agent_by_name_api_success(mocker, mock_auth_header):
    """Test get_agent_by_name_api success case."""
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_agent_by_name = mocker.patch(
        "management.api.agent.agent.get_agent_by_name_impl")
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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_agent_by_name = mocker.patch(
        "management.api.agent.agent.get_agent_by_name_impl")
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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mocker.patch(
        "management.api.agent.agent.get_agent_by_name_impl",
        side_effect=RuntimeError("database unavailable"),
    )
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")

    response = config_client.get(
        "/agent/by-name/NonExistentAgent",
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Agent by name lookup error."}


# Legacy creating-sub-agent endpoint removal
# ---------------------------------------------------------------------------


def test_legacy_creating_sub_agent_endpoint_is_not_exposed():
    """Agent creation must use POST /agent/update instead of draft allocation."""
    response = config_client.get("/agent/get_creating_sub_agent_id")

    assert response.status_code == 404


# update_agent_info_api Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Updated Agent", "agent-one", "class", "9agent", ""])
def test_update_agent_info_api_rejects_invalid_callable_names(mocker, mock_auth_header, name):
    """Reject invalid internal identifiers before invoking the update service."""
    update_agent = mocker.patch(
        "management.api.agent.agent.update_agent_info_impl", new_callable=AsyncMock)

    response = config_client.post(
        "/agent/update",
        json={"agent_id": 123, "name": name},
        headers=mock_auth_header,
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "name"]
    update_agent.assert_not_called()


def test_update_agent_info_api_success(mocker, mock_auth_header):
    """Test update_agent_info_api success case."""
    mock_update_agent = mocker.patch(
        "management.api.agent.agent.update_agent_info_impl", new_callable=AsyncMock)
    mock_update_agent.return_value = None

    response = config_client.post(
        "/agent/update",
        json={"agent_id": 123, "name": "updated_agent",
              "display_name": "Updated Display Name"},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_update_agent.assert_called_once()
    request = mock_update_agent.call_args.args[0]
    assert request.name == "updated_agent"
    assert request.display_name == "Updated Display Name"
    assert response.json() == {}


def test_update_agent_info_api_with_result(mocker, mock_auth_header):
    """Test update_agent_info_api returns result when provided."""
    mock_update_agent = mocker.patch(
        "management.api.agent.agent.update_agent_info_impl", new_callable=AsyncMock)
    mock_update_agent.return_value = {"updated": True, "agent_id": 123}

    response = config_client.post(
        "/agent/update",
        json={"agent_id": 123, "name": "updated_agent"},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    assert response.json()["updated"] is True


def test_update_agent_info_api_rejects_invalid_model_parameters(mocker, mock_auth_header):
    from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError

    mocker.patch("management.api.agent.agent.update_agent_info_impl", new_callable=AsyncMock,
                 side_effect=ParameterValidationError("PARAMETER_VALUE_INVALID", "/temperature"))
    response = config_client.post("/agent/update", json={"agent_id": 1}, headers=mock_auth_header)
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "PARAMETER_VALUE_INVALID", "field": "/temperature"}


def test_update_agent_info_api_exception(mocker, mock_auth_header):
    """Test update_agent_info_api exception handling."""
    mock_update_agent = mocker.patch(
        "management.api.agent.agent.update_agent_info_impl", new_callable=AsyncMock)
    mock_update_agent.side_effect = Exception("Test error")

    response = config_client.post(
        "/agent/update",
        json={"agent_id": 123, "name": "updated_agent"},
        headers=mock_auth_header
    )

    assert response.status_code == 500
    assert "Agent update error" in response.json()["detail"]


def test_update_agent_info_api_returns_agent_quota_error(mocker, mock_auth_header):
    """Agent quota failures must preserve the standard 429 error contract."""
    limit_error = TenantResourceLimitError(
        "Tenant agent limit reached: maximum 1000 agents per tenant",
        resource="agents",
        scope="tenant",
        limit=1000,
        current_count=1000,
    )
    mock_update_agent = mocker.patch(
        "management.api.agent.agent.update_agent_info_impl", new_callable=AsyncMock,
        side_effect=limit_error,
    )

    response = config_client.post(
        "/agent/update",
        json={"display_name": "New Agent"},
        headers=mock_auth_header,
    )

    assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert response.json() == tenant_resource_limit_error_payload(limit_error)
    mock_update_agent.assert_called_once()


# delete_agent_api Tests
# ---------------------------------------------------------------------------


def test_delete_agent_api_success(mocker, mock_auth_header):
    """Test delete_agent_api success case without tenant_id query parameter."""
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_delete_agent = mocker.patch(
        "management.api.agent.agent.delete_agent_impl", new_callable=AsyncMock)
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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_delete_agent = mocker.patch(
        "management.api.agent.agent.delete_agent_impl", new_callable=AsyncMock)
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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_delete_agent = mocker.patch(
        "management.api.agent.agent.delete_agent_impl", new_callable=AsyncMock)
    mock_logger = mocker.patch("management.api.agent.agent.logger")
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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_delete_agent = mocker.patch(
        "management.api.agent.agent.delete_agent_impl", new_callable=AsyncMock)
    mock_logger = mocker.patch("management.api.agent.agent.logger")
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
        "management.api.agent.agent.export_agent_with_skills_impl", new_callable=AsyncMock)
    mock_export_agent.return_value = {"agent_id": 123, "name": "Test Agent"}

    response = config_client.post(
        "/agent/export",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_export_agent.assert_called_once_with(
        123, AuthenticatedIdentity("test_user", "test_tenant"))
    assert response.json()["code"] == 0
    assert response.json()["message"] == "success"


def test_export_agent_api_success_with_zip(mocker, mock_auth_header):
    """Test export_agent_api success case returning ZIP file."""
    mock_export_agent = mocker.patch(
        "management.api.agent.agent.export_agent_with_skills_impl", new_callable=AsyncMock)
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
    assert "attachment; filename*=UTF-8''agent_export.zip" in response.headers["content-disposition"]
    assert response.content == b"PK\x03\x04test zip content"


def test_export_agent_api_success_with_zip_default_filename(mocker, mock_auth_header):
    """Test export_agent_api ZIP response with default filename."""
    mock_export_agent = mocker.patch(
        "management.api.agent.agent.export_agent_with_skills_impl", new_callable=AsyncMock)
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
    assert "attachment; filename*=UTF-8''agent_export.zip" in response.headers["content-disposition"]


def test_export_agent_api_success_with_zip_non_ascii_filename(mocker, mock_auth_header):
    """Test export_agent_api ZIP response with a non-ASCII agent display name."""
    from urllib.parse import quote

    mock_export_agent = mocker.patch(
        "management.api.agent.agent.export_agent_with_skills_impl", new_callable=AsyncMock)
    mock_export_agent.return_value = {
        "_zip": True,
        "data": b"PK\x03\x04zip content",
        "filename": "\u667a\u80fd\u4f53\u5bfc\u51fa.zip"
    }

    response = config_client.post(
        "/agent/export",
        json={"agent_id": 789},
        headers=mock_auth_header
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    expected = "attachment; filename*=UTF-8''" + quote("\u667a\u80fd\u4f53\u5bfc\u51fa.zip")
    assert response.headers["content-disposition"] == expected


def test_export_agent_api_exception(mocker, mock_auth_header):
    """Test export_agent_api exception handling."""
    mock_export_agent = mocker.patch(
        "management.api.agent.agent.export_agent_with_skills_impl", new_callable=AsyncMock)
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
    mock_check = mocker.patch("management.api.agent.agent.check_skill_conflicts_impl")
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
        AuthenticatedIdentity("test_user", "test_tenant"),
    )


def test_check_skills_api_error(mocker, mock_auth_header):
    """Skill conflict precheck maps unexpected failures to a server error."""
    mocker.patch(
        "management.api.agent.agent.check_skill_conflicts_impl",
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
        "management.api.agent.agent.import_agent_impl", new_callable=AsyncMock)
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


def test_import_agent_api_returns_agent_quota_error(mocker, mock_auth_header):
    """Agent import quota failures must preserve the standard 429 error contract."""
    limit_error = TenantResourceLimitError(
        "Tenant agent limit reached: maximum 1000 agents per tenant",
        resource="agents",
        scope="tenant",
        limit=1000,
        current_count=1000,
    )
    mock_import_agent = mocker.patch(
        "management.api.agent.agent.import_agent_impl",
        new_callable=AsyncMock,
        side_effect=limit_error,
    )

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
                        "managed_agents": [],
                    }
                },
                "mcp_info": [],
            }
        },
        headers=mock_auth_header,
    )

    assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert response.json() == tenant_resource_limit_error_payload(limit_error)
    mock_import_agent.assert_called_once()


def test_import_agent_api_success_with_skills(mocker, mock_auth_header):
    """Test import_agent_api success case with skills."""
    mock_import_with_skills = mocker.patch(
        "management.api.agent.agent.import_agent_with_skills_impl", new_callable=AsyncMock)
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
    from contracts.errors.exceptions import SkillDuplicateError
    mock_import_agent = mocker.patch(
        "management.api.agent.agent.import_agent_impl", new_callable=AsyncMock)
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
        "management.api.agent.agent.import_agent_impl", new_callable=AsyncMock)
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


def test_list_agent_page_api_forwards_filters_and_returns_paged_agents(
    mocker, mock_auth_header
):
    """The paged list endpoint delegates filters after resolving the caller."""
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_list_agent_page = mocker.patch(
        "management.api.agent.agent.list_agent_page_impl", new_callable=AsyncMock, create=True
    )
    mock_get_user_info.return_value = ("test_user", "auth_tenant", "en")
    mock_list_agent_page.return_value = {
        "items": [
            {
                "agent_id": 7,
                "name": "Support Agent",
                "permission": "EDIT",
                "created_by": "test_user",
                "create_time": "2026-09-22T08:00:00+00:00",
                "tags": ["support"],
            }
        ],
        "pagination": {"page": 2, "page_size": 5, "total": 6, "total_pages": 2},
    }

    response = config_client.get(
        "/agent/list/page",
        params={
            "tenant_id": "tenant_123",
            "permission": "EDIT",
            "tag": "support",
            "search": "support",
            "page": 2,
            "page_size": 5,
            "include_repository_info": "true",
        },
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    assert response.json() == mock_list_agent_page.return_value
    mock_list_agent_page.assert_awaited_once_with(
        tenant_id="tenant_123",
        user_id="test_user",
        caller_tenant_id="auth_tenant",
        permission="EDIT",
        tag="support",
        search="support",
        page=2,
        page_size=5,
        sort_by_update_time=False,
        include_repository_info=True,
    )


def test_list_agent_page_api_forwards_publish_time_sort(mocker, mock_auth_header):
    """The latest-published-first selector is forwarded to the service."""
    mocker.patch(
        "management.api.agent.agent.get_current_user_info",
        return_value=("test_user", "auth_tenant", "en"),
    )
    mock_list = mocker.patch(
        "management.api.agent.agent.list_agent_page_impl", new_callable=AsyncMock
    )
    mock_list.return_value = {
        "items": [],
        "pagination": {"page": 1, "page_size": 5, "total": 0, "total_pages": 0},
    }

    response = config_client.get(
        "/agent/list/page",
        params={"sort_by_update_time": "true"},
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    assert mock_list.await_args.kwargs["sort_by_update_time"] is True


def test_list_agent_page_api_forwards_creator_and_structured_tag_filters(
    mocker, mock_auth_header
):
    mocker.patch(
        "management.api.agent.agent.get_current_user_info",
        return_value=("test_user", "auth_tenant", "en"),
    )
    mock_list = mocker.patch(
        "management.api.agent.agent.list_agent_page_impl", new_callable=AsyncMock
    )
    mock_list.return_value = {"items": [], "pagination": {"total": 0}}

    response = config_client.get(
        "/agent/list/page",
        params={
            "tenant_id": "auth_tenant",
            "created_by_not": "test_user",
            "tag_predicates": '[{"definition_id":1,"value_ids":[2]}]',
            "page": 1,
            "page_size": 8,
        },
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    kwargs = mock_list.await_args.kwargs
    assert kwargs["created_by_not"] == "test_user"
    assert kwargs["tag_predicates"][0].definition_id == 1
    assert kwargs["page_size"] == 8


def test_list_agent_page_api_forwards_creator_and_asset_owner_tenant(
    mocker, mock_auth_header
):
    mocker.patch(
        "management.api.agent.agent.get_current_user_info",
        return_value=("test_user", "auth_tenant", "en"),
    )
    mocker.patch("management.api.agent.agent.ASSET_OWNER_TENANT_ID", "asset_owner")
    mock_list = mocker.patch(
        "management.api.agent.agent.list_agent_page_impl", new_callable=AsyncMock
    )
    mock_list.return_value = {"items": [], "pagination": {"total": 0}}

    response = config_client.get(
        "/agent/list/page",
        params={"created_by": "author-7"},
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    kwargs = mock_list.await_args.kwargs
    assert kwargs["tenant_id"] == "auth_tenant"
    assert kwargs["caller_tenant_id"] == "auth_tenant"
    assert kwargs["created_by"] == "author-7"
    assert kwargs["additional_tenant_id"] == "asset_owner"


def test_list_agent_page_api_rejects_invalid_tag_predicates(mocker, mock_auth_header):
    mocker.patch(
        "management.api.agent.agent.get_current_user_info",
        return_value=("test_user", "auth_tenant", "en"),
    )
    mock_list = mocker.patch(
        "management.api.agent.agent.list_agent_page_impl", new_callable=AsyncMock
    )

    response = config_client.get(
        "/agent/list/page",
        params={"tag_predicates": "{}"},
        headers=mock_auth_header,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "tag_predicates must be a list"
    mock_list.assert_not_awaited()


def test_list_agent_page_api_hides_unexpected_error(mocker, mock_auth_header):
    mocker.patch(
        "management.api.agent.agent.get_current_user_info",
        return_value=("test_user", "auth_tenant", "en"),
    )
    mock_list = mocker.patch(
        "management.api.agent.agent.list_agent_page_impl",
        new_callable=AsyncMock,
        side_effect=RuntimeError("lookup failed"),
    )
    log_error = mocker.patch("management.api.agent.agent.logger.error")

    response = config_client.get("/agent/list/page", headers=mock_auth_header)

    assert response.status_code == 500
    assert response.json()["detail"] == "Paged agent list error."
    mock_list.assert_awaited_once()
    log_error.assert_called_once_with("Paged agent list error: lookup failed")


def test_list_all_agent_info_api_success(mocker, mock_auth_header):
    """Test list_all_agent_info_api success case without tenant_id."""
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "management.api.agent.agent.list_all_agent_info_impl", new_callable=AsyncMock)
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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "management.api.agent.agent.list_all_agent_info_impl", new_callable=AsyncMock)
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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "management.api.agent.agent.list_all_agent_info_impl", new_callable=AsyncMock)
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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "management.api.agent.agent.list_all_agent_info_impl", new_callable=AsyncMock)
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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "management.api.agent.agent.list_all_agent_info_impl", new_callable=AsyncMock)
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
        "management.api.agent.agent.export_agent_with_skills_impl", new_callable=AsyncMock)

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
        456, AuthenticatedIdentity("test_user", "test_tenant"))

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
        "management.api.agent.agent.export_agent_with_skills_impl", new_callable=AsyncMock)

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
        789, AuthenticatedIdentity("test_user", "test_tenant"))

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
        from management.services.agent import service as b_agent_service
        # Map both the package and submodule for compatibility
        sys.modules['services'] = b_services
        sys.modules['management.services.agent.service'] = b_agent_service
    except Exception:
        # If the project already supports direct imports, ignore the failure
        pass


def test_get_agent_call_relationship_api_success(mocker, mock_auth_header):
    """Test get_agent_call_relationship_api success case."""
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_impl = mocker.patch("management.api.agent.agent.get_agent_call_relationship_impl")
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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_impl = mocker.patch("management.api.agent.agent.get_agent_call_relationship_impl")
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
        "management.api.agent.agent.check_agent_name_conflict_batch_impl",
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
        "management.api.agent.agent.check_agent_name_conflict_batch_impl",
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
        "management.api.agent.agent.check_agent_name_conflict_batch_impl",
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
        "management.api.agent.agent.regenerate_agent_name_batch_impl",
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
        "management.api.agent.agent.regenerate_agent_name_batch_impl",
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
        "management.api.agent.agent.regenerate_agent_name_batch_impl",
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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_clear_agent_new_mark = mocker.patch(
        "management.api.agent.agent.clear_agent_new_mark_impl", new_callable=AsyncMock)

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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_clear_agent_new_mark = mocker.patch(
        "management.api.agent.agent.clear_agent_new_mark_impl", new_callable=AsyncMock)
    mock_logger = mocker.patch("management.api.agent.agent.logger")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_publish_version = mocker.patch("management.api.agent.agent.publish_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_publish_version = mocker.patch("management.api.agent.agent.publish_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_publish_version = mocker.patch("management.api.agent.agent.publish_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_publish_version = mocker.patch("management.api.agent.agent.publish_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_compare_versions = mocker.patch(
        "management.api.agent.agent.compare_versions_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_compare_versions = mocker.patch(
        "management.api.agent.agent.compare_versions_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_compare_versions = mocker.patch(
        "management.api.agent.agent.compare_versions_impl")

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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_get_version_list = mocker.patch(
        "management.api.agent.agent.get_version_list_impl")

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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_get_version_list = mocker.patch(
        "management.api.agent.agent.get_version_list_impl")

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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_get_version_list = mocker.patch(
        "management.api.agent.agent.get_version_list_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_version = mocker.patch("management.api.agent.agent.get_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_version = mocker.patch("management.api.agent.agent.get_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_version = mocker.patch("management.api.agent.agent.get_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_version_detail = mocker.patch(
        "management.api.agent.agent._get_version_detail_or_draft")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_version_detail = mocker.patch(
        "management.api.agent.agent._get_version_detail_or_draft")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_version_detail = mocker.patch(
        "management.api.agent.agent._get_version_detail_or_draft")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_version_detail = mocker.patch(
        "management.api.agent.agent._get_version_detail_or_draft")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_rollback_version = mocker.patch(
        "management.api.agent.agent.rollback_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_rollback_version = mocker.patch(
        "management.api.agent.agent.rollback_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_rollback_version = mocker.patch(
        "management.api.agent.agent.rollback_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_update_version_status = mocker.patch(
        "management.api.agent.agent.update_version_status_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_update_version_status = mocker.patch(
        "management.api.agent.agent.update_version_status_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_update_version_status = mocker.patch(
        "management.api.agent.agent.update_version_status_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_update_version = mocker.patch("management.api.agent.agent.update_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_update_version = mocker.patch("management.api.agent.agent.update_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_update_version = mocker.patch("management.api.agent.agent.update_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_delete_version = mocker.patch("management.api.agent.agent.delete_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_delete_version = mocker.patch("management.api.agent.agent.delete_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_delete_version = mocker.patch("management.api.agent.agent.delete_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_current_version = mocker.patch(
        "management.api.agent.agent.get_current_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_current_version = mocker.patch(
        "management.api.agent.agent.get_current_version_impl")

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_get_current_version = mocker.patch(
        "management.api.agent.agent.get_current_version_impl")

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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_list_published_agents = mocker.patch(
        "management.api.agent.agent.list_published_agents_impl", new_callable=AsyncMock)

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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_list_published_agents = mocker.patch(
        "management.api.agent.agent.list_published_agents_impl", new_callable=AsyncMock)
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
    mock_get_user_info = mocker.patch("management.api.agent.agent.get_current_user_info")
    mock_list_published_agents = mocker.patch(
        "management.api.agent.agent.list_published_agents_impl", new_callable=AsyncMock)

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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_caps = mocker.patch(
        "management.api.agent.agent.get_agent_knowledge_capabilities")
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
    mock_get_user_id = mocker.patch("management.api.agent.agent.get_current_user_id")
    mock_caps = mocker.patch(
        "management.api.agent.agent.get_agent_knowledge_capabilities")
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
    mocker.patch("management.api.agent.agent.get_current_user_id",
                 return_value=("user-1", "tenant-1"))
    mocker.patch(
        "management.api.agent.agent.get_agent_knowledge_capabilities",
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
    mocker.patch("management.api.agent.agent.get_current_user_id", return_value=("user-1", "tenant-1"))
    mocker.patch("management.api.agent.agent.upload_agent_icon_impl", new_callable=AsyncMock, side_effect=error)

    response = config_client.post(
        "/agent/7/icon",
        files={"file": ("icon.png", b"png-content", "image/png")},
        headers=mock_auth_header,
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == detail


def test_upload_agent_icon_api_success(mocker, mock_auth_header):
    mocker.patch("management.api.agent.agent.get_current_user_id", return_value=("user-1", "tenant-1"))
    upload_impl = mocker.patch(
        "management.api.agent.agent.upload_agent_icon_impl",
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
    mocker.patch("management.api.agent.agent.get_current_user_id", return_value=("user-1", "tenant-1"))
    get_impl = mocker.patch(
        "management.api.agent.agent.get_agent_icon_impl",
        new_callable=AsyncMock,
        return_value=(b"image-bytes", "image/webp"),
    )

    response = config_client.get("/agent/7/icon?v=new-revision", headers=mock_auth_header)

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
    mocker.patch("management.api.agent.agent.get_current_user_id", return_value=("user-1", "tenant-1"))
    mocker.patch(
        "management.api.agent.agent.get_agent_icon_impl",
        new_callable=AsyncMock,
        side_effect=FileNotFoundError("Agent icon not found"),
    )

    response = config_client.get("/agent/7/icon", headers=mock_auth_header)

    assert response.status_code == 404
    assert response.json()["detail"] == "Agent icon not found"


def test_get_agent_icon_api_internal_error(mocker, mock_auth_header):
    mocker.patch("management.api.agent.agent.get_current_user_id", return_value=("user-1", "tenant-1"))
    mocker.patch(
        "management.api.agent.agent.get_agent_icon_impl",
        new_callable=AsyncMock,
        side_effect=RuntimeError("storage unavailable"),
    )

    response = config_client.get("/agent/7/icon", headers=mock_auth_header)

    assert response.status_code == 500
    assert response.json()["detail"] == "Agent icon retrieval error."


# ---------------------------------------------------------------------------
# Security audit entries
# ---------------------------------------------------------------------------


def test_update_agent_info_api_emits_audit_entry(mocker, mock_auth_header, caplog):
    """Successful agent update records an identifier-only audit line."""
    import logging

    mocker.patch("management.api.agent.agent.update_agent_info_impl", new_callable=AsyncMock,
                 return_value={"updated": True})
    mocker.patch(
        "management.api.agent.agent.get_current_user_id",
        return_value=("test_user", "test_tenant"),
    )

    with caplog.at_level(logging.INFO, logger="audit.security"):
        response = config_client.post(
            "/agent/update",
            json={"agent_id": 123, "display_name": "Bot",
                  "prompt": "secret prompt text"},
            headers=mock_auth_header,
        )

    assert response.status_code == 200
    messages = [record.getMessage() for record in caplog.records
                if record.name == "audit.security"]
    assert len(messages) == 1
    assert "event=agent_update" in messages[0]
    assert "result=success" in messages[0]
    assert "user_id=test_user" in messages[0]
    assert '"agent_id":123' in messages[0]
    assert '"patch_keys":["agent_id","display_name","prompt"]' in messages[0]
    assert "secret prompt text" not in messages[0]


def test_upload_agent_icon_api_emits_audit_entry(mocker, mock_auth_header, caplog):
    """Successful icon upload records filename and size, never the bytes."""
    import logging

    mocker.patch(
        "management.api.agent.agent.upload_agent_icon_impl",
        new_callable=AsyncMock,
        return_value={"icon_url": "/agent/7/icon/x"},
    )
    mocker.patch(
        "management.api.agent.agent.get_current_user_id",
        return_value=("test_user", "test_tenant"),
    )

    with caplog.at_level(logging.INFO, logger="audit.security"):
        response = config_client.post(
            "/agent/7/icon",
            files={"file": ("avatar.png", b"binary-image", "image/png")},
            headers=mock_auth_header,
        )

    assert response.status_code == 200
    messages = [record.getMessage() for record in caplog.records
                if record.name == "audit.security"]
    assert len(messages) == 1
    assert "event=agent_icon_upload" in messages[0]
    assert '"agent_id":7' in messages[0]
    assert '"filename":"avatar.png"' in messages[0]
    assert '"size":12' in messages[0]
    assert "binary-image" not in messages[0]


def test_import_agent_api_emits_audit_entry_without_payload(mocker, mock_auth_header, caplog):
    """Successful import records identifiers and counts, not the agent payload."""
    import logging

    mocker.patch("management.api.agent.agent.import_agent_impl", new_callable=AsyncMock,
                 return_value={123: 456})
    mocker.patch(
        "management.api.agent.agent.get_current_user_id",
        return_value=("test_user", "test_tenant"),
    )

    with caplog.at_level(logging.INFO, logger="audit.security"):
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
                "force_import": True
            },
            headers=mock_auth_header,
        )

    assert response.status_code == 200
    messages = [record.getMessage() for record in caplog.records
                if record.name == "audit.security"]
    assert len(messages) == 1
    assert "event=agent_import" in messages[0]
    assert '"source_agent_id":123' in messages[0]
    assert '"force_import":true' in messages[0]
    assert '"skills_count":0' in messages[0]
    assert "ImportedAgent" not in messages[0]
    assert "Test description" not in messages[0]


def test_publish_version_api_emits_audit_entry(mocker, mock_auth_header, caplog):
    """Successful publish records agent_id and version name."""
    import logging

    mocker.patch("management.api.agent.agent.get_current_user_id",
                 return_value=("test_user", "test_tenant"))
    mocker.patch("management.api.agent.agent.publish_version_impl", return_value={"version_no": 1})

    with caplog.at_level(logging.INFO, logger="audit.security"):
        response = config_client.post(
            "/agent/123/publish",
            json={"version_name": "v1.0.0", "release_note": "Initial release"},
            headers=mock_auth_header,
        )

    assert response.status_code == 200
    messages = [record.getMessage() for record in caplog.records
                if record.name == "audit.security"]
    assert len(messages) == 1
    assert "event=agent_version_publish" in messages[0]
    assert '"agent_id":123' in messages[0]
    assert '"version_name":"v1.0.0"' in messages[0]
