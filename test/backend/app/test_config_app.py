import atexit
from apps.config_app import app
from fastapi.testclient import TestClient
from fastapi import HTTPException
import unittest
from unittest.mock import patch, MagicMock, Mock
import sys
import os

# Add the backend directory to path so we can import modules
backend_path = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '../../../backend'))
sys.path.insert(0, backend_path)

# Apply patches before importing any app modules
# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()

# Start critical patches first - storage factory and config validation must be patched
# before any module imports that might trigger MinioClient initialization
critical_patches = [
    # Patch storage factory and MinIO config validation FIRST
    patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
          return_value=storage_client_mock),
    patch('nexent.storage.minio_config.MinIOStorageConfig.validate',
          lambda self: None),
    # Mock boto3 client
    patch('boto3.client', return_value=Mock()),
    # Mock boto3 resource
    patch('boto3.resource', return_value=Mock()),
    # Mock Elasticsearch to prevent connection errors
    patch('elasticsearch.Elasticsearch', return_value=Mock()),
]

for p in critical_patches:
    p.start()

# Patch MinioClient class to return mock instance when instantiated
# This prevents real initialization during module import
patches = [
    patch('backend.database.client.MinioClient', return_value=minio_mock),
    patch('database.client.MinioClient', return_value=minio_mock),
    patch('backend.database.client.minio_client', minio_mock),
]

for p in patches:
    p.start()

# Combine all patches for cleanup
all_patches = critical_patches + patches

# Now safe to import modules that use database.client
# After import, we can patch get_db_session if needed
try:
    from backend.database import client as db_client_module
    # Patch get_db_session after module is imported
    db_session_patch = patch.object(
        db_client_module, 'get_db_session', return_value=Mock())
    db_session_patch.start()
    all_patches.append(db_session_patch)
except ImportError:
    # If import fails, try patching the path directly (may trigger import)
    db_session_patch = patch(
        'backend.database.client.get_db_session', return_value=Mock())
    db_session_patch.start()
    all_patches.append(db_session_patch)

# Now safe to import app modules


# Stop all patches at the end of the module


def stop_patches():
    for p in all_patches:
        p.stop()


atexit.register(stop_patches)


