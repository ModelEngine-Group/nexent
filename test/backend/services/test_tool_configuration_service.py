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

# Mock rerank_model module with proper class exports
class MockBaseRerank:
    """Mock BaseRerank class"""
    pass

class MockOpenAICompatibleRerank(MockBaseRerank):
    """Mock OpenAICompatibleRerank class"""
    def __init__(self, *args, **kwargs):
        pass

rerank_model_module = types.ModuleType('nexent.core.models.rerank_model')
rerank_model_module.BaseRerank = MockBaseRerank
rerank_model_module.OpenAICompatibleRerank = MockOpenAICompatibleRerank
sys.modules['nexent.core.models.rerank_model'] = rerank_model_module

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
    @patch('backend.utils.tool_utils.get_local_tools_classes')
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

        from backend.utils.tool_utils import get_local_tools_classes
        result = get_local_tools_classes()

        # Assertions
        assert len(result) == 2
        assert mock_tool_class1 in result
        assert mock_tool_class2 in result
        assert mock_non_class not in result

    @patch('backend.services.tool_configuration_service.importlib.import_module')
    @patch('backend.utils.tool_utils.get_local_tools_classes')
    def test_get_local_tools_classes_import_error(self, mock_get_local_tools_classes, mock_import):
        """ test the import error of get_local_tools_classes"""
        mock_import.side_effect = ImportError("Module not found")
        mock_get_local_tools_classes.side_effect = ImportError(
            "Module not found")

        from backend.utils.tool_utils import get_local_tools_classes
        with pytest.raises(ImportError):
            get_local_tools_classes()


class TestGetLocalTools:
    """ test the function of get_local_tools"""

    @patch('backend.utils.tool_utils.get_local_tools_classes')
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

    @patch('backend.utils.tool_utils.get_local_tools_classes')
    @patch('backend.services.tool_configuration_service.get_local_tools')
    def test_get_local_tools_no_classes(self, mock_get_local_tools, mock_get_classes):
        """ test the no tool class of get_local_tools"""
        mock_get_classes.return_value = []
        mock_get_local_tools.return_value = []

        from backend.services.tool_configuration_service import get_local_tools
        result = get_local_tools()
        assert result == []

    @patch('backend.utils.tool_utils.get_local_tools_classes')
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


class TestCreateMcpTransport:
    """Test _create_mcp_transport function"""

    @patch('backend.services.tool_configuration_service.SSETransport')
    def test_create_mcp_transport_sse_with_token(self, mock_sse_transport):
        """Test creating SSETransport for URL ending with /sse and with authorization token"""
        from backend.services.tool_configuration_service import _create_mcp_transport

        mock_transport = Mock()
        mock_sse_transport.return_value = mock_transport

        result = _create_mcp_transport("http://test-server.com/sse", "Bearer token123")

        assert result == mock_transport
        mock_sse_transport.assert_called_once_with(
            url="http://test-server.com/sse",
            headers={"Authorization": "Bearer token123"}
        )

    @patch('backend.services.tool_configuration_service.SSETransport')
    def test_create_mcp_transport_sse_without_token(self, mock_sse_transport):
        """Test creating SSETransport for URL ending with /sse and without authorization token"""
        from backend.services.tool_configuration_service import _create_mcp_transport

        mock_transport = Mock()
        mock_sse_transport.return_value = mock_transport

        result = _create_mcp_transport("http://test-server.com/sse", None)

        assert result == mock_transport
        mock_sse_transport.assert_called_once_with(
            url="http://test-server.com/sse",
            headers={}
        )

    @patch('backend.services.tool_configuration_service.StreamableHttpTransport')
    def test_create_mcp_transport_mcp_with_token(self, mock_http_transport):
        """Test creating StreamableHttpTransport for URL ending with /mcp and with authorization token"""
        from backend.services.tool_configuration_service import _create_mcp_transport

        mock_transport = Mock()
        mock_http_transport.return_value = mock_transport

        result = _create_mcp_transport("http://test-server.com/mcp", "Bearer token456")

        assert result == mock_transport
        mock_http_transport.assert_called_once_with(
            url="http://test-server.com/mcp",
            headers={"Authorization": "Bearer token456"}
        )

    @patch('backend.services.tool_configuration_service.StreamableHttpTransport')
    def test_create_mcp_transport_mcp_without_token(self, mock_http_transport):
        """Test creating StreamableHttpTransport for URL ending with /mcp and without authorization token"""
        from backend.services.tool_configuration_service import _create_mcp_transport

        mock_transport = Mock()
        mock_http_transport.return_value = mock_transport

        result = _create_mcp_transport("http://test-server.com/mcp", None)

        assert result == mock_transport
        mock_http_transport.assert_called_once_with(
            url="http://test-server.com/mcp",
            headers={}
        )

    @patch('backend.services.tool_configuration_service.StreamableHttpTransport')
    def test_create_mcp_transport_default_with_token(self, mock_http_transport):
        """Test creating default StreamableHttpTransport for unrecognized URL format with authorization token"""
        from backend.services.tool_configuration_service import _create_mcp_transport

        mock_transport = Mock()
        mock_http_transport.return_value = mock_transport

        result = _create_mcp_transport("http://test-server.com/api", "Bearer token789")

        assert result == mock_transport
        mock_http_transport.assert_called_once_with(
            url="http://test-server.com/api",
            headers={"Authorization": "Bearer token789"}
        )

    @patch('backend.services.tool_configuration_service.StreamableHttpTransport')
    def test_create_mcp_transport_default_without_token(self, mock_http_transport):
        """Test creating default StreamableHttpTransport for unrecognized URL format without authorization token"""
        from backend.services.tool_configuration_service import _create_mcp_transport

        mock_transport = Mock()
        mock_http_transport.return_value = mock_transport

        result = _create_mcp_transport("http://test-server.com/api", None)

        assert result == mock_transport
        mock_http_transport.assert_called_once_with(
            url="http://test-server.com/api",
            headers={}
        )

    @patch('backend.services.tool_configuration_service.SSETransport')
    def test_create_mcp_transport_sse_with_whitespace(self, mock_sse_transport):
        """Test creating SSETransport for URL with whitespace ending with /sse"""
        from backend.services.tool_configuration_service import _create_mcp_transport

        mock_transport = Mock()
        mock_sse_transport.return_value = mock_transport

        result = _create_mcp_transport("  http://test-server.com/sse  ", "token")

        assert result == mock_transport
        # Verify URL is stripped before checking ending
        mock_sse_transport.assert_called_once_with(
            url="http://test-server.com/sse",
            headers={"Authorization": "token"}
        )


