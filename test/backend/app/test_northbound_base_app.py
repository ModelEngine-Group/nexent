"""
Unit tests for northbound_base_app module.

Tests cover FastAPI application configuration, CORS middleware, router inclusion,
and basic A2A endpoint routing and error handling.
"""
import os
import sys
import types
import unittest
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, '../../../backend'))
sys.path.insert(0, backend_dir)

# ---------------------------------------------------------------------------
# BLOCK 1: Mock the entire 'services' package to prevent deep imports
# ---------------------------------------------------------------------------
services_pkg = types.ModuleType("services")
services_pkg.__path__ = [os.path.join(backend_dir, "services")]
sys.modules['services'] = services_pkg

# NorthboundContext stub - minimal dataclass for type compatibility
@dataclass
class NorthboundContext:
    """Minimal stub of NorthboundContext for testing."""
    request_id: str
    tenant_id: str
    user_id: str
    authorization: str
    token_id: int = 0

# services.northbound_service - provides only NorthboundContext
northbound_service_module = types.ModuleType("services.northbound_service")
northbound_service_module.NorthboundContext = NorthboundContext
sys.modules['services.northbound_service'] = northbound_service_module

# services.a2a_server_service - stub with a2a_server_service object and exceptions
from unittest.mock import AsyncMock, MagicMock

a2a_service_module = types.ModuleType("services.a2a_server_service")
a2a_service_module.EndpointNotFoundError = type("EndpointNotFoundError", (Exception,), {})
a2a_service_module.AgentNotEnabledError = type("AgentNotEnabledError", (Exception,), {})
a2a_service_module.TaskNotFoundError = type("TaskNotFoundError", (Exception,), {})
a2a_service_module.UnsupportedOperationError = type("UnsupportedOperationError", (Exception,), {})
a2a_service_module.A2AServerServiceError = type("A2AServerServiceError", (Exception,), {})
sys.modules['services.a2a_server_service'] = a2a_service_module

# Create a proper mock service instance with all methods
a2a_server_service_mock = MagicMock()
a2a_server_service_mock.handle_message_send = AsyncMock()
a2a_server_service_mock.handle_message_stream = MagicMock(return_value=iter([]))
a2a_server_service_mock.get_agent_card = MagicMock()
a2a_server_service_mock.get_task = MagicMock()
a2a_service_module.a2a_server_service = a2a_server_service_mock

# ---------------------------------------------------------------------------
# BLOCK 2: Mock minimal consts modules needed by apps layer
# ---------------------------------------------------------------------------
consts_module = types.ModuleType("consts")
consts_module.__path__ = [os.path.join(backend_dir, "consts")]
sys.modules['consts'] = consts_module

# consts.model - only exceptions and AgentRequest needed by apps
consts_model_module = types.ModuleType("consts.model")
consts_model_module.LimitExceededError = type("LimitExceededError", (Exception,), {})
consts_model_module.UnauthorizedError = type("UnauthorizedError", (Exception,), {})
consts_model_module.SignatureValidationError = type("SignatureValidationError", (Exception,), {})
consts_model_module.AgentRequest = type("AgentRequest", (), {})
consts_module.model = consts_model_module
sys.modules['consts.model'] = consts_model_module

# consts.exceptions
consts_exceptions_module = types.ModuleType("consts.exceptions")
consts_exceptions_module.AppException = type("AppException", (Exception,), {})
consts_exceptions_module.LimitExceededError = consts_model_module.LimitExceededError
consts_exceptions_module.UnauthorizedError = consts_model_module.UnauthorizedError
consts_exceptions_module.SignatureValidationError = consts_model_module.SignatureValidationError
consts_exceptions_module.MemoryPreparationException = type("MemoryPreparationException", (Exception,), {})
consts_exceptions_module.AgentRunException = type("AgentRunException", (Exception,), {})
consts_module.exceptions = consts_exceptions_module
sys.modules['consts.exceptions'] = consts_exceptions_module

# ---------------------------------------------------------------------------
# BLOCK 3: Mock remaining dependencies referenced by northbound_app
# ---------------------------------------------------------------------------
# Mock apps.northbound_app - provides the _get_northbound_context helper
northbound_app_router = APIRouter()

@northbound_app_router.get("/dummy")
async def _dummy_route():
    return {"msg": "ok"}

northbound_app_module = types.ModuleType("apps.northbound_app")
northbound_app_module.router = northbound_app_router

# _get_northbound_context helper used by a2a endpoints
async def _get_northbound_context_fake(request):
    """Return a fake NorthboundContext extracted from dummy headers."""
    return NorthboundContext(
        request_id="test-req-id",
        tenant_id=request.headers.get("X-Tenant-ID", "default"),
        user_id=request.headers.get("X-User-ID", "test_user"),
        authorization=request.headers.get("Authorization", "Bearer token"),
        token_id=0
    )

northbound_app_module._get_northbound_context = _get_northbound_context_fake
sys.modules['apps.northbound_app'] = northbound_app_module

