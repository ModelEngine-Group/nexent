from fastapi import Request
from consts.model import ExportAndImportAgentInfo, ExportAndImportDataFormat, MCPInfo, AgentRequest
import sys
import asyncio
import json
from unittest.mock import patch, MagicMock, mock_open, call, Mock, AsyncMock

import pytest
from fastapi.responses import StreamingResponse

# Import the actual ToolConfig model for testing before any mocking
from nexent.core.agents.agent_model import ToolConfig

# Mock boto3 before importing the module under test
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Mock Elasticsearch
elasticsearch_client_mock = MagicMock()
patch('elasticsearch._sync.client.Elasticsearch',
      return_value=elasticsearch_client_mock).start()
patch('elasticsearch.Elasticsearch',
      return_value=elasticsearch_client_mock).start()

# Mock ElasticSearchCore
elasticsearch_core_mock = MagicMock()
patch('sdk.nexent.vector_database.elasticsearch_core.ElasticSearchCore',
      return_value=elasticsearch_core_mock).start()


# Mock memory-related modules
nexent_mock = MagicMock()
sys.modules['nexent'] = nexent_mock
sys.modules['nexent.core'] = MagicMock()
sys.modules['nexent.core.agents'] = MagicMock()
# Don't mock agent_model yet, we need to import ToolConfig first
sys.modules['nexent.memory'] = MagicMock()
sys.modules['nexent.memory.memory_service'] = MagicMock()

# Mock other dependencies
sys.modules['agents'] = MagicMock()
sys.modules['agents.create_agent_info'] = MagicMock()
sys.modules['database'] = MagicMock()
sys.modules['database.agent_db'] = MagicMock()
sys.modules['database.tool_db'] = MagicMock()
sys.modules['database.remote_mcp_db'] = MagicMock()
sys.modules['services'] = MagicMock()
sys.modules['services.remote_mcp_service'] = MagicMock()
sys.modules['services.tool_configuration_service'] = MagicMock()
sys.modules['services.conversation_management_service'] = MagicMock()
sys.modules['services.memory_config_service'] = MagicMock()
sys.modules['utils'] = MagicMock()
sys.modules['utils.auth_utils'] = MagicMock()
sys.modules['utils.memory_utils'] = MagicMock()
sys.modules['utils.thread_utils'] = MagicMock()
sys.modules['agents.agent_run_manager'] = MagicMock()
sys.modules['agents.preprocess_manager'] = MagicMock()
sys.modules['nexent.core.agents.run_agent'] = MagicMock()

from backend.services.agent_service import (
    get_agent_call_relationship_impl,
    delete_agent_impl,
    export_agent_impl,
    export_agent_by_agent_id,
    import_agent_by_agent_id,
    insert_related_agent_impl,
    load_default_agents_json_file,
    clear_agent_memory,
    import_agent_impl,
    get_agent_id_by_name,
    save_messages,
    prepare_agent_run,
    run_agent_stream,
    stop_agent_tasks,
)
from backend.services.agent_service import get_enable_tool_id_by_agent_id
from backend.services.agent_service import get_creating_sub_agent_id_service
from backend.services.agent_service import get_agent_info_impl
from backend.services.agent_service import list_all_agent_info_impl
from backend.services.agent_service import get_creating_sub_agent_info_impl
from backend.services.agent_service import update_agent_info_impl

original_agent_model = sys.modules['nexent.core.agents.agent_model']
sys.modules['nexent.core.agents.agent_model'] = MagicMock()

# Mock specific classes that might be imported
MemoryContext = MagicMock()
MemoryUserConfig = MagicMock()
sys.modules['nexent.core.agents.agent_model'].MemoryContext = MemoryContext
sys.modules['nexent.core.agents.agent_model'].MemoryUserConfig = MemoryUserConfig
sys.modules['nexent.core.agents.agent_model'].ToolConfig = ToolConfig


# Setup and teardown for each test
@pytest.fixture(autouse=True)
def reset_mocks():
    """Reset all mocks before each test to ensure a clean test environment."""
    yield


@pytest.mark.asyncio
async def test_get_enable_tool_id_by_agent_id():
    """
    Test the function that retrieves enabled tool IDs for a specific agent.

    This test verifies that:
    1. The function correctly filters and returns only enabled tool IDs
    2. The underlying query function is called with correct parameters
    """
    # Setup
    mock_tool_instances = [
        {"tool_id": 1, "enabled": True},
        {"tool_id": 2, "enabled": False},
        {"tool_id": 3, "enabled": True},
        {"tool_id": 4, "enabled": True}
    ]

    with patch('backend.services.agent_service.query_all_enabled_tool_instances') as mock_query:
        mock_query.return_value = mock_tool_instances

        # Execute
        result = get_enable_tool_id_by_agent_id(
            agent_id=123,
            tenant_id="test_tenant"
        )

        # Assert
        assert sorted(result) == [1, 3, 4]
        mock_query.assert_called_once_with(
            agent_id=123,
            tenant_id="test_tenant"
        )


