import os
import sys
import asyncio
import types
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# Dynamically determine the backend path - MUST BE FIRST
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../backend"))
sys.path.insert(0, backend_dir)

# Patch environment variables before any imports that might use them
os.environ.setdefault('MINIO_ENDPOINT', 'http://localhost:9000')
os.environ.setdefault('MINIO_ACCESS_KEY', 'minioadmin')
os.environ.setdefault('MINIO_SECRET_KEY', 'minioadmin')
os.environ.setdefault('MINIO_REGION', 'us-east-1')
os.environ.setdefault('MINIO_DEFAULT_BUCKET', 'test-bucket')

# Mock boto3 and dotenv before importing the module under test
boto3_mock = MagicMock()
minio_client_mock = MagicMock()
sys.modules['boto3'] = boto3_mock
sys.modules['dotenv'] = MagicMock(load_dotenv=MagicMock())

# Mock nexent modules before importing modules that use them
nexent_mock = MagicMock()
sys.modules['nexent'] = nexent_mock
sys.modules['nexent.core'] = MagicMock()
sys.modules['nexent.core.models'] = MagicMock()
sys.modules['nexent.core.models.embedding_model'] = MagicMock()
sys.modules['nexent.core.nlp'] = MagicMock()
sys.modules['nexent.core.nlp.tokenizer'] = MagicMock()
sys.modules['nexent.vector_database'] = MagicMock()
sys.modules['nexent.vector_database.elasticsearch_core'] = MagicMock()
sys.modules['nexent.core.agents'] = MagicMock()
sys.modules['nexent.core.agents.agent_model'] = MagicMock()
sys.modules['nexent.storage.storage_client_factory'] = MagicMock()

# Stub nexent.core.models.* required by attachment_utils
nexent_core_models_pkg = types.ModuleType("nexent.core.models")
nexent_core_models_pkg.__path__ = []  # Mark as package for submodule imports
sys.modules["nexent.core.models"] = nexent_core_models_pkg

openai_long_ctx_mod = types.ModuleType(
    "nexent.core.models.openai_long_context_model"
)


class OpenAILongContextModel:
    def __init__(self, *args, **kwargs):
        pass


openai_long_ctx_mod.OpenAILongContextModel = OpenAILongContextModel
sys.modules[
    "nexent.core.models.openai_long_context_model"
] = openai_long_ctx_mod
# Also expose on the package for `from nexent.core.models import OpenAILongContextModel`
nexent_core_models_pkg.OpenAILongContextModel = OpenAILongContextModel

openai_vlm_mod = types.ModuleType("nexent.core.models.openai_vlm")


class OpenAIVLModel:
    def __init__(self, *args, **kwargs):
        pass


openai_vlm_mod.OpenAIVLModel = OpenAIVLModel
sys.modules["nexent.core.models.openai_vlm"] = openai_vlm_mod
# Also expose on the package for potential direct imports
nexent_core_models_pkg.OpenAIVLModel = OpenAIVLModel

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()

# Create stub vector database modules to satisfy imports
vector_db_module = types.ModuleType("nexent.vector_database")
vector_db_module.__path__ = []  # Mark as package
vector_db_base_module = types.ModuleType("nexent.vector_database.base")

class MockVectorDatabaseCore:
    def __init__(self, *args, **kwargs):
        pass

vector_db_base_module.VectorDatabaseCore = MockVectorDatabaseCore

vector_db_es_module = types.ModuleType("nexent.vector_database.elasticsearch_core")

class MockElasticSearchCore:
    def __init__(self, *args, **kwargs):
        pass

vector_db_es_module.ElasticSearchCore = MockElasticSearchCore

sys.modules['nexent.vector_database'] = vector_db_module
sys.modules['nexent.vector_database.base'] = vector_db_base_module
sys.modules['nexent.vector_database.elasticsearch_core'] = vector_db_es_module
setattr(vector_db_module, "base", vector_db_base_module)
setattr(vector_db_module, "elasticsearch_core", vector_db_es_module)

# Pre-inject a stubbed base_app to avoid import side effects
backend_pkg = types.ModuleType("backend")
apps_pkg = types.ModuleType("backend.apps")
base_app_mod = types.ModuleType("backend.apps.base_app")
base_app_mod.app = MagicMock()

# Install stubs into sys.modules
sys.modules.setdefault("backend", backend_pkg)
sys.modules["backend.apps"] = apps_pkg
sys.modules["backend.apps.base_app"] = base_app_mod

# Also stub non-namespaced imports used by the application
apps_pkg_flat = types.ModuleType("apps")
base_app_mod_flat = types.ModuleType("apps.config_app")
base_app_mod_flat.app = MagicMock()
sys.modules["apps"] = apps_pkg_flat
sys.modules["apps.config_app"] = base_app_mod_flat
setattr(apps_pkg_flat, "config_app", base_app_mod_flat)

# Wire package attributes
setattr(backend_pkg, "apps", apps_pkg)
setattr(apps_pkg, "config_app", base_app_mod)


class TestTenantConfigService:
    """Unit tests for tenant_config_service helpers"""

    @patch('backend.services.tenant_config_service.get_selected_knowledge_list')
    def test_build_knowledge_name_mapping_prefers_knowledge_name(self, mock_get_selected):
        """Ensure knowledge_name is used as key when present."""
        mock_get_selected.return_value = [
            {"knowledge_name": "User Docs", "index_name": "index_user_docs"},
            {"knowledge_name": "API Docs", "index_name": "index_api_docs"},
        ]

        from backend.services.tenant_config_service import build_knowledge_name_mapping

        mapping = build_knowledge_name_mapping(tenant_id="t1", user_id="u1")

        assert mapping == {
            "User Docs": "index_user_docs",
            "API Docs": "index_api_docs",
        }
        mock_get_selected.assert_called_once_with(tenant_id="t1", user_id="u1")

    @patch('backend.services.tenant_config_service.get_selected_knowledge_list')
    def test_build_knowledge_name_mapping_fallbacks_to_index_name(self, mock_get_selected):
        """Fallback to index_name when knowledge_name is missing."""
        mock_get_selected.return_value = [
            {"index_name": "index_fallback_only"},
            {"knowledge_name": None, "index_name": "index_none_name"},
        ]

        from backend.services.tenant_config_service import build_knowledge_name_mapping

        mapping = build_knowledge_name_mapping(tenant_id="t2", user_id="u2")

        assert mapping == {
            "index_fallback_only": "index_fallback_only",
            "index_none_name": "index_none_name",
        }
        mock_get_selected.assert_called_once_with(tenant_id="t2", user_id="u2")


if __name__ == '__main__':
    pytest.main()