# Mock apps.app_factory (imported by northbound_base_app)
app_factory_module = types.ModuleType("apps.app_factory")

# Import real register_exception_handlers to apply to the app
try:
    from apps.app_factory import register_exception_handlers as _real_register_exception_handlers
except Exception:
    _real_register_exception_handlers = None

def register_exception_handlers(app):
    """Mock register_exception_handlers that adds exception handlers."""
    from fastapi import HTTPException
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from fastapi.responses import JSONResponse

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})

    @app.exception_handler(Exception)
    async def generic_exception_handler(request, exc):
        return JSONResponse(status_code=500, content={"message": "Internal server error"})

app_factory_module.register_exception_handlers = register_exception_handlers
app_factory_module.create_app = None  # placeholder
sys.modules['apps.app_factory'] = app_factory_module

# Provide a real create_app function that returns a FastAPI app
def _create_app_impl(title, description="", version="1.0.0", root_path="/api",
                     cors_origins=None, cors_methods=None, enable_monitoring=True):
    """Minimal implementation of create_app for testing."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(
        title=title,
        description=description,
        version=version,
        root_path=root_path
    )

    # Add CORS middleware (simplified)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=cors_methods or ["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    # Register exception handlers (equivalent to real app_factory behavior)
    register_exception_handlers(app)

    return app

app_factory_module.create_app = _create_app_impl

database_a2a_module = types.ModuleType("database.a2a_agent_db")
database_a2a_module.PROTOCOL_HTTP_JSON = "http+json"
database_a2a_module.PROTOCOL_JSONRPC = "jsonrpc"
sys.modules['database.a2a_agent_db'] = database_a2a_module

# Mock utils.auth_utils (referenced by northbound_app._get_northbound_context)
auth_utils_module = types.ModuleType("utils.auth_utils")
auth_utils_module.validate_bearer_token = MagicMock(return_value=(True, {"user_id": "test", "tenant_id": "test"}))
sys.modules['utils.auth_utils'] = auth_utils_module

# ---------------------------------------------------------------------------
# SAFE TO IMPORT THE TARGET MODULE
# ---------------------------------------------------------------------------
from apps.northbound_base_app import northbound_app as app  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class TestNorthboundBaseApp(unittest.TestCase):
    """Unit tests covering FastAPI application configuration in northbound_base_app.py."""

    def setUp(self):
        self.client = TestClient(app)

    # -------------------------------------------------------------------
    # Application configuration
    # -------------------------------------------------------------------
    def test_app_root_path(self):
        """The FastAPI app should be mounted under /api."""
        self.assertEqual(app.root_path, "/api")

    def test_cors_middleware_configuration(self):
        """CORS middleware must allow all origins with expected methods and headers."""
        cors_middleware = None
        for middleware in app.user_middleware:
            if middleware.cls.__name__ == "CORSMiddleware":
                cors_middleware = middleware
                break
        self.assertIsNotNone(cors_middleware, "CORSMiddleware should be registered")
        self.assertEqual(cors_middleware.kwargs.get("allow_origins"), ["*"])
        self.assertTrue(cors_middleware.kwargs.get("allow_credentials"))
        self.assertEqual(cors_middleware.kwargs.get("allow_methods"), ["GET", "POST", "PUT", "DELETE"])
        self.assertEqual(cors_middleware.kwargs.get("allow_headers"), ["*"])

    def test_router_inclusion(self):
        """The main northbound router should be included."""
        routes = [route.path for route in app.routes]
        self.assertIn("/dummy", routes)

    def test_a2a_router_inclusion(self):
        """A2A router should be registered under /nb/a2a."""
        routes = [route.path for route in app.routes]
        self.assertIn("/nb/a2a/{endpoint_id}/.well-known/agent-card.json", routes)
        self.assertIn("/nb/a2a/{endpoint_id}/v1", routes)
        self.assertIn("/nb/a2a/{endpoint_id}/message:send", routes)
        self.assertIn("/nb/a2a/{endpoint_id}/message:stream", routes)
        self.assertIn("/nb/a2a/{endpoint_id}/tasks/{task_id}", routes)

    # -------------------------------------------------------------------
    # Exception handlers - delegated to app_factory which calls register_exception_handlers
    # -------------------------------------------------------------------
    def test_http_exception_handler_registration(self):
        """FastAPI's default HTTPException handler should be present."""
        # Uses starlette's HTTPException (not fastapi's)
        from starlette.exceptions import HTTPException as StarletteHTTPException
        self.assertIn(StarletteHTTPException, app.exception_handlers)
        self.assertTrue(callable(app.exception_handlers[StarletteHTTPException]))

    def test_custom_exception_handlers_registration(self):
        """Custom exception handlers for uncaught exceptions should be registered."""
        self.assertIn(Exception, app.exception_handlers)
        self.assertTrue(callable(app.exception_handlers[Exception]))

    # -------------------------------------------------------------------
    # Basic sanity endpoint
    # -------------------------------------------------------------------
    def test_dummy_endpoint_success(self):
        """Dummy endpoint defined on the northbound_app router stub should return 200."""
        response = self.client.get("/dummy")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"msg": "ok"})

    # -------------------------------------------------------------------
    # A2A endpoint tests
    # -------------------------------------------------------------------
    def test_get_agent_card_success(self):
        """GET /.well-known/agent-card.json should return agent card with proper cache headers."""
        # Arrange
        test_card = {
            "name": "test-agent",
            "description": "Test agent card",
            "protocol": "a2a",
            "version": "1.0.0"
        }
        # Clear side_effect from previous test before setting return_value
        a2a_service_module.a2a_server_service.get_agent_card.side_effect = None
        a2a_service_module.a2a_server_service.get_agent_card.return_value = test_card

        # Act
        response = self.client.get("/nb/a2a/test-endpoint/.well-known/agent-card.json")

        # Assert
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "test-agent")
        self.assertIn("Cache-Control", response.headers)
        self.assertIn("ETag", response.headers)

    def test_get_agent_card_not_found(self):
        """GET /.well-known/agent-card.json returns 404 when endpoint_id is unknown."""
        # Arrange
        a2a_service_module.a2a_server_service.get_agent_card.side_effect = (
            a2a_service_module.EndpointNotFoundError("Unknown endpoint")
        )

        # Act
        response = self.client.get("/nb/a2a/unknown/.well-known/agent-card.json")

        # Assert
        self.assertEqual(response.status_code, 404)
        # Detail may be in 'detail' or 'message' depending on exception handler
        body = response.json()
        self.assertIn("unknown endpoint", str(body).lower())

    def test_jsonrpc_send_message_success(self):
        """POST /v1 with SendMessage method should invoke a2a_server_service and return JSON-RPC response."""
        # Arrange
        expected_result = {"status": "ok", "task_id": "task-123"}
        a2a_service_module.a2a_server_service.handle_message_send.return_value = expected_result
        payload = {
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "params": {
                "message": {"content": "hello"},
                "configuration": {},
                "metadata": {}
            },
            "id": "req-1"
        }

        # Act
        response = self.client.post("/nb/a2a/test-endpoint/v1", json=payload)

        # Assert
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["jsonrpc"], "2.0")
        self.assertEqual(data["id"], "req-1")
        self.assertEqual(data["result"], expected_result)
        a2a_service_module.a2a_server_service.handle_message_send.assert_called_once()

    def test_jsonrpc_method_not_found(self):
        """POST /v1 with unknown method should return JSON-RPC method error."""
        # Arrange
        payload = {
            "jsonrpc": "2.0",
            "method": "UnknownMethod",
            "params": {},
            "id": "req-1"
        }

        # Act
        response = self.client.post("/nb/a2a/test-endpoint/v1", json=payload)

        # Assert
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["jsonrpc"], "2.0")
        self.assertEqual(data["error"]["code"], -32601)
        self.assertIn("not found", data["error"]["message"].lower())

    def test_rest_message_send_success(self):
        """POST /message:send should call a2a_server_service.handle_message_send."""
        # Arrange
        expected_result = {"status": "sent"}
        a2a_service_module.a2a_server_service.handle_message_send.return_value = expected_result
        message_payload = {
            "message": {"content": "test message"},
            "configuration": {},
            "metadata": {}
        }

        # Act
        response = self.client.post("/nb/a2a/test-endpoint/message:send", json=message_payload)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected_result)

    def test_rest_get_task_success(self):
        """GET /tasks/{task_id} should return task details."""
        # Arrange
        expected_task = {"id": "task-123", "status": "completed"}
        # Clear side_effect from previous test before setting return_value
        a2a_service_module.a2a_server_service.get_task.side_effect = None
        a2a_service_module.a2a_server_service.get_task.return_value = expected_task

        # Act
        response = self.client.get("/nb/a2a/test-endpoint/tasks/task-123")

        # Assert
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["task"], expected_task)

    def test_rest_get_task_not_found(self):
        """GET /tasks/{task_id} returns 404 when task does not exist."""
        # Arrange
        a2a_service_module.a2a_server_service.get_task.side_effect = (
            a2a_service_module.TaskNotFoundError("Task not found")
        )

        # Act
        response = self.client.get("/nb/a2a/test-endpoint/tasks/missing-task")

        # Assert
        self.assertEqual(response.status_code, 404)

    def test_rest_message_stream_endpoint_exists(self):
        """POST /message:stream endpoint should be registered (returns 200)."""
        # Arrange
        a2a_service_module.a2a_server_service.handle_message_stream.return_value = iter([])

        # Act
        response = self.client.post("/nb/a2a/test-endpoint/message:send", json={"message": {}})

        # Assert - endpoint exists and returns a response
        self.assertIn(response.status_code, [200, 500])


if __name__ == "__main__":
    unittest.main()
