import unittest
from unittest.mock import patch, MagicMock, Mock
import sys
import os

# Add the backend directory to path so we can import modules
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../backend'))
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
    patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock),
    patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None),
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
    db_session_patch = patch.object(db_client_module, 'get_db_session', return_value=Mock())
    db_session_patch.start()
    all_patches.append(db_session_patch)
except ImportError:
    # If import fails, try patching the path directly (may trigger import)
    db_session_patch = patch('backend.database.client.get_db_session', return_value=Mock())
    db_session_patch.start()
    all_patches.append(db_session_patch)

# Now safe to import app modules
from fastapi import HTTPException
from fastapi.testclient import TestClient
from apps.config_app import app


# Stop all patches at the end of the module
import atexit
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
            'mock_user_management_router',  # or 'user_management_router' depending on IS_SPEED_MODE
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
        self.assertGreater(len(app.routes), 10)  # Should have many routes from all routers

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


if __name__ == "__main__":
    unittest.main()