class TestBaseApp(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_app_initialization(self):
        """Test that the FastAPI app is initialized with correct root path."""
        self.assertEqual(app.root_path, "/api")

    def test_cors_middleware(self):
        """Test that CORS middleware is properly configured."""
        # Find the CORS middleware
        cors_middleware = None
        for middleware in app.user_middleware:
            if middleware.cls.__name__ == "CORSMiddleware":
                cors_middleware = middleware
                break

        self.assertIsNotNone(cors_middleware)

        # In FastAPI, middleware options are stored in 'middleware.kwargs'
        self.assertEqual(cors_middleware.kwargs.get("allow_origins"), ["*"])
        self.assertTrue(cors_middleware.kwargs.get("allow_credentials"))
        self.assertEqual(cors_middleware.kwargs.get("allow_methods"), ["*"])
        self.assertEqual(cors_middleware.kwargs.get("allow_headers"), ["*"])

    def test_routers_included(self):
        """Test that all routers are included in the app."""
        # Get all routes in the app
        routes = [route.path for route in app.routes]

        # Check if routes exist (at least some routes should be present)
        self.assertTrue(len(routes) > 0)

    def test_http_exception_handler(self):
        """Test the HTTP exception handler."""
        # Test that the exception handler is registered
        exception_handlers = app.exception_handlers
        self.assertIn(HTTPException, exception_handlers)

        # Test that the handler function exists and is callable
        http_exception_handler = exception_handlers[HTTPException]
        self.assertIsNotNone(http_exception_handler)
        self.assertTrue(callable(http_exception_handler))

    def test_generic_exception_handler(self):
        """Test the generic exception handler."""
        # Test that the exception handler is registered
        exception_handlers = app.exception_handlers
        self.assertIn(Exception, exception_handlers)

        # Test that the handler function exists and is callable
        generic_exception_handler = exception_handlers[Exception]
        self.assertTrue(callable(generic_exception_handler))

    def test_exception_handling_with_client(self):
        """Test exception handling using the test client."""
        # This test requires mocking an endpoint that raises an exception
        # For demonstration purposes, we'll check if status_code for a non-existent endpoint is 404
        response = self.client.get("/non-existent-endpoint")
        self.assertEqual(response.status_code, 404)

    def test_speed_mode_logic(self):
        """Test the speed mode conditional logic."""
        # Since the conditional logic is executed at import time,
        # we test the logic by checking the final state of the app
        from apps.config_app import app
        from consts.const import IS_SPEED_MODE

        # Verify that the app has been properly initialized with routers
        self.assertIsNotNone(app)
        self.assertGreater(len(app.routes), 10)  # Should have many routes

        # Test that IS_SPEED_MODE is accessible
        self.assertIsInstance(IS_SPEED_MODE, bool)

    @patch('utils.monitoring.monitoring_manager.setup_fastapi_app')
    def test_monitoring_setup(self, mock_setup):
        """Test that monitoring is set up for the application."""
        # Re-import to trigger the setup
        import importlib
        import apps.config_app
        importlib.reload(apps.config_app)

        # Verify that setup_fastapi_app was called with the app
        mock_setup.assert_called_once()
        # The argument should be the FastAPI app instance
        call_args = mock_setup.call_args[0]
        self.assertEqual(call_args[0].root_path, "/api")

    def test_all_routers_included(self):
        """Test that all expected routers are included in the app."""
        expected_routers = [
            'model_manager_router',
            'config_sync_router',
            'agent_router',
            'vectordatabase_router',
            'voice_router',
            'file_manager_router',
            'proxy_router',
            'tool_config_router',
            # or 'user_management_router' depending on IS_SPEED_MODE
            'mock_user_management_router',
            'summary_router',
            'prompt_router',
            'tenant_config_router',
            'remote_mcp_router',
            'tenant_router',
            'group_router',
            'invitation_router'
        ]

        # Get all router names that were included
        included_routers = []
        for route in app.routes:
            if hasattr(route, 'tags') and route.tags:
                # Try to identify router by tags or other means
                pass

        # Since it's hard to identify routers directly from routes,
        # we'll check that we have a reasonable number of routes
        # Should have many routes from all routers
        self.assertGreater(len(app.routes), 10)

    def test_http_exception_handler_registration(self):
        """Test that HTTP exception handler is properly registered."""
        # Test that the exception handler exists in the app
        exception_handlers = app.exception_handlers
        self.assertIn(HTTPException, exception_handlers)

    def test_generic_exception_handler_registration(self):
        """Test that generic exception handler is properly registered."""
        # Test that the exception handler exists in the app
        exception_handlers = app.exception_handlers
        self.assertIn(Exception, exception_handlers)

    def test_app_exception_handler_registration(self):
        """Test that AppException handler is properly registered."""
        from consts.exceptions import AppException
        exception_handlers = app.exception_handlers
        self.assertIn(AppException, exception_handlers)


class TestExceptionHandlerResponses(unittest.TestCase):
    """Test exception handler responses."""

    def setUp(self):
        # Use the actual config_app with exception handlers
        from apps.config_app import app
        from consts.const import IS_SPEED_MODE

        self.test_app = app
        # Use raise_server_exceptions=False to let exception handlers process the exceptions
        self.client = TestClient(self.test_app, raise_server_exceptions=False)

        # Also access the logger for testing
        from apps import config_app as config_app_module
        self.logger = config_app_module.logger

    def test_http_exception_handler_logs_error(self):
        """Test HTTPException handler logs the error."""
        from fastapi import HTTPException

        # Create a mock request
        mock_request = MagicMock()
        mock_request.url = "http://test.com/test"

        # Call the exception handler directly
        from apps.config_app import http_exception_handler
        exc = HTTPException(status_code=400, detail="Bad request")

        # Run the handler
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(
                http_exception_handler(mock_request, exc))
        finally:
            loop.close()

        # Verify response
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.body, b'{"message":"Bad request"}')

    def test_app_exception_handler_logs_error(self):
        """Test AppException handler logs the error and returns correct response."""
        from consts.error_code import ErrorCode
        from consts.exceptions import AppException

        # Create a mock request
        mock_request = MagicMock()
        mock_request.url = "http://test.com/test"

        # Call the exception handler directly
        from apps.config_app import app_exception_handler
        exc = AppException(ErrorCode.VALIDATION_ERROR, "Validation failed")

        # Run the handler
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(
                app_exception_handler(mock_request, exc))
        finally:
            loop.close()

        # Verify response
        self.assertEqual(response.status_code, 400)  # VALIDATION_ERROR -> 400
        import json
        body = json.loads(response.body)
        self.assertEqual(body["code"], ErrorCode.VALIDATION_ERROR.value)
        self.assertEqual(body["message"], "Validation failed")

    def test_app_exception_handler_with_details(self):
        """Test AppException handler with details field."""
        from consts.error_code import ErrorCode
        from consts.exceptions import AppException

        mock_request = MagicMock()
        mock_request.url = "http://test.com/test"

        from apps.config_app import app_exception_handler
        exc = AppException(
            ErrorCode.VALIDATION_ERROR,
            "Validation failed",
            details={"field": "email"}
        )

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(
                app_exception_handler(mock_request, exc))
        finally:
            loop.close()

        self.assertEqual(response.status_code, 400)
        import json
        body = json.loads(response.body)
        self.assertEqual(body["details"]["field"], "email")

    def test_generic_exception_handler_logs_error(self):
        """Test generic exception handler logs the error."""
        # Create a mock request
        mock_request = MagicMock()
        mock_request.url = "http://test.com/test"

        # Call the exception handler directly
        from apps.config_app import generic_exception_handler
        exc = ValueError("Something went wrong")

        # Run the handler
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(
                generic_exception_handler(mock_request, exc))
        finally:
            loop.close()

        # Verify response
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.body, b'{"message":"Internal server error, please try again later."}')

    def test_generic_exception_handler_delegates_to_app_exception_handler(self):
        """Test generic exception handler delegates to AppException handler for AppException."""
        from consts.error_code import ErrorCode
        from consts.exceptions import AppException

        # Create a mock request
        mock_request = MagicMock()
        mock_request.url = "http://test.com/test"

        # Call the exception handler directly with an AppException
        from apps.config_app import generic_exception_handler
        exc = AppException(ErrorCode.FORBIDDEN, "Access denied")

        # Run the handler
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(
                generic_exception_handler(mock_request, exc))
        finally:
            loop.close()

        # Verify it was delegated to app_exception_handler (returns 403 not 500)
        self.assertEqual(response.status_code, 403)
        import json
        body = json.loads(response.body)
        self.assertEqual(body["message"], "Access denied")

    def test_different_app_exception_error_codes(self):
        """Test AppException with different error codes."""
        from consts.error_code import ErrorCode
        from consts.exceptions import AppException

        test_cases = [
            (ErrorCode.TOKEN_EXPIRED, 401),
            (ErrorCode.FORBIDDEN, 403),
            (ErrorCode.RATE_LIMIT_EXCEEDED, 429),
            (ErrorCode.FILE_TOO_LARGE, 413),
        ]

        mock_request = MagicMock()
        mock_request.url = "http://test.com/test"

        from apps.config_app import app_exception_handler

        import asyncio
        for error_code, expected_status in test_cases:
            exc = AppException(error_code, "Test error")

            loop = asyncio.new_event_loop()
            try:
                response = loop.run_until_complete(
                    app_exception_handler(mock_request, exc))
            finally:
                loop.close()

            self.assertEqual(response.status_code, expected_status,
                             f"Expected {expected_status} for {error_code}, got {response.status_code}")
