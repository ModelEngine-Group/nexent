import unittest
from unittest.mock import patch, MagicMock, Mock
import sys
import os

# Add the backend directory to path so we can import modules
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../backend'))
sys.path.insert(0, backend_path)

# Apply critical patches before importing any app modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
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
from apps.datamate_app import router

# Stop all patches at the end of the module
import atexit
def stop_patches():
    for p in all_patches:
        p.stop()
atexit.register(stop_patches)


class TestDataMateApp(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create a FastAPI app with the datamate router for testing
        from fastapi import FastAPI
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)

        # Common mock return values
        self.mock_user_id = "test_user_123"
        self.mock_tenant_id = "test_tenant_456"
        self.mock_knowledge_base_id = "test_kb_789"

    @patch('apps.datamate_app.get_current_user_id')
    @patch('apps.datamate_app.sync_datamate_knowledge_bases_records')
    def test_sync_datamate_and_create_records_endpoint_success(self, mock_sync_service, mock_get_user):
        """Test successful sync and create records endpoint."""
        # Arrange
        mock_get_user.return_value = (self.mock_user_id, self.mock_tenant_id)
        mock_sync_service.return_value = {
            "indices": ["kb1", "kb2"],
            "count": 2,
            "indices_info": [
                {"name": "kb1", "display_name": "Knowledge Base 1", "stats": {}},
                {"name": "kb2", "display_name": "Knowledge Base 2", "stats": {}}
            ]
        }

        # Act
        response = self.client.post(
            "/datamate/sync_and_create_records",
            headers={"Authorization": "Bearer test_token"}
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data["indices"], ["kb1", "kb2"])
        self.assertEqual(response_data["count"], 2)
        self.assertEqual(len(response_data["indices_info"]), 2)
        mock_get_user.assert_called_once_with("Bearer test_token")
        mock_sync_service.assert_called_once_with(
            tenant_id=self.mock_tenant_id,
            user_id=self.mock_user_id
        )

    @patch('apps.datamate_app.get_current_user_id')
    @patch('apps.datamate_app.sync_datamate_knowledge_bases_records')
    def test_sync_datamate_and_create_records_endpoint_no_auth(self, mock_sync_service, mock_get_user):
        """Test sync endpoint without authorization header."""
        # Arrange
        mock_get_user.return_value = (self.mock_user_id, self.mock_tenant_id)
        mock_sync_service.return_value = {"indices": [], "count": 0}

        # Act
        response = self.client.post("/datamate/sync_and_create_records")

        # Assert
        self.assertEqual(response.status_code, 200)
        mock_get_user.assert_called_once_with(None)
        mock_sync_service.assert_called_once_with(
            tenant_id=self.mock_tenant_id,
            user_id=self.mock_user_id
        )

    @patch('apps.datamate_app.get_current_user_id')
    def test_sync_datamate_and_create_records_endpoint_service_error(self, mock_get_user):
        """Test sync endpoint when service raises an exception."""
        # Arrange
        mock_get_user.return_value = (self.mock_user_id, self.mock_tenant_id)

        # Mock the service to raise an exception
        with patch('apps.datamate_app.sync_datamate_knowledge_bases_records') as mock_sync:
            mock_sync.side_effect = Exception("Service error occurred")

            # Act
            response = self.client.post(
                "/datamate/sync_and_create_records",
                headers={"Authorization": "Bearer test_token"}
            )

            # Assert
            self.assertEqual(response.status_code, 500)
            response_data = response.json()
            self.assertIn("Error syncing DataMate knowledge bases", response_data["detail"])
            self.assertIn("Service error occurred", response_data["detail"])

    @patch('apps.datamate_app.get_current_user_id')
    def test_sync_datamate_and_create_records_endpoint_auth_error(self, mock_get_user):
        """Test sync endpoint when authentication fails."""
        # Arrange
        mock_get_user.side_effect = Exception("Authentication failed")

        # Act
        response = self.client.post(
            "/datamate/sync_and_create_records",
            headers={"Authorization": "Bearer invalid_token"}
        )

        # Assert
        self.assertEqual(response.status_code, 500)
        response_data = response.json()
        self.assertIn("Error syncing DataMate knowledge bases", response_data["detail"])

    @patch('apps.datamate_app.fetch_datamate_knowledge_base_file_list')
    def test_get_datamate_knowledge_base_files_endpoint_success(self, mock_fetch_files):
        """Test successful get knowledge base files endpoint."""
        # Arrange
        mock_files_data = {
            "status": "success",
            "files": [
                {"name": "file1.pdf", "size": 12345, "type": "pdf"},
                {"name": "file2.txt", "size": 6789, "type": "txt"}
            ]
        }
        mock_fetch_files.return_value = mock_files_data

        # Act
        response = self.client.get(f"/datamate/{self.mock_knowledge_base_id}/files")

        # Assert
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data["status"], "success")
        self.assertEqual(len(response_data["files"]), 2)
        self.assertEqual(response_data["files"][0]["name"], "file1.pdf")
        mock_fetch_files.assert_called_once_with(self.mock_knowledge_base_id)

    @patch('apps.datamate_app.fetch_datamate_knowledge_base_file_list')
    def test_get_datamate_knowledge_base_files_endpoint_with_auth(self, mock_fetch_files):
        """Test get files endpoint with authorization header (should be ignored)."""
        # Arrange
        mock_files_data = {
            "status": "success",
            "files": [{"name": "file1.pdf", "size": 12345}]
        }
        mock_fetch_files.return_value = mock_files_data

        # Act
        response = self.client.get(
            f"/datamate/{self.mock_knowledge_base_id}/files",
            headers={"Authorization": "Bearer test_token"}
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        mock_fetch_files.assert_called_once_with(self.mock_knowledge_base_id)

    @patch('apps.datamate_app.fetch_datamate_knowledge_base_file_list')
    def test_get_datamate_knowledge_base_files_endpoint_service_error(self, mock_fetch_files):
        """Test get files endpoint when service raises an exception."""
        # Arrange
        mock_fetch_files.side_effect = RuntimeError("Failed to fetch files")

        # Act
        response = self.client.get(f"/datamate/{self.mock_knowledge_base_id}/files")

        # Assert
        self.assertEqual(response.status_code, 500)
        response_data = response.json()
        self.assertIn("Error fetching DataMate knowledge base files", response_data["detail"])
        self.assertIn("Failed to fetch files", response_data["detail"])

    def test_get_datamate_knowledge_base_files_endpoint_invalid_kb_id(self):
        """Test get files endpoint with various knowledge base IDs."""
        # Test with empty knowledge base ID
        response = self.client.get("/datamate//files")
        self.assertEqual(response.status_code, 404)  # FastAPI path validation

        # Test with special characters (should be handled by service)
        with patch('apps.datamate_app.fetch_datamate_knowledge_base_file_list') as mock_fetch:
            mock_fetch.return_value = {"status": "success", "files": []}
            response = self.client.get("/datamate/kb-with-special-chars_123/files")
            self.assertEqual(response.status_code, 200)
            mock_fetch.assert_called_once_with("kb-with-special-chars_123")

    @patch('apps.datamate_app.fetch_datamate_knowledge_base_file_list')
    def test_get_datamate_knowledge_base_files_endpoint_empty_files(self, mock_fetch_files):
        """Test get files endpoint when knowledge base has no files."""
        # Arrange
        mock_fetch_files.return_value = {
            "status": "success",
            "files": []
        }

        # Act
        response = self.client.get(f"/datamate/{self.mock_knowledge_base_id}/files")

        # Assert
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data["status"], "success")
        self.assertEqual(response_data["files"], [])

    @patch('apps.datamate_app.fetch_datamate_knowledge_base_file_list')
    def test_get_datamate_knowledge_base_files_endpoint_large_response(self, mock_fetch_files):
        """Test get files endpoint with a large number of files."""
        # Arrange
        large_files_list = [
            {"name": f"file{i}.pdf", "size": 1000 + i, "type": "pdf"}
            for i in range(100)
        ]
        mock_fetch_files.return_value = {
            "status": "success",
            "files": large_files_list
        }

        # Act
        response = self.client.get(f"/datamate/{self.mock_knowledge_base_id}/files")

        # Assert
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(len(response_data["files"]), 100)
        self.assertEqual(response_data["files"][0]["name"], "file0.pdf")
        self.assertEqual(response_data["files"][99]["name"], "file99.pdf")

    def test_router_prefix(self):
        """Test that the router has the correct prefix."""
        self.assertEqual(router.prefix, "/datamate")

    def test_endpoint_paths(self):
        """Test that endpoints are registered with correct paths."""
        routes = [route.path for route in router.routes]

        # Check that both endpoints are registered (with router prefix)
        self.assertIn("/datamate/sync_and_create_records", routes)
        self.assertIn("/datamate/{knowledge_base_id}/files", routes)

        # Verify HTTP methods
        post_routes = [route for route in router.routes if route.methods == {"POST"}]
        get_routes = [route for route in router.routes if route.methods == {"GET"}]

        self.assertEqual(len(post_routes), 1)
        self.assertEqual(len(get_routes), 1)
        self.assertEqual(post_routes[0].path, "/datamate/sync_and_create_records")
        self.assertEqual(get_routes[0].path, "/datamate/{knowledge_base_id}/files")


if __name__ == '__main__':
    unittest.main()