@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.search_blank_sub_agent_by_main_agent_id')
@pytest.mark.asyncio
async def test_get_creating_sub_agent_id_service_existing_agent(mock_search, mock_create):
    """
    Test retrieving an existing sub-agent ID associated with a main agent.

    This test verifies that when a sub-agent already exists for a main agent:
    1. The function returns the existing sub-agent ID
    2. No new agent is created (create_agent is not called)
    """
    # Setup - existing sub agent found
    mock_search.return_value = 456

    # Execute
    result = await get_creating_sub_agent_id_service(
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert
    assert result == 456
    mock_search.assert_called_once_with(tenant_id="test_tenant")
    mock_create.assert_not_called()


@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.search_blank_sub_agent_by_main_agent_id')
@pytest.mark.asyncio
async def test_get_creating_sub_agent_id_service_new_agent(mock_search, mock_create):
    """
    Test creating a new sub-agent when none exists for a main agent.

    This test verifies that when no sub-agent exists for a main agent:
    1. A new agent is created with appropriate parameters
    2. The function returns the newly created agent's ID
    """
    # Setup - no existing sub agent found
    mock_search.return_value = None
    mock_create.return_value = {"agent_id": 789}

    # Execute
    result = await get_creating_sub_agent_id_service(
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert
    assert result == 789
    mock_search.assert_called_once_with(tenant_id="test_tenant")
    mock_create.assert_called_once_with(
        agent_info={"enabled": False},
        tenant_id="test_tenant",
        user_id="test_user"
    )


@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_get_agent_info_impl_success(mock_search_agent_info, mock_search_tools, mock_query_sub_agents_id):
    """
    Test successful retrieval of an agent's information by ID.

    This test verifies that:
    1. The function correctly retrieves the agent's basic information
    2. It fetches the associated tools
    3. It gets the sub-agent ID list
    4. It returns a complete agent information structure
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_name": "gpt-4",
        "business_description": "Test agent"
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1"}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [456, 789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_name": "gpt-4",
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids
    }
    assert result == expected_result
    mock_search_agent_info.assert_called_once_with(123, "test_tenant")
    mock_search_tools.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant")
    mock_query_sub_agents_id.assert_called_once_with(
        main_agent_id=123, tenant_id="test_tenant")


@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.get_enable_tool_id_by_agent_id')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@patch('backend.services.agent_service.get_creating_sub_agent_id_service')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_get_creating_sub_agent_info_impl_success(mock_get_current_user_info, mock_get_creating_sub_agent,
                                                        mock_search_agent_info, mock_get_enable_tools,
                                                        mock_query_sub_agents_id):
    """
    Test successful retrieval of creating sub-agent information.

    This test verifies that:
    1. The function correctly gets the current user and tenant IDs
    2. It retrieves or creates the sub-agent ID
    3. It fetches the sub-agent's information and enabled tools
    4. It returns a complete data structure with the sub-agent information
    """
    # Setup
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")
    mock_get_creating_sub_agent.return_value = 456
    mock_search_agent_info.return_value = {
        "model_id": 456,
        "name": "agent_name",
        "display_name": "display name",
        "description": "description...",
        "model_name": "gpt-4",
        "max_steps": 5,
        "business_description": "Sub agent",
        "duty_prompt": "Sub duty prompt",
        "constraint_prompt": "Sub constraint prompt",
        "few_shots_prompt": "Sub few shots prompt"
    }
    mock_get_enable_tools.return_value = [1, 2]
    mock_query_sub_agents_id.return_value = [789]

    # Execute
    # Ensure the sub agent id remains as initially configured (456)
    mock_get_enable_tools.return_value = [1, 2]
    result = await get_creating_sub_agent_info_impl(authorization="Bearer token")

    # Assert
    expected_result = {
        "agent_id": 456,
        "name": "agent_name",
        "display_name": "display name",
        "description": "description...",
        "enable_tool_id_list": [1, 2],
        "model_name": "gpt-4",
        "max_steps": 5,
        "business_description": "Sub agent",
        "duty_prompt": "Sub duty prompt",
        "constraint_prompt": "Sub constraint prompt",
        "few_shots_prompt": "Sub few shots prompt",
        "sub_agent_id_list": [789]
    }
    assert result == expected_result


@patch('backend.services.agent_service.update_agent')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_update_agent_info_impl_success(mock_get_current_user_info, mock_update_agent):
    """
    Test successful update of agent information.

    This test verifies that:
    1. The function correctly gets the current user and tenant IDs
    2. It calls the update_agent function with the correct parameters
    """
    # Setup
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")

    # Create a mock AgentInfoRequest object since consts.model is mocked
    request = MagicMock()
    request.agent_id = 123
    request.model_name = "gpt-4"
    request.business_description = "Updated agent"
    request.display_name = "Updated Display Name"

    # Execute
    await update_agent_info_impl(request, authorization="Bearer token")

    # Assert
    mock_update_agent.assert_called_once_with(
        123, request, "test_tenant", "test_user")


@patch('backend.services.agent_service.delete_tools_by_agent_id')
@patch('backend.services.agent_service.delete_agent_relationship')
@patch('backend.services.agent_service.delete_agent_by_id')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_delete_agent_impl_success(mock_get_current_user_info, mock_delete_agent, mock_delete_related,
                                         mock_delete_tools):
    """
    Test successful deletion of an agent.

    This test verifies that:
    1. The function correctly gets the current user and tenant IDs
    2. It calls the delete_agent_by_id function with the correct parameters
    3. It also deletes all related agent relationships
    """
    # Setup
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")

    # Execute
    await delete_agent_impl(123, authorization="Bearer token")

    # Assert
    mock_delete_agent.assert_called_once_with(123, "test_tenant", "test_user")
    mock_delete_related.assert_called_once_with(
        123, "test_tenant", "test_user")
    mock_delete_tools.assert_called_once_with(123, "test_tenant", "test_user")


@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_get_agent_info_impl_exception_handling(mock_search_agent_info):
    """
    Test exception handling in get_agent_info_impl function.

    This test verifies that:
    1. When an exception occurs during agent info retrieval
    2. The function raises a ValueError with an appropriate message
    """
    # Setup
    mock_search_agent_info.side_effect = Exception("Database error")

    # Execute & Assert
    with pytest.raises(ValueError) as context:
        await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert "Failed to get agent info" in str(context.value)


@patch('backend.services.agent_service.update_agent')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_update_agent_info_impl_exception_handling(mock_get_current_user_info, mock_update_agent):
    """
    Test exception handling in update_agent_info_impl function.

    This test verifies that:
    1. When an exception occurs during agent info update
    2. The function raises a ValueError with an appropriate message
    """
    # Setup
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")
    mock_update_agent.side_effect = Exception("Update failed")

    # Create a mock AgentInfoRequest object since consts.model is mocked
    request = MagicMock()
    request.agent_id = 123
    request.model_name = "gpt-4"
    request.display_name = "Test Display Name"

    # Execute & Assert
    with pytest.raises(ValueError) as context:
        await update_agent_info_impl(request, authorization="Bearer token")

    assert "Failed to update agent info" in str(context.value)


@patch('backend.services.agent_service.delete_agent_by_id')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_delete_agent_impl_exception_handling(mock_get_current_user_info, mock_delete_agent):
    """
    Test exception handling in delete_agent_impl function.

    This test verifies that:
    1. When an exception occurs during agent deletion
    2. The function raises a ValueError with an appropriate message
    """
    # Setup
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")
    mock_delete_agent.side_effect = Exception("Delete failed")

    # Execute & Assert
    with pytest.raises(ValueError) as context:
        await delete_agent_impl(123, authorization="Bearer token")

    assert "Failed to delete agent" in str(context.value)


@patch('backend.services.agent_service.get_mcp_server_by_name_and_tenant')
@patch('backend.services.agent_service.ExportAndImportDataFormat')
@patch('backend.services.agent_service.export_agent_by_agent_id')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_export_agent_impl_success(mock_get_current_user_info, mock_export_agent_by_id, mock_export_data_format,
                                         mock_get_mcp_server):
    """
    Test successful export of agent information with MCP servers.
    """
    # Setup
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")

    # Create tools with MCP source
    mcp_tool = ToolConfig(
        class_name="MCPTool",
        name="MCP Tool",
        source="mcp",
        params={"param1": "value1"},
        metadata={},
        description="MCP tool description",
        inputs="input description",
        output_type="output type description",
        usage="test_mcp_server"
    )

    # Create a proper ExportAndImportAgentInfo object with MCP tools
    mcp_tool_dict = mcp_tool.model_dump()
    mock_agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="Test Agent",
        display_name="Test Agent Display",
        description="A test agent",
        business_description="For testing purposes",
        model_name="main_model",
        max_steps=10,
        provide_run_summary=True,
        duty_prompt="Test duty prompt",
        constraint_prompt="Test constraint prompt",
        few_shots_prompt="Test few shots prompt",
        enabled=True,
        tools=[mcp_tool_dict],
        managed_agents=[]
    )
    mock_export_agent_by_id.return_value = mock_agent_info

    # Mock MCP server URL retrieval
    mock_get_mcp_server.return_value = "http://test-mcp-server.com"

    # Mock the ExportAndImportDataFormat to return a proper model_dump
    mock_export_data_instance = Mock()
    mock_export_data_instance.model_dump.return_value = {
        "agent_id": 123,
        "agent_info": {
            "123": {
                "agent_id": 123,
                "name": "Test Agent",
                "display_name": "Test Agent Display",
                "description": "A test agent",
                "business_description": "For testing purposes",
                "model_name": "main_model",
                "max_steps": 10,
                "provide_run_summary": True,
                "duty_prompt": "Test duty prompt",
                "constraint_prompt": "Test constraint prompt",
                "few_shots_prompt": "Test few shots prompt",
                "enabled": True,
                "tools": [mcp_tool.model_dump()],
                "managed_agents": []
            }
        },
        "mcp_info": [
            {
                "mcp_server_name": "test_mcp_server",
                "mcp_url": "http://test-mcp-server.com"
            }
        ]
    }
    mock_export_data_format.return_value = mock_export_data_instance

    # Execute
    result = await export_agent_impl(
        agent_id=123,
        authorization="Bearer token"
    )

    # Assert the result structure - result is a dict from model_dump()
    assert result["agent_id"] == 123
    assert "agent_info" in result
    assert "123" in result["agent_info"]
    assert "mcp_info" in result

    # The agent_info should contain the ExportAndImportAgentInfo data
    agent_data = result["agent_info"]["123"]
    assert agent_data["name"] == "Test Agent"
    assert agent_data["business_description"] == "For testing purposes"
    assert agent_data["agent_id"] == 123
    assert len(agent_data["tools"]) == 1

    # Check MCP info
    mcp_info = result["mcp_info"]
    assert len(mcp_info) == 1
    assert mcp_info[0]["mcp_server_name"] == "test_mcp_server"
    assert mcp_info[0]["mcp_url"] == "http://test-mcp-server.com"

    # Verify function calls
    mock_get_current_user_info.assert_called_once_with("Bearer token")
    mock_export_agent_by_id.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant", user_id="test_user")
    mock_get_mcp_server.assert_called_once_with(
        "test_mcp_server", "test_tenant")
    mock_export_data_format.assert_called_once()


@patch('backend.services.agent_service.get_mcp_server_by_name_and_tenant')
@patch('backend.services.agent_service.ExportAndImportDataFormat')
@patch('backend.services.agent_service.export_agent_by_agent_id')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_export_agent_impl_no_mcp_tools(mock_get_current_user_info, mock_export_agent_by_id,
                                              mock_export_data_format, mock_get_mcp_server):
    """
    Test successful export of agent information without MCP tools.
    """
    # Setup
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")

    # Create a proper ExportAndImportAgentInfo object without MCP tools
    mock_agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="Test Agent",
        display_name="Test Agent Display",
        description="A test agent",
        business_description="For testing purposes",
        model_name="main_model",
        max_steps=10,
        provide_run_summary=True,
        duty_prompt="Test duty prompt",
        constraint_prompt="Test constraint prompt",
        few_shots_prompt="Test few shots prompt",
        enabled=True,
        tools=[],
        managed_agents=[]
    )
    mock_export_agent_by_id.return_value = mock_agent_info

    # Mock the ExportAndImportDataFormat to return a proper model_dump
    mock_export_data_instance = Mock()
    mock_export_data_instance.model_dump.return_value = {
        "agent_id": 123,
        "agent_info": {
            "123": {
                "agent_id": 123,
                "name": "Test Agent",
                "display_name": "Test Agent Display",
                "description": "A test agent",
                "business_description": "For testing purposes",
                "model_name": "main_model",
                "max_steps": 10,
                "provide_run_summary": True,
                "duty_prompt": "Test duty prompt",
                "constraint_prompt": "Test constraint prompt",
                "few_shots_prompt": "Test few shots prompt",
                "enabled": True,
                "tools": [],
                "managed_agents": []
            }
        },
        "mcp_info": []
    }
    mock_export_data_format.return_value = mock_export_data_instance

    # Execute
    result = await export_agent_impl(
        agent_id=123,
        authorization="Bearer token"
    )

    # Assert the result structure
    assert result["agent_id"] == 123
    assert "agent_info" in result
    assert "123" in result["agent_info"]
    assert "mcp_info" in result
    assert len(result["mcp_info"]) == 0  # No MCP tools

    # Verify function calls
    mock_get_current_user_info.assert_called_once_with("Bearer token")
    mock_export_agent_by_id.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant", user_id="test_user")
    # Should not be called when no MCP tools
    mock_get_mcp_server.assert_not_called()
    mock_export_data_format.assert_called_once()


@patch('backend.services.agent_service.search_agent_info_by_agent_id')
async def test_get_agent_info_impl_with_tool_error(mock_search_agent_info):
    """
    Test get_agent_info_impl with an error in retrieving tool information.

    This test verifies that:
    1. The function correctly gets the agent information
    2. When an error occurs retrieving tool information
    3. The function returns the agent information with an empty tools list
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_name": "gpt-4",
        "business_description": "Test agent"
    }
    mock_search_agent_info.return_value = mock_agent_info

    # Mock the search_tools_for_sub_agent function to raise an exception
    with patch('backend.services.agent_service.search_tools_for_sub_agent') as mock_search_tools, \
            patch('backend.services.agent_service.query_sub_agents_id_list') as mock_query_sub_agents_id:
        mock_search_tools.side_effect = Exception("Tool search error")
        mock_query_sub_agents_id.return_value = []

        # Execute
        result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

        # Assert
        assert result["agent_id"] == 123
        assert result["tools"] == []
        assert result["sub_agent_id_list"] == []
        mock_search_agent_info.assert_called_once_with(123, "test_tenant")


async def test_list_all_agent_info_impl_success():
    """
    Test successful retrieval of all agent information.

    This test verifies that:
    1. The function correctly queries all agents for a tenant
    2. It retrieves tool information for each agent
    3. It checks tool availability
    4. It returns a properly formatted list of agent information
    """
    # Setup mock agents
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "First test agent",
            "enabled": True
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Second test agent",
            "enabled": True
        }
    ]

    # Setup mock tools
    mock_tools = [
        {"tool_id": 101, "name": "Tool 1"},
        {"tool_id": 102, "name": "Tool 2"}
    ]

    with patch('backend.services.agent_service.query_all_agent_info_by_tenant_id') as mock_query_agents, \
            patch('backend.services.agent_service.search_tools_for_sub_agent') as mock_search_tools, \
            patch('backend.services.agent_service.check_tool_is_available') as mock_check_tools:
        # Configure mocks
        mock_query_agents.return_value = mock_agents
        mock_search_tools.return_value = mock_tools
        mock_check_tools.return_value = [True, True]  # All tools are available

        # Execute
        result = await list_all_agent_info_impl(tenant_id="test_tenant")

        # Assert
        assert len(result) == 2
        assert result[0]["agent_id"] == 1
        assert result[0]["name"] == "Agent 1"
        assert result[0]["display_name"] == "Display Agent 1"
        assert result[0]["is_available"] == True
        assert result[1]["agent_id"] == 2
        assert result[1]["name"] == "Agent 2"
        assert result[1]["display_name"] == "Display Agent 2"
        assert result[1]["is_available"] == True

        # Verify mock calls
        mock_query_agents.assert_called_once_with(tenant_id="test_tenant")
        assert mock_search_tools.call_count == 2
        mock_search_tools.assert_has_calls([
            call(agent_id=1, tenant_id="test_tenant"),
            call(agent_id=2, tenant_id="test_tenant")
        ])
        mock_check_tools.assert_has_calls([
            call([101, 102]),
            call([101, 102])
        ])


async def test_list_all_agent_info_impl_with_unavailable_tools():
    """
    Test retrieval of agent information with some unavailable tools.

    This test verifies that:
    1. The function correctly handles cases where some tools are unavailable
    2. It properly sets the is_available flag based on tool availability
    """
    # Setup mock agents
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent with available tools",
            "enabled": True
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Agent with unavailable tools",
            "enabled": True
        }
    ]

    # Setup mock tools
    mock_tools = [
        {"tool_id": 101, "name": "Tool 1"},
        {"tool_id": 102, "name": "Tool 2"}
    ]

    with patch('backend.services.agent_service.query_all_agent_info_by_tenant_id') as mock_query_agents, \
            patch('backend.services.agent_service.search_tools_for_sub_agent') as mock_search_tools, \
            patch('backend.services.agent_service.check_tool_is_available') as mock_check_tools:
        # Configure mocks
        mock_query_agents.return_value = mock_agents
        mock_search_tools.return_value = mock_tools
        # First agent has available tools, second agent has unavailable tools
        mock_check_tools.side_effect = [[True, True], [False, True]]

        # Execute
        result = await list_all_agent_info_impl(tenant_id="test_tenant")

        # Assert
        assert len(result) == 2
        assert result[0]["is_available"] == True
        assert result[1]["is_available"] == False

        # Verify mock calls
        mock_query_agents.assert_called_once_with(tenant_id="test_tenant")
        assert mock_search_tools.call_count == 2
        assert mock_check_tools.call_count == 2


