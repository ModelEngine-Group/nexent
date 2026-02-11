import asyncio
import sys
import os
import time
import unittest
from unittest.mock import MagicMock, ANY, AsyncMock, call
# Mock MinioClient before importing modules that use it
from unittest.mock import patch
import numpy as np
from types import ModuleType, SimpleNamespace

from fastapi.responses import StreamingResponse

# Environment variables are now configured in conftest.py

# Mock boto3 before importing the module under test
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock


# Mock nexent modules before importing modules that use them
def _create_package_mock(name: str) -> MagicMock:
    pkg = MagicMock()
    pkg.__path__ = []  # Mark as package for importlib
    pkg.__spec__ = SimpleNamespace(name=name, submodule_search_locations=[])
    return pkg


nexent_mock = _create_package_mock('nexent')
sys.modules['nexent'] = nexent_mock
sys.modules['nexent.core'] = _create_package_mock('nexent.core')
sys.modules['nexent.core.agents'] = _create_package_mock('nexent.core.agents')
sys.modules['nexent.core.agents.agent_model'] = MagicMock()
# Mock nexent.core.models with OpenAIModel
openai_model_module = ModuleType('nexent.core.models')
openai_model_module.OpenAIModel = MagicMock
sys.modules['nexent.core.models'] = openai_model_module
sys.modules['nexent.core.models.embedding_model'] = MagicMock()
sys.modules['nexent.core.models.stt_model'] = MagicMock()
sys.modules['nexent.core.nlp'] = _create_package_mock('nexent.core.nlp')
sys.modules['nexent.core.nlp.tokenizer'] = MagicMock()
# Mock nexent.core.utils and observer module
sys.modules['nexent.core.utils'] = _create_package_mock('nexent.core.utils')
observer_module = ModuleType('nexent.core.utils.observer')
observer_module.MessageObserver = MagicMock
sys.modules['nexent.core.utils.observer'] = observer_module
sys.modules['nexent.vector_database'] = _create_package_mock(
    'nexent.vector_database')
vector_db_base_module = ModuleType('nexent.vector_database.base')


class _VectorDatabaseCore:
    """Lightweight stand-in for the real VectorDatabaseCore for import-time typing."""
    pass


vector_db_base_module.VectorDatabaseCore = _VectorDatabaseCore
sys.modules['nexent.vector_database.base'] = vector_db_base_module
sys.modules['nexent.vector_database.elasticsearch_core'] = MagicMock()
sys.modules['nexent.vector_database.datamate_core'] = MagicMock()
# Mock nexent.storage module and its submodules before any imports
sys.modules['nexent.storage'] = _create_package_mock('nexent.storage')
storage_factory_module = MagicMock()
storage_config_module = MagicMock()
# Create mock classes/functions that will be imported
MinIOStorageConfigMock = MagicMock()
MinIOStorageConfigMock.validate = lambda self: None
storage_factory_module.create_storage_client_from_config = MagicMock()
storage_factory_module.MinIOStorageConfig = MinIOStorageConfigMock
storage_config_module.MinIOStorageConfig = MinIOStorageConfigMock
sys.modules['nexent.storage.storage_client_factory'] = storage_factory_module
sys.modules['nexent.storage.minio_config'] = storage_config_module

# Mock specific classes that are imported
sys.modules['nexent.core.agents.agent_model'].ToolConfig = MagicMock()
sys.modules['nexent.core.models.stt_model'].STTConfig = MagicMock()
sys.modules['nexent.core.models.stt_model'].STTModel = MagicMock()
sys.modules['nexent.core.models.tts_model'] = MagicMock()
sys.modules['nexent.core.models.tts_model'].TTSConfig = MagicMock()
sys.modules['nexent.core.models.tts_model'].TTSModel = MagicMock()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
# Configure storage_client_mock.delete_file to return tuple (True, None)
storage_client_mock.delete_file.return_value = (True, None)
minio_client_mock = MagicMock()
# Configure default return values for minio_client_mock methods
minio_client_mock.delete_file.return_value = (True, None)
minio_client_mock.storage_config = MagicMock()
minio_client_mock.storage_config.default_bucket = 'test-bucket'
# Set _storage_client to storage_client_mock so MinioClient.delete_file works correctly
minio_client_mock._storage_client = storage_client_mock
patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate',
      lambda self: None).start()
patch('backend.database.client.MinioClient',
      return_value=minio_client_mock).start()
patch('backend.database.client.minio_client', minio_client_mock).start()
# Patch attachment_db.minio_client to use the same mock
# This ensures delete_file and other methods work correctly
patch('backend.database.attachment_db.minio_client', minio_client_mock).start()

# Apply the patches before importing the module being tested
with patch('botocore.client.BaseClient._make_api_call'), \
        patch('elasticsearch.Elasticsearch', return_value=MagicMock()):
    # Import utils.document_vector_utils to ensure it's available for patching
    import utils.document_vector_utils
    from backend.services.vectordatabase_service import ElasticSearchService, check_knowledge_base_exist_impl


def _accurate_search_impl(request, vdb_core):
    start_time = time.time()
    if not request.query or not request.query.strip():
        raise Exception("Search query cannot be empty")
    if not request.index_names:
        raise Exception("At least one index name is required")

    results = vdb_core.accurate_search(
        index_names=request.index_names,
        query=request.query,
        top_k=request.top_k
    )
    end_time = time.time()
    query_time_ms = (end_time - start_time) * 1000

    return {
        "results": results,
        "total": len(results),
        "query_time_ms": query_time_ms
    }


def _semantic_search_impl(request, vdb_core):
    start_time = time.time()
    results = vdb_core.semantic_search(
        index_names=request.index_names,
        query=request.query,
        top_k=request.top_k
    )
    end_time = time.time()
    query_time_ms = (end_time - start_time) * 1000

    return {
        "results": results,
        "total": len(results),
        "query_time_ms": query_time_ms
    }


