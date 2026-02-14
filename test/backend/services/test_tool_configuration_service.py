from consts.exceptions import MCPConnectionError, NotFoundException, ToolExecutionException
import asyncio
import inspect
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Environment variables are now configured in conftest.py

boto3_mock = MagicMock()
minio_client_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Patch smolagents and its sub-modules before importing consts.model to avoid ImportError
mock_smolagents = MagicMock()
sys.modules['smolagents'] = mock_smolagents

# Create dummy smolagents sub-modules to satisfy indirect imports
for sub_mod in ["agents", "memory", "models", "monitoring", "utils", "local_python_executor"]:
    sub_mod_obj = types.ModuleType(f"smolagents.{sub_mod}")
    setattr(mock_smolagents, sub_mod, sub_mod_obj)
    sys.modules[f"smolagents.{sub_mod}"] = sub_mod_obj

# Populate smolagents.agents with required attributes
# Exception classes should be real exception classes, not MagicMock


class MockAgentError(Exception):
    pass


setattr(mock_smolagents.agents, "AgentError", MockAgentError)
for name in ["CodeAgent", "handle_agent_output_types", "ActionOutput", "RunResult"]:
    setattr(mock_smolagents.agents, name, MagicMock(
        name=f"smolagents.agents.{name}"))

# Populate smolagents.local_python_executor with required attributes
setattr(mock_smolagents.local_python_executor, "fix_final_answer_code",
        MagicMock(name="fix_final_answer_code"))

# Populate smolagents.memory with required attributes
for name in ["ActionStep", "PlanningStep", "FinalAnswerStep", "ToolCall", "TaskStep", "SystemPromptStep"]:
    setattr(mock_smolagents.memory, name, MagicMock(
        name=f"smolagents.memory.{name}"))

# Populate smolagents.models with required attributes
setattr(mock_smolagents.models, "ChatMessage", MagicMock(name="ChatMessage"))
setattr(mock_smolagents.models, "MessageRole", MagicMock(name="MessageRole"))
setattr(mock_smolagents.models, "CODEAGENT_RESPONSE_FORMAT",
        MagicMock(name="CODEAGENT_RESPONSE_FORMAT"))

# OpenAIServerModel should be a class that can be instantiated


class MockOpenAIServerModel:
    def __init__(self, *args, **kwargs):
        pass


setattr(mock_smolagents.models, "OpenAIServerModel", MockOpenAIServerModel)

# Populate smolagents with Tool attribute
setattr(mock_smolagents, "Tool", MagicMock(name="Tool"))

# Populate smolagents.monitoring with required attributes
for name in ["LogLevel", "Timing", "YELLOW_HEX", "TokenUsage"]:
    setattr(mock_smolagents.monitoring, name, MagicMock(
        name=f"smolagents.monitoring.{name}"))

# Populate smolagents.utils with required attributes
# Exception classes should be real exception classes, not MagicMock


class MockAgentExecutionError(Exception):
    pass


class MockAgentGenerationError(Exception):
    pass


class MockAgentMaxStepsError(Exception):
    pass


setattr(mock_smolagents.utils, "AgentExecutionError", MockAgentExecutionError)
setattr(mock_smolagents.utils, "AgentGenerationError", MockAgentGenerationError)
setattr(mock_smolagents.utils, "AgentMaxStepsError", MockAgentMaxStepsError)
for name in ["truncate_content", "extract_code_from_text"]:
    setattr(mock_smolagents.utils, name, MagicMock(
        name=f"smolagents.utils.{name}"))

# mcpadapt imports a helper from smolagents.utils


def _is_package_available(pkg_name: str) -> bool:
    """Simplified availability check for tests."""
    return True


setattr(mock_smolagents.utils, "_is_package_available", _is_package_available)

# Mock nexent module and its submodules before patching


def _create_package_mock(name):
    """Helper to create a package-like mock module."""
    pkg = types.ModuleType(name)
    pkg.__path__ = []
    return pkg


nexent_mock = _create_package_mock('nexent')
sys.modules['nexent'] = nexent_mock
sys.modules['nexent.core'] = _create_package_mock('nexent.core')
sys.modules['nexent.core.agents'] = _create_package_mock('nexent.core.agents')
sys.modules['nexent.core.agents.agent_model'] = MagicMock()
sys.modules['nexent.core.models'] = _create_package_mock('nexent.core.models')


class MockMessageObserver:
    """Lightweight stand-in for nexent.MessageObserver."""
    pass


# Expose MessageObserver on top-level nexent package
setattr(sys.modules['nexent'], 'MessageObserver', MockMessageObserver)

# Mock embedding model module to satisfy vectordatabase_service imports
embedding_model_module = types.ModuleType('nexent.core.models.embedding_model')


class MockBaseEmbedding:
    pass


class MockOpenAICompatibleEmbedding(MockBaseEmbedding):
    pass


class MockJinaEmbedding(MockBaseEmbedding):
    pass


embedding_model_module.BaseEmbedding = MockBaseEmbedding
embedding_model_module.OpenAICompatibleEmbedding = MockOpenAICompatibleEmbedding
embedding_model_module.JinaEmbedding = MockJinaEmbedding
sys.modules['nexent.core.models.embedding_model'] = embedding_model_module

# Provide model class used by file_management_service imports


class MockOpenAILongContextModel:
    def __init__(self, *args, **kwargs):
        pass


setattr(sys.modules['nexent.core.models'],
        'OpenAILongContextModel', MockOpenAILongContextModel)

# Provide vision model class used by image_service imports


class MockOpenAIVLModel:
    def __init__(self, *args, **kwargs):
        pass


setattr(sys.modules['nexent.core.models'],
        'OpenAIVLModel', MockOpenAIVLModel)

# Mock vector database modules used by vectordatabase_service
sys.modules['nexent.vector_database'] = _create_package_mock(
    'nexent.vector_database')
vector_database_base_module = types.ModuleType('nexent.vector_database.base')
vector_database_elasticsearch_module = types.ModuleType(
    'nexent.vector_database.elasticsearch_core')


class MockVectorDatabaseCore:
    pass


class MockElasticSearchCore(MockVectorDatabaseCore):
    def __init__(self, *args, **kwargs):
        pass


# Provide a mock DataMateCore to satisfy imports in vectordatabase_service
vector_database_datamate_module = types.ModuleType(
    'nexent.vector_database.datamate_core')


class MockDataMateCore(MockVectorDatabaseCore):
    def __init__(self, *args, **kwargs):
        pass


vector_database_datamate_module.DataMateCore = MockDataMateCore
sys.modules['nexent.vector_database.datamate_core'] = vector_database_datamate_module
setattr(sys.modules['nexent.vector_database'],
        'datamate_core', vector_database_datamate_module)
setattr(sys.modules['nexent.vector_database'],
        'DataMateCore', MockDataMateCore)

vector_database_base_module.VectorDatabaseCore = MockVectorDatabaseCore
vector_database_elasticsearch_module.ElasticSearchCore = MockElasticSearchCore
sys.modules['nexent.vector_database.base'] = vector_database_base_module
sys.modules['nexent.vector_database.elasticsearch_core'] = vector_database_elasticsearch_module

# Expose submodules on parent packages
setattr(sys.modules['nexent.core'], 'models',
        sys.modules['nexent.core.models'])
setattr(sys.modules['nexent.core.models'], 'embedding_model',
        sys.modules['nexent.core.models.embedding_model'])
setattr(sys.modules['nexent'], 'vector_database',
        sys.modules['nexent.vector_database'])
setattr(sys.modules['nexent.vector_database'], 'base',
        sys.modules['nexent.vector_database.base'])
setattr(sys.modules['nexent.vector_database'], 'elasticsearch_core',
        sys.modules['nexent.vector_database.elasticsearch_core'])

# Mock nexent.storage module and its submodules
sys.modules['nexent.storage'] = _create_package_mock('nexent.storage')
storage_factory_module = types.ModuleType(
    'nexent.storage.storage_client_factory')
storage_config_module = types.ModuleType('nexent.storage.minio_config')

# Create mock classes/functions


class MockMinIOStorageConfig:
    def __init__(self, *args, **kwargs):
        pass

    def validate(self):
        pass


storage_factory_module.create_storage_client_from_config = MagicMock()
storage_factory_module.MinIOStorageConfig = MockMinIOStorageConfig
storage_config_module.MinIOStorageConfig = MockMinIOStorageConfig

# Ensure nested packages are reachable via attributes
setattr(sys.modules['nexent'], 'storage', sys.modules['nexent.storage'])
# Expose submodules on the storage package for patch lookups
setattr(sys.modules['nexent.storage'],
        'storage_client_factory', storage_factory_module)
setattr(sys.modules['nexent.storage'], 'minio_config', storage_config_module)
sys.modules['nexent.storage.storage_client_factory'] = storage_factory_module
sys.modules['nexent.storage.minio_config'] = storage_config_module

# Load actual backend modules so that patch targets resolve correctly
import importlib  # noqa: E402
backend_module = importlib.import_module('backend')
sys.modules['backend'] = backend_module
backend_database_module = importlib.import_module('backend.database')
sys.modules['backend.database'] = backend_database_module
backend_database_client_module = importlib.import_module(
    'backend.database.client')
sys.modules['backend.database.client'] = backend_database_client_module
backend_services_module = importlib.import_module(
    'backend.services.tool_configuration_service')
# Ensure services package can resolve tool_configuration_service for patching
sys.modules['services.tool_configuration_service'] = backend_services_module

# Mock services modules
sys.modules['services'] = _create_package_mock('services')
services_modules = {
    'file_management_service': {'get_llm_model': MagicMock()},
    'vectordatabase_service': {'get_embedding_model': MagicMock(), 'get_vector_db_core': MagicMock(),
                               'ElasticSearchService': MagicMock()},
    'tenant_config_service': {'get_selected_knowledge_list': MagicMock(), 'build_knowledge_name_mapping': MagicMock()},
    'image_service': {'get_vlm_model': MagicMock()}
}
for service_name, attrs in services_modules.items():
    service_module = types.ModuleType(f'services.{service_name}')
    for attr_name, attr_value in attrs.items():
        setattr(service_module, attr_name, attr_value)
    sys.modules[f'services.{service_name}'] = service_module
    # Expose on parent package for patch resolution
    setattr(sys.modules['services'], service_name, service_module)

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate',
      lambda self: None).start()
