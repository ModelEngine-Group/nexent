import pytest
import sys
from unittest.mock import patch, MagicMock, mock_open, call, Mock, AsyncMock

# Mock boto3 before importing the module under test
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Mock Elasticsearch
elasticsearch_client_mock = MagicMock()
patch('elasticsearch._sync.client.Elasticsearch', return_value=elasticsearch_client_mock).start()
patch('elasticsearch.Elasticsearch', return_value=elasticsearch_client_mock).start()

# Mock ElasticSearchCore
elasticsearch_core_mock = MagicMock()
patch('sdk.nexent.vector_database.elasticsearch_core.ElasticSearchCore', return_value=elasticsearch_core_mock).start()

# Mock memory-related modules - removed module-level patches to avoid conflicts with test-level patches

# Import the services
from backend.services.agent_service import (
    get_enable_tool_id_by_agent_id,
    get_creating_sub_agent_id_service,
    get_agent_info_impl,
    get_creating_sub_agent_info_impl,
    update_agent_info_impl,
    delete_agent_impl,
    export_agent_impl,
    export_agent_by_agent_id,
    import_agent_impl,
    import_agent_by_agent_id,
    load_default_agents_json_file,
    list_all_agent_info_impl,
    insert_related_agent_impl,
    clear_agent_memory
)
from backend.consts.model import AgentInfoRequest, ExportAndImportAgentInfo, ExportAndImportDataFormat, ToolInstanceInfoRequest, ToolConfig


# Setup and teardown for each test
@pytest.fixture(autouse=True)
def reset_mocks():
    """Reset all mocks before each test to ensure a clean test environment."""
    yield


def test_get_enable_tool_id_by_agent_id():
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
            tenant_id="test_tenant", 
            user_id="test_user"
        )
        
        # Assert
        assert sorted(result) == [1, 3, 4]
        mock_query.assert_called_once_with(
            agent_id=123,
            tenant_id="test_tenant", 
            user_id=None
        )


@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.search_blank_sub_agent_by_main_agent_id')
def test_get_creating_sub_agent_id_service_existing_agent(mock_search, mock_create):
    """
    Test retrieving an existing sub-agent ID associated with a main agent.
    
    This test verifies that when a sub-agent already exists for a main agent:
    1. The function returns the existing sub-agent ID
    2. No new agent is created (create_agent is not called)
    """
    # Setup - existing sub agent found
    mock_search.return_value = 456
    
    # Execute
    result = get_creating_sub_agent_id_service(
        tenant_id="test_tenant", 
        user_id="test_user"
    )
    
    # Assert
    assert result == 456
    mock_search.assert_called_once_with(tenant_id="test_tenant")
    mock_create.assert_not_called()


