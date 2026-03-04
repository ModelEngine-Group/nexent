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


class AppException(Exception):
    """Dummy AppException for testing purposes."""
    pass


class LimitExceededError(Exception):
    """Dummy rate-limit exception for testing purposes."""
    pass

class UnauthorizedError(Exception):
    """Dummy unauthorized exception for testing purposes."""
    pass

class SignatureValidationError(Exception):
    """Dummy signature validation exception for testing purposes."""
    pass


consts_exceptions_module.AppException = AppException
consts_exceptions_module.LimitExceededError = LimitExceededError
consts_exceptions_module.UnauthorizedError = UnauthorizedError
consts_exceptions_module.SignatureValidationError = SignatureValidationError

# Register the stub so that `from consts.exceptions import ...` works seamlessly
sys.modules['consts.exceptions'] = consts_exceptions_module

# ---------------------------------------------------------------------------
# SAFE TO IMPORT THE TARGET MODULE UNDER TEST NOW
# ---------------------------------------------------------------------------
from apps.northbound_base_app import northbound_app as app
from fastapi import HTTPException
from fastapi.testclient import TestClient  # noqa: E402


class TestNorthboundBaseApp(unittest.TestCase):
    """Unit tests covering the FastAPI instance defined in northbound_base_app.py"""

    def setUp(self):
        self.client = TestClient(app)

    # -------------------------------------------------------------------
    # Basic application wiring / configuration
    # -------------------------------------------------------------------
    def test_app_root_path(self):
        """Ensure the FastAPI application is configured with the correct root path."""
        self.assertEqual(app.root_path, "/api")

    def test_cors_middleware_configuration(self):
        """Verify that CORS middleware is present and its options match expectations."""
        cors_middleware = None
        for middleware in app.user_middleware:
            if middleware.cls.__name__ == "CORSMiddleware":
                cors_middleware = middleware
                break
        # Middleware must be registered
        self.assertIsNotNone(cors_middleware)
        # Validate configured options – these must match the implementation exactly
        self.assertEqual(cors_middleware.kwargs.get("allow_origins"), ["*"])
        self.assertTrue(cors_middleware.kwargs.get("allow_credentials"))
        self.assertEqual(cors_middleware.kwargs.get("allow_methods"), ["GET", "POST", "PUT", "DELETE"])
        self.assertEqual(cors_middleware.kwargs.get("allow_headers"), ["*"])

    def test_router_inclusion(self):
        """The northbound router should be included – expect our dummy '/test' endpoint present."""
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
    # End-to-end sanity for health (dummy) endpoint – relies on router stub
    # -------------------------------------------------------------------
    def test_dummy_endpoint_success(self):
        response = self.client.get("/test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"msg": "ok"})


if __name__ == "__main__":
    unittest.main()