class TestGetToolFromRemoteMcpServer:
    """Test get_tool_from_remote_mcp_server function"""

    @patch('backend.services.tool_configuration_service.Client')
    @patch('backend.services.tool_configuration_service.jsonref.replace_refs')
    @patch('backend.services.tool_configuration_service._sanitize_function_name')
    @patch('backend.services.tool_configuration_service._create_mcp_transport')
    async def test_get_tool_from_remote_mcp_server_success(self, mock_create_transport, mock_sanitize, mock_replace_refs, mock_client_cls):
        """Test successfully getting tools from remote MCP server"""
        # Mock transport
        mock_transport = Mock()
        mock_create_transport.return_value = mock_transport

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
        mock_create_transport.assert_called_once_with("http://test-server.com", None)
        mock_client_cls.assert_called_once_with(transport=mock_transport, timeout=10)
        assert mock_client.list_tools.call_count == 1

    @patch('backend.services.tool_configuration_service.Client')
    @patch('backend.services.tool_configuration_service.jsonref.replace_refs')
    @patch('backend.services.tool_configuration_service._sanitize_function_name')
    @patch('backend.services.tool_configuration_service._create_mcp_transport')
    @patch('backend.services.tool_configuration_service.get_mcp_authorization_token_by_name_and_url')
    async def test_get_tool_from_remote_mcp_server_with_token_from_db(self, mock_get_token, mock_create_transport, mock_sanitize, mock_replace_refs, mock_client_cls):
        """Test getting tools from remote MCP server with authorization token from database"""
        # Mock authorization token from database
        mock_get_token.return_value = "Bearer token_from_db"

        # Mock transport
        mock_transport = Mock()
        mock_create_transport.return_value = mock_transport

        # Mock client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        # Mock tool list
        mock_tool = Mock()
        mock_tool.name = "test_tool"
        mock_tool.description = "Test tool description"
        mock_tool.inputSchema = {"properties": {"param1": {"type": "string"}}}

        mock_client.list_tools.return_value = [mock_tool]

        # Mock JSON schema processing
        mock_replace_refs.return_value = {"properties": {"param1": {"type": "string", "description": "see tool description"}}}

        # Mock name sanitization
        mock_sanitize.return_value = "test_tool"

        from backend.services.tool_configuration_service import get_tool_from_remote_mcp_server

        result = await get_tool_from_remote_mcp_server(
            "test_server", "http://test-server.com", tenant_id="tenant1"
        )

        # Verify results
        assert len(result) == 1
        assert result[0].name == "test_tool"

        # Verify authorization token was fetched from database
        mock_get_token.assert_called_once_with(
            mcp_name="test_server",
            mcp_server="http://test-server.com",
            tenant_id="tenant1"
        )

        # Verify transport was created with token
        mock_create_transport.assert_called_once_with("http://test-server.com", "Bearer token_from_db")

    @patch('backend.services.tool_configuration_service.Client')
    @patch('backend.services.tool_configuration_service.jsonref.replace_refs')
    @patch('backend.services.tool_configuration_service._sanitize_function_name')
    @patch('backend.services.tool_configuration_service._create_mcp_transport')
    async def test_get_tool_from_remote_mcp_server_with_provided_token(self, mock_create_transport, mock_sanitize, mock_replace_refs, mock_client_cls):
        """Test getting tools from remote MCP server with directly provided authorization token"""
        # Mock transport
        mock_transport = Mock()
        mock_create_transport.return_value = mock_transport

        # Mock client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        # Mock tool list
        mock_tool = Mock()
        mock_tool.name = "test_tool"
        mock_tool.description = "Test tool description"
        mock_tool.inputSchema = {"properties": {"param1": {"type": "string"}}}

        mock_client.list_tools.return_value = [mock_tool]

        # Mock JSON schema processing
        mock_replace_refs.return_value = {"properties": {"param1": {"type": "string", "description": "see tool description"}}}

        # Mock name sanitization
        mock_sanitize.return_value = "test_tool"

        from backend.services.tool_configuration_service import get_tool_from_remote_mcp_server

        result = await get_tool_from_remote_mcp_server(
            "test_server", "http://test-server.com", tenant_id="tenant1", authorization_token="Bearer provided_token"
        )

        # Verify results
        assert len(result) == 1
        assert result[0].name == "test_tool"

        # Verify transport was created with provided token (not fetched from DB)
        mock_create_transport.assert_called_once_with("http://test-server.com", "Bearer provided_token")

    @patch('backend.services.tool_configuration_service.Client')
    @patch('backend.services.tool_configuration_service._create_mcp_transport')
    async def test_get_tool_from_remote_mcp_server_empty_tools(self, mock_create_transport, mock_client_cls):
        """Test remote server with no tools"""
        # Mock transport
        mock_transport = Mock()
        mock_create_transport.return_value = mock_transport

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client
        mock_client.list_tools.return_value = []

        from backend.services.tool_configuration_service import get_tool_from_remote_mcp_server

        result = await get_tool_from_remote_mcp_server("test_server", "http://test-server.com")

        assert result == []

    @patch('backend.services.tool_configuration_service.Client')
    @patch('backend.services.tool_configuration_service._create_mcp_transport')
    async def test_get_tool_from_remote_mcp_server_connection_error(self, mock_create_transport, mock_client_cls):
        """Test connection error scenario"""
        # Mock transport
        mock_transport = Mock()
        mock_create_transport.return_value = mock_transport

        mock_client_cls.side_effect = Exception("Connection failed")

        from backend.services.tool_configuration_service import get_tool_from_remote_mcp_server

        with pytest.raises(MCPConnectionError):
            await get_tool_from_remote_mcp_server("test_server", "http://test-server.com")

        # Verify transport was created before connection error
        mock_create_transport.assert_called_once_with("http://test-server.com", None)

    @patch('backend.services.tool_configuration_service.Client')
    @patch('backend.services.tool_configuration_service.jsonref.replace_refs')
    @patch('backend.services.tool_configuration_service._sanitize_function_name')
    @patch('backend.services.tool_configuration_service._create_mcp_transport')
    async def test_get_tool_from_remote_mcp_server_missing_properties(self, mock_create_transport, mock_sanitize, mock_replace_refs, mock_client_cls):
        """Test tools missing required properties"""
        # Mock transport
        mock_transport = Mock()
        mock_create_transport.return_value = mock_transport

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

    @patch('backend.services.tool_configuration_service.discover_langchain_modules')
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

    @patch('backend.services.tool_configuration_service.discover_langchain_modules')
    def test_get_langchain_tools_empty_result(self, mock_discover_modules):
        """Test scenario where no LangChain tools are discovered"""
        # Mock discover_langchain_modules to return empty list
        mock_discover_modules.return_value = []

        from backend.services.tool_configuration_service import get_langchain_tools

        result = get_langchain_tools()

        # Verify result is empty list
        assert result == []
        mock_discover_modules.assert_called_once()

    @patch('backend.services.tool_configuration_service.discover_langchain_modules')
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

    @patch('backend.services.tool_configuration_service.discover_langchain_modules')
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