class TestElasticSearchService(unittest.TestCase):
    def setUp(self):
        """
        Set up test environment before each test.

        This method initializes a fresh ElasticSearchService instance
        and prepares mock objects for the ES core and embedding model
        that will be used across test cases.
        """
        self.es_service = ElasticSearchService()
        self.mock_vdb_core = MagicMock()
        self.mock_vdb_core.embedding_model = MagicMock()
        self.mock_vdb_core.embedding_dim = 768

        # Patch get_embedding_model for all tests
        self.get_embedding_model_patcher = patch(
            'backend.services.vectordatabase_service.get_embedding_model')
        self.mock_get_embedding = self.get_embedding_model_patcher.start()
        self.mock_embedding = MagicMock()
        self.mock_embedding.embedding_dim = 768
        self.mock_embedding.model = "test-model"
        self.mock_get_embedding.return_value = self.mock_embedding

        ElasticSearchService.accurate_search = staticmethod(
            _accurate_search_impl)
        ElasticSearchService.semantic_search = staticmethod(
            _semantic_search_impl)

    def tearDown(self):
        """Clean up resources after each test."""
        self.get_embedding_model_patcher.stop()
        if hasattr(ElasticSearchService, 'accurate_search'):
            del ElasticSearchService.accurate_search
        if hasattr(ElasticSearchService, 'semantic_search'):
            del ElasticSearchService.semantic_search

    @patch('backend.services.vectordatabase_service.create_knowledge_record')
    def test_create_index_success(self, mock_create_knowledge):
        """
        Test successful index creation.

        This test verifies that:
        1. The index is created when it doesn't already exist
        2. The vector index is properly configured with the correct embedding dimension
        3. A knowledge record is created for the new index
        4. The method returns a success status
        """
        # Setup
        self.mock_vdb_core.check_index_exists.return_value = False
        self.mock_vdb_core.create_index.return_value = True
        mock_create_knowledge.return_value = True

        # Execute
        result = ElasticSearchService.create_index(
            index_name="test_index",
            embedding_dim=768,
            vdb_core=self.mock_vdb_core,
            user_id="test_user",
            tenant_id="test_tenant"  # Added explicit tenant_id
        )

        # Assert
        self.assertEqual(result["status"], "success")
        self.mock_vdb_core.check_index_exists.assert_called_once_with(
            "test_index")
        self.mock_vdb_core.create_index.assert_called_once_with(
            "test_index", embedding_dim=768)
        mock_create_knowledge.assert_called_once()

    @patch('backend.services.vectordatabase_service.create_knowledge_record')
    def test_create_index_already_exists(self, mock_create_knowledge):
        """
        Test index creation when the index already exists.

        This test verifies that:
        1. An Exception with status code 500 is raised when the index already exists
        2. The exception message contains "already exists"
        3. No knowledge record is created
        """
        # Setup
        self.mock_vdb_core.check_index_exists.return_value = True

        # Execute and Assert
        with self.assertRaises(Exception) as context:
            ElasticSearchService.create_index(
                index_name="test_index",
                embedding_dim=768,
                vdb_core=self.mock_vdb_core,
                user_id="test_user"
            )

        # Check the exception message
        self.assertIn("already exists", str(context.exception))
        mock_create_knowledge.assert_not_called()

    @patch('backend.services.vectordatabase_service.create_knowledge_record')
    def test_create_knowledge_base_generates_index(self, mock_create_knowledge):
        """Ensure create_knowledge_base creates record then ES index."""
        self.mock_vdb_core.create_index.return_value = True
        mock_create_knowledge.return_value = {
            "knowledge_id": 7,
            "index_name": "7-uuid",
            "knowledge_name": "kb1",
        }

        result = ElasticSearchService.create_knowledge_base(
            knowledge_name="kb1",
            embedding_dim=256,
            vdb_core=self.mock_vdb_core,
            user_id="user-1",
            tenant_id="tenant-1",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["knowledge_id"], 7)
        self.assertEqual(result["id"], "7-uuid")
        self.mock_vdb_core.create_index.assert_called_once_with(
            "7-uuid", embedding_dim=256
        )

    @patch('backend.services.vectordatabase_service.create_knowledge_record')
    def test_create_knowledge_base_with_group_permissions(self, mock_create_knowledge):
        """
        Test create_knowledge_base with group permissions.

        Verifies that ingroup_permission and group_ids are correctly
        passed to the knowledge record creation.
        """
        self.mock_vdb_core.create_index.return_value = True
        mock_create_knowledge.return_value = {
            "knowledge_id": 7,
            "index_name": "7-uuid",
            "knowledge_name": "kb1",
        }

        result = ElasticSearchService.create_knowledge_base(
            knowledge_name="kb1",
            embedding_dim=256,
            vdb_core=self.mock_vdb_core,
            user_id="user-1",
            tenant_id="tenant-1",
            ingroup_permission="EDIT",
            group_ids=[1, 2, 3],
        )

        self.assertEqual(result["status"], "success")
        # Verify that create_knowledge_record was called with group permissions
        mock_create_knowledge.assert_called_once()
        # Parameters are passed as positional argument (knowledge_data dict), not keyword args
        call_kwargs = mock_create_knowledge.call_args[0][0]
        self.assertEqual(call_kwargs["ingroup_permission"], "EDIT")
        self.assertEqual(call_kwargs["group_ids"], [1, 2, 3])

    @patch('backend.services.vectordatabase_service.create_knowledge_record')
    def test_create_knowledge_base_with_partial_group_permissions(self, mock_create_knowledge):
        """
        Test create_knowledge_base with only ingroup_permission (no group_ids).

        Verifies that the method handles partial group permissions correctly.
        """
        self.mock_vdb_core.create_index.return_value = True
        mock_create_knowledge.return_value = {
            "knowledge_id": 8,
            "index_name": "8-uuid2",
            "knowledge_name": "kb2",
        }

        result = ElasticSearchService.create_knowledge_base(
            knowledge_name="kb2",
            embedding_dim=256,
            vdb_core=self.mock_vdb_core,
            user_id="user-1",
            tenant_id="tenant-1",
            ingroup_permission="READ_ONLY",
            # group_ids not provided
        )

        self.assertEqual(result["status"], "success")
        mock_create_knowledge.assert_called_once()
        # Parameters are passed as positional argument (knowledge_data dict), not keyword args
        call_kwargs = mock_create_knowledge.call_args[0][0]
        self.assertEqual(call_kwargs["ingroup_permission"], "READ_ONLY")
        # group_ids should not be in the call if not provided
        self.assertNotIn("group_ids", call_kwargs)

    @patch('backend.services.vectordatabase_service.create_knowledge_record')
    def test_create_knowledge_base_with_empty_group_ids(self, mock_create_knowledge):
        """
        Test create_knowledge_base with empty group_ids list.

        Verifies that an empty list of group_ids is passed correctly.
        """
        self.mock_vdb_core.create_index.return_value = True
        mock_create_knowledge.return_value = {
            "knowledge_id": 9,
            "index_name": "9-uuid3",
            "knowledge_name": "kb3",
        }

        result = ElasticSearchService.create_knowledge_base(
            knowledge_name="kb3",
            embedding_dim=256,
            vdb_core=self.mock_vdb_core,
            user_id="user-1",
            tenant_id="tenant-1",
            ingroup_permission="PRIVATE",
            group_ids=[],
        )

        self.assertEqual(result["status"], "success")
        mock_create_knowledge.assert_called_once()
        # Parameters are passed as positional argument (knowledge_data dict), not keyword args
        call_kwargs = mock_create_knowledge.call_args[0][0]
        self.assertEqual(call_kwargs["ingroup_permission"], "PRIVATE")
        self.assertEqual(call_kwargs["group_ids"], [])

    @patch('backend.services.vectordatabase_service.create_knowledge_record')
    def test_create_index_failure(self, mock_create_knowledge):
        """
        Test index creation failure.

        This test verifies that:
        1. An Exception with status code 500 is raised when index creation fails
        2. The exception message contains "Failed to create index"
        3. No knowledge record is created
        """
        # Setup
        self.mock_vdb_core.check_index_exists.return_value = False
        self.mock_vdb_core.create_index.return_value = False

        # Execute and Assert
        with self.assertRaises(Exception) as context:
            ElasticSearchService.create_index(
                index_name="test_index",
                embedding_dim=768,
                vdb_core=self.mock_vdb_core,
                user_id="test_user",
                tenant_id="test_tenant"  # Added explicit tenant_id
            )

        self.assertIn("Failed to create index", str(context.exception))
        mock_create_knowledge.assert_not_called()

    @patch('backend.services.vectordatabase_service.delete_knowledge_record')
    def test_delete_index_success(self, mock_delete_knowledge):
        """
        Test successful index deletion.

        This test verifies that:
        1. The index is successfully deleted from Elasticsearch
        2. The corresponding knowledge record is deleted
        3. The method returns a success status
        """
        # Setup
        self.mock_vdb_core.delete_index.return_value = True
        mock_delete_knowledge.return_value = True

        # Execute
        async def run_test():
            result = await ElasticSearchService.delete_index(
                index_name="test_index",
                vdb_core=self.mock_vdb_core,
                user_id="test_user"
            )

            # Assert
            self.assertEqual(result["status"], "success")
            self.mock_vdb_core.delete_index.assert_called_once_with(
                "test_index")
            mock_delete_knowledge.assert_called_once()

        asyncio.run(run_test())

    @patch('backend.services.vectordatabase_service.delete_knowledge_record')
    def test_delete_index_failure(self, mock_delete_knowledge):
        """
        Test index deletion failure.

        This test verifies that:
        1. When index deletion fails, the method still proceeds with knowledge record deletion
        2. The method returns success status if knowledge record deletion succeeds
        """
        # Setup
        self.mock_vdb_core.delete_index.return_value = False
        mock_delete_knowledge.return_value = True

        # Execute
        async def run_test():
            result = await ElasticSearchService.delete_index(
                index_name="test_index",
                vdb_core=self.mock_vdb_core,
                user_id="test_user"
            )

            # Assert
            self.assertEqual(result["status"], "success")
            self.mock_vdb_core.delete_index.assert_called_once_with(
                "test_index")
            mock_delete_knowledge.assert_called_once()

        asyncio.run(run_test())

    @patch('backend.services.vectordatabase_service.delete_knowledge_record')
    def test_delete_index_knowledge_record_failure(self, mock_delete_knowledge):
        """
        Test deletion when the index is deleted but knowledge record deletion fails.

        This test verifies that:
        1. When Elasticsearch index is deleted successfully but knowledge record deletion fails
        2. An Exception with status code 500 is raised
        3. The exception message contains "Error deleting knowledge record"
        """
        # Setup
        self.mock_vdb_core.delete_index.return_value = True
        mock_delete_knowledge.return_value = False

        # Execute and Assert
        async def run_test():
            with self.assertRaises(Exception) as context:
                await ElasticSearchService.delete_index(
                    index_name="test_index",
                    vdb_core=self.mock_vdb_core,
                    user_id="test_user"
                )

            self.assertIn("Error deleting knowledge record",
                          str(context.exception))

        asyncio.run(run_test())

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_without_stats(self, mock_get_knowledge, mock_get_user_tenant, mock_get_group_ids):
        """
        Test listing indices without including statistics.

        This test verifies that:
        1. The method retrieves indices matching the pattern
        2. The correct number of indices is returned
        3. No statistics are requested when include_stats is False
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1", "index2"]
        mock_get_knowledge.return_value = [
            {"index_name": "index1",
                "embedding_model_name": "test-model", "group_ids": "1,2", "knowledge_sources": "elasticsearch", "ingroup_permission": "EDIT", "tenant_id": "test_tenant"},
            {"index_name": "index2", "embedding_model_name": "test-model",
                "group_ids": "", "knowledge_sources": "elasticsearch", "ingroup_permission": "READ_ONLY", "tenant_id": "test_tenant"}
        ]
        mock_get_user_tenant.return_value = {
            "user_role": "SU", "tenant_id": "test_tenant"}
        mock_get_group_ids.return_value = []

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=False,
            target_tenant_id="test_tenant",  # Now required parameter
            user_id="test_user",  # New required parameter
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(len(result["indices"]), 2)
        self.assertEqual(result["count"], 2)
        self.mock_vdb_core.get_user_indices.assert_called_once_with("*")
        mock_get_knowledge.assert_called_once_with("test_tenant")

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_with_stats(self, mock_get_knowledge, mock_get_user_tenant, mock_get_group_ids):
        """
        Test listing indices with statistics included.

        This test verifies that:
        1. The method retrieves indices matching the pattern
        2. Statistics for each index are also retrieved
        3. Both indices and their stats are included in the response
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1", "index2"]
        self.mock_vdb_core.get_indices_detail.return_value = {
            "index1": {"base_info": {"doc_count": 10, "embedding_model": "test-model"}},
            "index2": {"base_info": {"doc_count": 20, "embedding_model": "test-model"}}
        }
        mock_get_knowledge.return_value = [
            {"index_name": "index1",
                "embedding_model_name": "test-model", "group_ids": "1,2", "knowledge_sources": "elasticsearch", "ingroup_permission": "EDIT", "tenant_id": "test_tenant"},
            {"index_name": "index2", "embedding_model_name": "test-model",
                "group_ids": "", "knowledge_sources": "elasticsearch", "ingroup_permission": "READ_ONLY", "tenant_id": "test_tenant"}
        ]
        mock_get_user_tenant.return_value = {
            "user_role": "SU", "tenant_id": "test_tenant"}
        mock_get_group_ids.return_value = []

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=True,
            target_tenant_id="test_tenant",  # Now required parameter
            user_id="test_user",  # New required parameter
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(len(result["indices"]), 2)
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["indices_info"]), 2)

        # Verify group_ids are included and correctly parsed
        self.assertEqual(result["indices_info"][0]["group_ids"], [1, 2])
        self.assertEqual(result["indices_info"][1]["group_ids"], [])

        self.mock_vdb_core.get_user_indices.assert_called_once_with("*")
        self.mock_vdb_core.get_indices_detail.assert_called_once_with(
            ["index1", "index2"])
        mock_get_knowledge.assert_called_once_with("test_tenant")

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_skips_missing_indices(self, mock_get_info, mock_get_user_tenant, mock_get_group_ids):
        """
        Test that list_indices skips indices that exist in database but not in Elasticsearch.
        """
        self.mock_vdb_core.get_user_indices.return_value = ["es_index"]
        mock_get_info.return_value = [
            {"index_name": "dangling_index",
                "embedding_model_name": "model-A", "group_ids": "1", "knowledge_sources": "elasticsearch", "ingroup_permission": "EDIT", "tenant_id": "tenant-1"}
        ]
        mock_get_user_tenant.return_value = {
            "user_role": "SU", "tenant_id": "tenant-1"}
        mock_get_group_ids.return_value = []

        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=False,
            target_tenant_id="tenant-1",
            user_id="user-1",
            vdb_core=self.mock_vdb_core
        )

        # Should skip the dangling index and return empty result
        self.assertEqual(result["indices"], [])
        self.assertEqual(result["count"], 0)

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_stats_defaults_when_missing(self, mock_get_info, mock_get_user_tenant, mock_get_group_ids):
        """
        Test list_indices include_stats path when Elasticsearch returns no stats for an index.
        """
        self.mock_vdb_core.get_user_indices.return_value = ["index1"]
        mock_get_info.return_value = [
            {"index_name": "index1", "embedding_model_name": "model-A",
                "group_ids": "1,2", "knowledge_sources": "elasticsearch", "ingroup_permission": "EDIT", "tenant_id": "tenant-1"}
        ]
        self.mock_vdb_core.get_indices_detail.return_value = {}
        mock_get_user_tenant.return_value = {
            "user_role": "SU", "tenant_id": "tenant-1"}
        mock_get_group_ids.return_value = []

        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=True,
            target_tenant_id="tenant-1",
            user_id="user-1",
            vdb_core=self.mock_vdb_core
        )

        self.assertEqual(result["indices"], ["index1"])
        self.assertEqual(result["indices_info"][0]["name"], "index1")
        self.assertEqual(result["indices_info"][0]["stats"], {})

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.update_model_name_by_index_name')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_backfills_missing_model_names(self, mock_get_info, mock_update_model, mock_get_user_tenant, mock_get_group_ids):
        """
        Test that list_indices updates database records when embedding_model_name is missing.
        """
        self.mock_vdb_core.get_user_indices.return_value = ["index1"]
        mock_get_info.return_value = [
            {"index_name": "index1", "embedding_model_name": None,
                "knowledge_sources": "elasticsearch", "ingroup_permission": "EDIT", "tenant_id": "tenant-1"}
        ]
        self.mock_vdb_core.get_indices_detail.return_value = {
            "index1": {"base_info": {"embedding_model": "text-embedding-ada-002"}}
        }
        mock_get_user_tenant.return_value = {
            "user_role": "SU", "tenant_id": "tenant-1"}
        mock_get_group_ids.return_value = []

        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=True,
            target_tenant_id="tenant-1",
            user_id="user-1",
            vdb_core=self.mock_vdb_core
        )

        mock_update_model.assert_called_once_with(
            "index1", "text-embedding-ada-002", "tenant-1", "user-1"
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["indices"][0], "index1")

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_stats_surfaces_elasticsearch_errors(self, mock_get_info, mock_get_user_tenant, mock_get_group_ids):
        """
        Test that list_indices propagates Elasticsearch errors while fetching stats.
        """
        self.mock_vdb_core.get_user_indices.return_value = ["index1"]
        mock_get_info.return_value = [
            {"index_name": "index1", "embedding_model_name": "model-A",
                "group_ids": "1,2", "knowledge_sources": "elasticsearch", "ingroup_permission": "EDIT", "tenant_id": "tenant-1"}
        ]
        self.mock_vdb_core.get_indices_detail.side_effect = Exception(
            "503 Service Unavailable"
        )
        mock_get_user_tenant.return_value = {
            "user_role": "SU", "tenant_id": "tenant-1"}
        mock_get_group_ids.return_value = []

        with self.assertRaises(Exception) as context:
            ElasticSearchService.list_indices(
                pattern="*",
                include_stats=True,
                target_tenant_id="tenant-1",
                user_id="user-1",
                vdb_core=self.mock_vdb_core
            )

        self.assertIn("503 Service Unavailable", str(context.exception))

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_stats_keeps_non_stat_fields(self, mock_get_info, mock_get_user_tenant, mock_get_group_ids):
        """
        Test that list_indices preserves all stats fields returned by ElasticSearchCore.
        """
        self.mock_vdb_core.get_user_indices.return_value = ["index1"]
        mock_get_info.return_value = [
            {"index_name": "index1", "embedding_model_name": "model-A",
                "group_ids": "1,2", "knowledge_sources": "elasticsearch", "ingroup_permission": "EDIT", "tenant_id": "tenant-1"}
        ]
        detailed_stats = {
            "index1": {
                "base_info": {
                    "doc_count": 42,
                    "process_source": "Unstructured",
                    "embedding_model": "text-embedding-3-large"
                },
                "search_performance": {"avg_time": 12.3}
            }
        }
        self.mock_vdb_core.get_indices_detail.return_value = detailed_stats
        mock_get_user_tenant.return_value = {
            "user_role": "SU", "tenant_id": "tenant-1"}
        mock_get_group_ids.return_value = []

        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=True,
            target_tenant_id="tenant-1",
            user_id="user-1",
            vdb_core=self.mock_vdb_core
        )

        self.assertEqual(len(result["indices_info"]), 1)
        self.assertEqual(result["indices_info"][0]
                         ["stats"], detailed_stats["index1"])

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_creator_permission(self, mock_get_knowledge, mock_get_user_tenant, mock_get_group_ids):
        """
        Test that creator of a knowledge base gets CREATOR permission.

        This test verifies that:
        1. When user is the creator of a knowledge base, they get CREATOR permission
        2. When user is not the creator, they don't get CREATOR permission
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1", "index2"]
        mock_get_knowledge.return_value = [
            {
                "index_name": "index1",
                "embedding_model_name": "test-model",
                "group_ids": "1",
                "created_by": "test_user",  # User is creator
                "ingroup_permission": "READ_ONLY",
                "tenant_id": "test_tenant",
                "knowledge_sources": "elasticsearch"
            },
            {
                "index_name": "index2",
                "embedding_model_name": "test-model",
                "group_ids": "1",
                "created_by": "other_user",  # User is not creator
                "ingroup_permission": "EDIT",
                "tenant_id": "test_tenant",
                "knowledge_sources": "elasticsearch"
            }
        ]
        mock_get_user_tenant.return_value = {
            "user_role": "USER", "tenant_id": "test_tenant"}
        mock_get_group_ids.return_value = [1]

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=False,
            target_tenant_id="test_tenant",
            user_id="test_user",
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(len(result["indices"]), 2)
        self.assertEqual(result["count"], 2)

        # When include_stats=False, indices is just a list of names
        # When include_stats=True, indices_info contains the detailed info with permissions
        self.assertIn("index1", result["indices"])
        self.assertIn("index2", result["indices"])

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_permission_edit_when_not_creator(self, mock_get_knowledge, mock_get_user_tenant, mock_get_group_ids):
        """
        Test that non-creator user gets EDIT permission when ingroup_permission is EDIT.

        This test verifies that:
        1. When user is not the creator but has group intersection
        2. And ingroup_permission is EDIT, user gets EDIT permission
        3. This covers line 611-612
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1"]
        self.mock_vdb_core.get_indices_detail.return_value = {
            "index1": {"base_info": {"doc_count": 10, "embedding_model": "test-model"}}
        }
        mock_get_knowledge.return_value = [
            {
                "index_name": "index1",
                "embedding_model_name": "test-model",
                "group_ids": "1,2",
                "created_by": "other_user",  # User is NOT creator
                "ingroup_permission": "EDIT",  # EDIT permission
                "tenant_id": "test_tenant",
                "knowledge_sources": "elasticsearch"
            }
        ]
        mock_get_user_tenant.return_value = {
            "user_role": "USER", "tenant_id": "test_tenant"}
        mock_get_group_ids.return_value = [1]  # User belongs to group 1

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=True,  # Need stats to see permissions
            target_tenant_id="test_tenant",
            user_id="test_user",
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(len(result["indices_info"]), 1)
        self.assertEqual(result["indices_info"][0]["permission"], "EDIT")

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    @patch('backend.services.vectordatabase_service.IS_SPEED_MODE', new=False)
    def test_list_indices_permission_read_when_not_creator(self, mock_get_knowledge, mock_get_user_tenant, mock_get_group_ids):
        """
        Test that non-creator user gets READ_ONLY permission when ingroup_permission is READ_ONLY.

        This test verifies that:
        1. When user is not the creator but has group intersection
        2. And ingroup_permission is READ_ONLY, user gets READ_ONLY permission
        3. This covers line 614-615
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1"]
        self.mock_vdb_core.get_indices_detail.return_value = {
            "index1": {"base_info": {"doc_count": 10, "embedding_model": "test-model"}}
        }
        mock_get_knowledge.return_value = [
            {
                "index_name": "index1",
                "embedding_model_name": "test-model",
                "group_ids": "1,2",
                "created_by": "other_user",  # User is NOT creator
                "ingroup_permission": "READ_ONLY",  # READ_ONLY permission
                "tenant_id": "test_tenant",
                "knowledge_sources": "elasticsearch"
            }
        ]
        mock_get_user_tenant.return_value = {
            "user_role": "USER", "tenant_id": "test_tenant"}
        mock_get_group_ids.return_value = [1]  # User belongs to group 1

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=True,  # Need stats to see permissions
            target_tenant_id="test_tenant",
            user_id="test_user",
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(len(result["indices_info"]), 1)
        self.assertEqual(result["indices_info"][0]["permission"], "READ_ONLY")

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    @patch('backend.services.vectordatabase_service.IS_SPEED_MODE', new=False)
    def test_list_indices_permission_default_read_when_not_creator(self, mock_get_knowledge, mock_get_user_tenant, mock_get_group_ids):
        """
        Test that non-creator user gets default READ_ONLY permission when ingroup_permission is None or other value.

        This test verifies that:
        1. When user is not the creator but has group intersection
        2. And ingroup_permission is None or not EDIT/READ_ONLY/PRIVATE, user gets default READ_ONLY permission
        3. This covers line 605
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1"]
        self.mock_vdb_core.get_indices_detail.return_value = {
            "index1": {"base_info": {"doc_count": 10, "embedding_model": "test-model"}}
        }
        mock_get_knowledge.return_value = [
            {
                "index_name": "index1",
                "embedding_model_name": "test-model",
                "group_ids": "1,2",
                "created_by": "other_user",  # User is NOT creator
                "ingroup_permission": None,  # None permission (will default to READ_ONLY)
                "tenant_id": "test_tenant",
                "knowledge_sources": "elasticsearch"
            }
        ]
        mock_get_user_tenant.return_value = {
            "user_role": "USER", "tenant_id": "test_tenant"}
        mock_get_group_ids.return_value = [1]  # User belongs to group 1

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=True,  # Need stats to see permissions
            target_tenant_id="test_tenant",
            user_id="test_user",
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(len(result["indices_info"]), 1)
        # When ingroup_permission is None, it defaults to READ_ONLY (line 584)
        # Then line 605 sets permission = PERMISSION_READ (which is "READ_ONLY")
        self.assertEqual(result["indices_info"][0]["permission"], "READ_ONLY")

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_kb_group_ids_none(self, mock_get_knowledge, mock_get_user_tenant, mock_get_group_ids):
        """
        Test that list_indices handles kb_group_ids_str as None correctly.

        This test verifies that:
        1. When kb_group_ids_str is None, kb_groups_empty is correctly calculated
        2. This covers line 591 (None branch)
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1"]
        self.mock_vdb_core.get_indices_detail.return_value = {
            "index1": {"base_info": {"doc_count": 10, "embedding_model": "test-model"}}
        }
        mock_get_knowledge.return_value = [
            {
                "index_name": "index1",
                "embedding_model_name": "test-model",
                "group_ids": None,  # None value to test line 591
                "created_by": "other_user",
                "ingroup_permission": "EDIT",
                "tenant_id": "test_tenant",
                "knowledge_sources": "elasticsearch"
            }
        ]
        mock_get_user_tenant.return_value = {
            "user_role": "USER", "tenant_id": "test_tenant"}
        mock_get_group_ids.return_value = []  # Empty user groups

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=True,
            target_tenant_id="test_tenant",
            user_id="test_user",
            vdb_core=self.mock_vdb_core
        )

        # Assert
        # When both kb_group_ids and user_group_ids are empty/None, they are considered intersecting
        # So the knowledge base should be visible
        self.assertEqual(len(result["indices_info"]), 1)
        self.assertEqual(result["indices_info"][0]["permission"], "EDIT")

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_kb_group_ids_empty_string(self, mock_get_knowledge, mock_get_user_tenant, mock_get_group_ids):
        """
        Test that list_indices handles kb_group_ids_str as empty string correctly.

        This test verifies that:
        1. When kb_group_ids_str is empty string, kb_groups_empty is correctly calculated
        2. This covers line 591 (empty string branch)
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1"]
        self.mock_vdb_core.get_indices_detail.return_value = {
            "index1": {"base_info": {"doc_count": 10, "embedding_model": "test-model"}}
        }
        mock_get_knowledge.return_value = [
            {
                "index_name": "index1",
                "embedding_model_name": "test-model",
                "group_ids": "",  # Empty string to test line 591
                "created_by": "other_user",
                "ingroup_permission": "EDIT",
                "tenant_id": "test_tenant",
                "knowledge_sources": "elasticsearch"
            }
        ]
        mock_get_user_tenant.return_value = {
            "user_role": "USER", "tenant_id": "test_tenant"}
        mock_get_group_ids.return_value = []  # Empty user groups

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=True,
            target_tenant_id="test_tenant",
            user_id="test_user",
            vdb_core=self.mock_vdb_core
        )

        # Assert
        # When both kb_group_ids and user_group_ids are empty, they are considered intersecting
        self.assertEqual(len(result["indices_info"]), 1)
        self.assertEqual(result["indices_info"][0]["permission"], "EDIT")

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_fallback_admin_logic(self, mock_get_knowledge, mock_get_user_tenant, mock_get_group_ids):
        """
        Test the fallback admin logic when user_id equals tenant_id.

        This test verifies that:
        1. When user_id equals tenant_id, user is treated as legacy admin regardless of user_role
        2. Legacy admin gets EDIT permission on all knowledgebases in their tenant
        3. Debug log is recorded for legacy admin identification
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1", "index2"]
        mock_get_knowledge.return_value = [
            {
                "index_name": "index1",
                "embedding_model_name": "test-model",
                "group_ids": "1,2",
                "tenant_id": "legacy_admin_user",  # Same as user_id
                "knowledge_sources": "elasticsearch",
                "ingroup_permission": "EDIT"
            },
            {
                "index_name": "index2",
                "embedding_model_name": "test-model",
                "group_ids": "3",
                "tenant_id": "legacy_admin_user",  # Same as user_id
                "knowledge_sources": "elasticsearch",
                "ingroup_permission": "EDIT"
            }
        ]
        # user_role is None to test fallback logic
        mock_get_user_tenant.return_value = {
            "user_role": None, "tenant_id": "legacy_admin_user"}
        mock_get_group_ids.return_value = []

        # Execute
        with patch('backend.services.vectordatabase_service.logger') as mock_logger:
            result = ElasticSearchService.list_indices(
                pattern="*",
                include_stats=True,  # Need stats to see permissions
                target_tenant_id="legacy_admin_user",
                user_id="legacy_admin_user",  # user_id equals tenant_id
                vdb_core=self.mock_vdb_core
            )

        # Assert
        self.assertEqual(len(result["indices"]), 2)
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["indices_info"]), 2)

        # Both knowledgebases should have EDIT permission due to legacy admin fallback
        for kb_info in result["indices_info"]:
            self.assertEqual(kb_info["permission"], "EDIT")

        # Verify info log was called once for each index for legacy admin identification
        mock_logger.info.assert_has_calls([
            call("User legacy_admin_user identified as legacy admin"),
            call("User legacy_admin_user identified as legacy admin")
        ])

    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    def test_list_indices_speed_version_admin_logic(self, mock_get_group_ids, mock_get_user_tenant, mock_get_knowledge):
        """
        Test the SPEED version admin logic when user is default user and tenant is default tenant.

        This test verifies that:
        1. When user_id equals DEFAULT_USER_ID and tenant_id equals DEFAULT_TENANT_ID, user is treated as admin
        2. SPEED version admin gets EDIT permission on all knowledgebases in their tenant
        3. Info log is recorded for SPEED version admin identification
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1", "index2"]
        mock_get_knowledge.return_value = [
            {
                "index_name": "index1",
                "embedding_model_name": "test-model",
                "group_ids": "1,2",
                "tenant_id": "tenant_id",  # DEFAULT_TENANT_ID
                "knowledge_sources": "elasticsearch",
                "ingroup_permission": "EDIT"
            },
            {
                "index_name": "index2",
                "embedding_model_name": "test-model",
                "group_ids": "3",
                "tenant_id": "tenant_id",  # DEFAULT_TENANT_ID
                "knowledge_sources": "elasticsearch",
                "ingroup_permission": "EDIT"
            }
        ]
        # Use legacy admin logic: user_id equals tenant_id
        mock_get_user_tenant.return_value = {
            "user_role": "USER", "tenant_id": "user_id"}  # tenant_id equals user_id for legacy admin
        mock_get_group_ids.return_value = []

        # Execute
        with patch('backend.services.vectordatabase_service.logger') as mock_logger:
            result = ElasticSearchService.list_indices(
                pattern="*",
                include_stats=True,  # Need stats to see permissions
                target_tenant_id="user_id",  # DEFAULT_TENANT_ID (same as user_id for legacy admin)
                user_id="user_id",  # DEFAULT_USER_ID
                vdb_core=self.mock_vdb_core
            )

        # Assert
        self.assertEqual(len(result["indices"]), 2)
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["indices_info"]), 2)

        # Both knowledgebases should have EDIT permission due to legacy admin logic
        for kb_info in result["indices_info"]:
            self.assertEqual(kb_info["permission"], "EDIT")

        # Verify info log was called once for each index for legacy admin identification
        mock_logger.info.assert_has_calls([
            call("User user_id identified as legacy admin"),
            call("User user_id identified as legacy admin")
        ])

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_skips_datamate_sources(self, mock_get_knowledge, mock_get_user_tenant, mock_get_group_ids):
        """
        Test that list_indices skips records with knowledge_sources='datamate'.

        This test verifies that:
        1. Records with knowledge_sources='datamate' are skipped and not included in results
        2. Records with knowledge_sources='elasticsearch' are included in results
        3. Only non-datamate knowledgebases are visible to users
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1", "index2", "index3"]
        mock_get_knowledge.return_value = [
            {
                "index_name": "index1",
                "embedding_model_name": "test-model",
                "group_ids": "1,2",
                "created_by": "test_user",
                "ingroup_permission": "READ_ONLY",
                "tenant_id": "test_tenant",
                "knowledge_sources": "elasticsearch"  # Should be included
            },
            {
                "index_name": "index2",
                "embedding_model_name": "test-model",
                "group_ids": "1",
                "created_by": "test_user",
                "ingroup_permission": "EDIT",
                "tenant_id": "test_tenant",
                "knowledge_sources": "datamate"  # Should be skipped
            },
            {
                "index_name": "index3",
                "embedding_model_name": "test-model",
                "group_ids": "2",
                "created_by": "other_user",
                "ingroup_permission": "READ_ONLY",
                "tenant_id": "test_tenant",
                "knowledge_sources": "elasticsearch"  # Should be included
            }
        ]
        mock_get_user_tenant.return_value = {
            "user_role": "USER", "tenant_id": "test_tenant"}
        mock_get_group_ids.return_value = [1, 2]

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=False,
            target_tenant_id="test_tenant",
            user_id="test_user",
            vdb_core=self.mock_vdb_core
        )

        # Assert
        # Only index1 and index3 should be included (index2 with datamate should be skipped)
        self.assertEqual(len(result["indices"]), 2)
        self.assertEqual(result["count"], 2)
        self.assertIn("index1", result["indices"])
        self.assertNotIn("index2", result["indices"])  # datamate source should be excluded
        self.assertIn("index3", result["indices"])

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_uses_tenant_id_for_filtering(self, mock_get_knowledge, mock_get_user_tenant, mock_get_group_ids):
        """
        Test that list_indices uses tenant_id for filtering knowledge bases.

        This test verifies that:
        1. The method filters knowledge bases by the tenant_id parameter
        2. Only knowledge bases belonging to the target tenant are returned
        3. The user's tenant_id from auth is used for permission checking, not for filtering
        """
        # Setup - Simulate user from tenant_A querying for tenant_B's knowledge bases
        self.mock_vdb_core.get_user_indices.return_value = [
            "kb1", "kb2", "kb3"]
        mock_get_knowledge.return_value = [
            {
                "index_name": "kb1",
                "embedding_model_name": "test-model",
                "group_ids": "",
                "created_by": "user1",
                "ingroup_permission": "READ_ONLY",
                "tenant_id": "tenant_B",  # Belongs to tenant_B
                "knowledge_sources": "elasticsearch"
            },
            {
                "index_name": "kb2",
                "embedding_model_name": "test-model",
                "group_ids": "",
                "created_by": "user2",
                "ingroup_permission": "EDIT",
                "tenant_id": "tenant_B",  # Belongs to tenant_B
                "knowledge_sources": "elasticsearch"
            },
            {
                "index_name": "kb3",
                "embedding_model_name": "test-model",
                "group_ids": "",
                "created_by": "user3",
                "ingroup_permission": "READ_ONLY",
                "tenant_id": "tenant_C",  # Should be filtered out
                "knowledge_sources": "elasticsearch"
            }
        ]
        # User belongs to tenant_A
        mock_get_user_tenant.return_value = {
            "user_role": "ADMIN", "tenant_id": "tenant_A"}
        mock_get_group_ids.return_value = []

        # Execute - Querying for tenant_B's knowledge bases
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=False,
            target_tenant_id="tenant_B",  # Querying for tenant_B
            user_id="admin_user",  # User from tenant_A
            vdb_core=self.mock_vdb_core
        )

        # Assert
        # The mock returns all records without filtering by tenant_id
        # So all 3 indices are returned (the filtering is expected to happen in the DB function)
        self.assertEqual(len(result["indices"]), 3)
        self.assertEqual(result["count"], 3)
        self.assertIn("kb1", result["indices"])
        self.assertIn("kb2", result["indices"])
        self.assertIn("kb3", result["indices"])

        # Verify that get_knowledge_info_by_tenant_id was called with tenant_id
        mock_get_knowledge.assert_called_once_with("tenant_B")

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    def test_list_indices_includes_tenant_id_in_response(self, mock_get_knowledge, mock_get_user_tenant, mock_get_group_ids):
        """
        Test that list_indices includes tenant_id in the indices_info response.

        This test verifies that:
        1. Each knowledge base in indices_info includes the tenant_id field
        2. The tenant_id matches the tenant_id used for filtering
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["kb1"]
        self.mock_vdb_core.get_indices_detail.return_value = {
            "kb1": {"base_info": {"doc_count": 5, "embedding_model": "test-model"}}
        }
        mock_get_knowledge.return_value = [
            {
                "index_name": "kb1",
                "embedding_model_name": "test-model",
                "group_ids": "",
                "created_by": "user1",
                "ingroup_permission": "EDIT",
                "tenant_id": "tenant_X",
                "knowledge_sources": "elasticsearch",
                "update_time": "2024-01-15T10:30:00"
            }
        ]
        mock_get_user_tenant.return_value = {
            "user_role": "ADMIN", "tenant_id": "tenant_X"}
        mock_get_group_ids.return_value = []

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=True,
            target_tenant_id="tenant_X",
            user_id="admin_user",
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(len(result["indices_info"]), 1)
        self.assertEqual(result["indices_info"][0]["tenant_id"], "tenant_X")
        self.assertEqual(result["indices_info"][0]["name"], "kb1")
        # Verify update_time is included in response
        self.assertEqual(result["indices_info"][0]
                         ["update_time"], "2024-01-15T10:30:00")

    def test_vectorize_documents_success(self):
        """
        Test successful document indexing.

        This test verifies that:
        1. Documents are properly indexed when the index exists
        2. The indexing operation returns the correct count of indexed documents
        3. The response contains proper success status and document counts
        4. Documents with various metadata fields are handled correctly
        """
        # Setup
        self.mock_vdb_core.check_index_exists.return_value = True
        self.mock_vdb_core.vectorize_documents.return_value = 2
        mock_embedding_model = MagicMock()
        mock_embedding_model.model = "test-model"
        with patch('backend.services.vectordatabase_service.get_knowledge_record') as mock_get_record, \
                patch('backend.services.vectordatabase_service.tenant_config_manager') as mock_tenant_cfg:
            mock_get_record.return_value = {"tenant_id": "tenant-1"}
            mock_tenant_cfg.get_model_config.return_value = {"chunk_batch": 5}

            test_data = [
                {
                    "metadata": {
                        "title": "Test Document",
                        "languages": ["en"],
                        "author": "Test Author",
                        "date": "2023-01-01",
                        "creation_date": "2023-01-01T12:00:00"
                    },
                    "path_or_url": "test_path",
                    "content": "Test content",
                    "source_type": "file",
                    "file_size": 1024,
                    "filename": "test.txt"
                },
                {
                    "metadata": {
                        "title": "Test Document 2"
                    },
                    "path_or_url": "test_path2",
                    "content": "Test content 2"
                }
            ]

            # Execute
            result = ElasticSearchService.index_documents(
                index_name="test_index",
                data=test_data,
                vdb_core=self.mock_vdb_core,
                embedding_model=mock_embedding_model
            )

            # Assert
            self.assertTrue(result["success"])
            self.assertEqual(result["total_indexed"], 2)
            self.assertEqual(result["total_submitted"], 2)
            self.mock_vdb_core.vectorize_documents.assert_called_once()
            _, kwargs = self.mock_vdb_core.vectorize_documents.call_args
            self.assertEqual(kwargs.get("embedding_batch_size"), 5)
            self.assertTrue(callable(kwargs.get("progress_callback")))

    def test_vectorize_documents_empty_data(self):
        """
        Test document indexing with empty data.

        This test verifies that:
        1. When no documents are provided, the method handles it gracefully
        2. No documents are indexed when the data list is empty
        3. The response correctly indicates success with zero documents
        """
        # Setup
        test_data = []
        mock_embedding_model = MagicMock()

        # Execute
        result = ElasticSearchService.index_documents(
            index_name="test_index",
            data=test_data,
            vdb_core=self.mock_vdb_core,
            embedding_model=mock_embedding_model
        )

        # Assert
        self.assertTrue(result["success"])
        self.assertEqual(result["total_indexed"], 0)
        self.assertEqual(result["total_submitted"], 0)
        self.mock_vdb_core.vectorize_documents.assert_not_called()

    def test_vectorize_documents_create_index(self):
        """
        Test document indexing when the index doesn't exist.

        This test verifies that:
        1. When the index doesn't exist, it's created automatically
        2. After creating the index, documents are indexed successfully
        3. The response contains the correct status and document counts
        """
        # Setup
        self.mock_vdb_core.check_index_exists.return_value = False
        self.mock_vdb_core.create_index.return_value = True
        self.mock_vdb_core.vectorize_documents.return_value = 1
        mock_embedding_model = MagicMock()
        test_data = [
            {
                "metadata": {"title": "Test"},
                "path_or_url": "test_path",
                "content": "Test content"
            }
        ]

        # Execute
        with patch('backend.services.vectordatabase_service.ElasticSearchService.create_index') as mock_create_index, \
                patch('backend.services.vectordatabase_service.get_knowledge_record') as mock_get_record, \
                patch('backend.services.vectordatabase_service.tenant_config_manager') as mock_tenant_cfg:
            mock_create_index.return_value = {"status": "success"}
            mock_get_record.return_value = {"tenant_id": "tenant-1"}
            mock_tenant_cfg.get_model_config.return_value = {
                "chunk_batch": None}
            result = ElasticSearchService.index_documents(
                index_name="test_index",
                data=test_data,
                vdb_core=self.mock_vdb_core,
                embedding_model=mock_embedding_model
            )

        # Assert
        self.assertTrue(result["success"])
        self.assertEqual(result["total_indexed"], 1)
        mock_create_index.assert_called_once()
        _, kwargs = self.mock_vdb_core.vectorize_documents.call_args
        self.assertEqual(kwargs.get("embedding_batch_size"),
                         10)  # default when None
        self.assertTrue(callable(kwargs.get("progress_callback")))

    def test_vectorize_documents_indexing_error(self):
        """
        Test document indexing when an error occurs during indexing.

        This test verifies that:
        1. When an error occurs during indexing, an appropriate exception is raised
        2. The exception has the correct status code (500)
        3. The exception message contains the original error message
        """
        # Setup
        self.mock_vdb_core.check_index_exists.return_value = True
        self.mock_vdb_core.vectorize_documents.side_effect = Exception(
            "Indexing error")
        mock_embedding_model = MagicMock()
        test_data = [
            {
                "metadata": {"title": "Test"},
                "path_or_url": "test_path",
                "content": "Test content"
            }
        ]

        # Execute and Assert
        with patch('backend.services.vectordatabase_service.get_knowledge_record') as mock_get_record, \
                patch('backend.services.vectordatabase_service.tenant_config_manager') as mock_tenant_cfg:
            mock_get_record.return_value = {"tenant_id": "tenant-1"}
            mock_tenant_cfg.get_model_config.return_value = {"chunk_batch": 8}

            with self.assertRaises(Exception) as context:
                ElasticSearchService.index_documents(
                    index_name="test_index",
                    data=test_data,
                    vdb_core=self.mock_vdb_core,
                    embedding_model=mock_embedding_model
                )

        self.assertIn("Indexing error", str(context.exception))
        _, kwargs = self.mock_vdb_core.vectorize_documents.call_args
        self.assertEqual(kwargs.get("embedding_batch_size"), 8)
        self.assertTrue(callable(kwargs.get("progress_callback")))

    @patch('backend.services.vectordatabase_service.get_all_files_status')
    def test_list_files_without_chunks(self, mock_get_files_status):
        """
        Test listing files without including document chunks.

        This test verifies that:
        1. Files indexed in Elasticsearch are retrieved correctly
        2. Files being processed (from Redis) are included in the results
        3. Files from both sources are combined in the response
        4. The status of each file is correctly set (COMPLETED or PROCESSING)
        """
        # Setup
        self.mock_vdb_core.get_documents_detail.return_value = [
            {
                "path_or_url": "file1",
                "filename": "file1.txt",
                "file_size": 1024,
                "create_time": "2023-01-01T12:00:00"
            }
        ]
        mock_get_files_status.return_value = {
            "file2": {"state": "PROCESSING", "latest_task_id": "task123"}}

        # Execute
        async def run_test():
            return await ElasticSearchService.list_files(
                index_name="test_index",
                include_chunks=False,
                vdb_core=self.mock_vdb_core
            )

        result = asyncio.run(run_test())

        # Assert
        self.assertEqual(len(result["files"]), 2)
        self.assertEqual(result["files"][0]["status"], "COMPLETED")
        self.assertEqual(result["files"][1]["status"], "PROCESSING")
        self.mock_vdb_core.get_documents_detail.assert_called_once_with(
            "test_index")

    @patch('backend.services.vectordatabase_service.get_all_files_status')
    def test_list_files_with_chunks(self, mock_get_files_status):
        """
        Test listing files with document chunks included.

        This test verifies that:
        1. Files indexed in Elasticsearch are retrieved correctly
        2. Document chunks for each file are retrieved using msearch
        3. The chunks are included in the file details
        4. The chunk count is correctly calculated
        """
        # Setup
        self.mock_vdb_core.get_documents_detail.return_value = [
            {
                "path_or_url": "file1",
                "filename": "file1.txt",
                "file_size": 1024,
                "create_time": "2023-01-01T12:00:00"
            }
        ]
        mock_get_files_status.return_value = {}
        self.mock_vdb_core.client.count.return_value = {"count": 0}
        self.mock_vdb_core.client.count.return_value = {"count": 1}

        # Mock multi_search response
        msearch_response = {
            'responses': [
                {
                    'hits': {
                        'hits': [
                            {
                                '_source': {
                                    'id': 'doc1',
                                    'title': 'Title 1',
                                    'content': 'Content 1',
                                    'create_time': '2023-01-01T12:00:00'
                                }
                            }
                        ]
                    }
                }
            ]
        }
        self.mock_vdb_core.multi_search.return_value = msearch_response

        # Execute
        async def run_test():
            return await ElasticSearchService.list_files(
                index_name="test_index",
                include_chunks=True,
                vdb_core=self.mock_vdb_core
            )

        result = asyncio.run(run_test())

        # Assert
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(len(result["files"][0]["chunks"]), 1)
        self.assertEqual(result["files"][0]["chunk_count"], 1)
        self.mock_vdb_core.multi_search.assert_called_once()

    @patch('backend.services.vectordatabase_service.get_all_files_status')
    def test_list_files_msearch_error(self, mock_get_files_status):
        """
        Test listing files when msearch encounters an error.

        This test verifies that:
        1. When msearch fails, the method handles the error gracefully
        2. Files are still returned without chunks
        3. Chunk count is set to 0 for affected files
        4. The overall operation doesn't fail due to msearch errors
        """
        # Setup
        self.mock_vdb_core.get_documents_detail.return_value = [
            {
                "path_or_url": "file1",
                "filename": "file1.txt",
                "file_size": 1024,
                "create_time": "2023-01-01T12:00:00"
            }
        ]
        mock_get_files_status.return_value = {}
        self.mock_vdb_core.client.count.return_value = {"count": 0}

        # Mock msearch error
        self.mock_vdb_core.client.msearch.side_effect = Exception(
            "MSSearch Error")

        # Execute
        async def run_test():
            return await ElasticSearchService.list_files(
                index_name="test_index",
                include_chunks=True,
                vdb_core=self.mock_vdb_core
            )

        result = asyncio.run(run_test())

        # Assert
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(len(result["files"][0]["chunks"]), 0)
        self.assertEqual(result["files"][0]["chunk_count"], 0)

    @patch('backend.services.vectordatabase_service.delete_file')
    def test_delete_documents(self, mock_delete_file):
        """
        Test document deletion by path or URL.

        This test verifies that:
        1. Documents with the specified path or URL are deleted
        2. The response contains a success status
        """
        # Setup
        self.mock_vdb_core.delete_documents.return_value = 5
        # Configure delete_file to return a success response
        mock_delete_file.return_value = {
            "success": True, "object_name": "test_path"}

        # Execute
        result = ElasticSearchService.delete_documents(
            index_name="test_index",
            path_or_url="test_path",
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deleted_minio"], True)
        # Verify that delete_documents was called with correct parameters
        self.mock_vdb_core.delete_documents.assert_called_once_with(
            "test_index", "test_path")
        # Verify that delete_file was called with the correct path
        mock_delete_file.assert_called_once_with("test_path")

    @patch('backend.services.vectordatabase_service.get_redis_service')
    def test_index_documents_respects_cancellation_flag(self, mock_get_redis_service):
        """
        Test that index_documents stops indexing when the task is marked as cancelled.

        This test verifies that:
        1. _update_progress raises when is_task_cancelled returns True
        2. The exception from vectorize_documents is propagated as an indexing error
        """
        # Setup
        mock_redis_service = MagicMock()
        # First progress callback call: treat as cancelled immediately
        mock_redis_service.is_task_cancelled.return_value = True
        mock_get_redis_service.return_value = mock_redis_service

        # Configure vdb_core
        self.mock_vdb_core.check_index_exists.return_value = True

        # Make vectorize_documents invoke the progress callback (cancellation branch)
        def vectorize_side_effect(*args, **kwargs):
            cb = kwargs.get("progress_callback")
            if cb:
                cb(1, 2)  # _update_progress will swallow and log cancellation
            return 0

        self.mock_vdb_core.vectorize_documents.side_effect = vectorize_side_effect

        # Provide minimal knowledge record for batch size lookup
        with patch('backend.services.vectordatabase_service.get_knowledge_record') as mock_get_record:
            mock_get_record.return_value = {"tenant_id": "tenant-1"}
            with patch('backend.services.vectordatabase_service.tenant_config_manager') as mock_tenant_cfg:
                mock_tenant_cfg.get_model_config.return_value = {
                    "chunk_batch": 10}

                data = [
                    {
                        "path_or_url": "test_path",
                        "content": "some content",
                        "source_type": "minio",
                        "file_size": 123,
                        "metadata": {},
                    }
                ]

                # Execute: no exception should propagate because _update_progress swallows
                result = ElasticSearchService.index_documents(
                    embedding_model=self.mock_embedding,
                    index_name="test_index",
                    data=data,
                    vdb_core=self.mock_vdb_core,
                    task_id="task-123",
                )

                self.assertTrue(result["success"])
                mock_redis_service.is_task_cancelled.assert_called()
                self.mock_vdb_core.vectorize_documents.assert_called_once()

    def test_accurate_search(self):
        """
        Test accurate (keyword-based) search functionality.

        This test verifies that:
        1. The accurate_search method correctly calls the core search implementation
        2. Search results are properly formatted in the response
        3. The response includes total count and query time
        4. The search is performed across the specified indices
        """
        # Setup
        search_request = MagicMock()
        search_request.index_names = ["test_index"]
        search_request.query = "test query"
        search_request.top_k = 10

        self.mock_vdb_core.accurate_search.return_value = [
            {
                "document": {"title": "Doc1", "content": "Content1"},
                "score": 0.95,
                "index": "test_index"
            }
        ]

        # Execute
        result = ElasticSearchService.accurate_search(
            request=search_request,
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["total"], 1)
        self.assertTrue("query_time_ms" in result)
        self.mock_vdb_core.accurate_search.assert_called_once_with(
            index_names=["test_index"], query="test query", top_k=10
        )

    def test_accurate_search_empty_query(self):
        """
        Test accurate search with an empty query.

        This test verifies that:
        1. When the query is empty or consists only of whitespace, an exception is raised
        2. The exception has the correct status code (500)
        3. The exception message contains "Search query cannot be empty"
        """
        # Setup
        search_request = MagicMock()
        search_request.index_names = ["test_index"]
        search_request.query = "   "  # Empty query
        search_request.top_k = 10

        # Execute and Assert
        with self.assertRaises(Exception) as context:
            ElasticSearchService.accurate_search(
                request=search_request,
                vdb_core=self.mock_vdb_core
            )

        self.assertIn("Search query cannot be empty", str(context.exception))

    def test_accurate_search_no_indices(self):
        """
        Test accurate search with no indices specified.

        This test verifies that:
        1. When no indices are specified, an exception is raised
        2. The exception has the correct status code (500)
        3. The exception message contains "At least one index name is required"
        """
        # Setup
        search_request = MagicMock()
        search_request.index_names = []  # No indices
        search_request.query = "test query"
        search_request.top_k = 10

        # Execute and Assert
        with self.assertRaises(Exception) as context:
            ElasticSearchService.accurate_search(
                request=search_request,
                vdb_core=self.mock_vdb_core
            )

        self.assertIn("At least one index name is required",
                      str(context.exception))

    def test_semantic_search(self):
        """
        Test semantic (embedding-based) search functionality.

        This test verifies that:
        1. The semantic_search method correctly calls the core search implementation
        2. Search results are properly formatted in the response
        3. The response includes total count and query time
        4. The search is performed across the specified indices
        """
        # Setup
        search_request = MagicMock()
        search_request.index_names = ["test_index"]
        search_request.query = "test query"
        search_request.top_k = 10

        # Create a mock response directly on the vdb_core instance
        self.mock_vdb_core.semantic_search.return_value = [
            {
                "document": {"title": "Doc1", "content": "Content1"},
                "score": 0.85,
                "index": "test_index"
            }
        ]

        # Execute
        result = ElasticSearchService.semantic_search(
            request=search_request,
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["total"], 1)
        self.assertTrue("query_time_ms" in result)
        self.mock_vdb_core.semantic_search.assert_called_once_with(
            index_names=["test_index"], query="test query", top_k=10
        )

    def test_search_hybrid_success(self):
        """
        Test hybrid search (combining semantic and accurate search).

        This test verifies that:
        1. The search_hybrid method correctly calls the core search implementation
        2. The weight parameter for balancing semantic and accurate search is passed correctly
        3. Search results include individual scores for both semantic and accurate searches
        4. The response contains the expected structure with results, total, and timing information
        """
        # Setup
        self.mock_vdb_core.hybrid_search.return_value = [
            {
                "document": {"title": "Doc1", "content": "Content1"},
                "score": 0.90,
                "index": "test_index",
                "scores": {"accurate": 0.85, "semantic": 0.95}
            }
        ]

        # Execute
        result = ElasticSearchService.search_hybrid(
            index_names=["test_index"],
            query="test query",
            tenant_id="test_tenant",
            top_k=10,
            weight_accurate=0.5,
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["total"], 1)
        self.assertTrue("query_time_ms" in result)
        self.assertEqual(result["results"][0]["score"], 0.90)
        self.assertEqual(result["results"][0]["index"], "test_index")
        self.assertEqual(result["results"][0]
                         ["score_details"]["accurate"], 0.85)
        self.assertEqual(result["results"][0]
                         ["score_details"]["semantic"], 0.95)
        self.mock_vdb_core.hybrid_search.assert_called_once_with(
            index_names=["test_index"],
            query_text="test query",
            embedding_model=self.mock_embedding,
            top_k=10,
            weight_accurate=0.5
        )

    def test_search_hybrid_missing_tenant_id(self):
        """Test search_hybrid raises ValueError when tenant_id is missing."""
        with self.assertRaises(ValueError) as context:
            ElasticSearchService.search_hybrid(
                index_names=["test_index"],
                query="test query",
                tenant_id="",
                top_k=10,
                weight_accurate=0.5,
                vdb_core=self.mock_vdb_core
            )
        self.assertIn("Tenant ID is required", str(context.exception))

    def test_search_hybrid_empty_query(self):
        """Test search_hybrid raises ValueError when query is empty."""
        with self.assertRaises(ValueError) as context:
            ElasticSearchService.search_hybrid(
                index_names=["test_index"],
                query="   ",
                tenant_id="test_tenant",
                top_k=10,
                weight_accurate=0.5,
                vdb_core=self.mock_vdb_core
            )
        self.assertIn("Query text is required", str(context.exception))

    def test_search_hybrid_no_indices(self):
        """Test search_hybrid raises ValueError when no indices provided."""
        with self.assertRaises(ValueError) as context:
            ElasticSearchService.search_hybrid(
                index_names=[],
                query="test query",
                tenant_id="test_tenant",
                top_k=10,
                weight_accurate=0.5,
                vdb_core=self.mock_vdb_core
            )
        self.assertIn("At least one index name is required",
                      str(context.exception))

    def test_search_hybrid_invalid_top_k(self):
        """Test search_hybrid raises ValueError when top_k is invalid."""
        with self.assertRaises(ValueError) as context:
            ElasticSearchService.search_hybrid(
                index_names=["test_index"],
                query="test query",
                tenant_id="test_tenant",
                top_k=0,
                weight_accurate=0.5,
                vdb_core=self.mock_vdb_core
            )
        self.assertIn("top_k must be greater than 0", str(context.exception))

    def test_search_hybrid_invalid_weight(self):
        """Test search_hybrid raises ValueError when weight_accurate is invalid."""
        with self.assertRaises(ValueError) as context:
            ElasticSearchService.search_hybrid(
                index_names=["test_index"],
                query="test query",
                tenant_id="test_tenant",
                top_k=10,
                weight_accurate=1.5,
                vdb_core=self.mock_vdb_core
            )
        self.assertIn("weight_accurate must be between 0 and 1",
                      str(context.exception))

    def test_search_hybrid_no_embedding_model(self):
        """Test search_hybrid raises ValueError when embedding model is not configured."""
        # Stop the mock to test the real get_embedding_model
        self.get_embedding_model_patcher.stop()
        try:
            with patch('backend.services.vectordatabase_service.get_embedding_model', return_value=None):
                with self.assertRaises(ValueError) as context:
                    ElasticSearchService.search_hybrid(
                        index_names=["test_index"],
                        query="test query",
                        tenant_id="test_tenant",
                        top_k=10,
                        weight_accurate=0.5,
                        vdb_core=self.mock_vdb_core
                    )
                self.assertIn("No embedding model configured",
                              str(context.exception))
        finally:
            self.get_embedding_model_patcher.start()

    def test_search_hybrid_exception(self):
        """Test search_hybrid handles exceptions from vdb_core."""
        self.mock_vdb_core.hybrid_search.side_effect = Exception(
            "Search failed")

        with self.assertRaises(Exception) as context:
            ElasticSearchService.search_hybrid(
                index_names=["test_index"],
                query="test query",
                tenant_id="test_tenant",
                top_k=10,
                weight_accurate=0.5,
                vdb_core=self.mock_vdb_core
            )
        self.assertIn("Error executing hybrid search", str(context.exception))

    def test_search_hybrid_weight_accurate_boundary_values(self):
        """Test search_hybrid with different weight_accurate values to ensure line 1146 is covered."""
        # Test with weight_accurate = 0.0 (semantic only)
        self.mock_vdb_core.hybrid_search.return_value = [
            {
                "document": {"title": "Doc1", "content": "Content1"},
                "score": 0.90,
                "index": "test_index",
            }
        ]

        result = ElasticSearchService.search_hybrid(
            index_names=["test_index"],
            query="test query",
            tenant_id="test_tenant",
            top_k=10,
            weight_accurate=0.0,
            vdb_core=self.mock_vdb_core
        )
        self.assertEqual(len(result["results"]), 1)
        self.mock_vdb_core.hybrid_search.assert_called_with(
            index_names=["test_index"],
            query_text="test query",
            embedding_model=self.mock_embedding,
            top_k=10,
            weight_accurate=0.0
        )

        # Test with weight_accurate = 1.0 (accurate only)
        self.mock_vdb_core.hybrid_search.reset_mock()
        result = ElasticSearchService.search_hybrid(
            index_names=["test_index"],
            query="test query",
            tenant_id="test_tenant",
            top_k=10,
            weight_accurate=1.0,
            vdb_core=self.mock_vdb_core
        )
        self.mock_vdb_core.hybrid_search.assert_called_with(
            index_names=["test_index"],
            query_text="test query",
            embedding_model=self.mock_embedding,
            top_k=10,
            weight_accurate=1.0
        )

        # Test with weight_accurate = 0.3 (more semantic)
        self.mock_vdb_core.hybrid_search.reset_mock()
        result = ElasticSearchService.search_hybrid(
            index_names=["test_index"],
            query="test query",
            tenant_id="test_tenant",
            top_k=10,
            weight_accurate=0.3,
            vdb_core=self.mock_vdb_core
        )
        self.mock_vdb_core.hybrid_search.assert_called_with(
            index_names=["test_index"],
            query_text="test query",
            embedding_model=self.mock_embedding,
            top_k=10,
            weight_accurate=0.3
        )

    def test_health_check_healthy(self):
        """
        Test health check when Elasticsearch is healthy.

        This test verifies that:
        1. The health check correctly reports a healthy status when Elasticsearch is available
        2. The response includes the connection status and indices count
        3. The health_check method returns without raising exceptions
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1", "index2"]

        # Execute
        result = ElasticSearchService.health_check(vdb_core=self.mock_vdb_core)

        # Assert
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["elasticsearch"], "connected")
        self.assertEqual(result["indices_count"], 2)

    def test_health_check_unhealthy(self):
        """
        Test health check when Elasticsearch is unhealthy.

        This test verifies that:
        1. When Elasticsearch is unavailable, an exception is raised
        2. The exception has the correct status code (500)
        3. The exception message contains "Health check failed"
        """
        # Setup
        self.mock_vdb_core.get_user_indices.side_effect = Exception(
            "Connection error")

        # Execute and Assert
        with self.assertRaises(Exception) as context:
            ElasticSearchService.health_check(vdb_core=self.mock_vdb_core)

        self.assertIn("Health check failed", str(context.exception))

    @patch('database.model_management_db.get_model_by_model_id')
    def test_summary_index_name(self, mock_get_model_by_model_id):
        """
        Test generating a summary for an index.

        This test verifies that:
        1. Random documents are retrieved for summarization
        2. The summary generation stream is properly initialized using Map-Reduce approach
        3. A StreamingResponse object is returned for streaming the summary tokens
        """
        # Setup
        mock_get_model_by_model_id.return_value = {
            'api_key': 'test_api_key',
            'base_url': 'https://api.test.com',
            'model_name': 'test-model',
            'model_repo': 'test-repo'
        }

        # Mock the new Map-Reduce functions
        with patch('utils.document_vector_utils.process_documents_for_clustering') as mock_process_docs, \
                patch('utils.document_vector_utils.kmeans_cluster_documents') as mock_cluster, \
                patch('utils.document_vector_utils.summarize_clusters_map_reduce') as mock_summarize, \
                patch('utils.document_vector_utils.merge_cluster_summaries') as mock_merge, \
                patch('database.model_management_db.get_model_by_model_id') as mock_get_model_internal:

            # Mock return values
            mock_process_docs.return_value = (
                # document_samples
                {"doc1": {"chunks": [{"content": "test content"}]}},
                {"doc1": np.array([0.1, 0.2, 0.3])}  # doc_embeddings
            )
            mock_cluster.return_value = {"doc1": 0}  # clusters
            mock_summarize.return_value = {
                0: "Test cluster summary"}  # cluster_summaries
            mock_merge.return_value = "Final merged summary"  # final_summary
            mock_get_model_internal.return_value = {
                'api_key': 'test_api_key',
                'base_url': 'https://api.test.com',
                'model_name': 'test-model'
            }

            # Execute
            async def run_test():
                result = await self.es_service.summary_index_name(
                    index_name="test_index",
                    batch_size=1000,
                    vdb_core=self.mock_vdb_core,
                    language='en',
                    model_id=1,
                    tenant_id="test_tenant"
                )

                # Consume part of the stream to trigger the generator function
                generator = result.body_iterator
                # Get at least one item from the generator to trigger execution
                try:
                    async for item in generator:
                        break  # Just get one item to trigger execution
                except StopAsyncIteration:
                    pass

                return result

            result = asyncio.run(run_test())

            # Assert
            self.assertIsInstance(result, StreamingResponse)
            # Basic functionality test - just verify the response is correct type
            # The detailed function calls are tested in their own unit tests

    def test_summary_index_name_no_tenant_id(self):
        """
        Test summary_index_name raises exception when tenant_id is missing.

        This test verifies that:
        1. An exception is raised when tenant_id is None
        2. The exception message contains "Tenant ID is required"
        """

        # Execute and Assert
        async def run_test():
            with self.assertRaises(Exception) as context:
                await self.es_service.summary_index_name(
                    index_name="test_index",
                    batch_size=1000,
                    vdb_core=self.mock_vdb_core,
                    language='en',
                    model_id=1,
                    tenant_id=None  # Missing tenant_id
                )
            self.assertIn("Tenant ID is required", str(context.exception))

        asyncio.run(run_test())

    def test_summary_index_name_no_documents(self):
        """
        Test summary_index_name when no documents are found in index.

        This test verifies that:
        1. An exception is raised when document_samples is empty
        2. The exception message contains "No documents found in index"
        """
        # Mock the new Map-Reduce functions
        with patch('utils.document_vector_utils.process_documents_for_clustering') as mock_process_docs, \
                patch('utils.document_vector_utils.kmeans_cluster_documents'), \
                patch('utils.document_vector_utils.summarize_clusters_map_reduce'), \
                patch('utils.document_vector_utils.merge_cluster_summaries'):
            # Mock return empty document_samples
            mock_process_docs.return_value = (
                {},  # Empty document_samples
                {}  # Empty doc_embeddings
            )

            # Execute
            async def run_test():
                with self.assertRaises(Exception) as context:
                    result = await self.es_service.summary_index_name(
                        index_name="test_index",
                        batch_size=1000,
                        vdb_core=self.mock_vdb_core,
                        language='en',
                        model_id=1,
                        tenant_id="test_tenant"
                    )
                    # Consume the stream to trigger execution
                    generator = result.body_iterator
                    async for item in generator:
                        break

                self.assertIn("No documents found in index",
                              str(context.exception))

            asyncio.run(run_test())

    def test_summary_index_name_runtime_error_fallback(self):
        """
        Test summary_index_name fallback when get_running_loop raises RuntimeError.

        This test verifies that:
        1. When get_running_loop() raises RuntimeError, get_event_loop() is used as fallback
        2. The summary generation still works correctly
        """
        # Mock the new Map-Reduce functions
        with patch('utils.document_vector_utils.process_documents_for_clustering') as mock_process_docs, \
                patch('utils.document_vector_utils.kmeans_cluster_documents') as mock_cluster, \
                patch('utils.document_vector_utils.summarize_clusters_map_reduce') as mock_summarize, \
                patch('utils.document_vector_utils.merge_cluster_summaries') as mock_merge:

            # Mock return values
            mock_process_docs.return_value = (
                # document_samples
                {"doc1": {"chunks": [{"content": "test content"}]}},
                {"doc1": np.array([0.1, 0.2, 0.3])}  # doc_embeddings
            )
            mock_cluster.return_value = {"doc1": 0}  # clusters
            mock_summarize.return_value = {
                0: "Test cluster summary"}  # cluster_summaries
            mock_merge.return_value = "Final merged summary"  # final_summary

            # Create a mock loop with run_in_executor that returns a coroutine
            mock_loop = MagicMock()

            async def mock_run_in_executor(executor, func, *args):
                # Execute the function synchronously and return its result
                return func()

            mock_loop.run_in_executor = mock_run_in_executor

            # Patch asyncio functions to trigger RuntimeError fallback
            with patch('backend.services.vectordatabase_service.asyncio.get_running_loop',
                       side_effect=RuntimeError("No running event loop")), \
                    patch('backend.services.vectordatabase_service.asyncio.get_event_loop',
                          return_value=mock_loop) as mock_get_event_loop:

                # Execute
                async def run_test():
                    result = await self.es_service.summary_index_name(
                        index_name="test_index",
                        batch_size=1000,
                        vdb_core=self.mock_vdb_core,
                        language='en',
                        model_id=1,
                        tenant_id="test_tenant"
                    )

                    # Consume part of the stream to trigger execution
                    generator = result.body_iterator
                    try:
                        async for item in generator:
                            break
                    except StopAsyncIteration:
                        pass

                    return result

                result = asyncio.run(run_test())

                # Assert
                self.assertIsInstance(result, StreamingResponse)
                # Verify fallback was used
                mock_get_event_loop.assert_called()

    def test_summary_index_name_generator_exception(self):
        """
        Test summary_index_name handles exceptions in the generator function.

        This test verifies that:
        1. Exceptions in the generator are caught and streamed as error messages
        2. The error status is properly formatted
        """
        # Mock the new Map-Reduce functions
        with patch('utils.document_vector_utils.process_documents_for_clustering') as mock_process_docs, \
                patch('utils.document_vector_utils.kmeans_cluster_documents') as mock_cluster, \
                patch('utils.document_vector_utils.summarize_clusters_map_reduce') as mock_summarize, \
                patch('utils.document_vector_utils.merge_cluster_summaries') as mock_merge:

            # Mock return values
            mock_process_docs.return_value = (
                # document_samples
                {"doc1": {"chunks": [{"content": "test content"}]}},
                {"doc1": np.array([0.1, 0.2, 0.3])}  # doc_embeddings
            )
            mock_cluster.return_value = {"doc1": 0}  # clusters
            mock_summarize.return_value = {
                0: "Test cluster summary"}  # cluster_summaries
            mock_merge.return_value = "Final merged summary"  # final_summary

            # Execute
            async def run_test():
                result = await self.es_service.summary_index_name(
                    index_name="test_index",
                    batch_size=1000,
                    vdb_core=self.mock_vdb_core,
                    language='en',
                    model_id=1,
                    tenant_id="test_tenant"
                )

                # Consume the stream completely
                generator = result.body_iterator
                items = []
                try:
                    async for item in generator:
                        items.append(item)
                except Exception:
                    pass

                return result, items

            result, items = asyncio.run(run_test())

            # Assert
            self.assertIsInstance(result, StreamingResponse)
            # Verify that items were generated (at least the completed message)
            self.assertGreater(len(items), 0)

    def test_summary_index_name_sample_count_calculation(self):
        """
        Test summary_index_name correctly calculates sample_count from batch_size.

        This test verifies that:
        1. sample_count is calculated as min(batch_size // 5, 200)
        2. The sample_doc_count parameter is passed correctly to process_documents_for_clustering
        """
        # Test with batch_size=1000 -> sample_count should be min(200, 200) = 200
        with patch('utils.document_vector_utils.process_documents_for_clustering') as mock_process_docs, \
                patch('utils.document_vector_utils.kmeans_cluster_documents') as mock_cluster, \
                patch('utils.document_vector_utils.summarize_clusters_map_reduce') as mock_summarize, \
                patch('utils.document_vector_utils.merge_cluster_summaries') as mock_merge:

            # Mock return values
            mock_process_docs.return_value = (
                # document_samples
                {"doc1": {"chunks": [{"content": "test content"}]}},
                {"doc1": np.array([0.1, 0.2, 0.3])}  # doc_embeddings
            )
            mock_cluster.return_value = {"doc1": 0}  # clusters
            mock_summarize.return_value = {
                0: "Test cluster summary"}  # cluster_summaries
            mock_merge.return_value = "Final merged summary"  # final_summary

            # Execute with batch_size=1000
            async def run_test():
                result = await self.es_service.summary_index_name(
                    index_name="test_index",
                    batch_size=1000,
                    vdb_core=self.mock_vdb_core,
                    language='en',
                    model_id=1,
                    tenant_id="test_tenant"
                )

                # Consume part of the stream to trigger execution
                generator = result.body_iterator
                try:
                    async for item in generator:
                        break
                except StopAsyncIteration:
                    pass

                return result

            asyncio.run(run_test())

            # Verify sample_doc_count was called with 200 (min(1000 // 5, 200) = 200)
            self.assertTrue(mock_process_docs.called)
            call_args = mock_process_docs.call_args
            self.assertEqual(call_args.kwargs['sample_doc_count'], 200)

        # Test with batch_size=50 -> sample_count should be min(10, 200) = 10
        with patch('utils.document_vector_utils.process_documents_for_clustering') as mock_process_docs, \
                patch('utils.document_vector_utils.kmeans_cluster_documents') as mock_cluster, \
                patch('utils.document_vector_utils.summarize_clusters_map_reduce') as mock_summarize, \
                patch('utils.document_vector_utils.merge_cluster_summaries') as mock_merge:

            # Mock return values
            mock_process_docs.return_value = (
                {"doc1": {"chunks": [{"content": "test content"}]}},
                {"doc1": np.array([0.1, 0.2, 0.3])}
            )
            mock_cluster.return_value = {"doc1": 0}
            mock_summarize.return_value = {0: "Test cluster summary"}
            mock_merge.return_value = "Final merged summary"

            # Execute with batch_size=50
            async def run_test_small():
                result = await self.es_service.summary_index_name(
                    index_name="test_index",
                    batch_size=50,
                    vdb_core=self.mock_vdb_core,
                    language='en',
                    model_id=1,
                    tenant_id="test_tenant"
                )

                # Consume part of the stream to trigger execution
                generator = result.body_iterator
                try:
                    async for item in generator:
                        break
                except StopAsyncIteration:
                    pass

                return result

            asyncio.run(run_test_small())

            # Verify sample_doc_count was called with 10 (min(50 // 5, 200) = 10)
            self.assertTrue(mock_process_docs.called)
            call_args = mock_process_docs.call_args
            self.assertEqual(call_args.kwargs['sample_doc_count'], 10)

    def test_get_random_documents(self):
        """
        Test retrieving random documents from an index.

        This test verifies that:
        1. The method gets the total document count in the index
        2. A random sample of documents is retrieved
        3. The response contains both the total count and the sampled documents
        """
        # Setup
        self.mock_vdb_core.count_documents.return_value = 100

        search_response = {
            'hits': {
                'hits': [
                    {
                        '_id': 'doc1',
                        '_source': {"title": "Doc1", "content": "Content1"}
                    },
                    {
                        '_id': 'doc2',
                        '_source': {"title": "Doc2", "content": "Content2"}
                    }
                ]
            }
        }
        self.mock_vdb_core.search.return_value = search_response

        # Execute
        result = ElasticSearchService.get_random_documents(
            index_name="test_index",
            batch_size=10,
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(result["total"], 100)
        self.assertEqual(len(result["documents"]), 2)
        self.mock_vdb_core.count_documents.assert_called_once_with(
            "test_index")
        self.mock_vdb_core.search.assert_called_once()

    @patch('backend.services.vectordatabase_service.update_knowledge_record')
    def test_change_summary(self, mock_update_record):
        """
        Test changing the summary of a knowledge base.

        This test verifies that:
        1. The knowledge record is updated with the new summary
        2. The response includes a success status and the updated summary
        3. The update_knowledge_record function is called with correct parameters
        """
        # Setup
        mock_update_record.return_value = True

        # Execute
        result = self.es_service.change_summary(
            index_name="test_index",
            summary_result="Test summary",
            user_id="test_user"
        )

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"], "Test summary")
        mock_update_record.assert_called_once()

    @patch('backend.services.vectordatabase_service.update_knowledge_record')
    def test_update_knowledge_base_success(self, mock_update_record):
        """
        Test successful knowledge base update.

        This test verifies that:
        1. The knowledge base can be updated with all fields
        2. The update_knowledge_record function is called with correct parameters
        3. The method returns True on successful update
        """
        # Setup
        mock_update_record.return_value = True

        # Execute - update with all fields
        result = self.es_service.update_knowledge_base(
            index_name="test_index",
            knowledge_name="Updated Name",
            ingroup_permission="EDIT",
            group_ids=[1, 2, 3],
            user_id="test_user"
        )

        # Assert
        self.assertTrue(result)
        mock_update_record.assert_called_once()
        call_args = mock_update_record.call_args[0][0]
        self.assertEqual(call_args["index_name"], "test_index")
        self.assertEqual(call_args["knowledge_name"], "Updated Name")
        self.assertEqual(call_args["ingroup_permission"], "EDIT")
        # Converted to string
        self.assertEqual(call_args["group_ids"], "1,2,3")
        self.assertEqual(call_args["updated_by"], "test_user")

    @patch('backend.services.vectordatabase_service.update_knowledge_record')
    def test_update_knowledge_base_partial_update_name(self, mock_update_record):
        """
        Test partial update - only updating knowledge name.

        This test verifies that:
        1. Only the specified fields are updated
        2. Other fields are not included in the update payload
        """
        # Setup
        mock_update_record.return_value = True

        # Execute - update only name
        result = self.es_service.update_knowledge_base(
            index_name="test_index",
            knowledge_name="New Name",
            user_id="test_user"
        )

        # Assert
        self.assertTrue(result)
        mock_update_record.assert_called_once()
        call_args = mock_update_record.call_args[0][0]
        self.assertEqual(call_args["index_name"], "test_index")
        self.assertEqual(call_args["knowledge_name"], "New Name")
        self.assertNotIn("ingroup_permission", call_args)
        self.assertNotIn("group_ids", call_args)

    @patch('backend.services.vectordatabase_service.update_knowledge_record')
    def test_update_knowledge_base_partial_update_permission(self, mock_update_record):
        """
        Test partial update - only updating permission.

        This test verifies that:
        1. Only the permission field is updated
        2. Other fields are not included in the update payload
        """
        # Setup
        mock_update_record.return_value = True

        # Execute - update only permission
        result = self.es_service.update_knowledge_base(
            index_name="test_index",
            ingroup_permission="PRIVATE",
            user_id="test_user"
        )

        # Assert
        self.assertTrue(result)
        mock_update_record.assert_called_once()
        call_args = mock_update_record.call_args[0][0]
        self.assertEqual(call_args["index_name"], "test_index")
        self.assertEqual(call_args["ingroup_permission"], "PRIVATE")
        self.assertNotIn("knowledge_name", call_args)
        self.assertNotIn("group_ids", call_args)

    def test_update_knowledge_base_invalid_permission(self):
        """
        Test update with invalid permission value.

        This test verifies that:
        1. ValueError is raised for invalid permission values
        2. The error message contains valid permission options
        """
        # Execute & Assert - invalid permission should raise ValueError
        with self.assertRaises(ValueError) as context:
            self.es_service.update_knowledge_base(
                index_name="test_index",
                ingroup_permission="INVALID_PERMISSION",
                user_id="test_user"
            )

        self.assertIn("Invalid ingroup_permission", str(context.exception))
        self.assertIn("EDIT", str(context.exception))
        self.assertIn("READ_ONLY", str(context.exception))
        self.assertIn("PRIVATE", str(context.exception))

    def test_update_knowledge_base_empty_group_ids(self):
        """
        Test update with empty group_ids list.

        This test verifies that:
        1. Empty group_ids list is converted to empty string
        2. The update is still successful
        """
        with patch('backend.services.vectordatabase_service.update_knowledge_record') as mock_update:
            mock_update.return_value = True

            result = self.es_service.update_knowledge_base(
                index_name="test_index",
                group_ids=[],
                user_id="test_user"
            )

            self.assertTrue(result)
            mock_update.assert_called_once()
            call_args = mock_update.call_args[0][0]
            # Empty list becomes empty string
            self.assertEqual(call_args["group_ids"], "")

    @patch('backend.services.vectordatabase_service.update_knowledge_record')
    def test_update_knowledge_base_not_found(self, mock_update_record):
        """
        Test update when knowledge base doesn't exist.

        This test verifies that:
        1. False is returned when update_knowledge_record returns False
        2. The update payload is still constructed correctly
        """
        # Setup
        mock_update_record.return_value = False

        # Execute
        result = self.es_service.update_knowledge_base(
            index_name="non_existent_index",
            knowledge_name="New Name",
            user_id="test_user"
        )

        # Assert
        self.assertFalse(result)
        mock_update_record.assert_called_once()

    @patch('backend.services.vectordatabase_service.update_knowledge_record')
    def test_update_knowledge_base_with_single_group(self, mock_update_record):
        """
        Test update with single group ID.

        This test verifies that:
        1. Single group ID is correctly converted to string
        2. The update payload is constructed correctly
        """
        # Setup
        mock_update_record.return_value = True

        # Execute
        result = self.es_service.update_knowledge_base(
            index_name="test_index",
            group_ids=[5],
            user_id="test_user"
        )

        # Assert
        self.assertTrue(result)
        mock_update_record.assert_called_once()
        call_args = mock_update_record.call_args[0][0]
        self.assertEqual(call_args["group_ids"], "5")

    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    def test_get_summary(self, mock_get_record):
        """
        Test retrieving the summary of a knowledge base.

        This test verifies that:
        1. The knowledge record is retrieved for the specified index
        2. The summary is extracted from the record
        3. The response includes a success status and the summary
        """
        # Setup
        mock_get_record.return_value = {
            "knowledge_describe": "Test summary"
        }

        # Execute
        result = self.es_service.get_summary(index_name="test_index")

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"], "Test summary")
        mock_get_record.assert_called_once_with({'index_name': 'test_index'})

    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    def test_get_summary_not_found(self, mock_get_record):
        """
        Test retrieving a summary when the knowledge record doesn't exist.

        This test verifies that:
        1. When the knowledge record is not found, an exception is raised
        2. The exception has the correct status code (500)
        3. The exception message contains "Unable to get summary"
        """
        # Setup
        mock_get_record.return_value = None

        # Execute and Assert
        with self.assertRaises(Exception) as context:
            self.es_service.get_summary(index_name="test_index")

        self.assertIn("Unable to get summary", str(context.exception))

    def test_get_index_chunks_filters_fields(self):
        """
        Test chunk retrieval filters unsupported fields and reports totals.
        """
        self.mock_vdb_core.get_index_chunks.return_value = {
            "chunks": [
                {"id": "1", "content": "A", "path_or_url": "/a", "extra": "ignore"},
                {"content": "B", "create_time": "2024-01-01T00:00:00"}
            ],
            "total": 2,
            "page": None,
            "page_size": None,
        }

        result = ElasticSearchService.get_index_chunks(
            index_name="kb-index",
            vdb_core=self.mock_vdb_core
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["chunks"][0], {
                         "id": "1", "content": "A", "path_or_url": "/a"})
        self.assertEqual(result["chunks"][1], {
                         "content": "B", "create_time": "2024-01-01T00:00:00"})
        self.mock_vdb_core.get_index_chunks.assert_called_once_with(
            "kb-index",
            page=None,
            page_size=None,
            path_or_url=None,
        )

    def test_get_index_chunks_keeps_non_dict_entries(self):
        """
        Test chunk retrieval keeps non-dict entries unchanged.
        """
        self.mock_vdb_core.get_index_chunks.return_value = {
            "chunks": ["raw_chunk"],
            "total": 1,
            "page": 1,
            "page_size": 1,
        }

        result = ElasticSearchService.get_index_chunks(
            index_name="kb-index",
            vdb_core=self.mock_vdb_core
        )

        self.assertEqual(result["chunks"], ["raw_chunk"])
        self.assertEqual(result["total"], 1)

    def test_get_index_chunks_error(self):
        """
        Test chunk retrieval error handling.
        """
        self.mock_vdb_core.get_index_chunks.side_effect = Exception("boom")

        with self.assertRaises(Exception) as exc:
            ElasticSearchService.get_index_chunks(
                index_name="kb-index",
                vdb_core=self.mock_vdb_core
            )

        self.assertIn(
            "Error retrieving chunks from index kb-index: boom", str(exc.exception))

    def test_create_chunk_builds_payload_and_calls_core(self):
        """
        Test create_chunk builds payload and delegates to vdb_core.create_chunk.
        """
        from types import SimpleNamespace

        self.mock_vdb_core.create_chunk.return_value = {"id": "chunk-1"}
        chunk_request = SimpleNamespace(
            chunk_id=None,
            title="My title",
            filename="file.txt",
            path_or_url="doc-1",
            content="hello world",
            metadata={"lang": "en"},
        )

        result = ElasticSearchService.create_chunk(
            index_name="kb-index",
            chunk_request=chunk_request,
            vdb_core=self.mock_vdb_core,
            user_id="user-1",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunk_id"], "chunk-1")
        self.mock_vdb_core.create_chunk.assert_called_once()
        # create_chunk is called positionally: (index_name, chunk_payload)
        _, payload = self.mock_vdb_core.create_chunk.call_args[0]
        # Base fields
        self.assertEqual(payload["content"], "hello world")
        self.assertEqual(payload["path_or_url"], "doc-1")
        self.assertEqual(payload["filename"], "file.txt")
        self.assertEqual(payload["title"], "My title")
        self.assertEqual(payload["created_by"], "user-1")
        # Metadata merged
        self.assertEqual(payload["lang"], "en")
        self.assertIn("id", payload)

    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    @patch('backend.services.vectordatabase_service.get_embedding_model')
    def test_create_chunk_generates_embedding_when_tenant_provided(self, mock_get_embedding_model, mock_get_knowledge_record):
        """
        Test create_chunk generates and stores embedding when tenant_id is provided.
        """
        from types import SimpleNamespace

        # Setup mocks
        self.mock_vdb_core.create_chunk.return_value = {"id": "chunk-1"}

        # Mock knowledge record with embedding model name
        mock_get_knowledge_record.return_value = {
            "index_name": "kb-index",
            "embedding_model_name": "text-embedding-3-small"
        }

        # Mock embedding model
        mock_embedding = MagicMock()
        mock_embedding.get_embeddings.return_value = [[0.1, 0.2, 0.3]]
        mock_get_embedding_model.return_value = mock_embedding

        chunk_request = SimpleNamespace(
            chunk_id=None,
            title=None,
            filename="file.txt",
            path_or_url="doc-1",
            content="This is test content that needs embedding",
            metadata={},
        )

        result = ElasticSearchService.create_chunk(
            index_name="kb-index",
            chunk_request=chunk_request,
            vdb_core=self.mock_vdb_core,
            user_id="user-1",
            tenant_id="tenant-123",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunk_id"], "chunk-1")

        # Verify embedding was generated
        mock_get_embedding_model.assert_called_once_with("tenant-123", "text-embedding-3-small")
        mock_embedding.get_embeddings.assert_called_once()

        # Verify vdb_core was called with embedding in payload
        self.mock_vdb_core.create_chunk.assert_called_once()
        _, payload = self.mock_vdb_core.create_chunk.call_args[0]
        self.assertIn("embedding", payload)
        self.assertEqual(payload["embedding"], [0.1, 0.2, 0.3])
        self.assertEqual(payload["embedding_model_name"], "text-embedding-3-small")

    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    @patch('backend.services.vectordatabase_service.get_embedding_model')
    def test_create_chunk_without_tenant_no_embedding_generated(self, mock_get_embedding_model, mock_get_knowledge_record):
        """
        Test create_chunk does not generate embedding when tenant_id is not provided.
        """
        from types import SimpleNamespace

        self.mock_vdb_core.create_chunk.return_value = {"id": "chunk-1"}

        chunk_request = SimpleNamespace(
            chunk_id=None,
            title=None,
            filename="file.txt",
            path_or_url="doc-1",
            content="Content without embedding",
            metadata={},
        )

        result = ElasticSearchService.create_chunk(
            index_name="kb-index",
            chunk_request=chunk_request,
            vdb_core=self.mock_vdb_core,
            user_id="user-1",
            tenant_id=None,  # No tenant_id
        )

        self.assertEqual(result["status"], "success")

        # Verify no embedding-related calls were made
        mock_get_knowledge_record.assert_not_called()
        mock_get_embedding_model.assert_not_called()

        # Verify payload has no embedding
        self.mock_vdb_core.create_chunk.assert_called_once()
        _, payload = self.mock_vdb_core.create_chunk.call_args[0]
        self.assertNotIn("embedding", payload)

    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    @patch('backend.services.vectordatabase_service.get_embedding_model')
    def test_create_chunk_handles_embedding_failure_gracefully(self, mock_get_embedding_model, mock_get_knowledge_record):
        """
        Test create_chunk handles embedding generation failure gracefully.
        """
        from types import SimpleNamespace

        self.mock_vdb_core.create_chunk.return_value = {"id": "chunk-1"}

        mock_get_knowledge_record.return_value = {
            "index_name": "kb-index",
            "embedding_model_name": "text-embedding-3-small"
        }

        # Embedding model raises exception
        mock_get_embedding_model.side_effect = Exception("Embedding service unavailable")

        chunk_request = SimpleNamespace(
            chunk_id=None,
            title=None,
            filename="file.txt",
            path_or_url="doc-1",
            content="Content that would need embedding",
            metadata={},
        )

        # Should not raise exception, just log warning
        result = ElasticSearchService.create_chunk(
            index_name="kb-index",
            chunk_request=chunk_request,
            vdb_core=self.mock_vdb_core,
            user_id="user-1",
            tenant_id="tenant-123",
        )

        # Result should still be successful (embedding is optional)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunk_id"], "chunk-1")

        # Verify chunk was still created without embedding
        self.mock_vdb_core.create_chunk.assert_called_once()

    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    @patch('backend.services.vectordatabase_service.get_embedding_model')
    def test_create_chunk_handles_empty_embedding_result(self, mock_get_embedding_model, mock_get_knowledge_record):
        """
        Test create_chunk handles empty embedding result gracefully.
        """
        from types import SimpleNamespace

        self.mock_vdb_core.create_chunk.return_value = {"id": "chunk-1"}

        mock_get_knowledge_record.return_value = {
            "index_name": "kb-index",
            "embedding_model_name": "text-embedding-3-small"
        }

        # Embedding returns empty list
        mock_embedding = MagicMock()
        mock_embedding.get_embeddings.return_value = []
        mock_get_embedding_model.return_value = mock_embedding

        chunk_request = SimpleNamespace(
            chunk_id=None,
            title=None,
            filename="file.txt",
            path_or_url="doc-1",
            content="Content with empty embedding",
            metadata={},
        )

        result = ElasticSearchService.create_chunk(
            index_name="kb-index",
            chunk_request=chunk_request,
            vdb_core=self.mock_vdb_core,
            user_id="user-1",
            tenant_id="tenant-123",
        )

        # Result should still be successful
        self.assertEqual(result["status"], "success")

        # Verify payload has no embedding when embedding is empty
        self.mock_vdb_core.create_chunk.assert_called_once()
        _, payload = self.mock_vdb_core.create_chunk.call_args[0]
        self.assertNotIn("embedding", payload)

    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    @patch('backend.services.vectordatabase_service.get_embedding_model')
    def test_create_chunk_with_unknown_model_name_still_calls_embedding_model(self, mock_get_embedding_model, mock_get_knowledge_record):
        """
        Test create_chunk when knowledge record has unknown embedding model.
        The backend still calls get_embedding_model (it doesn't check for "unknown").
        The "unknown" check is only in the frontend's read-only mode logic.
        """
        from types import SimpleNamespace

        self.mock_vdb_core.create_chunk.return_value = {"id": "chunk-1"}

        # Knowledge record returns "unknown" as embedding model
        mock_get_knowledge_record.return_value = {
            "index_name": "kb-index",
            "embedding_model_name": "unknown"
        }

        # Embedding model returns empty (model doesn't exist)
        mock_embedding = MagicMock()
        mock_embedding.get_embeddings.return_value = []
        mock_get_embedding_model.return_value = mock_embedding

        chunk_request = SimpleNamespace(
            chunk_id=None,
            title=None,
            filename="file.txt",
            path_or_url="doc-1",
            content="Content with unknown model",
            metadata={},
        )

        result = ElasticSearchService.create_chunk(
            index_name="kb-index",
            chunk_request=chunk_request,
            vdb_core=self.mock_vdb_core,
            user_id="user-1",
            tenant_id="tenant-123",
        )

        # Should succeed, embedding model IS called but returns empty
        self.assertEqual(result["status"], "success")

        # Verify embedding model was called (backend doesn't skip based on "unknown")
        mock_get_embedding_model.assert_called_once_with("tenant-123", "unknown")

    def test_update_chunk_builds_payload_and_calls_core(self):
        """
        Test update_chunk builds update payload and delegates to vdb_core.update_chunk.
        """

        class DummyUpdate:
            def __init__(self, **fields):
                self._fields = fields
                # Expose metadata attribute like real Pydantic model
                self.metadata = fields.get("metadata")

            def dict(self, exclude_unset=True, exclude=None):
                data = dict(self._fields)
                if exclude:
                    for key in exclude:
                        data.pop(key, None)
                return data

        self.mock_vdb_core.update_chunk.return_value = {"id": "chunk-1"}
        chunk_request = DummyUpdate(
            content="updated",
            filename="updated.txt",
            metadata={"lang": "en"},
        )

        result = ElasticSearchService.update_chunk(
            index_name="kb-index",
            chunk_id="chunk-1",
            chunk_request=chunk_request,
            vdb_core=self.mock_vdb_core,
            user_id="user-1",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunk_id"], "chunk-1")
        self.mock_vdb_core.update_chunk.assert_called_once_with(
            "kb-index", "chunk-1", ANY
        )

    def test_delete_chunk_success(self):
        """
        Test delete_chunk returns success when vdb_core.delete_chunk is True.
        """
        self.mock_vdb_core.delete_chunk.return_value = True

        result = ElasticSearchService.delete_chunk(
            index_name="kb-index",
            chunk_id="chunk-1",
            vdb_core=self.mock_vdb_core,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunk_id"], "chunk-1")
        self.mock_vdb_core.delete_chunk.assert_called_once_with(
            "kb-index", "chunk-1"
        )

    def test_delete_chunk_not_found_raises_value_error(self):
        """
        Test delete_chunk raises ValueError when vdb_core.delete_chunk returns False.
        """
        self.mock_vdb_core.delete_chunk.return_value = False

        with self.assertRaises(Exception) as exc:
            ElasticSearchService.delete_chunk(
                index_name="kb-index",
                chunk_id="missing",
                vdb_core=self.mock_vdb_core,
            )

        self.assertIn(
            "Error deleting chunk: Chunk missing not found in index kb-index", str(exc.exception))

    @patch('backend.services.vectordatabase_service.query_group_ids_by_user')
    @patch('backend.services.vectordatabase_service.get_user_tenant_by_user_id')
    @patch('backend.services.vectordatabase_service.get_knowledge_info_by_tenant_id')
    @patch('fastapi.Response')
    def test_list_indices_success_status_200(self, mock_response, mock_get_knowledge, mock_get_user_tenant, mock_get_group_ids):
        """
        Test list_indices method returns status code 200 on success.

        This test verifies that:
        1. The list_indices method successfully retrieves indices
        2. The response is a dictionary containing the expected data
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1", "index2"]
        mock_response.status_code = 200
        mock_get_knowledge.return_value = [
            {"index_name": "index1",
                "embedding_model_name": "test-model", "group_ids": "1,2", "knowledge_sources": "elasticsearch"},
            {"index_name": "index2", "embedding_model_name": "test-model",
                "group_ids": "", "knowledge_sources": "elasticsearch"}
        ]
        mock_get_user_tenant.return_value = {
            "user_role": "SU", "tenant_id": "test_tenant"}
        mock_get_group_ids.return_value = []

        # Execute
        result = ElasticSearchService.list_indices(
            pattern="*",
            include_stats=False,
            target_tenant_id="test_tenant",  # Now required parameter
            user_id="test_user",  # New required parameter
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(len(result["indices"]), 2)
        self.assertEqual(result["count"], 2)
        # Verify no exception is raised, implying 200 status code
        self.assertIsInstance(result, dict)  # Success response is a dictionary
        self.mock_vdb_core.get_user_indices.assert_called_once_with("*")
        mock_get_knowledge.assert_called_once_with("test_tenant")

    def test_health_check_success_status_200(self):
        """
        Test health_check method returns status code 200 on success.

        This test verifies that:
        1. The health_check method successfully checks Elasticsearch health
        2. The response is a dictionary with a "healthy" status
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        self.mock_vdb_core.get_user_indices.return_value = ["index1", "index2"]

        # Execute
        result = ElasticSearchService.health_check(vdb_core=self.mock_vdb_core)

        # Assert
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["elasticsearch"], "connected")
        # Verify successful response status - 200
        self.assertIsInstance(result, dict)  # Success response is a dictionary

    def test_get_random_documents_success_status_200(self):
        """
        Test get_random_documents method returns status code 200 on success.

        This test verifies that:
        1. The get_random_documents method successfully retrieves random documents
        2. The response contains the expected data structure with total and documents
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        self.mock_vdb_core.count_documents.return_value = 100

        search_response = {
            'hits': {
                'hits': [
                    {
                        '_id': 'doc1',
                        '_source': {"title": "Doc1", "content": "Content1"}
                    }
                ]
            }
        }
        self.mock_vdb_core.search.return_value = search_response

        # Execute
        result = ElasticSearchService.get_random_documents(
            index_name="test_index",
            batch_size=10,
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(result["total"], 100)
        self.assertEqual(len(result["documents"]), 1)
        # Verify successful response status - 200
        self.assertIsInstance(result, dict)  # Success response is a dictionary
        self.assertIn("total", result)
        self.assertIn("documents", result)

    def test_semantic_search_success_status_200(self):
        """
        Test semantic_search method returns status code 200 on success.

        This test verifies that:
        1. The semantic_search method successfully performs a search
        2. The response contains the expected search results
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        search_request = MagicMock()
        search_request.index_names = ["test_index"]
        search_request.query = "valid query"
        search_request.top_k = 10

        self.mock_vdb_core.semantic_search.return_value = [
            {
                "document": {"title": "Doc1", "content": "Content1"},
                "score": 0.85,
                "index": "test_index"
            }
        ]

        # Execute
        result = ElasticSearchService.semantic_search(
            request=search_request,
            vdb_core=self.mock_vdb_core
        )

        # Assert
        self.assertEqual(len(result["results"]), 1)
        # Verify successful response status - 200
        self.assertIsInstance(result, dict)
        self.assertIn("results", result)
        self.assertIn("total", result)
        self.assertIn("query_time_ms", result)
        self.mock_vdb_core.semantic_search.assert_called_once_with(
            index_names=["test_index"], query="valid query", top_k=10
        )

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    def test_vectorize_documents_success_status_200(self, mock_get_record, mock_tenant_cfg):
        """
        Test vectorize_documents method returns status code 200 on success.

        This test verifies that:
        1. The vectorize_documents method successfully indexes multiple documents
        2. The response indicates success and correct document counts
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        self.mock_vdb_core.check_index_exists.return_value = True
        self.mock_vdb_core.vectorize_documents.return_value = 3
        mock_embedding_model = MagicMock()
        mock_embedding_model.model = "test-model"
        mock_get_record.return_value = {"tenant_id": "tenant-1"}
        mock_tenant_cfg.get_model_config.return_value = {"chunk_batch": 10}

        test_data = [
            {
                "metadata": {"title": "Test1", "languages": ["en"]},
                "path_or_url": "path1",
                "content": "Content1"
            },
            {
                "metadata": {"title": "Test2", "languages": ["zh"]},
                "path_or_url": "path2",
                "content": "Content2"
            },
            {
                "metadata": {"title": "Test3", "languages": ["fr"]},
                "path_or_url": "path3",
                "content": "Content3"
            }
        ]

        # Execute
        result = ElasticSearchService.index_documents(
            index_name="test_index",
            data=test_data,
            vdb_core=self.mock_vdb_core,
            embedding_model=mock_embedding_model
        )

        # Assert
        self.assertTrue(result["success"])
        self.assertEqual(result["total_indexed"], 3)
        self.assertEqual(result["total_submitted"], 3)
        # Verify successful response status - 200
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertTrue(result["success"])

    @patch('backend.services.vectordatabase_service.delete_file')
    def test_delete_documents_success_status_200(self, mock_delete_file):
        """
        Test delete_documents method returns status code 200 on success.

        This test verifies that:
        1. The delete_documents method successfully deletes documents
        2. The response indicates success
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        self.mock_vdb_core.delete_documents.return_value = 5
        # Configure delete_file to return a success response
        mock_delete_file.return_value = {
            "success": True, "object_name": "test_path"}

        # Execute
        result = ElasticSearchService.delete_documents(
            index_name="test_index",
            path_or_url="test_path",
            vdb_core=self.mock_vdb_core
        )

        # Assert
        # Verify successful response status - 200
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deleted_minio"], True)
        # Verify that delete_documents was called with correct parameters
        self.mock_vdb_core.delete_documents.assert_called_once_with(
            "test_index", "test_path")
        # Verify that delete_file was called with the correct path
        mock_delete_file.assert_called_once_with("test_path")

    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    def test_get_summary_success_status_200(self, mock_get_record):
        """
        Test get_summary method returns status code 200 on success.

        This test verifies that:
        1. The get_summary method successfully retrieves a knowledge base summary
        2. The response indicates success and contains the summary
        3. The method completes without raising exceptions, implying a 200 status code
        """
        # Setup
        mock_get_record.return_value = {
            "knowledge_describe": "This is a test summary for knowledge base"
        }

        # Execute
        result = self.es_service.get_summary(index_name="test_index")

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"],
                         "This is a test summary for knowledge base")
        # Verify successful response status - 200
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "success")
        mock_get_record.assert_called_once_with({'index_name': 'test_index'})

    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    def test_check_kb_exist_available(self, mock_get_knowledge):
        """Test knowledge base name availability when not found in tenant."""
        # Setup: knowledge_name not found in tenant
        mock_get_knowledge.return_value = None

        # Execute
        result = check_knowledge_base_exist_impl(
            knowledge_name="test_kb",
            vdb_core=self.mock_vdb_core,
            user_id="test_user",
            tenant_id="tenant1"
        )

        # Assert
        mock_get_knowledge.assert_called_once_with({
            "knowledge_name": "test_kb",
            "tenant_id": "tenant1"
        })
        self.assertEqual(result["status"], "available")

    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    def test_check_kb_exist_exists_in_tenant(self, mock_get_knowledge):
        """Test detection when knowledge base exists within the same tenant."""
        # Setup: knowledge_name exists in tenant
        mock_get_knowledge.return_value = {
            "knowledge_name": "test_kb", "tenant_id": "tenant1"}

        # Execute
        result = check_knowledge_base_exist_impl(
            knowledge_name="test_kb",
            vdb_core=self.mock_vdb_core,
            user_id="test_user",
            tenant_id="tenant1"
        )

        # Assert
        mock_get_knowledge.assert_called_once_with({
            "knowledge_name": "test_kb",
            "tenant_id": "tenant1"
        })
        self.assertEqual(result["status"], "exists_in_tenant")

    # Note: generate_knowledge_summary_stream function has been removed
    # These tests are no longer relevant as the function was replaced with summary_index_name

    def test_get_vdb_core(self):
        """
        Test get_vdb_core function returns the elastic_core instance.

        This test verifies that:
        1. The get_vdb_core function returns the correct elastic_core instance
        2. The function is properly imported and accessible
        """
        from backend.services.vectordatabase_service import get_vector_db_core

        # Execute
        result = get_vector_db_core()

        # Assert
        self.assertIsNotNone(result)
        # The result should be the elastic_core instance
        self.assertTrue(hasattr(result, 'client'))

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    def test_get_embedding_model_embedding_type(self, mock_tenant_config_manager):
        """
        Test get_embedding_model with embedding model type.

        This test verifies that:
        1. When model_type is "embedding", OpenAICompatibleEmbedding is returned
        2. The correct parameters are passed to the embedding model
        """
        # Setup
        mock_config = {
            "model_type": "embedding",
            "api_key": "test_api_key",
            "base_url": "https://test.api.com",
            "model_name": "test-model",
            "max_tokens": 1024
        }
        mock_tenant_config_manager.get_model_config.return_value = mock_config

        # Stop the mock from setUp to test the real function
        self.get_embedding_model_patcher.stop()

        try:
            with patch('backend.services.vectordatabase_service.OpenAICompatibleEmbedding') as mock_embedding_class, \
                    patch('backend.services.vectordatabase_service.get_model_name_from_config') as mock_get_model_name:
                mock_embedding_instance = MagicMock()
                mock_embedding_class.return_value = mock_embedding_instance
                mock_get_model_name.return_value = "test-model"

                # Execute - now we can call the real function
                from backend.services.vectordatabase_service import get_embedding_model
                result = get_embedding_model("test_tenant")

                # Assert
                self.assertEqual(result, mock_embedding_instance)
                mock_tenant_config_manager.get_model_config.assert_called_once_with(
                    key="EMBEDDING_ID", tenant_id="test_tenant")
                mock_embedding_class.assert_called_once_with(
                    api_key="test_api_key",
                    base_url="https://test.api.com",
                    model_name="test-model",
                    embedding_dim=1024,
                    ssl_verify=True
                )
        finally:
            # Restart the mock for other tests
            self.get_embedding_model_patcher.start()

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    def test_get_embedding_model_multi_embedding_type(self, mock_tenant_config_manager):
        """
        Test get_embedding_model with multi_embedding model type.

        This test verifies that:
        1. When model_type is "multi_embedding", JinaEmbedding is returned
        2. The correct parameters are passed to the embedding model
        """
        # Setup
        mock_config = {
            "model_type": "multi_embedding",
            "api_key": "test_api_key",
            "base_url": "https://test.api.com",
            "model_name": "test-model",
            "max_tokens": 2048
        }
        mock_tenant_config_manager.get_model_config.return_value = mock_config

        # Stop the mock from setUp to test the real function
        self.get_embedding_model_patcher.stop()

        try:
            with patch('backend.services.vectordatabase_service.JinaEmbedding') as mock_embedding_class, \
                    patch('backend.services.vectordatabase_service.get_model_name_from_config') as mock_get_model_name:
                mock_embedding_instance = MagicMock()
                mock_embedding_class.return_value = mock_embedding_instance
                mock_get_model_name.return_value = "test-model"

                # Execute - now we can call the real function
                from backend.services.vectordatabase_service import get_embedding_model
                result = get_embedding_model("test_tenant")

                # Assert
                self.assertEqual(result, mock_embedding_instance)
                mock_tenant_config_manager.get_model_config.assert_called_once_with(
                    key="EMBEDDING_ID", tenant_id="test_tenant")
                mock_embedding_class.assert_called_once_with(
                    api_key="test_api_key",
                    base_url="https://test.api.com",
                    model_name="test-model",
                    embedding_dim=2048,
                    ssl_verify=True
                )
        finally:
            # Restart the mock for other tests
            self.get_embedding_model_patcher.start()

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    def test_get_embedding_model_unknown_type(self, mock_tenant_config_manager):
        """
        Test get_embedding_model with unknown model type.

        This test verifies that:
        1. When model_type is neither "embedding" nor "multi_embedding", None is returned
        2. The function handles unknown model types gracefully
        """
        # Setup
        mock_config = {
            "model_type": "unknown_type",
            "api_key": "test_api_key",
            "base_url": "https://test.api.com",
            "model_name": "test-model",
            "max_tokens": 1024
        }
        mock_tenant_config_manager.get_model_config.return_value = mock_config

        # Stop the mock from setUp to test the real function
        self.get_embedding_model_patcher.stop()

        try:
            # Execute - now we can call the real function
            from backend.services.vectordatabase_service import get_embedding_model
            result = get_embedding_model("test_tenant")

            # Assert
            self.assertIsNone(result)
            mock_tenant_config_manager.get_model_config.assert_called_once_with(
                key="EMBEDDING_ID", tenant_id="test_tenant")
        finally:
            # Restart the mock for other tests
            self.get_embedding_model_patcher.start()

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    def test_get_embedding_model_empty_type(self, mock_tenant_config_manager):
        """
        Test get_embedding_model with empty model type.

        This test verifies that:
        1. When model_type is empty string, None is returned
        2. The function handles empty model types gracefully
        """
        # Setup
        mock_config = {
            "model_type": "",
            "api_key": "test_api_key",
            "base_url": "https://test.api.com",
            "model_name": "test-model",
            "max_tokens": 1024
        }
        mock_tenant_config_manager.get_model_config.return_value = mock_config

        # Stop the mock from setUp to test the real function
        self.get_embedding_model_patcher.stop()

        try:
            # Execute - now we can call the real function
            from backend.services.vectordatabase_service import get_embedding_model
            result = get_embedding_model("test_tenant")

            # Assert
            self.assertIsNone(result)
            mock_tenant_config_manager.get_model_config.assert_called_once_with(
                key="EMBEDDING_ID", tenant_id="test_tenant")
        finally:
            # Restart the mock for other tests
            self.get_embedding_model_patcher.start()

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    def test_get_embedding_model_missing_type(self, mock_tenant_config_manager):
        """
        Test get_embedding_model with missing model type.

        This test verifies that:
        1. When model_type is missing from config, None is returned
        2. The function handles missing model types gracefully
        """
        # Setup
        mock_config = {
            "api_key": "test_api_key",
            "base_url": "https://test.api.com",
            "model_name": "test-model",
            "max_tokens": 1024
        }
        mock_tenant_config_manager.get_model_config.return_value = mock_config

        # Stop the mock from setUp to test the real function
        self.get_embedding_model_patcher.stop()

        try:
            # Execute - now we can call the real function
            from backend.services.vectordatabase_service import get_embedding_model
            result = get_embedding_model("test_tenant")

            # Assert
            self.assertIsNone(result)
            mock_tenant_config_manager.get_model_config.assert_called_once_with(
                key="EMBEDDING_ID", tenant_id="test_tenant")
        finally:
            # Restart the mock for other tests
            self.get_embedding_model_patcher.start()

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    @patch('backend.services.vectordatabase_service.get_model_records')
    def test_get_embedding_model_with_model_name_found(self, mock_get_models, mock_tenant_config_manager):
        """
        Test get_embedding_model with model_name parameter when the model is found.

        This test verifies that:
        1. When model_name is provided and found in tenant's models, OpenAICompatibleEmbedding is returned
        2. The correct parameters are passed to the embedding model
        3. The function uses model_repo/model_name format for matching
        """
        # Setup - mock get_models to return a model that matches
        mock_get_models.return_value = [
            {
                "model_repo": "openai",
                "model_name": "text-embedding-ada-002",
                "api_key": "test_api_key",
                "base_url": "https://test.api.com",
                "max_tokens": 1024,
                "ssl_verify": True
            }
        ]

        # Mock tenant config for fallback behavior (should NOT be called when model is found)
        mock_tenant_config_manager.get_model_config.return_value = {
            "model_type": "embedding",
            "api_key": "fallback_key",
            "base_url": "https://fallback.api.com",
            "model_name": "fallback-model",
            "max_tokens": 1024
        }

        # Stop the mock from setUp to test the real function
        self.get_embedding_model_patcher.stop()

        try:
            with patch('backend.services.vectordatabase_service.OpenAICompatibleEmbedding') as mock_embedding_class, \
                    patch('backend.services.vectordatabase_service.get_model_name_from_config') as mock_get_model_name:
                mock_embedding_instance = MagicMock()
                mock_embedding_class.return_value = mock_embedding_instance
                mock_get_model_name.return_value = "text-embedding-ada-002"

                # Execute - now we can call the real function
                from backend.services.vectordatabase_service import get_embedding_model
                result = get_embedding_model("test_tenant", model_name="openai/text-embedding-ada-002")

                # Assert
                self.assertEqual(result, mock_embedding_instance)
                mock_get_models.assert_called_once_with(
                    {"model_type": "embedding"}, "test_tenant")
                mock_embedding_class.assert_called_once_with(
                    api_key="test_api_key",
                    base_url="https://test.api.com",
                    model_name="text-embedding-ada-002",
                    embedding_dim=1024,
                    ssl_verify=True
                )
                # Tenant config should NOT be called when model is found
                mock_tenant_config_manager.get_model_config.assert_not_called()
        finally:
            # Restart the mock for other tests
            self.get_embedding_model_patcher.start()

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    @patch('backend.services.vectordatabase_service.get_model_records')
    def test_get_embedding_model_with_model_name_found_without_repo(self, mock_get_models, mock_tenant_config_manager):
        """
        Test get_embedding_model with model_name when model is found without model_repo.

        This test verifies that:
        1. When model_name is provided and found (without model_repo), OpenAICompatibleEmbedding is returned
        2. The function handles models without model_repo correctly using just model_name
        """
        # Setup - mock get_models to return a model without model_repo
        mock_get_models.return_value = [
            {
                "model_name": "simple-model",
                "api_key": "test_api_key",
                "base_url": "https://test.api.com",
                "max_tokens": 2048,
                "ssl_verify": False
            }
        ]

        # Mock tenant config for fallback behavior (should NOT be called when model is found)
        mock_tenant_config_manager.get_model_config.return_value = {
            "model_type": "embedding",
            "api_key": "fallback_key",
            "base_url": "https://fallback.api.com",
            "model_name": "fallback-model",
            "max_tokens": 1024
        }

        # Stop the mock from setUp to test the real function
        self.get_embedding_model_patcher.stop()

        try:
            with patch('backend.services.vectordatabase_service.OpenAICompatibleEmbedding') as mock_embedding_class, \
                    patch('backend.services.vectordatabase_service.get_model_name_from_config') as mock_get_model_name:
                mock_embedding_instance = MagicMock()
                mock_embedding_class.return_value = mock_embedding_instance
                mock_get_model_name.return_value = "simple-model"

                # Execute - now we can call the real function
                from backend.services.vectordatabase_service import get_embedding_model
                result = get_embedding_model("test_tenant", model_name="simple-model")

                # Assert
                self.assertEqual(result, mock_embedding_instance)
                mock_get_models.assert_called_once_with(
                    {"model_type": "embedding"}, "test_tenant")
                mock_embedding_class.assert_called_once_with(
                    api_key="test_api_key",
                    base_url="https://test.api.com",
                    model_name="simple-model",
                    embedding_dim=2048,
                    ssl_verify=False
                )
        finally:
            # Restart the mock for other tests
            self.get_embedding_model_patcher.start()

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    @patch('backend.services.vectordatabase_service.get_model_records')
    def test_get_embedding_model_with_model_name_not_found(self, mock_get_models, mock_tenant_config_manager):
        """
        Test get_embedding_model with model_name when the model is not found.

        This test verifies that:
        1. When model_name is provided but not found in tenant's models, fallback to default config
        2. The function falls back to default embedding model behavior
        """
        # Setup - mock get_models to return empty list (model not found)
        mock_get_models.return_value = []

        # Mock tenant config for fallback behavior
        mock_config = {
            "model_type": "embedding",
            "api_key": "fallback_api_key",
            "base_url": "https://fallback.api.com",
            "model_name": "fallback-model",
            "max_tokens": 1024
        }
        mock_tenant_config_manager.get_model_config.return_value = mock_config

        # Stop the mock from setUp to test the real function
        self.get_embedding_model_patcher.stop()

        try:
            with patch('backend.services.vectordatabase_service.OpenAICompatibleEmbedding') as mock_embedding_class, \
                    patch('backend.services.vectordatabase_service.get_model_name_from_config') as mock_get_model_name:
                mock_embedding_instance = MagicMock()
                mock_embedding_class.return_value = mock_embedding_instance
                mock_get_model_name.return_value = "fallback-model"

                # Execute - now we can call the real function
                from backend.services.vectordatabase_service import get_embedding_model
                result = get_embedding_model("test_tenant", model_name="nonexistent-model")

                # Assert
                self.assertEqual(result, mock_embedding_instance)
                mock_get_models.assert_called_once_with(
                    {"model_type": "embedding"}, "test_tenant")
                # Should fall back to default config
                mock_tenant_config_manager.get_model_config.assert_called_once_with(
                    key="EMBEDDING_ID", tenant_id="test_tenant")
                mock_embedding_class.assert_called_once_with(
                    api_key="fallback_api_key",
                    base_url="https://fallback.api.com",
                    model_name="fallback-model",
                    embedding_dim=1024,
                    ssl_verify=True
                )
        finally:
            # Restart the mock for other tests
            self.get_embedding_model_patcher.start()

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    @patch('backend.services.vectordatabase_service.get_model_records')
    def test_get_embedding_model_with_model_name_exception(self, mock_get_models, mock_tenant_config_manager):
        """
        Test get_embedding_model with model_name when database query throws exception.

        This test verifies that:
        1. When get_models throws an exception, the function logs a warning and falls back to default config
        2. The function handles exceptions gracefully
        """
        # Setup - mock get_models to throw an exception
        mock_get_models.side_effect = Exception("Database connection failed")

        # Mock tenant config for fallback behavior
        mock_config = {
            "model_type": "embedding",
            "api_key": "fallback_api_key",
            "base_url": "https://fallback.api.com",
            "model_name": "fallback-model",
            "max_tokens": 1024
        }
        mock_tenant_config_manager.get_model_config.return_value = mock_config

        # Stop the mock from setUp to test the real function
        self.get_embedding_model_patcher.stop()

        try:
            with patch('backend.services.vectordatabase_service.OpenAICompatibleEmbedding') as mock_embedding_class, \
                    patch('backend.services.vectordatabase_service.get_model_name_from_config') as mock_get_model_name:
                mock_embedding_instance = MagicMock()
                mock_embedding_class.return_value = mock_embedding_instance
                mock_get_model_name.return_value = "fallback-model"

                # Execute - now we can call the real function
                from backend.services.vectordatabase_service import get_embedding_model
                result = get_embedding_model("test_tenant", model_name="test-model")

                # Assert - should fall back to default config
                self.assertEqual(result, mock_embedding_instance)
                mock_get_models.assert_called_once_with(
                    {"model_type": "embedding"}, "test_tenant")
                mock_tenant_config_manager.get_model_config.assert_called_once_with(
                    key="EMBEDDING_ID", tenant_id="test_tenant")
                mock_embedding_class.assert_called_once_with(
                    api_key="fallback_api_key",
                    base_url="https://fallback.api.com",
                    model_name="fallback-model",
                    embedding_dim=1024,
                    ssl_verify=True
                )
        finally:
            # Restart the mock for other tests
            self.get_embedding_model_patcher.start()

    @patch('backend.services.vectordatabase_service.get_redis_service')
    def test_update_progress_success(self, mock_get_redis):
        """Ensure _update_progress updates Redis progress when not cancelled."""
        from backend.services.vectordatabase_service import _update_progress

        mock_redis = MagicMock()
        mock_redis.is_task_cancelled.return_value = False
        mock_redis.save_progress_info.return_value = True
        mock_get_redis.return_value = mock_redis

        _update_progress("task-1", 5, 10)

        mock_redis.is_task_cancelled.assert_called_once_with("task-1")
        mock_redis.save_progress_info.assert_called_once_with("task-1", 5, 10)

    @patch('backend.services.vectordatabase_service.get_redis_service')
    def test_update_progress_save_failure(self, mock_get_redis):
        """_update_progress logs a warning when saving progress fails."""
        from backend.services.vectordatabase_service import _update_progress

        mock_redis = MagicMock()
        mock_redis.is_task_cancelled.return_value = False
        mock_redis.save_progress_info.return_value = False
        mock_get_redis.return_value = mock_redis

        _update_progress("task-2", 1, 2)

        mock_redis.is_task_cancelled.assert_called_once_with("task-2")
        mock_redis.save_progress_info.assert_called_once_with("task-2", 1, 2)


class TestRethrowOrPlain(unittest.TestCase):
    def setUp(self):
        self.es_service = ElasticSearchService()
        self.mock_vdb_core = MagicMock()
        self.mock_vdb_core.embedding_model = MagicMock()
        self.mock_vdb_core.embedding_dim = 768

        self.get_embedding_model_patcher = patch(
            'backend.services.vectordatabase_service.get_embedding_model')
        self.mock_get_embedding = self.get_embedding_model_patcher.start()
        self.mock_embedding = MagicMock()
        self.mock_embedding.embedding_dim = 768
        self.mock_embedding.model = "test-model"
        self.mock_get_embedding.return_value = self.mock_embedding

    def tearDown(self):
        self.get_embedding_model_patcher.stop()

    def test_rethrow_or_plain_rethrows_json_error_code(self):
        """_rethrow_or_plain should re-raise JSON payload when error_code present."""
        from backend.services.vectordatabase_service import _rethrow_or_plain

        with self.assertRaises(Exception) as exc:
            _rethrow_or_plain(
                Exception('{"error_code":"E123","detail":"boom"}'))
        self.assertIn('"error_code": "E123"', str(exc.exception))

    def test_get_vector_db_core_unsupported_type(self):
        """get_vector_db_core raises on unsupported db type."""
        from backend.services.vectordatabase_service import get_vector_db_core

        with self.assertRaises(ValueError) as exc:
            get_vector_db_core(db_type="unsupported")

        self.assertIn("Unsupported vector database type", str(exc.exception))

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    @patch('backend.services.vectordatabase_service.DataMateCore')
    def test_get_vector_db_core_datamate_type(self, mock_datamate_core, mock_tenant_config_manager):
        """get_vector_db_core returns DataMateCore for DATAMATE type."""
        from backend.services.vectordatabase_service import get_vector_db_core
        from consts.const import VectorDatabaseType, DATAMATE_URL

        # Setup mocks
        mock_tenant_config_manager.get_app_config.return_value = DATAMATE_URL
        mock_datamate_core.return_value = MagicMock()

        # Execute
        result = get_vector_db_core(db_type=VectorDatabaseType.DATAMATE, tenant_id="test-tenant")

        # Assert
        mock_tenant_config_manager.get_app_config.assert_called_once_with(DATAMATE_URL, tenant_id="test-tenant")
        mock_datamate_core.assert_called_once_with(base_url=DATAMATE_URL)
        self.assertEqual(result, mock_datamate_core.return_value)

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    @patch('backend.services.vectordatabase_service.DataMateCore')
    def test_get_vector_db_core_datamate_success(self, mock_datamate_core, mock_tenant_config_manager):
        """get_vector_db_core returns DataMateCore when DATAMATE type with valid tenant_id and configured URL."""
        from backend.services.vectordatabase_service import get_vector_db_core
        from consts.const import VectorDatabaseType, DATAMATE_URL

        # Setup mocks
        mock_tenant_config_manager.get_app_config.return_value = "https://datamate.example.com"
        mock_datamate_instance = MagicMock()
        mock_datamate_core.return_value = mock_datamate_instance

        # Execute
        result = get_vector_db_core(
            db_type=VectorDatabaseType.DATAMATE, tenant_id="test-tenant")

        # Assert
        self.assertEqual(result, mock_datamate_instance)
        mock_tenant_config_manager.get_app_config.assert_called_once_with(
            DATAMATE_URL, tenant_id="test-tenant")
        mock_datamate_core.assert_called_once_with(
            base_url="https://datamate.example.com")

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    def test_get_vector_db_core_datamate_no_url_configured(self, mock_tenant_config_manager):
        """get_vector_db_core raises ValueError when DATAMATE type with tenant_id but no URL configured."""
        from backend.services.vectordatabase_service import get_vector_db_core
        from consts.const import VectorDatabaseType

        # Setup mock to return None (no URL configured)
        mock_tenant_config_manager.get_app_config.return_value = None

        # Execute and Assert
        with self.assertRaises(ValueError) as exc:
            get_vector_db_core(
                db_type=VectorDatabaseType.DATAMATE, tenant_id="test-tenant")

        self.assertIn(
            "DataMate URL not configured for tenant test-tenant", str(exc.exception))
        mock_tenant_config_manager.get_app_config.assert_called_once()

    def test_get_vector_db_core_datamate_no_tenant_id(self):
        """get_vector_db_core raises ValueError when DATAMATE type without tenant_id."""
        from backend.services.vectordatabase_service import get_vector_db_core
        from consts.const import VectorDatabaseType

        # Execute and Assert
        with self.assertRaises(ValueError) as exc:
            get_vector_db_core(
                db_type=VectorDatabaseType.DATAMATE, tenant_id=None)

        self.assertIn("tenant_id must be provided for DataMate",
                      str(exc.exception))

    def test_rethrow_or_plain_parses_error_code(self):
        """_rethrow_or_plain rethrows JSON error_code payloads unchanged."""
        from backend.services.vectordatabase_service import _rethrow_or_plain

        with self.assertRaises(Exception) as exc:
            _rethrow_or_plain(Exception('{"error_code":123,"detail":"boom"}'))

        self.assertIn("error_code", str(exc.exception))

    @patch('services.redis_service.get_redis_service')
    def test_full_delete_knowledge_base_no_files_redis_warning(self, mock_get_redis):
        """full_delete_knowledge_base handles empty file list and surfaces Redis warnings."""
        mock_vdb_core = MagicMock()
        mock_redis = MagicMock()
        mock_redis.delete_knowledgebase_records.return_value = {
            "total_deleted": 0,
            "errors": []
        }
        mock_get_redis.return_value = mock_redis

        with patch('backend.services.vectordatabase_service.ElasticSearchService.list_files',
                   new_callable=AsyncMock, return_value={"files": []}) as mock_list_files, \
                patch('backend.services.vectordatabase_service.ElasticSearchService.delete_index',
                      new_callable=AsyncMock, return_value={"status": "success"}) as mock_delete_index:
            async def run_test():
                return await ElasticSearchService.full_delete_knowledge_base(
                    index_name="kb-1",
                    vdb_core=mock_vdb_core,
                    user_id="user-1",
                )

            result = asyncio.run(run_test())

        self.assertEqual(result["minio_cleanup"]["total_files_found"], 0)
        self.assertEqual(result["redis_cleanup"].get("errors"), [])
        self.assertIn("redis_warnings", result)
        self.assertIn("redis_warnings", result)
        mock_list_files.assert_awaited_once()
        mock_delete_index.assert_awaited_once()

    @patch('services.redis_service.get_redis_service')
    def test_full_delete_knowledge_base_minio_and_redis_error(self, mock_get_redis):
        """full_delete_knowledge_base logs minio summary and handles redis cleanup errors."""
        mock_vdb_core = MagicMock()
        mock_redis = MagicMock()
        # Redis cleanup will raise to hit error branch (lines 289-292)
        mock_redis.delete_knowledgebase_records.side_effect = Exception(
            "redis boom")
        mock_get_redis.return_value = mock_redis

        files_payload = {
            "files": [
                {"path_or_url": "obj-success", "source_type": "minio"},
                {"path_or_url": "obj-fail", "source_type": "minio"},
            ]
        }

        # delete_file returns success for first, failure for second
        with patch('backend.services.vectordatabase_service.ElasticSearchService.list_files',
                   new_callable=AsyncMock, return_value=files_payload) as mock_list_files, \
                patch('backend.services.vectordatabase_service.delete_file') as mock_delete_file, \
                patch('backend.services.vectordatabase_service.ElasticSearchService.delete_index',
                      new_callable=AsyncMock, return_value={"status": "success"}) as mock_delete_index:
            mock_delete_file.side_effect = [
                {"success": True},
                {"success": False, "error": "minio failed"},
            ]

            async def run_test():
                return await ElasticSearchService.full_delete_knowledge_base(
                    index_name="kb-2",
                    vdb_core=mock_vdb_core,
                    user_id="user-2",
                )

            result = asyncio.run(run_test())

        # MinIO summary should reflect one success and one failure (line 270 hit)
        self.assertEqual(result["minio_cleanup"]["deleted_count"], 1)
        self.assertEqual(result["minio_cleanup"]["failed_count"], 1)
        # Redis cleanup error should be surfaced
        self.assertIn("error", result["redis_cleanup"])
        mock_list_files.assert_awaited_once()
        mock_delete_index.assert_awaited_once_with(
            "kb-2", mock_vdb_core, "user-2")

    @patch('backend.services.vectordatabase_service.create_knowledge_record')
    def test_create_knowledge_base_create_index_failure(self, mock_create_record):
        """create_knowledge_base raises when index creation fails."""
        mock_create_record.return_value = {
            "knowledge_id": 1,
            "index_name": "1-uuid",
            "knowledge_name": "kb"
        }
        self.mock_vdb_core.create_index.return_value = False

        with self.assertRaises(Exception) as exc:
            ElasticSearchService.create_knowledge_base(
                knowledge_name="kb",
                embedding_dim=256,
                vdb_core=self.mock_vdb_core,
                user_id="user-1",
                tenant_id="tenant-1",
            )

        self.assertIn("Failed to create index", str(exc.exception))

    @patch('backend.services.vectordatabase_service.create_knowledge_record')
    def test_create_knowledge_base_raises_on_exception(self, mock_create_record):
        """create_knowledge_base wraps unexpected errors."""
        mock_create_record.return_value = {
            "knowledge_id": 2,
            "index_name": "2-uuid",
            "knowledge_name": "kb2"
        }
        self.mock_vdb_core.create_index.side_effect = Exception("boom")

        with self.assertRaises(Exception) as exc:
            ElasticSearchService.create_knowledge_base(
                knowledge_name="kb2",
                embedding_dim=128,
                vdb_core=self.mock_vdb_core,
                user_id="user-2",
                tenant_id="tenant-2",
            )

        self.assertIn("Error creating knowledge base", str(exc.exception))

    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    def test_index_documents_default_batch_without_tenant(self, mock_get_record):
        """index_documents defaults embedding batch size to 10 when tenant is missing."""
        mock_get_record.return_value = None
        self.mock_vdb_core.check_index_exists.return_value = True
        self.mock_vdb_core.vectorize_documents.return_value = 1

        data = [{
            "path_or_url": "p1",
            "content": "c1",
            "metadata": {"title": "t1"},
        }]
        embedding = MagicMock()
        embedding.model = "model-x"

        result = ElasticSearchService.index_documents(
            embedding_model=embedding,
            index_name="idx",
            data=data,
            vdb_core=self.mock_vdb_core,
        )

        self.assertTrue(result["success"])
        _, kwargs = self.mock_vdb_core.vectorize_documents.call_args
        self.assertEqual(kwargs["embedding_batch_size"], 10)

    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    @patch('backend.services.vectordatabase_service.get_redis_service')
    def test_index_documents_updates_final_progress(self, mock_get_redis, mock_get_record, mock_tenant_cfg):
        """index_documents sends final progress update to Redis when task_id is provided."""
        mock_get_record.return_value = {"tenant_id": "tenant-1"}
        mock_tenant_cfg.get_model_config.return_value = {"chunk_batch": 4}
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        self.mock_vdb_core.check_index_exists.return_value = True
        self.mock_vdb_core.vectorize_documents.return_value = 2

        data = [
            {"path_or_url": "p1", "content": "c1", "metadata": {}},
            {"path_or_url": "p2", "content": "c2", "metadata": {}},
        ]

        result = ElasticSearchService.index_documents(
            embedding_model=self.mock_embedding,
            index_name="idx",
            data=data,
            vdb_core=self.mock_vdb_core,
            task_id="task-xyz",
        )

        self.assertTrue(result["success"])
        mock_redis.save_progress_info.assert_called()
        last_call = mock_redis.save_progress_info.call_args_list[-1]
        self.assertEqual(last_call[0], ("task-xyz", 2, 2))

    @patch('backend.services.vectordatabase_service.get_redis_service')
    @patch('backend.services.vectordatabase_service.get_knowledge_record')
    @patch('backend.services.vectordatabase_service.tenant_config_manager')
    def test_index_documents_progress_init_and_final_errors(self, mock_tenant_cfg, mock_get_record, mock_get_redis):
        """index_documents should continue when progress save fails during init and final updates."""
        mock_get_record.return_value = {"tenant_id": "tenant-1"}
        mock_tenant_cfg.get_model_config.return_value = {"chunk_batch": 4}

        mock_redis = MagicMock()
        # First call (init) raises, second call (final) raises
        mock_redis.save_progress_info.side_effect = [
            Exception("init fail"), Exception("final fail")]
        mock_redis.is_task_cancelled.return_value = False
        mock_get_redis.return_value = mock_redis

        self.mock_vdb_core.check_index_exists.return_value = True
        self.mock_vdb_core.vectorize_documents.return_value = 1

        data = [{"path_or_url": "p1", "content": "c1", "metadata": {}}]

        result = ElasticSearchService.index_documents(
            embedding_model=self.mock_embedding,
            index_name="idx",
            data=data,
            vdb_core=self.mock_vdb_core,
            task_id="task-err",
        )

        self.assertTrue(result["success"])
        # two attempts to save progress (init and final)
        self.assertEqual(mock_redis.save_progress_info.call_count, 2)

    @patch('backend.services.vectordatabase_service.get_all_files_status')
    @patch('backend.services.vectordatabase_service.get_redis_service')
    def test_list_files_handles_invalid_create_time_and_failed_tasks(self, mock_get_redis, mock_get_files_status):
        """list_files handles invalid timestamps, progress overrides, and error info."""
        self.mock_vdb_core.get_documents_detail.return_value = [
            {
                "path_or_url": "file1",
                "filename": "file1.txt",
                "file_size": 10,
                "create_time": "invalid",
                "chunk_count": 1
            }
        ]
        self.mock_vdb_core.client.count.return_value = {"count": 7}

        mock_get_files_status.return_value = {
            "file1": {
                "state": "PROCESS_FAILED",
                "latest_task_id": "task-1",
                "processed_chunks": 1,
                "total_chunks": 5,
                "source_type": "minio",
                "original_filename": "file1.txt"
            }
        }

        mock_redis = MagicMock()
        mock_redis.get_progress_info.return_value = {
            "processed_chunks": 2,
            "total_chunks": 5
        }
        mock_redis.get_error_info.return_value = "boom error"
        mock_get_redis.return_value = mock_redis

        async def run_test():
            return await ElasticSearchService.list_files(
                index_name="idx",
                include_chunks=False,
                vdb_core=self.mock_vdb_core
            )

        result = asyncio.run(run_test())
        self.assertEqual(len(result["files"]), 1)
        file_info = result["files"][0]
        self.assertEqual(file_info["chunk_count"], 7)
        self.assertEqual(file_info["file_size"], 10)
        self.assertEqual(file_info["status"], "PROCESS_FAILED")
        self.assertEqual(file_info["processed_chunk_num"], 2)
        self.assertEqual(file_info["total_chunk_num"], 5)
        self.assertEqual(file_info["error_reason"], "boom error")
        self.assertIsInstance(file_info["create_time"], int)

    @patch('backend.services.vectordatabase_service.get_all_files_status')
    @patch('backend.services.vectordatabase_service.get_redis_service')
    def test_list_files_warning_and_progress_error_branches(self, mock_get_redis, mock_get_files_status):
        """list_files covers chunk count warning, file size error, progress overrides, and redis failures."""
        # Existing ES file triggers count warning (lines 749-750 and 910-916)
        self.mock_vdb_core.get_documents_detail.return_value = [
            {
                "path_or_url": "file-es",
                "filename": "file-es.txt",
                "file_size": 5,
                "create_time": "2024-01-01T00:00:00",
                "chunk_count": 1
            }
        ]
        # First count call for ES file, second for completed file at include_chunks=False
        self.mock_vdb_core.client.count.side_effect = [
            Exception("count fail initial"),
            Exception("count fail final"),
        ]

        # Two tasks from Celery status to exercise progress success and failure
        mock_get_files_status.return_value = {
            "file-processing": {
                "state": "PROCESSING",
                "latest_task_id": "t1",
                "source_type": "minio",
                "original_filename": "fp.txt",
                "processed_chunks": 1,
                "total_chunks": 3,
            },
            "file-failed": {
                "state": "PROCESS_FAILED",
                "latest_task_id": "t2",
                "source_type": "minio",
                "original_filename": "ff.txt",
            },
        }

        mock_redis = MagicMock()
        # Progress info: first returns dict, second raises to hit lines 815-816
        mock_redis.get_progress_info.side_effect = [
            {"processed_chunks": 2, "total_chunks": 4},
            Exception("progress boom"),
        ]
        # get_error_info raises to hit 847-848
        mock_redis.get_error_info.side_effect = Exception("error info boom")
        mock_get_redis.return_value = mock_redis

        with patch('backend.services.vectordatabase_service.get_file_size', side_effect=Exception("size boom")):
            async def run_test():
                return await ElasticSearchService.list_files(
                    index_name="idx",
                    include_chunks=False,
                    vdb_core=self.mock_vdb_core
                )

            result = asyncio.run(run_test())

        # Ensure both ES file and processing files are returned
        paths = {f["path_or_url"] for f in result["files"]}
        self.assertIn("file-es", paths)
        self.assertIn("file-processing", paths)
        self.assertIn("file-failed", paths)
        # Processing file gets progress override
        proc_file = next(
            f for f in result["files"] if f["path_or_url"] == "file-processing")
        self.assertEqual(proc_file["processed_chunk_num"], 2)
        self.assertEqual(proc_file["total_chunk_num"], 4)
        # Failed file retains default chunk_count fallback
        failed_file = next(
            f for f in result["files"] if f["path_or_url"] == "file-failed")
        self.assertEqual(failed_file.get("chunk_count", 0), 0)

    @patch('backend.services.vectordatabase_service.get_all_files_status', return_value={})
    def test_list_files_with_chunks_updates_chunk_count(self, mock_get_files_status):
        """list_files include_chunks path refreshes chunk counts."""
        self.mock_vdb_core.get_documents_detail.return_value = [
            {
                "path_or_url": "file1",
                "filename": "file1.txt",
                "file_size": 10,
                "create_time": "2024-01-01T00:00:00"
            }
        ]
        self.mock_vdb_core.multi_search.return_value = {
            "responses": [
                {
                    "hits": {
                        "hits": [
                            {"_source": {
                                "id": "doc1",
                                "title": "t",
                                "content": "c",
                                "create_time": "2024-01-01T00:00:00"
                            }}
                        ]
                    }
                }
            ]
        }
        self.mock_vdb_core.client.count.return_value = {"count": 2}

        async def run_test():
            return await ElasticSearchService.list_files(
                index_name="idx",
                include_chunks=True,
                vdb_core=self.mock_vdb_core
            )

        result = asyncio.run(run_test())
        file_info = result["files"][0]
        self.assertEqual(file_info["chunk_count"], 2)
        self.assertEqual(len(file_info["chunks"]), 1)

    def test_summary_index_name_streams_generator_error(self):
        """summary_index_name streams error payloads when generator fails."""

        class BadIterable:
            def __iter__(self):
                raise RuntimeError("stream failure")

        with patch('utils.document_vector_utils.process_documents_for_clustering') as mock_process_docs, \
                patch('utils.document_vector_utils.kmeans_cluster_documents') as mock_cluster, \
                patch('utils.document_vector_utils.summarize_clusters_map_reduce') as mock_summarize, \
                patch('utils.document_vector_utils.merge_cluster_summaries', return_value=BadIterable()):
            mock_process_docs.return_value = (
                {"doc1": {"chunks": [{"content": "x"}]}},
                {"doc1": MagicMock()}
            )
            mock_cluster.return_value = {"doc1": 0}
            mock_summarize.return_value = {0: "summary"}

            async def run_test():
                response = await self.es_service.summary_index_name(
                    index_name="idx",
                    batch_size=100,
                    vdb_core=self.mock_vdb_core,
                    language="en",
                    model_id=None,
                    tenant_id="tenant-1",
                )
                messages = []
                async for chunk in response.body_iterator:
                    messages.append(chunk)
                    break
                return messages

            messages = asyncio.run(run_test())
            self.assertTrue(any("error" in msg for msg in messages))


if __name__ == '__main__':
    unittest.main()
