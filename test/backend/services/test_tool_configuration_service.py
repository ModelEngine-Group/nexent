import asyncio
import inspect
import sys
import unittest
from typing import Any, List, Dict
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

boto3_mock = MagicMock()
minio_client_mock = MagicMock()
sys.modules['boto3'] = boto3_mock
with patch('backend.database.client.MinioClient', return_value=minio_client_mock):
    from backend.services.tool_configuration_service import (
        python_type_to_json_schema,
        get_local_tools,
        get_local_tools_classes,
        search_tool_info_impl,
        update_tool_info_impl,
        list_all_tools,
        load_last_tool_config_impl, validate_tool_impl
)
from consts.exceptions import MCPConnectionError, NotFoundException, ToolExecutionException
from consts.model import ToolInfo, ToolSourceEnum, ToolInstanceInfoRequest, ToolValidateRequest


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

        result = get_local_tools_classes()

        # Assertions
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
        mock_tool_class.description = Mock(
            side_effect=AttributeError("No description"))

        mock_get_classes.return_value = [mock_tool_class]

        with pytest.raises(AttributeError):
            get_local_tools()


class TestSearchToolInfoImpl:
    """ test the function of search_tool_info_impl"""

    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    def test_search_tool_info_impl_success(self, mock_query):
        """ test the success of search_tool_info_impl"""
        mock_query.return_value = {
            "params": {"param1": "value1"},
            "enabled": True
        }

        result = search_tool_info_impl(1, 1, "test_tenant")

        assert result["params"] == {"param1": "value1"}
        assert result["enabled"] is True
        mock_query.assert_called_once_with(1, 1, "test_tenant")

    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    def test_search_tool_info_impl_not_found(self, mock_query):
        """ test the tool info not found of search_tool_info_impl"""
        mock_query.return_value = None

        result = search_tool_info_impl(1, 1, "test_tenant")

        assert result["params"] is None
        assert result["enabled"] is False

    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    def test_search_tool_info_impl_database_error(self, mock_query):
        """ test the database error of search_tool_info_impl"""
        mock_query.side_effect = Exception("Database error")

        with pytest.raises(Exception):
            search_tool_info_impl(1, 1, "test_tenant")

    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    def test_search_tool_info_impl_invalid_ids(self, mock_query):
        """ test the invalid id of search_tool_info_impl"""
        # test the negative id
        mock_query.return_value = None
        result = search_tool_info_impl(-1, -1, "test_tenant")
        assert result["enabled"] is False

    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    def test_search_tool_info_impl_zero_ids(self, mock_query):
        """ test the zero id of search_tool_info_impl"""
        mock_query.return_value = None

        result = search_tool_info_impl(0, 0, "test_tenant")
        assert result["enabled"] is False


class TestUpdateToolInfoImpl:
    """ test the function of update_tool_info_impl"""

    @patch('backend.services.tool_configuration_service.create_or_update_tool_by_tool_info')
    def test_update_tool_info_impl_success(self, mock_create_update):
        """ test the success of update_tool_info_impl"""
        mock_request = Mock(spec=ToolInstanceInfoRequest)
        mock_tool_instance = {"id": 1, "name": "test_tool"}
        mock_create_update.return_value = mock_tool_instance

        result = update_tool_info_impl(
            mock_request, "test_tenant", "test_user")

        assert result["tool_instance"] == mock_tool_instance
        mock_create_update.assert_called_once_with(
            mock_request, "test_tenant", "test_user")

    @patch('backend.services.tool_configuration_service.create_or_update_tool_by_tool_info')
    def test_update_tool_info_impl_database_error(self, mock_create_update):
        """ test the database error of update_tool_info_impl"""
        mock_request = Mock(spec=ToolInstanceInfoRequest)
        mock_create_update.side_effect = Exception("Database error")

        with pytest.raises(Exception):
            update_tool_info_impl(mock_request, "test_tenant", "test_user")


class TestListAllTools:
    """ test the function of list_all_tools"""

    @patch('backend.services.tool_configuration_service.query_all_tools')
    async def test_list_all_tools_success(self, mock_query):
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

        result = await list_all_tools("test_tenant")

        assert len(result) == 2
        assert result[0]["tool_id"] == 1
        assert result[0]["name"] == "test_tool_1"
        assert result[1]["tool_id"] == 2
        assert result[1]["name"] == "test_tool_2"
        mock_query.assert_called_once_with("test_tenant")

    @patch('backend.services.tool_configuration_service.query_all_tools')
    async def test_list_all_tools_empty_result(self, mock_query):
        """ test the empty result of list_all_tools"""
        mock_query.return_value = []

        result = await list_all_tools("test_tenant")

        assert result == []
        mock_query.assert_called_once_with("test_tenant")

    @patch('backend.services.tool_configuration_service.query_all_tools')
    async def test_list_all_tools_missing_fields(self, mock_query):
        """ test tools with missing fields"""
        mock_tools = [
            {
                "tool_id": 1,
                "name": "test_tool",
                "description": "Test tool"
                # missing other fields
            }
        ]
        mock_query.return_value = mock_tools

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