async def test_list_all_agent_info_impl_query_error():
    """
    Test error handling when querying agent information fails.

    This test verifies that:
    1. When an error occurs during agent query
    2. The function raises a ValueError with an appropriate message
    """
    with patch('backend.services.agent_service.query_all_agent_info_by_tenant_id') as mock_query_agents:
        # Configure mock to raise exception
        mock_query_agents.side_effect = Exception("Database error")

        # Execute & Assert
        with pytest.raises(ValueError) as context:
            await list_all_agent_info_impl(tenant_id="test_tenant")

        assert "Failed to query all agent info" in str(context.value)
        mock_query_agents.assert_called_once_with(tenant_id="test_tenant")


@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.create_tool_config_list', new_callable=AsyncMock)
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_export_agent_by_agent_id_success(mock_search_agent_info, mock_create_tool_config,
                                                mock_query_sub_agents_id):
    """
    Test successful export of agent information by agent ID.

    This test verifies that:
    1. The function correctly retrieves agent information
    2. It creates tool configuration list
    3. It gets sub-agent ID list
    4. It returns properly structured ExportAndImportAgentInfo
    """
    # Setup
    mock_agent_info = {
        "name": "Test Agent",
        "display_name": "Test Agent Display",
        "description": "A test agent",
        "business_description": "For testing purposes",
        "model_name": "main_model",
        "max_steps": 10,
        "provide_run_summary": True,
        "duty_prompt": "Test duty prompt",
        "constraint_prompt": "Test constraint prompt",
        "few_shots_prompt": "Test few shots prompt",
        "enabled": True
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [
        ToolConfig(
            class_name="Tool1",
            name="Tool One",
            source="source1",
            params={"param1": "value1"},
            metadata={},
            description="Tool 1 description",
            inputs="input description",
            output_type="output type description",
            usage=None
        ),
        ToolConfig(
            class_name="KnowledgeBaseSearchTool",
            name="Knowledge Search",
            source="source2",
            params={"param2": "value2"},
            metadata={"some": "data"},
            description="Knowledge base search tool",
            inputs="search query",
            output_type="search results",
            usage=None
        ),
        ToolConfig(
            class_name="MCPTool",
            name="MCP Tool",
            source="mcp",
            params={"param3": "value3"},
            metadata={},
            description="MCP tool description",
            inputs="mcp input",
            output_type="mcp output",
            usage="test_mcp_server"
        )
    ]
    mock_create_tool_config.return_value = mock_tools

    mock_sub_agent_ids = [456, 789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Execute
    with patch('backend.services.agent_service.ExportAndImportAgentInfo', new=ExportAndImportAgentInfo):
        result = await export_agent_by_agent_id(
            agent_id=123,
            tenant_id="test_tenant",
            user_id="test_user"
        )

    # Assert
    assert result.agent_id == 123
    assert result.name == "Test Agent"
    assert result.business_description == "For testing purposes"
    assert len(result.tools) == 3
    assert result.managed_agents == mock_sub_agent_ids

    # Verify KnowledgeBaseSearchTool metadata is empty
    knowledge_tool = next(
        tool for tool in result.tools if tool.class_name == "KnowledgeBaseSearchTool")
    assert knowledge_tool.metadata == {}

    # Verify MCP tool has usage field
    mcp_tool = next(
        tool for tool in result.tools if tool.class_name == "MCPTool")
    assert mcp_tool.usage == "test_mcp_server"

    # Verify function calls
    mock_search_agent_info.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant")
    mock_create_tool_config.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant", user_id="test_user")
    mock_query_sub_agents_id.assert_called_once_with(
        main_agent_id=123, tenant_id="test_tenant")


@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@pytest.mark.asyncio
async def test_import_agent_by_agent_id_success(mock_query_all_tools, mock_create_agent, mock_create_tool):
    """
    Test successful import of agent by agent ID.

    This test verifies that:
    1. The function correctly retrieves agent information
    2. It creates tool configuration list
    3. It gets sub-agent ID list
    4. It returns properly structured ExportAndImportAgentInfo
    """
    # Setup
    mock_tool_info = [
        {
            "tool_id": 101,
            "class_name": "Tool1",
            "source": "source1",
            "params": [{"name": "param1", "type": "string"}],
            "description": "Tool 1 description",
            "name": "Tool One",
            "inputs": "input description",
            "output_type": "output type description"
        }
    ]
    mock_query_all_tools.return_value = mock_tool_info

    mock_create_agent.return_value = {"agent_id": 456}

    # Create import data
    tool_config = ToolConfig(
        class_name="Tool1",
        name="Tool One",
        source="source1",
        params={"param1": "value1"},
        metadata={},
        description="Tool 1 description",
        inputs="input description",
        output_type="output type description",
        usage=None
    )

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="valid_agent_name",
        display_name="Valid Agent Display Name",
        description="Imported description",
        business_description="Imported business description",
        model_name="main_model",
        max_steps=5,
        provide_run_summary=True,
        duty_prompt="Imported duty prompt",
        constraint_prompt="Imported constraint prompt",
        few_shots_prompt="Imported few shots prompt",
        enabled=True,
        tools=[tool_config],
        managed_agents=[]
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert
    assert result == 456
    mock_create_agent.assert_called_once()
    assert mock_create_agent.call_args[1]["agent_info"]["name"] == "valid_agent_name"
    assert mock_create_agent.call_args[1]["agent_info"]["display_name"] == "Valid Agent Display Name"
    mock_create_tool.assert_called_once()


@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@pytest.mark.asyncio
async def test_import_agent_by_agent_id_invalid_tool(mock_query_all_tools, mock_create_tool):
    """
    Test import of agent by agent ID with an invalid tool.

    This test verifies that:
    1. When a tool doesn't exist in the database
    2. The function raises a ValueError with appropriate message
    """
    # Setup
    mock_tool_info = [
        {
            "tool_id": 101,
            "class_name": "OtherTool",
            "source": "source1",
            "params": [{"name": "param1", "type": "string"}],
            "description": "Other tool description",
            "name": "Other Tool",
            "inputs": "other input",
            "output_type": "other output"
        }
    ]
    mock_query_all_tools.return_value = mock_tool_info

    # Create import data with non-existent tool
    tool_config = ToolConfig(
        class_name="Tool1",
        name="Tool One",
        source="source1",
        params={"param1": "value1"},
        metadata={},
        description="Tool 1 description",
        inputs="input description",
        output_type="output type description"
    )

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="valid_agent_name",
        display_name="Valid Agent Display Name",
        description="Imported description",
        business_description="Imported business description",
        model_name="main_model",
        max_steps=5,
        provide_run_summary=True,
        duty_prompt="Imported duty prompt",
        constraint_prompt="Imported constraint prompt",
        few_shots_prompt="Imported few shots prompt",
        enabled=True,
        tools=[tool_config],
        managed_agents=[]
    )

    # Execute & Assert
    with pytest.raises(ValueError) as context:
        await import_agent_by_agent_id(
            import_agent_info=agent_info,
            tenant_id="test_tenant",
            user_id="test_user"
        )

    assert "Cannot find tool Tool1 in source1." in str(context.value)
    mock_create_tool.assert_not_called()


@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@pytest.mark.asyncio
async def test_import_agent_by_agent_id_with_mcp_tool(mock_query_all_tools, mock_create_agent, mock_create_tool):
    """
    Test successful import of agent by agent ID with MCP tools.
    """
    # Setup
    mock_tool_info = [
        {
            "tool_id": 101,
            "class_name": "MCPTool",
            "source": "mcp",
            "params": [{"name": "param1", "type": "string"}],
            "description": "MCP tool description",
            "name": "MCP Tool",
            "inputs": "mcp input",
            "output_type": "mcp output"
        }
    ]
    mock_query_all_tools.return_value = mock_tool_info

    mock_create_agent.return_value = {"agent_id": 456}

    # Create import data with MCP tool
    tool_config = ToolConfig(
        class_name="MCPTool",
        name="MCP Tool",
        source="mcp",
        params={"param1": "value1"},
        metadata={},
        description="MCP tool description",
        inputs="mcp input",
        output_type="mcp output",
        usage="test_mcp_server"
    )

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="valid_agent_name",
        display_name="Valid Agent Display Name",
        description="Imported description",
        business_description="Imported business description",
        model_name="main_model",
        max_steps=5,
        provide_run_summary=True,
        duty_prompt="Imported duty prompt",
        constraint_prompt="Imported constraint prompt",
        few_shots_prompt="Imported few shots prompt",
        enabled=True,
        tools=[tool_config],
        managed_agents=[]
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert
    assert result == 456
    mock_create_agent.assert_called_once()
    assert mock_create_agent.call_args[1]["agent_info"]["name"] == "valid_agent_name"
    assert mock_create_agent.call_args[1]["agent_info"]["display_name"] == "Valid Agent Display Name"
    mock_create_tool.assert_called_once()


@patch('backend.services.agent_service.insert_related_agent')
@patch('backend.services.agent_service.query_sub_agents_id_list')
def test_insert_related_agent_impl_success(mock_query_sub_agents_id, mock_insert_related):
    """
    Test successful insertion of related agent relationship.

    This test verifies that:
    1. The function checks for circular dependencies using BFS
    2. When no circular dependency exists, it inserts the relationship
    3. It returns a success response
    """
    # Setup
    # Child agent has different sub-agents
    mock_query_sub_agents_id.return_value = [789]
    mock_insert_related.return_value = True

    # Execute
    result = insert_related_agent_impl(
        parent_agent_id=123,
        child_agent_id=456,
        tenant_id="test_tenant"
    )

    # Assert
    assert result.status_code == 200
    assert "Insert relation success" in result.body.decode()
    mock_insert_related.assert_called_once_with(123, 456, "test_tenant")


@patch('backend.services.agent_service.query_sub_agents_id_list')
def test_insert_related_agent_impl_circular_dependency(mock_query_sub_agents_id):
    """
    Test insertion of related agent with circular dependency.

    This test verifies that:
    1. The function detects circular dependencies
    2. It returns an error response when circular dependency exists
    """
    # Setup - simulate circular dependency
    mock_query_sub_agents_id.side_effect = [
        # Child agent 456 has parent agent 123 as its sub-agent (circular)
        [123],
    ]

    # Execute
    result = insert_related_agent_impl(
        parent_agent_id=123,
        child_agent_id=456,
        tenant_id="test_tenant"
    )

    # Assert
    assert result.status_code == 500
    assert "There is a circular call in the agent" in result.body.decode()


@patch('os.path.join', return_value='test_path')
@patch('os.listdir')
@patch('builtins.open', new_callable=mock_open)
def test_load_default_agents_json_file(mock_file, mock_listdir, mock_join):
    """
    Test loading default agent JSON files.

    This test verifies that:
    1. The function correctly lists files in the specified directory
    2. It filters for JSON files
    3. It reads and parses each JSON file
    4. It returns a list of validated agent configurations
    """
    # Setup
    mock_listdir.return_value = ['agent1.json', 'agent2.json', 'not_json.txt']

    # Set up the mock file content for each file
    json_content1 = """{
        "agent_id": 1,
        "name": "Agent1",
        "display_name": "Agent 1 Display",
        "description": "Agent 1 description",
        "business_description": "Business description",
        "model_name": "main_model",
        "max_steps": 10,
        "provide_run_summary": true,
        "duty_prompt": "Agent 1 prompt",
        "enabled": true,
        "tools": [],
        "managed_agents": []
    }"""

    json_content2 = """{
        "agent_id": 2,
        "name": "Agent2",
        "display_name": "Agent 2 Display",
        "description": "Agent 2 description",
        "business_description": "Business description",
        "model_name": "sub_model",
        "max_steps": 5,
        "provide_run_summary": false,
        "duty_prompt": "Agent 2 prompt",
        "enabled": true,
        "tools": [],
        "managed_agents": []
    }"""

    # Make the mock file return different content for different files
    mock_file.return_value.__enter__.side_effect = [
        MagicMock(read=lambda: json_content1),
        MagicMock(read=lambda: json_content2)
    ]

    # Need to patch json.load to handle the mock file contents
    with patch('json.load') as mock_json_load:
        mock_json_load.side_effect = [
            {
                "agent_id": 1,
                "name": "Agent1",
                "display_name": "Agent 1 Display",
                "description": "Agent 1 description",
                "business_description": "Business description",
                "model_name": "main_model",
                "max_steps": 10,
                "provide_run_summary": True,
                "duty_prompt": "Agent 1 prompt",
                "enabled": True,
                "tools": [],
                "managed_agents": []
            },
            {
                "agent_id": 2,
                "name": "Agent2",
                "display_name": "Agent 2 Display",
                "description": "Agent 2 description",
                "business_description": "Business description",
                "model_name": "sub_model",
                "max_steps": 5,
                "provide_run_summary": False,
                "duty_prompt": "Agent 2 prompt",
                "enabled": True,
                "tools": [],
                "managed_agents": []
            }
        ]

        # Execute
        with patch('backend.services.agent_service.ExportAndImportAgentInfo', new=ExportAndImportAgentInfo):
            result = load_default_agents_json_file("default/path")

        # Assert
        assert len(result) == 2
        assert result[0].name == "Agent1"
        assert result[1].name == "Agent2"
        assert mock_file.call_count == 2
        mock_listdir.assert_called_once_with("default/path")


# clear_agent_memory function tests
@patch('backend.services.agent_service.clear_memory', new_callable=AsyncMock)
@patch('backend.services.agent_service.build_memory_config')
@pytest.mark.asyncio
async def test_clear_agent_memory_success(mock_build_config, mock_clear_memory):
    """
    Test successful clearing of agent memory.

    This test verifies that:
    1. The function correctly builds memory configuration
    2. It clears both agent-level and user_agent-level memory
    3. It logs the results appropriately
    """
    # Setup
    mock_memory_config = {
        "llm": {"provider": "openai", "config": {"model": "gpt-4"}},
        "embedder": {"provider": "openai", "config": {"model": "text-embedding-ada-002"}},
        "vector_store": {"provider": "elasticsearch", "config": {"host": "localhost"}}
    }
    mock_build_config.return_value = mock_memory_config

    mock_clear_memory.side_effect = [
        {"deleted_count": 5},
        {"deleted_count": 3}
    ]

    # Execute
    await clear_agent_memory(
        agent_id=123,
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert
    mock_build_config.assert_called_once_with("test_tenant")
    assert mock_clear_memory.call_count == 2

    # Verify agent-level memory cleanup
    agent_call = mock_clear_memory.call_args_list[0]
    assert agent_call[1]["memory_level"] == "agent"
    assert agent_call[1]["memory_config"] == mock_memory_config
    assert agent_call[1]["tenant_id"] == "test_tenant"
    assert agent_call[1]["user_id"] == "test_user"
    assert agent_call[1]["agent_id"] == "123"

    # Verify user_agent-level memory cleanup
    user_agent_call = mock_clear_memory.call_args_list[1]
    assert user_agent_call[1]["memory_level"] == "user_agent"
    assert user_agent_call[1]["memory_config"] == mock_memory_config
    assert user_agent_call[1]["tenant_id"] == "test_tenant"
    assert user_agent_call[1]["user_id"] == "test_user"
    assert user_agent_call[1]["agent_id"] == "123"


@patch('backend.services.agent_service.clear_memory', new_callable=AsyncMock)
@patch('backend.services.agent_service.build_memory_config')
@pytest.mark.asyncio
async def test_clear_agent_memory_build_config_error(mock_build_config, mock_clear_memory):
    """
    Test clear_agent_memory when build_memory_config fails.

    This test verifies that:
    1. When build_memory_config raises an exception
    2. The function catches the exception and logs it
    3. The function does not raise the exception (to avoid affecting agent deletion)
    """
    # Setup
    mock_build_config.side_effect = ValueError("Invalid memory configuration")

    # Execute - should not raise exception
    await clear_agent_memory(
        agent_id=123,
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert
    mock_build_config.assert_called_once_with("test_tenant")
    mock_clear_memory.assert_not_called()


@patch('backend.services.agent_service.clear_memory', new_callable=AsyncMock)
@patch('backend.services.agent_service.build_memory_config')
@pytest.mark.asyncio
async def test_clear_agent_memory_clear_memory_error(mock_build_config, mock_clear_memory):
    """
    Test clear_agent_memory when clear_memory fails.

    This test verifies that:
    1. When clear_memory raises an exception
    2. The function catches the exception and logs it
    3. The function continues with the second clear_memory call
    4. The function does not raise the exception
    """
    # Setup
    mock_memory_config = {
        "llm": {"provider": "openai", "config": {"model": "gpt-4"}},
        "embedder": {"provider": "openai", "config": {"model": "text-embedding-ada-002"}},
        "vector_store": {"provider": "elasticsearch", "config": {"host": "localhost"}}
    }
    mock_build_config.return_value = mock_memory_config

    # First call fails, second call succeeds
    mock_clear_memory.side_effect = [
        Exception("Database connection failed"),  # agent-level memory fails
        {"deleted_count": 3}  # user_agent-level memory succeeds
    ]

    # Execute - should not raise exception
    await clear_agent_memory(
        agent_id=123,
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert
    mock_build_config.assert_called_once_with("test_tenant")
    assert mock_clear_memory.call_count == 2


# Import agent tests
@patch('backend.services.agent_service.import_agent_by_agent_id')
@patch('backend.services.agent_service.update_tool_list', new_callable=AsyncMock)
@patch('backend.services.agent_service.add_remote_mcp_server_list', new_callable=AsyncMock)
@patch('backend.services.agent_service.get_mcp_server_by_name_and_tenant')
@patch('backend.services.agent_service.check_mcp_name_exists')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_import_agent_impl_success_with_mcp(mock_get_current_user_info, mock_check_mcp_exists,
                                                  mock_get_mcp_server,
                                                  mock_add_mcp_server, mock_update_tool_list, mock_import_agent):
    """
    Test successful import of agent with MCP servers.
    """
    # Setup
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")

    # Mock MCP server checks
    mock_check_mcp_exists.return_value = False  # MCP server doesn't exist
    mock_get_mcp_server.return_value = "http://existing-mcp-server.com"
    mock_add_mcp_server.return_value = None  # Function returns None on success
    mock_update_tool_list.return_value = None

    # Create MCP info
    mcp_info = MCPInfo(mcp_server_name="test_mcp_server",
                       mcp_url="http://test-mcp-server.com")

    # Create agent info
    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="Test Agent",
        display_name="Test Agent Display",
        description="A test agent",
        business_description="For testing purposes",
        model_name="main_model",
        max_steps=10,
        provide_run_summary=True,
        duty_prompt="Test duty prompt",
        constraint_prompt="Test constraint prompt",
        few_shots_prompt="Test few shots prompt",
        enabled=True,
        tools=[],
        managed_agents=[]
    )

    # Create export data format
    export_data = ExportAndImportDataFormat(
        agent_id=123,
        agent_info={"123": agent_info},
        mcp_info=[mcp_info]
    )

    # Mock import agent
    mock_import_agent.return_value = 456  # New agent ID

    # Execute
    await import_agent_impl(export_data, authorization="Bearer token")

    # Assert
    mock_get_current_user_info.assert_called_once_with("Bearer token")
    mock_check_mcp_exists.assert_called_once_with(
        mcp_name="test_mcp_server", tenant_id="test_tenant")
    mock_add_mcp_server.assert_called_once_with(
        tenant_id="test_tenant",
        user_id="test_user",
        remote_mcp_server="http://test-mcp-server.com",
        remote_mcp_server_name="test_mcp_server"
    )
    mock_update_tool_list.assert_called_once_with(
        tenant_id="test_tenant", user_id="test_user")
    mock_import_agent.assert_called_once_with(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user"
    )


@patch('backend.services.agent_service.import_agent_by_agent_id')
@patch('backend.services.agent_service.update_tool_list', new_callable=AsyncMock)
@patch('backend.services.agent_service.add_remote_mcp_server_list', new_callable=AsyncMock)
@patch('backend.services.agent_service.get_mcp_server_by_name_and_tenant')
@patch('backend.services.agent_service.check_mcp_name_exists')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_import_agent_impl_mcp_exists_same_url(mock_get_current_user_info, mock_check_mcp_exists,
                                                     mock_get_mcp_server,
                                                     mock_add_mcp_server, mock_update_tool_list, mock_import_agent):
    """
    Test import of agent when MCP server exists with same URL (should skip).
    """
    # Setup
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")

    # Mock MCP server exists with same URL
    mock_check_mcp_exists.return_value = True
    mock_get_mcp_server.return_value = "http://test-mcp-server.com"  # Same URL
    mock_update_tool_list.return_value = None

    # Create MCP info
    mcp_info = MCPInfo(mcp_server_name="test_mcp_server",
                       mcp_url="http://test-mcp-server.com")

    # Create agent info
    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="Test Agent",
        display_name="Test Agent Display",
        description="A test agent",
        business_description="For testing purposes",
        model_name="main_model",
        max_steps=10,
        provide_run_summary=True,
        duty_prompt="Test duty prompt",
        constraint_prompt="Test constraint prompt",
        few_shots_prompt="Test few shots prompt",
        enabled=True,
        tools=[],
        managed_agents=[]
    )

    # Create export data format
    export_data = ExportAndImportDataFormat(
        agent_id=123,
        agent_info={"123": agent_info},
        mcp_info=[mcp_info]
    )

    # Mock import agent
    mock_import_agent.return_value = 456

    # Execute
    await import_agent_impl(export_data, authorization="Bearer token")

    # Assert
    mock_get_current_user_info.assert_called_once_with("Bearer token")
    mock_check_mcp_exists.assert_called_once_with(
        mcp_name="test_mcp_server", tenant_id="test_tenant")
    mock_get_mcp_server.assert_called_once_with(
        mcp_name="test_mcp_server", tenant_id="test_tenant")
    mock_add_mcp_server.assert_not_called()  # Should not add since URL is the same
    mock_update_tool_list.assert_called_once_with(
        tenant_id="test_tenant", user_id="test_user")
    mock_import_agent.assert_called_once()


@patch('backend.services.agent_service.import_agent_by_agent_id')
@patch('backend.services.agent_service.update_tool_list', new_callable=AsyncMock)
@patch('backend.services.agent_service.add_remote_mcp_server_list', new_callable=AsyncMock)
@patch('backend.services.agent_service.get_mcp_server_by_name_and_tenant')
@patch('backend.services.agent_service.check_mcp_name_exists')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_import_agent_impl_mcp_exists_different_url(mock_get_current_user_info, mock_check_mcp_exists,
                                                          mock_get_mcp_server,
                                                          mock_add_mcp_server, mock_update_tool_list, mock_import_agent):
    """
    Test import of agent when MCP server exists with different URL (should add with import prefix).
    """
    # Setup
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")

    # Mock MCP server exists with different URL
    mock_check_mcp_exists.return_value = True
    mock_get_mcp_server.return_value = "http://different-mcp-server.com"  # Different URL
    mock_add_mcp_server.return_value = None  # Function returns None on success
    mock_update_tool_list.return_value = None

    # Create MCP info
    mcp_info = MCPInfo(mcp_server_name="test_mcp_server",
                       mcp_url="http://test-mcp-server.com")

    # Create agent info
    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="Test Agent",
        display_name="Test Agent Display",
        description="A test agent",
        business_description="For testing purposes",
        model_name="main_model",
        max_steps=10,
        provide_run_summary=True,
        duty_prompt="Test duty prompt",
        constraint_prompt="Test constraint prompt",
        few_shots_prompt="Test few shots prompt",
        enabled=True,
        tools=[],
        managed_agents=[]
    )

    # Create export data format
    export_data = ExportAndImportDataFormat(
        agent_id=123,
        agent_info={"123": agent_info},
        mcp_info=[mcp_info]
    )

    # Mock import agent
    mock_import_agent.return_value = 456

    # Execute
    await import_agent_impl(export_data, authorization="Bearer token")

    # Assert
    mock_get_current_user_info.assert_called_once_with("Bearer token")
    mock_check_mcp_exists.assert_called_once_with(
        mcp_name="test_mcp_server", tenant_id="test_tenant")
    mock_get_mcp_server.assert_called_once_with(
        mcp_name="test_mcp_server", tenant_id="test_tenant")
    # Should add with import prefix
    mock_add_mcp_server.assert_called_once_with(
        tenant_id="test_tenant",
        user_id="test_user",
        remote_mcp_server="http://test-mcp-server.com",
        remote_mcp_server_name="import_test_mcp_server"
    )
    mock_update_tool_list.assert_called_once_with(
        tenant_id="test_tenant", user_id="test_user")
    mock_import_agent.assert_called_once()



@patch('backend.services.agent_service.add_remote_mcp_server_list', new_callable=AsyncMock)
@patch('backend.services.agent_service.get_mcp_server_by_name_and_tenant')
@patch('backend.services.agent_service.check_mcp_name_exists')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_import_agent_impl_mcp_add_failure(mock_get_current_user_info, mock_check_mcp_exists, mock_get_mcp_server,
                                                 mock_add_mcp_server):
    """
    Test import of agent when MCP server addition fails.
    """
    # Setup
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")

    # Mock MCP server checks
    mock_check_mcp_exists.return_value = False  # MCP server doesn't exist
    mock_get_mcp_server.return_value = "http://existing-mcp-server.com"

    # Mock MCP server addition failure - the function raises an exception
    mock_add_mcp_server.side_effect = Exception("MCP server connection failed")

    # Create MCP info
    mcp_info = MCPInfo(mcp_server_name="test_mcp_server",
                       mcp_url="http://test-mcp-server.com")

    # Create agent info
    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="Test Agent",
        display_name="Test Agent Display",
        description="A test agent",
        business_description="For testing purposes",
        model_name="main_model",
        max_steps=10,
        provide_run_summary=True,
        duty_prompt="Test duty prompt",
        constraint_prompt="Test constraint prompt",
        few_shots_prompt="Test few shots prompt",
        enabled=True,
        tools=[],
        managed_agents=[]
    )

    # Create export data format
    export_data = ExportAndImportDataFormat(
        agent_id=123,
        agent_info={"123": agent_info},
        mcp_info=[mcp_info]
    )

    # Execute & Assert
    with pytest.raises(Exception) as context:
        await import_agent_impl(export_data, authorization="Bearer token")

    assert "Failed to add MCP server test_mcp_server" in str(context.value)
    mock_add_mcp_server.assert_called_once_with(
        tenant_id="test_tenant",
        user_id="test_user",
        remote_mcp_server="http://test-mcp-server.com",
        remote_mcp_server_name="test_mcp_server"
    )