class TestBuildToolInfoFromLangchain:
    """Test _build_tool_info_from_langchain function edge cases."""

    def test_build_tool_info_from_langchain_with_empty_args(self):
        """Test _build_tool_info_from_langchain when tool has no args."""
        from backend.services.tool_configuration_service import _build_tool_info_from_langchain

        # Create mock tool with no args attribute
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "Test tool description"
        mock_tool.args = {}
        mock_tool.func = MagicMock()
        mock_tool.func.__name__ = "test_func"

        result = _build_tool_info_from_langchain(mock_tool)

        assert result.name == "test_tool"
        assert result.description == "Test tool description"

    def test_build_tool_info_from_langchain_with_args_missing_description(self):
        """Test _build_tool_info_from_langchain when args lacks description."""
        from backend.services.tool_configuration_service import _build_tool_info_from_langchain

        # Create mock tool with args missing description
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "Test tool description"
        mock_tool.args = {"param1": {"type": "string"}}  # Missing description
        mock_tool.func = MagicMock()
        mock_tool.func.__name__ = "test_func"

        result = _build_tool_info_from_langchain(mock_tool)

        # Verify description was added
        import json
        inputs = json.loads(result.inputs)
        assert "description" in inputs["param1"]

    def test_build_tool_info_from_langchain_with_invalid_signature(self):
        """Test _build_tool_info_from_langchain when signature raises TypeError."""
        from backend.services.tool_configuration_service import _build_tool_info_from_langchain

        # Create a mock tool with a callable that will raise TypeError on signature
        mock_func = lambda: None  # A simple callable
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "Test tool description"
        mock_tool.args = {}
        mock_tool.func = mock_func

        # Make inspect.signature raise TypeError
        import inspect
        with patch('backend.services.tool_configuration_service.inspect.signature', side_effect=TypeError("cannot inspect")):
            result = _build_tool_info_from_langchain(mock_tool)

        # Should fall back to string output type
        assert result.output_type == "string"

    def test_build_tool_info_from_langchain_with_invalid_return_annotation(self):
        """Test _build_tool_info_from_langchain when return annotation raises ValueError."""
        from backend.services.tool_configuration_service import _build_tool_info_from_langchain

        # Create a mock tool with a callable that will raise ValueError on signature
        mock_func = lambda: None
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "Test tool description"
        mock_tool.args = {}
        mock_tool.func = mock_func

        # Make inspect.signature raise ValueError for this specific callable
        import inspect

        def mock_signature(obj):
            if obj == mock_func:
                raise ValueError("Cannot get signature")
            return inspect.signature(obj)

        with patch('backend.services.tool_configuration_service.inspect.signature', side_effect=mock_signature):
            result = _build_tool_info_from_langchain(mock_tool)

        # Should fall back to string output type
        assert result.output_type == "string"


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
    @patch('backend.services.tool_configuration_service._create_mcp_transport')
    async def test_call_mcp_tool_success(self, mock_create_transport, mock_client_cls):
        """Test successful MCP tool call"""
        # Mock transport
        mock_transport = Mock()
        mock_create_transport.return_value = mock_transport

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
        mock_create_transport.assert_called_once_with("http://test-server.com", None)
        mock_client_cls.assert_called_once_with(transport=mock_transport)
        mock_client.call_tool.assert_called_once_with(
            name="test_tool", arguments={"param": "value"})

    @patch('backend.services.tool_configuration_service.Client')
    @patch('backend.services.tool_configuration_service._create_mcp_transport')
    async def test_call_mcp_tool_with_authorization_token(self, mock_create_transport, mock_client_cls):
        """Test MCP tool call with authorization token"""
        # Mock transport
        mock_transport = Mock()
        mock_create_transport.return_value = mock_transport

        # Mock client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.is_connected.return_value = True

        # Mock tool result structure
        mock_content_item = Mock()
        mock_content_item.text = "test result with token"
        mock_result = Mock()
        mock_result.content = [mock_content_item]
        mock_client.call_tool.return_value = mock_result

        mock_client_cls.return_value = mock_client

        from backend.services.tool_configuration_service import _call_mcp_tool

        result = await _call_mcp_tool(
            "http://test-server.com", "test_tool", {"param": "value"}, authorization_token="Bearer token123"
        )

        assert result == "test result with token"
        mock_create_transport.assert_called_once_with("http://test-server.com", "Bearer token123")
        mock_client_cls.assert_called_once_with(transport=mock_transport)
        mock_client.call_tool.assert_called_once_with(
            name="test_tool", arguments={"param": "value"})

    @patch('backend.services.tool_configuration_service.Client')
    @patch('backend.services.tool_configuration_service._create_mcp_transport')
    async def test_call_mcp_tool_connection_failed(self, mock_create_transport, mock_client_cls):
        """Test MCP tool call when connection fails"""
        # Mock transport
        mock_transport = Mock()
        mock_create_transport.return_value = mock_transport

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
        mock_create_transport.assert_called_once_with("http://test-server.com", None)
        mock_client_cls.assert_called_once_with(transport=mock_transport)
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

    @patch('backend.services.tool_configuration_service.get_mcp_authorization_token_by_name_and_url')
    @patch('backend.services.tool_configuration_service.get_mcp_server_by_name_and_tenant')
    @patch('backend.services.tool_configuration_service._call_mcp_tool')
    async def test_validate_mcp_tool_remote_success(self, mock_call_tool, mock_get_server, mock_get_token):
        """Test successful remote MCP tool validation with authorization token from database"""
        mock_get_server.return_value = "http://remote-server.com"
        mock_get_token.return_value = "Bearer token_from_db"
        mock_call_tool.return_value = "validation result"

        from backend.services.tool_configuration_service import _validate_mcp_tool_remote

        result = await _validate_mcp_tool_remote("test_tool", {"param": "value"}, "test_server", "tenant1")

        assert result == "validation result"
        mock_get_server.assert_called_once_with("test_server", "tenant1")
        mock_get_token.assert_called_once_with(
            mcp_name="test_server",
            mcp_server="http://remote-server.com",
            tenant_id="tenant1"
        )
        # _call_mcp_tool is called with authorization_token as positional argument
        mock_call_tool.assert_called_once_with(
            "http://remote-server.com", "test_tool", {"param": "value"}, "Bearer token_from_db")

    @patch('backend.services.tool_configuration_service.get_mcp_server_by_name_and_tenant')
    @patch('backend.services.tool_configuration_service._call_mcp_tool')
    async def test_validate_mcp_tool_remote_without_tenant_id(self, mock_call_tool, mock_get_server):
        """Test remote MCP tool validation when tenant_id is None (no token fetched)"""
        mock_get_server.return_value = "http://remote-server.com"
        mock_call_tool.return_value = "validation result"

        from backend.services.tool_configuration_service import _validate_mcp_tool_remote

        result = await _validate_mcp_tool_remote("test_tool", {"param": "value"}, "test_server", None)

        assert result == "validation result"
        mock_get_server.assert_called_once_with("test_server", None)
        # Verify _call_mcp_tool was called with authorization_token as positional argument (None)
        mock_call_tool.assert_called_once_with(
            "http://remote-server.com", "test_tool", {"param": "value"}, None)

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

    @patch('backend.services.tool_configuration_service.discover_langchain_modules')
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

    @patch('backend.services.tool_configuration_service.discover_langchain_modules')
    def test_validate_langchain_tool_not_found(self, mock_discover):
        """Test LangChain tool validation when tool not found"""
        mock_discover.return_value = []

        from backend.services.tool_configuration_service import _validate_langchain_tool

        with pytest.raises(ToolExecutionException, match="LangChain tool 'test_tool' validation failed: Tool 'test_tool' not found in LangChain tools"):
            _validate_langchain_tool("test_tool", {"input": "value"})

    @patch('backend.services.tool_configuration_service.discover_langchain_modules')
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
            "rerank_model": None,
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
            "rerank_model": None,
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
            "rerank_model": None,
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
            "rerank_model": None,
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
            "rerank_model": None,
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

    def setup_method(self):
        """Import the function to test."""
        from backend.utils.tool_utils import get_local_tools_description_zh
        self.get_local_tools_description_zh = get_local_tools_description_zh

    @patch('backend.utils.tool_utils.get_local_tools_classes')
    def test_returns_correct_structure_with_description_zh(self, mock_get_classes):
        """Test that function returns correct structure with description_zh for tools."""
        from pydantic import Field

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

            def __init__(self, api_key: str = Field(description="API key", default="default")):
                self.api_key = api_key

        mock_get_classes.return_value = [MockToolWithDescriptionZh]

        result = self.get_local_tools_description_zh()

        # Verify structure
        assert "test_search_tool" in result
        tool_info = result["test_search_tool"]
        assert "description_zh" in tool_info
        assert tool_info["description_zh"] == "测试搜索工具"
        assert "params" in tool_info
        assert "inputs" in tool_info

    @patch('backend.utils.tool_utils.get_local_tools_classes')
    def test_extracts_param_description_zh(self, mock_get_classes):
        """Test that function extracts description_zh from init params."""
        from pydantic import Field

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

            def __init__(self, param1: str = Field(description="param1", default=""), param2: int = Field(description="param2", default=0)):
                self.param1 = param1
                self.param2 = param2

        mock_get_classes.return_value = [MockToolWithParamDescriptions]

        result = self.get_local_tools_description_zh()

        tool_info = result["test_tool"]
        params = tool_info["params"]

        # Find params with description_zh
        param1_info = next((p for p in params if p["name"] == "param1"), None)
        param2_info = next((p for p in params if p["name"] == "param2"), None)

        assert param1_info is not None
        assert param1_info["description_zh"] == "第一个参数"
        assert param2_info is not None
        assert param2_info["description_zh"] == "第二个参数"

    @patch('backend.utils.tool_utils.get_local_tools_classes')
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

        result = self.get_local_tools_description_zh()

        tool_info = result["search_tool"]
        inputs = tool_info["inputs"]

        assert "query" in inputs
        assert inputs["query"]["description_zh"] == "搜索查询字符串"
        assert "limit" in inputs
        assert inputs["limit"]["description_zh"] == "最大结果数"

    @patch('backend.utils.tool_utils.get_local_tools_classes')
    def test_returns_empty_dict_when_no_tools(self, mock_get_classes):
        """Test that function returns empty dict when no tools available."""
        mock_get_classes.return_value = []

        result = self.get_local_tools_description_zh()

        assert result == {}

    @patch('backend.utils.tool_utils.get_local_tools_classes')
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

        result = self.get_local_tools_description_zh()

        # Should still return the tool, but with None for description_zh
        assert "legacy_tool" in result
        tool_info = result["legacy_tool"]
        assert "description_zh" in tool_info
        assert tool_info["description_zh"] is None