class TestInitializeToolsOnStartup:
    """Test cases for initialize_tools_on_startup function"""

    @patch('backend.services.tool_configuration_service.get_all_tenant_ids')
    @patch('backend.services.tool_configuration_service.update_tool_list')
    @patch('backend.services.tool_configuration_service.query_all_tools')
    @patch('backend.services.tool_configuration_service.logger')
    async def test_initialize_tools_on_startup_no_tenants(self, mock_logger, mock_query_tools, mock_update_tool_list, mock_get_tenants):
        """Test initialize_tools_on_startup when no tenants are found"""
        # Mock get_all_tenant_ids to return empty list
        mock_get_tenants.return_value = []

        # Import and call the function
        from backend.services.tool_configuration_service import initialize_tools_on_startup
        await initialize_tools_on_startup()

        # Verify warning was logged
        mock_logger.warning.assert_called_with(
            "No tenants found in database, skipping tool initialization")
        mock_update_tool_list.assert_not_called()

    @patch('backend.services.tool_configuration_service.get_all_tenant_ids')
    @patch('backend.services.tool_configuration_service.update_tool_list')
    @patch('backend.services.tool_configuration_service.query_all_tools')
    @patch('backend.services.tool_configuration_service.logger')
    async def test_initialize_tools_on_startup_success(self, mock_logger, mock_query_tools, mock_update_tool_list, mock_get_tenants):
        """Test successful tool initialization for all tenants"""
        # Mock tenant IDs
        tenant_ids = ["tenant_1", "tenant_2", "default_tenant"]
        mock_get_tenants.return_value = tenant_ids

        # Mock update_tool_list to succeed
        mock_update_tool_list.return_value = None

        # Mock query_all_tools to return mock tools
        mock_tools = [
            {"tool_id": "tool_1", "name": "Test Tool 1"},
            {"tool_id": "tool_2", "name": "Test Tool 2"}
        ]
        mock_query_tools.return_value = mock_tools

        # Import and call the function
        from backend.services.tool_configuration_service import initialize_tools_on_startup
        await initialize_tools_on_startup()

        # Verify update_tool_list was called for each tenant
        assert mock_update_tool_list.call_count == len(tenant_ids)

        # Verify success logging
        mock_logger.info.assert_any_call("Tool initialization completed!")
        mock_logger.info.assert_any_call(
            "Total tools available across all tenants: 6")  # 2 tools * 3 tenants
        mock_logger.info.assert_any_call("Successfully processed: 3/3 tenants")

    @patch('backend.services.tool_configuration_service.get_all_tenant_ids')
    @patch('backend.services.tool_configuration_service.update_tool_list')
    @patch('backend.services.tool_configuration_service.logger')
    async def test_initialize_tools_on_startup_timeout(self, mock_logger, mock_update_tool_list, mock_get_tenants):
        """Test tool initialization timeout scenario"""
        tenant_ids = ["tenant_1", "tenant_2"]
        mock_get_tenants.return_value = tenant_ids

        # Mock update_tool_list to timeout
        mock_update_tool_list.side_effect = asyncio.TimeoutError()

        # Import and call the function
        from backend.services.tool_configuration_service import initialize_tools_on_startup
        await initialize_tools_on_startup()

        # Verify timeout error was logged for each tenant
        assert mock_logger.error.call_count == len(tenant_ids)
        for call in mock_logger.error.call_args_list:
            assert "timed out" in str(call)

        # Verify failed tenants were logged
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "Failed tenants:" in warning_call
        assert "tenant_1 (timeout)" in warning_call
        assert "tenant_2 (timeout)" in warning_call

    @patch('backend.services.tool_configuration_service.get_all_tenant_ids')
    @patch('backend.services.tool_configuration_service.update_tool_list')
    @patch('backend.services.tool_configuration_service.logger')
    async def test_initialize_tools_on_startup_exception(self, mock_logger, mock_update_tool_list, mock_get_tenants):
        """Test tool initialization with exception during processing"""
        tenant_ids = ["tenant_1", "tenant_2"]
        mock_get_tenants.return_value = tenant_ids

        # Mock update_tool_list to raise exception
        mock_update_tool_list.side_effect = Exception(
            "Database connection failed")

        # Import and call the function
        from backend.services.tool_configuration_service import initialize_tools_on_startup
        await initialize_tools_on_startup()

        # Verify exception error was logged for each tenant
        assert mock_logger.error.call_count == len(tenant_ids)
        for call in mock_logger.error.call_args_list:
            assert "Tool initialization failed" in str(call)
            assert "Database connection failed" in str(call)

        # Verify failed tenants were logged
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "Failed tenants:" in warning_call
        assert "tenant_1 (error: Database connection failed)" in warning_call
        assert "tenant_2 (error: Database connection failed)" in warning_call

    @patch('backend.services.tool_configuration_service.get_all_tenant_ids')
    @patch('backend.services.tool_configuration_service.logger')
    async def test_initialize_tools_on_startup_critical_exception(self, mock_logger, mock_get_tenants):
        """Test tool initialization when get_all_tenant_ids raises exception"""
        # Mock get_all_tenant_ids to raise exception
        mock_get_tenants.side_effect = Exception("Database connection failed")

        # Import and call the function
        from backend.services.tool_configuration_service import initialize_tools_on_startup

        # Should raise the exception
        with pytest.raises(Exception, match="Database connection failed"):
            await initialize_tools_on_startup()

        # Verify critical error was logged
        mock_logger.error.assert_called_with(
            "❌ Tool initialization failed: Database connection failed")

    @patch('backend.services.tool_configuration_service.get_all_tenant_ids')
    @patch('backend.services.tool_configuration_service.update_tool_list')
    @patch('backend.services.tool_configuration_service.query_all_tools')
    @patch('backend.services.tool_configuration_service.logger')
    async def test_initialize_tools_on_startup_mixed_results(self, mock_logger, mock_query_tools, mock_update_tool_list, mock_get_tenants):
        """Test tool initialization with mixed success and failure results"""
        tenant_ids = ["tenant_1", "tenant_2", "tenant_3"]
        mock_get_tenants.return_value = tenant_ids

        # Mock update_tool_list with mixed results
        def side_effect(*args, **kwargs):
            tenant_id = kwargs.get('tenant_id')
            if tenant_id == "tenant_1":
                return None  # Success
            elif tenant_id == "tenant_2":
                raise asyncio.TimeoutError()  # Timeout
            else:  # tenant_3
                raise Exception("Connection error")  # Exception

        mock_update_tool_list.side_effect = side_effect

        # Mock query_all_tools for successful tenant
        mock_tools = [{"tool_id": "tool_1", "name": "Test Tool"}]
        mock_query_tools.return_value = mock_tools

        # Import and call the function
        from backend.services.tool_configuration_service import initialize_tools_on_startup
        await initialize_tools_on_startup()

        # Verify mixed results logging
        mock_logger.info.assert_any_call("Tool initialization completed!")
        mock_logger.info.assert_any_call(
            "Total tools available across all tenants: 1")
        mock_logger.info.assert_any_call("Successfully processed: 1/3 tenants")

        # Verify failed tenants were logged
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "Failed tenants:" in warning_call
        assert "tenant_2 (timeout)" in warning_call
        assert "tenant_3 (error: Connection error)" in warning_call


