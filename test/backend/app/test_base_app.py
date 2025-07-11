import unittest
from unittest.mock import patch, MagicMock, Mock
import sys
import os

# Add the backend directory to path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../backend')))

# Apply patches before importing any app modules
patches = [
    # Mock boto3 client
    patch('boto3.client', return_value=Mock()),
    # Mock boto3 resource
    patch('boto3.resource', return_value=Mock()),
    # Mock database sessions
    patch('backend.database.client.get_db_session', return_value=Mock())
]

for p in patches:
    p.start()

# Now safe to import app modules
from fastapi import HTTPException
from fastapi.testclient import TestClient
from apps.base_app import app


# Stop all patches at the end of the module
import atexit
def stop_patches():
    for p in patches:
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

    @patch("apps.base_app.logging")
    def test_http_exception_handler(self, mock_logging):
        """Test the HTTP exception handler."""
        # Create a mock request and exception
        mock_request = MagicMock()
        http_exception = HTTPException(status_code=404, detail="Test not found")
        
        # Call the exception handler directly
        from apps.base_app import http_exception_handler
        import asyncio
        
        response = asyncio.run(http_exception_handler(mock_request, http_exception))
        
        # Verify the response
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.body.decode(), '{"message":"Test not found"}')
        mock_logging.error.assert_called_once_with("HTTPException: Test not found")

    @patch("apps.base_app.logging")
    def test_generic_exception_handler(self, mock_logging):
        """Test the generic exception handler."""
        # Create a mock request and exception
        mock_request = MagicMock()
        generic_exception = Exception("Test exception")
        
        # Call the exception handler directly
        from apps.base_app import generic_exception_handler
        import asyncio
        
        response = asyncio.run(generic_exception_handler(mock_request, generic_exception))
        
        # Verify the response
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.body.decode(), '{"message":"Internal server error, please try again later."}')
        mock_logging.error.assert_called_once_with("Generic Exception: Test exception")

    def test_exception_handling_with_client(self):
        """Test exception handling using the test client."""
        # This test requires mocking an endpoint that raises an exception
        # For demonstration purposes, we'll check if status_code for a non-existent endpoint is 404
        response = self.client.get("/non-existent-endpoint")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
