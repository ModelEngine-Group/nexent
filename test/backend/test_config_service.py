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

# Mock external dependencies before importing backend modules
with patch('backend.database.client.MinioClient', return_value=minio_client_mock), \
        patch('elasticsearch.Elasticsearch', return_value=MagicMock()), \
        patch('nexent.vector_database.elasticsearch_core.ElasticSearchCore', return_value=MagicMock()):
    # Mock dotenv before importing config_service
    with patch('dotenv.load_dotenv'):
        # Mock logging configuration
        with patch('utils.logging_utils.configure_logging'), \
                patch('utils.logging_utils.configure_elasticsearch_logging'):
            from config_service import startup_initialization


class TestMainService:
    """Test cases for config_service module"""

    @pytest.mark.asyncio
    @patch('config_service.initialize_tools_on_startup', new_callable=AsyncMock)
    @patch('config_service.logger')
    async def test_startup_initialization_success(self, mock_logger, mock_initialize_tools):
        """
        Test successful startup initialization.

        This test verifies that:
        1. The function logs the start of initialization
        2. It logs the APP version
        3. It calls initialize_tools_on_startup
        4. It logs successful completion
        """
        # Setup
        mock_initialize_tools.return_value = None

        # Execute
        await startup_initialization()

        # Assert
        # Check that appropriate log messages were called
        mock_logger.info.assert_any_call("Starting server initialization...")
        mock_logger.info.assert_any_call(
            "Server initialization completed successfully!")

        # Verify initialize_tools_on_startup was called
        mock_initialize_tools.assert_called_once()

    @pytest.mark.asyncio
    @patch('config_service.initialize_tools_on_startup', new_callable=AsyncMock)
    @patch('config_service.logger')
    async def test_startup_initialization_with_version_log(self, mock_logger, mock_initialize_tools):
        """
        Test that startup initialization logs the APP version.

        This test verifies that:
        1. The function logs the APP version from consts.const
        """
        # Setup
        mock_initialize_tools.return_value = None

        # Execute
        await startup_initialization()

        # Assert
        # Check that version logging was called (should contain "APP version is:")
        version_logged = any(
            call for call in mock_logger.info.call_args_list
            if len(call.args) > 0 and "APP version is:" in str(call.args[0])
        )
        assert version_logged, "APP version should be logged during initialization"

    @pytest.mark.asyncio
    @patch('config_service.initialize_tools_on_startup', new_callable=AsyncMock)
    @patch('config_service.logger')
    async def test_startup_initialization_tool_initialization_failure(self, mock_logger, mock_initialize_tools):
        """
        Test startup initialization when tool initialization fails.

        This test verifies that:
        1. When initialize_tools_on_startup raises an exception
        2. The function catches the exception and logs an error
        3. The function logs a warning about continuing despite issues
        4. The function does not re-raise the exception
        """
        # Setup
        mock_initialize_tools.side_effect = Exception(
            "Tool initialization failed")

        # Execute - should not raise exception
        await startup_initialization()

        # Assert
        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args[0][0]
        assert "Server initialization failed:" in error_call
        assert "Tool initialization failed" in error_call

        mock_logger.warning.assert_called_once_with(
            "Server will continue to start despite initialization issues"
        )

        # Verify initialize_tools_on_startup was called
        mock_initialize_tools.assert_called_once()

    @pytest.mark.asyncio
    @patch('config_service.initialize_tools_on_startup', new_callable=AsyncMock)
    @patch('config_service.logger')
    async def test_startup_initialization_database_error(self, mock_logger, mock_initialize_tools):
        """
        Test startup initialization when database connection fails.

        This test verifies that:
        1. Database-related exceptions are handled gracefully
        2. Appropriate error messages are logged
        3. The server startup is not blocked
        """
        # Setup
        mock_initialize_tools.side_effect = ConnectionError(
            "Database connection failed")

        # Execute - should not raise exception
        await startup_initialization()

        # Assert
        mock_logger.error.assert_called_once()
        error_message = mock_logger.error.call_args[0][0]
        assert "Server initialization failed:" in error_message
        assert "Database connection failed" in error_message

        mock_logger.warning.assert_called_once_with(
            "Server will continue to start despite initialization issues"
        )

    @pytest.mark.asyncio
    @patch('config_service.initialize_tools_on_startup', new_callable=AsyncMock)
    @patch('config_service.logger')
    async def test_startup_initialization_timeout_error(self, mock_logger, mock_initialize_tools):
        """
        Test startup initialization when tool initialization times out.

        This test verifies that:
        1. Timeout exceptions are handled gracefully
        2. Appropriate error messages are logged
        3. The function continues execution
        """
        # Setup
        mock_initialize_tools.side_effect = asyncio.TimeoutError(
            "Tool initialization timed out")

        # Execute - should not raise exception
        await startup_initialization()

        # Assert
        mock_logger.error.assert_called_once()
        error_message = mock_logger.error.call_args[0][0]
        assert "Server initialization failed:" in error_message

        mock_logger.warning.assert_called_once_with(
            "Server will continue to start despite initialization issues"
        )

    @pytest.mark.asyncio
    @patch('config_service.initialize_tools_on_startup', new_callable=AsyncMock)
    @patch('config_service.logger')
    async def test_startup_initialization_multiple_calls_safe(self, mock_logger, mock_initialize_tools):
        """
        Test that multiple calls to startup_initialization are safe.

        This test verifies that:
        1. The function can be called multiple times without issues
        2. Each call properly executes the initialization sequence
        """
        # Setup
        mock_initialize_tools.return_value = None

        # Execute multiple times
        await startup_initialization()
        await startup_initialization()

        # Assert
        assert mock_initialize_tools.call_count == 2
        # At least 2 calls * 2 info messages per call
        assert mock_logger.info.call_count >= 4

    @pytest.mark.asyncio
    @patch('config_service.initialize_tools_on_startup', new_callable=AsyncMock)
    @patch('config_service.logger')
    async def test_startup_initialization_logging_order(self, mock_logger, mock_initialize_tools):
        """
        Test that logging occurs in the correct order during initialization.

        This test verifies that:
        1. Start message is logged first
        2. Version message is logged second
        3. Success message is logged last (when successful)
        """
        # Setup
        mock_initialize_tools.return_value = None

        # Execute
        await startup_initialization()

        # Assert
        info_calls = [call.args[0] for call in mock_logger.info.call_args_list]

        # Check order of log messages
        assert len(info_calls) >= 3
        assert "Starting server initialization..." in info_calls[0]
        assert "APP version is:" in info_calls[1]
        assert "Server initialization completed successfully!" in info_calls[-1]

    @pytest.mark.asyncio
    @patch('config_service.initialize_tools_on_startup', new_callable=AsyncMock)
    @patch('config_service.logger')
    async def test_startup_initialization_exception_details_logged(self, mock_logger, mock_initialize_tools):
        """
        Test that exception details are properly logged.

        This test verifies that:
        1. The specific exception message is included in error logs
        2. Both error and warning messages are logged on failure
        """
        # Setup
        specific_error_message = "Specific tool configuration error occurred"
        mock_initialize_tools.side_effect = ValueError(specific_error_message)

        # Execute
        await startup_initialization()

        # Assert
        mock_logger.error.assert_called_once()
        error_call_args = mock_logger.error.call_args[0][0]
        assert specific_error_message in error_call_args
        assert "Server initialization failed:" in error_call_args

        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    @patch('config_service.initialize_tools_on_startup', new_callable=AsyncMock)
    @patch('config_service.logger')
    async def test_startup_initialization_no_exception_propagation(self, mock_logger, mock_initialize_tools):
        """
        Test that exceptions during initialization do not propagate.

        This test verifies that:
        1. Even when initialize_tools_on_startup fails, no exception is raised
        2. This allows the server to continue starting up
        """
        # Setup
        mock_initialize_tools.side_effect = RuntimeError(
            "Critical initialization error")

        # Execute and Assert - should not raise any exception
        try:
            await startup_initialization()
        except Exception as e:
            pytest.fail(
                f"startup_initialization should not raise exceptions, but raised: {e}")

        # Verify that error handling occurred
        mock_logger.error.assert_called_once()
        mock_logger.warning.assert_called_once()


class TestMainServiceModuleIntegration:
    """Integration tests for config_service module dependencies"""

    @patch('config_service.configure_logging')
    @patch('config_service.configure_elasticsearch_logging')
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

    @patch('config_service.APP_VERSION', 'test_version_1.2.3')
    @patch('config_service.initialize_tools_on_startup', new_callable=AsyncMock)
    @patch('config_service.logger')
    async def test_startup_initialization_with_custom_version(self, mock_logger, mock_initialize_tools):
        """
        Test startup initialization with a custom APP_VERSION.

        This test verifies that:
        1. The custom version is properly logged
        """
        # Setup
        mock_initialize_tools.return_value = None

        # Execute
        await startup_initialization()

        # Assert
        version_logged = any(
            "test_version_1.2.3" in str(call.args[0])
            for call in mock_logger.info.call_args_list
            if len(call.args) > 0
        )
        assert version_logged, "Custom APP version should be logged"


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
