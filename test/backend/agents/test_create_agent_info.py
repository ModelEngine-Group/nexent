import pytest
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, Mock, PropertyMock, mock_open
from typing import List, Tuple, Any

# Mock external dependencies before imports
sys.modules['nexent.core.utils.observer'] = MagicMock()
sys.modules['nexent.core.agents.agent_model'] = MagicMock()
sys.modules['smolagents.agents'] = MagicMock()
sys.modules['smolagents.utils'] = MagicMock()
sys.modules['services.remote_mcp_service'] = MagicMock()
sys.modules['utils.auth_utils'] = MagicMock()
sys.modules['database.agent_db'] = MagicMock()
sys.modules['database.tool_db'] = MagicMock()
sys.modules['services.elasticsearch_service'] = MagicMock()
sys.modules['services.tenant_config_service'] = MagicMock()
sys.modules['utils.prompt_template_utils'] = MagicMock()
sys.modules['utils.config_utils'] = MagicMock()
sys.modules['utils.langchain_utils'] = MagicMock()
sys.modules['langchain_core.tools'] = MagicMock()
sys.modules['services.memory_config_service'] = MagicMock()
sys.modules['nexent.memory.memory_service'] = MagicMock()

# Create mock classes that might be imported
mock_agent_config = MagicMock()
mock_model_config = MagicMock()
mock_tool_config = MagicMock()
mock_agent_run_info = MagicMock()
mock_message_observer = MagicMock()

sys.modules['nexent.core.agents.agent_model'].AgentConfig = mock_agent_config
sys.modules['nexent.core.agents.agent_model'].ModelConfig = mock_model_config
sys.modules['nexent.core.agents.agent_model'].ToolConfig = mock_tool_config
sys.modules['nexent.core.agents.agent_model'].AgentRunInfo = mock_agent_run_info
sys.modules['nexent.core.utils.observer'].MessageObserver = mock_message_observer

# Mock BASE_BUILTIN_MODULES
sys.modules['smolagents.utils'].BASE_BUILTIN_MODULES = ["os", "sys", "json"]

# Now import the module under test
from backend.agents.create_agent_info import (
    discover_langchain_tools,
    create_tool_config_list,
    create_agent_config,
    create_model_config_list,
    filter_mcp_servers_and_tools,
    create_agent_run_info,
    join_minio_file_description_to_query,
    prepare_prompt_templates
)


class TestDiscoverLangchainTools:
    """测试discover_langchain_tools函数"""

    @pytest.mark.asyncio
    async def test_discover_langchain_tools_success(self):
        """测试成功发现LangChain工具的情况"""
        # 准备测试数据
        mock_tool1 = Mock()
        mock_tool1.name = "test_tool1"
        
        mock_tool2 = Mock()
        mock_tool2.name = "test_tool2"
        
        # Mock the import statement inside the function
        mock_discover_func = Mock(return_value=[
            (mock_tool1, "tool1.py"),
            (mock_tool2, "tool2.py")
        ])
        
        with patch('backend.agents.create_agent_info.logger') as mock_logger:
            # Mock the import by patching the globals within the function scope
            with patch.dict('sys.modules', {
                'utils.langchain_utils': Mock(discover_langchain_modules=mock_discover_func)
            }):
                # 执行测试
                result = await discover_langchain_tools()
                
                # 验证结果
                assert len(result) == 2
                assert result[0] == mock_tool1
                assert result[1] == mock_tool2
                
                # 验证调用
                mock_discover_func.assert_called_once()
                assert mock_logger.info.call_count == 2
                mock_logger.info.assert_any_call("Loaded LangChain tool 'test_tool1' from tool1.py")
                mock_logger.info.assert_any_call("Loaded LangChain tool 'test_tool2' from tool2.py")

    @pytest.mark.asyncio
    async def test_discover_langchain_tools_empty(self):
        """测试未发现任何工具的情况"""
        mock_discover_func = Mock(return_value=[])
        
        with patch.dict('sys.modules', {
            'utils.langchain_utils': Mock(discover_langchain_modules=mock_discover_func)
        }):
            result = await discover_langchain_tools()
            
            assert len(result) == 0
            assert result == []
            mock_discover_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_discover_langchain_tools_module_exception(self):
        """测试discover_langchain_modules抛出异常的情况"""
        mock_discover_func = Mock(side_effect=Exception("模块发现错误"))
        
        with patch('backend.agents.create_agent_info.logger') as mock_logger:
            with patch.dict('sys.modules', {
                'utils.langchain_utils': Mock(discover_langchain_modules=mock_discover_func)
            }):
                result = await discover_langchain_tools()
                
                assert len(result) == 0
                assert result == []
                mock_logger.error.assert_called_once_with("Unexpected error scanning LangChain tools directory: 模块发现错误")

    @pytest.mark.asyncio
    async def test_discover_langchain_tools_processing_exception(self):
        """测试处理单个工具时出错的情况"""
        mock_good_tool = Mock()
        mock_good_tool.name = "good_tool"
        
        # 创建一个访问name属性时会抛出异常的工具
        mock_error_tool = Mock()
        type(mock_error_tool).name = PropertyMock(side_effect=Exception("工具处理错误"))
        
        mock_discover_func = Mock(return_value=[
            (mock_good_tool, "good_tool.py"),
            (mock_error_tool, "error_tool.py")
        ])
        
        with patch('backend.agents.create_agent_info.logger') as mock_logger:
            with patch.dict('sys.modules', {
                'utils.langchain_utils': Mock(discover_langchain_modules=mock_discover_func)
            }):
                result = await discover_langchain_tools()
                
                # 验证结果 - 只有正常的工具被返回
                assert len(result) == 1
                assert result[0] == mock_good_tool
                
                # 验证错误日志被记录
                mock_logger.error.assert_called_once()
                error_call = mock_logger.error.call_args[0][0]
                assert "Error processing LangChain tool from error_tool.py:" in error_call