@patch('backend.services.agent_service.update_tool_list', new_callable=AsyncMock)
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_import_agent_impl_update_tool_list_failure(mock_get_current_user_info, mock_update_tool_list):
    """
    Test import of agent when tool list update fails.
    """
    # Setup
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")

    # Mock tool list update failure
    mock_update_tool_list.side_effect = Exception("Tool list update failed")

    # Create agent info
    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="Test Agent",
        display_name="Test Agent Display",
        description="A test agent",
        business_description="For testing purposes",
        model_name="main_model",
        max_steps=10,
        provide_run_summary=True,
        duty_prompt="Test duty prompt",
        constraint_prompt="Test constraint prompt",
        few_shots_prompt="Test few shots prompt",
        enabled=True,
        tools=[],
        managed_agents=[]
    )

    # Create export data format
    export_data = ExportAndImportDataFormat(
        agent_id=123,
        agent_info={"123": agent_info},
        mcp_info=[]
    )

    # Execute & Assert
    with pytest.raises(Exception) as context:
        await import_agent_impl(export_data, authorization="Bearer token")

    assert "Failed to update tool list" in str(context.value)
    mock_update_tool_list.assert_called_once_with(
        tenant_id="test_tenant", user_id="test_user")


@patch('backend.services.agent_service.import_agent_by_agent_id')
@patch('backend.services.agent_service.update_tool_list', new_callable=AsyncMock)
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_import_agent_impl_no_mcp_info(mock_get_current_user_info, mock_update_tool_list,
                                             mock_import_agent):
    """
    Test import of agent without MCP info.
    """
    # Setup
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")
    mock_update_tool_list.return_value = None

    # Create agent info
    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="Test Agent",
        display_name="Test Agent Display",
        description="A test agent",
        business_description="For testing purposes",
        model_name="main_model",
        max_steps=10,
        provide_run_summary=True,
        duty_prompt="Test duty prompt",
        constraint_prompt="Test constraint prompt",
        few_shots_prompt="Test few shots prompt",
        enabled=True,
        tools=[],
        managed_agents=[]
    )

    # Create export data format without MCP info
    export_data = ExportAndImportDataFormat(
        agent_id=123,
        agent_info={"123": agent_info},
        mcp_info=[]
    )

    # Mock import agent
    mock_import_agent.return_value = 456

    # Execute
    await import_agent_impl(export_data, authorization="Bearer token")

    # Assert
    mock_get_current_user_info.assert_called_once_with("Bearer token")
    mock_update_tool_list.assert_called_once_with(
        tenant_id="test_tenant", user_id="test_user")
    mock_import_agent.assert_called_once_with(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user"
    )


