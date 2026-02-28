import os
import sys
import types
import unittest
from unittest.mock import MagicMock

# Dynamically append backend path so that the relative imports inside the backend package resolve correctly
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, '../../../backend'))
sys.path.insert(0, backend_dir)

# ---------------------------------------------------------------------------
# PRE-MOCK HEAVY DEPENDENCIES BEFORE THE TARGET MODULE IS IMPORTED
# ---------------------------------------------------------------------------
# 1) Mock the sub-modules that may not exist / are heavy to import
sys.modules['boto3'] = MagicMock()
sys.modules['boto3.client'] = MagicMock()
sys.modules['boto3.resource'] = MagicMock()

# ---------------------------------------------------------------------------
# Prepare stub for 'apps.northbound_app' so that northbound_base_app can import
# ---------------------------------------------------------------------------
from fastapi import APIRouter

router_stub = APIRouter()

# Add a simple endpoint to verify router inclusion later
@router_stub.get("/test")
async def _dummy_route():
    return {"msg": "ok"}

# Add endpoints for exception testing
@router_stub.get("/http-exception")
async def _http_exception_route():
    from fastapi import HTTPException
    raise HTTPException(status_code=400, detail="Bad request")

@router_stub.get("/app-exception")
async def _app_exception_route():
    from consts.error_code import ErrorCode
    from consts.exceptions import AppException
    raise AppException(ErrorCode.VALIDATION_ERROR, "Validation failed")

@router_stub.get("/generic-exception")
async def _generic_exception_route():
    raise ValueError("Something went wrong")

# Create a lightweight module object and register it as 'apps.northbound_app'.
# We add a minimalist namespace package for 'apps' (PEP 420 style) so that imports
# using dotted paths still resolve. We set its __path__ to include the real
# backend/apps directory so that any further submodules (other than the stub) can
# still be lazily imported from disk if needed.

apps_pkg = types.ModuleType("apps")
apps_pkg.__path__ = [os.path.join(backend_dir, "apps")]
sys.modules['apps'] = apps_pkg

northbound_app_module = types.ModuleType("apps.northbound_app")
northbound_app_module.router = router_stub

sys.modules['apps.northbound_app'] = northbound_app_module

# 2) Provide dummy exception classes expected from consts.model so that they can be referenced
consts_module = types.ModuleType("consts")
consts_model_module = types.ModuleType("consts.model")

class LimitExceededError(Exception):
    """Dummy rate-limit exception for testing purposes."""
    pass

class UnauthorizedError(Exception):
    """Dummy unauthorized exception for testing purposes."""
    pass

class SignatureValidationError(Exception):
    """Dummy signature validation exception for testing purposes."""
    pass

consts_model_module.LimitExceededError = LimitExceededError
consts_model_module.UnauthorizedError = UnauthorizedError
consts_model_module.SignatureValidationError = SignatureValidationError

consts_module.model = consts_model_module
sys.modules['consts'] = consts_module
sys.modules['consts.model'] = consts_model_module
# ---------------------------------------------------------------------------
# Provide 'consts.exceptions' stub so that northbound_base_app import succeeds
# ---------------------------------------------------------------------------
consts_exceptions_module = types.ModuleType("consts.exceptions")
consts_exceptions_module.LimitExceededError = LimitExceededError
consts_exceptions_module.UnauthorizedError = UnauthorizedError
consts_exceptions_module.SignatureValidationError = SignatureValidationError

# Need to import AppException for the stub
from backend.consts.exceptions import AppException as RealAppException
consts_exceptions_module.AppException = RealAppException

# Register the stub so that `from consts.exceptions import ...` works seamlessly
sys.modules['consts.exceptions'] = consts_exceptions_module

# ---------------------------------------------------------------------------
# Provide 'consts.error_code' stub so that it can be imported in tests
# ---------------------------------------------------------------------------
consts_error_code_module = types.ModuleType("consts.error_code")

# Import the real ErrorCode from backend
from backend.consts.error_code import ErrorCode as RealErrorCode
consts_error_code_module.ErrorCode = RealErrorCode

# Register the stub
sys.modules['consts.error_code'] = consts_error_code_module

# ---------------------------------------------------------------------------
# SAFE TO IMPORT THE TARGET MODULE UNDER TEST NOW
# ---------------------------------------------------------------------------
from apps.northbound_base_app import northbound_app as app
from fastapi import HTTPException
from fastapi.testclient import TestClient  # noqa: E402