class TestCreateToolConfigList:
    """测试create_tool_config_list函数"""

    @pytest.mark.asyncio
    async def test_create_tool_config_list_basic(self):
        """测试基本的工具配置列表创建"""
        with patch('backend.agents.create_agent_info.discover_langchain_tools') as mock_discover, \
             patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
             patch('backend.agents.create_agent_info.get_selected_knowledge_list') as mock_knowledge:
            
            # 设置mock返回值
            mock_discover.return_value = []
            mock_search_tools.return_value = [
                {
                    "class_name": "TestTool",
                    "name": "test_tool",
                    "description": "A test tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [{"name": "param1", "default": "value1"}],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_knowledge.return_value = []
            
            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")
            
            assert len(result) == 1
            # 验证ToolConfig被正确调用
            mock_tool_config.assert_called_once_with(
                class_name="TestTool",
                name="test_tool",
                description="A test tool",
                inputs="string",
                output_type="string",
                params={"param1": "value1"},
                source="local",
                usage=None
            )

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_knowledge_base_tool(self):
        """测试包含知识库搜索工具的情况"""
        with patch('backend.agents.create_agent_info.discover_langchain_tools') as mock_discover, \
             patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
             patch('backend.agents.create_agent_info.get_selected_knowledge_list') as mock_knowledge, \
             patch('backend.agents.create_agent_info.elastic_core') as mock_elastic, \
             patch('backend.agents.create_agent_info.get_embedding_model') as mock_embedding:
            
            mock_discover.return_value = []
            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_knowledge.return_value = [
                {"index_name": "knowledge_1"},
                {"index_name": "knowledge_2"}
            ]
            mock_elastic.return_value = "mock_elastic_core"
            mock_embedding.return_value = "mock_embedding_model"
            
            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")
            
            assert len(result) == 1
            # 验证ToolConfig被正确调用，包含知识库元数据
            # 检查最后一次调用是否是KnowledgeBaseSearchTool
            last_call = mock_tool_config.call_args_list[-1]
            assert last_call[1]['class_name'] == "KnowledgeBaseSearchTool"


class TestCreateAgentConfig:
    """测试create_agent_config函数"""

    @pytest.mark.asyncio
    async def test_create_agent_config_basic(self):
        """测试基本的代理配置创建"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
             patch('backend.agents.create_agent_info.query_sub_agents_id_list') as mock_query_sub, \
             patch('backend.agents.create_agent_info.create_tool_config_list') as mock_create_tools, \
             patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
             patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
             patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
             patch('backend.agents.create_agent_info.search_memory_in_levels', new_callable=AsyncMock) as mock_search_memory, \
             patch('backend.agents.create_agent_info.get_selected_knowledge_list') as mock_knowledge, \
             patch('backend.agents.create_agent_info.prepare_prompt_templates') as mock_prepare_templates:
            
            # 设置mock返回值
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_name": "test_model",
                "provide_run_summary": True
            }
            mock_query_sub.return_value = []
            mock_create_tools.return_value = []
            mock_get_template.return_value = {"system_prompt": "{{duty}} {{constraint}} {{few_shots}}"}
            mock_tenant_config.get_app_config.side_effect = ["TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(memory_switch=False),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1"
            )
            mock_knowledge.return_value = []
            mock_prepare_templates.return_value = {"system_prompt": "populated_system_prompt"}
            
            result = await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")
            
            # 验证AgentConfig被正确调用
            mock_agent_config.assert_called_once_with(
                name="test_agent",
                description="test description",
                prompt_templates={"system_prompt": "populated_system_prompt"},
                tools=[],
                max_steps=5,
                model_name="test_model",
                provide_run_summary=True,
                managed_agents=[]
            )

    @pytest.mark.asyncio
    async def test_create_agent_config_with_sub_agents(self):
        """测试包含子代理的代理配置创建"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
             patch('backend.agents.create_agent_info.query_sub_agents_id_list') as mock_query_sub, \
             patch('backend.agents.create_agent_info.create_tool_config_list') as mock_create_tools, \
             patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
             patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
             patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
             patch('backend.agents.create_agent_info.search_memory_in_levels', new_callable=AsyncMock) as mock_search_memory, \
             patch('backend.agents.create_agent_info.get_selected_knowledge_list') as mock_knowledge, \
             patch('backend.agents.create_agent_info.prepare_prompt_templates') as mock_prepare_templates:
            
            # 设置mock返回值
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_name": "test_model",
                "provide_run_summary": True
            }
            mock_query_sub.return_value = ["sub_agent_1"]
            mock_create_tools.return_value = []
            mock_get_template.return_value = {"system_prompt": "{{duty}} {{constraint}} {{few_shots}}"}
            mock_tenant_config.get_app_config.side_effect = ["TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(memory_switch=False),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1"
            )
            mock_knowledge.return_value = []
            mock_prepare_templates.return_value = {"system_prompt": "populated_system_prompt"}
            
            # Mock子代理配置
            mock_sub_agent_config = Mock()
            mock_sub_agent_config.name = "sub_agent"
            
            # 递归调用create_agent_config时返回子代理配置
            with patch('backend.agents.create_agent_info.create_agent_config', return_value=mock_sub_agent_config):
                # 重置mock状态，因为之前的测试可能已经调用了AgentConfig
                mock_agent_config.reset_mock()
                
                result = await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")
                
                # 验证AgentConfig被正确调用，包含子代理
                mock_agent_config.assert_called_once_with(
                    name="test_agent",
                    description="test description",
                    prompt_templates={"system_prompt": "populated_system_prompt"},
                    tools=[],
                    max_steps=5,
                    model_name="test_model",
                    provide_run_summary=True,
                    managed_agents=[mock_sub_agent_config]
                )

    @pytest.mark.asyncio
    async def test_create_agent_config_with_memory(self):
        """测试包含记忆功能的代理配置创建"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
             patch('backend.agents.create_agent_info.query_sub_agents_id_list') as mock_query_sub, \
             patch('backend.agents.create_agent_info.create_tool_config_list') as mock_create_tools, \
             patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
             patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
             patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
             patch('backend.agents.create_agent_info.search_memory_in_levels', new_callable=AsyncMock) as mock_search_memory, \
             patch('backend.agents.create_agent_info.get_selected_knowledge_list') as mock_knowledge, \
             patch('backend.agents.create_agent_info.prepare_prompt_templates') as mock_prepare_templates:
            
            # 设置mock返回值
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_name": "test_model",
                "provide_run_summary": True
            }
            mock_query_sub.return_value = []
            mock_create_tools.return_value = []
            mock_get_template.return_value = {"system_prompt": "{{duty}} {{constraint}} {{few_shots}}"}
            mock_tenant_config.get_app_config.side_effect = ["TestApp", "Test Description"]
            
            # 设置记忆功能开启
            mock_user_config = Mock()
            mock_user_config.memory_switch = True
            mock_user_config.agent_share_option = "always"
            mock_user_config.disable_agent_ids = []
            mock_user_config.disable_user_agent_ids = []
            
            mock_build_memory.return_value = Mock(
                user_config=mock_user_config,
                memory_config={"test": "config"},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1"
            )
            mock_search_memory.return_value = {"results": [{"memory": "test"}]}
            mock_knowledge.return_value = []
            mock_prepare_templates.return_value = {"system_prompt": "populated_system_prompt"}
            
            result = await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")
            
            # 验证记忆搜索被调用
            mock_search_memory.assert_called_once_with(
                query_text="test query",
                memory_config={"test": "config"},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
                memory_levels=["tenant", "agent", "user", "user_agent"]
            )


class TestCreateModelConfigList:
    """测试create_model_config_list函数"""

    @pytest.mark.asyncio
    async def test_create_model_config_list(self):
        """测试模型配置列表创建"""
        with patch('backend.agents.create_agent_info.tenant_config_manager') as mock_manager, \
             patch('backend.agents.create_agent_info.get_model_name_from_config') as mock_get_model_name:
            
            # 设置mock返回值
            mock_manager.get_model_config.side_effect = [
                {
                    "api_key": "main_key",
                    "model_name": "main_model",
                    "base_url": "http://main.url",
                    "is_deep_thinking": True
                },
                {
                    "api_key": "sub_key", 
                    "model_name": "sub_model",
                    "base_url": "http://sub.url",
                    "is_deep_thinking": False
                }
            ]
            
            mock_get_model_name.side_effect = ["main_model_name", "sub_model_name"]
            
            result = await create_model_config_list("tenant_1")
            
            assert len(result) == 2
            # 验证ModelConfig被正确调用两次
            assert mock_model_config.call_count == 2


class TestFilterMcpServersAndTools:
    """测试filter_mcp_servers_and_tools函数"""

    def test_filter_mcp_servers_with_mcp_tools(self):
        """测试包含MCP工具时的过滤逻辑"""
        # 创建mock对象
        mock_tool = Mock()
        mock_tool.source = "mcp"
        mock_tool.usage = "test_server"
        
        mock_agent_config = Mock()
        mock_agent_config.tools = [mock_tool]
        mock_agent_config.managed_agents = []
        
        mcp_info_dict = {
            "test_server": {
                "remote_mcp_server": "http://test.server"
            }
        }
        
        # 执行函数
        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)
        
        # 验证结果
        assert result == ["http://test.server"]

    def test_filter_mcp_servers_no_mcp_tools(self):
        """测试不包含MCP工具时的过滤逻辑"""
        mock_tool = Mock()
        mock_tool.source = "local"
        
        mock_agent_config = Mock()
        mock_agent_config.tools = [mock_tool]
        mock_agent_config.managed_agents = []
        
        mcp_info_dict = {}
        
        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)
        
        # 没有MCP工具，应该返回空列表
        assert result == []

    def test_filter_mcp_servers_with_sub_agents(self):
        """测试包含子代理时的过滤逻辑"""
        # 创建子代理的mock工具
        mock_sub_tool = Mock()
        mock_sub_tool.source = "mcp"
        mock_sub_tool.usage = "sub_server"
        
        mock_sub_agent = Mock()
        mock_sub_agent.tools = [mock_sub_tool]
        mock_sub_agent.managed_agents = []
        
        # 创建主代理的mock工具
        mock_main_tool = Mock()
        mock_main_tool.source = "mcp"
        mock_main_tool.usage = "main_server"
        
        mock_agent_config = Mock()
        mock_agent_config.tools = [mock_main_tool]
        mock_agent_config.managed_agents = [mock_sub_agent]
        
        mcp_info_dict = {
            "main_server": {
                "remote_mcp_server": "http://main.server"
            },
            "sub_server": {
                "remote_mcp_server": "http://sub.server"
            }
        }
        
        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)
        
        # 应该包含两个服务器的URL
        assert len(result) == 2
        assert "http://main.server" in result
        assert "http://sub.server" in result

    def test_filter_mcp_servers_unknown_server(self):
        """测试未知MCP服务器的情况"""
        mock_tool = Mock()
        mock_tool.source = "mcp"
        mock_tool.usage = "unknown_server"
        
        mock_agent_config = Mock()
        mock_agent_config.tools = [mock_tool]
        mock_agent_config.managed_agents = []
        
        mcp_info_dict = {
            "different_server": {
                "remote_mcp_server": "http://different.server"
            }
        }
        
        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)
        
        # 未知服务器不应该被包含
        assert result == []


class TestCreateAgentRunInfo:
    """测试create_agent_run_info函数"""

    @pytest.mark.asyncio
    async def test_create_agent_run_info_success(self):
        """测试成功创建agent运行信息"""
        with patch('backend.agents.create_agent_info.get_current_user_id') as mock_get_user, \
             patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
             patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
             patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
             patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
             patch('backend.agents.create_agent_info.config_manager') as mock_config, \
             patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
             patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
             patch('backend.agents.create_agent_info.threading') as mock_threading:
            
            # 设置mock返回值
            mock_get_user.return_value = ("user_1", "tenant_1")
            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = [
                {
                    "remote_mcp_server_name": "test_server",
                    "remote_mcp_server": "http://test.server",
                    "status": True
                }
            ]
            mock_create_agent.return_value = "agent_config"
            mock_config.get_config.return_value = "http://nexent.mcp"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = ["http://test.server"]
            mock_threading.Event.return_value = "stop_event"
            
            result = await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                authorization="Bearer token",
                language="zh"
            )
            
            # 验证AgentRunInfo被正确调用
            mock_agent_run_info.assert_called_once_with(
                query="processed_query",
                model_config_list=["model_config"],
                observer=mock_message_observer.return_value,
                agent_config="agent_config",
                mcp_host=["http://test.server"],
                history=[],
                stop_event="stop_event"
            )
            
            # 验证其他函数被正确调用
            mock_get_user.assert_called_once_with("Bearer token")
            mock_join_query.assert_called_once_with(minio_files=[], query="test query")
            mock_create_models.assert_called_once_with("tenant_1")
            mock_create_agent.assert_called_once_with(
                agent_id="agent_1",
                tenant_id="tenant_1", 
                user_id="user_1",
                language="zh",
                last_user_query="processed_query"
            )
            mock_get_mcp.assert_called_once_with(tenant_id="tenant_1")
            mock_filter.assert_called_once_with("agent_config", {
                "test_server": {
                    "remote_mcp_server_name": "test_server",
                    "remote_mcp_server": "http://test.server",
                    "status": True
                },
                "nexent": {
                    "remote_mcp_server_name": "nexent",
                    "remote_mcp_server": "http://nexent.mcp/sse",
                    "status": True
                }
            })


class TestJoinMinioFileDescriptionToQuery:
    """测试join_minio_file_description_to_query函数"""

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_with_files(self):
        """测试包含文件描述的情况"""
        minio_files = [
            {"description": "File 1 description"},
            {"description": "File 2 description"},
            {"no_description": "should be ignored"}
        ]
        query = "test query"
        
        result = await join_minio_file_description_to_query(minio_files, query)
        
        expected = "User provided some reference files:\nFile 1 description\nFile 2 description\n\nUser wants to answer questions based on the above information: test query"
        assert result == expected

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_no_files(self):
        """测试没有文件的情况"""
        minio_files = []
        query = "test query"
        
        result = await join_minio_file_description_to_query(minio_files, query)
        
        assert result == "test query"

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_none_files(self):
        """测试文件为None的情况"""
        minio_files = None
        query = "test query"
        
        result = await join_minio_file_description_to_query(minio_files, query)
        
        assert result == "test query"

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_no_descriptions(self):
        """测试文件没有描述的情况"""
        minio_files = [
            {"no_description": "should be ignored"},
            {"another_field": "also ignored"}
        ]
        query = "test query"
        
        result = await join_minio_file_description_to_query(minio_files, query)
        
        assert result == "test query"


class TestPreparePromptTemplates:
    """测试prepare_prompt_templates函数"""

    @pytest.mark.asyncio
    async def test_prepare_prompt_templates_manager_zh(self):
        """测试管理器模式中文提示模板"""
        with patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template:
            
            mock_get_template.return_value = {"test": "template"}
            
            result = await prepare_prompt_templates(True, "test system prompt", "zh")
            
            mock_get_template.assert_called_once_with(True, "zh")
            assert result["system_prompt"] == "test system prompt"
            assert result["test"] == "template"

    @pytest.mark.asyncio
    async def test_prepare_prompt_templates_worker_en(self):
        """测试工作模式英文提示模板"""
        with patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template:
            
            mock_get_template.return_value = {"test": "template"}
            
            result = await prepare_prompt_templates(False, "test system prompt", "en")
            
            mock_get_template.assert_called_once_with(False, "en")
            assert result["system_prompt"] == "test system prompt"
            assert result["test"] == "template"


if __name__ == "__main__":
    pytest.main([__file__])
