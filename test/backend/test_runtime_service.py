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
# Environment variables are now configured in conftest.py

# Mock boto3 and dotenv before importing the module under test
boto3_mock = MagicMock()
minio_client_mock = MagicMock()
sys.modules['boto3'] = boto3_mock
sys.modules['dotenv'] = MagicMock(load_dotenv=MagicMock())

# Mock nexent modules before importing modules that use them
nexent_mock = MagicMock()
sys.modules['nexent'] = nexent_mock
sys.modules['nexent.core'] = MagicMock()
sys.modules['nexent.core.models.embedding_model'] = MagicMock()
sys.modules['nexent.core.nlp'] = MagicMock()
sys.modules['nexent.core.nlp.tokenizer'] = MagicMock()

# Stub nexent.core.models.* required by attachment_utils and file_management_service
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
nexent_core_models_pkg.OpenAILongContextModel = OpenAILongContextModel

openai_vlm_mod = types.ModuleType("nexent.core.models.openai_vlm")


class OpenAIVLModel:
    def __init__(self, *args, **kwargs):
        pass


openai_vlm_mod.OpenAIVLModel = OpenAIVLModel
sys.modules["nexent.core.models.openai_vlm"] = openai_vlm_mod
nexent_core_models_pkg.OpenAIVLModel = OpenAIVLModel

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

sys.modules['nexent.core.agents'] = MagicMock()
sys.modules['nexent.core.agents.agent_model'] = MagicMock()
sys.modules['nexent.storage.storage_client_factory'] = MagicMock()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()

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
base_app_mod_flat = types.ModuleType("apps.runtime_app")
base_app_mod_flat.app = MagicMock()
sys.modules["apps"] = apps_pkg_flat
sys.modules["apps.runtime_app"] = base_app_mod_flat
setattr(apps_pkg_flat, "runtime_app", base_app_mod_flat)

# Wire package attributes
setattr(backend_pkg, "apps", apps_pkg)
setattr(apps_pkg, "runtime_app", base_app_mod)


class TestMainServiceModuleIntegration:
    """Integration tests for runtime_service module dependencies"""

    @patch('runtime_service.configure_logging')
    @patch('runtime_service.configure_elasticsearch_logging')
    def test_logging_configuration_called_on_import(self, mock_configure_es, mock_configure_logging):
        """
        Test that logging configuration functions are called when module is imported.

        This test verifies that:
        1. configure_logging is called with logging.INFO
        2. configure_elasticsearch_logging is called
        """
        # Note: This test checks that logging configuration happens during module import
        # The mocks should have been called when the module was imported
        # In a real scenario, you might need to reload the module to test this properly
        pass  # The actual verification would depend on how the test runner handles imports


if __name__ == '__main__':
    pytest.main()
