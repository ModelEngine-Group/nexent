# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from test.common.contract_stubs import install_shared_contract_stub
from test.common.contract_stubs import install_business_constant_stubs, install_business_contract_stubs
import asyncio
import importlib
import sys
import os
import time
import types
from management.services.knowledge_base import listing as listing_contract
import unittest
from enum import Enum
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, call
# Mock MinioClient before importing modules that use it
from unittest.mock import patch
from types import ModuleType, SimpleNamespace

import pytest


from test.common.module_stubs import capture_module_stubs

_modules_before_stubs = sys.modules.copy()

@pytest.fixture(autouse=True)
def isolate_list_tag_projection(monkeypatch, _isolated_imports):
    """Keep list tests independent from tag persistence, which has its own tests."""
    module = types.ModuleType("management.services.tag.projection")
    def project_tags(resources, **kwargs):
        assert kwargs["resource_type"] == "knowledge_base"
        assert kwargs["id_field"] == "index_name"
        return [{**resource, "tags": ["Catalog tag"]} for resource in resources]

    module.project_authorized_resource_tags = MagicMock(
        side_effect=project_tags
    )
    monkeypatch.setitem(sys.modules, "management.services.tag.projection", module)
    return module.project_authorized_resource_tags

# Environment variables are now configured in conftest.py

REPO_ROOT = Path(__file__).resolve().parents[3]
SDK_ROOT = REPO_ROOT / "sdk"
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

try:
    import nexent.memory.memory_service as real_memory_service
    memory_pkg = sys.modules.get("nexent.memory")
except Exception:
    real_memory_service = None
    memory_pkg = ModuleType("nexent.memory")
    memory_pkg.__path__ = []
    memory_service_stub = ModuleType("nexent.memory.memory_service")
    async def _clear_memory_stub(*_args, **_kwargs):
        await asyncio.sleep(0)
        return None
    memory_service_stub.clear_memory = _clear_memory_stub
    sys.modules["nexent.memory.memory_service"] = memory_service_stub

# Mock boto3 before importing the module under test
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock


# Mock nexent modules before importing modules that use them


def _create_package_mock(name):
    """Helper to create a package-like mock module."""
    pkg = types.ModuleType(name)
    pkg.__path__ = []
    return pkg


nexent_mock = _create_package_mock('nexent')
sys.modules['nexent'] = nexent_mock

# Mock nexent.monitor module to satisfy imports
monitor_module = types.ModuleType('nexent.monitor')
monitor_module.set_monitoring_context = MagicMock()
monitor_module.set_monitoring_operation = MagicMock()
monitor_module.get_monitoring_manager = MagicMock()
sys.modules['nexent.monitor'] = monitor_module
setattr(nexent_mock, 'monitor', monitor_module)

# Mock nexent.memory module to break import chain
memory_service_module = types.ModuleType('nexent.memory.memory_service')
memory_service_module.clear_memory = MagicMock()
memory_service_module.add_memory = MagicMock()
memory_service_module.get_memory = MagicMock()
nexent_memory_module = _create_package_mock('nexent.memory')
sys.modules['nexent.memory'] = nexent_memory_module
sys.modules['nexent.memory.memory_service'] = memory_service_module
setattr(nexent_memory_module, 'memory_service', memory_service_module)

# Mock nexent.core.models.embedding_model with proper class exports
embedding_model_module = types.ModuleType('nexent.core.models.embedding_model')


consts_exceptions_mod = types.ModuleType("contracts.errors.exceptions")


class AppException(Exception):
    def __init__(self, error_code, message=None, details=None):
        self.error_code = error_code
        self.message = message or str(error_code)
        self.details = details or {}
        super().__init__(self.message)

    @property
    def http_status(self):
        return 500

    def to_dict(self):
        return {
            "code": str(getattr(self.error_code, "value", self.error_code)),
            "message": self.message,
            "details": self.details or None,
        }


class UnauthorizedError(Exception):
    pass


class NotFoundException(Exception):
    pass


class DuplicateError(Exception):
    pass


class ValidationError(Exception):
    pass


class TenantResourceLimitError(ValidationError, ValueError):
    pass


consts_exceptions_mod.UnauthorizedError = UnauthorizedError
consts_exceptions_mod.AppException = AppException
consts_exceptions_mod.NotFoundException = NotFoundException
consts_exceptions_mod.DuplicateError = DuplicateError
consts_exceptions_mod.ValidationError = ValidationError
consts_exceptions_mod.TenantResourceLimitError = TenantResourceLimitError

# Use real contracts.constants.environment/scheduler (env vars are configured in test/conftest.py)
consts_const_mod = importlib.import_module("contracts.constants.environment")
consts_scheduler_mod = importlib.import_module("contracts.constants.constants")

# The shared test bootstrap can load a reduced consts stub before this module.
# Supply the knowledge-base service constants required by the refactored module.
if not hasattr(consts_const_mod, "DATAMATE_URL"):
    consts_const_mod.DATAMATE_URL = "DATAMATE_URL"
if not hasattr(consts_const_mod, "ES_API_KEY"):
    consts_const_mod.ES_API_KEY = ""
if not hasattr(consts_const_mod, "ES_HOST"):
    consts_const_mod.ES_HOST = ""
if not hasattr(consts_const_mod, "VectorDatabaseType"):
    class VectorDatabaseType(str, Enum):
        ELASTICSEARCH = "elasticsearch"
        DATAMATE = "datamate"

    consts_const_mod.VectorDatabaseType = VectorDatabaseType

sys.modules["contracts.constants.environment"] = consts_const_mod
install_business_constant_stubs(consts_const_mod)
install_shared_contract_stub(consts_exceptions_mod, 'exceptions')
install_business_contract_stubs(MagicMock())
install_shared_contract_stub(consts_scheduler_mod, 'scheduler')
install_shared_contract_stub(MagicMock(), 'error_code')
identity_constants = importlib.import_module('contracts.constants.constants')


class _VectorDatabaseCore:
    """Lightweight stand-in for the real VectorDatabaseCore for import-time typing."""
    pass


class MockOpenAICompatibleEmbedding:
    def __init__(self, *args, **kwargs):
        self.model = kwargs.get("model_name", "mock-embedding-model")
        self.embedding_dim = kwargs.get("embedding_dim", 768)
        self.model_type = kwargs.get("model_type", "embedding")


class MockDashScopeMultimodalEmbedding:
    def __init__(self, *args, **kwargs):
        pass


class MockJinaEmbedding:
    def __init__(self, *args, **kwargs):
        pass


class MockSiliconflowMultimodalEmbedding:
    def __init__(self, *args, **kwargs):
        pass


class MockBaseEmbedding:
    pass


embedding_model_module.OpenAICompatibleEmbedding = MockOpenAICompatibleEmbedding
embedding_model_module.JinaEmbedding = MockJinaEmbedding
embedding_model_module.BaseEmbedding = MockBaseEmbedding
embedding_model_module.DashScopeMultimodalEmbedding = MockDashScopeMultimodalEmbedding
embedding_model_module.SiliconflowMultimodalEmbedding = MockSiliconflowMultimodalEmbedding
sys.modules['nexent.core.models.embedding_model'] = embedding_model_module

# Mock nexent.core.models.rerank_model with proper class exports
rerank_model_module = types.ModuleType('nexent.core.models.rerank_model')


class MockOpenAICompatibleRerank:
    def __init__(self, *args, **kwargs):
        pass


class MockBaseRerank:
    pass


rerank_model_module.OpenAICompatibleRerank = MockOpenAICompatibleRerank
rerank_model_module.BaseRerank = MockBaseRerank
sys.modules['nexent.core.models.rerank_model'] = rerank_model_module

# Mock nexent.core.models
nexent_core_models_module = types.ModuleType('nexent.core.models')
nexent_core_models_module.OpenAIModel = MagicMock
nexent_core_models_module.embedding_model = embedding_model_module
nexent_core_models_module.rerank_model = rerank_model_module
nexent_core_models_module.stt_model = _create_package_mock('nexent.core.models.stt_model')
sys.modules['nexent.core.models'] = nexent_core_models_module

# Mock nexent.core
nexent_core_module = _create_package_mock('nexent.core')
nexent_core_module.models = nexent_core_models_module
sys.modules['nexent.core'] = nexent_core_module
setattr(nexent_mock, 'core', nexent_core_module)

nexent_core_gateway_module = _create_package_mock('nexent.core.gateway')
nexent_core_gateway_modality_module = types.ModuleType('nexent.core.gateway.modality')
nexent_core_gateway_modality_module.EmbeddingAdapter = MockBaseEmbedding
nexent_core_gateway_module.modality = nexent_core_gateway_modality_module
nexent_core_module.gateway = nexent_core_gateway_module
sys.modules['nexent.core.gateway'] = nexent_core_gateway_module
sys.modules['nexent.core.gateway.modality'] = nexent_core_gateway_modality_module

# Mock nexent.vector_database modules
vector_db_base_module = types.ModuleType('nexent.vector_database.base')


class MockVectorDatabaseCore:
    def __init__(self, *args, **kwargs):
        pass


vector_db_base_module.VectorDatabaseCore = MockVectorDatabaseCore
sys.modules['nexent.vector_database.base'] = vector_db_base_module
sys.modules['nexent.vector_database.elasticsearch_core'] = MagicMock()
if memory_pkg is not None:
    sys.modules["nexent.memory"] = memory_pkg
    nexent_mock.memory = memory_pkg
    if real_memory_service is not None:
        sys.modules["nexent.memory.memory_service"] = real_memory_service
sys.modules['nexent.vector_database.datamate_core'] = MagicMock()
# Mock nexent.storage module and its submodules before any imports
sys.modules['nexent.storage'] = _create_package_mock('nexent.storage')
sys.modules['nexent.storage'].__path__ = [str(SDK_ROOT / 'nexent' / 'storage')]
storage_factory_module = types.ModuleType('nexent.storage.storage_client_factory')
storage_config_module = types.ModuleType('nexent.storage.minio_config')


class MockMinIOStorageConfig:
    def __init__(self, *args, **kwargs):
        pass

    def validate(self):
        pass


storage_factory_module.create_storage_client_from_config = MagicMock()
storage_factory_module.MinIOStorageConfig = MockMinIOStorageConfig
storage_config_module.MinIOStorageConfig = MockMinIOStorageConfig
sys.modules['nexent.storage.storage_client_factory'] = storage_factory_module
sys.modules['nexent.storage.minio_config'] = storage_config_module
nexent_storage_module = sys.modules['nexent.storage']
nexent_storage_module.storage_client_factory = storage_factory_module
nexent_storage_module.minio_config = storage_config_module
setattr(nexent_mock, 'storage', nexent_storage_module)

# Mock nexent.core.agents.agent_model
nexent_core_agents_module = _create_package_mock('nexent.core.agents')
nexent_core_agents_agent_model_module = types.ModuleType('nexent.core.agents.agent_model')
nexent_core_agents_agent_model_module.ToolConfig = MagicMock()
sys.modules['nexent.core.agents'] = nexent_core_agents_module
sys.modules['nexent.core.agents.agent_model'] = nexent_core_agents_agent_model_module

# Mock nexent.core.nlp
nexent_core_nlp_module = _create_package_mock('nexent.core.nlp')
nexent_core_nlp_tokenizer_module = types.ModuleType('nexent.core.nlp.tokenizer')
nexent_core_nlp_module.tokenizer = nexent_core_nlp_tokenizer_module
sys.modules['nexent.core.nlp'] = nexent_core_nlp_module
sys.modules['nexent.core.nlp.tokenizer'] = nexent_core_nlp_tokenizer_module

# Mock nexent.core.utils
nexent_core_utils_module = _create_package_mock('nexent.core.utils')
observer_module = types.ModuleType('nexent.core.utils.observer')
observer_module.MessageObserver = MagicMock
nexent_core_utils_module.observer = observer_module
sys.modules['nexent.core.utils'] = nexent_core_utils_module
sys.modules['nexent.core.utils.observer'] = observer_module

# Mock nexent.multi_modal
nexent_multi_modal_module = _create_package_mock('nexent.multi_modal')
multi_modal_utils_module = types.ModuleType('nexent.multi_modal.utils')
multi_modal_utils_module.parse_s3_url = MagicMock()
nexent_multi_modal_module.utils = multi_modal_utils_module
sys.modules['nexent.multi_modal'] = nexent_multi_modal_module
sys.modules['nexent.multi_modal.utils'] = multi_modal_utils_module

# Mock psycopg2 before infrastructure.rdb.client is imported
sys.modules['psycopg2'] = MagicMock()
sys.modules['psycopg2.pool'] = MagicMock()
sys.modules['psycopg2.extras'] = MagicMock()
sys.modules['psycopg2.extensions'] = MagicMock()

# Mock redis before management.services.knowledge_base.task_state is imported
sys.modules['redis'] = MagicMock()
sys.modules['redis.client'] = MagicMock()
sys.modules['redis.connection'] = MagicMock()
sys.modules['redis.lock'] = MagicMock()

# Mock services.* modules that vectordatabase_service imports
# These must be registered in sys.modules so import can find them
sys.modules['services'] = _create_package_mock('services')

# Create mock redis_service module
redis_service_mock = types.ModuleType('management.services.knowledge_base.task_state')
redis_service_mock.get_redis_service = MagicMock(return_value=MagicMock(
    is_task_cancelled=MagicMock(return_value=False),
    save_progress_info=MagicMock(return_value=True),
    delete_knowledgebase_records=MagicMock(return_value={'total_deleted': 0, 'tasks_cancelled': 0}),
    get_progress_info=MagicMock(return_value=None),
    get_error_info=MagicMock(return_value=None),
))
sys.modules['management.services.knowledge_base.task_state'] = redis_service_mock
setattr(sys.modules['services'], 'redis_service', redis_service_mock)

# Create mock group_service module
group_service_mock = types.ModuleType('management.services.permission.identity.groups')
group_service_mock.get_tenant_default_group_id = MagicMock(return_value=1)
sys.modules['management.services.permission.identity.groups'] = group_service_mock
setattr(sys.modules['services'], 'group_service', group_service_mock)

# Create mock asset_owner_visibility module
def _mock_postprocess_knowledge_visibility(items, caller_role=None, caller_tenant_id=None):
    return items


asset_owner_visibility_mock = types.ModuleType('management.services.permission.asset_owner')
asset_owner_visibility_mock.postprocess_knowledge_visibility = _mock_postprocess_knowledge_visibility
sys.modules['management.services.permission.asset_owner'] = asset_owner_visibility_mock
setattr(sys.modules['services'], 'asset_owner_visibility', asset_owner_visibility_mock)

storage_service_mock = types.ModuleType('management.services.knowledge_base.storage')
storage_service_mock.release_storage_charge = MagicMock(return_value=True)
storage_service_mock.resolve_storage_reference = MagicMock(return_value=None)
storage_service_mock.resolve_storage_object_knowledge = MagicMock(return_value=None)
sys.modules[
    'management.services.knowledge_base.storage'
] = storage_service_mock
setattr(
    sys.modules['services'],
    'knowledge_storage_service',
    storage_service_mock,
)