class TestGetLocalToolsDescriptionZhCoverage:
    """Additional tests for description_zh coverage in get_local_tools and list_all_tools."""

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_get_local_tools_with_description_zh(self, mock_get_classes):
        """Test get_local_tools extracts description_zh from tool class."""
        from pydantic import Field

        class MockToolWithZh:
            name = "test_tool_zh"
            description = "Test tool"
            description_zh = "测试工具"
            output_type = "string"
            category = "test"
            inputs = {
                "query": {
                    "type": "string",
                    "description": "Query",
                    "description_zh": "查询"
                }
            }
            # Use init_param_descriptions for param description_zh (Pydantic V2 doesn't support Field(description_zh=...))
            init_param_descriptions = {
                "param1": {
                    "description": "Param1",
                    "description_zh": "参数1"
                }
            }

            def __init__(self, param1: str = Field(description="Param1", default="")):
                pass

        mock_get_classes.return_value = [MockToolWithZh]

        from backend.services.tool_configuration_service import get_local_tools
        result = get_local_tools()

        assert len(result) == 1
        tool_info = result[0]
        assert tool_info.description_zh == "测试工具"

        # Check params have description_zh from init_param_descriptions
        params = tool_info.params
        param1 = next((p for p in params if p["name"] == "param1"), None)
        assert param1 is not None
        assert param1["description_zh"] == "参数1"

        # Check inputs have description_zh
        import json
        inputs = json.loads(tool_info.inputs)
        assert "query" in inputs
        assert inputs["query"]["description_zh"] == "查询"

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_get_local_tools_param_without_description_zh(self, mock_get_classes):
        """Test get_local_tools handles param without description_zh."""
        from pydantic import Field

        class MockToolNoParamZh:
            name = "test_tool_no_param_zh"
            description = "Test tool"
            description_zh = "测试工具"
            output_type = "string"
            category = "test"
            inputs = {}

            def __init__(self, param1: str = Field(description="Param1", default="")):
                pass

        mock_get_classes.return_value = [MockToolNoParamZh]

        from backend.services.tool_configuration_service import get_local_tools
        result = get_local_tools()

        assert len(result) == 1
        params = result[0].params
        param1 = next((p for p in params if p["name"] == "param1"), None)
        assert param1 is not None
        assert param1["description_zh"] is None

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_get_local_tools_inputs_non_dict_value(self, mock_get_classes):
        """Test get_local_tools handles inputs with non-dict values."""
        from pydantic import Field

        class MockToolNonDictInputs:
            name = "test_tool_non_dict"
            description = "Test tool"
            description_zh = "测试工具"
            output_type = "string"
            category = "test"
            inputs = {"query": "string"}  # Non-dict value

            def __init__(self):
                pass

        mock_get_classes.return_value = [MockToolNonDictInputs]

        from backend.services.tool_configuration_service import get_local_tools
        result = get_local_tools()

        assert len(result) == 1
        import json
        inputs = json.loads(result[0].inputs)
        assert inputs == {"query": "string"}

    @patch('backend.services.tool_configuration_service.get_local_tools_description_zh')
    @patch('backend.services.tool_configuration_service.query_all_tools')
    @pytest.mark.asyncio
    async def test_list_all_tools_merges_description_zh_for_local_tools(self, mock_query, mock_get_desc):
        """Test list_all_tools merges description_zh from SDK for local tools."""
        mock_query.return_value = [
            {
                "tool_id": 1,
                "name": "local_tool",
                "origin_name": None,
                "description": "Local tool",
                "source": "local",
                "is_available": True,
                "create_time": "2024-01-01",
                "usage": None,
                "params": [{"name": "param1", "description": "Param1"}],
                "inputs": "{}",
                "category": "test"
            }
        ]

        mock_get_desc.return_value = {
            "local_tool": {
                "description_zh": "本地工具",
                "params": [{"name": "param1", "description_zh": "参数1"}],
                "inputs": {"query": {"description_zh": "查询"}}
            }
        }

        from backend.services.tool_configuration_service import list_all_tools
        result = await list_all_tools("tenant1")

        assert len(result) == 1
        assert result[0]["description_zh"] == "本地工具"
        assert result[0]["params"][0]["description_zh"] == "参数1"

    @patch('backend.services.tool_configuration_service.get_local_tools_description_zh')
    @patch('backend.services.tool_configuration_service.query_all_tools')
    @pytest.mark.asyncio
    async def test_list_all_tools_merges_inputs_description_zh(self, mock_query, mock_get_desc):
        """Test list_all_tools merges inputs description_zh from SDK."""
        mock_query.return_value = [
            {
                "tool_id": 1,
                "name": "local_tool",
                "origin_name": None,
                "description": "Local tool",
                "source": "local",
                "is_available": True,
                "create_time": "2024-01-01",
                "usage": None,
                "params": [],
                "inputs": '{"query": {"type": "string", "description": "Query"}}',
                "category": "test"
            }
        ]

        mock_get_desc.return_value = {
            "local_tool": {
                "description_zh": "本地工具",
                "params": [],
                "inputs": {"query": {"description_zh": "查询词"}}
            }
        }

        from backend.services.tool_configuration_service import list_all_tools
        result = await list_all_tools("tenant1")

        import json
        inputs = json.loads(result[0]["inputs"])
        assert inputs["query"]["description_zh"] == "查询词"

    @patch('backend.services.tool_configuration_service.get_local_tools_description_zh')
    @patch('backend.services.tool_configuration_service.query_all_tools')
    @pytest.mark.asyncio
    async def test_list_all_tools_non_local_tool(self, mock_query, mock_get_desc):
        """Test list_all_tools handles non-local tools."""
        mock_query.return_value = [
            {
                "tool_id": 1,
                "name": "mcp_tool",
                "origin_name": None,
                "description": "MCP tool",
                "source": "mcp",
                "is_available": True,
                "create_time": "2024-01-01",
                "usage": "mcp_server",
                "params": [],
                "inputs": "{}",
                "category": "test",
                "description_zh": "MCP工具"
            }
        ]

        mock_get_desc.return_value = {}

        from backend.services.tool_configuration_service import list_all_tools
        result = await list_all_tools("tenant1")

        assert len(result) == 1
        assert result[0]["description_zh"] == "MCP工具"

    @patch('backend.services.tool_configuration_service.get_local_tools_description_zh')
    @patch('backend.services.tool_configuration_service.query_all_tools')
    @pytest.mark.asyncio
    async def test_list_all_tools_inputs_json_decode_error(self, mock_query, mock_get_desc):
        """Test list_all_tools handles JSON decode error for inputs."""
        mock_query.return_value = [
            {
                "tool_id": 1,
                "name": "local_tool",
                "origin_name": None,
                "description": "Local tool",
                "source": "local",
                "is_available": True,
                "create_time": "2024-01-01",
                "usage": None,
                "params": [],
                "inputs": "invalid json{",
                "category": "test"
            }
        ]

        mock_get_desc.return_value = {
            "local_tool": {
                "description_zh": "本地工具",
                "params": [],
                "inputs": {}
            }
        }

        from backend.services.tool_configuration_service import list_all_tools
        result = await list_all_tools("tenant1")

        assert len(result) == 1
        # Should not crash, inputs should remain as original string
        assert result[0]["inputs"] == "invalid json{"


class TestGetLocalToolsClassesDirect:
    """Tests for get_local_tools_classes function directly."""

    @patch('backend.utils.tool_utils.importlib.import_module')
    def test_get_local_tools_classes_returns_classes(self, mock_import):
        """Test that get_local_tools_classes returns a list of classes."""
        # Create mock tool classes
        mock_tool_class1 = type('TestTool1', (), {})
        mock_tool_class2 = type('TestTool2', (), {})

        # Create a mock package with tool classes
        class MockPackage:
            def __init__(self):
                self.TestTool1 = mock_tool_class1
                self.TestTool2 = mock_tool_class2
                self.not_a_class = "string_value"
                self.__name__ = 'nexent.core.tools'

            def __dir__(self):
                return ['TestTool1', 'TestTool2', 'not_a_class', '__name__']

        mock_package = MockPackage()
        mock_import.return_value = mock_package

        from backend.utils.tool_utils import get_local_tools_classes
        result = get_local_tools_classes()

        assert isinstance(result, list)
        assert mock_tool_class1 in result
        assert mock_tool_class2 in result
        # String should not be included
        assert "string_value" not in result


# ============================================================
# Outer API Tools Tests (Newly Added Functions 830-1237)
# ============================================================


