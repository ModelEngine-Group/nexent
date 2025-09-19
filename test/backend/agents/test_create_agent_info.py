import pytest
import sys
from unittest.mock import AsyncMock, MagicMock, patch, Mock, PropertyMock

# Mock consts module first to avoid ModuleNotFoundError
consts_mock = MagicMock()
consts_mock.const = MagicMock()
# Set required constants in consts.const
consts_mock.const.MINIO_ENDPOINT = "http://localhost:9000"
consts_mock.const.MINIO_ACCESS_KEY = "test_access_key"
consts_mock.const.MINIO_SECRET_KEY = "test_secret_key"
consts_mock.const.MINIO_REGION = "us-east-1"
consts_mock.const.MINIO_DEFAULT_BUCKET = "test-bucket"
consts_mock.const.POSTGRES_HOST = "localhost"
consts_mock.const.POSTGRES_USER = "test_user"
consts_mock.const.NEXENT_POSTGRES_PASSWORD = "test_password"
consts_mock.const.POSTGRES_DB = "test_db"
consts_mock.const.POSTGRES_PORT = 5432
consts_mock.const.DEFAULT_TENANT_ID = "default_tenant"
consts_mock.const.LOCAL_MCP_SERVER = "http://localhost:5011"
consts_mock.const.MODEL_CONFIG_MAPPING = {"llm": "llm_config"}
consts_mock.const.LANGUAGE = {"ZH": "zh"}

# Add the mocked consts module to sys.modules
sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const

# Mock utils module
utils_mock = MagicMock()
utils_mock.auth_utils = MagicMock()
utils_mock.auth_utils.get_current_user_id = MagicMock(return_value=("test_user_id", "test_tenant_id"))

# Add the mocked utils module to sys.modules
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_mock.auth_utils

# Provide a stub for the `boto3` module so that it can be imported safely even
# if the testing environment does not have it available.
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Mock the entire client module
client_mock = MagicMock()
client_mock.MinioClient = MagicMock()
client_mock.PostgresClient = MagicMock()
client_mock.db_client = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()

# Add the mocked client module to sys.modules
sys.modules['backend.database.client'] = client_mock

# Mock external dependencies before imports
sys.modules['nexent.core.utils.observer'] = MagicMock()
sys.modules['nexent.core.agents.agent_model'] = MagicMock()
sys.modules['smolagents.agents'] = MagicMock()
sys.modules['smolagents.utils'] = MagicMock()
sys.modules['services.remote_mcp_service'] = MagicMock()
sys.modules['database.agent_db'] = MagicMock()
sys.modules['database.tool_db'] = MagicMock()
sys.modules['database.model_management_db'] = MagicMock()
sys.modules['services.elasticsearch_service'] = MagicMock()
sys.modules['services.tenant_config_service'] = MagicMock()
sys.modules['utils.prompt_template_utils'] = MagicMock()
sys.modules['utils.config_utils'] = MagicMock()
sys.modules['utils.langchain_utils'] = MagicMock()
sys.modules['utils.model_name_utils'] = MagicMock()
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

# Import constants for testing
from consts.const import MODEL_CONFIG_MAPPING