# Mock management.services.model.adapter so vectordatabase_service can import
# ``build_adapter_fresh`` (the gateway bridge). Tests that exercise the
# embedding/rerank paths patch the bound name on vectordatabase_service
# directly, so this mock only needs to satisfy the import.
model_gateway_service_mock = types.ModuleType('management.services.model.adapter')
model_gateway_service_mock.build_adapter_fresh = MagicMock()
sys.modules['management.services.model.adapter'] = model_gateway_service_mock
setattr(
    sys.modules['services'],
    'model_gateway_service',
    model_gateway_service_mock,
)

# Create mock utils modules - backend.utils needs __path__ for submodule lookups
utils_mock = types.ModuleType('utils')  # No __path__ so Python won't try submodule lookup
utils_mock.__path__ = []  # Empty __path__ to make it a namespace package
sys.modules['utils'] = utils_mock

# backend.utils needs to be a proper package with __path__ for submodules
backend_utils_mock = types.ModuleType('backend.utils')
backend_utils_mock.__path__ = []  # Empty __path__ makes it a namespace package
sys.modules['backend.utils'] = backend_utils_mock

file_management_utils_mock = types.ModuleType('management.services.file.upload')
file_management_utils_mock.get_file_size = MagicMock(return_value=0)
sys.modules['management.services.file.upload'] = file_management_utils_mock
setattr(sys.modules['utils'], 'file_management_utils', file_management_utils_mock)
setattr(sys.modules['backend.utils'], 'file_management_utils', file_management_utils_mock)

str_utils_mock = types.ModuleType('management.utils.serialization')
str_utils_mock.convert_list_to_string = lambda items: ",".join(str(item) for item in items) if items else ""
str_utils_mock.convert_string_to_list = lambda s: [int(x.strip()) for x in s.split(',') if x.strip().isdigit()] if s and s.strip() else []
sys.modules['management.utils.serialization'] = str_utils_mock
sys.modules['management.utils.serialization'] = str_utils_mock
setattr(sys.modules['utils'], 'str_utils', str_utils_mock)
setattr(sys.modules['backend.utils'], 'str_utils', str_utils_mock)

storage_key_utils_mock = types.ModuleType('management.services.file.preview')
storage_key_utils_mock.build_preview_pdf_object_key = MagicMock(return_value='preview/test.pdf')
sys.modules['management.services.file.preview'] = storage_key_utils_mock
sys.modules['management.services.file.preview'] = storage_key_utils_mock
setattr(sys.modules['utils'], 'storage_key_utils', storage_key_utils_mock)
setattr(sys.modules['backend.utils'], 'storage_key_utils', storage_key_utils_mock)

config_utils_mock = types.ModuleType('management.services.configuration.tenant.settings')
config_utils_mock.tenant_config_manager = MagicMock()
config_utils_mock.tenant_config_manager.get_app_config = MagicMock(return_value='')
config_utils_mock.tenant_config_manager.get_model_config = MagicMock(return_value={})
config_utils_mock.get_model_name_from_config = MagicMock(return_value='')
sys.modules['management.services.configuration.tenant.settings'] = config_utils_mock
sys.modules['management.services.configuration.tenant.settings'] = config_utils_mock
setattr(sys.modules['utils'], 'config_utils', config_utils_mock)
setattr(sys.modules['backend.utils'], 'config_utils', config_utils_mock)

knowledge_telemetry_mock = types.ModuleType('infrastructure.trace.knowledge')
knowledge_telemetry_mock.set_span_attributes = MagicMock()
knowledge_telemetry_mock.trace_knowledge_operation = MagicMock()
sys.modules['infrastructure.trace.knowledge'] = knowledge_telemetry_mock
setattr(sys.modules['utils'], 'knowledge_telemetry', knowledge_telemetry_mock)

# Shared mock instances for MinIO
storage_client_mock = MagicMock()
storage_client_mock.delete_file.return_value = (True, None)
minio_client_mock = MagicMock()
minio_client_mock.delete_file.return_value = (True, None)
minio_client_mock.storage_config = MagicMock()
minio_client_mock.storage_config.default_bucket = 'test-bucket'
minio_client_mock._storage_client = storage_client_mock

# Load actual backend modules so that patch targets resolve correctly
backend_module = importlib.import_module('backend')
sys.modules['backend'] = backend_module
# Set backend.utils as attribute so imports like 'from backend.utils.xxx import yyy' work
setattr(backend_module, 'utils', backend_utils_mock)
backend_database_client_module = importlib.import_module('infrastructure.rdb.client')
sys.modules['infrastructure.rdb.client'] = backend_database_client_module
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["infrastructure.rdb.client"])

# Storage deletion tests isolate Agent previews and binding persistence.
# Their actual implementations are covered in focused app/database tests.
for module_name, functions in {
    "management.db.agent.repository": ("query_knowledge_binding_agents",),
    "management.db.tool.repository": ("remove_tool_knowledge_references",),
    "management.db.conversation.repository": ("remove_conversation_knowledge_bindings",),
}.items():
    boundary_module = types.ModuleType(module_name)
    for function_name in functions:
        setattr(boundary_module, function_name, MagicMock())
    sys.modules[module_name] = boundary_module

