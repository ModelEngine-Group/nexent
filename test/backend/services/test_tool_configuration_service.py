import pytest
import inspect
import unittest
from unittest.mock import Mock, patch, MagicMock
from typing import Any, List, Dict
import sys

boto3_mock = MagicMock()
minio_client_mock = MagicMock()
sys.modules['boto3'] = boto3_mock
with patch('backend.database.client.MinioClient', return_value=minio_client_mock):
    from backend.services.tool_configuration_service import (
        python_type_to_json_schema,
        get_local_tools,
        get_local_tools_classes,
        search_tool_info_impl,
        update_tool_info_impl
    )
from consts.model import ToolInfo, ToolSourceEnum, ToolInstanceInfoRequest


class TestPythonTypeToJsonSchema:
    """ test the function of python_type_to_json_schema"""

    def test_python_type_to_json_schema_basic_types(self):
        """ test the basic types of python"""
        assert python_type_to_json_schema(str) == "string"
        assert python_type_to_json_schema(int) == "integer"
        assert python_type_to_json_schema(float) == "float"
        assert python_type_to_json_schema(bool) == "boolean"
        assert python_type_to_json_schema(list) == "array"
        assert python_type_to_json_schema(dict) == "object"

    def test_python_type_to_json_schema_typing_types(self):
        """ test the typing types of python"""
        from typing import List, Dict, Tuple, Any
        
        assert python_type_to_json_schema(List) == "array"
        assert python_type_to_json_schema(Dict) == "object"
        assert python_type_to_json_schema(Tuple) == "array"
        assert python_type_to_json_schema(Any) == "any"

    def test_python_type_to_json_schema_empty_annotation(self):
        """ test the empty annotation of python"""
        assert python_type_to_json_schema(inspect.Parameter.empty) == "string"

    def test_python_type_to_json_schema_unknown_type(self):
        """ test the unknown type of python"""
        class CustomType:
            pass
        
        # the unknown type should return the type name itself
        result = python_type_to_json_schema(CustomType)
        assert "CustomType" in result

    def test_python_type_to_json_schema_edge_cases(self):
        """ test the edge cases of python"""
        # test the None type
        assert python_type_to_json_schema(type(None)) == "NoneType"
        
        # test the complex type string representation
        complex_type = List[Dict[str, Any]]
        result = python_type_to_json_schema(complex_type)
        assert isinstance(result, str)


class TestGetLocalToolsClasses:
    """ test the function of get_local_tools_classes"""

    @patch('backend.services.tool_configuration_service.importlib.import_module')
    def test_get_local_tools_classes_success(self, mock_import):
        """ test the success of get_local_tools_classes"""
        # create the mock tool class
        mock_tool_class1 = type('TestTool1', (), {})
        mock_tool_class2 = type('TestTool2', (), {})
        mock_non_class = "not_a_class"
        
        # create the mock package, use MagicMock to avoid circular reference problem
        mock_package = MagicMock()
        
        # directly set the attributes instead of through __dict__
        mock_package.TestTool1 = mock_tool_class1
        mock_package.TestTool2 = mock_tool_class2
        mock_package.not_a_class = mock_non_class
        mock_package.__name__ = 'nexent.core.tools'
        
        def mock_dir(obj):
            return ['TestTool1', 'TestTool2', 'not_a_class', '__name__']
        
        def mock_getattr(obj, name):
            if name == 'TestTool1':
                return mock_tool_class1
            elif name == 'TestTool2':
                return mock_tool_class2
            elif name == 'not_a_class':
                return mock_non_class
            elif name == '__name__':
                return 'nexent.core.tools'
            else:
                raise AttributeError(f"'{type(obj).__name__}' object has no attribute '{name}'")
        
        mock_import.return_value = mock_package
        
        with patch('builtins.dir', side_effect=mock_dir), \
             patch('builtins.getattr', side_effect=mock_getattr):
            
            result = get_local_tools_classes()
            
            assert len(result) == 2
            assert mock_tool_class1 in result
            assert mock_tool_class2 in result
            assert mock_non_class not in result

    @patch('backend.services.tool_configuration_service.importlib.import_module')
    def test_get_local_tools_classes_import_error(self, mock_import):
        """ test the import error of get_local_tools_classes"""
        mock_import.side_effect = ImportError("Module not found")
        
        with pytest.raises(ImportError):
            get_local_tools_classes()