class TestDiscoverLangchainTools:
    """Tests for the discover_langchain_tools function"""

    @pytest.mark.asyncio
    async def test_discover_langchain_tools_success(self):
        """Test case for successfully discovering LangChain tools"""
        # Prepare test data
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
                # Execute the test
                result = await discover_langchain_tools()

                # Verify the results
                assert len(result) == 2
                assert result[0] == mock_tool1
                assert result[1] == mock_tool2

                # Verify calls
                mock_discover_func.assert_called_once()
                assert mock_logger.info.call_count == 2
                mock_logger.info.assert_any_call(
                    "Loaded LangChain tool 'test_tool1' from tool1.py")
                mock_logger.info.assert_any_call(
                    "Loaded LangChain tool 'test_tool2' from tool2.py")

    @pytest.mark.asyncio
    async def test_discover_langchain_tools_empty(self):
        """Test case for when no tools are discovered"""
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
        """Test case for when discover_langchain_modules throws an exception"""
        mock_discover_func = Mock(side_effect=Exception("模块发现错误"))

        with patch('backend.agents.create_agent_info.logger') as mock_logger:
            with patch.dict('sys.modules', {
                'utils.langchain_utils': Mock(discover_langchain_modules=mock_discover_func)
            }):
                result = await discover_langchain_tools()

                assert len(result) == 0
                assert result == []
                mock_logger.error.assert_called_once_with(
                    "Unexpected error scanning LangChain tools directory: 模块发现错误")

    @pytest.mark.asyncio
    async def test_discover_langchain_tools_processing_exception(self):
        """Test case for when an error occurs while processing a single tool"""
        mock_good_tool = Mock()
        mock_good_tool.name = "good_tool"

        # Create a tool that throws an exception when accessing the name attribute
        mock_error_tool = Mock()
        type(mock_error_tool).name = PropertyMock(
            side_effect=Exception("工具处理错误"))

        mock_discover_func = Mock(return_value=[
            (mock_good_tool, "good_tool.py"),
            (mock_error_tool, "error_tool.py")
        ])

        with patch('backend.agents.create_agent_info.logger') as mock_logger:
            with patch.dict('sys.modules', {
                'utils.langchain_utils': Mock(discover_langchain_modules=mock_discover_func)
            }):
                result = await discover_langchain_tools()

                # Verify the results - only the valid tool should be returned
                assert len(result) == 1
                assert result[0] == mock_good_tool

                # Verify that the error was logged
                mock_logger.error.assert_called_once()
                error_call = mock_logger.error.call_args[0][0]
                assert "Error processing LangChain tool from error_tool.py:" in error_call


class TestCreateToolConfigList:
    """Tests for the create_tool_config_list function"""

    @pytest.mark.asyncio
    async def test_create_tool_config_list_basic(self):
        """Test case for basic tool configuration list creation"""
        with patch('backend.agents.create_agent_info.discover_langchain_tools') as mock_discover, \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_selected_knowledge_list') as mock_knowledge:

            # Set mock return values
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
            # Verify that ToolConfig was called correctly
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
        """Test case including the knowledge base search tool"""
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
            # Verify that ToolConfig was called correctly, including knowledge base metadata
            # Check if the last call was for KnowledgeBaseSearchTool
            last_call = mock_tool_config.call_args_list[-1]
            assert last_call[1]['class_name'] == "KnowledgeBaseSearchTool"


