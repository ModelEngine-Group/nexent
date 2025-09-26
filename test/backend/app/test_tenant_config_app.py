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

    def test_load_knowledge_list_success(self):
        """Test successful loading of knowledge list"""
        response = self.client.get(
            "/tenant_config/load_knowledge_list",
            headers={"authorization": "Bearer test-token"}
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("content", data)

        content = data["content"]
        self.assertEqual(content["selectedKbNames"], ["kb1", "kb2"])
        self.assertEqual(content["selectedKbModels"], [
                         "embedding-model-1", "embedding-model-2"])
        self.assertEqual(content["selectedKbSources"], [
                         ["source1", "source2"], ["source3"]])

    def test_load_knowledge_list_auth_error(self):
        """Test knowledge list loading with authentication error"""
        self.mock_get_user_id.side_effect = Exception("Authentication failed")

        response = self.client.get(
            "/tenant_config/load_knowledge_list",
            headers={"authorization": "Bearer invalid-token"}
        )

        self.assertEqual(response.status_code,
                         HTTPStatus.INTERNAL_SERVER_ERROR)
        data = response.json()
        self.assertIn("Failed to load configuration", data["detail"])

    def test_load_knowledge_list_service_error(self):
        """Test knowledge list loading with service error"""
        self.mock_get_knowledge_list.side_effect = Exception("Database error")

        response = self.client.get(
            "/tenant_config/load_knowledge_list",
            headers={"authorization": "Bearer test-token"}
        )

        self.assertEqual(response.status_code,
                         HTTPStatus.INTERNAL_SERVER_ERROR)
        data = response.json()
        self.assertIn("Failed to load configuration", data["detail"])

    def test_load_knowledge_list_empty(self):
        """Test loading empty knowledge list"""
        self.mock_get_knowledge_list.return_value = []

        response = self.client.get(
            "/tenant_config/load_knowledge_list",
            headers={"authorization": "Bearer test-token"}
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["status"], "success")

        content = data["content"]
        self.assertEqual(content["selectedKbNames"], [])
        self.assertEqual(content["selectedKbModels"], [])
        self.assertEqual(content["selectedKbSources"], [])

    def test_load_knowledge_list_missing_model_name(self):
        """Test loading knowledge list with missing model_name field"""
        # This should cause a KeyError when trying to access model_name
        self.mock_get_knowledge_list.return_value = [
            {
                "index_name": "kb1",
                "knowledge_sources": ["source1"]
                # Missing embedding_model_name field
            }
        ]

        response = self.client.get(
            "/tenant_config/load_knowledge_list",
            headers={"authorization": "Bearer test-token"}
        )

        self.assertEqual(response.status_code,
                         HTTPStatus.INTERNAL_SERVER_ERROR)
        data = response.json()
        self.assertIn("Failed to load configuration", data["detail"])

    def test_update_knowledge_list_success(self):
        """Test successful knowledge list update"""
        knowledge_list = ["kb1", "kb3"]

        response = self.client.post(
            "/tenant_config/update_knowledge_list",
            headers={"authorization": "Bearer test-token"},
            json=knowledge_list
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "update success")

        # Verify the mock was called with correct parameters
        self.mock_update_knowledge.assert_called_once_with(
            tenant_id="test_tenant",
            user_id="test_user",
            index_name_list=knowledge_list
        )

    def test_update_knowledge_list_failure(self):
        """Test knowledge list update failure"""
        self.mock_update_knowledge.return_value = False
        knowledge_list = ["kb1", "kb3"]

        response = self.client.post(
            "/tenant_config/update_knowledge_list",
            headers={"authorization": "Bearer test-token"},
            json=knowledge_list
        )

        self.assertEqual(response.status_code,
                         HTTPStatus.INTERNAL_SERVER_ERROR)
        data = response.json()
        self.assertIn("Failed to update configuration", data["detail"])

    def test_update_knowledge_list_auth_error(self):
        """Test knowledge list update with authentication error"""
        self.mock_get_user_id.side_effect = Exception("Authentication failed")
        knowledge_list = ["kb1", "kb3"]

        response = self.client.post(
            "/tenant_config/update_knowledge_list",
            headers={"authorization": "Bearer invalid-token"},
            json=knowledge_list
        )

        self.assertEqual(response.status_code,
                         HTTPStatus.INTERNAL_SERVER_ERROR)
        data = response.json()
        self.assertIn("Failed to update configuration", data["detail"])

    def test_update_knowledge_list_service_error(self):
        """Test knowledge list update with service error"""
        self.mock_update_knowledge.side_effect = Exception("Database error")
        knowledge_list = ["kb1", "kb3"]

        response = self.client.post(
            "/tenant_config/update_knowledge_list",
            headers={"authorization": "Bearer test-token"},
            json=knowledge_list
        )

        self.assertEqual(response.status_code,
                         HTTPStatus.INTERNAL_SERVER_ERROR)
        data = response.json()
        self.assertIn("Failed to update configuration", data["detail"])

    def test_update_knowledge_list_empty_list(self):
        """Test updating with empty knowledge list"""
        knowledge_list = []

        response = self.client.post(
            "/tenant_config/update_knowledge_list",
            headers={"authorization": "Bearer test-token"},
            json=knowledge_list
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "update success")

    def test_update_knowledge_list_no_body(self):
        """Test updating without request body"""
        response = self.client.post(
            "/tenant_config/update_knowledge_list",
            headers={"authorization": "Bearer test-token"}
        )

        # When no body is provided, FastAPI will pass None to the knowledge_list parameter
        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["status"], "success")

        # Verify the mock was called with None
        self.mock_update_knowledge.assert_called_once_with(
            tenant_id="test_tenant",
            user_id="test_user",
            index_name_list=None
        )

    def test_get_deployment_version_success(self):
        """Test successful retrieval of deployment version"""
        response = self.client.get("/tenant_config/deployment_version")

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("deployment_version", data)
        self.assertIn("app_version", data)
        self.assertEqual(len(data.keys()), 3)

    def test_load_knowledge_list_no_auth_header(self):
        """Test loading knowledge list without authorization header"""
        response = self.client.get("/tenant_config/load_knowledge_list")

        # This should still work as the authorization parameter is Optional
        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["status"], "success")

    def test_update_knowledge_list_no_auth_header(self):
        """Test updating knowledge list without authorization header"""
        knowledge_list = ["kb1", "kb2"]

        response = self.client.post(
            "/tenant_config/update_knowledge_list",
            json=knowledge_list
        )

        # This should still work as the authorization parameter is Optional
        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data["status"], "success")


if __name__ == '__main__':
    unittest.main()