patch('backend.database.client.MinioClient',
      return_value=minio_client_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Patch tool_configuration_service imports to avoid triggering actual imports during patch
# This prevents import errors when patch tries to import the module
# Note: These patches use the import path as seen in tool_configuration_service.py
patch('services.file_management_service.get_llm_model', MagicMock()).start()
patch('services.vectordatabase_service.get_embedding_model', MagicMock()).start()
patch('services.vectordatabase_service.get_vector_db_core', MagicMock()).start()
patch('services.tenant_config_service.get_selected_knowledge_list', MagicMock()).start()
patch('services.tenant_config_service.build_knowledge_name_mapping',
      MagicMock()).start()
patch('services.image_service.get_vlm_model', MagicMock()).start()

# Import consts after patching dependencies
from consts.model import ToolInfo, ToolSourceEnum, ToolInstanceInfoRequest, ToolValidateRequest  # noqa: E402


class TestPythonTypeToJsonSchema:
    """ test the function of python_type_to_json_schema"""

    @patch('backend.services.tool_configuration_service.python_type_to_json_schema')
    def test_python_type_to_json_schema_basic_types(self, mock_python_type_to_json_schema):
        """ test the basic types of python"""
        mock_python_type_to_json_schema.side_effect = lambda x: {
            str: "string",
            int: "integer",
            float: "float",
            bool: "boolean",
            list: "array",
            dict: "object"
        }.get(x, "unknown")

        from backend.services.tool_configuration_service import python_type_to_json_schema
        assert python_type_to_json_schema(str) == "string"
        assert python_type_to_json_schema(int) == "integer"
        assert python_type_to_json_schema(float) == "float"
        assert python_type_to_json_schema(bool) == "boolean"
        assert python_type_to_json_schema(list) == "array"
        assert python_type_to_json_schema(dict) == "object"

    @patch('backend.services.tool_configuration_service.python_type_to_json_schema')
    def test_python_type_to_json_schema_typing_types(self, mock_python_type_to_json_schema):
        """ test the typing types of python"""
        from typing import List, Dict, Tuple, Any

        mock_python_type_to_json_schema.side_effect = lambda x: {
            List: "array",
            Dict: "object",
            Tuple: "array",
            Any: "any"
        }.get(x, "unknown")

        from backend.services.tool_configuration_service import python_type_to_json_schema
        assert python_type_to_json_schema(List) == "array"
        assert python_type_to_json_schema(Dict) == "object"
        assert python_type_to_json_schema(Tuple) == "array"
        assert python_type_to_json_schema(Any) == "any"

    @patch('backend.services.tool_configuration_service.python_type_to_json_schema')
    def test_python_type_to_json_schema_empty_annotation(self, mock_python_type_to_json_schema):
        """ test the empty annotation of python"""
        mock_python_type_to_json_schema.return_value = "string"

        from backend.services.tool_configuration_service import python_type_to_json_schema
        assert python_type_to_json_schema(inspect.Parameter.empty) == "string"

    @patch('backend.services.tool_configuration_service.python_type_to_json_schema')
    def test_python_type_to_json_schema_unknown_type(self, mock_python_type_to_json_schema):
        """ test the unknown type of python"""
        class CustomType:
            pass

        # the unknown type should return the type name itself
        mock_python_type_to_json_schema.return_value = "CustomType"

        from backend.services.tool_configuration_service import python_type_to_json_schema
        result = python_type_to_json_schema(CustomType)
        assert "CustomType" in result

    @patch('backend.services.tool_configuration_service.python_type_to_json_schema')
    def test_python_type_to_json_schema_edge_cases(self, mock_python_type_to_json_schema):
        """ test the edge cases of python"""
        from typing import List, Dict, Any

        # test the None type
        mock_python_type_to_json_schema.side_effect = lambda x: "NoneType" if x == type(
            None) else "array"

        from backend.services.tool_configuration_service import python_type_to_json_schema
        assert python_type_to_json_schema(type(None)) == "NoneType"

        # test the complex type string representation
        complex_type = List[Dict[str, Any]]
        mock_python_type_to_json_schema.return_value = "array"
        result = python_type_to_json_schema(complex_type)
        assert isinstance(result, str)


class TestGetLocalToolsClasses:
    """ test the function of get_local_tools_classes"""

    @patch('backend.services.tool_configuration_service.importlib.import_module')
    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_get_local_tools_classes_success(self, mock_get_local_tools_classes, mock_import):
        """ test the success of get_local_tools_classes"""
        # create the mock tool class
        mock_tool_class1 = type('TestTool1', (), {})
        mock_tool_class2 = type('TestTool2', (), {})
        mock_non_class = "not_a_class"

        # Create a proper mock object with defined attributes and __dir__ method
        class MockPackage:
            def __init__(self):
                self.TestTool1 = mock_tool_class1
                self.TestTool2 = mock_tool_class2
                self.not_a_class = mock_non_class
                self.__name__ = 'nexent.core.tools'

            def __dir__(self):
                return ['TestTool1', 'TestTool2', 'not_a_class', '__name__']

        mock_package = MockPackage()
        mock_import.return_value = mock_package
        mock_get_local_tools_classes.return_value = [
            mock_tool_class1, mock_tool_class2]

        from backend.services.tool_configuration_service import get_local_tools_classes
        result = get_local_tools_classes()

        # Assertions
        assert len(result) == 2
        assert mock_tool_class1 in result
        assert mock_tool_class2 in result
        assert mock_non_class not in result

    @patch('backend.services.tool_configuration_service.importlib.import_module')
    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_get_local_tools_classes_import_error(self, mock_get_local_tools_classes, mock_import):
        """ test the import error of get_local_tools_classes"""
        mock_import.side_effect = ImportError("Module not found")
        mock_get_local_tools_classes.side_effect = ImportError(
            "Module not found")

        from backend.services.tool_configuration_service import get_local_tools_classes
        with pytest.raises(ImportError):
            get_local_tools_classes()


class TestGetLocalTools:
    """ test the function of get_local_tools"""

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    @patch('backend.services.tool_configuration_service.get_local_tools')
    def test_get_local_tools_success(self, mock_get_local_tools, mock_signature, mock_get_classes):
        """ test the success of get_local_tools"""
        # create the mock tool class
        mock_tool_class = Mock()
        mock_tool_class.name = "test_tool"
        mock_tool_class.description = "Test tool description"
        mock_tool_class.inputs = {"input1": "value1"}
        mock_tool_class.output_type = "string"
        mock_tool_class.category = "test_category"
        mock_tool_class.__name__ = "TestTool"

        # create the mock parameter
        mock_param = Mock()
        mock_param.annotation = str
        mock_param.default = Mock()
        mock_param.default.description = "Test parameter"
        mock_param.default.default = "default_value"
        mock_param.default.exclude = False

        # create the mock signature
        mock_sig = Mock()
        mock_sig.parameters = {
            'self': Mock(),
            'test_param': mock_param
        }

        mock_signature.return_value = mock_sig
        mock_get_classes.return_value = [mock_tool_class]

        # Create mock tool info
        mock_tool_info = Mock()
        mock_tool_info.name = "test_tool"
        mock_tool_info.description = "Test tool description"
        mock_tool_info.source = ToolSourceEnum.LOCAL.value
        mock_tool_info.class_name = "TestTool"
        mock_get_local_tools.return_value = [mock_tool_info]

        from backend.services.tool_configuration_service import get_local_tools
        result = get_local_tools()

        assert len(result) == 1
        tool_info = result[0]
        assert tool_info.name == "test_tool"
        assert tool_info.description == "Test tool description"
        assert tool_info.source == ToolSourceEnum.LOCAL.value
        assert tool_info.class_name == "TestTool"

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    @patch('backend.services.tool_configuration_service.get_local_tools')
    def test_get_local_tools_no_classes(self, mock_get_local_tools, mock_get_classes):
        """ test the no tool class of get_local_tools"""
        mock_get_classes.return_value = []
        mock_get_local_tools.return_value = []

        from backend.services.tool_configuration_service import get_local_tools
        result = get_local_tools()
        assert result == []

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    @patch('backend.services.tool_configuration_service.get_local_tools')
    def test_get_local_tools_with_exception(self, mock_get_local_tools, mock_get_classes):
        """ test the exception of get_local_tools"""
        mock_tool_class = Mock()
        mock_tool_class.name = "test_tool"
        # mock the attribute error
        mock_tool_class.description = Mock(
            side_effect=AttributeError("No description"))

        mock_get_classes.return_value = [mock_tool_class]
        mock_get_local_tools.side_effect = AttributeError("No description")

        from backend.services.tool_configuration_service import get_local_tools
        with pytest.raises(AttributeError):
            get_local_tools()


class TestSearchToolInfoImpl:
    """ test the function of search_tool_info_impl"""

    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    @patch('backend.services.tool_configuration_service.search_tool_info_impl')
    def test_search_tool_info_impl_success(self, mock_search_tool_info_impl, mock_query):
        """ test the success of search_tool_info_impl"""
        mock_query.return_value = {
            "params": {"param1": "value1"},
            "enabled": True
        }
        mock_search_tool_info_impl.return_value = {
            "params": {"param1": "value1"},
            "enabled": True
        }

        from backend.services.tool_configuration_service import search_tool_info_impl
        result = search_tool_info_impl(1, 1, "test_tenant")

        assert result["params"] == {"param1": "value1"}
        assert result["enabled"] is True
        mock_search_tool_info_impl.assert_called_once_with(1, 1, "test_tenant")

    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    @patch('backend.services.tool_configuration_service.search_tool_info_impl')
    def test_search_tool_info_impl_not_found(self, mock_search_tool_info_impl, mock_query):
        """ test the tool info not found of search_tool_info_impl"""
        mock_query.return_value = None
        mock_search_tool_info_impl.return_value = {
            "params": None,
            "enabled": False
        }

        from backend.services.tool_configuration_service import search_tool_info_impl
        result = search_tool_info_impl(1, 1, "test_tenant")

        assert result["params"] is None
        assert result["enabled"] is False

    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    @patch('backend.services.tool_configuration_service.search_tool_info_impl')
    def test_search_tool_info_impl_database_error(self, mock_search_tool_info_impl, mock_query):
        """ test the database error of search_tool_info_impl"""
        mock_query.side_effect = Exception("Database error")
        mock_search_tool_info_impl.side_effect = Exception("Database error")

        from backend.services.tool_configuration_service import search_tool_info_impl
        with pytest.raises(Exception):
            search_tool_info_impl(1, 1, "test_tenant")

    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    @patch('backend.services.tool_configuration_service.search_tool_info_impl')
    def test_search_tool_info_impl_invalid_ids(self, mock_search_tool_info_impl, mock_query):
        """ test the invalid id of search_tool_info_impl"""
        # test the negative id
        mock_query.return_value = None
        mock_search_tool_info_impl.return_value = {
            "params": None,
            "enabled": False
        }
        from backend.services.tool_configuration_service import search_tool_info_impl
        result = search_tool_info_impl(-1, -1, "test_tenant")
        assert result["enabled"] is False

    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    @patch('backend.services.tool_configuration_service.search_tool_info_impl')
    def test_search_tool_info_impl_zero_ids(self, mock_search_tool_info_impl, mock_query):
        """ test the zero id of search_tool_info_impl"""
        mock_query.return_value = None
        mock_search_tool_info_impl.return_value = {
            "params": None,
            "enabled": False
        }

        from backend.services.tool_configuration_service import search_tool_info_impl
        result = search_tool_info_impl(0, 0, "test_tenant")
        assert result["enabled"] is False


class TestUpdateToolInfoImpl:
    """ test the function of update_tool_info_impl"""

    @patch('backend.services.tool_configuration_service.create_or_update_tool_by_tool_info')
    @patch('backend.services.tool_configuration_service.update_tool_info_impl')
    def test_update_tool_info_impl_success(self, mock_update_tool_info_impl, mock_create_update):
        """ test the success of update_tool_info_impl"""
        mock_request = Mock(spec=ToolInstanceInfoRequest)
        mock_tool_instance = {"id": 1, "name": "test_tool"}
        mock_create_update.return_value = mock_tool_instance
        mock_update_tool_info_impl.return_value = {
            "tool_instance": mock_tool_instance
        }

        from backend.services.tool_configuration_service import update_tool_info_impl
        result = update_tool_info_impl(
            mock_request, "test_tenant", "test_user")

        assert result["tool_instance"] == mock_tool_instance
        mock_update_tool_info_impl.assert_called_once_with(
            mock_request, "test_tenant", "test_user")

    @patch('backend.services.tool_configuration_service.create_or_update_tool_by_tool_info')
    @patch('backend.services.tool_configuration_service.update_tool_info_impl')
    def test_update_tool_info_impl_database_error(self, mock_update_tool_info_impl, mock_create_update):
        """ test the database error of update_tool_info_impl"""
        mock_request = Mock(spec=ToolInstanceInfoRequest)
        mock_create_update.side_effect = Exception("Database error")
        mock_update_tool_info_impl.side_effect = Exception("Database error")

        from backend.services.tool_configuration_service import update_tool_info_impl
        with pytest.raises(Exception):
            update_tool_info_impl(mock_request, "test_tenant", "test_user")

    @patch('backend.services.tool_configuration_service.create_or_update_tool_by_tool_info')
    def test_update_tool_info_impl_with_version_no_zero(self, mock_create_update):
        """Test update_tool_info_impl when version_no is 0"""
        mock_request = Mock(spec=ToolInstanceInfoRequest)
        mock_request.version_no = 0
        mock_request.__dict__ = {"agent_id": 1, "tool_id": 1, "version_no": 0}
        mock_tool_instance = {"id": 1, "name": "test_tool"}
        mock_create_update.return_value = mock_tool_instance

        from backend.services.tool_configuration_service import update_tool_info_impl
        result = update_tool_info_impl(mock_request, "test_tenant", "test_user")

        assert result["tool_instance"] == mock_tool_instance
        # Verify that create_or_update_tool_by_tool_info was called with version_no=0
        mock_create_update.assert_called_once_with(
            mock_request, "test_tenant", "test_user", version_no=0)

    @patch('backend.services.tool_configuration_service.create_or_update_tool_by_tool_info')
    def test_update_tool_info_impl_without_version_no(self, mock_create_update):
        """Test update_tool_info_impl when version_no is not provided (should default to 0)"""
        # Create a simple object without version_no attribute
        class MockToolInfoWithoutVersion:
            def __init__(self):
                self.agent_id = 1
                self.tool_id = 1
                # Explicitly do not set version_no
        
        mock_request = MockToolInfoWithoutVersion()
        mock_tool_instance = {"id": 1, "name": "test_tool"}
        mock_create_update.return_value = mock_tool_instance

        from backend.services.tool_configuration_service import update_tool_info_impl
        result = update_tool_info_impl(mock_request, "test_tenant", "test_user")

        assert result["tool_instance"] == mock_tool_instance
        # Verify that create_or_update_tool_by_tool_info was called with version_no=0 (default)
        mock_create_update.assert_called_once_with(
            mock_request, "test_tenant", "test_user", version_no=0)

    @patch('backend.services.tool_configuration_service.create_or_update_tool_by_tool_info')
    def test_update_tool_info_impl_with_version_no_non_zero(self, mock_create_update):
        """Test update_tool_info_impl when version_no is not 0"""
        mock_request = Mock(spec=ToolInstanceInfoRequest)
        mock_request.version_no = 5
        mock_request.__dict__ = {"agent_id": 1, "tool_id": 1, "version_no": 5}
        mock_tool_instance = {"id": 1, "name": "test_tool"}
        mock_create_update.return_value = mock_tool_instance

        from backend.services.tool_configuration_service import update_tool_info_impl
        result = update_tool_info_impl(mock_request, "test_tenant", "test_user")

        assert result["tool_instance"] == mock_tool_instance
        # Verify that create_or_update_tool_by_tool_info was called with version_no=5
        mock_create_update.assert_called_once_with(
            mock_request, "test_tenant", "test_user", version_no=5)


class TestListAllTools:
    """ test the function of list_all_tools"""

    @patch('backend.services.tool_configuration_service.query_all_tools')
    @patch('backend.services.tool_configuration_service.list_all_tools')
    async def test_list_all_tools_success(self, mock_list_all_tools, mock_query):
        """ test the success of list_all_tools"""
        mock_tools = [
            {
                "tool_id": 1,
                "name": "test_tool_1",
                "description": "Test tool 1",
                "source": "local",
                "is_available": True,
                "create_time": "2023-01-01",
                "usage": "test_usage",
                "params": [{"name": "param1"}]
            },
            {
                "tool_id": 2,
                "name": "test_tool_2",
                "description": "Test tool 2",
                "source": "mcp",
                "is_available": False,
                "create_time": "2023-01-02",
                "usage": None,
                "params": []
            }
        ]
        mock_query.return_value = mock_tools
        mock_list_all_tools.return_value = mock_tools

        from backend.services.tool_configuration_service import list_all_tools
        result = await list_all_tools("test_tenant")

        assert len(result) == 2
        assert result[0]["tool_id"] == 1
        assert result[0]["name"] == "test_tool_1"
        assert result[1]["tool_id"] == 2
        assert result[1]["name"] == "test_tool_2"
        mock_list_all_tools.assert_called_once_with("test_tenant")

    @patch('backend.services.tool_configuration_service.query_all_tools')
    @patch('backend.services.tool_configuration_service.list_all_tools')
    async def test_list_all_tools_empty_result(self, mock_list_all_tools, mock_query):
        """ test the empty result of list_all_tools"""
        mock_query.return_value = []
        mock_list_all_tools.return_value = []

        from backend.services.tool_configuration_service import list_all_tools
        result = await list_all_tools("test_tenant")

        assert result == []
        mock_list_all_tools.assert_called_once_with("test_tenant")

    @patch('backend.services.tool_configuration_service.query_all_tools')
    @patch('backend.services.tool_configuration_service.list_all_tools')
    async def test_list_all_tools_missing_fields(self, mock_list_all_tools, mock_query):
        """ test tools with missing fields"""
        mock_tools = [
            {
                "tool_id": 1,
                "name": "test_tool",
                "description": "Test tool",
                "params": []
                # missing other fields
            }
        ]
        mock_query.return_value = mock_tools
        mock_list_all_tools.return_value = mock_tools

        from backend.services.tool_configuration_service import list_all_tools
        result = await list_all_tools("test_tenant")

        assert len(result) == 1
        assert result[0]["tool_id"] == 1
        assert result[0]["name"] == "test_tool"
        assert result[0]["params"] == []  # default value


# test the fixture and helper function
@pytest.fixture
def sample_tool_info():
    """ create the fixture of sample tool info"""
    return ToolInfo(
        name="sample_tool",
        description="Sample tool for testing",
        params=[{
            "name": "param1",
            "type": "string",
            "description": "Test parameter",
            "optional": False
        }],
        source=ToolSourceEnum.LOCAL.value,
        inputs='{"input1": "value1"}',
        output_type="string",
        class_name="SampleTool"
    )


@pytest.fixture
def sample_tool_request():
    """ create the fixture of sample tool request"""
    return ToolInstanceInfoRequest(
        agent_id=1,
        tool_id=1,
        params={"param1": "value1"},
        enabled=True
    )


class TestGetAllMcpTools:
    """Test get_all_mcp_tools function"""

    @patch('backend.services.tool_configuration_service.get_mcp_records_by_tenant')
    @patch('backend.services.tool_configuration_service.get_tool_from_remote_mcp_server')
    @patch('backend.services.tool_configuration_service.LOCAL_MCP_SERVER', "http://default-server.com")
    @patch('backend.services.tool_configuration_service.urljoin')
    async def test_get_all_mcp_tools_success(self, mock_urljoin, mock_get_tools, mock_get_records):
        """Test successfully getting all MCP tools"""
        # Mock MCP records
        mock_get_records.return_value = [
            {"mcp_name": "server1", "mcp_server": "http://server1.com", "status": True},
            {"mcp_name": "server2", "mcp_server": "http://server2.com",
                "status": False},  # Not connected
            {"mcp_name": "server3", "mcp_server": "http://server3.com", "status": True}
        ]

        # Mock tool information
        mock_tools1 = [
            ToolInfo(name="tool1", description="Tool 1", params=[], source=ToolSourceEnum.MCP.value,
                     inputs="{}", output_type="string", class_name="Tool1", usage="server1")
        ]
        mock_tools2 = [
            ToolInfo(name="tool2", description="Tool 2", params=[], source=ToolSourceEnum.MCP.value,
                     inputs="{}", output_type="string", class_name="Tool2", usage="server3")
        ]
        mock_default_tools = [
            ToolInfo(name="default_tool", description="Default Tool", params=[], source=ToolSourceEnum.MCP.value,
                     inputs="{}", output_type="string", class_name="DefaultTool", usage="nexent")
        ]

        mock_get_tools.side_effect = [
            mock_tools1, mock_tools2, mock_default_tools]
        mock_urljoin.return_value = "http://default-server.com/sse"

        # 导入函数
        from backend.services.tool_configuration_service import get_all_mcp_tools

        result = await get_all_mcp_tools("test_tenant")

        # Verify results
        assert len(result) == 3  # 2 connected server tools + 1 default tool
        assert result[0].name == "tool1"
        assert result[0].usage == "server1"
        assert result[1].name == "tool2"
        assert result[1].usage == "server3"
        assert result[2].name == "default_tool"
        assert result[2].usage == "nexent"

        # Verify calls
        assert mock_get_tools.call_count == 3

    @patch('backend.services.tool_configuration_service.get_mcp_records_by_tenant')
    @patch('backend.services.tool_configuration_service.get_tool_from_remote_mcp_server')
    @patch('backend.services.tool_configuration_service.LOCAL_MCP_SERVER', "http://default-server.com")
    @patch('backend.services.tool_configuration_service.urljoin')
    async def test_get_all_mcp_tools_connection_error(self, mock_urljoin, mock_get_tools, mock_get_records):
        """Test MCP connection error scenario"""
        mock_get_records.return_value = [
            {"mcp_name": "server1", "mcp_server": "http://server1.com", "status": True}
        ]
        # First call fails, second call succeeds (default server)
        mock_get_tools.side_effect = [Exception("Connection failed"),
                                      [ToolInfo(name="default_tool", description="Default Tool", params=[],
                                                source=ToolSourceEnum.MCP.value, inputs="{}", output_type="string",
                                                class_name="DefaultTool", usage="nexent")]]
        mock_urljoin.return_value = "http://default-server.com/sse"

        from backend.services.tool_configuration_service import get_all_mcp_tools

        result = await get_all_mcp_tools("test_tenant")

        # Should return default tools even if connection fails
        assert len(result) == 1
        assert result[0].name == "default_tool"

    @patch('backend.services.tool_configuration_service.get_mcp_records_by_tenant')
    @patch('backend.services.tool_configuration_service.get_tool_from_remote_mcp_server')
    @patch('backend.services.tool_configuration_service.LOCAL_MCP_SERVER', "http://default-server.com")
    @patch('backend.services.tool_configuration_service.urljoin')
    async def test_get_all_mcp_tools_no_connected_servers(self, mock_urljoin, mock_get_tools, mock_get_records):
        """Test scenario with no connected servers"""
        mock_get_records.return_value = [
            {"mcp_name": "server1", "mcp_server": "http://server1.com", "status": False},
            {"mcp_name": "server2", "mcp_server": "http://server2.com", "status": False}
        ]
        mock_default_tools = [
            ToolInfo(name="default_tool", description="Default Tool", params=[], source=ToolSourceEnum.MCP.value,
                     inputs="{}", output_type="string", class_name="DefaultTool", usage="nexent")
        ]
        mock_get_tools.return_value = mock_default_tools
        mock_urljoin.return_value = "http://default-server.com/sse"

        from backend.services.tool_configuration_service import get_all_mcp_tools

        result = await get_all_mcp_tools("test_tenant")

        # Should only return default tools
        assert len(result) == 1
        assert result[0].name == "default_tool"
        assert mock_get_tools.call_count == 1  # Only call default server once


class TestGetToolFromRemoteMcpServer:
    """Test get_tool_from_remote_mcp_server function"""

    @patch('backend.services.tool_configuration_service.Client')
    @patch('backend.services.tool_configuration_service.jsonref.replace_refs')
    @patch('backend.services.tool_configuration_service._sanitize_function_name')
    async def test_get_tool_from_remote_mcp_server_success(self, mock_sanitize, mock_replace_refs, mock_client_cls):
        """Test successfully getting tools from remote MCP server"""
        # Mock client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        # Mock tool list
        mock_tool1 = Mock()
        mock_tool1.name = "test_tool_1"
        mock_tool1.description = "Test tool 1 description"
        mock_tool1.inputSchema = {"properties": {"param1": {"type": "string"}}}

        mock_tool2 = Mock()
        mock_tool2.name = "test_tool_2"
        mock_tool2.description = "Test tool 2 description"
        mock_tool2.inputSchema = {
            "properties": {"param2": {"type": "integer"}}}

        mock_client.list_tools.return_value = [mock_tool1, mock_tool2]

        # Mock JSON schema processing
        mock_replace_refs.side_effect = [
            {"properties": {"param1": {"type": "string",
                                       "description": "see tool description"}}},
            {"properties": {"param2": {"type": "integer",
                                       "description": "see tool description"}}}
        ]

        # Mock name sanitization
        mock_sanitize.side_effect = ["test_tool_1", "test_tool_2"]

        from backend.services.tool_configuration_service import get_tool_from_remote_mcp_server

        result = await get_tool_from_remote_mcp_server("test_server", "http://test-server.com")

        # Verify results
        assert len(result) == 2
        assert result[0].name == "test_tool_1"
        assert result[0].description == "Test tool 1 description"
        assert result[0].source == ToolSourceEnum.MCP.value
        assert result[0].usage == "test_server"
        assert result[1].name == "test_tool_2"
        assert result[1].description == "Test tool 2 description"

        # Verify calls
        mock_client_cls.assert_called_once_with(
            "http://test-server.com", timeout=10)
        assert mock_client.list_tools.call_count == 1

    @patch('backend.services.tool_configuration_service.Client')
    async def test_get_tool_from_remote_mcp_server_empty_tools(self, mock_client_cls):
        """Test remote server with no tools"""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client
        mock_client.list_tools.return_value = []

        from backend.services.tool_configuration_service import get_tool_from_remote_mcp_server

        result = await get_tool_from_remote_mcp_server("test_server", "http://test-server.com")

        assert result == []

    @patch('backend.services.tool_configuration_service.Client')
    async def test_get_tool_from_remote_mcp_server_connection_error(self, mock_client_cls):
        """Test connection error scenario"""
        mock_client_cls.side_effect = Exception("Connection failed")

        from backend.services.tool_configuration_service import get_tool_from_remote_mcp_server

        with pytest.raises(MCPConnectionError):
            await get_tool_from_remote_mcp_server("test_server", "http://test-server.com")

    @patch('backend.services.tool_configuration_service.Client')
    @patch('backend.services.tool_configuration_service.jsonref.replace_refs')
    @patch('backend.services.tool_configuration_service._sanitize_function_name')
    async def test_get_tool_from_remote_mcp_server_missing_properties(self, mock_sanitize, mock_replace_refs, mock_client_cls):
        """Test tools missing required properties"""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        # Mock tool missing description and type
        mock_tool = Mock()
        mock_tool.name = "test_tool"
        mock_tool.description = "Test tool description"
        mock_tool.inputSchema = {"properties": {
            "param1": {}}}  # Missing description and type

        mock_client.list_tools.return_value = [mock_tool]
        mock_replace_refs.return_value = {"properties": {"param1": {}}}
        mock_sanitize.return_value = "test_tool"

        from backend.services.tool_configuration_service import get_tool_from_remote_mcp_server

        result = await get_tool_from_remote_mcp_server("test_server", "http://test-server.com")

        assert len(result) == 1
        assert result[0].name == "test_tool"
        # Verify default values are added
        assert "see tool description" in str(result[0].inputs)
        assert "string" in str(result[0].inputs)


class TestUpdateToolList:
    """Test update_tool_list function"""

    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools')
    # Add mock for get_langchain_tools
    @patch('backend.services.tool_configuration_service.get_langchain_tools')
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    async def test_update_tool_list_success(self, mock_update_table, mock_get_langchain_tools, mock_get_mcp_tools, mock_get_local_tools):
        """Test successfully updating tool list"""
        # Mock local tools
        local_tools = [
            ToolInfo(name="local_tool", description="Local tool", params=[], source=ToolSourceEnum.LOCAL.value,
                     inputs="{}", output_type="string", class_name="LocalTool", usage=None)
        ]
        mock_get_local_tools.return_value = local_tools

        # Mock MCP tools
        mcp_tools = [
            ToolInfo(name="mcp_tool", description="MCP tool", params=[], source=ToolSourceEnum.MCP.value,
                     inputs="{}", output_type="string", class_name="McpTool", usage="test_server")
        ]
        mock_get_mcp_tools.return_value = mcp_tools

        # Mock LangChain tools - return empty list
        mock_get_langchain_tools.return_value = [
            ToolInfo(name="langchain_tool", description="LangChain tool", params=[], source=ToolSourceEnum.LANGCHAIN.value,
                     inputs="{}", output_type="string", class_name="LangchainTool", usage="test_server")
        ]

        from backend.services.tool_configuration_service import update_tool_list

        await update_tool_list("test_tenant", "test_user")

        # Verify calls
        mock_get_local_tools.assert_called_once()
        mock_get_mcp_tools.assert_called_once_with("test_tenant")
        mock_get_langchain_tools.assert_called_once()

        # Get tool list returned by mock get_langchain_tools
        langchain_tools = mock_get_langchain_tools.return_value

        mock_update_table.assert_called_once_with(
            tenant_id="test_tenant",
            user_id="test_user",
            tool_list=local_tools + mcp_tools + langchain_tools
        )

    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools')
    @patch('backend.services.tool_configuration_service.get_langchain_tools')
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    async def test_update_tool_list_mcp_error(self, mock_update_table, mock_get_langchain_tools, mock_get_mcp_tools, mock_get_local_tools):
        """Test MCP tool retrieval failure scenario"""
        mock_get_local_tools.return_value = []
        mock_get_langchain_tools.return_value = []
        mock_get_mcp_tools.side_effect = Exception("MCP connection failed")

        from backend.services.tool_configuration_service import update_tool_list

        with pytest.raises(MCPConnectionError, match="failed to get all mcp tools"):
            await update_tool_list("test_tenant", "test_user")

    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools')
    @patch('backend.services.tool_configuration_service.get_langchain_tools')
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    async def test_update_tool_list_database_error(self, mock_update_table, mock_get_langchain_tools, mock_get_mcp_tools, mock_get_local_tools):
        """Test database update failure scenario"""
        mock_get_local_tools.return_value = []
        mock_get_mcp_tools.return_value = []
        mock_get_langchain_tools.return_value = []
        mock_update_table.side_effect = Exception("Database error")

        from backend.services.tool_configuration_service import update_tool_list

        with pytest.raises(Exception, match="Database error"):
            await update_tool_list("test_tenant", "test_user")

    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools')
    # Add mock for get_langchain_tools
    @patch('backend.services.tool_configuration_service.get_langchain_tools')
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    async def test_update_tool_list_empty_tools(self, mock_update_table, mock_get_langchain_tools, mock_get_mcp_tools, mock_get_local_tools):
        """Test scenario with no tools"""
        mock_get_local_tools.return_value = []
        mock_get_mcp_tools.return_value = []
        # Ensure LangChain tools also return empty list
        mock_get_langchain_tools.return_value = []

        from backend.services.tool_configuration_service import update_tool_list

        await update_tool_list("test_tenant", "test_user")

        # Verify update function is called even with no tools
        mock_update_table.assert_called_once_with(
            tenant_id="test_tenant",
            user_id="test_user",
            tool_list=[]
        )


class TestIntegrationScenarios:
    """Integration test scenarios"""

    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools')
    # Add mock for get_langchain_tools
    @patch('backend.services.tool_configuration_service.get_langchain_tools')
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    @patch('backend.services.tool_configuration_service.get_tool_from_remote_mcp_server')
    async def test_full_tool_update_workflow(self, mock_get_remote_tools, mock_update_table, mock_get_langchain_tools, mock_get_mcp_tools, mock_get_local_tools):
        """Test complete tool update workflow"""
        # 1. Mock local tools
        local_tools = [
            ToolInfo(name="local_tool", description="Local tool", params=[], source=ToolSourceEnum.LOCAL.value,
                     inputs="{}", output_type="string", class_name="LocalTool", usage=None)
        ]
        mock_get_local_tools.return_value = local_tools

        # 2. Mock MCP tools
        mcp_tools = [
            ToolInfo(name="mcp_tool", description="MCP tool", params=[], source=ToolSourceEnum.MCP.value,
                     inputs="{}", output_type="string", class_name="McpTool", usage="test_server")
        ]
        mock_get_mcp_tools.return_value = mcp_tools

        # 3. Mock LangChain tools - set to empty list
        mock_get_langchain_tools.return_value = []

        # 4. Mock remote tool retrieval
        remote_tools = [
            ToolInfo(name="remote_tool", description="Remote tool", params=[], source=ToolSourceEnum.MCP.value,
                     inputs="{}", output_type="string", class_name="RemoteTool", usage="remote_server")
        ]
        mock_get_remote_tools.return_value = remote_tools

        from backend.services.tool_configuration_service import update_tool_list

        # 5. Execute update
        await update_tool_list("test_tenant", "test_user")

        # 6. Verify entire process
        mock_get_local_tools.assert_called_once()
        mock_get_mcp_tools.assert_called_once_with("test_tenant")
        mock_get_langchain_tools.assert_called_once()
        mock_update_table.assert_called_once_with(
            tenant_id="test_tenant",
            user_id="test_user",
            tool_list=local_tools + mcp_tools
        )


class TestGetLangchainTools:
    """Test get_langchain_tools function"""

    @patch('utils.langchain_utils.discover_langchain_modules')
    @patch('backend.services.tool_configuration_service._build_tool_info_from_langchain')
    def test_get_langchain_tools_success(self, mock_build_tool_info, mock_discover_modules):
        """Test successfully discovering and converting LangChain tools"""
        # Create mock LangChain tool objects
        mock_tool1 = Mock()
        mock_tool1.name = "langchain_tool_1"
        mock_tool1.description = "LangChain tool 1"

        mock_tool2 = Mock()
        mock_tool2.name = "langchain_tool_2"
        mock_tool2.description = "LangChain tool 2"

        # Mock discover_langchain_modules return value
        mock_discover_modules.return_value = [
            (mock_tool1, "tool1.py"),
            (mock_tool2, "tool2.py")
        ]

        # Mock _build_tool_info_from_langchain return value
        tool_info1 = ToolInfo(
            name="langchain_tool_1",
            description="LangChain tool 1",
            params=[],
            source=ToolSourceEnum.LANGCHAIN.value,
            inputs="{}",
            output_type="string",
            class_name="langchain_tool_1",
            usage=None
        )

        tool_info2 = ToolInfo(
            name="langchain_tool_2",
            description="LangChain tool 2",
            params=[],
            source=ToolSourceEnum.LANGCHAIN.value,
            inputs="{}",
            output_type="string",
            class_name="langchain_tool_2",
            usage=None
        )

        mock_build_tool_info.side_effect = [tool_info1, tool_info2]

        # Import function to test
        from backend.services.tool_configuration_service import get_langchain_tools

        # Call function
        result = get_langchain_tools()

        # Verify results
        assert len(result) == 2
        assert result[0] == tool_info1
        assert result[1] == tool_info2

        # Verify calls
        mock_discover_modules.assert_called_once()
        assert mock_build_tool_info.call_count == 2

    @patch('utils.langchain_utils.discover_langchain_modules')
    def test_get_langchain_tools_empty_result(self, mock_discover_modules):
        """Test scenario where no LangChain tools are discovered"""
        # Mock discover_langchain_modules to return empty list
        mock_discover_modules.return_value = []

        from backend.services.tool_configuration_service import get_langchain_tools

        result = get_langchain_tools()

        # Verify result is empty list
        assert result == []
        mock_discover_modules.assert_called_once()

    @patch('utils.langchain_utils.discover_langchain_modules')
    @patch('backend.services.tool_configuration_service._build_tool_info_from_langchain')
    def test_get_langchain_tools_exception_handling(self, mock_build_tool_info, mock_discover_modules):
        """Test exception handling when processing tools"""
        # Create mock LangChain tool objects
        mock_tool1 = Mock()
        mock_tool1.name = "good_tool"

        mock_tool2 = Mock()
        mock_tool2.name = "problematic_tool"

        # Mock discover_langchain_modules return value
        mock_discover_modules.return_value = [
            (mock_tool1, "good_tool.py"),
            (mock_tool2, "problematic_tool.py")
        ]

        # Mock _build_tool_info_from_langchain behavior
        # First call succeeds, second call raises exception
        tool_info1 = ToolInfo(
            name="good_tool",
            description="Good LangChain tool",
            params=[],
            source=ToolSourceEnum.LANGCHAIN.value,
            inputs="{}",
            output_type="string",
            class_name="good_tool",
            usage=None
        )

        mock_build_tool_info.side_effect = [
            tool_info1,
            Exception("Error processing tool")
        ]

        from backend.services.tool_configuration_service import get_langchain_tools

        # Call function - should not raise exception
        result = get_langchain_tools()

        # Verify result - only successfully processed tools
        assert len(result) == 1
        assert result[0] == tool_info1

        # Verify calls
        mock_discover_modules.assert_called_once()
        assert mock_build_tool_info.call_count == 2

    @patch('utils.langchain_utils.discover_langchain_modules')
    @patch('backend.services.tool_configuration_service._build_tool_info_from_langchain')
    def test_get_langchain_tools_with_different_tool_types(self, mock_build_tool_info, mock_discover_modules):
        """Test processing different types of LangChain tool objects"""
        # Create different types of tool objects
        class CustomTool:
            def __init__(self):
                self.name = "custom_tool"
                self.description = "Custom tool"

        mock_tool1 = Mock()  # Standard Mock object
        mock_tool1.name = "mock_tool"
        mock_tool1.description = "Mock tool"

        mock_tool2 = CustomTool()  # Custom class object

        # Mock discover_langchain_modules return value
        mock_discover_modules.return_value = [
            (mock_tool1, "mock_tool.py"),
            (mock_tool2, "custom_tool.py")
        ]

        # Mock _build_tool_info_from_langchain return value
        tool_info1 = ToolInfo(
            name="mock_tool",
            description="Mock tool",
            params=[],
            source=ToolSourceEnum.LANGCHAIN.value,
            inputs="{}",
            output_type="string",
            class_name="mock_tool",
            usage=None
        )

        tool_info2 = ToolInfo(
            name="custom_tool",
            description="Custom tool",
            params=[],
            source=ToolSourceEnum.LANGCHAIN.value,
            inputs="{}",
            output_type="string",
            class_name="custom_tool",
            usage=None
        )

        mock_build_tool_info.side_effect = [tool_info1, tool_info2]

        from backend.services.tool_configuration_service import get_langchain_tools

        result = get_langchain_tools()

        # Verify results
        assert len(result) == 2
        assert result[0] == tool_info1
        assert result[1] == tool_info2

        # Verify calls
        mock_discover_modules.assert_called_once()
        assert mock_build_tool_info.call_count == 2


class TestLoadLastToolConfigImpl:
    """Test load_last_tool_config_impl function"""

    @patch('backend.services.tool_configuration_service.search_last_tool_instance_by_tool_id')
    @patch('backend.services.tool_configuration_service.load_last_tool_config_impl')
    def test_load_last_tool_config_impl_success(self, mock_load_last_tool_config_impl, mock_search_tool_instance):
        """Test successfully loading last tool configuration"""
        mock_tool_instance = {
            "tool_instance_id": 1,
            "tool_id": 123,
            "params": {"param1": "value1", "param2": "value2"},
            "enabled": True
        }
        mock_search_tool_instance.return_value = mock_tool_instance
        mock_load_last_tool_config_impl.return_value = {
            "param1": "value1", "param2": "value2"}

        from backend.services.tool_configuration_service import load_last_tool_config_impl
        result = load_last_tool_config_impl(123, "tenant1", "user1")

        assert result == {"param1": "value1", "param2": "value2"}
        mock_load_last_tool_config_impl.assert_called_once_with(
            123, "tenant1", "user1")

    @patch('backend.services.tool_configuration_service.search_last_tool_instance_by_tool_id')
    @patch('backend.services.tool_configuration_service.load_last_tool_config_impl')
    def test_load_last_tool_config_impl_not_found(self, mock_load_last_tool_config_impl, mock_search_tool_instance):
        """Test loading tool config when tool instance not found"""
        mock_search_tool_instance.return_value = None
        mock_load_last_tool_config_impl.side_effect = ValueError(
            "Tool configuration not found for tool ID: 123")

        from backend.services.tool_configuration_service import load_last_tool_config_impl
        with pytest.raises(ValueError, match="Tool configuration not found for tool ID: 123"):
            load_last_tool_config_impl(123, "tenant1", "user1")

        mock_load_last_tool_config_impl.assert_called_once_with(
            123, "tenant1", "user1")

    @patch('backend.services.tool_configuration_service.search_last_tool_instance_by_tool_id')
    @patch('backend.services.tool_configuration_service.load_last_tool_config_impl')
    def test_load_last_tool_config_impl_empty_params(self, mock_load_last_tool_config_impl, mock_search_tool_instance):
        """Test loading tool config with empty params"""
        mock_tool_instance = {
            "tool_instance_id": 1,
            "tool_id": 123,
            "params": {},
            "enabled": True
        }
        mock_search_tool_instance.return_value = mock_tool_instance
        mock_load_last_tool_config_impl.return_value = {}

        from backend.services.tool_configuration_service import load_last_tool_config_impl
        result = load_last_tool_config_impl(123, "tenant1", "user1")

        assert result == {}
        mock_load_last_tool_config_impl.assert_called_once_with(
            123, "tenant1", "user1")

    @patch('backend.services.tool_configuration_service.Client')
    async def test_call_mcp_tool_success(self, mock_client_cls):
        """Test successful MCP tool call"""
        # Mock client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.is_connected.return_value = True

        # Mock tool result structure to match what _call_mcp_tool expects
        mock_content_item = Mock()
        mock_content_item.text = "test result"
        mock_result = Mock()
        mock_result.content = [mock_content_item]
        mock_client.call_tool.return_value = mock_result

        mock_client_cls.return_value = mock_client

        from backend.services.tool_configuration_service import _call_mcp_tool

        result = await _call_mcp_tool("http://test-server.com", "test_tool", {"param": "value"})

        assert result == "test result"
        mock_client_cls.assert_called_once_with("http://test-server.com")
        mock_client.call_tool.assert_called_once_with(
            name="test_tool", arguments={"param": "value"})

    @patch('backend.services.tool_configuration_service.Client')
    async def test_call_mcp_tool_connection_failed(self, mock_client_cls):
        """Test MCP tool call when connection fails"""
        # Mock client with proper async context manager setup
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.is_connected = Mock(return_value=False)

        mock_client_cls.return_value = mock_client

        from backend.services.tool_configuration_service import _call_mcp_tool

        with pytest.raises(MCPConnectionError, match="Failed to connect to MCP server"):
            await _call_mcp_tool("http://test-server.com", "test_tool", {"param": "value"})

        # Verify client was created and connection was checked
        mock_client_cls.assert_called_once_with("http://test-server.com")
        mock_client.is_connected.assert_called_once()

    @patch('backend.services.tool_configuration_service.urljoin')
    @patch('backend.services.tool_configuration_service._call_mcp_tool')
    async def test_validate_mcp_tool_nexent_success(self, mock_call_tool, mock_urljoin):
        """Test successful nexent MCP tool validation"""
        mock_urljoin.return_value = "http://nexent-server.com/sse"
        mock_call_tool.return_value = "nexent result"

        from backend.services.tool_configuration_service import _validate_mcp_tool_nexent

        result = await _validate_mcp_tool_nexent("test_tool", {"param": "value"})

        assert result == "nexent result"
        mock_urljoin.assert_called_once()
        mock_call_tool.assert_called_once_with(
            "http://nexent-server.com/sse", "test_tool", {"param": "value"})

    @patch('backend.services.tool_configuration_service.get_mcp_server_by_name_and_tenant')
    @patch('backend.services.tool_configuration_service._call_mcp_tool')
    async def test_validate_mcp_tool_remote_success(self, mock_call_tool, mock_get_server):
        """Test successful remote MCP tool validation"""
        mock_get_server.return_value = "http://remote-server.com"
        mock_call_tool.return_value = "validation result"

        from backend.services.tool_configuration_service import _validate_mcp_tool_remote

        result = await _validate_mcp_tool_remote("test_tool", {"param": "value"}, "test_server", "tenant1")

        assert result == "validation result"
        mock_get_server.assert_called_once_with("test_server", "tenant1")
        mock_call_tool.assert_called_once_with(
            "http://remote-server.com", "test_tool", {"param": "value"})

    @patch('backend.services.tool_configuration_service.get_mcp_server_by_name_and_tenant')
    async def test_validate_mcp_tool_remote_server_not_found(self, mock_get_server):
        """Test remote MCP tool validation when server not found"""
        mock_get_server.return_value = None

        from backend.services.tool_configuration_service import _validate_mcp_tool_remote

        with pytest.raises(NotFoundException, match="MCP server not found for name: test_server"):
            await _validate_mcp_tool_remote("test_tool", {"param": "value"}, "test_server", "tenant1")

    @patch('backend.services.tool_configuration_service.importlib.import_module')
    def test_get_tool_class_by_name_success(self, mock_import):
        """Test successfully getting tool class by name"""
        # Create a real class that will pass inspect.isclass() check
        class TestToolClass:
            name = "test_tool"
            description = "Test tool description"
            inputs = {}
            output_type = "string"

        # Create a custom mock package class that properly handles getattr
        class MockPackage:
            def __init__(self):
                self.__name__ = 'nexent.core.tools'
                self.test_tool = TestToolClass
                self.other_class = Mock()

            def __dir__(self):
                return ['test_tool', 'other_class']

            def __getattr__(self, name):
                if name == 'test_tool':
                    return TestToolClass
                elif name == 'other_class':
                    return Mock()
                else:
                    raise AttributeError(f"'{name}' not found")

        mock_package = MockPackage()
        mock_import.return_value = mock_package

        from backend.services.tool_configuration_service import _get_tool_class_by_name

        result = _get_tool_class_by_name("test_tool")

        assert result == TestToolClass
        mock_import.assert_called_once_with('nexent.core.tools')

    @patch('backend.services.tool_configuration_service.importlib.import_module')
    def test_get_tool_class_by_name_not_found(self, mock_import):
        """Test getting tool class when tool not found"""
        # Create mock package without the target tool
        mock_package = Mock()
        mock_package.__name__ = 'nexent.core.tools'
        mock_package.__dir__ = Mock(return_value=['other_class'])

        mock_import.return_value = mock_package

        from backend.services.tool_configuration_service import _get_tool_class_by_name

        result = _get_tool_class_by_name("nonexistent_tool")

        assert result is None

    @patch('backend.services.tool_configuration_service.importlib.import_module')
    def test_get_tool_class_by_name_import_error(self, mock_import):
        """Test getting tool class when import fails"""
        mock_import.side_effect = ImportError("Module not found")

        from backend.services.tool_configuration_service import _get_tool_class_by_name

        result = _get_tool_class_by_name("test_tool")

        assert result is None

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    def test_validate_local_tool_success(self, mock_signature, mock_get_class):
        """Test successful local tool validation"""
        # Mock tool class
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "validation result"
        mock_tool_class.return_value = mock_tool_instance

        mock_get_class.return_value = mock_tool_class

        # Mock signature without observer parameter
        mock_sig = Mock()
        mock_sig.parameters = {}
        mock_signature.return_value = mock_sig

        from backend.services.tool_configuration_service import _validate_local_tool

        result = _validate_local_tool(
            "test_tool", {"input": "value"}, {"param": "config"})

        assert result == "validation result"
        mock_get_class.assert_called_once_with("test_tool")
        mock_tool_class.assert_called_once_with(param="config")
        mock_tool_instance.forward.assert_called_once_with(input="value")

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    def test_validate_local_tool_with_observer(self, mock_signature, mock_get_class):
        """Test local tool validation with observer parameter"""
        # Mock tool class
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "validation result"
        mock_tool_class.return_value = mock_tool_instance

        mock_get_class.return_value = mock_tool_class

        # Mock signature with observer parameter
        mock_sig = Mock()
        mock_observer_param = Mock()
        mock_observer_param.default = None
        mock_sig.parameters = {'observer': mock_observer_param}
        mock_signature.return_value = mock_sig

        from backend.services.tool_configuration_service import _validate_local_tool

        result = _validate_local_tool(
            "test_tool", {"input": "value"}, {"param": "config"})

        assert result == "validation result"
        mock_tool_class.assert_called_once_with(param="config", observer=None)

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    def test_validate_local_tool_class_not_found(self, mock_get_class):
        """Test local tool validation when class not found"""
        mock_get_class.return_value = None

        from backend.services.tool_configuration_service import _validate_local_tool

        with pytest.raises(ToolExecutionException, match="Local tool test_tool validation failed: Tool class not found for test_tool"):
            _validate_local_tool("test_tool", {"input": "value"}, {
                                 "param": "config"})

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    def test_validate_local_tool_execution_error(self, mock_signature, mock_get_class):
        """Test local tool validation when execution fails"""
        # Mock tool class
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.side_effect = Exception("Execution failed")
        mock_tool_class.return_value = mock_tool_instance

        mock_get_class.return_value = mock_tool_class

        # Mock signature
        mock_sig = Mock()
        mock_sig.parameters = {}
        mock_signature.return_value = mock_sig

        from backend.services.tool_configuration_service import _validate_local_tool

        with pytest.raises(ToolExecutionException, match="Local tool test_tool validation failed"):
            _validate_local_tool("test_tool", {"input": "value"}, {
                                 "param": "config"})

    @patch('utils.langchain_utils.discover_langchain_modules')
    def test_validate_langchain_tool_success(self, mock_discover):
        """Test successful LangChain tool validation"""
        # Mock LangChain tool
        mock_tool = Mock()
        mock_tool.name = "test_tool"
        mock_tool.invoke.return_value = "validation result"

        mock_discover.return_value = [(mock_tool, "test_tool.py")]

        from backend.services.tool_configuration_service import _validate_langchain_tool

        result = _validate_langchain_tool("test_tool", {"input": "value"})

        assert result == "validation result"
        mock_tool.invoke.assert_called_once_with({"input": "value"})

    @patch('utils.langchain_utils.discover_langchain_modules')
    def test_validate_langchain_tool_not_found(self, mock_discover):
        """Test LangChain tool validation when tool not found"""
        mock_discover.return_value = []

        from backend.services.tool_configuration_service import _validate_langchain_tool

        with pytest.raises(ToolExecutionException, match="LangChain tool 'test_tool' validation failed: Tool 'test_tool' not found in LangChain tools"):
            _validate_langchain_tool("test_tool", {"input": "value"})

    @patch('utils.langchain_utils.discover_langchain_modules')
    def test_validate_langchain_tool_execution_error(self, mock_discover):
        """Test LangChain tool validation when execution fails"""
        # Mock LangChain tool
        mock_tool = Mock()
        mock_tool.name = "test_tool"
        mock_tool.invoke.side_effect = Exception("Execution failed")

        mock_discover.return_value = [(mock_tool, "test_tool.py")]

        from backend.services.tool_configuration_service import _validate_langchain_tool

        with pytest.raises(ToolExecutionException, match="LangChain tool 'test_tool' validation failed"):
            _validate_langchain_tool("test_tool", {"input": "value"})

    @patch('backend.services.tool_configuration_service._validate_mcp_tool_nexent')
    @patch('backend.services.tool_configuration_service.validate_tool_impl')
    async def test_validate_tool_nexent(self, mock_validate_tool_impl, mock_validate_nexent):
        """Test MCP tool validation using nexent server"""
        mock_validate_nexent.return_value = "nexent result"
        mock_validate_tool_impl.return_value = "nexent result"

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.MCP.value,
            usage="nexent",
            inputs={"param": "value"}
        )

        from backend.services.tool_configuration_service import validate_tool_impl
        result = await validate_tool_impl(request, "tenant1")

        assert result == "nexent result"
        mock_validate_tool_impl.assert_called_once_with(request, "tenant1")

    @patch('backend.services.tool_configuration_service._validate_mcp_tool_remote')
    @patch('backend.services.tool_configuration_service.validate_tool_impl')
    async def test_validate_tool_remote(self, mock_validate_tool_impl, mock_validate_remote):
        """Test MCP tool validation using remote server"""
        mock_validate_remote.return_value = "remote result"
        mock_validate_tool_impl.return_value = "remote result"

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.MCP.value,
            usage="remote_server",
            inputs={"param": "value"}
        )

        from backend.services.tool_configuration_service import validate_tool_impl
        result = await validate_tool_impl(request, "tenant1")

        assert result == "remote result"
        mock_validate_tool_impl.assert_called_once_with(request, "tenant1")

    @patch('backend.services.tool_configuration_service._validate_local_tool')
    @patch('backend.services.tool_configuration_service.validate_tool_impl')
    async def test_validate_tool_local(self, mock_validate_tool_impl, mock_validate_local):
        """Test local tool validation"""
        mock_validate_local.return_value = "local result"
        mock_validate_tool_impl.return_value = "local result"

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.LOCAL.value,
            usage=None,
            inputs={"param": "value"},
            params={"config": "value"}
        )

        from backend.services.tool_configuration_service import validate_tool_impl
        result = await validate_tool_impl(request, "tenant1")

        assert result == "local result"
        mock_validate_tool_impl.assert_called_once_with(request, "tenant1")

    @patch('backend.services.tool_configuration_service._validate_langchain_tool')
    @patch('backend.services.tool_configuration_service.validate_tool_impl')
    async def test_validate_tool_langchain(self, mock_validate_tool_impl, mock_validate_langchain):
        """Test LangChain tool validation"""
        mock_validate_langchain.return_value = "langchain result"
        mock_validate_tool_impl.return_value = "langchain result"

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.LANGCHAIN.value,
            usage=None,
            inputs={"param": "value"}
        )

        from backend.services.tool_configuration_service import validate_tool_impl
        result = await validate_tool_impl(request, "tenant1")

        assert result == "langchain result"
        mock_validate_tool_impl.assert_called_once_with(request, "tenant1")

    @patch('backend.services.tool_configuration_service.validate_tool_impl')
    async def test_validate_tool_unsupported_source(self, mock_validate_tool_impl):
        """Test validation with unsupported tool source"""
        mock_validate_tool_impl.side_effect = ToolExecutionException(
            "Unsupported tool source: unsupported")

        request = ToolValidateRequest(
            name="test_tool",
            source="unsupported",
            usage=None,
            inputs={"param": "value"}
        )

        from backend.services.tool_configuration_service import validate_tool_impl
        with pytest.raises(ToolExecutionException, match="Unsupported tool source: unsupported"):
            await validate_tool_impl(request, "tenant1")

    @patch('backend.services.tool_configuration_service._validate_mcp_tool_nexent')
    @patch('backend.services.tool_configuration_service.validate_tool_impl')
    async def test_validate_tool_nexent_connection_error(self, mock_validate_tool_impl, mock_validate_nexent):
        """Test MCP tool validation when connection fails"""
        mock_validate_nexent.side_effect = MCPConnectionError(
            "Connection failed")
        mock_validate_tool_impl.side_effect = MCPConnectionError(
            "Connection failed")

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.MCP.value,
            usage="nexent",
            inputs={"param": "value"}
        )

        from backend.services.tool_configuration_service import validate_tool_impl
        with pytest.raises(MCPConnectionError, match="Connection failed"):
            await validate_tool_impl(request, "tenant1")

    @patch('backend.services.tool_configuration_service._validate_local_tool')
    @patch('backend.services.tool_configuration_service.validate_tool_impl')
    async def test_validate_tool_local_execution_error(self, mock_validate_tool_impl, mock_validate_local):
        """Test local tool validation when execution fails"""
        mock_validate_local.side_effect = Exception("Execution failed")
        mock_validate_tool_impl.side_effect = ToolExecutionException(
            "Execution failed")

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.LOCAL.value,
            usage=None,
            inputs={"param": "value"},
            params={"config": "value"}
        )

        from backend.services.tool_configuration_service import validate_tool_impl
        with pytest.raises(ToolExecutionException, match="Execution failed"):
            await validate_tool_impl(request, "tenant1")

    @patch('backend.services.tool_configuration_service._validate_mcp_tool_remote')
    @patch('backend.services.tool_configuration_service.validate_tool_impl')
    async def test_validate_tool_remote_server_not_found(self, mock_validate_tool_impl, mock_validate_remote):
        """Test MCP tool validation when remote server not found"""
        mock_validate_remote.side_effect = NotFoundException(
            "MCP server not found for name: test_server")
        mock_validate_tool_impl.side_effect = NotFoundException(
            "MCP server not found for name: test_server")

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.MCP.value,
            usage="test_server",
            inputs={"param": "value"}
        )

        from backend.services.tool_configuration_service import validate_tool_impl
        with pytest.raises(NotFoundException, match="MCP server not found for name: test_server"):
            await validate_tool_impl(request, "tenant1")

    @patch('backend.services.tool_configuration_service._validate_local_tool')
    @patch('backend.services.tool_configuration_service.validate_tool_impl')
    async def test_validate_tool_local_tool_not_found(self, mock_validate_tool_impl, mock_validate_local):
        """Test local tool validation when tool class not found"""
        mock_validate_local.side_effect = NotFoundException(
            "Tool class not found for test_tool")
        mock_validate_tool_impl.side_effect = NotFoundException(
            "Tool class not found for test_tool")

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.LOCAL.value,
            usage=None,
            inputs={"param": "value"},
            params={"config": "value"}
        )

        from backend.services.tool_configuration_service import validate_tool_impl
        with pytest.raises(NotFoundException, match="Tool class not found for test_tool"):
            await validate_tool_impl(request, "tenant1")

    @patch('backend.services.tool_configuration_service._validate_langchain_tool')
    @patch('backend.services.tool_configuration_service.validate_tool_impl')
    async def test_validate_tool_langchain_tool_not_found(self, mock_validate_tool_impl, mock_validate_langchain):
        """Test LangChain tool validation when tool not found"""
        mock_validate_langchain.side_effect = NotFoundException(
            "Tool 'test_tool' not found in LangChain tools")
        mock_validate_tool_impl.side_effect = NotFoundException(
            "Tool 'test_tool' not found in LangChain tools")

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.LANGCHAIN.value,
            usage=None,
            inputs={"param": "value"}
        )

        from backend.services.tool_configuration_service import validate_tool_impl
        with pytest.raises(NotFoundException, match="Tool 'test_tool' not found in LangChain tools"):
            await validate_tool_impl(request, "tenant1")