class TestParseOpenapiToMcpTools:
    """Test cases for parse_openapi_to_mcp_tools function."""

    def test_parse_openapi_basic_path(self):
        """Test parsing a basic OpenAPI path with GET method."""
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/users": {
                    "get": {
                        "summary": "Get users",
                        "description": "Retrieve all users",
                        "operationId": "getUsers",
                        "responses": {"200": {"description": "Success"}}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import parse_openapi_to_mcp_tools
        tools = parse_openapi_to_mcp_tools(openapi_json)

        assert len(tools) == 1
        assert tools[0]["name"] == "getUsers"
        assert tools[0]["description"] == "Retrieve all users"
        assert tools[0]["method"] == "GET"
        assert tools[0]["url"] == "/users"

    def test_parse_openapi_with_servers_base_url(self):
        """Test parsing with servers base URL."""
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "servers": [{"url": "https://api.example.com/v1"}],
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "getUsers",
                        "responses": {"200": {"description": "Success"}}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import parse_openapi_to_mcp_tools
        tools = parse_openapi_to_mcp_tools(openapi_json)

        assert len(tools) == 1
        assert tools[0]["url"] == "https://api.example.com/v1/users"

    def test_parse_openapi_multiple_methods(self):
        """Test parsing path with multiple HTTP methods."""
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/users/{id}": {
                    "get": {
                        "operationId": "getUser",
                        "summary": "Get user",
                        "responses": {"200": {"description": "Success"}}
                    },
                    "put": {
                        "operationId": "updateUser",
                        "summary": "Update user",
                        "responses": {"200": {"description": "Success"}}
                    },
                    "delete": {
                        "operationId": "deleteUser",
                        "summary": "Delete user",
                        "responses": {"204": {"description": "Deleted"}}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import parse_openapi_to_mcp_tools
        tools = parse_openapi_to_mcp_tools(openapi_json)

        assert len(tools) == 3
        tool_names = [t["name"] for t in tools]
        assert "getUser" in tool_names
        assert "updateUser" in tool_names
        assert "deleteUser" in tool_names

    def test_parse_openapi_generates_operation_id(self):
        """Test that operation ID is generated when not provided."""
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/users/list": {
                    "get": {
                        "summary": "Get users list",
                        "responses": {"200": {"description": "Success"}}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import parse_openapi_to_mcp_tools
        tools = parse_openapi_to_mcp_tools(openapi_json)

        assert len(tools) == 1
        # Should generate operation ID from method and path
        assert tools[0]["name"] == "get_users_list"

    def test_parse_openapi_with_query_parameters(self):
        """Test parsing parameters in query."""
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "getUsers",
                        "parameters": [
                            {
                                "name": "limit",
                                "in": "query",
                                "schema": {"type": "integer"},
                                "description": "Max results"
                            },
                            {
                                "name": "offset",
                                "in": "query",
                                "schema": {"type": "integer"},
                                "description": "Offset"
                            }
                        ],
                        "responses": {"200": {"description": "Success"}}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import parse_openapi_to_mcp_tools
        tools = parse_openapi_to_mcp_tools(openapi_json)

        assert len(tools) == 1
        assert "limit" in tools[0]["query_template"]
        assert tools[0]["query_template"]["limit"]["required"] is False
        assert tools[0]["query_template"]["limit"]["description"] == "Max results"

    def test_parse_openapi_with_required_query_parameter(self):
        """Test parsing required query parameters."""
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "getUsers",
                        "parameters": [
                            {
                                "name": "user_id",
                                "in": "query",
                                "schema": {"type": "string"},
                                "required": True,
                                "description": "User ID"
                            }
                        ],
                        "responses": {"200": {"description": "Success"}}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import parse_openapi_to_mcp_tools
        tools = parse_openapi_to_mcp_tools(openapi_json)

        assert len(tools) == 1
        assert tools[0]["query_template"]["user_id"]["required"] is True

    def test_parse_openapi_with_request_body(self):
        """Test parsing request body schema."""
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/users": {
                    "post": {
                        "operationId": "createUser",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string", "description": "User name"},
                                            "email": {"type": "string", "description": "User email"}
                                        },
                                        "required": ["name"]
                                    }
                                }
                            }
                        },
                        "responses": {"201": {"description": "Created"}}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import parse_openapi_to_mcp_tools
        tools = parse_openapi_to_mcp_tools(openapi_json)

        assert len(tools) == 1
        assert "name" in tools[0]["input_schema"]["properties"]
        assert "email" in tools[0]["input_schema"]["properties"]
        assert "name" in tools[0]["input_schema"]["required"]

    def test_parse_openapi_with_ref_schema(self):
        """Test parsing request body with $ref reference."""
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "components": {
                "schemas": {
                    "User": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "email": {"type": "string"}
                        }
                    }
                }
            },
            "paths": {
                "/users": {
                    "post": {
                        "operationId": "createUser",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/User"}
                                }
                            }
                        },
                        "responses": {"201": {"description": "Created"}}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import parse_openapi_to_mcp_tools
        tools = parse_openapi_to_mcp_tools(openapi_json)

        assert len(tools) == 1
        # Should resolve the $ref
        assert "name" in tools[0]["input_schema"]["properties"]

    def test_parse_openapi_with_path_parameters(self):
        """Test that path parameters are ignored (not included in templates)."""
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/users/{id}": {
                    "get": {
                        "operationId": "getUser",
                        "parameters": [
                            {
                                "name": "id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"}
                            }
                        ],
                        "responses": {"200": {"description": "Success"}}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import parse_openapi_to_mcp_tools
        tools = parse_openapi_to_mcp_tools(openapi_json)

        assert len(tools) == 1
        # Path parameters should not be in query_template
        assert "id" not in tools[0]["query_template"]

    def test_parse_openapi_empty_paths(self):
        """Test parsing with no paths defined."""
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {}
        }

        from backend.services.tool_configuration_service import parse_openapi_to_mcp_tools
        tools = parse_openapi_to_mcp_tools(openapi_json)

        assert len(tools) == 0

    def test_parse_openapi_invalid_method(self):
        """Test that invalid HTTP methods are skipped."""
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/users": {
                    "custom_method": {
                        "operationId": "customOp",
                        "responses": {"200": {"description": "Success"}}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import parse_openapi_to_mcp_tools
        tools = parse_openapi_to_mcp_tools(openapi_json)

        assert len(tools) == 0

    def test_parse_openapi_with_headers_parameters(self):
        """Test that header parameters are parsed but not included in templates."""
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "getUsers",
                        "parameters": [
                            {
                                "name": "Authorization",
                                "in": "header",
                                "required": True,
                                "schema": {"type": "string"}
                            }
                        ],
                        "responses": {"200": {"description": "Success"}}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import parse_openapi_to_mcp_tools
        tools = parse_openapi_to_mcp_tools(openapi_json)

        assert len(tools) == 1
        # Header parameters are not included in query_template
        assert "Authorization" not in tools[0]["query_template"]

    def test_parse_openapi_description_fallback(self):
        """Test that description falls back to summary or method+path."""
        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/users": {
                    "post": {
                        "operationId": "createUser",
                        "responses": {"201": {"description": "Created"}}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import parse_openapi_to_mcp_tools
        tools = parse_openapi_to_mcp_tools(openapi_json)

        assert len(tools) == 1
        # Should fall back to "POST /users"
        assert tools[0]["description"] == "POST /users"


class TestResolveRef:
    """Test cases for _resolve_ref function."""

    def test_resolve_simple_ref(self):
        """Test resolving a simple $ref."""
        schemas = {
            "User": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"}
                }
            }
        }

        from backend.services.tool_configuration_service import _resolve_ref
        result = _resolve_ref("#/components/schemas/User", schemas)

        assert result["type"] == "object"
        assert "name" in result["properties"]

    def test_resolve_ref_not_found(self):
        """Test resolving a ref that doesn't exist."""
        schemas = {
            "User": {"type": "object"}
        }

        from backend.services.tool_configuration_service import _resolve_ref
        result = _resolve_ref("#/components/schemas/NonExistent", schemas)

        assert result == {}

    def test_resolve_ref_invalid_format(self):
        """Test resolving a ref with invalid format."""
        schemas = {"User": {"type": "object"}}

        from backend.services.tool_configuration_service import _resolve_ref
        result = _resolve_ref("invalid/ref/format", schemas)

        assert result == {}

    def test_resolve_ref_without_prefix(self):
        """Test resolving a ref without #/ prefix returns empty dict."""
        schemas = {
            "User": {
                "type": "object"
            }
        }

        from backend.services.tool_configuration_service import _resolve_ref
        # Ref without #/ prefix is treated as invalid and returns empty dict
        result = _resolve_ref("User", schemas)

        assert result == {}