if __name__ == '__main__':
    pytest.main()


# Agent run tests
@pytest.fixture
def mock_agent_request():
    return AgentRequest(
        agent_id=1,
        conversation_id=123,
        query="test query",
        history=[],
        minio_files=[],
        is_debug=False,
    )


@pytest.fixture
def mock_http_request():
    return Request(scope={"type": "http", "headers": []})


@pytest.mark.asyncio
@patch('backend.services.agent_service.build_memory_context')
@patch('backend.services.agent_service.create_agent_run_info', new_callable=AsyncMock)
@patch('backend.services.agent_service.agent_run_manager')
async def test_prepare_agent_run(
    mock_agent_run_manager,
    mock_create_run_info,
    mock_build_memory_context,
    mock_agent_request,
    mock_http_request,
):
    """Test prepare_agent_run function."""
    # Setup
    mock_run_info = MagicMock()
    mock_create_run_info.return_value = mock_run_info
    mock_memory_context = MagicMock()
    mock_build_memory_context.return_value = mock_memory_context

    # Execute
    agent_run_info, memory_context = await prepare_agent_run(
        mock_agent_request,
        user_id="test_user",
        tenant_id="test_tenant",
    )

    # Assert
    assert agent_run_info == mock_run_info
    assert memory_context == mock_memory_context
    mock_build_memory_context.assert_called_once_with(
        "test_user", "test_tenant", 1)
    mock_create_run_info.assert_called_once()
    mock_agent_run_manager.register_agent_run.assert_called_once_with(
        123, mock_run_info, "test_user")


@patch('backend.services.agent_service.submit')
def test_save_messages(mock_submit, mock_agent_request):
    """Test save_messages function."""
    # Test user message saving
    save_messages(mock_agent_request, "user", user_id="u", tenant_id="t")
    mock_submit.assert_called_once()

    # Test assistant message saving
    save_messages(
        mock_agent_request,
        "assistant",
        user_id="u",
        tenant_id="t",
        messages=["test message"],
    )
    assert mock_submit.call_count == 2

    # Test invalid target should not raise according to current implementation; ensure no submit called
    save_messages(
        mock_agent_request,
        "invalid",
        user_id="u",
        tenant_id="t",
        messages=["test message"],
    )
    assert mock_submit.call_count == 2


@pytest.mark.asyncio
@patch(
    "backend.services.agent_service._resolve_user_tenant_language",
    return_value=(None, None, "en"),
)
@patch("backend.services.agent_service.build_memory_context")
@patch('backend.services.agent_service.save_messages')
@patch("backend.services.agent_service.generate_stream_with_memory")
async def test_run_agent_stream(
    mock_generate_stream,
    mock_save_messages,
    mock_build_mem_ctx,
    mock_resolve,
    mock_agent_request,
    mock_http_request,
):
    """Test run_agent_stream function."""

    # Setup
    async def mock_streamer():
        yield "chunk1"
        yield "chunk2"

    mock_generate_stream.return_value = mock_streamer()

    # Execute
    response = await run_agent_stream(mock_agent_request, mock_http_request, "Bearer token")

    # Assert
    assert isinstance(response, StreamingResponse)
    mock_save_messages.assert_called_once_with(
        mock_agent_request,
        target="user",
        user_id=None,
        tenant_id=None,
    )
    mock_generate_stream.assert_called_once_with(
        mock_agent_request,
        user_id=None,
        tenant_id=None,
        language="en",
    )

    # Test debug mode
    mock_agent_request.is_debug = True
    mock_save_messages.reset_mock()

    await run_agent_stream(mock_agent_request, mock_http_request, "Bearer token")

    mock_save_messages.assert_not_called()

    # Memory switch should be True to trigger generate_stream_with_memory path
    mock_build_mem_ctx.return_value = MagicMock(
        user_config=MagicMock(memory_switch=True)
    )


