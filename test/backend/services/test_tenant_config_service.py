import sys
import os
import types
import unittest
from unittest.mock import MagicMock, patch

# Add backend directory to Python path for proper imports
project_root = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '../../../'))
backend_dir = os.path.join(project_root, 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Patch boto3 and other dependencies before importing anything from backend
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
minio_client_mock._ensure_bucket_exists = MagicMock()
minio_client_mock.client = MagicMock()

# Mock the entire MinIOStorageConfig class to avoid validation
minio_config_mock = MagicMock()
minio_config_mock.validate = MagicMock()

# Import backend modules after all patches are applied
# Use additional context manager to ensure MinioClient is properly mocked during import
with patch('backend.database.client.MinioClient', return_value=minio_client_mock), \
        patch('nexent.storage.minio_config.MinIOStorageConfig', return_value=minio_config_mock):
    from backend.services.tenant_config_service import (
        get_selected_knowledge_list,
        update_selected_knowledge,
        delete_selected_knowledge_by_index_name,
    )


class TestTenantConfigService(unittest.TestCase):
    def setUp(self):
        self.tenant_id = "test_tenant_id"
        self.user_id = "test_user_id"
        self.index_name = "test_index_name"
        self.index_name_list = ["test_index_name1", "test_index_name2"]
        self.knowledge_id = "knowledge_id_1"
        self.knowledge_ids = ["knowledge_id_1", "knowledge_id_2"]
        self.tenant_config_id = "tenant_config_id_1"

    @patch("backend.services.tenant_config_service.get_tenant_config_info")
    @patch("backend.services.tenant_config_service.get_knowledge_info_by_knowledge_ids")
    def test_get_selected_knowledge_list_empty(
        self, mock_get_knowledge_info, mock_get_config
    ):
        mock_get_config.return_value = []
        result = get_selected_knowledge_list(self.tenant_id, self.user_id)
        self.assertEqual(result, [])
        mock_get_knowledge_info.assert_not_called()

    @patch("backend.services.tenant_config_service.get_tenant_config_info")
    @patch("backend.services.tenant_config_service.get_knowledge_info_by_knowledge_ids")
    def test_get_selected_knowledge_list_with_records(
        self, mock_get_knowledge_info, mock_get_config
    ):
        mock_get_config.return_value = [
            {"config_value": self.knowledge_id,
                "tenant_config_id": self.tenant_config_id}
        ]
        mock_get_knowledge_info.return_value = [
            {"knowledge_id": self.knowledge_id, "name": "Test Knowledge"}
        ]

        result = get_selected_knowledge_list(self.tenant_id, self.user_id)

        self.assertEqual(
            result, [{"knowledge_id": self.knowledge_id,
                      "name": "Test Knowledge"}]
        )
        mock_get_knowledge_info.assert_called_once_with([self.knowledge_id])

    @patch("backend.services.tenant_config_service.delete_config_by_tenant_config_id")
    @patch("backend.services.tenant_config_service.insert_config")
    @patch("backend.services.tenant_config_service.get_tenant_config_info")
    @patch("backend.services.tenant_config_service.get_knowledge_ids_by_index_names")
    def test_update_selected_knowledge_add_only(
        self, mock_get_ids, mock_get_config, mock_insert, mock_delete
    ):
        mock_get_ids.return_value = self.knowledge_ids
        mock_get_config.return_value = []
        mock_insert.return_value = True

        result = update_selected_knowledge(
            self.tenant_id, self.user_id, self.index_name_list
        )
        self.assertTrue(result)
        self.assertEqual(mock_insert.call_count, 2)
        mock_delete.assert_not_called()

    @patch("backend.services.tenant_config_service.delete_config_by_tenant_config_id")
    @patch("backend.services.tenant_config_service.insert_config")
    @patch("backend.services.tenant_config_service.get_tenant_config_info")
    @patch("backend.services.tenant_config_service.get_knowledge_ids_by_index_names")
    def test_update_selected_knowledge_remove_only(
        self, mock_get_ids, mock_get_config, mock_insert, mock_delete
    ):
        mock_get_ids.return_value = []
        mock_get_config.return_value = [
            {"config_value": self.knowledge_id,
                "tenant_config_id": self.tenant_config_id}
        ]
        mock_delete.return_value = True

        result = update_selected_knowledge(self.tenant_id, self.user_id, [])
        self.assertTrue(result)
        mock_insert.assert_not_called()
        mock_delete.assert_called_once_with(self.tenant_config_id)

    @patch("backend.services.tenant_config_service.delete_config_by_tenant_config_id")
    @patch("backend.services.tenant_config_service.insert_config")
    @patch("backend.services.tenant_config_service.get_tenant_config_info")
    @patch("backend.services.tenant_config_service.get_knowledge_ids_by_index_names")
    def test_update_selected_knowledge_add_and_remove(
        self, mock_get_ids, mock_get_config, mock_insert, mock_delete
    ):
        mock_get_ids.return_value = ["knowledge_id_2"]
        mock_get_config.return_value = [
            {"config_value": "knowledge_id_1",
                "tenant_config_id": "tenant_config_id_1"}
        ]
        mock_insert.return_value = True
        mock_delete.return_value = True

        result = update_selected_knowledge(
            self.tenant_id, self.user_id, ["new_index"])
        self.assertTrue(result)
        mock_insert.assert_called_once()
        mock_delete.assert_called_once_with("tenant_config_id_1")

    @patch("backend.services.tenant_config_service.delete_config_by_tenant_config_id")
    @patch("backend.services.tenant_config_service.insert_config")
    @patch("backend.services.tenant_config_service.get_tenant_config_info")
    @patch("backend.services.tenant_config_service.get_knowledge_ids_by_index_names")
    def test_update_selected_knowledge_insert_failure(
        self, mock_get_ids, mock_get_config, mock_insert, mock_delete
    ):
        mock_get_ids.return_value = self.knowledge_ids
        mock_get_config.return_value = []
        mock_insert.return_value = False

        result = update_selected_knowledge(
            self.tenant_id, self.user_id, self.index_name_list
        )
        self.assertFalse(result)
        mock_insert.assert_called_once()

    @patch("backend.services.tenant_config_service.delete_config_by_tenant_config_id")
    @patch("backend.services.tenant_config_service.insert_config")
    @patch("backend.services.tenant_config_service.get_tenant_config_info")
    @patch("backend.services.tenant_config_service.get_knowledge_ids_by_index_names")
    def test_update_selected_knowledge_delete_failure(
        self, mock_get_ids, mock_get_config, mock_insert, mock_delete
    ):
        mock_get_ids.return_value = []
        mock_get_config.return_value = [
            {"config_value": self.knowledge_id,
                "tenant_config_id": self.tenant_config_id}
        ]
        mock_delete.return_value = False

        result = update_selected_knowledge(self.tenant_id, self.user_id, [])
        self.assertFalse(result)
        mock_delete.assert_called_once_with(self.tenant_config_id)

    @patch("backend.services.tenant_config_service.delete_config_by_tenant_config_id")
    @patch("backend.services.tenant_config_service.get_tenant_config_info")
    @patch("backend.services.tenant_config_service.get_knowledge_ids_by_index_names")
    def test_delete_selected_knowledge_by_index_name_success(
        self, mock_get_ids, mock_get_config, mock_delete
    ):
        mock_get_ids.return_value = [self.knowledge_id]
        mock_get_config.return_value = [
            {"config_value": self.knowledge_id,
                "tenant_config_id": self.tenant_config_id}
        ]
        mock_delete.return_value = True

        result = delete_selected_knowledge_by_index_name(
            self.tenant_id, self.user_id, self.index_name
        )
        self.assertTrue(result)
        mock_delete.assert_called_once_with(self.tenant_config_id)

    @patch("backend.services.tenant_config_service.delete_config_by_tenant_config_id")
    @patch("backend.services.tenant_config_service.get_tenant_config_info")
    @patch("backend.services.tenant_config_service.get_knowledge_ids_by_index_names")
    def test_delete_selected_knowledge_by_index_name_no_match(
        self, mock_get_ids, mock_get_config, mock_delete
    ):
        mock_get_ids.return_value = ["different_id"]
        mock_get_config.return_value = [
            {"config_value": self.knowledge_id,
                "tenant_config_id": self.tenant_config_id}
        ]

        result = delete_selected_knowledge_by_index_name(
            self.tenant_id, self.user_id, self.index_name
        )
        self.assertTrue(result)
        mock_delete.assert_not_called()

    @patch("backend.services.tenant_config_service.delete_config_by_tenant_config_id")
    @patch("backend.services.tenant_config_service.get_tenant_config_info")
    @patch("backend.services.tenant_config_service.get_knowledge_ids_by_index_names")
    def test_delete_selected_knowledge_by_index_name_failure(
        self, mock_get_ids, mock_get_config, mock_delete
    ):
        mock_get_ids.return_value = [self.knowledge_id]
        mock_get_config.return_value = [
            {"config_value": self.knowledge_id,
                "tenant_config_id": self.tenant_config_id}
        ]
        mock_delete.return_value = False

        result = delete_selected_knowledge_by_index_name(
            self.tenant_id, self.user_id, self.index_name
        )
        self.assertFalse(result)
        mock_delete.assert_called_once_with(self.tenant_config_id)


if __name__ == "__main__":
    unittest.main()