class TestLoadLastToolConfigImpl:
    """Test load_last_tool_config_impl function"""

    @patch('backend.services.tool_configuration_service.search_last_tool_instance_by_tool_id')
    def test_load_last_tool_config_impl_success(self, mock_search_tool_instance):
        """Test successfully loading last tool configuration"""
        mock_tool_instance = {
            "tool_instance_id": 1,
            "tool_id": 123,
            "params": {"param1": "value1", "param2": "value2"},
            "enabled": True
        }
        mock_search_tool_instance.return_value = mock_tool_instance

        result = load_last_tool_config_impl(123, "tenant1", "user1")

        assert result == {"param1": "value1", "param2": "value2"}
        mock_search_tool_instance.assert_called_once_with(
            123, "tenant1", "user1")

    @patch('backend.services.tool_configuration_service.search_last_tool_instance_by_tool_id')
    def test_load_last_tool_config_impl_not_found(self, mock_search_tool_instance):
        """Test loading tool config when tool instance not found"""
        mock_search_tool_instance.return_value = None

        with pytest.raises(ValueError, match="Tool configuration not found for tool ID: 123"):
            load_last_tool_config_impl(123, "tenant1", "user1")

        mock_search_tool_instance.assert_called_once_with(
            123, "tenant1", "user1")

    @patch('backend.services.tool_configuration_service.search_last_tool_instance_by_tool_id')
    def test_load_last_tool_config_impl_empty_params(self, mock_search_tool_instance):
        """Test loading tool config with empty params"""
        mock_tool_instance = {
            "tool_instance_id": 1,
            "tool_id": 123,
            "params": {},
            "enabled": True
        }
        mock_search_tool_instance.return_value = mock_tool_instance

        result = load_last_tool_config_impl(123, "tenant1", "user1")

        assert result == {}
        mock_search_tool_instance.assert_called_once_with(
            123, "tenant1", "user1")

    @patch('backend.services.tool_configuration_service.Client')
    async def test_call_mcp_tool_success(self, mock_client_cls):
        """Test successful MCP tool call"""
        # Mock client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.is_connected.return_value = True

        # Mock tool result
        mock_result = Mock()
        mock_result.text = "test result"
        mock_client.call_tool.return_value = [mock_result]

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
    async def test_validate_tool_nexent(self, mock_validate_nexent):
        """Test MCP tool validation using nexent server"""
        mock_validate_nexent.return_value = "nexent result"

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.MCP.value,
            usage="nexent",
            inputs={"param": "value"}
        )

        result = await validate_tool_impl(request, "tenant1")

        assert result == "nexent result"
        mock_validate_nexent.assert_called_once_with(
            "test_tool", {"param": "value"})

    @patch('backend.services.tool_configuration_service._validate_mcp_tool_remote')
    async def test_validate_tool_remote(self, mock_validate_remote):
        """Test MCP tool validation using remote server"""
        mock_validate_remote.return_value = "remote result"

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.MCP.value,
            usage="remote_server",
            inputs={"param": "value"}
        )

        result = await validate_tool_impl(request, "tenant1")

        assert result == "remote result"
        mock_validate_remote.assert_called_once_with(
            "test_tool", {"param": "value"}, "remote_server", "tenant1")

    @patch('backend.services.tool_configuration_service._validate_local_tool')
    async def test_validate_tool_local(self, mock_validate_local):
        """Test local tool validation"""
        mock_validate_local.return_value = "local result"

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.LOCAL.value,
            usage=None,
            inputs={"param": "value"},
            params={"config": "value"}
        )

        result = await validate_tool_impl(request, "tenant1")

        assert result == "local result"
        mock_validate_local.assert_called_once_with(
            "test_tool", {"param": "value"}, {"config": "value"})

    @patch('backend.services.tool_configuration_service._validate_langchain_tool')
    async def test_validate_tool_langchain(self, mock_validate_langchain):
        """Test LangChain tool validation"""
        mock_validate_langchain.return_value = "langchain result"

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.LANGCHAIN.value,
            usage=None,
            inputs={"param": "value"}
        )

        result = await validate_tool_impl(request, "tenant1")

        assert result == "langchain result"
        mock_validate_langchain.assert_called_once_with(
            "test_tool", {"param": "value"})

    async def test_validate_tool_unsupported_source(self):
        """Test validation with unsupported tool source"""
        request = ToolValidateRequest(
            name="test_tool",
            source="unsupported",
            usage=None,
            inputs={"param": "value"}
        )

        with pytest.raises(ToolExecutionException, match="Validate Tool failed"):
            await validate_tool_impl(request, "tenant1")

    @patch('backend.services.tool_configuration_service._validate_mcp_tool_nexent')
    async def test_validate_tool_nexent_connection_error(self, mock_validate_nexent):
        """Test MCP tool validation when connection fails"""
        mock_validate_nexent.side_effect = MCPConnectionError(
            "Connection failed")

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.MCP.value,
            usage="nexent",
            inputs={"param": "value"}
        )

        with pytest.raises(MCPConnectionError, match="MCP connection failed: Connection failed"):
            await validate_tool_impl(request, "tenant1")

    @patch('backend.services.tool_configuration_service._validate_local_tool')
    async def test_validate_tool_local_execution_error(self, mock_validate_local):
        """Test local tool validation when execution fails"""
        mock_validate_local.side_effect = Exception("Execution failed")

        request = ToolValidateRequest(
            name="test_tool",
            source=ToolSourceEnum.LOCAL.value,
            usage=None,
            inputs={"param": "value"},
            params={"config": "value"}
        )

        with pytest.raises(ToolExecutionException, match="Validate Tool failed"):
            await validate_tool_impl(request, "tenant1")


if __name__ == '__main__':
    unittest.main()