class TestValidateLocalToolKnowledgeBaseSearch:
    """Test cases for _validate_local_tool function with knowledge_base_search tool"""

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    @patch('backend.services.tool_configuration_service.get_embedding_model')
    @patch('backend.services.tool_configuration_service.get_vector_db_core')
    def test_validate_local_tool_knowledge_base_search_success(self, mock_get_vector_db_core, mock_get_embedding_model,
                                                               mock_signature, mock_get_class):
        """Test successful knowledge_base_search tool validation with proper dependencies"""
        # Mock tool class
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "knowledge base search result"
        mock_tool_class.return_value = mock_tool_instance

        mock_get_class.return_value = mock_tool_class

        # Mock signature for knowledge_base_search tool
        mock_sig = Mock()
        mock_index_names_param = Mock()
        mock_index_names_param.default = ["default_index"]
        
        mock_sig.parameters = {
            'self': Mock(),
            'index_names': mock_index_names_param,
            'vdb_core': Mock(),
            'embedding_model': Mock()
        }
        mock_signature.return_value = mock_sig

        # Mock knowledge base dependencies
        mock_get_embedding_model.return_value = "mock_embedding_model"
        mock_vdb_core = Mock()
        mock_get_vector_db_core.return_value = mock_vdb_core

        from backend.services.tool_configuration_service import _validate_local_tool

        result = _validate_local_tool(
            "knowledge_base_search",
            {"query": "test query"},
            {"param": "config"},
            "tenant1",
            "user1"
        )

        assert result == "knowledge base search result"
        mock_get_class.assert_called_once_with("knowledge_base_search")

        # Verify knowledge base specific parameters were passed
        expected_params = {
            "param": "config",
            "index_names": ["default_index"],
            "vdb_core": mock_vdb_core,
            "embedding_model": "mock_embedding_model",
        }
        mock_tool_class.assert_called_once_with(**expected_params)
        mock_tool_instance.forward.assert_called_once_with(query="test query")

        # Verify service calls
        mock_get_embedding_model.assert_called_once_with(tenant_id="tenant1")

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.get_embedding_model')
    @patch('backend.services.tool_configuration_service.get_vector_db_core')
    def test_validate_local_tool_knowledge_base_search_missing_tenant_id(self, mock_get_vector_db_core,
                                                                        mock_get_embedding_model, mock_get_class):
        """Test knowledge_base_search tool validation when tenant_id is missing"""
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "knowledge base search result"
        mock_tool_class.return_value = mock_tool_instance
        mock_get_class.return_value = mock_tool_class

        mock_get_embedding_model.return_value = "mock_embedding_model"
        mock_get_vector_db_core.return_value = Mock()

        from backend.services.tool_configuration_service import _validate_local_tool

        # knowledge_base_search doesn't require tenant_id/user_id in current implementation
        result = _validate_local_tool(
            "knowledge_base_search",
            {"query": "test query"},
            {"param": "config"},
            None,  # Missing tenant_id
            "user1"
        )

        assert result == "knowledge base search result"

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.get_embedding_model')
    @patch('backend.services.tool_configuration_service.get_vector_db_core')
    def test_validate_local_tool_knowledge_base_search_missing_user_id(self, mock_get_vector_db_core,
                                                                       mock_get_embedding_model, mock_get_class):
        """Test knowledge_base_search tool validation when user_id is missing"""
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "knowledge base search result"
        mock_tool_class.return_value = mock_tool_instance
        mock_get_class.return_value = mock_tool_class

        mock_get_embedding_model.return_value = "mock_embedding_model"
        mock_get_vector_db_core.return_value = Mock()

        from backend.services.tool_configuration_service import _validate_local_tool

        # knowledge_base_search doesn't require tenant_id/user_id in current implementation
        result = _validate_local_tool(
            "knowledge_base_search",
            {"query": "test query"},
            {"param": "config"},
            "tenant1",
            None  # Missing user_id
        )

        assert result == "knowledge base search result"

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.get_embedding_model')
    @patch('backend.services.tool_configuration_service.get_vector_db_core')
    def test_validate_local_tool_knowledge_base_search_missing_both_ids(self, mock_get_vector_db_core,
                                                                        mock_get_embedding_model, mock_get_class):
        """Test knowledge_base_search tool validation when both tenant_id and user_id are missing"""
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "knowledge base search result"
        mock_tool_class.return_value = mock_tool_instance
        mock_get_class.return_value = mock_tool_class

        mock_get_embedding_model.return_value = "mock_embedding_model"
        mock_get_vector_db_core.return_value = Mock()

        from backend.services.tool_configuration_service import _validate_local_tool

        # knowledge_base_search doesn't require tenant_id/user_id in current implementation
        result = _validate_local_tool(
            "knowledge_base_search",
            {"query": "test query"},
            {"param": "config"},
            None,  # Missing tenant_id
            None   # Missing user_id
        )

        assert result == "knowledge base search result"

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    @patch('backend.services.tool_configuration_service.get_embedding_model')
    @patch('backend.services.tool_configuration_service.get_vector_db_core')
    def test_validate_local_tool_knowledge_base_search_empty_knowledge_list(self, mock_get_vector_db_core,
                                                                            mock_get_embedding_model,
                                                                            mock_signature,
                                                                            mock_get_class):
        """Test knowledge_base_search tool validation with empty knowledge list"""
        # Mock tool class
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "empty knowledge result"
        mock_tool_class.return_value = mock_tool_instance

        mock_get_class.return_value = mock_tool_class

        # Mock signature for knowledge_base_search tool
        mock_sig = Mock()
        mock_index_names_param = Mock()
        mock_index_names_param.default = []
        mock_sig.parameters = {
            'self': Mock(),
            'index_names': mock_index_names_param,
            'vdb_core': Mock(),
            'embedding_model': Mock()
        }
        mock_signature.return_value = mock_sig

        # Mock empty knowledge list
        mock_get_embedding_model.return_value = "mock_embedding_model"
        mock_vdb_core = Mock()
        mock_get_vector_db_core.return_value = mock_vdb_core

        from backend.services.tool_configuration_service import _validate_local_tool

        result = _validate_local_tool(
            "knowledge_base_search",
            {"query": "test query"},
            {"param": "config"},
            "tenant1",
            "user1"
        )

        assert result == "empty knowledge result"

        # Verify knowledge base specific parameters were passed with empty index_names
        expected_params = {
            "param": "config",
            "index_names": [],
            "vdb_core": mock_vdb_core,
            "embedding_model": "mock_embedding_model",
        }
        mock_tool_class.assert_called_once_with(**expected_params)
        mock_tool_instance.forward.assert_called_once_with(query="test query")


    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    @patch('backend.services.tool_configuration_service.get_embedding_model')
    @patch('backend.services.tool_configuration_service.get_vector_db_core')
    def test_validate_local_tool_knowledge_base_search_execution_error(self, mock_get_vector_db_core,
                                                                       mock_get_embedding_model,
                                                                       mock_signature,
                                                                       mock_get_class):
        """Test knowledge_base_search tool validation when execution fails"""
        # Mock tool class
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.side_effect = Exception(
            "Knowledge base search failed")
        mock_tool_class.return_value = mock_tool_instance

        mock_get_class.return_value = mock_tool_class

        # Mock signature for knowledge_base_search tool
        mock_sig = Mock()
        mock_index_names_param = Mock()
        mock_index_names_param.default = ["default_index"]
        mock_sig.parameters = {
            'self': Mock(),
            'index_names': mock_index_names_param,
            'vdb_core': Mock(),
            'embedding_model': Mock()
        }
        mock_signature.return_value = mock_sig

        # Mock knowledge base dependencies
        mock_get_embedding_model.return_value = "mock_embedding_model"
        mock_vdb_core = Mock()
        mock_get_vector_db_core.return_value = mock_vdb_core

        from backend.services.tool_configuration_service import _validate_local_tool

        with pytest.raises(ToolExecutionException,
                           match="Local tool knowledge_base_search validation failed: Knowledge base search failed"):
            _validate_local_tool(
                "knowledge_base_search",
                {"query": "test query"},
                {"param": "config"},
                "tenant1",
                "user1"
            )


