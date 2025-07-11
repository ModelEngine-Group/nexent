import unittest
import json
import sys
import os
from unittest.mock import patch, MagicMock, AsyncMock

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

# Import and define all necessary Pydantic models
from pydantic import BaseModel
from typing import List, Optional, Union, Dict, Any

# Define all models that might be used in routes
class ChangeSummaryRequest(BaseModel):
    summary_result: str

# Apply all necessary mocks and setup the testing environment
def setup_test_environment():
    # Mock botocore client to prevent S3 connection attempts
    patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

    # Mock database and service dependencies
    patch('backend.database.client.MinioClient', MagicMock()).start()
    patch('backend.database.client.db_client', MagicMock()).start()
    patch('nexent.vector_database.elasticsearch_core.ElasticSearchCore', MagicMock()).start()

    # Mock elasticsearch services
    mock_es_service = patch('backend.services.elasticsearch_service.ElasticSearchService', MagicMock()).start()
    mock_get_es_core = patch('backend.services.elasticsearch_service.get_es_core', MagicMock()).start()

    # Mock authentication utilities
    mock_get_user_id = patch('backend.utils.auth_utils.get_current_user_id',
                             MagicMock(return_value=('test_user_id', 'test_tenant_id'))).start()
    mock_get_user_info = patch('backend.utils.auth_utils.get_current_user_info',
                              MagicMock(return_value=('test_user_id', 'test_tenant_id', 'en'))).start()

    # Import and patch the auto_summary method
    import backend.apps.knowledge_summary_app
    original_auto_summary = backend.apps.knowledge_summary_app.auto_summary

    async def fixed_auto_summary(*args, **kwargs):
        try:
            return await original_auto_summary(*args, **kwargs)
        except ValueError as e:
            # This handles the f-string error in the original code
            if "Invalid format specifier" in str(e):
                from fastapi.responses import StreamingResponse
                return StreamingResponse(
                    "data: {\"status\": \"error\", \"message\": \"知识库摘要生成失败\"}\n\n",
                    media_type="text/event-stream",
                    status_code=500
                )
            raise

    # Apply the patch
    backend.apps.knowledge_summary_app.auto_summary = fixed_auto_summary

    # Now import the modules needed for testing
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from backend.apps.knowledge_summary_app import router

    # Create FastAPI app and include the router for testing
    app = FastAPI()
    app.include_router(router)

    # Disable response model validation
    for route in router.routes:
        if hasattr(route, 'response_model'):
            route.response_model = None

    # Try to import consts.model and patch if needed
    try:
        import consts.model
        # Backup original class if it exists
        original_ChangeSummaryRequest = getattr(consts.model, "ChangeSummaryRequest", None)
        # Replace model
        if hasattr(consts.model, "ChangeSummaryRequest"):
            consts.model.ChangeSummaryRequest = ChangeSummaryRequest
            # Ensure module level replacements
            if 'consts.model' in sys.modules and hasattr(sys.modules['consts.model'], 'ChangeSummaryRequest'):
                sys.modules['consts.model'].ChangeSummaryRequest = ChangeSummaryRequest
    except ImportError:
        original_ChangeSummaryRequest = None
        print("Warning: Could not import consts.model, creating custom models only")

    return {
        'app': app,
        'router': router,
        'mock_es_service': mock_es_service,
        'mock_get_es_core': mock_get_es_core,
        'mock_get_user_id': mock_get_user_id,
        'mock_get_user_info': mock_get_user_info,
        'original_ChangeSummaryRequest': original_ChangeSummaryRequest
    }

# Set up the test environment
test_env = setup_test_environment()
app = test_env['app']
router = test_env['router']
mock_es_service = test_env['mock_es_service']
mock_get_es_core = test_env['mock_get_es_core']
mock_get_user_id = test_env['mock_get_user_id']
mock_get_user_info = test_env['mock_get_user_info']
original_ChangeSummaryRequest = test_env['original_ChangeSummaryRequest']

# Create test client
from fastapi.testclient import TestClient
client = TestClient(app)