@patch('backend.services.agent_service.agent_run_manager')
@patch('backend.services.agent_service.preprocess_manager')
def test_stop_agent_tasks(mock_preprocess_manager, mock_agent_run_manager):
    """Test stop_agent_tasks function."""
    # Test both stopped
    mock_agent_run_manager.stop_agent_run.return_value = True
    mock_preprocess_manager.stop_preprocess_tasks.return_value = True

    result = stop_agent_tasks(123, "test_user")
    assert result["status"] == "success"
    assert "successfully stopped agent run and preprocess tasks" in result["message"]

    mock_agent_run_manager.stop_agent_run.assert_called_once_with(123, "test_user")

    # Test only agent stopped
    mock_agent_run_manager.stop_agent_run.return_value = True
    mock_preprocess_manager.stop_preprocess_tasks.return_value = False
    result = stop_agent_tasks(123, "test_user")
    assert result["status"] == "success"
    assert "successfully stopped agent run" in result["message"]

    # Test neither stopped
    mock_agent_run_manager.stop_agent_run.return_value = False
    mock_preprocess_manager.stop_preprocess_tasks.return_value = False
    result = stop_agent_tasks(123, "test_user")
    assert result["status"] == "error"
    assert "no running agent or preprocess tasks found" in result["message"]


@patch('backend.services.agent_service.search_agent_id_by_agent_name')
async def test_get_agent_id_by_name(mock_search):
    """Test get_agent_id_by_name function."""
    # Test success
    mock_search.return_value = 1
    result = await get_agent_id_by_name("test_agent", "test_tenant")
    assert result == 1

    # Test not found
    mock_search.side_effect = Exception("Not found")
    with pytest.raises(Exception) as excinfo:
        await get_agent_id_by_name("test_agent", "test_tenant")
    assert "agent not found" in str(excinfo.value)

    # Test empty agent name
    with pytest.raises(Exception) as excinfo:
        await get_agent_id_by_name("", "test_tenant")
    assert "agent_name required" in str(excinfo.value)


@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.query_sub_agents_id_list')
def test_get_agent_call_relationship_impl_success(mock_query_sub_agents, mock_search_tools, mock_search_agent_info):
    """
    Test successful retrieval of agent call relationship tree.

    This test verifies that:
    1. The function correctly retrieves agent information
    2. Tools are properly normalized and formatted
    3. Sub-agents are recursively collected with their tools
    4. The response structure matches expected format
    """
    # Setup mock data
    mock_agent_info = {
        "agent_id": 1,
        "name": "Test Agent",
        "display_name": "Test Display Name",
        "description": "Test Description"
    }

    mock_tools = [
        {
            "tool_id": 1,
            "name": "Test Tool 1",
            "source": "local",
            "tool_name": "Local Tool"
        },
        {
            "tool_id": 2,
            "name": "Test Tool 2",
            "source": "mcp",
            "tool_name": "MCP Tool"
        },
        {
            "tool_id": 3,
            "name": "Test Tool 3",
            "source": "langchain",
            "tool_name": "LangChain Tool"
        }
    ]

    mock_sub_agent_ids = [2, 3]

    # Setup sub-agent info
    mock_sub_agent_info = {
        "agent_id": 2,
        "name": "Sub Agent 1",
        "display_name": "Sub Display 1"
    }

    mock_sub_tools = [
        {
            "tool_id": 4,
            "name": "Sub Tool 1",
            "source": "local"
        }
    ]

    # Setup mocks
    mock_search_agent_info.side_effect = [mock_agent_info, mock_sub_agent_info]
    mock_search_tools.side_effect = [mock_tools, mock_sub_tools]
    mock_query_sub_agents.return_value = mock_sub_agent_ids

    # Execute
    result = get_agent_call_relationship_impl(
        agent_id=1, tenant_id="test_tenant")

    # Assert
    assert result["agent_id"] == "1"
    assert result["name"] == "Test Display Name"
    assert len(result["tools"]) == 3
    assert len(result["sub_agents"]) == 1

    # Check tool normalization
    assert result["tools"][0]["type"] == "Local"
    assert result["tools"][1]["type"] == "MCP"
    assert result["tools"][2]["type"] == "LangChain"

    # Check sub-agent structure
    sub_agent = result["sub_agents"][0]
    assert sub_agent["agent_id"] == "2"
    assert sub_agent["name"] == "Sub Display 1"
    assert sub_agent["depth"] == 1
    assert len(sub_agent["tools"]) == 1
    assert sub_agent["tools"][0]["type"] == "Local"

    # Verify mock calls
    mock_search_agent_info.assert_called()
    mock_search_tools.assert_called()
    mock_query_sub_agents.assert_called()


@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.query_sub_agents_id_list')
def test_get_agent_call_relationship_impl_with_unknown_source(mock_query_sub_agents, mock_search_tools,
                                                              mock_search_agent_info):
    """
    Test agent call relationship with unknown tool source.

    This test verifies that:
    1. Unknown tool sources are handled gracefully
    2. Tool types are properly formatted for unknown sources
    """
    # Setup mock data
    mock_agent_info = {
        "agent_id": 1,
        "name": "Test Agent",
        "display_name": "Test Display Name"
    }

    mock_tools = [
        {
            "tool_id": 1,
            "name": "Unknown Tool",
            "source": "unknown_source",
            "tool_name": "Unknown Source Tool"
        }
    ]

    # Setup mocks
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = mock_tools
    mock_query_sub_agents.return_value = []

    # Execute
    result = get_agent_call_relationship_impl(
        agent_id=1, tenant_id="test_tenant")

    # Assert
    assert result["tools"][0]["type"] == "Unknown_source"
    assert len(result["sub_agents"]) == 0


@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.query_sub_agents_id_list')
def test_get_agent_call_relationship_impl_with_none_source(mock_query_sub_agents, mock_search_tools,
                                                           mock_search_agent_info):
    """
    Test agent call relationship with None tool source.

    This test verifies that:
    1. None tool sources are handled gracefully
    2. Tool types default to "UNKNOWN" for None sources
    """
    # Setup mock data
    mock_agent_info = {
        "agent_id": 1,
        "name": "Test Agent",
        "display_name": "Test Display Name"
    }

    mock_tools = [
        {
            "tool_id": 1,
            "name": "None Source Tool",
            "source": None,
            "tool_name": "None Source Tool"
        }
    ]

    # Setup mocks
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = mock_tools
    mock_query_sub_agents.return_value = []

    # Execute
    result = get_agent_call_relationship_impl(
        agent_id=1, tenant_id="test_tenant")

    # Assert
    assert result["tools"][0]["type"] == "UNKNOWN"
    assert len(result["sub_agents"]) == 0


@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.query_sub_agents_id_list')
def test_get_agent_call_relationship_impl_with_empty_tools(mock_query_sub_agents, mock_search_tools,
                                                           mock_search_agent_info):
    """
    Test agent call relationship with no tools.

    This test verifies that:
    1. Agents without tools are handled correctly
    2. Empty tool lists don't cause errors
    """
    # Setup mock data
    mock_agent_info = {
        "agent_id": 1,
        "name": "Test Agent",
        "display_name": "Test Display Name"
    }

    # Setup mocks
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = []
    mock_query_sub_agents.return_value = []

    # Execute
    result = get_agent_call_relationship_impl(
        agent_id=1, tenant_id="test_tenant")

    # Assert
    assert result["tools"] == []
    assert len(result["sub_agents"]) == 0


@patch('backend.services.agent_service.search_agent_info_by_agent_id')
def test_get_agent_call_relationship_impl_agent_not_found(mock_search_agent_info):
    """
    Test agent call relationship when agent is not found.

    This test verifies that:
    1. Appropriate error is raised when agent doesn't exist
    2. Error message is descriptive
    """
    # Setup mock to return None (agent not found)
    mock_search_agent_info.return_value = None

    # Execute and assert
    with pytest.raises(ValueError, match="Agent 999 not found"):
        get_agent_call_relationship_impl(agent_id=999, tenant_id="test_tenant")

    mock_search_agent_info.assert_called_once_with(999, "test_tenant")


@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.query_sub_agents_id_list')
def test_get_agent_call_relationship_impl_sub_agent_error_handling(mock_query_sub_agents, mock_search_tools,
                                                                   mock_search_agent_info):
    """
    Test agent call relationship with sub-agent errors.

    This test verifies that:
    1. Errors in sub-agent processing don't crash the entire function
    2. Failed sub-agents are logged and skipped
    3. Other sub-agents continue to be processed
    """
    # Setup mock data
    mock_agent_info = {
        "agent_id": 1,
        "name": "Test Agent",
        "display_name": "Test Agent"
    }

    # Setup mocks - one sub-agent will fail, one will succeed
    mock_search_agent_info.side_effect = [
        mock_agent_info,  # Main agent
        {"agent_id": 2, "name": "Sub Agent 1"},  # First sub-agent (success)
        ValueError("Sub-agent 3 not found")  # Second sub-agent (failure)
    ]

    mock_search_tools.return_value = []
    mock_query_sub_agents.return_value = [2, 3]  # Two sub-agents

    # Execute
    result = get_agent_call_relationship_impl(
        agent_id=1, tenant_id="test_tenant")

    # Assert - should only include the successful sub-agent
    assert len(result["sub_agents"]) == 1
    assert result["sub_agents"][0]["agent_id"] == "2"

    # Verify mock calls
    mock_search_agent_info.assert_called()
    # At least main agent + one sub-agent
    assert mock_search_agent_info.call_count >= 2


@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.query_sub_agents_id_list')
def test_get_agent_call_relationship_impl_tool_name_fallback(mock_query_sub_agents, mock_search_tools,
                                                             mock_search_agent_info):
    """
    Test agent call relationship tool name fallback logic.

    This test verifies that:
    1. Tool names fall back to tool_name if name is not available
    2. Tool names fall back to tool_id if neither name nor tool_name is available
    """
    # Setup mock data
    mock_agent_info = {
        "agent_id": 1,
        "name": "Test Agent",
        "display_name": "Test Agent"
    }

    mock_tools = [
        {
            "tool_id": 1,
            "source": "local"
            # No name or tool_name
        },
        {
            "tool_id": 2,
            "name": "Explicit Name",
            "source": "local"
        },
        {
            "tool_id": 3,
            "tool_name": "Tool Name",
            "source": "local"
            # No name
        }
    ]

    # Setup mocks
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = mock_tools
    mock_query_sub_agents.return_value = []

    # Execute
    result = get_agent_call_relationship_impl(
        agent_id=1, tenant_id="test_tenant")

    # Assert
    assert result["tools"][0]["name"] == "1"  # Fallback to tool_id
    assert result["tools"][1]["name"] == "Explicit Name"  # Use explicit name
    assert result["tools"][2]["name"] == "Tool Name"  # Use tool_name


#############################
# Additional tests for newer logic in agent_service.py
#############################

import backend.services.agent_service as agent_service