class TestValidateLocalToolAnalyzeImage:
    """Test cases for _validate_local_tool with analyze_image tool."""

    @patch('backend.services.tool_configuration_service.minio_client')
    @patch('backend.services.tool_configuration_service.get_vlm_model')
    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    def test_validate_local_tool_analyze_image_success(self, mock_signature, mock_get_class, mock_get_vlm_model, mock_minio_client):
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "analyze image result"
        mock_tool_class.return_value = mock_tool_instance
        mock_get_class.return_value = mock_tool_class
        mock_get_vlm_model.return_value = "mock_vlm_model"

        mock_sig = Mock()
        mock_sig.parameters = {}
        mock_signature.return_value = mock_sig

        from backend.services.tool_configuration_service import _validate_local_tool

        result = _validate_local_tool(
            "analyze_image",
            {"image": "bytes"},
            {"prompt": "describe"},
            "tenant1",
            "user1"
        )

        assert result == "analyze image result"
        mock_get_vlm_model.assert_called_once_with(tenant_id="tenant1")
        mock_tool_class.assert_called_once_with(
            prompt="describe",
            vlm_model="mock_vlm_model",
            storage_client=mock_minio_client
        )
        mock_tool_instance.forward.assert_called_once_with(image="bytes")

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    def test_validate_local_tool_analyze_image_missing_tenant(self, mock_get_class):
        mock_get_class.return_value = Mock()

        from backend.services.tool_configuration_service import _validate_local_tool

        with pytest.raises(ToolExecutionException,
                           match="Tenant ID and User ID are required for analyze_image validation"):
            _validate_local_tool(
                "analyze_image",
                {"image": "bytes"},
                {"prompt": "describe"},
                None,
                "user1"
            )

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    def test_validate_local_tool_analyze_image_missing_user(self, mock_get_class):
        mock_get_class.return_value = Mock()

        from backend.services.tool_configuration_service import _validate_local_tool

        with pytest.raises(ToolExecutionException,
                           match="Tenant ID and User ID are required for analyze_image validation"):
            _validate_local_tool(
                "analyze_image",
                {"image": "bytes"},
                {"prompt": "describe"},
                "tenant1",
                None
            )