class TestGetLocalTools:
    """ test the function of get_local_tools"""

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    @patch('backend.services.tool_configuration_service.inspect.signature')
    def test_get_local_tools_success(self, mock_signature, mock_get_classes):
        """ test the success of get_local_tools"""
        # create the mock tool class
        mock_tool_class = Mock()
        mock_tool_class.name = "test_tool"
        mock_tool_class.description = "Test tool description"
        mock_tool_class.inputs = {"input1": "value1"}
        mock_tool_class.output_type = "string"
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
        
        result = get_local_tools()
        
        assert len(result) == 1
        tool_info = result[0]
        assert tool_info.name == "test_tool"
        assert tool_info.description == "Test tool description"
        assert tool_info.source == ToolSourceEnum.LOCAL.value
        assert tool_info.class_name == "TestTool"

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_get_local_tools_no_classes(self, mock_get_classes):
        """ test the no tool class of get_local_tools"""
        mock_get_classes.return_value = []
        
        result = get_local_tools()
        assert result == []

    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_get_local_tools_with_exception(self, mock_get_classes):
        """ test the exception of get_local_tools"""
        mock_tool_class = Mock()
        mock_tool_class.name = "test_tool"
        # mock the attribute error
        mock_tool_class.description = Mock(side_effect=AttributeError("No description"))
        
        mock_get_classes.return_value = [mock_tool_class]
        
        with pytest.raises(AttributeError):
            get_local_tools()

class TestSearchToolInfoImpl:
    """ test the function of search_tool_info_impl"""

    @patch('backend.services.tool_configuration_service.get_user_info')
    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    def test_search_tool_info_impl_success(self, mock_query, mock_get_user):
        """ test the success of search_tool_info_impl"""
        mock_get_user.return_value = (1, 1)  # user_id, tenant_id
        mock_query.return_value = {
            "params": {"param1": "value1"},
            "enabled": True
        }
        
        result = search_tool_info_impl(1, 1)
        
        assert result["params"] == {"param1": "value1"}
        assert result["enabled"] is True
        mock_query.assert_called_once_with(1, 1, 1, 1)

    @patch('backend.services.tool_configuration_service.get_user_info')
    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    def test_search_tool_info_impl_not_found(self, mock_query, mock_get_user):
        """ test the tool info not found of search_tool_info_impl"""
        mock_get_user.return_value = (1, 1)
        mock_query.return_value = None
        
        result = search_tool_info_impl(1, 1)
        
        assert result["params"] is None
        assert result["enabled"] is False

    @patch('backend.services.tool_configuration_service.get_user_info')
    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    def test_search_tool_info_impl_database_error(self, mock_query, mock_get_user):
        """ test the database error of search_tool_info_impl"""
        mock_get_user.return_value = (1, 1)
        mock_query.side_effect = Exception("Database error")
        
        with pytest.raises(ValueError, match="search_tool_info_impl error"):
            search_tool_info_impl(1, 1)

    @patch('backend.services.tool_configuration_service.get_user_info')
    def test_search_tool_info_impl_invalid_ids(self, mock_get_user):
        """ test the invalid id of search_tool_info_impl"""
        mock_get_user.return_value = (1, 1)
        
        # test the negative id
        with patch('backend.services.tool_configuration_service.query_tool_instances_by_id') as mock_query:
            mock_query.return_value = None
            result = search_tool_info_impl(-1, -1)
            assert result["enabled"] is False

    def test_search_tool_info_impl_zero_ids(self):
        """ test the zero id of search_tool_info_impl"""
        with patch('backend.services.tool_configuration_service.get_user_info') as mock_get_user, \
             patch('backend.services.tool_configuration_service.query_tool_instances_by_id') as mock_query:
            
            mock_get_user.return_value = (1, 1)
            mock_query.return_value = None
            
            result = search_tool_info_impl(0, 0)
            assert result["enabled"] is False


class TestUpdateToolInfoImpl:
    """ test the function of update_tool_info_impl"""

    @patch('backend.services.tool_configuration_service.get_user_info')
    @patch('backend.services.tool_configuration_service.create_or_update_tool_by_tool_info')
    def test_update_tool_info_impl_success(self, mock_create_update, mock_get_user):
        """ test the success of update_tool_info_impl"""
        mock_get_user.return_value = (1, 1)
        mock_request = Mock(spec=ToolInstanceInfoRequest)
        mock_tool_instance = {"id": 1, "name": "test_tool"}
        mock_create_update.return_value = mock_tool_instance
        
        result = update_tool_info_impl(mock_request)
        
        assert result["tool_instance"] == mock_tool_instance
        mock_create_update.assert_called_once_with(mock_request, 1, 1)

    @patch('backend.services.tool_configuration_service.get_user_info')
    @patch('backend.services.tool_configuration_service.create_or_update_tool_by_tool_info')
    def test_update_tool_info_impl_database_error(self, mock_create_update, mock_get_user):
        """ test the database error of update_tool_info_impl"""
        mock_get_user.return_value = (1, 1)
        mock_request = Mock(spec=ToolInstanceInfoRequest)
        mock_create_update.side_effect = Exception("Database error")
        
        with pytest.raises(ValueError, match="update_tool_info_impl error"):
            update_tool_info_impl(mock_request)


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


if __name__ == '__main__':
    unittest.main()