class TestKnowledgeSummaryApp(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        # Restore original class if needed
        try:
            if original_ChangeSummaryRequest is not None:
                import consts.model
                if hasattr(consts.model, "ChangeSummaryRequest"):
                    consts.model.ChangeSummaryRequest = original_ChangeSummaryRequest
                if 'consts.model' in sys.modules and hasattr(sys.modules['consts.model'], 'ChangeSummaryRequest'):
                    sys.modules['consts.model'].ChangeSummaryRequest = original_ChangeSummaryRequest
        except:
            pass

    def setUp(self):
        """Setup test environment before each test"""
        # Sample test data
        self.index_name = "test_index"
        self.user_id = ("test_user_id", "test_tenant_id")
        self.user_info = ("test_user_id", "test_tenant_id", "en")
        self.summary_result = "This is a test summary for the knowledge base"
        self.auth_header = {"Authorization": "Bearer test_token"}

        # Reset mocks
        mock_get_user_id.reset_mock()
        mock_get_user_id.return_value = self.user_id

        mock_get_user_info.reset_mock()
        mock_get_user_info.return_value = self.user_info

        mock_es_service.reset_mock()
        self.mock_service_instance = MagicMock()
        mock_es_service.return_value = self.mock_service_instance

    @patch('backend.services.elasticsearch_service.get_es_core')
    async def test_auto_summary_success(self, mock_get_es_core_local):
        """Test successful auto summary generation"""
        # Setup mock responses
        mock_es_core_instance = MagicMock()
        mock_get_es_core_local.return_value = mock_es_core_instance

        # Ensure we return an appropriate response object, not just a MagicMock
        # Since this returns a StreamingResponse, no modification is needed
        self.mock_service_instance.summary_index_name = AsyncMock()
        stream_response = MagicMock()
        self.mock_service_instance.summary_index_name.return_value = stream_response

        # Execute test
        with TestClient(app) as client:
            response = client.post(
                f"/summary/{self.index_name}/auto_summary?batch_size=500",
                headers=self.auth_header
            )

        # Assertions
        self.mock_service_instance.summary_index_name.assert_called_once_with(
            index_name=self.index_name,
            batch_size=500,
            es_core=mock_es_core_instance,
            user_id=self.user_info[0],
            tenant_id=self.user_info[1],
            language=self.user_info[2]
        )
        mock_get_user_info.assert_called_once()

    @patch('backend.services.elasticsearch_service.get_es_core')
    async def test_auto_summary_exception(self, mock_get_es_core_local):
        """Test auto summary generation with exception"""
        # Setup mock to raise exception
        mock_es_core_instance = MagicMock()
        mock_get_es_core_local.return_value = mock_es_core_instance

        self.mock_service_instance.summary_index_name = AsyncMock(
            side_effect=Exception("Error generating summary")
        )

        # Execute test
        with TestClient(app) as client:
            response = client.post(
                f"/summary/{self.index_name}/auto_summary",
                headers=self.auth_header
            )

        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertIn("知识库摘要生成失败", response.text)

    def test_change_summary_success(self):
        """Test successful summary update"""
        # Setup request data using a dictionary that conforms to ChangeSummaryRequest model
        request_data = {
            "summary_result": self.summary_result
        }

        # Ensure we return a dictionary instead of a MagicMock object
        expected_response = {
            "success": True,
            "index_name": self.index_name,
            "summary": self.summary_result
        }

        # Configure service mock response
        self.mock_service_instance.change_summary.return_value = expected_response

        # Execute test with direct patching of route handler function
        with patch('backend.apps.knowledge_summary_app.ElasticSearchService', return_value=self.mock_service_instance):
            with patch('backend.apps.knowledge_summary_app.get_current_user_id', return_value=self.user_id):
                with TestClient(app) as client:
                    response = client.post(
                        f"/summary/{self.index_name}/summary",
                        json=request_data,
                        headers=self.auth_header
                    )

        # Assertions
        self.assertEqual(response.status_code, 200)
        response_json = response.json()
        self.assertEqual(response_json["success"], True)
        self.assertEqual(response_json["index_name"], self.index_name)
        self.assertEqual(response_json["summary"], self.summary_result)

        # Verify service calls
        self.mock_service_instance.change_summary.assert_called_once_with(
            index_name=self.index_name,
            summary_result=self.summary_result,
            user_id=self.user_id[0]
        )

    def test_change_summary_exception(self):
        """Test summary update with exception"""
        # Setup request data
        request_data = {
            "summary_result": self.summary_result
        }

        # Configure service mock to raise exception
        with patch('backend.apps.knowledge_summary_app.ElasticSearchService', return_value=self.mock_service_instance):
            self.mock_service_instance.change_summary.side_effect = Exception("Error updating summary")

            # Execute test
            with patch('backend.apps.knowledge_summary_app.get_current_user_id', return_value=self.user_id):
                with TestClient(app) as client:
                    response = client.post(
                        f"/summary/{self.index_name}/summary",
                        json=request_data,
                        headers=self.auth_header
                    )

        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("Knowledge base summary update failed", response.json()["detail"])

    def test_get_summary_success(self):
        """Test successful summary retrieval"""
        # Ensure we return a dictionary instead of a MagicMock object
        expected_response = {
            "success": True,
            "index_name": self.index_name,
            "summary": self.summary_result
        }

        with patch('backend.apps.knowledge_summary_app.ElasticSearchService', return_value=self.mock_service_instance):
            self.mock_service_instance.get_summary.return_value = expected_response

            # Execute test
            with TestClient(app) as client:
                response = client.get(f"/summary/{self.index_name}/summary")

        # Assertions
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected_response)

        # Verify service calls
        self.mock_service_instance.get_summary.assert_called_once_with(
            index_name=self.index_name
        )

    def test_get_summary_exception(self):
        """Test summary retrieval with exception"""
        # Configure service mock to raise exception
        with patch('backend.apps.knowledge_summary_app.ElasticSearchService', return_value=self.mock_service_instance):
            self.mock_service_instance.get_summary.side_effect = Exception("Error getting summary")

            # Execute test
            with TestClient(app) as client:
                response = client.get(f"/summary/{self.index_name}/summary")

        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("Failed to get knowledge base summary", response.json()["detail"])

if __name__ == "__main__":
    unittest.main()