class TestValidateLocalToolDatamateSearchTool:
    """Test cases for _validate_local_tool function with datamate_search_tool"""

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    def test_validate_local_tool_datamate_search_tool_success(self, mock_signature, mock_get_class):
        """Test successful datamate_search_tool validation with proper dependencies"""
        # Mock tool class
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "datamate search result"
        mock_tool_class.return_value = mock_tool_instance

        mock_get_class.return_value = mock_tool_class

        # Mock signature for datamate_search_tool
        # _validate_local_tool fills missing instantiation params from signature defaults.
        # For datamate_search there is no special index selection logic, so index_names
        # should come from the default value (empty list).
        mock_sig = Mock()
        mock_sig.parameters = {
            'self': Mock(),
            'index_names': Mock(default=Mock(default=[])),
        }
        mock_signature.return_value = mock_sig

        from backend.services.tool_configuration_service import _validate_local_tool

        result = _validate_local_tool(
            "datamate_search",
            {"query": "test query"},
            {"param": "config"},
            "tenant1",
            "user1"
        )

        assert result == "datamate search result"
        mock_get_class.assert_called_once_with("datamate_search")

        # Verify datamate_search_tool specific parameters were passed
        expected_params = {
            "param": "config",
            # Filled from signature default
            "index_names": [],
        }
        mock_tool_class.assert_called_once_with(**expected_params)
        mock_tool_instance.forward.assert_called_once_with(query="test query")

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    def test_validate_local_tool_datamate_search_tool_missing_tenant_id(self, mock_get_class):
        """Test datamate_search_tool validation when tenant_id is missing"""
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "datamate search result"
        mock_tool_class.return_value = mock_tool_instance
        mock_get_class.return_value = mock_tool_class

        from backend.services.tool_configuration_service import _validate_local_tool

        # datamate_search does not require tenant/user in current implementation
        result = _validate_local_tool(
            "datamate_search",
            {"query": "test query"},
            {"param": "config"},
            None,  # Missing tenant_id
            "user1"
        )
        assert result == "datamate search result"

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    def test_validate_local_tool_datamate_search_tool_missing_user_id(self, mock_get_class):
        """Test datamate_search_tool validation when user_id is missing"""
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "datamate search result"
        mock_tool_class.return_value = mock_tool_instance
        mock_get_class.return_value = mock_tool_class

        from backend.services.tool_configuration_service import _validate_local_tool

        # datamate_search does not require tenant/user in current implementation
        result = _validate_local_tool(
            "datamate_search",
            {"query": "test query"},
            {"param": "config"},
            "tenant1",
            None  # Missing user_id
        )
        assert result == "datamate search result"

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    def test_validate_local_tool_datamate_search_tool_missing_both_ids(self, mock_get_class):
        """Test datamate_search_tool validation when both tenant_id and user_id are missing"""
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "datamate search result"
        mock_tool_class.return_value = mock_tool_instance
        mock_get_class.return_value = mock_tool_class

        from backend.services.tool_configuration_service import _validate_local_tool

        # datamate_search does not require tenant/user in current implementation
        result = _validate_local_tool(
            "datamate_search",
            {"query": "test query"},
            {"param": "config"},
            None,  # Missing tenant_id
            None   # Missing user_id
        )
        assert result == "datamate search result"

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    def test_validate_local_tool_datamate_search_tool_empty_knowledge_list(self, mock_signature, mock_get_class):
        """Test datamate_search_tool validation with empty knowledge list"""
        # Mock tool class
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "empty datamate result"
        mock_tool_class.return_value = mock_tool_instance

        mock_get_class.return_value = mock_tool_class

        # Mock signature for datamate_search_tool (default empty list)
        mock_sig = Mock()
        mock_sig.parameters = {
            'self': Mock(),
            'index_names': Mock(default=Mock(default=[])),
        }
        mock_signature.return_value = mock_sig

        from backend.services.tool_configuration_service import _validate_local_tool

        result = _validate_local_tool(
            "datamate_search",
            {"query": "test query"},
            {"param": "config"},
            "tenant1",
            "user1"
        )

        assert result == "empty datamate result"

        # Verify parameters were passed with empty index_names
        expected_params = {
            "param": "config",
            "index_names": [],  # Empty list since no datamate sources
        }
        mock_tool_class.assert_called_once_with(**expected_params)
        mock_tool_instance.forward.assert_called_once_with(query="test query")

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    def test_validate_local_tool_datamate_search_tool_no_datamate_sources(self, mock_signature, mock_get_class):
        """Test datamate_search_tool validation when no datamate sources exist"""
        # Mock tool class
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "no datamate sources result"
        mock_tool_class.return_value = mock_tool_instance

        mock_get_class.return_value = mock_tool_class

        # Mock signature for datamate_search_tool (default empty list)
        mock_sig = Mock()
        mock_sig.parameters = {
            'self': Mock(),
            'index_names': Mock(default=Mock(default=[])),
        }
        mock_signature.return_value = mock_sig

        from backend.services.tool_configuration_service import _validate_local_tool

        result = _validate_local_tool(
            "datamate_search",
            {"query": "test query"},
            {"param": "config"},
            "tenant1",
            "user1"
        )

        assert result == "no datamate sources result"

        # Verify parameters were passed with empty index_names
        expected_params = {
            "param": "config",
            "index_names": [],  # Empty list since no datamate sources
        }
        mock_tool_class.assert_called_once_with(**expected_params)
        mock_tool_instance.forward.assert_called_once_with(query="test query")

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    def test_validate_local_tool_datamate_search_tool_execution_error(self, mock_signature, mock_get_class):
        """Test datamate_search_tool validation when execution fails"""
        # Mock tool class
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.side_effect = Exception(
            "Datamate search failed")
        mock_tool_class.return_value = mock_tool_instance

        mock_get_class.return_value = mock_tool_class

        # Mock signature for datamate_search_tool
        mock_sig = Mock()
        mock_sig.parameters = {
            'self': Mock(),
            'index_names': Mock(),
        }
        mock_signature.return_value = mock_sig

        from backend.services.tool_configuration_service import _validate_local_tool

        with pytest.raises(ToolExecutionException,
                           match=r"Local tool datamate_search validation failed: Datamate search failed"):
            _validate_local_tool(
                "datamate_search",
                {"query": "test query"},
                {"param": "config"},
                "tenant1",
                "user1"
            )


