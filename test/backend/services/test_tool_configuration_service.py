import inspect
import unittest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from typing import Any, List, Dict
import sys
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

    @patch('backend.services.tool_configuration_service.get_current_user_id')
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
        mock_query.assert_called_once_with(1, 1, 1)

    @patch('backend.services.tool_configuration_service.get_current_user_id')
    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    def test_search_tool_info_impl_not_found(self, mock_query, mock_get_user):
        """ test the tool info not found of search_tool_info_impl"""
        mock_get_user.return_value = (1, 1)
        mock_query.return_value = None

        result = search_tool_info_impl(1, 1)

        assert result["params"] is None
        assert result["enabled"] is False

    @patch('backend.services.tool_configuration_service.get_current_user_id')
    @patch('backend.services.tool_configuration_service.query_tool_instances_by_id')
    def test_search_tool_info_impl_database_error(self, mock_query, mock_get_user):
        """ test the database error of search_tool_info_impl"""
        mock_get_user.return_value = (1, 1)
        mock_query.side_effect = Exception("Database error")

        with pytest.raises(ValueError, match="search_tool_info_impl error"):
            search_tool_info_impl(1, 1)

    @patch('backend.services.tool_configuration_service.get_current_user_id')
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
        with patch('backend.services.tool_configuration_service.get_current_user_id') as mock_get_user, \
                patch('backend.services.tool_configuration_service.query_tool_instances_by_id') as mock_query:

            mock_get_user.return_value = (1, 1)
            mock_query.return_value = None

            result = search_tool_info_impl(0, 0)
            assert result["enabled"] is False


class TestUpdateToolInfoImpl:
    """ test the function of update_tool_info_impl"""

    @patch('backend.services.tool_configuration_service.get_current_user_id')
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

    @patch('backend.services.tool_configuration_service.get_current_user_id')
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


class TestGetAllMcpTools:
    """测试 get_all_mcp_tools 函数"""

    @patch('backend.services.tool_configuration_service.get_mcp_records_by_tenant')
    @patch('backend.services.tool_configuration_service.get_tool_from_remote_mcp_server')
    @patch('backend.services.tool_configuration_service.LOCAL_MCP_SERVER', "http://default-server.com")
    @patch('backend.services.tool_configuration_service.urljoin')
    async def test_get_all_mcp_tools_success(self, mock_urljoin, mock_get_tools, mock_get_records):
        """测试成功获取所有 MCP 工具"""
        # Mock MCP 记录
        mock_get_records.return_value = [
            {"mcp_name": "server1", "mcp_server": "http://server1.com", "status": True},
            {"mcp_name": "server2", "mcp_server": "http://server2.com",
                "status": False},  # 未连接
            {"mcp_name": "server3", "mcp_server": "http://server3.com", "status": True}
        ]

        # Mock 工具信息
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

        # 验证结果
        assert len(result) == 3  # 2个连接服务器的工具 + 1个默认工具
        assert result[0].name == "tool1"
        assert result[0].usage == "server1"
        assert result[1].name == "tool2"
        assert result[1].usage == "server3"
        assert result[2].name == "default_tool"
        assert result[2].usage == "nexent"

        # 验证调用
        assert mock_get_tools.call_count == 3

    @patch('backend.services.tool_configuration_service.get_mcp_records_by_tenant')
    @patch('backend.services.tool_configuration_service.get_tool_from_remote_mcp_server')
    @patch('backend.services.tool_configuration_service.LOCAL_MCP_SERVER', "http://default-server.com")
    @patch('backend.services.tool_configuration_service.urljoin')
    async def test_get_all_mcp_tools_connection_error(self, mock_urljoin, mock_get_tools, mock_get_records):
        """测试 MCP 连接错误的情况"""
        mock_get_records.return_value = [
            {"mcp_name": "server1", "mcp_server": "http://server1.com", "status": True}
        ]
        # 第一次调用失败，第二次调用成功（默认服务器）
        mock_get_tools.side_effect = [Exception("Connection failed"),
                                      [ToolInfo(name="default_tool", description="Default Tool", params=[],
                                                source=ToolSourceEnum.MCP.value, inputs="{}", output_type="string",
                                                class_name="DefaultTool", usage="nexent")]]
        mock_urljoin.return_value = "http://default-server.com/sse"

        from backend.services.tool_configuration_service import get_all_mcp_tools

        result = await get_all_mcp_tools("test_tenant")

        # 即使连接失败，也应该返回默认工具
        assert len(result) == 1
        assert result[0].name == "default_tool"

    @patch('backend.services.tool_configuration_service.get_mcp_records_by_tenant')
    @patch('backend.services.tool_configuration_service.get_tool_from_remote_mcp_server')
    @patch('backend.services.tool_configuration_service.LOCAL_MCP_SERVER', "http://default-server.com")
    @patch('backend.services.tool_configuration_service.urljoin')
    async def test_get_all_mcp_tools_no_connected_servers(self, mock_urljoin, mock_get_tools, mock_get_records):
        """测试没有连接服务器的情况"""
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

        # 只应该返回默认工具
        assert len(result) == 1
        assert result[0].name == "default_tool"
        assert mock_get_tools.call_count == 1  # 只调用一次默认服务器