# Apply patches AFTER loading the module (so patch targets resolve)
with patch('botocore.client.BaseClient._make_api_call'), \
        patch('elasticsearch.Elasticsearch', return_value=MagicMock()):
    from management.services.knowledge_base.management import KnowledgeBaseManagementService
    from management.services.knowledge_base.service import ElasticSearchService, KnowledgeBaseNeedsModelConfigError


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

        self.mock_embedding = MagicMock()
        self.mock_embedding.embedding_dim = 768
        self.mock_embedding.model = "test-model"
        self.mock_embedding.model_type = "text"

        # Patch get_embedding_model_by_id so it returns (None, None) when model_id is None.
        # This is critical because setUp also patches get_model_by_model_id, which would
        # otherwise cause get_embedding_model_by_id(tenant_id, None) to return a real mock
        # instance and populate embedding_model_name in create_index.
        self.get_embedding_model_by_id_patcher = patch(
            'management.services.knowledge_base.common.get_embedding_model_by_id')
        self.mock_get_embedding_by_id = self.get_embedding_model_by_id_patcher.start()
        self.mock_get_embedding_by_id.return_value = (None, None)

        self.get_model_by_id_patcher = patch(
            'management.services.knowledge_base.management.get_model_by_model_id')
        self.mock_get_model_by_id = self.get_model_by_id_patcher.start()
        self.mock_get_model_by_id.return_value = {
            "model_id": 1,
            "model_name": "test-model",
            "display_name": "Test model",
            "model_type": "embedding",
            "model_factory": "OpenAI-API-Compatible",
            "api_key": "test-key",
            "base_url": "https://api.example.com/v1/embeddings",
            "max_tokens": 768,
            "ssl_verify": True,
        }

        # Patch get_rerank_model for all tests
        self.get_rerank_model_patcher = patch(
            'management.services.model.resolver.get_rerank_model')
        self.mock_get_rerank = self.get_rerank_model_patcher.start()
        self.mock_rerank = MagicMock()
        self.mock_get_rerank.return_value = self.mock_rerank

        ElasticSearchService.accurate_search = staticmethod(
            _accurate_search_impl)
        ElasticSearchService.semantic_search = staticmethod(
            _semantic_search_impl)

    def tearDown(self):
        """Clean up resources after each test."""
        self.get_embedding_model_by_id_patcher.stop()
        self.get_model_by_id_patcher.stop()
        self.get_rerank_model_patcher.stop()
        if hasattr(ElasticSearchService, 'accurate_search'):
            del ElasticSearchService.accurate_search
        if hasattr(ElasticSearchService, 'semantic_search'):
            del ElasticSearchService.semantic_search












    # =============================================================================
    # Tests for create_knowledge_base with embedding_model_name parameter
    # =============================================================================
































    @patch('management.services.knowledge_base.files.read_knowledge_files')
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
        mock_get_files_status.return_value = [{'file_id': 'fixture-0', 'object_name': 'file2', 'status': 'PROCESSING', 'error_stage': 'PROCESS', 'forward_task_id': 'task123'}]

        # Execute
        async def run_test():
            return await ElasticSearchService.list_files(
                index_name="test_index",
                include_chunks=False,
                vdb_core=self.mock_vdb_core
            , user_id="user-1", tenant_id="tenant-1")

        result = asyncio.run(run_test())

        # Assert
        self.assertEqual(len(result["files"]), 2)
        self.assertEqual(result["files"][0]["status"], "COMPLETED")
        self.assertEqual(result["files"][1]["status"], "PROCESSING")
        self.mock_vdb_core.get_documents_detail.assert_called_once_with(
            "test_index")

    @patch('management.services.knowledge_base.task_state.get_redis_service')
    @patch('management.services.knowledge_base.files.get_file_size', return_value=12)
    @patch('management.services.knowledge_base.files.read_knowledge_files', new_callable=AsyncMock)
    def test_list_files_merges_lifecycle_rows_and_hides_tombstones(
        self, mock_get_files_status, mock_get_size, mock_redis
    ):
        """PG lifecycle rows should override legacy status and hide deleted paths."""
        self.mock_vdb_core.get_documents_detail.return_value = []
        mock_get_files_status.return_value = [{'file_id': 'fixture-0', 'object_name': 'legacy-ms', 'status': 'FAILED', 'error_stage': 'PROCESS', 'forward_task_id': 'task-legacy', 'uploaded_at': '2023-11-14T22:13:20+00:00', 'original_filename': 'legacy.txt'}]
        lifecycle_rows = [
            {"file_id": "deleted", "object_name": "deleted.txt", "status": "DELETED"},
            {
                "file_id": "failed",
                "object_name": "failed.txt",
                "original_filename": "failed.txt",
                "file_size": 4,
                "uploaded_at": "2024-01-01T00:00:00",
                "status": "FAILED",
                "stage": "FORWARD",
                "error_code": "FORWARD_FAILED",
                "error_message": "forward unavailable",
                "process_task_id": "task-failed",
                "failed_at": "2024-01-01T00:00:01",
            },
            {
                "file_id": "uploading",
                "object_name": "uploading.txt",
                "original_filename": "uploading.txt",
                "file_size": 2,
                "uploaded_at": "not-a-timestamp",
                "status": "UPLOADED",
            },
        ]
        mock_redis.return_value.get_error_info.return_value = "legacy parse error"

        mock_get_files_status.return_value += lifecycle_rows

        result = asyncio.run(
            ElasticSearchService.list_files("test_index", include_chunks=False, vdb_core=self.mock_vdb_core, user_id="user-1", tenant_id="tenant-1")
        )

        by_path = {item["path_or_url"]: item for item in result["files"]}
        assert "deleted.txt" not in by_path
        assert by_path["failed.txt"]["status"] == "FORWARD_FAILED"
        assert by_path["failed.txt"]["error_reason"] == "forward unavailable"
        assert by_path["failed.txt"]["file_id"] == "failed"
        assert by_path["uploading.txt"]["status"] == "WAIT_FOR_PROCESSING"
        assert by_path["legacy-ms"]["create_time"] == 1700000000000

    @patch('management.services.knowledge_base.task_state.get_redis_service')
    @patch('management.services.knowledge_base.files.read_knowledge_files', new_callable=AsyncMock)
    def test_list_files_keeps_legacy_effective_filename_over_lifecycle_name(
        self, mock_get_files_status, mock_redis
    ):
        """Existing ES/Redis effective names keep the old UI display contract."""
        self.mock_vdb_core.get_documents_detail.return_value = [{
            "path_or_url": "folder/data.txt",
            "filename": "data_1.txt",
            "file_size": 5,
            "create_time": "2024-01-01T00:00:00",
        }]
        mock_get_files_status.return_value = [{'file_id': 'fixture-0', 'object_name': 'folder/data.txt', 'status': 'FAILED', 'error_stage': 'PROCESS', 'forward_task_id': 'task-1', 'original_filename': 'data_1.txt'}]
        lifecycle_rows = [{
            "file_id": "fid-1",
            "object_name": "folder/data.txt",
            "original_filename": "data.txt",
            "status": "FAILED",
            "stage": "PROCESS",
            "error_code": "PARSE_FAILED",
        }]
        mock_redis.return_value.get_error_info.return_value = None

        mock_get_files_status.return_value += lifecycle_rows

        result = asyncio.run(
            ElasticSearchService.list_files("test_index", include_chunks=False, vdb_core=self.mock_vdb_core, user_id="user-1", tenant_id="tenant-1")
        )

        assert result["files"][0]["file"] == "data_1.txt"


    @patch('management.services.knowledge_base.files.read_knowledge_files')
    def test_list_files_with_chunks(self, mock_get_files_status):
        """
        Test listing files with document chunks included.

        This test verifies that:
        1. Files indexed in Elasticsearch are retrieved correctly
        2. Document chunks for each file are retrieved using msearch
        3. The chunks are included in the file details
        4. The chunk count comes from aggregation (chunk_count field)
        """
        # Setup - chunk_count from aggregation
        self.mock_vdb_core.get_documents_detail.return_value = [
            {
                "path_or_url": "file1",
                "filename": "file1.txt",
                "file_size": 1024,
                "create_time": "2023-01-01T12:00:00",
                "chunk_count": 1
            }
        ]
        mock_get_files_status.return_value = {}
        # Note: count() is no longer called - chunk_count comes from aggregation

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
            , user_id="user-1", tenant_id="tenant-1")

        result = asyncio.run(run_test())

        # Assert
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(len(result["files"][0]["chunks"]), 1)
        self.assertEqual(result["files"][0]["chunk_count"], 1)
        self.mock_vdb_core.multi_search.assert_called_once()

    @patch('management.services.knowledge_base.files.read_knowledge_files')
    def test_list_files_msearch_error(self, mock_get_files_status):
        """
        Test listing files when msearch encounters an error.

        This test verifies that:
        1. When msearch fails, the method handles the error gracefully
        2. Files are still returned without chunks
        3. Chunk count is set to 0 for affected files
        4. The overall operation doesn't fail due to msearch errors
        """
        # Setup - chunk_count from aggregation
        self.mock_vdb_core.get_documents_detail.return_value = [
            {
                "path_or_url": "file1",
                "filename": "file1.txt",
                "file_size": 1024,
                "create_time": "2023-01-01T12:00:00",
                "chunk_count": 1
            }
        ]
        mock_get_files_status.return_value = {}
        # Note: count() is no longer called

        # Mock msearch error
        self.mock_vdb_core.multi_search.side_effect = Exception("MSSearch Error")

        # Execute
        async def run_test():
            return await ElasticSearchService.list_files(
                index_name="test_index",
                include_chunks=True,
                vdb_core=self.mock_vdb_core
            , user_id="user-1", tenant_id="tenant-1")

        result = asyncio.run(run_test())

        # Assert
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(len(result["files"][0]["chunks"]), 0)
        self.assertEqual(result["files"][0]["chunk_count"], 1)


    @patch('management.services.knowledge_base.files.file_exists', return_value=False)
    def test_compute_source_available_completed_missing_minio(self, _mock_exists):
        available = ElasticSearchService._compute_source_available({
            "path_or_url": "knowledge_base/doc.pdf",
            "status": "COMPLETED",
        })
        self.assertFalse(available)

    def test_compute_source_available_processing_defaults_true(self):
        available = ElasticSearchService._compute_source_available({
            "path_or_url": "knowledge_base/doc.pdf",
            "status": "PROCESSING",
        })
        self.assertTrue(available)


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

    @patch('management.services.knowledge_base.service.get_embedding_model_by_index_name')
    def test_search_hybrid_success(self, mock_get_embedding_by_index):
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
                "scores": {"accurate": 0.85, "semantic": 0.95},
                "highlight_terms": ["Content1"],
            }
        ]
        mock_get_embedding_by_index.return_value = (self.mock_embedding, 1, {"status": "ok", "message": "OK"})

        # Execute
        result = ElasticSearchService.search_hybrid(
            index_names=["test_index"],
            query="test query",
            tenant_id=identity_constants.DEFAULT_TENANT_ID,
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
        self.assertEqual(
            result["results"][0]["score_details"]["retrieval_highlight_terms"],
            ["Content1"],
        )
        self.mock_vdb_core.hybrid_search.assert_called_once_with(
            index_names=["test_index"],
            query_text="test query",
            embedding_model=self.mock_embedding,
            top_k=10,
            weight_accurate=0.5
        )
        mock_get_embedding_by_index.assert_called_once_with(identity_constants.DEFAULT_TENANT_ID, "test_index")

    def test_apply_document_tag_predicates_keeps_only_matching_documents(self):
        tag_projection_module = types.ModuleType('management.services.knowledge_base.tag_projection')
        tag_projection_module.LOCAL_DOCUMENT_PROVIDER = 'local'
        tag_projection_module.decode_document_resource_id = (
            lambda resource_id: tuple(resource_id.split(':', 2))
        )
        tag_management_module = types.ModuleType('management.services.tag.library')
        tag_management_module.TagManagementService = type(
            'TagManagementService',
            (),
            {
                'filter_document_ids_by_predicates': staticmethod(
                    lambda *_args: ['local:test_index:matched.md']
                )
            },
        )

        with patch.dict(
            sys.modules,
            {
                'management.services.knowledge_base.tag_projection': tag_projection_module,
                'management.services.tag.library': tag_management_module,
            },
        ):
            results = ElasticSearchService._apply_document_tag_predicates(
                [
                    {'index': 'test_index', 'path_or_url': 'matched.md'},
                    {'index': 'test_index', 'path_or_url': 'other.md'},
                ],
                tenant_id='tenant-1',
                index_names=['test_index'],
                tag_predicates=[{'key': 'topic', 'values': ['marketing']}],
            )

        self.assertEqual(results, [{'index': 'test_index', 'path_or_url': 'matched.md'}])

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

    @patch('management.services.knowledge_base.service.get_embedding_model_by_index_name')
    def test_search_hybrid_no_embedding_model(self, mock_get_embedding_by_index):
        """Test search_hybrid raises model-config error when embedding model is not configured."""
        mock_get_embedding_by_index.return_value = (
            None,
            None,
            {"status": "needs_config", "message": "needs config"},
        )
        with self.assertRaises(KnowledgeBaseNeedsModelConfigError):
            ElasticSearchService.search_hybrid(
                index_names=["test_index"],
                query="test query",
                tenant_id=identity_constants.DEFAULT_TENANT_ID,
                top_k=10,
                weight_accurate=0.5,
                vdb_core=self.mock_vdb_core
            )

    @patch('management.services.knowledge_base.service.get_embedding_model_by_index_name')
    def test_search_hybrid_exception(self, mock_get_embedding_by_index):
        """Test search_hybrid handles exceptions from vdb_core."""
        # Mock get_embedding_model_by_index_name
        mock_get_embedding_by_index.return_value = (self.mock_embedding, 1, {"status": "ok", "message": "OK"})

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

    @patch('management.services.knowledge_base.service.get_embedding_model_by_index_name')
    def test_search_hybrid_weight_accurate_boundary_values(self, mock_get_embedding_by_index):

        # Test with weight_accurate = 0.0 (semantic only)
        self.mock_vdb_core.hybrid_search.return_value = [
            {
                "document": {"title": "Doc1", "content": "Content1"},
                "score": 0.90,
                "index": "test_index",
            }
        ]
        mock_get_embedding_by_index.return_value = (self.mock_embedding, 1, {"status": "ok", "message": "OK"})

        result = ElasticSearchService.search_hybrid(
            index_names=["test_index"],
            query="test query",
            tenant_id=identity_constants.DEFAULT_TENANT_ID,
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
            tenant_id=identity_constants.DEFAULT_TENANT_ID,
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
            tenant_id=identity_constants.DEFAULT_TENANT_ID,
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

            # Basic functionality test - just verify the response is correct type
            # The detailed function calls are tested in their own unit tests






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

    @patch('management.services.knowledge_base.service.update_last_summary_time')
    @patch('management.services.knowledge_base.service.update_knowledge_record')
    def test_change_summary(self, mock_update_record, mock_update_last_summary):
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

    @patch('management.services.knowledge_base.management.update_knowledge_record')
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

    @patch('management.services.knowledge_base.management.update_knowledge_record')
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
        self.assertNotIn("quota_limit_bytes", call_args)

    @patch('management.services.knowledge_base.management.update_knowledge_record')
    def test_update_knowledge_base_clear_quota(self, mock_update_record):
        """Test that an explicit None clears the knowledge base quota."""
        mock_update_record.return_value = True

        result = self.es_service.update_knowledge_base(
            index_name="test_index",
            quota_limit_bytes=None,
            user_id="test_user"
        )

        self.assertTrue(result)
        call_args = mock_update_record.call_args[0][0]
        self.assertIn("quota_limit_bytes", call_args)
        self.assertIsNone(call_args["quota_limit_bytes"])

    @patch('management.services.knowledge_base.management.update_knowledge_record')
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
        with patch('management.services.knowledge_base.management.update_knowledge_record') as mock_update:
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

    @patch('management.services.knowledge_base.management.update_knowledge_record')
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

    @patch('management.services.knowledge_base.management.update_knowledge_record')
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

    @patch('management.services.knowledge_base.management.update_knowledge_record')
    @patch('management.services.knowledge_base.management.get_knowledge_record')
    def test_update_knowledge_base_user_can_rename_own_private_kb(
        self, mock_get_record, mock_update_record
    ):
        """A USER may update non-permission fields of their own PRIVATE KB."""
        mock_get_record.return_value = {
            "index_name": "test_index",
            "ingroup_permission": "PRIVATE",
            "created_by": "test_user",
        }
        mock_update_record.return_value = True

        result = self.es_service.update_knowledge_base(
            index_name="test_index",
            knowledge_name="New Name",
            user_id="test_user",
            user_role="USER",
        )

        self.assertTrue(result)
        call_args = mock_update_record.call_args[0][0]
        self.assertEqual(call_args["knowledge_name"], "New Name")
        self.assertNotIn("ingroup_permission", call_args)
        self.assertNotIn("group_ids", call_args)

    @patch('management.services.knowledge_base.management.update_knowledge_record')
    @patch('management.services.knowledge_base.management.get_knowledge_record')
    def test_update_knowledge_base_user_cannot_make_private_shared(
        self, mock_get_record, mock_update_record
    ):
        """A USER changing a PRIVATE KB to EDIT is rejected."""
        mock_get_record.return_value = {
            "index_name": "test_index",
            "ingroup_permission": "PRIVATE",
            "created_by": "test_user",
        }

        with self.assertRaises(PermissionError) as context:
            self.es_service.update_knowledge_base(
                index_name="test_index",
                ingroup_permission="EDIT",
                user_id="test_user",
                user_role="USER",
            )

        self.assertIn("cannot turn a personal knowledge base", str(context.exception))
        mock_update_record.assert_not_called()

    @patch('management.services.knowledge_base.management.update_knowledge_record')
    @patch('management.services.knowledge_base.management.get_knowledge_record')
    def test_update_knowledge_base_user_cannot_assign_groups(
        self, mock_get_record, mock_update_record
    ):
        """A USER assigning groups to a PRIVATE KB is rejected."""
        mock_get_record.return_value = {
            "index_name": "test_index",
            "ingroup_permission": "PRIVATE",
            "created_by": "test_user",
        }

        with self.assertRaises(PermissionError) as context:
            self.es_service.update_knowledge_base(
                index_name="test_index",
                group_ids=[10],
                user_id="test_user",
                user_role="USER",
            )

        self.assertIn("cannot assign groups", str(context.exception))
        mock_update_record.assert_not_called()

    @patch('management.services.knowledge_base.management.update_knowledge_record')
    @patch('management.services.knowledge_base.management.get_knowledge_record')
    def test_update_knowledge_base_user_missing_record_raises(
        self, mock_get_record, mock_update_record
    ):
        """A USER updating a missing KB gets a not-found error."""
        mock_get_record.return_value = None

        with self.assertRaises(ValueError) as context:
            self.es_service.update_knowledge_base(
                index_name="missing",
                knowledge_name="New Name",
                user_id="test_user",
                user_role="USER",
            )

        self.assertIn("not found", str(context.exception))
        mock_update_record.assert_not_called()

    @patch('management.services.knowledge_base.service.get_knowledge_record')
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

    @patch('management.services.knowledge_base.service.get_knowledge_record')
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

        result = ElasticSearchService.get_external_file_chunks(
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

        result = ElasticSearchService.get_external_file_chunks(
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
            ElasticSearchService.get_external_file_chunks(
                index_name="kb-index",
                vdb_core=self.mock_vdb_core
            )

        self.assertIn(
            "Error retrieving chunks from index kb-index: boom", str(exc.exception))











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



    @patch('management.services.knowledge_base.service.get_knowledge_record')
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



    def test_get_vdb_core(self):
        """
        Test get_vdb_core function returns the elastic_core instance.

        This test verifies that:
        1. The get_vdb_core function returns the correct elastic_core instance
        2. The function is properly imported and accessible
        """
        from management.services.knowledge_base.service import get_vector_db_core

        # Execute
        result = get_vector_db_core()

        # Assert
        self.assertIsNotNone(result)
        # The result should be the elastic_core instance
        self.assertTrue(hasattr(result, 'client'))





class TestRethrowOrPlain(unittest.TestCase):
    def setUp(self):
        self.es_service = ElasticSearchService()
        self.mock_vdb_core = MagicMock()
        self.mock_vdb_core.embedding_model = MagicMock()
        self.mock_vdb_core.embedding_dim = 768

        self.get_embedding_model_patcher = patch(
            'management.services.knowledge_base.common.get_embedding_model_by_id')
        self.mock_get_embedding = self.get_embedding_model_patcher.start()
        self.mock_embedding = MagicMock()
        self.mock_embedding.embedding_dim = 768
        self.mock_embedding.model = "test-model"
        self.mock_get_embedding.return_value = self.mock_embedding

        self.get_rerank_model_patcher = patch(
            'management.services.model.resolver.get_rerank_model')
        self.mock_get_rerank = self.get_rerank_model_patcher.start()
        self.mock_rerank = MagicMock()
        self.mock_get_rerank.return_value = self.mock_rerank

    def tearDown(self):
        self.get_embedding_model_patcher.stop()
        self.get_rerank_model_patcher.stop()

    def test_rethrow_or_plain_rethrows_json_error_code(self):
        """_rethrow_or_plain should re-raise JSON payload when error_code present."""
        from management.services.knowledge_base.service import _rethrow_or_plain

        with self.assertRaises(Exception) as exc:
            _rethrow_or_plain(
                Exception('{"error_code":"E123","detail":"boom"}'))
        self.assertIn('"error_code": "E123"', str(exc.exception))

    def test_get_vector_db_core_unsupported_type(self):
        """get_vector_db_core raises on unsupported db type."""
        from management.services.knowledge_base.service import get_vector_db_core

        with self.assertRaises(ValueError) as exc:
            get_vector_db_core(db_type="unsupported")

        self.assertIn("Unsupported vector database type", str(exc.exception))

    @patch('management.services.knowledge_base.common.datamate_configuration_url')
    @patch('infrastructure.vdb.client.DataMateCore')
    def test_get_vector_db_core_datamate_type(self, mock_datamate_core, mock_tenant_config_manager):
        """get_vector_db_core returns DataMateCore for DATAMATE type."""
        from management.services.knowledge_base.service import get_vector_db_core
        from contracts.knowledge import VectorDatabaseType
        from contracts.constants.constants import DATAMATE_URL

        # Setup mocks
        mock_tenant_config_manager.return_value = DATAMATE_URL
        mock_datamate_core.return_value = MagicMock()

        # Execute
        result = get_vector_db_core(db_type=VectorDatabaseType.DATAMATE, tenant_id="test-tenant")

        # Assert
        mock_tenant_config_manager.assert_called_once_with("test-tenant")
        mock_datamate_core.assert_called_once_with(base_url=DATAMATE_URL)
        self.assertEqual(result, mock_datamate_core.return_value)

    @patch('management.services.knowledge_base.common.datamate_configuration_url')
    @patch('infrastructure.vdb.client.DataMateCore')
    def test_get_vector_db_core_datamate_success(self, mock_datamate_core, mock_tenant_config_manager):
        """get_vector_db_core returns DataMateCore when DATAMATE type with valid tenant_id and configured URL."""
        from management.services.knowledge_base.service import get_vector_db_core
        from contracts.knowledge import VectorDatabaseType
        from contracts.constants.constants import DATAMATE_URL

        # Setup mocks
        mock_tenant_config_manager.return_value = "https://datamate.example.com"
        mock_datamate_instance = MagicMock()
        mock_datamate_core.return_value = mock_datamate_instance

        # Execute
        result = get_vector_db_core(
            db_type=VectorDatabaseType.DATAMATE, tenant_id="test-tenant")

        # Assert
        self.assertEqual(result, mock_datamate_instance)
        mock_tenant_config_manager.assert_called_once_with("test-tenant")
        mock_datamate_core.assert_called_once_with(
            base_url="https://datamate.example.com")

    @patch('management.services.knowledge_base.common.datamate_configuration_url')
    def test_get_vector_db_core_datamate_no_url_configured(self, mock_tenant_config_manager):
        """get_vector_db_core raises ValueError when DATAMATE type with tenant_id but no URL configured."""
        from management.services.knowledge_base.service import get_vector_db_core
        from contracts.knowledge import VectorDatabaseType

        # Setup mock to return None (no URL configured)
        mock_tenant_config_manager.return_value = None

        # Execute and Assert
        with self.assertRaises(ValueError) as exc:
            get_vector_db_core(
                db_type=VectorDatabaseType.DATAMATE, tenant_id="test-tenant")

        self.assertIn(
            "DataMate URL not configured for tenant test-tenant", str(exc.exception))
        mock_tenant_config_manager.assert_called_once()

    def test_get_vector_db_core_datamate_no_tenant_id(self):
        """get_vector_db_core raises ValueError when DATAMATE type without tenant_id."""
        from management.services.knowledge_base.service import get_vector_db_core
        from contracts.knowledge import VectorDatabaseType

        # Execute and Assert
        with self.assertRaises(ValueError) as exc:
            get_vector_db_core(
                db_type=VectorDatabaseType.DATAMATE, tenant_id=None)

        self.assertIn("tenant_id must be provided for DataMate",
                      str(exc.exception))

    def test_rethrow_or_plain_parses_error_code(self):
        """_rethrow_or_plain rethrows JSON error_code payloads unchanged."""
        from management.services.knowledge_base.service import _rethrow_or_plain

        with self.assertRaises(Exception) as exc:
            _rethrow_or_plain(Exception('{"error_code":123,"detail":"boom"}'))

        self.assertIn("error_code", str(exc.exception))



    def test_rethrow_or_plain_non_json_string(self):
        """_rethrow_or_plain should re-raise plain string message when not valid JSON."""
        from management.services.knowledge_base.service import _rethrow_or_plain

        plain_message = "This is a plain error message without JSON"

        with self.assertRaises(Exception) as exc:
            _rethrow_or_plain(Exception(plain_message))

        # Should re-raise the original string message
        self.assertEqual(str(exc.exception), plain_message)

    def test_rethrow_or_plain_json_without_error_code(self):
        """_rethrow_or_plain should re-raise plain string when JSON has no error_code."""
        from management.services.knowledge_base.service import _rethrow_or_plain

        json_message = '{"detail": "some error", "status": 500}'

        with self.assertRaises(Exception) as exc:
            _rethrow_or_plain(Exception(json_message))

        # Should re-raise the original string, not the JSON
        self.assertEqual(str(exc.exception), json_message)







    @patch('management.services.knowledge_base.files.read_knowledge_files')
    def test_list_files_handles_invalid_create_time_and_failed_tasks(self, mock_get_files_status):
        """list_files handles invalid timestamps, progress from read_knowledge_files, and error info."""
        # ES file with invalid timestamp and chunk_count from aggregation
        self.mock_vdb_core.get_documents_detail.return_value = [
            {
                "path_or_url": "file1",
                "filename": "file1.txt",
                "file_size": 10,
                "create_time": "invalid",
                "chunk_count": 1
            }
        ]
        # Note: count() is no longer called - chunk_count comes from aggregation

        # Progress and error info now come from read_knowledge_files (durable snapshot)
        mock_get_files_status.return_value = [{'file_id': 'fixture-0', 'object_name': 'file1', 'status': 'FAILED', 'error_stage': 'PROCESS', 'forward_task_id': 'task-1', 'processed_chunks': 2, 'total_chunks': 5, 'source_type': 'minio', 'original_filename': 'file1.txt'}]

        async def run_test():
            return await ElasticSearchService.list_files(
                index_name="idx",
                include_chunks=False,
                vdb_core=self.mock_vdb_core
            , user_id="user-1", tenant_id="tenant-1")

        result = asyncio.run(run_test())
        self.assertEqual(len(result["files"]), 1)
        file_info = result["files"][0]
        # chunk_count from aggregation (no longer uses count())
        self.assertEqual(file_info["chunk_count"], 1)
        self.assertEqual(file_info["file_size"], 10)
        self.assertEqual(file_info["status"], "PROCESS_FAILED")
        # Progress from read_knowledge_files
        self.assertEqual(file_info["processed_chunk_num"], 2)
        self.assertEqual(file_info["total_chunk_num"], 5)
        self.assertIsInstance(file_info["create_time"], int)

    @patch('management.services.knowledge_base.files.read_knowledge_files')
    def test_list_files_warning_and_progress_error_branches(self, mock_get_files_status):
        """list_files: chunk_count from aggregation, progress from read_knowledge_files, error handling."""
        # ES file - chunk_count from aggregation (no longer uses count())
        self.mock_vdb_core.get_documents_detail.return_value = [
            {
                "path_or_url": "file-es",
                "filename": "file-es.txt",
                "file_size": 5,
                "create_time": "2024-01-01T00:00:00",
                "chunk_count": 1
            }
        ]
        # Note: count() is no longer called - chunk_count comes from aggregation

        # Persisted lifecycle rows - progress already included (durable snapshot via read_knowledge_files)
        mock_get_files_status.return_value = [{'file_id': 'fixture-0', 'object_name': 'file-processing', 'status': 'PROCESSING', 'error_stage': 'PROCESS', 'forward_task_id': 't1', 'source_type': 'minio', 'original_filename': 'fp.txt', 'processed_chunks': 2, 'total_chunks': 4}, {'file_id': 'fixture-1', 'object_name': 'file-failed', 'status': 'FAILED', 'error_stage': 'PROCESS', 'forward_task_id': 't2', 'source_type': 'minio', 'original_filename': 'ff.txt'}]

        async def run_test():
            return await ElasticSearchService.list_files(
                index_name="idx",
                include_chunks=False,
                vdb_core=self.mock_vdb_core
            , user_id="user-1", tenant_id="tenant-1")

        result = asyncio.run(run_test())

        # Ensure both ES file and processing files are returned
        paths = {f["path_or_url"] for f in result["files"]}
        self.assertIn("file-es", paths)
        self.assertIn("file-processing", paths)
        self.assertIn("file-failed", paths)
        # Processing file gets progress from read_knowledge_files
        proc_file = next(
            f for f in result["files"] if f["path_or_url"] == "file-processing")
        self.assertEqual(proc_file["processed_chunk_num"], 2)
        self.assertEqual(proc_file["total_chunk_num"], 4)
        # ES file chunk_count from aggregation
        es_file = next(
            f for f in result["files"] if f["path_or_url"] == "file-es")
        self.assertEqual(es_file["chunk_count"], 1)

    @patch('management.services.knowledge_base.files.read_knowledge_files', return_value={})
    def test_list_files_with_chunks_updates_chunk_count(self, mock_get_files_status):
        """list_files include_chunks: chunk_count from aggregation, no extra count() calls."""
        self.mock_vdb_core.get_documents_detail.return_value = [
            {
                "path_or_url": "file1",
                "filename": "file1.txt",
                "file_size": 10,
                "create_time": "2024-01-01T00:00:00",
                "chunk_count": 2
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
        # Note: count() is no longer called - chunk_count comes from aggregation

        async def run_test():
            return await ElasticSearchService.list_files(
                index_name="idx",
                include_chunks=True,
                vdb_core=self.mock_vdb_core
            , user_id="user-1", tenant_id="tenant-1")

        result = asyncio.run(run_test())
        file_info = result["files"][0]
        self.assertEqual(file_info["chunk_count"], 2)
        self.assertEqual(len(file_info["chunks"]), 1)


    # Tests for get_rerank_model function
    @patch('management.services.model.resolver.get_model_records')
    @patch('management.services.model.resolver.tenant_config_manager')
    def test_get_rerank_model_with_specific_model_name_found(
        self, mock_tenant_config, mock_get_records
    ):
        """Test get_rerank_model when specific model name is provided and found."""
        # Setup
        mock_get_records.return_value = [
            {
                "model_name": "gte-rerank-v2",
                "model_repo": "Alibaba-NLP",
                "base_url": "https://api.example.com",
                "api_key": "test-key",
                "ssl_verify": True
            }
        ]

        mock_config = {"model_type": "embedding"}
        mock_tenant_config.get_model_config.return_value = mock_config

        # Stop the mock from setUp to test the real function
        self.get_rerank_model_patcher.stop()

        try:
            with patch('management.services.model.resolver.build_adapter_fresh') as mock_build:
                mock_adapter = MagicMock()
                mock_build.return_value = mock_adapter

                # Execute
                from management.services.model.resolver import get_rerank_model
                result = get_rerank_model("tenant-123", "Alibaba-NLP/gte-rerank-v2")

                # Assert
                self.assertEqual(result, mock_adapter)
                mock_get_records.assert_called_once_with({"model_type": "rerank"}, "tenant-123")
                mock_build.assert_called_once_with(
                    {
                        "model_name": "gte-rerank-v2",
                        "model_repo": "Alibaba-NLP",
                        "base_url": "https://api.example.com",
                        "api_key": "test-key",
                        "ssl_verify": True,
                    },
                    "rerank",
                    "rerank",
                    "tenant-123",
                )
        finally:
            self.get_rerank_model_patcher.start()

    @patch('management.services.model.resolver.get_model_records')
    @patch('management.services.model.resolver.tenant_config_manager')
    def test_get_rerank_model_with_specific_model_name_not_found(
        self, mock_tenant_config, mock_get_records
    ):
        """Test get_rerank_model when specific model name is not found, falls back to default."""
        # Setup
        mock_get_records.return_value = [
            {
                "model_name": "other-model",
                "model_repo": "some-repo",
                "base_url": "https://other.api.com",
                "api_key": "other-key",
                "ssl_verify": False
            }
        ]

        mock_config = {
            "model_type": "rerank",
            "model_name": "default-rerank",
            "base_url": "https://default.api.com",
            "api_key": "default-key",
            "ssl_verify": True
        }
        mock_tenant_config.get_model_config.return_value = mock_config

        # Stop the mock from setUp to test the real function
        self.get_rerank_model_patcher.stop()

        try:
            with patch('management.services.model.resolver.build_adapter_fresh') as mock_build:
                mock_adapter = MagicMock()
                mock_build.return_value = mock_adapter

                # Execute
                from management.services.model.resolver import get_rerank_model
                result = get_rerank_model("tenant-123", "nonexistent-model")

                # Assert
                self.assertEqual(result, mock_adapter)
                mock_get_records.assert_called_once()
                mock_tenant_config.get_model_config.assert_called_with(
                    key="RERANK_ID", tenant_id="tenant-123"
                )
                mock_build.assert_called_once_with(
                    {
                        "model_type": "rerank",
                        "model_name": "default-rerank",
                        "base_url": "https://default.api.com",
                        "api_key": "default-key",
                        "ssl_verify": True,
                    },
                    "rerank",
                    "rerank",
                    "tenant-123",
                )
        finally:
            self.get_rerank_model_patcher.start()

    @patch('management.services.model.resolver.get_model_records')
    @patch('management.services.model.resolver.tenant_config_manager')
    def test_get_rerank_model_with_specific_model_name_exception(
        self, mock_tenant_config, mock_get_records
    ):
        """Test get_rerank_model when get_model_records throws an exception."""
        # Setup
        mock_get_records.side_effect = Exception("Database error")

        mock_config = {
            "model_type": "rerank",
            "model_name": "default-rerank",
            "base_url": "https://default.api.com",
            "api_key": "default-key",
            "ssl_verify": True
        }
        mock_tenant_config.get_model_config.return_value = mock_config

        # Stop the mock from setUp to test the real function
        self.get_rerank_model_patcher.stop()

        try:
            with patch('management.services.model.resolver.build_adapter_fresh') as mock_build:
                mock_adapter = MagicMock()
                mock_build.return_value = mock_adapter

                # Execute
                from management.services.model.resolver import get_rerank_model
                result = get_rerank_model("tenant-123", "some-model")

                # Assert
                # Should fall back to default model when exception occurs
                self.assertEqual(result, mock_adapter)
                mock_build.assert_called_once_with(
                    {
                        "model_type": "rerank",
                        "model_name": "default-rerank",
                        "base_url": "https://default.api.com",
                        "api_key": "default-key",
                        "ssl_verify": True,
                    },
                    "rerank",
                    "rerank",
                    "tenant-123",
                )
        finally:
            self.get_rerank_model_patcher.start()

    @patch('management.services.model.resolver.tenant_config_manager')
    def test_get_rerank_model_default_rerank_type(self, mock_tenant_config):
        """Test get_rerank_model with default rerank model when model_type is rerank."""
        # Setup
        mock_config = {
            "model_type": "rerank",
            "model_name": "default-rerank",
            "base_url": "https://api.dashscope.aliyuncs.com",
            "api_key": "secret-key",
            "ssl_verify": True
        }
        mock_tenant_config.get_model_config.return_value = mock_config

        # Stop the mock from setUp to test the real function
        self.get_rerank_model_patcher.stop()

        try:
            with patch('management.services.model.resolver.build_adapter_fresh') as mock_build:
                mock_adapter = MagicMock()
                mock_build.return_value = mock_adapter

                # Execute
                from management.services.model.resolver import get_rerank_model
                result = get_rerank_model("tenant-123")

                # Assert
                self.assertEqual(result, mock_adapter)
                mock_tenant_config.get_model_config.assert_called_once_with(
                    key="RERANK_ID", tenant_id="tenant-123"
                )
                mock_build.assert_called_once_with(
                    {
                        "model_type": "rerank",
                        "model_name": "default-rerank",
                        "base_url": "https://api.dashscope.aliyuncs.com",
                        "api_key": "secret-key",
                        "ssl_verify": True,
                    },
                    "rerank",
                    "rerank",
                    "tenant-123",
                )
        finally:
            self.get_rerank_model_patcher.start()

    @patch('management.services.model.resolver.tenant_config_manager')
    def test_get_rerank_model_non_rerank_type_returns_none(self, mock_tenant_config):
        """Test get_rerank_model returns None when model_type is not rerank."""
        # Setup
        mock_config = {
            "model_type": "embedding",
            "model_name": "embedding-model",
            "base_url": "https://api.example.com",
            "api_key": "key"
        }
        mock_tenant_config.get_model_config.return_value = mock_config

        # Stop the mock from setUp to test the real function
        self.get_rerank_model_patcher.stop()

        try:
            # Execute
            from management.services.model.resolver import get_rerank_model
            result = get_rerank_model("tenant-123")

            # Assert
            self.assertIsNone(result)
        finally:
            self.get_rerank_model_patcher.start()

    @patch('management.services.model.resolver.tenant_config_manager')
    def test_get_rerank_model_empty_config(self, mock_tenant_config):
        """Test get_rerank_model returns None when model config is empty."""
        # Setup
        mock_tenant_config.get_model_config.return_value = {}

        # Stop the mock from setUp to test the real function
        self.get_rerank_model_patcher.stop()

        try:
            # Execute
            from management.services.model.resolver import get_rerank_model
            result = get_rerank_model("tenant-123")

            # Assert
            self.assertIsNone(result)
        finally:
            self.get_rerank_model_patcher.start()

    @patch('management.services.model.resolver.get_model_records')
    @patch('management.services.model.resolver.tenant_config_manager')
    def test_get_rerank_model_with_model_name_no_repo(
        self, mock_tenant_config, mock_get_records
    ):
        """Test get_rerank_model when model has no model_repo."""
        # Setup
        mock_get_records.return_value = [
            {
                "model_name": "gte-rerank-v2",
                "model_repo": None,
                "base_url": "https://api.example.com",
                "api_key": "test-key",
                "ssl_verify": True
            }
        ]

        mock_config = {"model_type": "embedding"}
        mock_tenant_config.get_model_config.return_value = mock_config

        # Stop the mock from setUp to test the real function
        self.get_rerank_model_patcher.stop()

        try:
            with patch('management.services.model.resolver.build_adapter_fresh') as mock_build:
                mock_adapter = MagicMock()
                mock_build.return_value = mock_adapter

                # Execute
                from management.services.model.resolver import get_rerank_model
                result = get_rerank_model("tenant-123", "gte-rerank-v2")

                # Assert
                self.assertEqual(result, mock_adapter)
                mock_build.assert_called_once_with(
                    {
                        "model_name": "gte-rerank-v2",
                        "model_repo": None,
                        "base_url": "https://api.example.com",
                        "api_key": "test-key",
                        "ssl_verify": True,
                    },
                    "rerank",
                    "rerank",
                    "tenant-123",
                )
        finally:
            self.get_rerank_model_patcher.start()





class TestNewEmbeddingModelMethods(unittest.TestCase):
    """
    Test new embedding model methods:
    - _get_embedding_model_display_name
    - get_embedding_model_by_index_name
    - get_embedding_model_by_id
    - update_embedding_model
    """

    def setUp(self):
        """Set up test environment."""
        self.es_service = ElasticSearchService()
        self.mock_vdb_core = MagicMock()

        # Patch get_embedding_model for tests that might use it indirectly
        self.get_embedding_model_patcher = patch(
            'management.services.knowledge_base.common.get_embedding_model_by_id')
        self.mock_get_embedding = self.get_embedding_model_patcher.start()

        # Patch get_rerank_model
        self.get_rerank_model_patcher = patch(
            'management.services.model.resolver.get_rerank_model')
        self.mock_get_rerank = self.get_rerank_model_patcher.start()

    def tearDown(self):
        """Clean up resources."""
        self.get_embedding_model_patcher.stop()
        self.get_rerank_model_patcher.stop()

    # Tests for get_embedding_model_by_index_name (lines 110-182)
    @patch('management.services.knowledge_base.common.get_knowledge_record')
    def test_get_embedding_model_by_index_name_kb_not_found(self, mock_get_knowledge):
        """
        Test get_embedding_model_by_index_name when knowledge base is not found.

        This test verifies that:
        1. When knowledge base doesn't exist, returns error status
        2. Error message indicates knowledge base not found
        """
        from management.services.knowledge_base.common import get_embedding_model_by_index_name

        mock_get_knowledge.return_value = None

        model, model_id, metadata = get_embedding_model_by_index_name("tenant-1", "kb-index")

        self.assertIsNone(model)
        self.assertIsNone(model_id)
        self.assertEqual(metadata["status"], "error")
        self.assertEqual(metadata["needs_update"], False)
        self.assertIn("not found", metadata["message"])

    @patch('management.services.knowledge_base.common.get_embedding_model_by_id')
    @patch('management.services.knowledge_base.common.get_knowledge_record')
    def test_get_embedding_model_by_index_name_model_id_valid(self, mock_get_knowledge, mock_get_model_by_id):
        """
        Test get_embedding_model_by_index_name when model_id exists and model is valid.

        This test verifies that:
        1. When model_id exists and model is found, returns ok status
        2. Model instance and model_id are returned correctly
        """
        from management.services.knowledge_base.common import get_embedding_model_by_index_name

        mock_get_knowledge.return_value = {
            "index_name": "kb-index",
            "tenant_id": "tenant-1",
            "embedding_model_id": 123,
            "embedding_model_name": "test-model"
        }

        mock_embedding = MagicMock()
        mock_get_model_by_id.return_value = (mock_embedding, 123)

        model, model_id, metadata = get_embedding_model_by_index_name("tenant-1", "kb-index")

        self.assertIsNotNone(model)
        self.assertEqual(model_id, 123)
        self.assertEqual(metadata["status"], "ok")
        self.assertEqual(metadata["needs_update"], False)
        self.assertEqual(metadata["message"], "Embedding model found")

    @patch('management.services.knowledge_base.common.get_embedding_model_by_id')
    @patch('management.services.knowledge_base.common.get_knowledge_record')
    def test_get_embedding_model_by_index_name_model_id_invalid(self, mock_get_knowledge, mock_get_model_by_id):
        """
        Test get_embedding_model_by_index_name when model_id exists but model is not found.

        This test verifies that:
        1. When model_id exists but model not found, returns needs_config status
        2. Guidance message for user to select a model
        """
        from management.services.knowledge_base.common import get_embedding_model_by_index_name

        mock_get_knowledge.return_value = {
            "index_name": "kb-index",
            "tenant_id": "tenant-1",
            "embedding_model_id": 999,
            "embedding_model_name": "test-model"
        }

        mock_get_model_by_id.return_value = (None, None)

        with patch('management.services.knowledge_base.common.logger') as mock_logger:
            model, model_id, metadata = get_embedding_model_by_index_name("tenant-1", "kb-index")

            self.assertIsNone(model)
            self.assertIsNone(model_id)
            self.assertEqual(metadata["status"], "needs_config")
            self.assertEqual(metadata["needs_update"], False)
            self.assertIn("Please select a model", metadata["message"])
            mock_logger.warning.assert_called()

    @patch('management.services.knowledge_base.common.get_embedding_model_by_id')
    @patch('management.services.knowledge_base.common.get_knowledge_record')
    def test_get_embedding_model_by_index_name_no_model_id_with_name(self, mock_get_knowledge, mock_get_model_by_id):
        """
        Test get_embedding_model_by_index_name when no model_id but has embedding_model_name (legacy data).

        This test verifies that:
        1. When model_id is None/0 but embedding_model_name exists (legacy), returns needs_config
        2. Warning is logged about legacy data needing explicit configuration
        """
        from management.services.knowledge_base.common import get_embedding_model_by_index_name

        mock_get_knowledge.return_value = {
            "index_name": "kb-index",
            "tenant_id": "tenant-1",
            "embedding_model_id": None,
            "embedding_model_name": "legacy-model"
        }

        mock_get_model_by_id.return_value = (None, None)

        with patch('management.services.knowledge_base.common.logger') as mock_logger:
            model, model_id, metadata = get_embedding_model_by_index_name("tenant-1", "kb-index")

            self.assertIsNone(model)
            self.assertIsNone(model_id)
            self.assertEqual(metadata["status"], "needs_config")
            mock_logger.warning.assert_called()
            # Check that warning mentions legacy data
            warning_msg = mock_logger.warning.call_args[0][0]
            self.assertIn("has embedding_model_name", warning_msg)

    @patch('management.services.knowledge_base.common.get_embedding_model_by_id')
    @patch('management.services.knowledge_base.common.get_knowledge_record')
    def test_get_embedding_model_by_index_name_no_model_at_all(self, mock_get_knowledge, mock_get_model_by_id):
        """
        Test get_embedding_model_by_index_name when no model configured at all.

        This test verifies that:
        1. When both model_id and embedding_model_name are None, returns needs_config
        2. Error is logged
        """
        from management.services.knowledge_base.common import get_embedding_model_by_index_name

        mock_get_knowledge.return_value = {
            "index_name": "kb-index",
            "tenant_id": "tenant-1",
            "embedding_model_id": None,
            "embedding_model_name": None
        }

        mock_get_model_by_id.return_value = (None, None)

        with patch('management.services.knowledge_base.common.logger') as mock_logger:
            model, model_id, metadata = get_embedding_model_by_index_name("tenant-1", "kb-index")

            self.assertIsNone(model)
            self.assertIsNone(model_id)
            self.assertEqual(metadata["status"], "needs_config")
            mock_logger.error.assert_called_once()
            error_msg = mock_logger.error.call_args[0][0]
            self.assertIn("no embedding model configured", error_msg)

    @patch('management.services.knowledge_base.common.get_knowledge_record')
    def test_get_embedding_model_by_index_name_exception(self, mock_get_knowledge):
        """
        Test get_embedding_model_by_index_name when exception occurs.

        This test verifies that:
        1. When exception occurs, returns error status with exception message
        2. Exception is logged as warning
        """
        from management.services.knowledge_base.common import get_embedding_model_by_index_name

        mock_get_knowledge.side_effect = Exception("Database error")

        with patch('management.services.knowledge_base.common.logger') as mock_logger:
            model, model_id, metadata = get_embedding_model_by_index_name("tenant-1", "kb-index")

            self.assertIsNone(model)
            self.assertIsNone(model_id)
            self.assertEqual(metadata["status"], "error")
            self.assertEqual(metadata["message"], "Database error")
            mock_logger.warning.assert_called()

    # Tests for get_embedding_model_by_id (lines 338-383)
    @patch('management.services.model.resolver.get_model_by_model_id')
    @patch('management.services.model.resolver.build_adapter_fresh')
    def test_get_embedding_model_by_id_embedding_type(self, mock_build, mock_get_model):
        """
        Test get_embedding_model_by_id with embedding model type.

        This test verifies that:
        1. When model_type is 'embedding', the adapter is built via build_adapter_fresh
        2. Correct parameters are passed to build_adapter_fresh
        3. Model instance and model_id are returned
        """
        from management.services.model.resolver import get_embedding_model_by_id

        mock_get_model.return_value = {
            "model_id": 123,
            "model_type": "embedding",
            "model_name": "text-embedding-3-small",
            "model_repo": "openai",
            "api_key": "test-key",
            "base_url": "https://api.openai.com",
            "max_tokens": 1536,
            "ssl_verify": True
        }

        mock_adapter = MagicMock()
        mock_build.return_value = mock_adapter

        model, model_id = get_embedding_model_by_id("tenant-1", 123)

        self.assertEqual(model, mock_adapter)
        self.assertEqual(model_id, 123)
        mock_get_model.assert_called_once_with(123, "tenant-1")
        mock_build.assert_called_once_with(
            {
                "model_repo": "openai",
                "model_name": "text-embedding-3-small",
                "api_key": "test-key",
                "base_url": "https://api.openai.com",
                "model_type": "embedding",
                "max_tokens": 1536,
                "ssl_verify": True,
            },
            "embedding",
            "embedding",
            None,
        )

    @patch('management.services.model.resolver.get_model_by_model_id')
    @patch('management.services.model.resolver.build_adapter_fresh')
    def test_get_embedding_model_by_id_multi_embedding_type(self, mock_build, mock_get_model):
        """
        Test get_embedding_model_by_id with multi_embedding model type.

        This test verifies that:
        1. When model_type is 'multi_embedding', the adapter is built via build_adapter_fresh
        2. Correct parameters are passed to build_adapter_fresh
        """
        from management.services.model.resolver import get_embedding_model_by_id

        mock_get_model.return_value = {
            "model_id": 456,
            "model_type": "multi_embedding",
            "model_name": "jina-embeddings-v2",
            "model_repo": "jinaai",
            "api_key": "jina-key",
            "base_url": "https://api.jina.ai",
            "max_tokens": 2048,
            "ssl_verify": False
        }

        mock_adapter = MagicMock()
        mock_build.return_value = mock_adapter

        model, model_id = get_embedding_model_by_id("tenant-1", 456)

        self.assertEqual(model, mock_adapter)
        self.assertEqual(model_id, 456)
        mock_build.assert_called_once_with(
            {
                "model_repo": "jinaai",
                "model_name": "jina-embeddings-v2",
                "api_key": "jina-key",
                "base_url": "https://api.jina.ai",
                "model_type": "multi_embedding",
                "max_tokens": 2048,
                "ssl_verify": False,
            },
            "multi_embedding",
            "multiEmbedding",
            None,
        )

    @patch('management.services.model.resolver.get_model_by_model_id')
    @patch('management.services.model.resolver.build_adapter_fresh')
    def test_get_embedding_model_by_id_uses_declared_embedding_type(
        self, mock_build, mock_get_model
    ):
        """Endpoint shape cannot override a model record declared as text embedding."""
        from management.services.model.resolver import get_embedding_model_by_id

        mock_get_model.return_value = {
            "model_id": 61,
            "model_type": "embedding",
            "model_factory": "dashscope",
            "model_name": "qwen3-vl-embedding",
            "model_repo": "dashscope",
            "api_key": "dashscope-key",
            "base_url": "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
            "max_tokens": 2560,
            "ssl_verify": True,
        }
        mock_adapter = MagicMock()
        mock_build.return_value = mock_adapter

        model, model_id = get_embedding_model_by_id("tenant-1", 61)

        self.assertEqual(model, mock_adapter)
        self.assertEqual(model_id, 61)
        mock_build.assert_called_once_with(
            {
                "model_repo": "dashscope",
                "model_name": "qwen3-vl-embedding",
                "api_key": "dashscope-key",
                "base_url": "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
                "model_type": "embedding",
                "model_factory": "dashscope",
                "max_tokens": 2560,
                "ssl_verify": True,
            },
            "embedding",
            "embedding",
            None,
        )

    @patch('management.services.model.resolver.get_model_by_model_id')
    @patch('management.services.model.resolver.build_adapter_fresh')
    def test_get_embedding_model_by_id_dashscope_multi_embedding(
        self, mock_build, mock_get_model
    ):
        """Test that a DashScope model selected by ID is built via the adapter registry."""
        from management.services.model.resolver import get_embedding_model_by_id

        mock_get_model.return_value = {
            "model_id": 48,
            "model_type": "multi_embedding",
            "model_factory": "dashscope",
            "model_name": "multimodal-embedding-v1",
            "model_repo": "dashscope",
            "api_key": "dashscope-key",
            "base_url": "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
            "max_tokens": 1024,
            "ssl_verify": True,
        }
        mock_adapter = MagicMock()
        mock_build.return_value = mock_adapter

        model, model_id = get_embedding_model_by_id("tenant-1", 48)

        self.assertEqual(model, mock_adapter)
        self.assertEqual(model_id, 48)
        mock_build.assert_called_once_with(
            {
                "model_repo": "dashscope",
                "model_name": "multimodal-embedding-v1",
                "api_key": "dashscope-key",
                "base_url": "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
                "model_type": "multi_embedding",
                "model_factory": "dashscope",
                "max_tokens": 1024,
                "ssl_verify": True,
            },
            "multi_embedding",
            "multiEmbedding",
            None,
        )

    @patch('management.services.model.resolver.get_model_by_model_id')
    def test_get_embedding_model_by_id_model_not_found(self, mock_get_model):
        """
        Test get_embedding_model_by_id when model is not found.

        This test verifies that:
        1. When model is not found (returns None), returns (None, None)
        2. Warning is logged
        """
        from management.services.model.resolver import get_embedding_model_by_id

        mock_get_model.return_value = None

        with patch('management.services.model.resolver.logger') as mock_logger:
            model, model_id = get_embedding_model_by_id("tenant-1", 999)

            self.assertIsNone(model)
            self.assertIsNone(model_id)
            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            self.assertIn("not found", warning_msg)

    @patch('management.services.model.resolver.get_model_by_model_id')
    def test_get_embedding_model_by_id_wrong_model_type(self, mock_get_model):
        """
        Test get_embedding_model_by_id when model type is not embedding/multi_embedding.

        This test verifies that:
        1. When model_type is not valid, returns (None, None)
        2. Warning is logged about wrong model type
        """
        from management.services.model.resolver import get_embedding_model_by_id

        mock_get_model.return_value = {
            "model_id": 789,
            "model_type": "rerank",
            "model_name": "rerank-model"
        }

        with patch('management.services.model.resolver.logger') as mock_logger:
            model, model_id = get_embedding_model_by_id("tenant-1", 789)

            self.assertIsNone(model)
            self.assertIsNone(model_id)
            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            self.assertIn("not an embedding model", warning_msg)

    @patch('management.services.model.resolver.get_model_by_model_id')
    def test_get_embedding_model_by_id_exception(self, mock_get_model):
        """
        Test get_embedding_model_by_id when exception occurs.

        This test verifies that:
        1. When exception occurs, returns (None, None)
        2. Warning is logged with exception message
        """
        from management.services.model.resolver import get_embedding_model_by_id

        mock_get_model.side_effect = Exception("Database connection failed")

        with patch('management.services.model.resolver.logger') as mock_logger:
            model, model_id = get_embedding_model_by_id("tenant-1", 123)

            self.assertIsNone(model)
            self.assertIsNone(model_id)
            mock_logger.warning.assert_called_once()

    # Tests for update_embedding_model (lines 725-793)
    @patch('management.services.knowledge_base.management.update_embedding_model_by_index_name')
    @patch('management.services.knowledge_base.management.get_model_by_model_id')
    def test_update_embedding_model_success(self, mock_get_model, mock_update):
        """
        Test update_embedding_model when update succeeds.

        This test verifies that:
        1. When model exists and is embedding type, update succeeds
        2. Database update function is called with correct parameters
        3. Success response is returned with model info
        """
        mock_get_model.return_value = {
            "model_id": 123,
            "model_type": "embedding",
            "display_name": "text-embedding-3-small",
            "model_name": "text-embedding-3-small"
        }

        mock_update.return_value = True

        result = ElasticSearchService.update_embedding_model(
            index_name="kb-index",
            model_id=123,
            tenant_id="tenant-1",
            user_id="user-1"
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["model_id"], 123)
        self.assertEqual(result["model_name"], "text-embedding-3-small")
        mock_get_model.assert_called_once_with(123, "tenant-1")
        mock_update.assert_called_once()

    @patch('management.services.knowledge_base.management.get_model_by_model_id')
    def test_update_embedding_model_model_not_found(self, mock_get_model):
        """
        Test update_embedding_model when model is not found.

        This test verifies that:
        1. When model not found, ValueError is raised
        2. Error message indicates model not found
        """
        mock_get_model.return_value = None

        with self.assertRaises(ValueError) as context:
            ElasticSearchService.update_embedding_model(
                index_name="kb-index",
                model_id=999,
                tenant_id="tenant-1",
                user_id="user-1"
            )

        self.assertIn("not found", str(context.exception))

    @patch('management.services.knowledge_base.management.get_model_by_model_id')
    def test_update_embedding_model_wrong_model_type(self, mock_get_model):
        """
        Test update_embedding_model when model type is not embedding/multi_embedding.

        This test verifies that:
        1. When model type is invalid, ValueError is raised
        2. Error message indicates wrong model type
        """
        mock_get_model.return_value = {
            "model_id": 456,
            "model_type": "rerank",
            "display_name": "rerank-model"
        }

        with self.assertRaises(ValueError) as context:
            ElasticSearchService.update_embedding_model(
                index_name="kb-index",
                model_id=456,
                tenant_id="tenant-1",
                user_id="user-1"
            )

        self.assertIn("not an embedding model", str(context.exception))
        self.assertIn("Please select an embedding model", str(context.exception))

    @patch('management.services.knowledge_base.management.update_embedding_model_by_index_name')
    @patch('management.services.knowledge_base.management.get_model_by_model_id')
    def test_update_embedding_model_database_update_failed(self, mock_get_model, mock_update):
        """
        Test update_embedding_model when database update fails.

        This test verifies that:
        1. When database update returns False, Exception is raised
        2. Error message indicates update failed
        """
        mock_get_model.return_value = {
            "model_id": 123,
            "model_type": "embedding",
            "display_name": "test-model"
        }

        mock_update.return_value = False

        with self.assertRaises(Exception) as context:
            ElasticSearchService.update_embedding_model(
                index_name="kb-index",
                model_id=123,
                tenant_id="tenant-1",
                user_id="user-1"
            )

        self.assertIn("Failed to update embedding model", str(context.exception))

    @patch('management.services.knowledge_base.management.update_embedding_model_by_index_name')
    @patch('management.services.knowledge_base.management.get_model_by_model_id')
    def test_update_embedding_model_exception(self, mock_get_model, mock_update):
        """
        Test update_embedding_model when exception occurs.

        This test verifies that:
        1. When exception occurs (not ValueError), it's wrapped and re-raised
        2. Error message contains original exception
        """
        mock_get_model.return_value = {
            "model_id": 123,
            "model_type": "embedding",
            "display_name": "test-model"
        }

        mock_update.side_effect = Exception("Database connection lost")

        with self.assertRaises(Exception) as context:
            ElasticSearchService.update_embedding_model(
                index_name="kb-index",
                model_id=123,
                tenant_id="tenant-1",
                user_id="user-1"
            )

        self.assertIn("Failed to update embedding model", str(context.exception))

    @patch('management.services.knowledge_base.management.update_embedding_model_by_index_name')
    @patch('management.services.knowledge_base.management.get_model_by_model_id')
    def test_update_embedding_model_multi_embedding_type(self, mock_get_model, mock_update):
        """
        Test update_embedding_model with multi_embedding model type.

        This test verifies that:
        1. When model_type is 'multi_embedding', update succeeds
        2. Success response is returned correctly
        """
        mock_get_model.return_value = {
            "model_id": 789,
            "model_type": "multi_embedding",
            "display_name": "jina-embeddings-v2",
            "model_name": "jina-embeddings-v2"
        }

        mock_update.return_value = True

        result = ElasticSearchService.update_embedding_model(
            index_name="kb-index",
            model_id=789,
            tenant_id="tenant-1",
            user_id="user-1"
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["model_id"], 789)
        self.assertEqual(result["model_name"], "jina-embeddings-v2")

    @patch('management.services.knowledge_base.management.update_embedding_model_by_index_name')
    @patch('management.services.knowledge_base.management.get_model_by_model_id')
    def test_update_embedding_model_without_user_id(self, mock_get_model, mock_update):
        """
        Test update_embedding_model when user_id is not provided.

        This test verifies that:
        1. When user_id is None, update still succeeds
        2. Empty string is passed to database update function
        """
        mock_get_model.return_value = {
            "model_id": 123,
            "model_type": "embedding",
            "display_name": "test-model"
        }

        mock_update.return_value = True

        result = ElasticSearchService.update_embedding_model(
            index_name="kb-index",
            model_id=123,
            tenant_id="tenant-1",
            user_id=None
        )

        self.assertEqual(result["status"], "success")
        # Verify that empty string was passed as user_id
        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args[1]
        self.assertEqual(call_kwargs["user_id"], "")


class TestCoverageImprovement(unittest.TestCase):
    """Test cases to improve coverage for uncovered lines."""

    def setUp(self):
        self.mock_vdb_core = MagicMock()
        self.mock_vdb_core.embedding_model = MagicMock()
        self.mock_vdb_core.embedding_dim = 768

    # Tests for _update_progress (lines 54-80)



    # Tests for index_documents - non-dict item skip (lines 1087-1089)
    # Note: The non-dict skip is tested via assertion of logger call.
    # The actual code path for skipping is covered by the document transformation logic.

    # Tests for index_documents - progress save returns False (lines 1169-1170)

    # Tests for list_files - file count exception (lines 1264-1267)
    @pytest.mark.asyncio
    async def test_list_files_file_count_exception(self):
        """Test list_files handles exception during file count query (lines 1264-1267)."""
        mock_vdb_core = MagicMock()
        mock_vdb_core.get_documents_detail.return_value = [
            {"path_or_url": "file1.txt", "filename": "file1.txt", "file_size": 100, "create_time": "2024-01-01T00:00:00"}
        ]
        mock_vdb_core.client.count.side_effect = Exception("Count query failed")
        # Return a file that's still being processed (not in ES yet)
        with patch('management.services.knowledge_base.files.read_knowledge_files',
                   new_callable=AsyncMock, return_value={}):
            result = await ElasticSearchService.list_files(
                index_name="test-index",
                include_chunks=False,
                vdb_core=mock_vdb_core,
             user_id="user-1", tenant_id="tenant-1")

        # Should return the file with count from aggregation fallback
        self.assertEqual(len(result["files"]), 1)

    # Tests for list_files with chunks - msearch exception (lines 1431-1433)
    @pytest.mark.asyncio
    async def test_list_files_with_chunks_msearch_exception(self):
        """Test list_files handles exception during msearch (lines 1431-1433)."""
        mock_vdb_core = MagicMock()
        mock_vdb_core.get_documents_detail.return_value = [
            {"path_or_url": "file1.txt", "filename": "file1.txt", "file_size": 100,
             "create_time": "2024-01-01T00:00:00", "status": "COMPLETED"}
        ]
        mock_vdb_core.client.count.return_value = {"count": 1}
        mock_vdb_core.multi_search.side_effect = Exception("Msearch failed")
        with patch('management.services.knowledge_base.files.read_knowledge_files',
                   new_callable=AsyncMock, return_value={}):
            result = await ElasticSearchService.list_files(
                index_name="test-index",
                include_chunks=True,
                vdb_core=mock_vdb_core,
             user_id="user-1", tenant_id="tenant-1")

        # Should return files even when msearch fails
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(result["files"][0]["chunks"], [])

    # Tests for list_files with chunks - count exception (lines 1426-1428)
    @pytest.mark.asyncio
    async def test_list_files_with_chunks_count_exception(self):
        """Test list_files handles exception during chunk count query (lines 1426-1428)."""
        mock_vdb_core = MagicMock()

        def count_side_effect(index, body):
            if "term" in str(body):
                raise Exception("Count query failed")
            return {"count": 1}

        mock_vdb_core.get_documents_detail.return_value = [
            {"path_or_url": "file1.txt", "filename": "file1.txt", "file_size": 100,
             "create_time": "2024-01-01T00:00:00", "status": "COMPLETED", "chunk_count": 1}
        ]
        mock_vdb_core.client.count.side_effect = count_side_effect
        mock_vdb_core.multi_search.return_value = {
            "responses": [
                {"hits": {"hits": [{"_source": {"id": "1", "title": "t", "content": "c"}}]}}
            ]
        }
        with patch('management.services.knowledge_base.files.read_knowledge_files',
                   new_callable=AsyncMock, return_value={}):
            result = await ElasticSearchService.list_files(
                index_name="test-index",
                include_chunks=True,
                vdb_core=mock_vdb_core,
             user_id="user-1", tenant_id="tenant-1")

        self.assertEqual(len(result["files"]), 1)

    # Tests for list_files without chunks - count exception (lines 1448-1450)
    @pytest.mark.asyncio
    async def test_list_files_without_chunks_count_exception(self):
        """Test list_files handles exception during count query without chunks (lines 1448-1450)."""
        mock_vdb_core = MagicMock()
        mock_vdb_core.get_documents_detail.return_value = [
            {"path_or_url": "file1.txt", "filename": "file1.txt", "file_size": 100,
             "create_time": "2024-01-01T00:00:00", "status": "COMPLETED", "chunk_count": 5}
        ]
        mock_vdb_core.client.count.side_effect = Exception("Count failed")
        with patch('management.services.knowledge_base.files.read_knowledge_files',
                   new_callable=AsyncMock, return_value={}):
            result = await ElasticSearchService.list_files(
                index_name="test-index",
                include_chunks=False,
                vdb_core=mock_vdb_core,
             user_id="user-1", tenant_id="tenant-1")

        # Should return file with fallback chunk_count from aggregation
        self.assertEqual(len(result["files"]), 1)

    # Tests for change_summary exception (lines 1705-1706)
    @patch('management.services.knowledge_base.service.update_knowledge_record')
    def test_change_summary_exception(self, mock_update):
        """Test change_summary handles exception from update_knowledge_record (lines 1705-1706)."""
        mock_update.side_effect = Exception("Database error")
        with self.assertRaises(Exception) as ctx:
            ElasticSearchService.change_summary(
                index_name="test-index",
                summary_result="New summary",
                user_id="user-1"
            )
        self.assertIn("Database error", str(ctx.exception))

    # Tests for get_summary exception (lines 1727-1729)
    @patch('management.services.knowledge_base.service.get_knowledge_record')
    def test_get_summary_exception(self, mock_get_record):
        """Test get_summary handles exception (lines 1727-1729)."""
        mock_get_record.side_effect = Exception("Database error")
        with self.assertRaises(Exception) as ctx:
            ElasticSearchService.get_summary(index_name="test-index")
        self.assertIn("Database error", str(ctx.exception))

    # Tests for create_chunk exception (lines 1858-1861)

    # Tests for update_chunk - no update payload (lines 1889-1890)
    # Note: The check `if not update_payload` is effectively dead code because
    # _build_chunk_payload always adds "update_time" and "updated_by" to the payload.
    # This line can only be reached if those fields are somehow falsy, which is unlikely.

    # Tests for update_chunk exception (lines 1899-1902)

    # Tests for delete_chunk exception (lines 1923-1926)

    # Tests for search_hybrid - KnowledgeBaseNeedsModelConfigError (line 1955, 1962)
    @patch('management.services.knowledge_base.service.get_embedding_model_by_index_name')
    def test_search_hybrid_needs_model_config_error(self, mock_get_model):
        """Test search_hybrid raises KnowledgeBaseNeedsModelConfigError (lines 1955, 1962)."""
        from management.services.knowledge_base.service import (
            KnowledgeBaseNeedsModelConfigError, get_embedding_model_by_index_name
        )
        mock_get_model.return_value = (None, None, {"status": "needs_config"})
        with self.assertRaises(KnowledgeBaseNeedsModelConfigError) as ctx:
            ElasticSearchService.search_hybrid(
                index_names=["test-index"],
                query="test query",
                tenant_id="tenant-1",
                top_k=10,
                vdb_core=self.mock_vdb_core,
            )
        self.assertEqual(ctx.exception.index_name, "test-index")

    # Tests for search_hybrid - generic ValueError from get_embedding_model_by_index_name (line 1996)
    @patch('management.services.knowledge_base.service.get_embedding_model_by_index_name')
    def test_search_hybrid_model_error_status(self, mock_get_model):
        """Test search_hybrid handles error status from get_embedding_model_by_index_name (line 1996)."""
        # Note: When status is "error", it doesn't raise ValueError.
        # It raises the generic Exception from the else branch.
        mock_get_model.return_value = (None, None, {"status": "error", "message": "KB not found"})
        with self.assertRaises(Exception) as ctx:
            ElasticSearchService.search_hybrid(
                index_names=["nonexistent-index"],
                query="test query",
                tenant_id="tenant-1",
                top_k=10,
                vdb_core=self.mock_vdb_core,
            )
        self.assertIn("embedding model", str(ctx.exception).lower())

    # Tests for search_hybrid - exception (line 1996)
    @patch('management.services.knowledge_base.service.get_embedding_model_by_index_name')
    def test_search_hybrid_vdb_exception(self, mock_get_model):
        """Test search_hybrid handles exception from vdb_core (line 1996)."""
        mock_model = MagicMock()
        mock_get_model.return_value = (mock_model, 1, {"status": "ok"})
        self.mock_vdb_core.hybrid_search.side_effect = Exception("Hybrid search failed")
        with self.assertRaises(Exception) as ctx:
            ElasticSearchService.search_hybrid(
                index_names=["test-index"],
                query="test query",
                tenant_id="tenant-1",
                top_k=10,
                vdb_core=self.mock_vdb_core,
            )
        self.assertIn("Hybrid search failed", str(ctx.exception))


    # Tests for create_index - no model_id provided (line 572)

    # Tests for delete_index - list_files exception (lines 818-820)

    # Tests for list_indices - empty user_group_ids (line 939)

    # Tests for list_indices - creator permission (line 951)

    # Tests for list_indices - private permission (line 959-960)
    # Note: The PRIVATE permission branch (lines 959-960) sets permission=None which correctly
    # excludes the KB from the result. This code path is difficult to isolate in unit tests
    # due to the interaction with other permission logic. The overall permission handling is
    # validated by other tests in TestElasticSearchService class.

    # Tests for index_documents - empty index_name (line 1070)

    # Tests for index_documents - index creation exception (lines 1078-1079)

    # Tests for list_files - msearch response error (lines 1401-1403)
    @pytest.mark.asyncio
    async def test_list_files_msearch_response_error(self):
        """Test list_files handles error in msearch response (lines 1401-1403)."""
        mock_vdb_core = MagicMock()
        mock_vdb_core.get_documents_detail.return_value = [
            {"path_or_url": "file1.txt", "filename": "file1.txt", "file_size": 100,
             "create_time": "2024-01-01T00:00:00", "status": "COMPLETED", "chunk_count": 1}
        ]
        mock_vdb_core.client.count.return_value = {"count": 1}
        # Return error in first response
        mock_vdb_core.multi_search.return_value = {
            "responses": [{"error": "Search failed"}]
        }
        with patch('management.services.knowledge_base.files.read_knowledge_files',
                   new_callable=AsyncMock, return_value={}):
            result = await ElasticSearchService.list_files(
                index_name="test-index",
                include_chunks=True,
                vdb_core=mock_vdb_core,
             user_id="user-1", tenant_id="tenant-1")

        # Should still return the file with empty chunks
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(result["files"][0]["chunks"], [])

    # Tests for get_random_documents - outer exception (lines 1670-1671)
    def test_get_random_documents_exception(self):
        """Test get_random_documents handles outer exception (lines 1670-1671)."""
        self.mock_vdb_core.count_documents.side_effect = Exception("Connection lost")

        with self.assertRaises(Exception) as ctx:
            ElasticSearchService.get_random_documents(
                index_name="test-index",
                vdb_core=self.mock_vdb_core,
            )
        self.assertIn("Connection lost", str(ctx.exception))

    # Tests for create_chunk - knowledge_record exception (lines 1812-1813)

    # Tests for create_chunk - embedding generation exception (lines 1829-1830)

    # Tests for update_chunk - empty payload (line 1890)

    # Tests for list_indices - no user tenant (line 879)

    # ===== Coverage improvement: remaining uncovered branches =====

    def test_create_embedding_model_dashscope(self):
        """Test _create_embedding_model builds a dashscope multi_embedding adapter via build_adapter_fresh."""
        from management.services.model.resolver import create_embedding_model
        with patch('management.services.model.resolver.build_adapter_fresh') as mock_build:
            mock_adapter = MagicMock()
            mock_build.return_value = mock_adapter
            result = create_embedding_model({
                "model_name": "bge-m3",
                "model_type": "multi_embedding",
                "model_factory": "dashscope",
                "api_key": "test-key",
                "base_url": "https://api.example.com",
            })
        # Should return the adapter built via build_adapter_fresh
        self.assertEqual(result, mock_adapter)
        mock_build.assert_called_once_with(
            {
                "model_repo": "",
                "model_name": "bge-m3",
                "api_key": "test-key",
                "base_url": "https://api.example.com",
                "model_type": "multi_embedding",
                "model_factory": "dashscope",
                "max_tokens": 1024,
                "ssl_verify": True,
            },
            "multi_embedding",
            "multiEmbedding",
            None,
        )

    def test_create_embedding_model_siliconflow(self):
        """Siliconflow multi-embedding models are built via build_adapter_fresh with the multiEmbedding slot."""
        from management.services.model.resolver import create_embedding_model
        with patch('management.services.model.resolver.build_adapter_fresh') as mock_build:
            mock_adapter = MagicMock()
            mock_build.return_value = mock_adapter
            result = create_embedding_model({
                "model_name": "Qwen/Qwen3-VL-Embedding-8B",
                "model_type": "multi_embedding",
                "model_factory": "silicon",
                "api_key": "test-key",
                "base_url": "https://api.siliconflow.cn/v1/embeddings",
            })

        self.assertEqual(result, mock_adapter)
        mock_build.assert_called_once_with(
            {
                "model_repo": "",
                "model_name": "Qwen/Qwen3-VL-Embedding-8B",
                "api_key": "test-key",
                "base_url": "https://api.siliconflow.cn/v1/embeddings",
                "model_type": "multi_embedding",
                "model_factory": "silicon",
                "max_tokens": 1024,
                "ssl_verify": True,
            },
            "multi_embedding",
            "multiEmbedding",
            None,
        )

    # Tests for create_knowledge_base model ID validation



    # Tests for delete_index - MINIO file deletion loop (lines 862-871)


    # Tests for list_indices - ASSET_OWNER record with SU/ADMIN/SPEED/DEV (lines 975-978)



    # Tests for list_indices - PRIVATE permission (lines 1021-1022)

    # Tests for list_indices - group intersection scenario (lines 1001, 1013, 1016)



    # Tests for index_documents - skip non-dict items (lines 1156-1158)

    # Tests for index_documents - image bytes fetch exception and raise (lines 1206-1214)

    # Tests for list_files - file_size exception (lines 1382-1386)
    @pytest.mark.asyncio
    async def test_list_files_file_size_exception(self):
        """Test list_files handles exception when getting file size (lines 1382-1386)."""
        mock_vdb_core = MagicMock()
        mock_vdb_core.get_documents_detail.return_value = []
        mock_vdb_core.multi_search.return_value = {"responses": []}

        async def mock_get_files(index_name):
            return [{'file_id': 'fixture-0', 'object_name': 'file1.txt', 'status': 'COMPLETED', 'error_stage': 'PROCESS', 'source_type': 'minio'}]

        with patch('management.services.knowledge_base.files.read_knowledge_files', mock_get_files), \
                patch('management.services.knowledge_base.files.get_file_size',
                      side_effect=Exception("Storage error")):
            result = await ElasticSearchService.list_files(
                index_name="test-index",
                include_chunks=False,
                vdb_core=mock_vdb_core,
             user_id="user-1", tenant_id="tenant-1")

        self.assertIn("files", result)
        self.assertGreater(len(result["files"]), 0)
        # file_size should be 0 due to exception
        self.assertEqual(result["files"][0].get("file_size"), 0)

    # Tests for list_files - redis error info exception (lines 1414-1421)
    @pytest.mark.asyncio
    async def test_list_files_redis_error_info_exception(self):
        """Test list_files handles exception when getting error info from Redis (lines 1414-1421)."""
        mock_vdb_core = MagicMock()
        mock_vdb_core.get_documents_detail.return_value = []

        async def mock_get_files(index_name):
            return [{'file_id': 'fixture-0', 'object_name': 'failed_file.txt', 'status': 'FAILED', 'error_stage': 'PROCESS', 'forward_task_id': 'task-42', 'source_type': 'minio'}]

        with patch('management.services.knowledge_base.files.read_knowledge_files', mock_get_files), \
                patch('management.services.knowledge_base.task_state.get_redis_service') as mock_get_redis:
            mock_redis_instance = MagicMock()
            mock_redis_instance.get_error_info.side_effect = Exception("Redis error")
            mock_get_redis.return_value = mock_redis_instance
            result = await ElasticSearchService.list_files(
                index_name="test-index",
                include_chunks=False,
                vdb_core=mock_vdb_core,
             user_id="user-1", tenant_id="tenant-1")

        self.assertIn("files", result)

    # Tests for list_files - msearch response error (lines 1459-1462)
    @pytest.mark.asyncio
    async def test_list_files_msearch_response_error(self):
        """Test list_files handles error in msearch response (lines 1459-1462)."""
        mock_vdb_core = MagicMock()
        mock_vdb_core.get_documents_detail.return_value = [
            {"path_or_url": "file1.txt", "filename": "file1.txt", "file_size": 100,
             "create_time": "2024-01-01T00:00:00", "status": "COMPLETED", "chunk_count": 1}
        ]
        mock_vdb_core.multi_search.return_value = {
            "responses": [{"error": "Search failed"}]  # Error in response
        }

        async def mock_get_files(index_name):
            return [{'file_id': 'fixture-0', 'object_name': 'file1.txt', 'status': 'COMPLETED', 'error_stage': 'PROCESS', 'source_type': 'minio'}]

        with patch('management.services.knowledge_base.files.read_knowledge_files', mock_get_files):
            result = await ElasticSearchService.list_files(
                index_name="test-index",
                include_chunks=True,
                vdb_core=mock_vdb_core,
             user_id="user-1", tenant_id="tenant-1")

        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(result["files"][0]["chunks"], [])

    # Tests for list_files - outer exception (lines 1497-1498)
    @pytest.mark.asyncio
    async def test_list_files_outer_exception(self):
        """Test list_files raises exception from get_documents_detail (lines 1497-1498)."""
        mock_vdb_core = MagicMock()
        mock_vdb_core.get_documents_detail.side_effect = Exception("Elasticsearch unavailable")

        with patch('management.services.knowledge_base.files.read_knowledge_files',
                   new_callable=AsyncMock, return_value={}):
            with self.assertRaises(Exception) as ctx:
                await ElasticSearchService.list_files(
                    index_name="test-index",
                    include_chunks=False,
                    vdb_core=mock_vdb_core,
                 user_id="user-1", tenant_id="tenant-1")
        self.assertIn("Elasticsearch unavailable", str(ctx.exception))

    # Tests for search_hybrid - outer exception (lines 2038-2043)
    @patch('management.services.knowledge_base.service.get_embedding_model_by_index_name')
    def test_search_hybrid_outer_exception(self, mock_get_model):
        """Test search_hybrid handles unexpected exceptions (lines 2038-2043)."""
        mock_model = MagicMock()
        mock_get_model.return_value = (mock_model, 1, {"status": "ok"})
        self.mock_vdb_core.hybrid_search.side_effect = RuntimeError("Unexpected error")

        with self.assertRaises(Exception) as ctx:
            ElasticSearchService.search_hybrid(
                index_names=["test-index"],
                query="test query",
                tenant_id="tenant-1",
                top_k=10,
                vdb_core=self.mock_vdb_core,
            )
        self.assertIn("Error executing hybrid search", str(ctx.exception))

    # Tests for search_hybrid - KnowledgeBaseNeedsModelConfigError (lines 1998-2004)
    @patch('management.services.knowledge_base.service.get_embedding_model_by_index_name')
    def test_search_hybrid_needs_config_raises(self, mock_get_model):
        """Test search_hybrid raises KnowledgeBaseNeedsModelConfigError when model not configured."""
        mock_get_model.return_value = (None, None, {"status": "needs_config"})
        with self.assertRaises(Exception) as ctx:
            ElasticSearchService.search_hybrid(
                index_names=["unconfigured-kb"],
                query="test",
                tenant_id="tenant-1",
                top_k=10,
                vdb_core=self.mock_vdb_core,
            )
        # Should be wrapped as a generic Exception by search_hybrid's outer handler
        self.assertIn("embedding model", str(ctx.exception).lower())


from management.services.knowledge_base import permission as kb_permission


def _patch_kb_permission_context(
    monkeypatch,
    record,
    user_tenant=None,
    user_group_ids=None,
    speed_mode=False,
):
    from management.services.knowledge_base import permission as vdb_service

    monkeypatch.setattr(vdb_service, "get_knowledge_record", lambda _filters: record)
    monkeypatch.setattr(
        vdb_service,
        "get_user_tenant_by_user_id",
        lambda _user_id: user_tenant,
    )
    monkeypatch.setattr(
        vdb_service,
        "query_group_ids_by_user",
        lambda _user_id: user_group_ids or [],
    )
    monkeypatch.setattr(vdb_service, "ASSET_OWNER_TENANT_ID", "asset-owner")


def test_resolve_knowledge_base_permission_not_found(monkeypatch):
    _patch_kb_permission_context(monkeypatch, record=None)

    with pytest.raises(ValueError, match="not found"):
        ElasticSearchService.resolve_knowledge_base_permission(
            "missing-kb", "user-1", "tenant-1"
        )


def test_resolve_knowledge_base_permission_datamate_creator_is_read_only(monkeypatch):
    _patch_kb_permission_context(
        monkeypatch,
        record={
            "index_name": "datamate-kb",
            "knowledge_sources": "datamate",
            "tenant_id": "tenant-1",
            "created_by": "user-1",
        },
        user_tenant={"user_role": "USER", "tenant_id": "tenant-1"},
    )

    permission = ElasticSearchService.resolve_knowledge_base_permission(
        "datamate-kb", "user-1", "tenant-1"
    )

    assert permission == "READ_ONLY"


def test_resolve_knowledge_base_permission_missing_membership_is_denied(
    monkeypatch,
):
    _patch_kb_permission_context(
        monkeypatch,
        record={
            "index_name": "kb",
            "knowledge_sources": "elasticsearch",
            "tenant_id": "tenant-from-record",
            "created_by": "other-user",
            "ingroup_permission": "EDIT",
        },
        user_tenant=None,
        speed_mode=True,
    )
    monkeypatch.setattr(
        "management.services.knowledge_base.permission.ResourceAccessControl.check",
        lambda resource, **kwargs: SimpleNamespace(permission_label="EDIT"),
    )

    assert (
        ElasticSearchService.resolve_knowledge_base_permission(
            "kb", "speed-user", tenant_id=None
        )
        is None
    )


def test_resolve_knowledge_base_permission_datamate_cross_tenant_denied(monkeypatch):
    _patch_kb_permission_context(
        monkeypatch,
        record={
            "index_name": "datamate-kb",
            "knowledge_sources": "datamate",
            "tenant_id": "tenant-2",
            "created_by": "admin-user",
        },
        user_tenant={"user_role": "ADMIN", "tenant_id": "tenant-1"},
    )

    assert (
        ElasticSearchService.resolve_knowledge_base_permission(
            "datamate-kb", "admin-user", "tenant-1"
        )
        is None
    )


def test_resolve_knowledge_base_permission_datamate_user_non_owner_denied(monkeypatch):
    _patch_kb_permission_context(
        monkeypatch,
        record={
            "index_name": "datamate-kb",
            "knowledge_sources": "datamate",
            "tenant_id": "tenant-1",
            "created_by": "other-user",
        },
        user_tenant={"user_role": "USER", "tenant_id": "tenant-1"},
    )

    assert (
        ElasticSearchService.resolve_knowledge_base_permission(
            "datamate-kb", "user-1", "tenant-1"
        )
        is None
    )


def test_resolve_knowledge_base_permission_without_user_tenant_returns_none(monkeypatch):
    _patch_kb_permission_context(
        monkeypatch,
        record={
            "index_name": "kb",
            "knowledge_sources": "elasticsearch",
            "tenant_id": "tenant-1",
        },
        user_tenant=None,
    )

    assert (
        ElasticSearchService.resolve_knowledge_base_permission("kb", "user-1", "tenant-1")
        is None
    )


@pytest.mark.parametrize(
    "user_id,user_tenant,speed_mode,expected",
    [
        ("tenant-1", {"tenant_id": "tenant-1"}, False, None),
        ("missing-user", None, True, None),
        ("admin-user", {"user_role": "ADMIN", "tenant_id": "tenant-1"}, False, "EDIT"),
    ],
)
def test_resolve_knowledge_base_permission_admin_like_roles_edit(
    monkeypatch,
    user_id,
    user_tenant,
    speed_mode,
    expected,
):
    _patch_kb_permission_context(
        monkeypatch,
        record={
            "index_name": "kb",
            "knowledge_sources": "elasticsearch",
            "tenant_id": "tenant-1",
        },
        user_tenant=user_tenant,
        speed_mode=speed_mode,
    )

    assert (
        ElasticSearchService.resolve_knowledge_base_permission("kb", user_id, "tenant-1")
        == expected
    )


@pytest.mark.parametrize(
    "role,expected",
    [
        ("ASSET_OWNER", "EDIT"),
        ("SU", "READ_ONLY"),
        ("DEV", "READ_ONLY"),
        ("USER", None),
    ],
)
def test_resolve_knowledge_base_permission_asset_owner_record(monkeypatch, role, expected):
    _patch_kb_permission_context(
        monkeypatch,
        record={
            "index_name": "asset-kb",
            "knowledge_sources": "elasticsearch",
            "tenant_id": "asset-owner",
        },
        user_tenant={"user_role": role, "tenant_id": "tenant-1"},
    )

    assert (
        ElasticSearchService.resolve_knowledge_base_permission("asset-kb", "user-1", "tenant-1")
        == expected
    )


def test_resolve_knowledge_base_permission_cross_tenant_returns_none(monkeypatch):
    _patch_kb_permission_context(
        monkeypatch,
        record={
            "index_name": "kb",
            "knowledge_sources": "elasticsearch",
            "tenant_id": "tenant-2",
        },
        user_tenant={"user_role": "ADMIN", "tenant_id": "tenant-1"},
    )

    assert (
        ElasticSearchService.resolve_knowledge_base_permission("kb", "admin-user", "tenant-1")
        is None
    )


def test_resolve_knowledge_base_permission_unknown_role_is_rejected(monkeypatch):
    _patch_kb_permission_context(
        monkeypatch,
        record={
            "index_name": "kb",
            "knowledge_sources": "elasticsearch",
            "tenant_id": "tenant-1",
        },
        user_tenant={"user_role": "GUEST", "tenant_id": "tenant-1"},
    )

    with pytest.raises(ValueError, match="Unknown or retired role"):
        ElasticSearchService.resolve_knowledge_base_permission("kb", "guest-user", "tenant-1")


@pytest.mark.parametrize(
    "record,user_group_ids,expected",
    [
        ({"group_ids": "1,2", "created_by": "other", "ingroup_permission": "EDIT"}, [2], None),
        ({"group_ids": "1", "created_by": "other", "ingroup_permission": "READ_ONLY"}, [1], None),
        ({"group_ids": "1", "created_by": "other", "ingroup_permission": "PRIVATE"}, [1], None),
        ({"group_ids": "1", "created_by": "other", "ingroup_permission": "UNKNOWN"}, [1], None),
        ({"group_ids": "1", "created_by": "other", "ingroup_permission": "EDIT"}, [3], None),
        ({"group_ids": "", "created_by": "user-1", "ingroup_permission": "READ_ONLY"}, [], "CREATOR"),
        ({"group_ids": "9", "created_by": "user-1", "ingroup_permission": "PRIVATE"}, [], "CREATOR"),
        ({"group_ids": None, "created_by": "other"}, [], None),
    ],
)
def test_resolve_knowledge_base_permission_user_group_rules(
    monkeypatch,
    record,
    user_group_ids,
    expected,
):
    record = {
        "index_name": "kb",
        "knowledge_sources": "elasticsearch",
        "tenant_id": "tenant-1",
        **record,
    }
    _patch_kb_permission_context(
        monkeypatch,
        record=record,
        user_tenant={"user_role": "USER", "tenant_id": "tenant-1"},
        user_group_ids=user_group_ids,
    )

    assert (
        ElasticSearchService.resolve_knowledge_base_permission("kb", "user-1", "tenant-1")
        == expected
    )


def test_resolve_knowledge_base_permission_private_dev_creator_ignores_groups(monkeypatch):
    record = {
        "index_name": "kb",
        "knowledge_sources": "elasticsearch",
        "tenant_id": "tenant-1",
        "created_by": "dev-user",
        "group_ids": "9",
        "ingroup_permission": "PRIVATE",
    }
    _patch_kb_permission_context(
        monkeypatch,
        record=record,
        user_tenant={"user_role": "DEV", "tenant_id": "tenant-1"},
        user_group_ids=[],
    )

    assert (
        ElasticSearchService.resolve_knowledge_base_permission("kb", "dev-user", "tenant-1")
        == ElasticSearchService.CREATOR_PERMISSION
    )




def test_update_knowledge_base_user_rejects_shared_record(monkeypatch):
    monkeypatch.setattr(
        "management.services.knowledge_base.management.get_knowledge_record",
        lambda _filters: {"ingroup_permission": "EDIT"},
    )

    with pytest.raises(PermissionError, match="only manage PRIVATE"):
        ElasticSearchService.update_knowledge_base(
            index_name="shared-kb",
            knowledge_name="renamed",
            user_id="user-1",
            user_role="USER",
        )


@pytest.mark.parametrize("permission", ["EDIT", "CREATOR"])
def test_require_knowledge_base_edit_permission_allows_editors(monkeypatch, permission):
    monkeypatch.setattr(
        kb_permission,
        "resolve_knowledge_base_permission",
        staticmethod(lambda *_args, **_kwargs: permission),
    )

    assert (
        ElasticSearchService.require_knowledge_base_edit_permission("kb", "user-1", "tenant-1")
        == permission
    )


def test_require_knowledge_base_edit_permission_rejects_read_only(monkeypatch):
    monkeypatch.setattr(
        kb_permission,
        "resolve_knowledge_base_permission",
        staticmethod(lambda *_args, **_kwargs: "READ_ONLY"),
    )

    with pytest.raises(PermissionError, match="No permission"):
        ElasticSearchService.require_knowledge_base_edit_permission("kb", "user-1", "tenant-1")


# ============================================================================
# KB Read Permission Control Tests (Issue #3339)
# ============================================================================


@pytest.mark.parametrize("permission", ["READ_ONLY", "EDIT", "CREATOR"])
def test_require_knowledge_base_read_permission_allows_readers(monkeypatch, permission):
    """User with any non-None permission level can read the knowledge base."""
    monkeypatch.setattr(
        kb_permission,
        "resolve_knowledge_base_permission",
        staticmethod(lambda *_args, **_kwargs: permission),
    )

    assert (
        ElasticSearchService.require_knowledge_base_read_permission("kb", "user-1", "tenant-1")
        == permission
    )


def test_require_knowledge_base_read_permission_rejects_no_permission(monkeypatch):
    """User with None permission cannot read the knowledge base."""
    monkeypatch.setattr(
        kb_permission,
        "resolve_knowledge_base_permission",
        staticmethod(lambda *_args, **_kwargs: None),
    )

    with pytest.raises(PermissionError, match="No permission"):
        ElasticSearchService.require_knowledge_base_read_permission("kb", "user-1", "tenant-1")


def test_filter_accessible_indices_preserves_order(monkeypatch):
    """filter_accessible_indices returns accessible indices in original order."""
    permissions = {
        "kb1": "READ_ONLY",
        "kb2": None,
        "kb3": "EDIT",
        "kb4": None,
        "kb5": "CREATOR",
    }

    def mock_resolve(index_name, user_id, tenant_id=None):
        return permissions.get(index_name)

    monkeypatch.setattr(
        kb_permission,
        "resolve_knowledge_base_permission",
        staticmethod(mock_resolve),
    )

    result = ElasticSearchService.filter_accessible_indices(
        ["kb1", "kb2", "kb3", "kb4", "kb5"], "user-1", "tenant-1"
    )
    assert result == ["kb1", "kb3", "kb5"]


def test_filter_accessible_indices_empty_input():
    """Empty input returns empty output."""
    result = ElasticSearchService.filter_accessible_indices([], "user-1", "tenant-1")
    assert result == []


def test_filter_accessible_indices_all_accessible(monkeypatch):
    """When all indices are accessible, all are returned."""
    monkeypatch.setattr(
        kb_permission,
        "resolve_knowledge_base_permission",
        staticmethod(lambda *_args, **_kw: "READ_ONLY"),
    )

    result = ElasticSearchService.filter_accessible_indices(
        ["kb1", "kb2", "kb3"], "user-1", "tenant-1"
    )
    assert result == ["kb1", "kb2", "kb3"]


def test_filter_accessible_indices_none_accessible(monkeypatch):
    """When no indices are accessible, empty list is returned."""
    monkeypatch.setattr(
        kb_permission,
        "resolve_knowledge_base_permission",
        staticmethod(lambda *_args, **_kw: None),
    )

    result = ElasticSearchService.filter_accessible_indices(
        ["kb1", "kb2", "kb3"], "user-1", "tenant-1"
    )
    assert result == []


def test_filter_accessible_indices_handles_missing_kb_gracefully(monkeypatch):
    """When KB record is not found (ValueError), treat as inaccessible and continue."""

    def mock_resolve(index_name, user_id, tenant_id=None):
        if index_name == "kb_missing":
            raise ValueError("KB not found")
        return "READ_ONLY"

    monkeypatch.setattr(
        kb_permission,
        "resolve_knowledge_base_permission",
        staticmethod(mock_resolve),
    )

    result = ElasticSearchService.filter_accessible_indices(
        ["kb1", "kb_missing", "kb2"], "user-1", "tenant-1"
    )
    assert result == ["kb1", "kb2"]


def test_filter_accessible_indices_handles_unexpected_exception(monkeypatch):
    """When permission check raises unexpected exception, treat as inaccessible and continue."""

    def mock_resolve(index_name, user_id, tenant_id=None):
        if index_name == "kb_error":
            raise RuntimeError("DB connection failed")
        return "READ_ONLY"

    monkeypatch.setattr(
        kb_permission,
        "resolve_knowledge_base_permission",
        staticmethod(mock_resolve),
    )

    result = ElasticSearchService.filter_accessible_indices(
        ["kb1", "kb_error", "kb2"], "user-1", "tenant-1"
    )
    assert result == ["kb1", "kb2"]


def test_create_embedding_model_rejects_invalid_model_type():
    from management.services.model.resolver import create_embedding_model

    with pytest.raises(ValueError, match="Invalid model_type 'chat'"):
        create_embedding_model({"model_name": "not-an-embedding", "model_type": "chat"})


if __name__ == '__main__':
    unittest.main()


def test_merge_paginated_indices_uses_ordered_service_merge():
    primary = {
        "indices": ["tenant-new", "tenant-old"],
        "indices_info": [
            {"name": "tenant-new", "update_time": "2026-08-24T10:00:00", "knowledge_id": 3},
            {"name": "tenant-old", "update_time": "2026-08-24T08:00:00", "knowledge_id": 1},
        ],
        "total": 2,
        "facets": {"sources": ["elasticsearch"], "models": ["model-a"]},
    }
    asset_owner = {
        "indices": ["asset-middle"],
        "indices_info": [
            {
                "name": "asset-middle",
                "update_time": "2026-08-24T09:00:00",
                "knowledge_id": 2,
                "permission": "EDIT",
            }
        ],
        "total": 1,
        "facets": {"sources": ["elasticsearch"], "models": ["model-b"]},
    }

    result = listing_contract.merge_paginated_list_indices_results(
        primary,
        asset_owner,
        offset=0,
        limit=2,
    )

    assert result["indices"] == ["tenant-new", "asset-middle"]
    assert result["indices_info"][1]["permission"] == "READ_ONLY"
    assert result["total"] == 3
    assert result["next_offset"] == 2
    assert "has_more" not in result


def test_prepare_indices_page_requires_limit_when_pagination_is_enabled():
    with pytest.raises(ValueError, match="limit is required"):
        listing_contract.prepare_indices_page(
            visible_knowledgebases=[],
            pagination_enabled=True,
            offset=0,
            limit=None,
            keyword=None,
            sources=None,
            models=None,
        )


def test_apply_read_only_returns_unchanged_result_without_indices_info():
    result = {"indices": ["asset-kb"], "count": 1}

    assert listing_contract.apply_read_only_to_asset_indices_info(result) is result


def test_merge_non_paginated_indices_applies_asset_read_only_permission():
    primary = {
        "indices": ["tenant-kb"],
        "count": 1,
        "indices_info": [{"name": "tenant-kb", "permission": "EDIT"}],
    }
    asset = {
        "indices": ["asset-kb"],
        "count": 1,
        "indices_info": [{"name": "asset-kb", "permission": "EDIT"}],
    }

    result = listing_contract.merge_list_indices_results(primary, asset)

    assert result["indices"] == ["tenant-kb", "asset-kb"]
    assert result["count"] == 2
    assert result["indices_info"] == [
        {"name": "tenant-kb", "permission": "EDIT"},
        {"name": "asset-kb", "permission": "READ_ONLY"},
    ]


def test_merge_non_paginated_indices_without_info_returns_names_only():
    result = listing_contract.merge_list_indices_results(
        {"indices": ["tenant-kb"], "count": 1},
        {"indices": ["asset-kb"], "count": 1},
    )

    assert result == {
        "indices": ["tenant-kb", "asset-kb"],
        "count": 2,
    }


def test_merge_paginated_indices_supports_asset_first_and_last_page():
    primary = {
        "indices": ["tenant-old"],
        "indices_info": [
            {"name": "tenant-old", "update_time": "2026-08-24T08:00:00", "knowledge_id": 1}
        ],
        "total": 1,
        "facets": {"sources": ["elasticsearch"], "models": ["model-a"]},
    }
    asset = {
        "indices": ["asset-new"],
        "indices_info": [
            {"name": "asset-new", "update_time": "2026-08-24T10:00:00", "knowledge_id": 2}
        ],
        "total": 1,
        "facets": {"sources": ["asset"], "models": ["model-b"]},
    }

    result = listing_contract.merge_paginated_list_indices_results(
        primary, asset, offset=0, limit=2
    )

    assert result["indices"] == ["asset-new", "tenant-old"]
    assert result["next_offset"] is None
    assert result["facets"] == {
        "sources": ["asset", "elasticsearch"],
        "models": ["model-a", "model-b"],
    }


def test_merge_paginated_indices_falls_back_to_index_names_without_info():
    result = listing_contract.merge_paginated_list_indices_results(
        {"indices": ["tenant-kb"], "count": 1},
        {"indices": ["asset-kb"], "count": 1},
        offset=1,
        limit=1,
    )

    assert result["indices"] == ["asset-kb"]
    assert result["count"] == 1
    assert result["total"] == 2
    assert result["next_offset"] is None
    assert "indices_info" not in result


def _install_fake_celery_app(monkeypatch, inspector=None, task_result=None):
    """Install the minimal Celery app shape used by the deletion coordinator."""
    if inspector is None:
        inspector = SimpleNamespace(active=MagicMock(return_value={}), reserved=MagicMock(return_value={}))
    if task_result is None:
        task_result = SimpleNamespace(ready=MagicMock(return_value=True), state="SUCCESS")
    celery_app = SimpleNamespace(
        control=SimpleNamespace(
            inspect=lambda timeout=0.5: inspector,
            revoke=MagicMock(),
        ),
        AsyncResult=MagicMock(return_value=task_result),
    )
    package = ModuleType("data_process")
    package.__path__ = []
    app_module = ModuleType("data_process.app")
    app_module.app = celery_app
    monkeypatch.setitem(sys.modules, "data_process", package)
    monkeypatch.setitem(sys.modules, "data_process.app", app_module)
    monkeypatch.setattr("management.services.knowledge_base.deletion.celery_app", celery_app)
    return celery_app


_install_module_stubs = capture_module_stubs(_modules_before_stubs)


@pytest.fixture(autouse=True)
def _isolated_imports(monkeypatch):
    _install_module_stubs(monkeypatch)