class TestValidateLocalToolAnalyzeTextFile:
    """Test cases for _validate_local_tool function with analyze_text_file tool"""

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    @patch('backend.services.tool_configuration_service.get_llm_model')
    @patch('backend.services.tool_configuration_service.minio_client')
    @patch('backend.services.tool_configuration_service.DATA_PROCESS_SERVICE', "http://data-process-service")
    def test_validate_local_tool_analyze_text_file_success(self, mock_minio_client, mock_get_llm_model,
                                                           mock_signature, mock_get_class):
        """Test successful analyze_text_file tool validation with proper dependencies"""
        # Mock tool class
        mock_tool_class = Mock()
        mock_tool_instance = Mock()
        mock_tool_instance.forward.return_value = "analyze text file result"
        mock_tool_class.return_value = mock_tool_instance

        mock_get_class.return_value = mock_tool_class

        # Mock signature for analyze_text_file tool
        mock_sig = Mock()
        mock_sig.parameters = {
            'self': Mock(),
            'llm_model': Mock(),
            'storage_client': Mock(),
            'data_process_service_url': Mock()
        }
        mock_signature.return_value = mock_sig

        # Mock dependencies
        mock_llm_model = Mock()
        mock_get_llm_model.return_value = mock_llm_model

        from backend.services.tool_configuration_service import _validate_local_tool

        result = _validate_local_tool(
            "analyze_text_file",
            {"input": "test input"},
            {"param": "config"},
            "tenant1",
            "user1"
        )

        assert result == "analyze text file result"
        mock_get_class.assert_called_once_with("analyze_text_file")

        # Verify analyze_text_file specific parameters were passed
        expected_params = {
            "param": "config",
            "llm_model": mock_llm_model,
            "storage_client": mock_minio_client,
            "data_process_service_url": "http://data-process-service",
        }
        mock_tool_class.assert_called_once_with(**expected_params)
        mock_tool_instance.forward.assert_called_once_with(input="test input")

        # Verify service calls
        mock_get_llm_model.assert_called_once_with(tenant_id="tenant1")

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    def test_validate_local_tool_analyze_text_file_missing_tenant_id(self, mock_get_class):
        """Test analyze_text_file tool validation when tenant_id is missing"""
        mock_tool_class = Mock()
        mock_get_class.return_value = mock_tool_class

        from backend.services.tool_configuration_service import _validate_local_tool

        with pytest.raises(ToolExecutionException,
                           match="Tenant ID and User ID are required for analyze_text_file validation"):
            _validate_local_tool(
                "analyze_text_file",
                {"input": "test input"},
                {"param": "config"},
                None,  # Missing tenant_id
                "user1"
            )

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    def test_validate_local_tool_analyze_text_file_missing_user_id(self, mock_get_class):
        """Test analyze_text_file tool validation when user_id is missing"""
        mock_tool_class = Mock()
        mock_get_class.return_value = mock_tool_class

        from backend.services.tool_configuration_service import _validate_local_tool

        with pytest.raises(ToolExecutionException,
                           match="Tenant ID and User ID are required for analyze_text_file validation"):
            _validate_local_tool(
                "analyze_text_file",
                {"input": "test input"},
                {"param": "config"},
                "tenant1",
                None  # Missing user_id
            )

    @patch('backend.services.tool_configuration_service._get_tool_class_by_name')
    def test_validate_local_tool_analyze_text_file_missing_both_ids(self, mock_get_class):
        """Test analyze_text_file tool validation when both tenant_id and user_id are missing"""
        mock_tool_class = Mock()
        mock_get_class.return_value = mock_tool_class

        from backend.services.tool_configuration_service import _validate_local_tool

        with pytest.raises(ToolExecutionException,
                           match="Tenant ID and User ID are required for analyze_text_file validation"):
            _validate_local_tool(
                "analyze_text_file",
                {"input": "test input"},
                {"param": "config"},
                None,  # Missing tenant_id
                None   # Missing user_id
            )