@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.search_blank_sub_agent_by_main_agent_id')
def test_get_creating_sub_agent_id_service_new_agent(mock_search, mock_create):
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
    result = get_creating_sub_agent_id_service(
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
def test_get_agent_info_impl_success(mock_search_agent_info, mock_search_tools, mock_query_sub_agents_id):
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
    result = get_agent_info_impl(agent_id=123, tenant_id="test_tenant")
    
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
    mock_search_tools.assert_called_once_with(agent_id=123, tenant_id="test_tenant")
    mock_query_sub_agents_id.assert_called_once_with(main_agent_id=123, tenant_id="test_tenant")


@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.get_enable_tool_id_by_agent_id')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@patch('backend.services.agent_service.get_creating_sub_agent_id_service')
@patch('backend.services.agent_service.get_current_user_id')
def test_get_creating_sub_agent_info_impl_success(mock_get_current_user_id, mock_get_creating_sub_agent,
                                                 mock_search_agent_info, mock_get_enable_tools, mock_query_sub_agents_id):
    """
    Test successful retrieval of creating sub-agent information.
    
    This test verifies that:
    1. The function correctly gets the current user and tenant IDs
    2. It retrieves or creates the sub-agent ID
    3. It fetches the sub-agent's information and enabled tools
    4. It returns a complete data structure with the sub-agent information
    """
    # Setup
    mock_get_current_user_id.return_value = ("test_user", "test_tenant")
    mock_get_creating_sub_agent.return_value = 456
    mock_search_agent_info.return_value = {
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
    result = get_creating_sub_agent_info_impl(authorization="Bearer token")
    
    # Assert
    expected_result = {
        "agent_id": 456,
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
@patch('backend.services.agent_service.get_current_user_id')
def test_update_agent_info_impl_success(mock_get_current_user_id, mock_update_agent):
    """
    Test successful update of agent information.
    
    This test verifies that:
    1. The function correctly gets the current user and tenant IDs
    2. It calls the update_agent function with the correct parameters
    """
    # Setup
    mock_get_current_user_id.return_value = ("test_user", "test_tenant")
    request = AgentInfoRequest(
        agent_id=123,
        model_name="gpt-4",
        business_description="Updated agent",
        display_name="Updated Display Name"
    )
    
    # Execute
    update_agent_info_impl(request, authorization="Bearer token")
    
    # Assert
    mock_update_agent.assert_called_once_with(123, request, "test_tenant", "test_user")


@patch('backend.services.agent_service.delete_all_related_agent')
@patch('backend.services.agent_service.delete_agent_by_id')
@patch('backend.services.agent_service.get_current_user_id')
@pytest.mark.asyncio
async def test_delete_agent_impl_success(mock_get_current_user_id, mock_delete_agent, mock_delete_related):
    """
    Test successful deletion of an agent.
    
    This test verifies that:
    1. The function correctly gets the current user and tenant IDs
    2. It calls the delete_agent_by_id function with the correct parameters
    3. It also deletes all related agent relationships
    """
    # Setup
    mock_get_current_user_id.return_value = ("test_user", "test_tenant")
    
    # Execute
    await delete_agent_impl(123, authorization="Bearer token")
    
    # Assert
    mock_delete_agent.assert_called_once_with(123, "test_tenant", "test_user")
    mock_delete_related.assert_called_once_with(123, "test_tenant")


@patch('backend.services.agent_service.search_agent_info_by_agent_id')
def test_get_agent_info_impl_exception_handling(mock_search_agent_info):
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
        get_agent_info_impl(agent_id=123, tenant_id="test_tenant")
    
    assert "Failed to get agent info" in str(context.value)


@patch('backend.services.agent_service.update_agent')
@patch('backend.services.agent_service.get_current_user_id')
def test_update_agent_info_impl_exception_handling(mock_get_current_user_id, mock_update_agent):
    """
    Test exception handling in update_agent_info_impl function.
    
    This test verifies that:
    1. When an exception occurs during agent info update
    2. The function raises a ValueError with an appropriate message
    """
    # Setup
    mock_get_current_user_id.return_value = ("test_user", "test_tenant")
    mock_update_agent.side_effect = Exception("Update failed")
    request = AgentInfoRequest(agent_id=123, model_name="gpt-4", display_name="Test Display Name")
    
    # Execute & Assert
    with pytest.raises(ValueError) as context:
        update_agent_info_impl(request, authorization="Bearer token")
    
    assert "Failed to update agent info" in str(context.value)
    

@patch('backend.services.agent_service.delete_agent_by_id')
@patch('backend.services.agent_service.get_current_user_id')
@pytest.mark.asyncio
async def test_delete_agent_impl_exception_handling(mock_get_current_user_id, mock_delete_agent):
    """
    Test exception handling in delete_agent_impl function.
    
    This test verifies that:
    1. When an exception occurs during agent deletion
    2. The function raises a ValueError with an appropriate message
    """
    # Setup
    mock_get_current_user_id.return_value = ("test_user", "test_tenant")
    mock_delete_agent.side_effect = Exception("Delete failed")
    
    # Execute & Assert
    with pytest.raises(ValueError) as context:
        await delete_agent_impl(123, authorization="Bearer token")
    
    assert "Failed to delete agent" in str(context.value)


@patch('backend.services.agent_service.ExportAndImportDataFormat')
@patch('backend.services.agent_service.export_agent_by_agent_id')
@patch('backend.services.agent_service.get_current_user_id')
@pytest.mark.asyncio
async def test_export_agent_impl_success(mock_get_current_user_id, mock_export_agent_by_id, mock_export_data_format):
    """
    Test successful export of agent information.
    """
    # Setup
    mock_get_current_user_id.return_value = ("test_user", "test_tenant")
    
    # Create a proper ExportAndImportAgentInfo object
    mock_agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="Test Agent",
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
        }
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
    
    # The agent_info should contain the ExportAndImportAgentInfo data
    agent_data = result["agent_info"]["123"]
    assert agent_data["name"] == "Test Agent"
    assert agent_data["business_description"] == "For testing purposes"
    assert agent_data["agent_id"] == 123
    assert len(agent_data["tools"]) == 0
    
    # Verify function calls
    mock_get_current_user_id.assert_called_once_with("Bearer token")
    mock_export_agent_by_id.assert_called_once_with(agent_id=123, tenant_id="test_tenant", user_id="test_user")
    mock_export_data_format.assert_called_once()


@patch('backend.services.agent_service.search_agent_info_by_agent_id')
def test_get_agent_info_impl_with_tool_error(mock_search_agent_info):
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
        result = get_agent_info_impl(agent_id=123, tenant_id="test_tenant")
        
        # Assert
        assert result["agent_id"] == 123
        assert result["tools"] == []
        assert result["sub_agent_id_list"] == []
        mock_search_agent_info.assert_called_once_with(123, "test_tenant")


def test_list_all_agent_info_impl_success():
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
            "description": "First test agent"
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Second test agent"
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
        result = list_all_agent_info_impl(tenant_id="test_tenant", user_id="test_user")
        
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


def test_list_all_agent_info_impl_with_unavailable_tools():
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
            "description": "Agent with available tools"
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Agent with unavailable tools"
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
        result = list_all_agent_info_impl(tenant_id="test_tenant", user_id="test_user")
        
        # Assert
        assert len(result) == 2
        assert result[0]["is_available"] == True
        assert result[1]["is_available"] == False
        
        # Verify mock calls
        mock_query_agents.assert_called_once_with(tenant_id="test_tenant")
        assert mock_search_tools.call_count == 2
        assert mock_check_tools.call_count == 2


def test_list_all_agent_info_impl_query_error():
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
            list_all_agent_info_impl(tenant_id="test_tenant", user_id="test_user")
        
        assert "Failed to query all agent info" in str(context.value)
        mock_query_agents.assert_called_once_with(tenant_id="test_tenant")


@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.create_tool_config_list')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_export_agent_by_agent_id_success(mock_search_agent_info, mock_create_tool_config, mock_query_sub_agents_id):
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
            output_type="output type description"
        ),
        ToolConfig(
            class_name="KnowledgeBaseSearchTool",
            name="Knowledge Search",
            source="source2",
            params={"param2": "value2"},
            metadata={"some": "data"},
            description="Knowledge base search tool",
            inputs="search query",
            output_type="search results"
        )
    ]
    mock_create_tool_config.return_value = mock_tools
    
    mock_sub_agent_ids = [456, 789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids
    
    # Execute
    result = await export_agent_by_agent_id(
        agent_id=123,
        tenant_id="test_tenant",
        user_id="test_user"
    )
    
    # Assert
    assert result.agent_id == 123
    assert result.name == "Test Agent"
    assert result.business_description == "For testing purposes"
    assert len(result.tools) == 2
    assert result.managed_agents == mock_sub_agent_ids
    
    # Verify KnowledgeBaseSearchTool metadata is empty
    knowledge_tool = next(tool for tool in result.tools if tool.class_name == "KnowledgeBaseSearchTool")
    assert knowledge_tool.metadata == {}
    
    # Verify function calls
    mock_search_agent_info.assert_called_once_with(agent_id=123, tenant_id="test_tenant")
    mock_create_tool_config.assert_called_once_with(agent_id=123, tenant_id="test_tenant", user_id="test_user")
    mock_query_sub_agents_id.assert_called_once_with(main_agent_id=123, tenant_id="test_tenant")


@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@pytest.mark.asyncio
async def test_import_agent_by_agent_id_success(mock_query_all_tools, mock_create_agent, mock_create_tool):
    """
    Test successful import of agent by agent ID.
    
    This test verifies that:
    1. The function correctly validates tools exist in the database
    2. It validates agent parameters
    3. It creates a new agent with correct information
    4. It creates tool instances for the agent
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
        output_type="output type description"
    )
    
    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="valid_agent_name",
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
    mock_create_tool.assert_called_once()


@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
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
    mock_query_sub_agents_id.return_value = [789]  # Child agent has different sub-agents
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
        [123],  # Child agent 456 has parent agent 123 as its sub-agent (circular)
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
        {"deleted_count": 3}                      # user_agent-level memory succeeds
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
    

if __name__ == '__main__':
    pytest.main()