@pytest.mark.asyncio
async def test__stream_agent_chunks_persists_and_unregisters(monkeypatch):
    """Ensure _stream_agent_chunks yields chunks, saves assistant messages (when not debug) and always unregisters the run regardless of errors."""
    # Prepare fake AgentRequest
    agent_request = AgentRequest(
        agent_id=1,
        conversation_id=999,
        query="hello",
        history=[],
        minio_files=[],
        is_debug=False,
    )

    # Mock agent_run to yield two chunks
    async def fake_agent_run(*_, **__):
        yield "chunk1"
        yield "chunk2"

    monkeypatch.setitem(sys.modules, "nexent.core.agents.run_agent", MagicMock())
    monkeypatch.setattr(
        "backend.services.agent_service.agent_run", fake_agent_run, raising=False
    )

    # Track calls
    save_calls = []

    def fake_save_messages(*args, **kwargs):
        save_calls.append((args, kwargs))

    monkeypatch.setattr(
        "backend.services.agent_service.save_messages",
        fake_save_messages,
        raising=False,
    )

    unregister_called = {}

    def fake_unregister(conv_id, user_id):
        unregister_called["conv_id"] = conv_id
        unregister_called["user_id"] = user_id

    monkeypatch.setattr(
        "backend.services.agent_service.agent_run_manager.unregister_agent_run",
        fake_unregister,
        raising=False,
    )

    # Collect streamed chunks
    collected = []
    async for out in agent_service._stream_agent_chunks(
        agent_request, "u", "t", MagicMock(), MagicMock()
    ):
        collected.append(out)

    assert collected == [
        "data: chunk1\n\n",
        "data: chunk2\n\n",
    ]  # Prefix added in helper
    assert save_calls, "save_messages should have been called for assistant messages"
    assert unregister_called.get("conv_id") == 999
    assert unregister_called.get("user_id") == "u"


@pytest.mark.asyncio
async def test__stream_agent_chunks_emits_error_chunk_on_run_failure(monkeypatch):
    """When agent_run raises, an error SSE chunk should be emitted and run unregistered."""
    agent_request = AgentRequest(
        agent_id=1,
        conversation_id=1001,
        query="trigger error",
        history=[],
        minio_files=[],
        is_debug=True,  # avoid persisting messages to focus on error path
    )

    async def failing_agent_run(*_, **__):
        raise Exception("oops")

    monkeypatch.setattr(
        "backend.services.agent_service.agent_run", failing_agent_run, raising=False
    )

    called = {"unregistered": None, "user_id": None}

    def fake_unregister(conv_id, user_id):
        called["unregistered"] = conv_id
        called["user_id"] = user_id

    monkeypatch.setattr(
        "backend.services.agent_service.agent_run_manager.unregister_agent_run",
        fake_unregister,
        raising=False,
    )

    # Collect streamed chunks
    collected = []
    async for out in agent_service._stream_agent_chunks(
        agent_request, "u", "t", MagicMock(), MagicMock()
    ):
        collected.append(out)

    # Expect a single error payload chunk and unregister called
    assert collected and collected[0].startswith(
        "data: {") and "\"type\": \"error\"" in collected[0]
    assert called["unregistered"] == 1001
    assert called["user_id"] == "u"


@pytest.mark.asyncio
async def test__stream_agent_chunks_captures_final_answer_and_adds_memory(monkeypatch):
    """Final answer should be captured and appended to memory via add_memory_in_levels."""
    agent_request = AgentRequest(
        agent_id=3,
        conversation_id=3003,
        query="hello",
        history=[],
        minio_files=[],
        is_debug=False,
    )

    async def yield_final_answer(*_, **__):
        yield json.dumps({"type": "token", "content": "hi"}, ensure_ascii=False)
        yield json.dumps({"type": "final_answer", "content": "bye"}, ensure_ascii=False)

    monkeypatch.setattr(
        "backend.services.agent_service.agent_run", yield_final_answer, raising=False
    )

    add_calls = {"args": None, "called": False}

    async def fake_add_memory_in_levels(**kwargs):
        add_calls["args"] = kwargs
        add_calls["called"] = True
        return {"results": [{"ok": True}]}

    monkeypatch.setattr(
        "backend.services.agent_service.add_memory_in_levels",
        fake_add_memory_in_levels,
        raising=False,
    )

    # Memory context with switch ON
    memory_ctx = MagicMock()
    memory_ctx.user_config = MagicMock(
        memory_switch=True,
        agent_share_option="always",
        disable_agent_ids=[],
        disable_user_agent_ids=[],
    )
    memory_ctx.memory_config = {"cfg": 1}
    memory_ctx.tenant_id = "t"
    memory_ctx.user_id = "u"
    memory_ctx.agent_id = 3

    # Capture and await scheduled background task
    task_holder = {"task": None}
    orig_create_task = asyncio.create_task

    def capture_task(coro):
        t = orig_create_task(coro)
        task_holder["task"] = t
        return t

    monkeypatch.setattr(asyncio, "create_task", capture_task)

    # Run stream
    collected = []
    async for out in agent_service._stream_agent_chunks(
        agent_request, "u", "t", MagicMock(query="hello"), memory_ctx
    ):
        collected.append(out)

    # Ensure background task completed
    if task_holder["task"] is not None:
        await task_holder["task"]

    assert add_calls["called"] is True
    assert add_calls["args"]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "bye"},
    ]
    assert set(add_calls["args"]["memory_levels"]) == {"agent", "user_agent"}
    assert add_calls["args"]["memory_config"] == {"cfg": 1}
    assert add_calls["args"]["tenant_id"] == "t"
    assert add_calls["args"]["user_id"] == "u"
    assert add_calls["args"]["agent_id"] == 3


@pytest.mark.asyncio
async def test__stream_agent_chunks_skips_memory_when_switch_off(monkeypatch):
    """When memory switch is off, background memory addition exits early."""
    agent_request = AgentRequest(
        agent_id=4,
        conversation_id=4004,
        query="q",
        history=[],
        minio_files=[],
        is_debug=False,
    )

    async def yield_one(*_, **__):
        yield json.dumps({"type": "final_answer", "content": "ans"}, ensure_ascii=False)

    monkeypatch.setattr(
        "backend.services.agent_service.agent_run", yield_one, raising=False
    )

    called = {"count": 0}

    async def track_add(**kwargs):
        called["count"] += 1
        return {"results": []}

    monkeypatch.setattr(
        "backend.services.agent_service.add_memory_in_levels", track_add, raising=False
    )

    memory_ctx = MagicMock()
    memory_ctx.user_config = MagicMock(memory_switch=False)

    async for _ in agent_service._stream_agent_chunks(
        agent_request, "u", "t", MagicMock(query="q"), memory_ctx
    ):
        pass

    await asyncio.sleep(0)
    assert called["count"] == 0


@pytest.mark.asyncio
async def test__stream_agent_chunks_background_add_exception(monkeypatch):
    """Exceptions in background memory addition should be caught and not crash the stream."""
    agent_request = AgentRequest(
        agent_id=5,
        conversation_id=5005,
        query="q",
        history=[],
        minio_files=[],
        is_debug=False,
    )

    async def yield_final(*_, **__):
        yield json.dumps({"type": "final_answer", "content": "A"}, ensure_ascii=False)

    monkeypatch.setattr(
        "backend.services.agent_service.agent_run", yield_final, raising=False
    )

    async def raise_in_add(**kwargs):
        raise RuntimeError("mem add fail")

    monkeypatch.setattr(
        "backend.services.agent_service.add_memory_in_levels", raise_in_add, raising=False
    )

    memory_ctx = MagicMock()
    memory_ctx.user_config = MagicMock(
        memory_switch=True,
        agent_share_option="always",
        disable_agent_ids=[],
        disable_user_agent_ids=[],
    )

    # Capture and await scheduled background task
    task_holder = {"task": None}
    orig_create_task = asyncio.create_task

    def capture_task(coro):
        t = orig_create_task(coro)
        task_holder["task"] = t
        return t

    monkeypatch.setattr(asyncio, "create_task", capture_task)

    async for _ in agent_service._stream_agent_chunks(
        agent_request, "u", "t", MagicMock(query="q"), memory_ctx
    ):
        pass

    # Let background exception be handled by awaiting the task
    if task_holder["task"] is not None:
        await task_holder["task"]


@pytest.mark.asyncio
async def test__stream_agent_chunks_schedule_task_failure(monkeypatch):
    """Scheduling background task failure should be caught and logged."""
    agent_request = AgentRequest(
        agent_id=6,
        conversation_id=6006,
        query="q",
        history=[],
        minio_files=[],
        is_debug=False,
    )

    async def yield_final(*_, **__):
        yield json.dumps({"type": "final_answer", "content": "A"}, ensure_ascii=False)

    monkeypatch.setattr(
        "backend.services.agent_service.agent_run", yield_final, raising=False
    )

    # Force asyncio.create_task to fail
    def fail_create_task(*_, **__):
        raise RuntimeError("schedule fail")

    monkeypatch.setattr("asyncio.create_task", fail_create_task)

    memory_ctx = MagicMock()
    memory_ctx.user_config = MagicMock(
        memory_switch=True,
        agent_share_option="always",
        disable_agent_ids=[],
        disable_user_agent_ids=[],
    )

    collected = []
    async for out in agent_service._stream_agent_chunks(
        agent_request, "u", "t", MagicMock(query="q"), memory_ctx
    ):
        collected.append(out)

    assert collected  # Stream still produced data without crashing


def test_insert_related_agent_impl_failure_returns_400():
    """When insertion fails, should return 400 JSONResponse."""
    with patch(
        "backend.services.agent_service.query_sub_agents_id_list", return_value=[]
    ) as _, patch(
        "backend.services.agent_service.insert_related_agent", return_value=False
    ) as __:
        resp = insert_related_agent_impl(
            parent_agent_id=1, child_agent_id=2, tenant_id="t")
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_generate_stream_with_memory_unexpected_exception_emits_error(monkeypatch):
    """Generic exceptions should emit an error SSE chunk and stop."""
    agent_request = AgentRequest(
        agent_id=9,
        conversation_id=9009,
        query="q",
        history=[],
        minio_files=[],
        is_debug=False,
    )

    # Cause an unexpected error inside the try block
    monkeypatch.setattr(
        "backend.services.agent_service.build_memory_context",
        MagicMock(side_effect=Exception("unexpected")),
        raising=False,
    )

    out = []
    async for d in agent_service.generate_stream_with_memory(
        agent_request, user_id="u", tenant_id="t"
    ):
        out.append(d)

    assert out and out[0].startswith(
        "data: {") and "\"type\": \"error\"" in out[0]