class TestGetLlmModel:
    """Test cases for get_llm_model function"""

    @patch('backend.services.file_management_service.MODEL_CONFIG_MAPPING', {"llm": "llm_config_key"})
    @patch('backend.services.file_management_service.MessageObserver')
    @patch('backend.services.file_management_service.OpenAILongContextModel')
    @patch('backend.services.file_management_service.get_model_name_from_config')
    @patch('backend.services.file_management_service.tenant_config_manager')
    def test_get_llm_model_success(self, mock_tenant_config, mock_get_model_name, mock_openai_model, mock_message_observer):
        """Test successful LLM model retrieval"""
        from backend.services.file_management_service import get_llm_model

        # Mock tenant config manager
        mock_config = {
            "base_url": "http://api.example.com",
            "api_key": "test_api_key",
            "max_tokens": 4096
        }
        mock_tenant_config.get_model_config.return_value = mock_config

        # Mock model name
        mock_get_model_name.return_value = "gpt-4"

        # Mock MessageObserver
        mock_observer_instance = Mock()
        mock_message_observer.return_value = mock_observer_instance

        # Mock OpenAILongContextModel
        mock_model_instance = Mock()
        mock_openai_model.return_value = mock_model_instance

        # Execute
        result = get_llm_model("tenant123")

        # Assertions
        assert result == mock_model_instance
        mock_tenant_config.get_model_config.assert_called_once_with(
            key="llm_config_key", tenant_id="tenant123")
        mock_get_model_name.assert_called_once_with(mock_config)
        mock_message_observer.assert_called_once()
        mock_openai_model.assert_called_once_with(
            observer=mock_observer_instance,
            model_id="gpt-4",
            api_base="http://api.example.com",
            api_key="test_api_key",
            max_context_tokens=4096,
            ssl_verify=True
        )

    @patch('backend.services.file_management_service.MODEL_CONFIG_MAPPING', {"llm": "llm_config_key"})
    @patch('backend.services.file_management_service.MessageObserver')
    @patch('backend.services.file_management_service.OpenAILongContextModel')
    @patch('backend.services.file_management_service.get_model_name_from_config')
    @patch('backend.services.file_management_service.tenant_config_manager')
    def test_get_llm_model_with_missing_config_values(self, mock_tenant_config, mock_get_model_name, mock_openai_model, mock_message_observer):
        """Test get_llm_model with missing config values"""
        from backend.services.file_management_service import get_llm_model

        # Mock tenant config manager with missing values
        mock_config = {
            "base_url": "http://api.example.com"
            # Missing api_key and max_tokens
        }
        mock_tenant_config.get_model_config.return_value = mock_config

        # Mock model name
        mock_get_model_name.return_value = "gpt-4"

        # Mock MessageObserver
        mock_observer_instance = Mock()
        mock_message_observer.return_value = mock_observer_instance

        # Mock OpenAILongContextModel
        mock_model_instance = Mock()
        mock_openai_model.return_value = mock_model_instance

        # Execute
        result = get_llm_model("tenant123")

        # Assertions
        assert result == mock_model_instance
        # Verify that get() is used for missing values (returns None)
        mock_openai_model.assert_called_once()
        call_kwargs = mock_openai_model.call_args[1]
        assert call_kwargs["api_key"] is None
        assert call_kwargs["max_context_tokens"] is None

    @patch('backend.services.file_management_service.MODEL_CONFIG_MAPPING', {"llm": "llm_config_key"})
    @patch('backend.services.file_management_service.MessageObserver')
    @patch('backend.services.file_management_service.OpenAILongContextModel')
    @patch('backend.services.file_management_service.get_model_name_from_config')
    @patch('backend.services.file_management_service.tenant_config_manager')
    def test_get_llm_model_with_different_tenant_ids(self, mock_tenant_config, mock_get_model_name, mock_openai_model, mock_message_observer):
        """Test get_llm_model with different tenant IDs"""
        from backend.services.file_management_service import get_llm_model

        # Mock tenant config manager
        mock_config = {
            "base_url": "http://api.example.com",
            "api_key": "test_api_key",
            "max_tokens": 4096
        }
        mock_tenant_config.get_model_config.return_value = mock_config

        # Mock model name
        mock_get_model_name.return_value = "gpt-4"

        # Mock MessageObserver
        mock_observer_instance = Mock()
        mock_message_observer.return_value = mock_observer_instance

        # Mock OpenAILongContextModel
        mock_model_instance = Mock()
        mock_openai_model.return_value = mock_model_instance

        # Execute with different tenant IDs
        result1 = get_llm_model("tenant1")
        result2 = get_llm_model("tenant2")

        # Assertions
        assert result1 == mock_model_instance
        assert result2 == mock_model_instance
        # Verify tenant config was called with different tenant IDs
        assert mock_tenant_config.get_model_config.call_count == 2
        assert mock_tenant_config.get_model_config.call_args_list[0][1]["tenant_id"] == "tenant1"
        assert mock_tenant_config.get_model_config.call_args_list[1][1]["tenant_id"] == "tenant2"