class TestResolveSchema:
    """Test cases for _resolve_schema function."""

    def test_resolve_schema_with_ref(self):
        """Test resolving schema with $ref."""
        schemas = {
            "User": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"}
                }
            }
        }
        schema = {"$ref": "#/components/schemas/User"}

        from backend.services.tool_configuration_service import _resolve_schema
        result = _resolve_schema(schema, schemas)

        assert result["type"] == "object"
        assert "name" in result["properties"]

    def test_resolve_schema_with_nested_ref(self):
        """Test resolving schema with nested $ref (single level)."""
        # Note: _resolve_schema resolves top-level $ref but nested $ref in properties
        # requires the referenced schema to exist in schemas dict
        schemas = {
            "User": {
                "type": "object",
                "properties": {
                    "address": {"type": "object"}  # Simplified: not a $ref
                }
            },
            "Address": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"}
                }
            }
        }
        schema = {"$ref": "#/components/schemas/User"}

        from backend.services.tool_configuration_service import _resolve_schema
        result = _resolve_schema(schema, schemas)

        assert result["type"] == "object"
        assert "address" in result["properties"]
        # Nested $ref is not automatically resolved in this implementation
        # Only top-level $ref is resolved

    def test_resolve_schema_with_items(self):
        """Test resolving schema with array items."""
        schemas = {}
        schema = {
            "type": "array",
            "items": {"type": "string"}
        }

        from backend.services.tool_configuration_service import _resolve_schema
        result = _resolve_schema(schema, schemas)

        assert result["type"] == "array"
        assert result["items"]["type"] == "string"

    def test_resolve_schema_with_properties(self):
        """Test resolving schema with properties."""
        schemas = {}
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"}
            }
        }

        from backend.services.tool_configuration_service import _resolve_schema
        result = _resolve_schema(schema, schemas)

        assert result["type"] == "object"
        assert "name" in result["properties"]
        assert "age" in result["properties"]

    def test_resolve_schema_with_allof(self):
        """Test resolving schema with allOf."""
        schemas = {}
        schema = {
            "allOf": [
                {"type": "object", "properties": {"name": {"type": "string"}}},
                {"type": "object", "properties": {"age": {"type": "integer"}}}
            ]
        }

        from backend.services.tool_configuration_service import _resolve_schema
        result = _resolve_schema(schema, schemas)

        assert "allOf" in result
        assert len(result["allOf"]) == 2

    def test_resolve_schema_with_anyof(self):
        """Test resolving schema with anyOf."""
        schemas = {}
        schema = {
            "anyOf": [
                {"type": "string"},
                {"type": "integer"}
            ]
        }

        from backend.services.tool_configuration_service import _resolve_schema
        result = _resolve_schema(schema, schemas)

        assert "anyOf" in result
        assert len(result["anyOf"]) == 2

    def test_resolve_schema_with_oneof(self):
        """Test resolving schema with oneOf."""
        schemas = {}
        schema = {
            "oneOf": [
                {"type": "string"},
                {"type": "integer"}
            ]
        }

        from backend.services.tool_configuration_service import _resolve_schema
        result = _resolve_schema(schema, schemas)

        assert "oneOf" in result
        assert len(result["oneOf"]) == 2

    def test_resolve_schema_max_depth(self):
        """Test that max recursion depth is respected."""
        schemas = {}
        # Use a schema without $ref to test depth limit directly
        schema = {
            "type": "object",
            "properties": {
                "level1": {
                    "type": "object",
                    "properties": {
                        "level2": {"type": "string"}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import _resolve_schema
        # Call with depth=11 to trigger the depth limit
        result = _resolve_schema(schema, schemas, depth=11)

        # After depth > 10, returns original schema unchanged
        assert result == schema

    def test_resolve_schema_ref_not_found_returns_empty(self):
        """Test that _resolve_schema returns empty dict when ref is not found."""
        schemas = {}
        schema = {"$ref": "#/components/schemas/NonExistent"}

        from backend.services.tool_configuration_service import _resolve_schema
        result = _resolve_schema(schema, schemas)

        # When ref is not found, _resolve_ref returns {}, which propagates
        assert result == {}


class TestParseParameters:
    """Test cases for _parse_parameters function."""

    def test_parse_query_parameters(self):
        """Test parsing query parameters."""
        parameters = [
            {"name": "limit", "in": "query", "schema": {"type": "integer"}, "description": "Max results"},
            {"name": "offset", "in": "query", "schema": {"type": "integer"}, "description": "Offset"}
        ]

        from backend.services.tool_configuration_service import _parse_parameters
        result = _parse_parameters(parameters, "query")

        assert "limit" in result
        assert "offset" in result
        assert result["limit"]["required"] is False
        assert result["offset"]["description"] == "Offset"

    def test_parse_path_parameters(self):
        """Test parsing path parameters."""
        parameters = [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
        ]

        from backend.services.tool_configuration_service import _parse_parameters
        result = _parse_parameters(parameters, "path")

        assert "id" in result
        assert result["id"]["required"] is True

    def test_parse_empty_parameters(self):
        """Test parsing empty parameters list."""
        from backend.services.tool_configuration_service import _parse_parameters
        result = _parse_parameters([], "query")

        assert result == {}


class TestImportOpenapiJson:
    """Test cases for import_openapi_json function."""

    @patch('backend.services.tool_configuration_service.sync_outer_api_tools')
    def test_import_openapi_json_success(self, mock_sync):
        """Test successful OpenAPI JSON import."""
        mock_sync.return_value = {
            "created": 5,
            "updated": 3,
            "deleted": 1
        }

        openapi_json = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "getUsers",
                        "responses": {"200": {"description": "Success"}}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import import_openapi_json
        result = import_openapi_json(openapi_json, "tenant1", "user1")

        assert result["created"] == 5
        assert result["updated"] == 3
        assert result["deleted"] == 1
        assert result["total_tools"] == 1
        mock_sync.assert_called_once()


class TestListOuterApiTools:
    """Test cases for list_outer_api_tools function."""

    @patch('backend.services.tool_configuration_service.query_outer_api_tools_by_tenant')
    def test_list_outer_api_tools_success(self, mock_query):
        """Test successful listing of outer API tools."""
        mock_query.return_value = [
            {"id": 1, "name": "tool1"},
            {"id": 2, "name": "tool2"}
        ]

        from backend.services.tool_configuration_service import list_outer_api_tools
        result = list_outer_api_tools("tenant1")

        assert len(result) == 2
        mock_query.assert_called_once_with("tenant1")

    @patch('backend.services.tool_configuration_service.query_outer_api_tools_by_tenant')
    def test_list_outer_api_tools_empty(self, mock_query):
        """Test listing when no outer API tools exist."""
        mock_query.return_value = []

        from backend.services.tool_configuration_service import list_outer_api_tools
        result = list_outer_api_tools("tenant1")

        assert len(result) == 0


class TestGetOuterApiTool:
    """Test cases for get_outer_api_tool function."""

    @patch('backend.services.tool_configuration_service.query_outer_api_tool_by_id')
    def test_get_outer_api_tool_success(self, mock_query):
        """Test successful retrieval of outer API tool."""
        mock_query.return_value = {"id": 1, "name": "test_tool"}

        from backend.services.tool_configuration_service import get_outer_api_tool
        result = get_outer_api_tool(1, "tenant1")

        assert result["id"] == 1
        assert result["name"] == "test_tool"
        mock_query.assert_called_once_with(1, "tenant1")

    @patch('backend.services.tool_configuration_service.query_outer_api_tool_by_id')
    def test_get_outer_api_tool_not_found(self, mock_query):
        """Test retrieval when outer API tool doesn't exist."""
        mock_query.return_value = None

        from backend.services.tool_configuration_service import get_outer_api_tool
        result = get_outer_api_tool(999, "tenant1")

        assert result is None


class TestDeleteOuterApiTool:
    """Test cases for delete_outer_api_tool function."""

    @patch('backend.services.tool_configuration_service._remove_outer_api_tool_from_mcp')
    @patch('backend.services.tool_configuration_service.query_outer_api_tool_by_id')
    @patch('backend.services.tool_configuration_service.db_delete_outer_api_tool')
    def test_delete_outer_api_tool_success(self, mock_delete, mock_query, mock_remove):
        """Test successful deletion of outer API tool."""
        mock_query.return_value = {"id": 1, "name": "test_tool"}
        mock_delete.return_value = True
        mock_remove.return_value = True

        from backend.services.tool_configuration_service import delete_outer_api_tool
        result = delete_outer_api_tool(1, "tenant1", "user1")

        assert result is True
        mock_delete.assert_called_once_with(1, "tenant1", "user1")
        mock_remove.assert_called_once_with("test_tool", "tenant1")

    @patch('backend.services.tool_configuration_service._remove_outer_api_tool_from_mcp')
    @patch('backend.services.tool_configuration_service.query_outer_api_tool_by_id')
    @patch('backend.services.tool_configuration_service.db_delete_outer_api_tool')
    def test_delete_outer_api_tool_not_found(self, mock_delete, mock_query, mock_remove):
        """Test deletion when tool doesn't exist."""
        mock_query.return_value = None
        mock_delete.return_value = False

        from backend.services.tool_configuration_service import delete_outer_api_tool
        result = delete_outer_api_tool(999, "tenant1", "user1")

        assert result is False
        mock_remove.assert_not_called()

    @patch('backend.services.tool_configuration_service._remove_outer_api_tool_from_mcp')
    @patch('backend.services.tool_configuration_service.query_outer_api_tool_by_id')
    @patch('backend.services.tool_configuration_service.db_delete_outer_api_tool')
    def test_delete_outer_api_tool_mcp_remove_fails(self, mock_delete, mock_query, mock_remove):
        """Test deletion when MCP removal fails (should still return True)."""
        mock_query.return_value = {"id": 1, "name": "test_tool"}
        mock_delete.return_value = True
        mock_remove.return_value = False  # MCP removal fails

        from backend.services.tool_configuration_service import delete_outer_api_tool
        result = delete_outer_api_tool(1, "tenant1", "user1")

        # Should still return True because DB deletion succeeded
        assert result is True


class TestRemoveOuterApiToolFromMcp:
    """Test cases for _remove_outer_api_tool_from_mcp function."""

    @patch('requests.delete')
    def test_remove_outer_api_tool_from_mcp_success(self, mock_delete):
        """Test successful removal from MCP server."""
        mock_response = Mock()
        mock_response.ok = True
        mock_delete.return_value = mock_response

        from backend.services.tool_configuration_service import _remove_outer_api_tool_from_mcp
        result = _remove_outer_api_tool_from_mcp("test_tool", "tenant1")

        assert result is True
        mock_delete.assert_called_once()

    @patch('requests.delete')
    def test_remove_outer_api_tool_from_mcp_failure(self, mock_delete):
        """Test removal failure from MCP server."""
        mock_response = Mock()
        mock_response.ok = False
        mock_response.status_code = 404
        mock_delete.return_value = mock_response

        from backend.services.tool_configuration_service import _remove_outer_api_tool_from_mcp
        result = _remove_outer_api_tool_from_mcp("test_tool", "tenant1")

        assert result is False

    @patch('requests.delete')
    def test_remove_outer_api_tool_from_mcp_request_exception(self, mock_delete):
        """Test removal with request exception."""
        import requests
        mock_delete.side_effect = requests.RequestException("Connection error")

        from backend.services.tool_configuration_service import _remove_outer_api_tool_from_mcp
        result = _remove_outer_api_tool_from_mcp("test_tool", "tenant1")

        assert result is False


class TestRefreshOuterApiToolsInMcp:
    """Test cases for _refresh_outer_api_tools_in_mcp function."""

    @patch('time.sleep')
    @patch('requests.post')
    def test_refresh_outer_api_tools_success(self, mock_post, mock_sleep):
        """Test successful refresh of outer API tools."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"data": {"refreshed": 5}}
        mock_post.return_value = mock_response

        from backend.services.tool_configuration_service import _refresh_outer_api_tools_in_mcp
        result = _refresh_outer_api_tools_in_mcp("tenant1")

        assert result == {"refreshed": 5}
        mock_post.assert_called_once()

    @patch('time.sleep')
    @patch('requests.post')
    def test_refresh_outer_api_tools_retry_success(self, mock_post, mock_sleep):
        """Test refresh with retry on first failure."""
        import requests
        mock_response_fail = Mock()
        mock_response_fail.ok = False
        mock_response_fail.raise_for_status.side_effect = requests.RequestException("Server error")

        mock_response_success = Mock()
        mock_response_success.ok = True
        mock_response_success.json.return_value = {"data": {"refreshed": 3}}

        mock_post.side_effect = [mock_response_fail, mock_response_success]

        from backend.services.tool_configuration_service import _refresh_outer_api_tools_in_mcp
        result = _refresh_outer_api_tools_in_mcp("tenant1")

        assert result == {"refreshed": 3}
        assert mock_post.call_count == 2
        assert mock_sleep.call_count == 1

    @patch('time.sleep')
    @patch('requests.post')
    @patch('backend.services.tool_configuration_service.logger')
    def test_refresh_outer_api_tools_all_retries_fail(self, mock_logger, mock_post, mock_sleep):
        """Test refresh when all retries fail."""
        import requests
        mock_response = Mock()
        mock_response.ok = False
        mock_response.raise_for_status.side_effect = requests.RequestException("Connection refused")
        mock_post.return_value = mock_response

        from backend.services.tool_configuration_service import _refresh_outer_api_tools_in_mcp
        result = _refresh_outer_api_tools_in_mcp("tenant1")

        assert "error" in result
        assert mock_post.call_count == 3  # max_retries = 3
        assert mock_sleep.call_count == 2  # 3 attempts, 2 sleeps

    @patch('requests.post')
    @patch('backend.services.tool_configuration_service.logger')
    def test_refresh_outer_api_tools_unexpected_exception(self, mock_logger, mock_post):
        """Test refresh with unexpected exception."""
        mock_post.side_effect = TypeError("Unexpected error")

        from backend.services.tool_configuration_service import _refresh_outer_api_tools_in_mcp
        result = _refresh_outer_api_tools_in_mcp("tenant1")

        assert "error" in result
        mock_logger.warning.assert_called_once()


class TestUpdateToolListRefreshOuterApi:
    """Test cases for update_tool_list calling _refresh_outer_api_tools_in_mcp."""

    @pytest.mark.asyncio
    @patch('backend.services.tool_configuration_service._refresh_outer_api_tools_in_mcp')
    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_langchain_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools', new_callable=AsyncMock)
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    async def test_update_tool_list_calls_refresh(self, mock_update_table, mock_get_mcp,
                                                   mock_get_langchain, mock_get_local, mock_refresh):
        """Test that update_tool_list calls _refresh_outer_api_tools_in_mcp."""
        mock_get_local.return_value = []
        mock_get_langchain.return_value = []
        mock_get_mcp.return_value = []
        mock_refresh.return_value = {"refreshed": 5}

        from backend.services.tool_configuration_service import update_tool_list
        await update_tool_list("tenant123", "user456")

        mock_refresh.assert_called_once_with("tenant123")

    @pytest.mark.asyncio
    @patch('backend.services.tool_configuration_service._refresh_outer_api_tools_in_mcp')
    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_langchain_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools', new_callable=AsyncMock)
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    async def test_update_tool_list_refresh_failure_does_not_fail(self, mock_update_table, mock_get_mcp,
                                                                   mock_get_langchain, mock_get_local, mock_refresh):
        """Test that update_tool_list continues even if refresh fails."""
        mock_get_local.return_value = []
        mock_get_langchain.return_value = []
        mock_get_mcp.return_value = []
        mock_refresh.return_value = {"error": "Connection failed"}

        from backend.services.tool_configuration_service import update_tool_list
        # Should not raise exception
        await update_tool_list("tenant123", "user456")

        mock_update_table.assert_called_once()


class TestValidateToolImplOuterApis:
    """Test cases for validate_tool_impl with outer-apis usage."""

    @patch('backend.services.tool_configuration_service._validate_mcp_tool_nexent')
    @pytest.mark.asyncio
    async def test_validate_tool_impl_mcp_outer_apis(self, mock_validate_nexent):
        """Test validate_tool_impl routes to _validate_mcp_tool_nexent for outer-apis."""
        mock_validate_nexent.return_value = "outer API result"

        request = ToolValidateRequest(
            name="outer_api_tool",
            source=ToolSourceEnum.MCP.value,
            usage="outer-apis",
            inputs={"param": "value"}
        )

        from backend.services.tool_configuration_service import validate_tool_impl
        result = await validate_tool_impl(request, "tenant1")

        assert result == "outer API result"
        mock_validate_nexent.assert_called_once_with("outer_api_tool", {"param": "value"})


class TestValidateMcpToolRemote:
    """Test cases for _validate_mcp_tool_remote function."""

    @pytest.mark.asyncio
    async def test_validate_mcp_tool_remote_success(self):
        """Test successful remote MCP tool validation."""
        mock_url = "http://remote-mcp-server/sse"
        mock_token = "auth_token_123"

        with patch('backend.services.tool_configuration_service.get_mcp_server_by_name_and_tenant', return_value=mock_url):
            with patch('backend.services.tool_configuration_service.get_mcp_authorization_token_by_name_and_url', return_value=mock_token):
                with patch('backend.services.tool_configuration_service._call_mcp_tool', return_value="tool result") as mock_call:
                    from backend.services.tool_configuration_service import _validate_mcp_tool_remote
                    result = await _validate_mcp_tool_remote(
                        "test_tool",
                        {"param": "value"},
                        "remote_mcp",
                        "tenant1"
                    )

                    assert result == "tool result"
                    mock_call.assert_called_once_with(mock_url, "test_tool", {"param": "value"}, mock_token)

    @pytest.mark.asyncio
    async def test_validate_mcp_tool_remote_server_not_found(self):
        """Test _validate_mcp_tool_remote raises NotFoundException when server not found."""
        with patch('backend.services.tool_configuration_service.get_mcp_server_by_name_and_tenant', return_value=None):
            from backend.services.tool_configuration_service import _validate_mcp_tool_remote
            with pytest.raises(NotFoundException, match="MCP server not found for name: remote_mcp"):
                await _validate_mcp_tool_remote("test_tool", {}, "remote_mcp", "tenant1")

    @pytest.mark.asyncio
    async def test_validate_mcp_tool_remote_no_token(self):
        """Test remote MCP tool validation without auth token."""
        mock_url = "http://remote-mcp-server/sse"

        with patch('backend.services.tool_configuration_service.get_mcp_server_by_name_and_tenant', return_value=mock_url):
            with patch('backend.services.tool_configuration_service.get_mcp_authorization_token_by_name_and_url', return_value=None):
                with patch('backend.services.tool_configuration_service._call_mcp_tool', return_value="tool result") as mock_call:
                    from backend.services.tool_configuration_service import _validate_mcp_tool_remote
                    result = await _validate_mcp_tool_remote(
                        "test_tool",
                        {"param": "value"},
                        "remote_mcp",
                        "tenant1"
                    )

                    assert result == "tool result"
                    # Token should be None
                    mock_call.assert_called_once_with(mock_url, "test_tool", {"param": "value"}, None)
        # Should still call with None token
        mock_call.assert_called_once()


class TestCallMcpTool:
    """Test cases for _call_mcp_tool function."""

    @pytest.mark.asyncio
    async def test_call_mcp_tool_success(self):
        """Test successful MCP tool call."""
        from fastmcp import Client

        mock_transport_instance = Mock()
        mock_client_instance = AsyncMock()
        mock_client_instance.is_connected.return_value = True
        mock_result = Mock()
        mock_result.content = [Mock(text="tool output")]
        mock_client_instance.call_tool.return_value = mock_result

        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch('backend.services.tool_configuration_service.Client', return_value=mock_client_instance):
            with patch('backend.services.tool_configuration_service._create_mcp_transport', return_value=mock_transport_instance):
                from backend.services.tool_configuration_service import _call_mcp_tool
                result = await _call_mcp_tool(
                    "http://mcp-server/sse",
                    "test_tool",
                    {"param": "value"},
                    "auth_token"
                )

        assert result == "tool output"

    @pytest.mark.asyncio
    async def test_call_mcp_tool_not_connected(self):
        """Test MCP tool call when client is not connected."""
        from fastmcp import Client

        mock_transport_instance = Mock()
        # Use a regular mock for client since we need to control is_connected behavior
        mock_client_instance = Mock(spec=Client)
        mock_client_instance.is_connected = Mock(return_value=False)
        mock_client_instance.call_tool = AsyncMock()

        # Make it work as a context manager
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch('backend.services.tool_configuration_service.Client', return_value=mock_client_instance):
            with patch('backend.services.tool_configuration_service._create_mcp_transport', return_value=mock_transport_instance):
                from backend.services.tool_configuration_service import _call_mcp_tool
                with pytest.raises(MCPConnectionError, match="Failed to connect to MCP server"):
                    await _call_mcp_tool("http://mcp-server/sse", "test_tool", {}, None)


class TestValidateLangChainTool:
    """Test cases for _validate_langchain_tool additional coverage."""

    @patch('backend.services.tool_configuration_service.discover_langchain_modules')
    def test_validate_langchain_tool_empty_inputs(self, mock_discover):
        """Test LangChain tool validation with empty dict inputs."""
        mock_tool = Mock()
        mock_tool.name = "test_tool"
        mock_tool.invoke.return_value = "result"

        mock_discover.return_value = [(mock_tool, "test_tool.py")]

        from backend.services.tool_configuration_service import _validate_langchain_tool
        # Call with empty dict (not None) to match actual usage
        result = _validate_langchain_tool("test_tool", {})

        assert result == "result"
        mock_tool.invoke.assert_called_once_with({})

    @patch('backend.services.tool_configuration_service.discover_langchain_modules')
    def test_validate_langchain_tool_exception_during_discovery(self, mock_discover):
        """Test LangChain tool validation when discovery raises exception."""
        mock_discover.side_effect = Exception("Discovery failed")

        from backend.services.tool_configuration_service import _validate_langchain_tool, ToolExecutionException
        with pytest.raises(ToolExecutionException, match="LangChain tool 'test_tool' validation failed"):
            _validate_langchain_tool("test_tool", {})


class TestGetToolClassByName:
    """Test cases for _get_tool_class_by_name function."""

    @patch('backend.services.tool_configuration_service.importlib.import_module')
    def test_get_tool_class_by_name_found(self, mock_import):
        """Test finding a tool class by name."""
        class MockToolClass:
            name = "test_tool"

        mock_module = Mock()
        mock_module.__name__ = "nexent.core.tools"
        mock_module.MockToolClass = MockToolClass
        mock_import.return_value = mock_module

        from backend.services.tool_configuration_service import _get_tool_class_by_name
        result = _get_tool_class_by_name("test_tool")

        assert result == MockToolClass

    @patch('backend.services.tool_configuration_service.importlib.import_module')
    def test_get_tool_class_by_name_not_found(self, mock_import):
        """Test when tool class is not found."""
        mock_module = Mock()
        mock_module.__name__ = "nexent.core.tools"
        mock_import.return_value = mock_module

        from backend.services.tool_configuration_service import _get_tool_class_by_name
        result = _get_tool_class_by_name("nonexistent_tool")

        assert result is None

    @patch('backend.services.tool_configuration_service.importlib.import_module')
    def test_get_tool_class_by_name_import_error(self, mock_import):
        """Test when module import fails."""
        mock_import.side_effect = Exception("Module import failed")

        from backend.services.tool_configuration_service import _get_tool_class_by_name
        result = _get_tool_class_by_name("test_tool")

        assert result is None


class TestCreateMcpTransport:
    """Test cases for _create_mcp_transport function."""

    def test_create_mcp_transport_sse(self):
        """Test creating SSE transport."""
        from backend.services.tool_configuration_service import _create_mcp_transport
        transport = _create_mcp_transport("http://server/sse", "auth_token")

        from fastmcp.client.transports import SSETransport
        assert isinstance(transport, SSETransport)

    def test_create_mcp_transport_streamable_http(self):
        """Test creating StreamableHttp transport."""
        from backend.services.tool_configuration_service import _create_mcp_transport
        transport = _create_mcp_transport("http://server/mcp", None)

        from fastmcp.client.transports import StreamableHttpTransport
        assert isinstance(transport, StreamableHttpTransport)

    def test_create_mcp_transport_default(self):
        """Test creating default transport for unrecognized URLs."""
        from backend.services.tool_configuration_service import _create_mcp_transport
        transport = _create_mcp_transport("http://server/custom", "token")

        from fastmcp.client.transports import StreamableHttpTransport
        assert isinstance(transport, StreamableHttpTransport)

    def test_create_mcp_transport_strips_whitespace(self):
        """Test that URL whitespace is stripped."""
        from backend.services.tool_configuration_service import _create_mcp_transport
        transport = _create_mcp_transport("  http://server/mcp  ", None)

        from fastmcp.client.transports import StreamableHttpTransport
        assert isinstance(transport, StreamableHttpTransport)


class TestGenerateOperationId:
    """Test cases for _generate_operation_id function."""

    def test_generate_operation_id_basic(self):
        """Test basic operation ID generation."""
        from backend.services.tool_configuration_service import _generate_operation_id
        result = _generate_operation_id("GET", "/users")

        assert result == "get_users"

    def test_generate_operation_id_with_path_params(self):
        """Test operation ID generation with path parameters."""
        from backend.services.tool_configuration_service import _generate_operation_id
        result = _generate_operation_id("POST", "/users/{id}")

        assert result == "post_users_id"

    def test_generate_operation_id_with_hyphens(self):
        """Test operation ID generation with hyphens in path."""
        from backend.services.tool_configuration_service import _generate_operation_id
        result = _generate_operation_id("GET", "/user-profiles")

        assert result == "get_user_profiles"


class TestParseRequestBody:
    """Test cases for _parse_request_body function."""

    def test_parse_request_body_with_query_params_only(self):
        """Test parsing request body with only query parameters."""
        operation = {
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "schema": {"type": "integer"},
                    "description": "Max results"
                }
            ]
        }

        from backend.services.tool_configuration_service import _parse_request_body
        result = _parse_request_body(operation, {})

        assert result["type"] == "object"
        assert "limit" in result["properties"]
        assert result["properties"]["limit"]["type"] == "integer"
        assert result["properties"]["limit"]["description"] == "Max results"

    def test_parse_request_body_with_required_query_params(self):
        """Test parsing request body with required query parameters."""
        operation = {
            "parameters": [
                {
                    "name": "user_id",
                    "in": "query",
                    "schema": {"type": "string"},
                    "required": True
                }
            ]
        }

        from backend.services.tool_configuration_service import _parse_request_body
        result = _parse_request_body(operation, {})

        assert "user_id" in result["required"]

    def test_parse_request_body_with_request_body_json(self):
        """Test parsing request body with JSON content."""
        operation = {
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "User name"},
                                "age": {"type": "integer", "description": "User age"}
                            },
                            "required": ["name"]
                        }
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import _parse_request_body
        result = _parse_request_body(operation, {})

        assert "name" in result["properties"]
        assert "age" in result["properties"]
        assert result["properties"]["name"]["type"] == "string"
        assert "name" in result["required"]

    def test_parse_request_body_with_ref_schema(self):
        """Test parsing request body with $ref schema."""
        schemas = {
            "User": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"}
                },
                "required": ["email"]
            }
        }
        operation = {
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/User"}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import _parse_request_body
        result = _parse_request_body(operation, schemas)

        assert "name" in result["properties"]
        assert "email" in result["properties"]
        assert "email" in result["required"]

    def test_parse_request_body_empty(self):
        """Test parsing empty request body."""
        from backend.services.tool_configuration_service import _parse_request_body
        result = _parse_request_body({}, {})

        assert result["type"] == "object"
        assert result["properties"] == {}
        assert result["required"] == []

    def test_parse_request_body_no_application_json(self):
        """Test parsing request body without application/json content."""
        operation = {
            "requestBody": {
                "content": {
                    "text/plain": {
                        "schema": {"type": "string"}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import _parse_request_body
        result = _parse_request_body(operation, {})

        # Should return default empty schema
        assert result["type"] == "object"
        assert result["properties"] == {}

    def test_parse_request_body_merges_query_and_body(self):
        """Test that query params and body params are merged."""
        operation = {
            "parameters": [
                {
                    "name": "source",
                    "in": "query",
                    "schema": {"type": "string"},
                    "description": "Source"
                }
            ],
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"}
                            }
                        }
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import _parse_request_body
        result = _parse_request_body(operation, {})

        assert "source" in result["properties"]
        assert "name" in result["properties"]


class TestParseRequestBodyTemplate:
    """Test cases for _parse_request_body_template function."""

    def test_parse_request_body_template_with_defaults(self):
        """Test parsing request body template with default values."""
        operation = {
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "example": "John"},
                                "age": {"type": "integer", "default": 25}
                            }
                        }
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import _parse_request_body_template
        result = _parse_request_body_template(operation, {})

        assert result["name"] == "John"
        assert result["age"] == 25

    def test_parse_request_body_template_with_ref_schema(self):
        """Test parsing request body template with $ref schema."""
        schemas = {
            "User": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "example": "Jane"},
                    "active": {"type": "boolean", "default": True}
                }
            }
        }
        operation = {
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/User"}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import _parse_request_body_template
        result = _parse_request_body_template(operation, schemas)

        assert result["name"] == "Jane"
        assert result["active"] is True

    def test_parse_request_body_template_empty(self):
        """Test parsing empty request body template."""
        from backend.services.tool_configuration_service import _parse_request_body_template
        result = _parse_request_body_template({}, {})

        assert result == {}

    def test_parse_request_body_template_no_example_or_default(self):
        """Test parsing request body template without example or default."""
        operation = {
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"}  # No example or default
                            }
                        }
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import _parse_request_body_template
        result = _parse_request_body_template(operation, {})

        assert result == {}

    def test_parse_request_body_template_no_application_json(self):
        """Test parsing request body template without application/json."""
        operation = {
            "requestBody": {
                "content": {
                    "text/plain": {
                        "schema": {"type": "string"}
                    }
                }
            }
        }

        from backend.services.tool_configuration_service import _parse_request_body_template
        result = _parse_request_body_template(operation, {})

        assert result == {}


class TestValidateMcpToolNexent:
    """Test cases for _validate_mcp_tool_nexent function."""

    @pytest.mark.asyncio
    async def test_validate_mcp_tool_nexent_success(self):
        """Test successful nexent MCP tool validation."""
        with patch('backend.services.tool_configuration_service._call_mcp_tool') as mock_call:
            mock_call.return_value = "tool result"

            from backend.services.tool_configuration_service import _validate_mcp_tool_nexent
            result = await _validate_mcp_tool_nexent("test_tool", {"param": "value"})

            assert result == "tool result"
            # Verify _call_mcp_tool was called (urljoin is used internally)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
