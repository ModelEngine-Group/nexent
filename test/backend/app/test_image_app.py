import unittest
import json
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os
from io import BytesIO

# Add the project root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Mock the consts.const module before importing the image_app module
mock_const = MagicMock()
mock_const.DATA_PROCESS_SERVICE = "http://mock-data-process-service"
sys.modules['consts.const'] = mock_const

# Mock external dependencies before importing the module
with patch('aiohttp.ClientSession') as mock_session:
    # Now import the module after mocking dependencies
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from backend.apps.image_app import router

# Create a FastAPI app and include the router for testing
app = FastAPI()
app.include_router(router)
client = TestClient(app)

class TestImageApp(unittest.TestCase):
    def setUp(self):
        """Setup test environment before each test"""
        # Sample test data
        self.test_url = "https://example.com/image.jpg"
        self.encoded_test_url = "https%3A%2F%2Fexample.com%2Fimage.jpg"
        self.success_response = {
            "success": True,
            "data": "base64_encoded_image_data",
            "mime_type": "image/jpeg"
        }
        self.error_response = {
            "success": False,
            "error": "Failed to fetch image or image format not supported"
        }

    @patch('aiohttp.ClientSession')
    async def test_proxy_image_success(self, mock_session_class):
        """Test successful image proxy request"""
        # Setup mock responses
        mock_session = AsyncMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = self.success_response
        
        mock_session.get.return_value.__aenter__.return_value = mock_response
        
        # Test with TestClient
        with TestClient(app) as client:
            response = client.get(f"/image?url={self.encoded_test_url}")
            
        # Assertions
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.success_response)
        
        # Verify the correct URL was called
        mock_session.get.assert_called_once()
        called_url = mock_session.get.call_args[0][0]
        self.assertIn(self.test_url, called_url)

    @patch('aiohttp.ClientSession')
    async def test_proxy_image_remote_error(self, mock_session_class):
        """Test image proxy when remote service returns error"""
        # Setup mock responses
        mock_session = AsyncMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session
        
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.text.return_value = "Image not found"
        
        mock_session.get.return_value.__aenter__.return_value = mock_response
        
        # Test with TestClient
        with TestClient(app) as client:
            response = client.get(f"/image?url={self.encoded_test_url}")
            
        # Assertions
        self.assertEqual(response.status_code, 200)  # API still returns 200 with error payload
        self.assertEqual(response.json()["success"], False)
        self.assertIn("Failed to fetch image", response.json()["error"])

    @patch('aiohttp.ClientSession')
    async def test_proxy_image_exception(self, mock_session_class):
        """Test image proxy when an exception occurs"""
        # Setup mock to raise exception
        mock_session = AsyncMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session
        
        mock_session.get.side_effect = Exception("Connection error")
        
        # Test with TestClient
        with TestClient(app) as client:
            response = client.get(f"/image?url={self.encoded_test_url}")
            
        # Assertions
        self.assertEqual(response.status_code, 200)  # API still returns 200 with error payload
        self.assertEqual(response.json()["success"], False)
        self.assertEqual(response.json()["error"], "Connection error")

    @patch('aiohttp.ClientSession')
    async def test_proxy_image_with_special_chars(self, mock_session_class):
        """Test image proxy with URL containing special characters"""
        special_url = "https://example.com/image with spaces.jpg"
        encoded_special_url = "https%3A%2F%2Fexample.com%2Fimage%20with%20spaces.jpg"
        
        # Setup mock responses
        mock_session = AsyncMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = self.success_response
        
        mock_session.get.return_value.__aenter__.return_value = mock_response
        
        # Test with TestClient
        with TestClient(app) as client:
            response = client.get(f"/image?url={encoded_special_url}")
            
        # Assertions
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.success_response)
        
        # Verify URL decoding worked properly
        mock_session.get.assert_called_once()
        called_url = mock_session.get.call_args[0][0]
        self.assertIn(special_url, called_url)

    @patch('logging.getLogger')
    @patch('aiohttp.ClientSession')
    async def test_proxy_image_logging(self, mock_session_class, mock_logger):
        """Test logging in image proxy"""
        # Setup mock logger
        mock_logger_instance = MagicMock()
        mock_logger.return_value = mock_logger_instance
        
        # Setup mock session to raise exception
        mock_session = AsyncMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session
        
        mock_session.get.side_effect = Exception("Logging test error")
        
        # Test with TestClient
        with TestClient(app) as client:
            response = client.get(f"/image?url={self.encoded_test_url}")
            
        # Assert that error was logged
        mock_logger_instance.error.assert_called_once()
        log_message = mock_logger_instance.error.call_args[0][0]
        self.assertIn("Error occurred while proxying image", log_message)
        self.assertIn("Logging test error", log_message)


if __name__ == "__main__":
    unittest.main()