class TestCreateAgentConfig:
    """Tests for the create_agent_config function"""

    @pytest.mark.asyncio
    async def test_create_agent_config_basic(self):
        """Test case for basic agent configuration creation"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agents_id_list') as mock_query_sub, \
                patch('backend.agents.create_agent_info.create_tool_config_list') as mock_create_tools, \
                patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
                patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
                patch('backend.agents.create_agent_info.get_selected_knowledge_list') as mock_knowledge, \
                patch('backend.agents.create_agent_info.prepare_prompt_templates') as mock_prepare_templates:

            # Set mock return values
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
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"}
            mock_tenant_config.get_app_config.side_effect = [
                "TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(memory_switch=False),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1"
            )
            mock_knowledge.return_value = []
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"}

            result = await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")

            # Verify that AgentConfig was called correctly
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
        """Test case for creating agent configuration with sub-agents"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agents_id_list') as mock_query_sub, \
                patch('backend.agents.create_agent_info.create_tool_config_list') as mock_create_tools, \
                patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
                patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
                patch('backend.agents.create_agent_info.search_memory_in_levels', new_callable=AsyncMock) as mock_search_memory, \
                patch('backend.agents.create_agent_info.get_selected_knowledge_list') as mock_knowledge, \
                patch('backend.agents.create_agent_info.prepare_prompt_templates') as mock_prepare_templates:

            # Set mock return values
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
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"}
            mock_tenant_config.get_app_config.side_effect = [
                "TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(memory_switch=False),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1"
            )
            mock_knowledge.return_value = []
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"}

            # Mock sub-agent configuration
            mock_sub_agent_config = Mock()
            mock_sub_agent_config.name = "sub_agent"

            # Return sub-agent config on recursive call to create_agent_config
            with patch('backend.agents.create_agent_info.create_agent_config', return_value=mock_sub_agent_config):
                # Reset mock state, as previous tests might have called AgentConfig
                mock_agent_config.reset_mock()

                result = await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")

                # Verify that AgentConfig was called correctly, including sub-agents
                mock_agent_config.assert_called_once_with(
                    name="test_agent",
                    description="test description",
                    prompt_templates={
                        "system_prompt": "populated_system_prompt"},
                    tools=[],
                    max_steps=5,
                    model_name="test_model",
                    provide_run_summary=True,
                    managed_agents=[mock_sub_agent_config]
                )

    @pytest.mark.asyncio
    async def test_create_agent_config_with_memory(self):
        """Test case for creating agent configuration with memory"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agents_id_list') as mock_query_sub, \
                patch('backend.agents.create_agent_info.create_tool_config_list') as mock_create_tools, \
                patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
                patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
                patch('backend.agents.create_agent_info.search_memory_in_levels', new_callable=AsyncMock) as mock_search_memory, \
                patch('backend.agents.create_agent_info.get_selected_knowledge_list') as mock_knowledge, \
                patch('backend.agents.create_agent_info.prepare_prompt_templates') as mock_prepare_templates:

            # Set mock return values
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
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"}
            mock_tenant_config.get_app_config.side_effect = [
                "TestApp", "Test Description"]

            # Enable memory feature
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
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"}

            result = await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")

            # Verify that memory search was called
            mock_search_memory.assert_called_once_with(
                query_text="test query",
                memory_config={"test": "config"},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
                memory_levels=["tenant", "agent", "user", "user_agent"]
            )

    @pytest.mark.asyncio
    async def test_create_agent_config_memory_disabled_no_search(self):
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agents_id_list"
            ) as mock_query_sub,
            patch(
                "backend.agents.create_agent_info.create_tool_config_list"
            ) as mock_create_tools,
            patch(
                "backend.agents.create_agent_info.get_agent_prompt_template"
            ) as mock_get_template,
            patch(
                "backend.agents.create_agent_info.tenant_config_manager"
            ) as mock_tenant_config,
            patch(
                "backend.agents.create_agent_info.build_memory_context"
            ) as mock_build_memory,
            patch(
                "backend.agents.create_agent_info.search_memory_in_levels",
                new_callable=AsyncMock,
            ) as mock_search_memory,
            patch(
                "backend.agents.create_agent_info.get_selected_knowledge_list"
            ) as mock_knowledge,
            patch(
                "backend.agents.create_agent_info.prepare_prompt_templates"
            ) as mock_prepare_templates,
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_name": "test_model",
                "provide_run_summary": True,
            }
            mock_query_sub.return_value = []
            mock_create_tools.return_value = []
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"
            }
            mock_tenant_config.get_app_config.side_effect = [
                "TestApp",
                "Test Description",
            ]

            # memory_switch is on, but search is disabled
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
                agent_id="agent_1",
            )

            mock_knowledge.return_value = []
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"
            }

            await create_agent_config(
                "agent_1",
                "tenant_1",
                "user_1",
                "zh",
                "test query",
                allow_memory_search=False,
            )

            mock_search_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_agent_config_memory_exception(self):
        """raise when search_memory_in_levels raises an exception"""
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agents_id_list"
            ) as mock_query_sub,
            patch(
                "backend.agents.create_agent_info.create_tool_config_list"
            ) as mock_create_tools,
            patch(
                "backend.agents.create_agent_info.get_agent_prompt_template"
            ) as mock_get_template,
            patch(
                "backend.agents.create_agent_info.tenant_config_manager"
            ) as mock_tenant_config,
            patch(
                "backend.agents.create_agent_info.build_memory_context"
            ) as mock_build_memory,
            patch(
                "backend.agents.create_agent_info.search_memory_in_levels",
                new_callable=AsyncMock,
            ) as mock_search_memory,
            patch(
                "backend.agents.create_agent_info.get_selected_knowledge_list"
            ) as mock_knowledge,
            patch(
                "backend.agents.create_agent_info.prepare_prompt_templates"
            ) as mock_prepare_templates,
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_name": "test_model",
                "provide_run_summary": True,
            }
            mock_query_sub.return_value = []
            mock_create_tools.return_value = []
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"
            }
            mock_tenant_config.get_app_config.side_effect = [
                "TestApp",
                "Test Description",
            ]

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
                agent_id="agent_1",
            )

            mock_search_memory.side_effect = Exception("boom")
            mock_knowledge.return_value = []
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"
            }

            with pytest.raises(Exception) as excinfo:
                await create_agent_config(
                    "agent_1",
                    "tenant_1",
                    "user_1",
                    "zh",
                    "test query",
                    allow_memory_search=True,
                )

            assert "Failed to retrieve memory list: boom" in str(excinfo.value)


class TestCreateModelConfigList:
    """Tests for the create_model_config_list function"""

    @pytest.mark.asyncio
    async def test_create_model_config_list(self):
        """Test case for model configuration list creation"""
        # Reset mock call count before test
        mock_model_config.reset_mock()
        
        with patch('backend.agents.create_agent_info.get_model_records') as mock_get_records, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_manager, \
                patch('backend.agents.create_agent_info.get_model_name_from_config') as mock_get_model_name, \
                patch('backend.agents.create_agent_info.add_repo_to_name') as mock_add_repo:

            # Mock database records
            mock_get_records.return_value = [
                {
                    "display_name": "GPT-4",
                    "api_key": "gpt4_key",
                    "model_repo": "openai",
                    "model_name": "gpt-4",
                    "base_url": "https://api.openai.com"
                },
                {
                    "display_name": "Claude",
                    "api_key": "claude_key", 
                    "model_repo": "anthropic",
                    "model_name": "claude-3",
                    "base_url": "https://api.anthropic.com"
                }
            ]

            # Mock tenant config for main_model and sub_model
            mock_manager.get_model_config.return_value = {
                "api_key": "main_key",
                "model_name": "main_model",
                "base_url": "http://main.url"
            }

            # Mock utility functions
            mock_add_repo.side_effect = ["openai/gpt-4", "anthropic/claude-3"]
            mock_get_model_name.return_value = "main_model_name"

            result = await create_model_config_list("tenant_1")

            # Should have 4 models: 2 from database + 2 default (main_model, sub_model)
            assert len(result) == 4
            
            # Verify get_model_records was called correctly
            mock_get_records.assert_called_once_with({"model_type": "llm"}, "tenant_1")
            
            # Verify tenant_config_manager was called for default models
            mock_manager.get_model_config.assert_called_once_with(
                key=MODEL_CONFIG_MAPPING["llm"], tenant_id="tenant_1")
            
            # Verify ModelConfig was called 4 times
            assert mock_model_config.call_count == 4
            
            # Verify the calls to ModelConfig
            calls = mock_model_config.call_args_list
            
            # First call: GPT-4 model from database
            assert calls[0][1]['cite_name'] == "GPT-4"
            assert calls[0][1]['api_key'] == "gpt4_key"
            assert calls[0][1]['model_name'] == "openai/gpt-4"
            assert calls[0][1]['url'] == "https://api.openai.com"
            
            # Second call: Claude model from database
            assert calls[1][1]['cite_name'] == "Claude"
            assert calls[1][1]['api_key'] == "claude_key"
            assert calls[1][1]['model_name'] == "anthropic/claude-3"
            assert calls[1][1]['url'] == "https://api.anthropic.com"
            
            # Third call: main_model
            assert calls[2][1]['cite_name'] == "main_model"
            assert calls[2][1]['api_key'] == "main_key"
            assert calls[2][1]['model_name'] == "main_model_name"
            assert calls[2][1]['url'] == "http://main.url"
            
            # Fourth call: sub_model
            assert calls[3][1]['cite_name'] == "sub_model"
            assert calls[3][1]['api_key'] == "main_key"
            assert calls[3][1]['model_name'] == "main_model_name"
            assert calls[3][1]['url'] == "http://main.url"

    @pytest.mark.asyncio
    async def test_create_model_config_list_empty_database(self):
        """Test case when database returns no records"""
        # Reset mock call count before test
        mock_model_config.reset_mock()
        
        with patch('backend.agents.create_agent_info.get_model_records') as mock_get_records, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_manager, \
                patch('backend.agents.create_agent_info.get_model_name_from_config') as mock_get_model_name:

            # Mock empty database records
            mock_get_records.return_value = []

            # Mock tenant config for main_model and sub_model
            mock_manager.get_model_config.return_value = {
                "api_key": "main_key",
                "model_name": "main_model",
                "base_url": "http://main.url"
            }

            mock_get_model_name.return_value = "main_model_name"

            result = await create_model_config_list("tenant_1")

            # Should have 2 models: only default models (main_model, sub_model)
            assert len(result) == 2
            
            # Verify ModelConfig was called 2 times
            assert mock_model_config.call_count == 2
            
            # Verify both calls are for default models
            calls = mock_model_config.call_args_list
            assert calls[0][1]['cite_name'] == "main_model"
            assert calls[1][1]['cite_name'] == "sub_model"

    @pytest.mark.asyncio
    async def test_create_model_config_list_no_model_name_in_config(self):
        """Test case when tenant config has no model_name"""
        # Reset mock call count before test
        mock_model_config.reset_mock()
        
        with patch('backend.agents.create_agent_info.get_model_records') as mock_get_records, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_manager, \
                patch('backend.agents.create_agent_info.get_model_name_from_config') as mock_get_model_name:

            # Mock empty database records
            mock_get_records.return_value = []

            # Mock tenant config without model_name
            mock_manager.get_model_config.return_value = {
                "api_key": "main_key",
                "base_url": "http://main.url"
                # No model_name field
            }

            result = await create_model_config_list("tenant_1")

            # Should have 2 models: only default models (main_model, sub_model)
            assert len(result) == 2
            
            # Verify ModelConfig was called 2 times with empty model_name
            assert mock_model_config.call_count == 2
            
            calls = mock_model_config.call_args_list
            assert calls[0][1]['cite_name'] == "main_model"
            assert calls[0][1]['model_name'] == ""  # Should be empty when no model_name in config
            assert calls[1][1]['cite_name'] == "sub_model"
            assert calls[1][1]['model_name'] == ""  # Should be empty when no model_name in config


class TestFilterMcpServersAndTools:
    """Tests for the filter_mcp_servers_and_tools function"""

    def test_filter_mcp_servers_with_mcp_tools(self):
        """Test case for filtering logic when MCP tools are present"""
        # Create mock objects
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

        # Execute the function
        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)

        # Verify the result
        assert result == ["http://test.server"]

    def test_filter_mcp_servers_no_mcp_tools(self):
        """Test case for filtering logic when no MCP tools are present"""
        mock_tool = Mock()
        mock_tool.source = "local"

        mock_agent_config = Mock()
        mock_agent_config.tools = [mock_tool]
        mock_agent_config.managed_agents = []

        mcp_info_dict = {}

        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)

        # Should return an empty list if there are no MCP tools
        assert result == []

    def test_filter_mcp_servers_with_sub_agents(self):
        """Test case for filtering logic with sub-agents"""
        # Create mock tool for the sub-agent
        mock_sub_tool = Mock()
        mock_sub_tool.source = "mcp"
        mock_sub_tool.usage = "sub_server"

        mock_sub_agent = Mock()
        mock_sub_agent.tools = [mock_sub_tool]
        mock_sub_agent.managed_agents = []

        # Create mock tool for the main agent
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

        # Should contain the URLs of both servers
        assert len(result) == 2
        assert "http://main.server" in result
        assert "http://sub.server" in result

    def test_filter_mcp_servers_unknown_server(self):
        """Test case for an unknown MCP server"""
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

        # Unknown servers should not be included
        assert result == []


class TestCreateAgentRunInfo:
    """Tests for the create_agent_run_info function"""

    @pytest.mark.asyncio
    async def test_create_agent_run_info_success(self):
        """Test case for successfully creating agent run info"""
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading:

            # Set mock return values
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
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = ["http://test.server"]
            mock_threading.Event.return_value = "stop_event"

            result = await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh"
            )

            # Verify that AgentRunInfo was called correctly
            mock_agent_run_info.assert_called_once_with(
                query="processed_query",
                model_config_list=["model_config"],
                observer=mock_message_observer.return_value,
                agent_config="agent_config",
                mcp_host=["http://test.server"],
                history=[],
                stop_event="stop_event"
            )

            # Verify that other functions were called correctly
            mock_join_query.assert_called_once_with(
                minio_files=[], query="test query")
            mock_create_models.assert_called_once_with("tenant_1")
            mock_create_agent.assert_called_once_with(
                agent_id="agent_1",
                tenant_id="tenant_1",
                user_id="user_1",
                language="zh",
                last_user_query="processed_query",
                allow_memory_search=True,
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

    @pytest.mark.asyncio
    async def test_create_agent_run_info_forwards_allow_memory_false(self):
        with (
            patch(
                "backend.agents.create_agent_info.join_minio_file_description_to_query"
            ) as mock_join_query,
            patch(
                "backend.agents.create_agent_info.create_model_config_list"
            ) as mock_create_models,
            patch(
                "backend.agents.create_agent_info.get_remote_mcp_server_list",
                new_callable=AsyncMock,
            ) as mock_get_mcp,
            patch(
                "backend.agents.create_agent_info.create_agent_config"
            ) as mock_create_agent,
            patch(
                "backend.agents.create_agent_info.filter_mcp_servers_and_tools"
            ) as mock_filter,
            patch("backend.agents.create_agent_info.urljoin") as mock_urljoin,
            patch("backend.agents.create_agent_info.threading") as mock_threading,
        ):
            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = []
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = []
            mock_threading.Event.return_value = "stop_event"

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                tenant_id="tenant_1",
                user_id="user_1",
                language="zh",
                allow_memory_search=False,
            )

            mock_create_agent.assert_called_once_with(
                agent_id="agent_1",
                tenant_id="tenant_1",
                user_id="user_1",
                language="zh",
                last_user_query="processed_query",
                allow_memory_search=False,
            )


class TestJoinMinioFileDescriptionToQuery:
    """Tests for the join_minio_file_description_to_query function"""

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_with_files(self):
        """Test case with file descriptions"""
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
        """Test case with no files"""
        minio_files = []
        query = "test query"

        result = await join_minio_file_description_to_query(minio_files, query)

        assert result == "test query"

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_none_files(self):
        """Test case when files are None"""
        minio_files = None
        query = "test query"

        result = await join_minio_file_description_to_query(minio_files, query)

        assert result == "test query"

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_no_descriptions(self):
        """Test case when files have no descriptions"""
        minio_files = [
            {"no_description": "should be ignored"},
            {"another_field": "also ignored"}
        ]
        query = "test query"

        result = await join_minio_file_description_to_query(minio_files, query)

        assert result == "test query"


class TestPreparePromptTemplates:
    """Tests for the prepare_prompt_templates function"""

    @pytest.mark.asyncio
    async def test_prepare_prompt_templates_manager_zh(self):
        """Test case for manager mode Chinese prompt templates"""
        with patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template:

            mock_get_template.return_value = {"test": "template"}

            result = await prepare_prompt_templates(True, "test system prompt", "zh")

            mock_get_template.assert_called_once_with(True, "zh")
            assert result["system_prompt"] == "test system prompt"
            assert result["test"] == "template"

    @pytest.mark.asyncio
    async def test_prepare_prompt_templates_worker_en(self):
        """Test case for worker mode English prompt templates"""
        with patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template:

            mock_get_template.return_value = {"test": "template"}

            result = await prepare_prompt_templates(False, "test system prompt", "en")

            mock_get_template.assert_called_once_with(False, "en")
            assert result["system_prompt"] == "test system prompt"
            assert result["test"] == "template"


if __name__ == "__main__":
    pytest.main([__file__])