class TestGetToolFromRemoteMcpServer:
    """测试 get_tool_from_remote_mcp_server 函数"""

    @patch('backend.services.tool_configuration_service.Client')
    @patch('backend.services.tool_configuration_service.jsonref.replace_refs')
    @patch('backend.services.tool_configuration_service._sanitize_function_name')
    async def test_get_tool_from_remote_mcp_server_success(self, mock_sanitize, mock_replace_refs, mock_client_cls):
        """测试成功从远程 MCP 服务器获取工具"""
        # Mock 客户端
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        # Mock 工具列表
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

        # Mock JSON schema 处理
        mock_replace_refs.side_effect = [
            {"properties": {"param1": {"type": "string",
                                       "description": "see tool description"}}},
            {"properties": {"param2": {"type": "integer",
                                       "description": "see tool description"}}}
        ]

        # Mock 名称清理
        mock_sanitize.side_effect = ["test_tool_1", "test_tool_2"]

        from backend.services.tool_configuration_service import get_tool_from_remote_mcp_server

        result = await get_tool_from_remote_mcp_server("test_server", "http://test-server.com")

        # 验证结果
        assert len(result) == 2
        assert result[0].name == "test_tool_1"
        assert result[0].description == "Test tool 1 description"
        assert result[0].source == ToolSourceEnum.MCP.value
        assert result[0].usage == "test_server"
        assert result[1].name == "test_tool_2"
        assert result[1].description == "Test tool 2 description"

        # 验证调用
        mock_client_cls.assert_called_once_with(
            "http://test-server.com", timeout=10)
        assert mock_client.list_tools.call_count == 1

    @patch('backend.services.tool_configuration_service.Client')
    async def test_get_tool_from_remote_mcp_server_empty_tools(self, mock_client_cls):
        """测试远程服务器没有工具的情况"""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client
        mock_client.list_tools.return_value = []

        from backend.services.tool_configuration_service import get_tool_from_remote_mcp_server

        result = await get_tool_from_remote_mcp_server("test_server", "http://test-server.com")

        assert result == []

    @patch('backend.services.tool_configuration_service.Client')
    async def test_get_tool_from_remote_mcp_server_connection_error(self, mock_client_cls):
        """测试连接错误的情况"""
        mock_client_cls.side_effect = Exception("Connection failed")

        from backend.services.tool_configuration_service import get_tool_from_remote_mcp_server

        with pytest.raises(Exception, match="Connection failed"):
            await get_tool_from_remote_mcp_server("test_server", "http://test-server.com")

    @patch('backend.services.tool_configuration_service.Client')
    @patch('backend.services.tool_configuration_service.jsonref.replace_refs')
    @patch('backend.services.tool_configuration_service._sanitize_function_name')
    async def test_get_tool_from_remote_mcp_server_missing_properties(self, mock_sanitize, mock_replace_refs, mock_client_cls):
        """测试工具缺少必要属性的情况"""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        # Mock 缺少 description 和 type 的工具
        mock_tool = Mock()
        mock_tool.name = "test_tool"
        mock_tool.description = "Test tool description"
        mock_tool.inputSchema = {"properties": {
            "param1": {}}}  # 缺少 description 和 type

        mock_client.list_tools.return_value = [mock_tool]
        mock_replace_refs.return_value = {"properties": {"param1": {}}}
        mock_sanitize.return_value = "test_tool"

        from backend.services.tool_configuration_service import get_tool_from_remote_mcp_server

        result = await get_tool_from_remote_mcp_server("test_server", "http://test-server.com")

        assert len(result) == 1
        assert result[0].name == "test_tool"
        # 验证默认值被添加
        assert "see tool description" in str(result[0].inputs)
        assert "string" in str(result[0].inputs)