class TestNorthboundBaseApp(unittest.TestCase):
    """Unit tests covering the FastAPI instance defined in northbound_base_app.py"""

    def setUp(self):
        # Use raise_server_exceptions=False to let exception handlers process the exceptions
        self.client = TestClient(app, raise_server_exceptions=False)

    # -------------------------------------------------------------------
    # Basic application wiring / configuration
    # -------------------------------------------------------------------
    def test_app_root_path(self):
        """Ensure the FastAPI application is configured with the correct root path."""
        self.assertEqual(app.root_path, "/api")

    def test_app_title(self):
        """Ensure the FastAPI application has correct title."""
        self.assertEqual(app.title, "Nexent Northbound API")

    def test_app_version(self):
        """Ensure the FastAPI application has correct version."""
        self.assertEqual(app.version, "1.0.0")

    def test_cors_middleware_configuration(self):
        """Verify that CORS middleware is present and its options match expectations."""
        cors_middleware = None
        for middleware in app.user_middleware:
            if middleware.cls.__name__ == "CORSMiddleware":
                cors_middleware = middleware
                break
        # Middleware must be registered
        self.assertIsNotNone(cors_middleware)
        # Validate configured options - these must match the implementation exactly
        self.assertEqual(cors_middleware.kwargs.get("allow_origins"), ["*"])
        self.assertTrue(cors_middleware.kwargs.get("allow_credentials"))
        self.assertEqual(cors_middleware.kwargs.get("allow_methods"), ["GET", "POST", "PUT", "DELETE"])
        self.assertEqual(cors_middleware.kwargs.get("allow_headers"), ["*"])

    def test_router_inclusion(self):
        """The northbound router should be included - expect our dummy '/test' endpoint present."""
        routes = [route.path for route in app.routes]
        self.assertIn("/test", routes)

    # -------------------------------------------------------------------
    # Exception handler wiring
    # -------------------------------------------------------------------
    def test_http_exception_handler_registration(self):
        self.assertIn(HTTPException, app.exception_handlers)
        self.assertTrue(callable(app.exception_handlers[HTTPException]))

    def test_custom_exception_handlers_registration(self):
        self.assertIn(Exception, app.exception_handlers)
        self.assertTrue(callable(app.exception_handlers[Exception]))

    # -------------------------------------------------------------------
    # End-to-end sanity for health (dummy) endpoint - relies on router stub
    # -------------------------------------------------------------------
    def test_dummy_endpoint_success(self):
        response = self.client.get("/test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"msg": "ok"})


class TestNorthboundExceptionHandlers(unittest.TestCase):
    """Test exception handlers in northbound_base_app.py"""

    def setUp(self):
        from apps.northbound_base_app import northbound_app as test_app
        self.test_app = test_app
        self.client = TestClient(self.test_app, raise_server_exceptions=False)

    def test_http_exception_handler_response(self):
        """Test HTTPException handler returns correct response."""
        response = self.client.get("/http-exception")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"message": "Bad request"})

    def test_http_exception_handler_different_status_codes(self):
        """Test HTTPException handler with different status codes."""
        from apps.northbound_base_app import northbound_app

        @northbound_app.get("/not-found")
        async def _not_found():
            raise HTTPException(status_code=404, detail="Resource not found")

        response = self.client.get("/not-found")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"message": "Resource not found"})

    def test_app_exception_handler_response(self):
        """Test AppException handler returns correct response."""
        response = self.client.get("/app-exception")
        self.assertEqual(response.status_code, 400)  # VALIDATION_ERROR -> 400
        data = response.json()
        self.assertIn("code", data)
        self.assertIn("message", data)
        self.assertEqual(data["message"], "Validation failed")

    def test_app_exception_handler_includes_error_code(self):
        """Test AppException handler includes error code in response."""
        response = self.client.get("/app-exception")
        data = response.json()
        self.assertIn("code", data)
        # Should have a valid error code
        self.assertIsNotNone(data["code"])

    def test_generic_exception_handler_response(self):
        """Test generic exception handler returns 500."""
        response = self.client.get("/generic-exception")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"message": "Internal server error, please try again later."})

    def test_generic_exception_handler_delegates_to_app_exception(self):
        """Test generic exception handler delegates to AppException handler."""
        from apps.northbound_base_app import northbound_app
        from consts.error_code import ErrorCode
        from consts.exceptions import AppException

        @northbound_app.get("/app-exception-delegated")
        async def _app_exception_delegated():
            raise AppException(ErrorCode.FORBIDDEN, "Access denied")

        response = self.client.get("/app-exception-delegated")
        # Should return 403 (FORBIDDEN), not 500
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertEqual(data["message"], "Access denied")

    def test_different_app_exception_error_codes(self):
        """Test different error codes map to correct HTTP status."""
        from apps.northbound_base_app import northbound_app
        from consts.error_code import ErrorCode
        from consts.exceptions import AppException

        test_cases = [
            (ErrorCode.TOKEN_EXPIRED, 401),
            (ErrorCode.FORBIDDEN, 403),
            (ErrorCode.RATE_LIMIT_EXCEEDED, 429),
            (ErrorCode.FILE_TOO_LARGE, 413),
        ]

        for error_code, expected_status in test_cases:
            @northbound_app.get(f"/test-{error_code.name}")
            async def _test_error():
                raise AppException(error_code, "Test error")

            response = self.client.get(f"/test-{error_code.name}")
            self.assertEqual(response.status_code, expected_status,
                           f"Expected {expected_status} for {error_code}, got {response.status_code}")