async def test_generate_stream_no_memory_registers_and_streams(monkeypatch):
    """generate_stream_no_memory should prepare run info, register it and stream data without memory tokens."""
    # Prepare AgentRequest & Request
    agent_request = AgentRequest(
        agent_id=2,
        conversation_id=555,
        query="test",
        history=[],
        minio_files=[],
        is_debug=False,
    )
    http_request = Request(scope={"type": "http", "headers": []})

    # Monkeypatch helpers
    monkeypatch.setattr(
        "backend.services.agent_service.build_memory_context",
        MagicMock(return_value=MagicMock()),
        raising=False,
    )
    monkeypatch.setattr(
        "backend.services.agent_service.create_agent_run_info",
        AsyncMock(return_value=MagicMock()),
        raising=False,
    )
    
    registered = {}

    def fake_register(conv_id, run_info, user_id):
        registered["conv_id"] = conv_id
        registered["run_info"] = run_info
        registered["user_id"] = user_id

    monkeypatch.setattr(
        "backend.services.agent_service.agent_run_manager.register_agent_run",
        fake_register,
        raising=False,
    )

    # Stream helper will yield chunks
    async def fake_stream_chunks(*_, **__):
        yield "data: body1\n\n"
        yield "data: body2\n\n"

    monkeypatch.setattr(
        "backend.services.agent_service._stream_agent_chunks",
        fake_stream_chunks,
        raising=False,
    )

    # Collect output
    collected = []
    async for d in agent_service.generate_stream_no_memory(
        agent_request, user_id="u", tenant_id="t"
    ):
        collected.append(d)

    assert registered.get("conv_id") == 555
    assert registered.get("user_id") == "u"
    assert registered.get("run_info") is not None
    assert collected == ["data: body1\n\n", "data: body2\n\n"]


@pytest.mark.asyncio
@patch(
    "backend.services.agent_service._resolve_user_tenant_language",
    return_value=(None, None, "en"),
)
@patch("backend.services.agent_service.build_memory_context")
@patch("backend.services.agent_service.save_messages")
@patch("backend.services.agent_service.generate_stream_no_memory")
async def test_run_agent_stream_no_memory(
    mock_gen_no_mem,
    mock_save_messages,
    mock_build_mem_ctx,
    mock_resolve,
    mock_agent_request,
    mock_http_request,
):
    async def mock_stream():
        yield "c1"

    mock_gen_no_mem.return_value = mock_stream()
    mock_build_mem_ctx.return_value = MagicMock(
        user_config=MagicMock(memory_switch=False)
    )

    resp = await run_agent_stream(mock_agent_request, mock_http_request, "Bearer token")
    assert isinstance(resp, StreamingResponse)
    mock_gen_no_mem.assert_called_once_with(
        mock_agent_request,
        user_id=None,
        tenant_id=None,
        language="en",
    )


@pytest.mark.asyncio
@patch(
    "backend.services.agent_service._resolve_user_tenant_language",
    return_value=("u", "t", "en"),
)
@patch("backend.services.agent_service.build_memory_context")
@patch("backend.services.agent_service.save_messages")
@patch("backend.services.agent_service.generate_stream_no_memory")
async def test_run_agent_stream_skip_user_save(
    mock_gen_no_mem,
    mock_save_messages,
    mock_build_mem_ctx,
    mock_resolve,
    mock_agent_request,
    mock_http_request,
):
    async def mock_stream():
        yield "c1"

    mock_gen_no_mem.return_value = mock_stream()
    mock_build_mem_ctx.return_value = MagicMock(
        user_config=MagicMock(memory_switch=False)
    )

    resp = await run_agent_stream(
        mock_agent_request, mock_http_request, "Bearer token", skip_user_save=True
    )
    assert isinstance(resp, StreamingResponse)
    # Should not save user message when skip_user_save=True
    mock_save_messages.assert_not_called()


@pytest.mark.asyncio
async def test_generate_stream_with_memory_emits_tokens_and_unregisters(monkeypatch):
    """generate_stream_with_memory emits start/done tokens and unregisters preprocess task."""
    # Prepare AgentRequest & Request
    agent_request = AgentRequest(
        agent_id=7,
        conversation_id=777,
        query="q",
        history=[],
        minio_files=[],
        is_debug=False,
    )
    http_request = Request(scope={"type": "http", "headers": []})

    # Enable memory switch in preview
    monkeypatch.setattr(
        "backend.services.agent_service.build_memory_context",
        MagicMock(return_value=MagicMock(user_config=MagicMock(memory_switch=True))),
        raising=False,
    )

    # Prepare run returned values
    monkeypatch.setattr(
        "backend.services.agent_service.prepare_agent_run",
        AsyncMock(return_value=(MagicMock(), MagicMock())),
        raising=False,
    )

    # Stream chunks from helper
    async def fake_chunks(*_, **__):
        yield "data: bodyA\n\n"
        yield "data: bodyB\n\n"

    monkeypatch.setattr(
        "backend.services.agent_service._stream_agent_chunks",
        fake_chunks,
        raising=False,
    )

    # Track preprocess register/unregister
    calls = {"registered": None, "unregistered": None}

    def fake_register(task_id, conv_id, task):
        calls["registered"] = (task_id, conv_id, bool(task))

    def fake_unregister(task_id):
        calls["unregistered"] = task_id

    monkeypatch.setattr(
        "backend.services.agent_service.preprocess_manager.register_preprocess_task",
        fake_register,
        raising=False,
    )
    monkeypatch.setattr(
        "backend.services.agent_service.preprocess_manager.unregister_preprocess_task",
        fake_unregister,
        raising=False,
    )

    # Collect output
    out = []
    async for d in agent_service.generate_stream_with_memory(
        agent_request, user_id="u", tenant_id="t"
    ):
        out.append(d)

    # Expect start and done memory tokens then body chunks
    assert any("memory_search" in s and "<MEM_START>" in s for s in out)
    assert any("memory_search" in s and "<MEM_DONE>" in s for s in out)
    assert "data: bodyA\n\n" in out and "data: bodyB\n\n" in out
    # Unregister must be called
    assert calls["registered"] is not None
    assert calls["unregistered"] is not None


@pytest.mark.asyncio
async def test_generate_stream_with_memory_fallback_on_failure(monkeypatch):
    """generate_stream_with_memory should emit fail token and fall back when memory prep fails."""
    agent_request = AgentRequest(
        agent_id=8,
        conversation_id=888,
        query="q2",
        history=[],
        minio_files=[],
        is_debug=False,
    )
    http_request = Request(scope={"type": "http", "headers": []})

    # Enable memory
    monkeypatch.setattr(
        "backend.services.agent_service.build_memory_context",
        MagicMock(return_value=MagicMock(user_config=MagicMock(memory_switch=True))),
        raising=False,
    )

    # Force prepare_agent_run to raise, which will be normalized
    async def raise_prepare(*_, **__):
        raise Exception("prep failed")

    monkeypatch.setattr(
        "backend.services.agent_service.prepare_agent_run",
        raise_prepare,
        raising=False,
    )

    # Fallback generator
    async def fallback_gen(*_, **__):
        yield "data: fb1\n\n"

    monkeypatch.setattr(
        "backend.services.agent_service.generate_stream_no_memory",
        fallback_gen,
        raising=False,
    )

    # Track preprocess unregister
    called = {"unregistered": False}

    def fake_unregister(task_id):
        called["unregistered"] = True

    monkeypatch.setattr(
        "backend.services.agent_service.preprocess_manager.unregister_preprocess_task",
        fake_unregister,
        raising=False,
    )

    out = []
    async for d in agent_service.generate_stream_with_memory(
        agent_request, user_id="u", tenant_id="t"
    ):
        out.append(d)

    assert any("memory_search" in s and "<MEM_FAILED>" in s for s in out)
    assert "data: fb1\n\n" in out
    assert called["unregistered"]


@pytest.mark.asyncio
async def test_list_all_agent_info_impl_with_disabled_agents():
    """
    Test list_all_agent_info_impl with disabled agents.
    
    This test verifies that:
    1. Agents with enabled=False are skipped and not included in the result
    2. Only enabled agents are processed and returned
    """
    # Setup mock agents with mixed enabled/disabled states
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Enabled Agent 1",
            "display_name": "Display Enabled Agent 1",
            "description": "First enabled agent",
            "enabled": True
        },
        {
            "agent_id": 2,
            "name": "Disabled Agent",
            "display_name": "Display Disabled Agent",
            "description": "Disabled agent that should be skipped",
            "enabled": False
        },
        {
            "agent_id": 3,
            "name": "Enabled Agent 2",
            "display_name": "Display Enabled Agent 2",
            "description": "Second enabled agent",
            "enabled": True
        }
    ]

    # Setup mock tools
    mock_tools = [
        {"tool_id": 101, "name": "Tool 1"},
        {"tool_id": 102, "name": "Tool 2"}
    ]

    with patch('backend.services.agent_service.query_all_agent_info_by_tenant_id') as mock_query_agents, \
            patch('backend.services.agent_service.search_tools_for_sub_agent') as mock_search_tools, \
            patch('backend.services.agent_service.check_tool_is_available') as mock_check_tools:
        # Configure mocks
        mock_query_agents.return_value = mock_agents
        mock_search_tools.return_value = mock_tools
        mock_check_tools.return_value = [True, True]  # All tools are available

        # Execute
        result = await list_all_agent_info_impl(tenant_id="test_tenant")

        # Assert - only enabled agents should be in the result
        assert len(result) == 2
        assert result[0]["agent_id"] == 1
        assert result[0]["name"] == "Enabled Agent 1"
        assert result[0]["display_name"] == "Display Enabled Agent 1"
        assert result[0]["is_available"] == True
        
        assert result[1]["agent_id"] == 3
        assert result[1]["name"] == "Enabled Agent 2"
        assert result[1]["display_name"] == "Display Enabled Agent 2"
        assert result[1]["is_available"] == True

        # Verify mock calls
        mock_query_agents.assert_called_once_with(tenant_id="test_tenant")
        # search_tools_for_sub_agent should only be called for enabled agents (2 calls, not 3)
        assert mock_search_tools.call_count == 2
        mock_search_tools.assert_has_calls([
            call(agent_id=1, tenant_id="test_tenant"),
            call(agent_id=3, tenant_id="test_tenant")
        ])
        # check_tool_is_available should only be called for enabled agents (2 calls, not 3)
        assert mock_check_tools.call_count == 2


@pytest.mark.asyncio
async def test_list_all_agent_info_impl_all_disabled_agents():
    """
    Test list_all_agent_info_impl with all agents disabled.
    
    This test verifies that:
    1. When all agents are disabled, an empty list is returned
    2. No tool queries are made since no agents are processed
    """
    # Setup mock agents - all disabled
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Disabled Agent 1",
            "display_name": "Display Disabled Agent 1",
            "description": "First disabled agent",
            "enabled": False
        },
        {
            "agent_id": 2,
            "name": "Disabled Agent 2",
            "display_name": "Display Disabled Agent 2",
            "description": "Second disabled agent",
            "enabled": False
        }
    ]

    with patch('backend.services.agent_service.query_all_agent_info_by_tenant_id') as mock_query_agents, \
            patch('backend.services.agent_service.search_tools_for_sub_agent') as mock_search_tools, \
            patch('backend.services.agent_service.check_tool_is_available') as mock_check_tools:
        # Configure mocks
        mock_query_agents.return_value = mock_agents

        # Execute
        result = await list_all_agent_info_impl(tenant_id="test_tenant")

        # Assert - no agents should be in the result
        assert len(result) == 0
        assert result == []

        # Verify mock calls
        mock_query_agents.assert_called_once_with(tenant_id="test_tenant")
        # No tool queries should be made since no agents are enabled
        mock_search_tools.assert_not_called()
        mock_check_tools.assert_not_called()