class TestUpdateToolList:
    """测试 update_tool_list 函数"""

    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools')
    # 添加对get_langchain_tools的模拟
    @patch('backend.services.tool_configuration_service.get_langchain_tools')
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    async def test_update_tool_list_success(self, mock_update_table, mock_get_langchain_tools, mock_get_mcp_tools, mock_get_local_tools):
        """测试成功更新工具列表"""
        # Mock 本地工具
        local_tools = [
            ToolInfo(name="local_tool", description="Local tool", params=[], source=ToolSourceEnum.LOCAL.value,
                     inputs="{}", output_type="string", class_name="LocalTool", usage=None)
        ]
        mock_get_local_tools.return_value = local_tools

        # Mock MCP 工具
        mcp_tools = [
            ToolInfo(name="mcp_tool", description="MCP tool", params=[], source=ToolSourceEnum.MCP.value,
                     inputs="{}", output_type="string", class_name="McpTool", usage="test_server")
        ]
        mock_get_mcp_tools.return_value = mcp_tools

        # Mock LangChain 工具 - 返回空列表
        mock_get_langchain_tools.return_value = [
            ToolInfo(name="langchain_tool", description="LangChain tool", params=[], source=ToolSourceEnum.LANGCHAIN.value,
                     inputs="{}", output_type="string", class_name="LangchainTool", usage="test_server")
        ]

        from backend.services.tool_configuration_service import update_tool_list

        await update_tool_list("test_tenant", "test_user")

        # 验证调用
        mock_get_local_tools.assert_called_once()
        mock_get_mcp_tools.assert_called_once_with("test_tenant")
        mock_get_langchain_tools.assert_called_once()

        # 获取mockget_langchain_tools返回的工具列表
        langchain_tools = mock_get_langchain_tools.return_value

        mock_update_table.assert_called_once_with(
            tenant_id="test_tenant",
            user_id="test_user",
            tool_list=local_tools + mcp_tools + langchain_tools
        )

    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools')
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    async def test_update_tool_list_mcp_error(self, mock_update_table, mock_get_mcp_tools, mock_get_local_tools):
        """测试 MCP 工具获取失败的情况"""
        mock_get_local_tools.return_value = []
        mock_get_mcp_tools.side_effect = Exception("MCP connection failed")

        from backend.services.tool_configuration_service import update_tool_list

        with pytest.raises(Exception, match="failed to get all mcp tools"):
            await update_tool_list("test_tenant", "test_user")

    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools')
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    async def test_update_tool_list_database_error(self, mock_update_table, mock_get_mcp_tools, mock_get_local_tools):
        """测试数据库更新失败的情况"""
        mock_get_local_tools.return_value = []
        mock_get_mcp_tools.return_value = []
        mock_update_table.side_effect = Exception("Database error")

        from backend.services.tool_configuration_service import update_tool_list

        with pytest.raises(Exception, match="failed to update tool list to PG"):
            await update_tool_list("test_tenant", "test_user")

    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools')
    # 添加对get_langchain_tools的模拟
    @patch('backend.services.tool_configuration_service.get_langchain_tools')
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    async def test_update_tool_list_empty_tools(self, mock_update_table, mock_get_langchain_tools, mock_get_mcp_tools, mock_get_local_tools):
        """测试没有工具的情况"""
        mock_get_local_tools.return_value = []
        mock_get_mcp_tools.return_value = []
        mock_get_langchain_tools.return_value = []  # 确保LangChain工具也返回空列表

        from backend.services.tool_configuration_service import update_tool_list

        await update_tool_list("test_tenant", "test_user")

        # 验证即使没有工具也会调用更新函数
        mock_update_table.assert_called_once_with(
            tenant_id="test_tenant",
            user_id="test_user",
            tool_list=[]
        )


class TestIntegrationScenarios:
    """集成测试场景"""

    @patch('backend.services.tool_configuration_service.get_local_tools')
    @patch('backend.services.tool_configuration_service.get_all_mcp_tools')
    # 添加对get_langchain_tools的模拟
    @patch('backend.services.tool_configuration_service.get_langchain_tools')
    @patch('backend.services.tool_configuration_service.update_tool_table_from_scan_tool_list')
    @patch('backend.services.tool_configuration_service.get_tool_from_remote_mcp_server')
    async def test_full_tool_update_workflow(self, mock_get_remote_tools, mock_update_table, mock_get_langchain_tools, mock_get_mcp_tools, mock_get_local_tools):
        """测试完整的工具更新工作流程"""
        # 1. 模拟本地工具
        local_tools = [
            ToolInfo(name="local_tool", description="Local tool", params=[], source=ToolSourceEnum.LOCAL.value,
                     inputs="{}", output_type="string", class_name="LocalTool", usage=None)
        ]
        mock_get_local_tools.return_value = local_tools

        # 2. 模拟 MCP 工具
        mcp_tools = [
            ToolInfo(name="mcp_tool", description="MCP tool", params=[], source=ToolSourceEnum.MCP.value,
                     inputs="{}", output_type="string", class_name="McpTool", usage="test_server")
        ]
        mock_get_mcp_tools.return_value = mcp_tools

        # 3. 模拟LangChain工具 - 设置为空列表
        mock_get_langchain_tools.return_value = []

        # 4. 模拟远程工具获取
        remote_tools = [
            ToolInfo(name="remote_tool", description="Remote tool", params=[], source=ToolSourceEnum.MCP.value,
                     inputs="{}", output_type="string", class_name="RemoteTool", usage="remote_server")
        ]
        mock_get_remote_tools.return_value = remote_tools

        from backend.services.tool_configuration_service import update_tool_list

        # 5. 执行更新
        await update_tool_list("test_tenant", "test_user")

        # 6. 验证整个流程
        mock_get_local_tools.assert_called_once()
        mock_get_mcp_tools.assert_called_once_with("test_tenant")
        mock_get_langchain_tools.assert_called_once()
        mock_update_table.assert_called_once_with(
            tenant_id="test_tenant",
            user_id="test_user",
            tool_list=local_tools + mcp_tools
        )