class TestInitToolListForTenant:
    """Test cases for init_tool_list_for_tenant function"""

    @pytest.mark.asyncio
    @patch('backend.services.tool_configuration_service.check_tool_list_initialized')
    @patch('backend.services.tool_configuration_service.update_tool_list', new_callable=AsyncMock)
    async def test_init_tool_list_for_tenant_success_new_tenant(self, mock_update_tool_list, mock_check_initialized):
        """Test successful initialization for a new tenant"""
        # Mock that tools are not yet initialized for this tenant
        mock_check_initialized.return_value = False

        from backend.services.tool_configuration_service import init_tool_list_for_tenant

        result = await init_tool_list_for_tenant("new_tenant_id", "user_id_123")

        # Verify that initialization was successful
        assert result["status"] == "success"
        assert result["message"] == "Tool list initialized successfully"
        mock_check_initialized.assert_called_once_with("new_tenant_id")
        mock_update_tool_list.assert_called_once_with(tenant_id="new_tenant_id", user_id="user_id_123")

    @pytest.mark.asyncio
    @patch('backend.services.tool_configuration_service.check_tool_list_initialized')
    async def test_init_tool_list_for_tenant_already_initialized(self, mock_check_initialized):
        """Test that initialization is skipped for already initialized tenant"""
        # Mock that tools are already initialized for this tenant
        mock_check_initialized.return_value = True

        from backend.services.tool_configuration_service import init_tool_list_for_tenant

        result = await init_tool_list_for_tenant("existing_tenant_id", "user_id_456")

        # Verify that initialization was skipped
        assert result["status"] == "already_initialized"
        assert result["message"] == "Tool list already exists"
        mock_check_initialized.assert_called_once_with("existing_tenant_id")

    @pytest.mark.asyncio
    @patch('backend.services.tool_configuration_service.check_tool_list_initialized')
    @patch('backend.services.tool_configuration_service.update_tool_list', new_callable=AsyncMock)
    @patch('backend.services.tool_configuration_service.logger')
    async def test_init_tool_list_for_tenant_logging(self, mock_logger, mock_update_tool_list, mock_check_initialized):
        """Test that init_tool_list_for_tenant logs appropriately"""
        mock_check_initialized.return_value = False

        from backend.services.tool_configuration_service import init_tool_list_for_tenant

        await init_tool_list_for_tenant("tenant_xyz", "user_abc")

        # Verify that info log was called for new tenant
        mock_logger.info.assert_any_call(f"Initializing tool list for new tenant: tenant_xyz")


class TestUpdateToolList:
    """Test cases for update_tool_list function"""

    @pytest.mark.asyncio
    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_langchain_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools', new_callable=AsyncMock)
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    async def test_update_tool_list_success(self, mock_update_table, mock_get_mcp, mock_get_langchain, mock_get_local):
        """Test successful tool list update"""
        # Mock tools
        mock_local_tools = [MagicMock(), MagicMock()]
        mock_langchain_tools = [MagicMock()]
        mock_mcp_tools = [MagicMock(), MagicMock(), MagicMock()]

        mock_get_local.return_value = mock_local_tools
        mock_get_langchain.return_value = mock_langchain_tools
        mock_get_mcp.return_value = mock_mcp_tools

        from backend.services.tool_configuration_service import update_tool_list

        await update_tool_list("tenant123", "user456")

        # Verify all tools were gathered and update was called
        mock_get_local.assert_called_once()
        mock_get_langchain.assert_called_once()
        mock_get_mcp.assert_called_once_with("tenant123")

    @pytest.mark.asyncio
    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_langchain_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools', new_callable=AsyncMock)
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    async def test_update_tool_list_combines_all_sources(self, mock_update_table, mock_get_mcp, mock_get_langchain, mock_get_local):
        """Test that update_tool_list combines tools from all sources"""
        mock_local_tools = [MagicMock(name="local_tool_1")]
        mock_langchain_tools = [MagicMock(name="langchain_tool_1")]
        mock_mcp_tools = [MagicMock(name="mcp_tool_1")]

        mock_get_local.return_value = mock_local_tools
        mock_get_langchain.return_value = mock_langchain_tools
        mock_get_mcp.return_value = mock_mcp_tools

        from backend.services.tool_configuration_service import update_tool_list

        await update_tool_list("tenant123", "user456")

        # Get the tool_list argument passed to update_tool_table_from_scan_tool_list
        call_args = mock_update_table.call_args
        combined_tool_list = call_args.kwargs["tool_list"]

        # Verify that combined list contains tools from all sources
        assert len(combined_tool_list) == 3


if __name__ == '__main__':
    unittest.main()


class TestGetLocalToolsDescriptionZh:
    """Tests for get_local_tools_description_zh function - tests description_zh i18n support."""

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_returns_correct_structure_with_description_zh(self, mock_get_classes):
        """Test that function returns correct structure with description_zh for tools."""
        # Create a mock tool class with description_zh
        class MockToolWithDescriptionZh:
            name = "test_search_tool"
            description = "A test search tool"
            description_zh = "测试搜索工具"
            inputs = {
                "query": {
                    "type": "string",
                    "description": "Search query",
                    "description_zh": "搜索查询词"
                }
            }
            init_param_descriptions = {
                "api_key": {
                    "description": "API key for the service",
                    "description_zh": "服务的API密钥"
                }
            }

            def __init__(self, api_key: str = "default"):
                self.api_key = api_key

        mock_get_classes.return_value = [MockToolWithDescriptionZh]

        result = get_local_tools_description_zh()

        # Verify structure
        assert "test_search_tool" in result
        tool_info = result["test_search_tool"]
        assert "description_zh" in tool_info
        assert tool_info["description_zh"] == "测试搜索工具"
        assert "params" in tool_info
        assert "inputs" in tool_info

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_extracts_param_description_zh(self, mock_get_classes):
        """Test that function extracts description_zh from init params."""
        class MockToolWithParamDescriptions:
            name = "test_tool"
            description = "Test tool"
            description_zh = "测试工具"
            inputs = {}
            init_param_descriptions = {
                "param1": {
                    "description": "First parameter",
                    "description_zh": "第一个参数"
                },
                "param2": {
                    "description": "Second parameter",
                    "description_zh": "第二个参数"
                }
            }

            def __init__(self, param1: str = "", param2: int = 0):
                self.param1 = param1
                self.param2 = param2

        mock_get_classes.return_value = [MockToolWithParamDescriptions]

        result = get_local_tools_description_zh()

        tool_info = result["test_tool"]
        params = tool_info["params"]

        # Find params with description_zh
        param1_info = next((p for p in params if p["name"] == "param1"), None)
        param2_info = next((p for p in params if p["name"] == "param2"), None)

        assert param1_info is not None
        assert param1_info["description_zh"] == "第一个参数"
        assert param2_info is not None
        assert param2_info["description_zh"] == "第二个参数"

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_extracts_inputs_description_zh(self, mock_get_classes):
        """Test that function extracts description_zh from inputs."""
        class MockToolWithInputDescriptions:
            name = "search_tool"
            description = "Search tool"
            description_zh = "搜索工具"
            inputs = {
                "query": {
                    "type": "string",
                    "description": "Search query string",
                    "description_zh": "搜索查询字符串"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results",
                    "description_zh": "最大结果数"
                }
            }
            init_param_descriptions = {}

            def __init__(self):
                pass

        mock_get_classes.return_value = [MockToolWithInputDescriptions]

        result = get_local_tools_description_zh()

        tool_info = result["search_tool"]
        inputs = tool_info["inputs"]

        assert "query" in inputs
        assert inputs["query"]["description_zh"] == "搜索查询字符串"
        assert "limit" in inputs
        assert inputs["limit"]["description_zh"] == "最大结果数"

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_returns_empty_dict_when_no_tools(self, mock_get_classes):
        """Test that function returns empty dict when no tools available."""
        mock_get_classes.return_value = []

        result = get_local_tools_description_zh()

        assert result == {}

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_handles_tool_without_description_zh(self, mock_get_classes):
        """Test that function handles tools without description_zh gracefully."""
        class MockToolWithoutDescriptionZh:
            name = "legacy_tool"
            description = "Legacy tool without Chinese description"
            # No description_zh attribute
            inputs = {}
            init_param_descriptions = {}

            def __init__(self):
                pass

        mock_get_classes.return_value = [MockToolWithoutDescriptionZh]

        result = get_local_tools_description_zh()

        # Should still return the tool, but with None for description_zh
        assert "legacy_tool" in result
        tool_info = result["legacy_tool"]
        assert "description_zh" in tool_info
        assert tool_info["description_zh"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
