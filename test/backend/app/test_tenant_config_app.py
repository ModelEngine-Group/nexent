import unittest
import json
import os
import sys
from unittest.mock import MagicMock
from http import HTTPStatus

# Add backend path to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.insert(0, backend_dir)

# Mock all external dependencies before any imports
database_client_mock = MagicMock()
database_client_mock.MinioClient = MagicMock()
database_client_mock.get_db_session = MagicMock()
database_client_mock.db_client = MagicMock()
sys.modules['database.client'] = database_client_mock

botocore_client_mock = MagicMock()
sys.modules['botocore.client'] = botocore_client_mock

sys.modules['database.tenant_config_db'] = MagicMock()

# Create mock functions
mock_get_current_user_id = MagicMock()
mock_get_selected_knowledge_list = MagicMock()
mock_update_selected_knowledge = MagicMock()

# Create mocked service modules
services_mock = MagicMock()
services_mock.get_selected_knowledge_list = mock_get_selected_knowledge_list
services_mock.update_selected_knowledge = mock_update_selected_knowledge

auth_mock = MagicMock()
auth_mock.get_current_user_id = mock_get_current_user_id

const_mock = MagicMock()
const_mock.DEPLOYMENT_VERSION = 'test_version'
const_mock.APP_VERSION = 'v1.2.3'

sys.modules['services.tenant_config_service'] = services_mock
sys.modules['utils.auth_utils'] = auth_mock
sys.modules['consts.const'] = const_mock

# Now import FastAPI components and the router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.tenant_config_app import router

# Import the module to directly replace functions
import apps.tenant_config_app as tenant_app

class TestTenantConfigApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up test client and mocks"""
        # Create FastAPI app and test client
        cls.app = FastAPI()
        cls.app.include_router(router)
        cls.client = TestClient(cls.app)

        # Store references to mocks for easy access
        cls.mock_get_user_id = mock_get_current_user_id
        cls.mock_get_knowledge_list = mock_get_selected_knowledge_list
        cls.mock_update_knowledge = mock_update_selected_knowledge

        # Replace functions in the imported module directly
        tenant_app.get_current_user_id = cls.mock_get_user_id
        tenant_app.get_selected_knowledge_list = cls.mock_get_knowledge_list
        tenant_app.update_selected_knowledge = cls.mock_update_knowledge

        # Set up default mock returns
        cls.mock_get_user_id.return_value = ("test_user", "test_tenant")
        cls.mock_get_knowledge_list.return_value = [
            {
                "index_name": "kb1",
                "embedding_model_name": "embedding-model-1",
                "knowledge_sources": ["source1", "source2"]
            },
            {
                "index_name": "kb2",
                "embedding_model_name": "embedding-model-2",
                "knowledge_sources": ["source3"]
            }
        ]
        cls.mock_update_knowledge.return_value = True

    def setUp(self):
        """Reset mocks before each test"""
        # Reset all mocks to default state
        self.mock_get_user_id.reset_mock()
        self.mock_get_knowledge_list.reset_mock()
        self.mock_update_knowledge.reset_mock()

        # Clear any side effects
        self.mock_get_user_id.side_effect = None
        self.mock_get_knowledge_list.side_effect = None
        self.mock_update_knowledge.side_effect = None

        # Set up default returns
        self.mock_get_user_id.return_value = ("test_user", "test_tenant")
        self.mock_get_knowledge_list.return_value = [
            {
                "index_name": "kb1",
                "embedding_model_name": "embedding-model-1",
                "knowledge_sources": ["source1", "source2"]
            },
            {
                "index_name": "kb2",
                "embedding_model_name": "embedding-model-2",
                "knowledge_sources": ["source3"]
            }
        ]
        self.mock_update_knowledge.return_value = True

    def test_get_deployment_version_success(self):
        """Test successful retrieval of deployment version"""
        response = self.client.get("/tenant_config/deployment_version")

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("deployment_version", data)
        self.assertIn("app_version", data)
        self.assertEqual(len(data.keys()), 3)


if __name__ == '__main__':
    unittest.main()