class TestGetLangchainTools:
    """测试 get_langchain_tools 函数"""

    @patch('utils.langchain_utils.discover_langchain_modules')
    @patch('backend.services.tool_configuration_service._build_tool_info_from_langchain')
    def test_get_langchain_tools_success(self, mock_build_tool_info, mock_discover_modules):
        """测试成功发现并转换LangChain工具"""
        # 创建模拟的LangChain工具对象
        mock_tool1 = Mock()
        mock_tool1.name = "langchain_tool_1"
        mock_tool1.description = "LangChain tool 1"

        mock_tool2 = Mock()
        mock_tool2.name = "langchain_tool_2"
        mock_tool2.description = "LangChain tool 2"

        # 模拟discover_langchain_modules返回值
        mock_discover_modules.return_value = [
            (mock_tool1, "tool1.py"),
            (mock_tool2, "tool2.py")
        ]

        # 模拟_build_tool_info_from_langchain返回值
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

        # 导入待测函数
        from backend.services.tool_configuration_service import get_langchain_tools

        # 调用函数
        result = get_langchain_tools()

        # 验证结果
        assert len(result) == 2
        assert result[0] == tool_info1
        assert result[1] == tool_info2

        # 验证调用
        mock_discover_modules.assert_called_once()
        assert mock_build_tool_info.call_count == 2

    @patch('utils.langchain_utils.discover_langchain_modules')
    def test_get_langchain_tools_empty_result(self, mock_discover_modules):
        """测试未发现任何LangChain工具的情况"""
        # 模拟discover_langchain_modules返回空列表
        mock_discover_modules.return_value = []

        from backend.services.tool_configuration_service import get_langchain_tools

        result = get_langchain_tools()

        # 验证结果为空列表
        assert result == []
        mock_discover_modules.assert_called_once()

    @patch('utils.langchain_utils.discover_langchain_modules')
    @patch('backend.services.tool_configuration_service._build_tool_info_from_langchain')
    def test_get_langchain_tools_exception_handling(self, mock_build_tool_info, mock_discover_modules):
        """测试处理工具时出现异常的情况"""
        # 创建模拟的LangChain工具对象
        mock_tool1 = Mock()
        mock_tool1.name = "good_tool"

        mock_tool2 = Mock()
        mock_tool2.name = "problematic_tool"

        # 模拟discover_langchain_modules返回值
        mock_discover_modules.return_value = [
            (mock_tool1, "good_tool.py"),
            (mock_tool2, "problematic_tool.py")
        ]

        # 模拟_build_tool_info_from_langchain的行为
        # 第一次调用成功，第二次调用抛出异常
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

        # 调用函数 - 不应该抛出异常
        result = get_langchain_tools()

        # 验证结果 - 只有成功处理的工具
        assert len(result) == 1
        assert result[0] == tool_info1

        # 验证调用
        mock_discover_modules.assert_called_once()
        assert mock_build_tool_info.call_count == 2

    @patch('utils.langchain_utils.discover_langchain_modules')
    @patch('backend.services.tool_configuration_service._build_tool_info_from_langchain')
    def test_get_langchain_tools_with_different_tool_types(self, mock_build_tool_info, mock_discover_modules):
        """测试处理不同类型的LangChain工具对象"""
        # 创建不同类型的工具对象
        class CustomTool:
            def __init__(self):
                self.name = "custom_tool"
                self.description = "Custom tool"

        mock_tool1 = Mock()  # 标准Mock对象
        mock_tool1.name = "mock_tool"
        mock_tool1.description = "Mock tool"

        mock_tool2 = CustomTool()  # 自定义类对象

        # 模拟discover_langchain_modules返回值
        mock_discover_modules.return_value = [
            (mock_tool1, "mock_tool.py"),
            (mock_tool2, "custom_tool.py")
        ]

        # 模拟_build_tool_info_from_langchain返回值
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

        # 验证结果
        assert len(result) == 2
        assert result[0] == tool_info1
        assert result[1] == tool_info2

        # 验证调用
        mock_discover_modules.assert_called_once()
        assert mock_build_tool_info.call_count == 2


if __name__ == '__main__':
    unittest.main()