class TestNorthboundExceptionHandlerFunctions(unittest.TestCase):
    """Test exception handler functions directly."""

    def test_northbound_http_exception_handler_logs_and_returns_json(self):
        """Test northbound_http_exception_handler logs and returns correct JSON."""
        from apps.northbound_base_app import northbound_http_exception_handler
        from apps.northbound_base_app import logger

        mock_request = MagicMock()
        mock_request.url = "http://test.com/test"
        exc = HTTPException(status_code=400, detail="Bad request")

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(northbound_http_exception_handler(mock_request, exc))
        finally:
            loop.close()

        self.assertEqual(response.status_code, 400)
        import json
        body = json.loads(response.body)
        self.assertEqual(body["message"], "Bad request")

    def test_northbound_app_exception_handler_logs_and_returns_json(self):
        """Test northbound_app_exception_handler logs and returns correct JSON."""
        from apps.northbound_base_app import northbound_app_exception_handler
        from consts.error_code import ErrorCode
        from consts.exceptions import AppException

        mock_request = MagicMock()
        mock_request.url = "http://test.com/test"
        exc = AppException(ErrorCode.VALIDATION_ERROR, "Validation failed")

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(northbound_app_exception_handler(mock_request, exc))
        finally:
            loop.close()

        self.assertEqual(response.status_code, 400)
        import json
        body = json.loads(response.body)
        self.assertEqual(body["code"], ErrorCode.VALIDATION_ERROR.value)
        self.assertEqual(body["message"], "Validation failed")

    def test_northbound_app_exception_handler_with_details(self):
        """Test northbound_app_exception_handler with details field."""
        from apps.northbound_base_app import northbound_app_exception_handler
        from consts.error_code import ErrorCode
        from consts.exceptions import AppException

        mock_request = MagicMock()
        mock_request.url = "http://test.com/test"
        exc = AppException(
            ErrorCode.VALIDATION_ERROR,
            "Validation failed",
            details={"field": "email"}
        )

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(northbound_app_exception_handler(mock_request, exc))
        finally:
            loop.close()

        self.assertEqual(response.status_code, 400)
        import json
        body = json.loads(response.body)
        self.assertEqual(body["details"]["field"], "email")

    def test_northbound_generic_exception_handler_returns_500(self):
        """Test northbound_generic_exception_handler returns 500."""
        from apps.northbound_base_app import northbound_generic_exception_handler

        mock_request = MagicMock()
        mock_request.url = "http://test.com/test"
        exc = ValueError("Something went wrong")

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(northbound_generic_exception_handler(mock_request, exc))
        finally:
            loop.close()

        self.assertEqual(response.status_code, 500)
        import json
        body = json.loads(response.body)
        self.assertEqual(body["message"], "Internal server error, please try again later.")

    def test_northbound_generic_exception_handler_delegates_to_app_exception(self):
        """Test northbound_generic_exception_handler delegates to AppException handler."""
        from apps.northbound_base_app import northbound_generic_exception_handler
        from consts.error_code import ErrorCode
        from consts.exceptions import AppException

        mock_request = MagicMock()
        mock_request.url = "http://test.com/test"
        exc = AppException(ErrorCode.FORBIDDEN, "Access denied")

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(northbound_generic_exception_handler(mock_request, exc))
        finally:
            loop.close()

        # Should delegate to app exception handler (403 not 500)
        self.assertEqual(response.status_code, 403)
        import json
        body = json.loads(response.body)
        self.assertEqual(body["message"], "Access denied")


if __name__ == "__main__":
    unittest.main()