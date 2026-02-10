import sys
import asyncio
import json
from contextlib import contextmanager
from unittest.mock import patch, MagicMock, mock_open, call, Mock, AsyncMock
import os

import pytest
from fastapi.responses import StreamingResponse
from fastapi import Request
from nexent.core.agents.agent_model import ToolConfig

from backend.consts.model import (
    AgentNameBatchCheckItem,
    AgentNameBatchCheckRequest,
    AgentNameBatchRegenerateItem,
    AgentNameBatchRegenerateRequest,
)


# Patch environment variables before any imports that might use them
# Environment variables are now configured in conftest.py

# Mock boto3 before importing the module under test
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()

# Mock external dependencies before importing backend modules that might initialize them
# Mock create_engine to prevent database connection attempts
mock_engine = MagicMock()
mock_session_maker = MagicMock()
mock_db_session = MagicMock()
mock_session_maker.return_value = mock_db_session

# Mock PostgresClient to prevent database connection attempts
# Create a mock class that returns the same instance (singleton pattern)
mock_postgres_client = MagicMock()
mock_postgres_client.session_maker = mock_session_maker
mock_postgres_client_class = MagicMock(return_value=mock_postgres_client)

# Mock get_db_session context manager - create a proper context manager mock
def mock_get_db_session(db_session=None):
    session = mock_db_session if db_session is None else db_session
    @contextmanager
    def _mock_context():
        yield session
    return _mock_context()

with patch('sqlalchemy.create_engine', return_value=mock_engine), \
     patch('backend.database.client.PostgresClient', new=mock_postgres_client_class), \
     patch('backend.database.client.get_db_session', side_effect=mock_get_db_session), \
     patch('backend.database.client.MinioClient', return_value=minio_client_mock) as minio_mock, \
     patch('elasticsearch.Elasticsearch', return_value=MagicMock()) as es_mock:

    import backend.services.agent_service as agent_service
    from backend.services.agent_service import update_agent_info_impl
    from backend.services.agent_service import get_creating_sub_agent_info_impl
    from backend.services.agent_service import list_all_agent_info_impl
    from backend.services.agent_service import get_agent_info_impl
    from backend.services.agent_service import get_creating_sub_agent_id_service
    from backend.services.agent_service import get_enable_tool_id_by_agent_id
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
        _resolve_user_tenant_language,
        _apply_duplicate_name_availability_rules,
        _check_single_model_availability,
        _normalize_language_key,
        _render_prompt_template,
        _format_existing_values,
        _generate_unique_agent_name_with_suffix,
        _generate_unique_display_name_with_suffix,
        _generate_unique_value_with_suffix,
        _regenerate_agent_value_with_llm,
        clear_agent_new_mark_impl,
    )
    from consts.model import ExportAndImportAgentInfo, ExportAndImportDataFormat, MCPInfo, AgentRequest

    # Ensure db_client is set to our mock after import
    import backend.database.client as db_client_module
    db_client_module.db_client = mock_postgres_client

# Mock Elasticsearch (already done in the import section above, but keeping for reference)
elasticsearch_client_mock = MagicMock()


# Mock memory-related modules
nexent_mock = MagicMock()
sys.modules['nexent'] = nexent_mock
sys.modules['nexent.core'] = MagicMock()
sys.modules['nexent.core.agents'] = MagicMock()
# Don't mock agent_model yet, we need to import ToolConfig first
sys.modules['nexent.memory'] = MagicMock()
sys.modules['nexent.memory.memory_service'] = MagicMock()

# Mock monitoring modules
monitoring_manager_mock = MagicMock()

# Define a decorator that simply returns the original function unchanged


def pass_through_decorator(*args, **kwargs):
    def decorator(func):
        return func
    return decorator


monitoring_manager_mock.monitor_endpoint = pass_through_decorator
monitoring_manager_mock.monitor_llm_call = pass_through_decorator
monitoring_manager_mock.setup_fastapi_app = MagicMock(return_value=True)
monitoring_manager_mock.configure = MagicMock()
monitoring_manager_mock.add_span_event = MagicMock()
monitoring_manager_mock.set_span_attributes = MagicMock()

# Mock nexent.monitor modules
sys.modules['nexent.monitor'] = MagicMock()
sys.modules['nexent.monitor.monitoring'] = MagicMock()
sys.modules['nexent.monitor'].get_monitoring_manager = lambda: monitoring_manager_mock
sys.modules['nexent.monitor'].monitoring_manager = monitoring_manager_mock

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
# Mock utils.monitoring to return our monitoring_manager_mock
utils_monitoring_mock = MagicMock()
utils_monitoring_mock.monitoring_manager = monitoring_manager_mock
utils_monitoring_mock.setup_fastapi_app = MagicMock(return_value=True)
sys.modules['utils.monitoring'] = utils_monitoring_mock
sys.modules['agents.agent_run_manager'] = MagicMock()
sys.modules['agents.preprocess_manager'] = MagicMock()
sys.modules['nexent.core.agents.run_agent'] = MagicMock()


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


@patch('backend.services.agent_service.check_agent_availability')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_get_agent_info_impl_success(mock_search_agent_info, mock_search_tools, mock_query_sub_agents_id, mock_get_model_by_model_id, mock_check_availability):
    """
    Test successful retrieval of an agent's information by ID.

    This test verifies that:
    1. The function correctly retrieves the agent's basic information
    2. It fetches the associated tools
    3. It gets the sub-agent ID list
    4. It returns a complete agent information structure with availability status
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent"
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1"}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [456, 789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock get_model_by_model_id - return None for model_id=None
    mock_get_model_by_model_id.return_value = None

    # Mock check_agent_availability - agent is available
    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "model_name": None,
        "business_logic_model_name": None,
        "is_available": True,
        "unavailable_reasons": []
    }
    assert result == expected_result
    mock_search_agent_info.assert_called_once_with(123, "test_tenant", 0)
    mock_search_tools.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant")
    mock_query_sub_agents_id.assert_called_once_with(
        main_agent_id=123, tenant_id="test_tenant")
    mock_check_availability.assert_called_once()


@patch('backend.services.agent_service.check_agent_availability')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_version_no(mock_search_agent_info, mock_search_tools, mock_query_sub_agents_id, mock_get_model_by_model_id, mock_check_availability):
    """
    Test get_agent_info_impl with explicit version_no parameter.

    This test verifies that:
    1. The function correctly passes version_no to search_agent_info_by_agent_id
    2. It works correctly when version_no is explicitly provided
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent"
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1"}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [456, 789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock get_model_by_model_id - return None for model_id=None
    mock_get_model_by_model_id.return_value = None

    # Mock check_agent_availability - agent is available
    mock_check_availability.return_value = (True, [])

    # Execute with explicit version_no
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant", version_no=5)

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "model_name": None,
        "business_logic_model_name": None,
        "is_available": True,
        "unavailable_reasons": []
    }
    assert result == expected_result
    # Verify version_no is passed correctly
    mock_search_agent_info.assert_called_once_with(123, "test_tenant", 5)
    mock_search_tools.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant")
    mock_query_sub_agents_id.assert_called_once_with(
        main_agent_id=123, tenant_id="test_tenant")
    mock_check_availability.assert_called_once()


@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.get_enable_tool_id_by_agent_id')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@patch('backend.services.agent_service.get_creating_sub_agent_id_service')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_get_creating_sub_agent_info_impl_success(mock_get_current_user_info, mock_get_creating_sub_agent,
                                                        mock_search_agent_info, mock_get_enable_tools,
                                                        mock_query_sub_agents_id, mock_get_model_by_model_id):
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
        "model_id": None,
        "model_name": "test_model",
        "name": "agent_name",
        "display_name": "display name",
        "description": "description...",
        "max_steps": 5,
        "business_description": "Sub agent",
        "duty_prompt": "Sub duty prompt",
        "constraint_prompt": "Sub constraint prompt",
        "few_shots_prompt": "Sub few shots prompt"
    }
    mock_get_enable_tools.return_value = [1, 2]
    mock_query_sub_agents_id.return_value = [789]

    # Mock get_model_by_model_id - return None for model_id=None
    mock_get_model_by_model_id.return_value = None

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
        "model_name": "test_model",
        "model_id": None,
        "max_steps": 5,
        "business_description": "Sub agent",
        "duty_prompt": "Sub duty prompt",
        "constraint_prompt": "Sub constraint prompt",
        "few_shots_prompt": "Sub few shots prompt",
        "sub_agent_id_list": [789]
    }
    assert result == expected_result


@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.query_tool_instances_by_id')
@patch('backend.services.agent_service.query_all_tools')
@patch('backend.services.agent_service.update_agent')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_update_agent_info_impl_success(mock_get_current_user_info, mock_update_agent,
                                                mock_query_all_tools, mock_query_tool_instances_by_id,
                                                mock_create_or_update_tool):
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
    request.model_id = None
    request.business_description = "Updated agent"
    request.display_name = "Updated Display Name"
    request.enabled_tool_ids = None  # Explicitly set to None to avoid tool handling path

    # Execute
    await update_agent_info_impl(request, authorization="Bearer token")

    # Assert
    mock_update_agent.assert_called_once_with(
        123, request, "test_user")


@patch('backend.services.agent_service.delete_tools_by_agent_id')
@patch('backend.services.agent_service.delete_agent_relationship')
@patch('backend.services.agent_service.delete_agent_by_id')
@pytest.mark.asyncio
async def test_delete_agent_impl_success(mock_delete_agent, mock_delete_related,
                                         mock_delete_tools):
    """
    Test successful deletion of an agent.

    This test verifies that:
    1. It calls the delete_agent_by_id function with the correct parameters
    2. It also deletes all related agent relationships
    3. It deletes all tools associated with the agent
    """
    # Execute
    await delete_agent_impl(123, "test_tenant", "test_user")

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
    # Verify version_no parameter is passed (default value 0)
    mock_search_agent_info.assert_called_once_with(123, "test_tenant", 0)


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
    request.model_id = None
    request.display_name = "Test Display Name"
    request.enabled_tool_ids = None
    request.related_agent_ids = None

    # Execute & Assert
    with pytest.raises(ValueError) as context:
        await update_agent_info_impl(request, authorization="Bearer token")

    assert "Failed to update agent info" in str(context.value)


@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.query_tool_instances_by_agent_id')
@patch('backend.services.agent_service.update_agent')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_update_agent_info_impl_with_enabled_tool_ids(
    mock_get_current_user_info,
    mock_update_agent,
    mock_query_tool_instances_by_agent_id,
    mock_create_or_update_tool
):
    """
    Test update_agent_info_impl with enabled_tool_ids parameter.

    This test verifies that:
    1. When enabled_tool_ids is provided, existing tools are disabled if not selected
    2. Selected tools are enabled (create or update)
    3. Existing tool params are preserved
    """
    # Setup
    mock_get_current_user_info.return_value = ("test_user", "test_tenant", "en")

    # Mock existing tool instances for this agent
    mock_query_tool_instances_by_agent_id.return_value = [
        {"tool_id": 1, "params": {"key1": "value1"}},  # Existing tool with params
    ]

    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = [1, 2]  # Enable tools 1 and 2
    request.related_agent_ids = None

    # Execute
    result = await update_agent_info_impl(request, authorization="Bearer token")

    # Assert
    assert result["agent_id"] == 123
    mock_update_agent.assert_called_once()

    # Verify tools were updated: tool 1 and 2 enabled
    assert mock_create_or_update_tool.call_count == 2

    # Check tool 1: enabled with existing params
    call_args = mock_create_or_update_tool.call_args_list[0]
    tool_info = call_args.kwargs['tool_info']
    assert tool_info.tool_id == 1
    assert tool_info.enabled is True
    assert tool_info.params == {"key1": "value1"}

    # Check tool 2: enabled with empty params (new tool)
    call_args = mock_create_or_update_tool.call_args_list[1]
    tool_info = call_args.kwargs['tool_info']
    assert tool_info.tool_id == 2
    assert tool_info.enabled is True
    assert tool_info.params == {}


@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.query_tool_instances_by_agent_id')
@patch('backend.services.agent_service.update_agent')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_update_agent_info_impl_with_enabled_tool_ids_instance_having_null_tool_id(
    mock_get_current_user_info,
    mock_update_agent,
    mock_query_tool_instances_by_agent_id,
    mock_create_or_update_tool
):
    """
    Test update_agent_info_impl when existing tool instance has null tool_id.

    This test verifies that:
    1. Instances with null tool_id are skipped (not causing errors)
    2. Only valid tool instances are processed for enabling/disabling
    """
    # Setup
    mock_get_current_user_info.return_value = ("test_user", "test_tenant", "en")

    # Mock existing tool instances: one with valid tool_id, one with null tool_id
    mock_query_tool_instances_by_agent_id.return_value = [
        {"tool_id": 1, "params": {"key1": "value1"}},  # Valid instance
        {"tool_id": None, "params": {}},               # Instance with null tool_id - should be skipped
    ]

    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = [1]  # Enable only tool 1
    request.related_agent_ids = None

    # Execute
    result = await update_agent_info_impl(request, authorization="Bearer token")

    # Assert
    assert result["agent_id"] == 123
    mock_update_agent.assert_called_once()

    # Verify only tool 1 was enabled; tool with null tool_id was skipped
    assert mock_create_or_update_tool.call_count == 1
    call_args = mock_create_or_update_tool.call_args
    tool_info = call_args.kwargs['tool_info']
    assert tool_info.tool_id == 1
    assert tool_info.enabled is True


@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.query_tool_instances_by_agent_id')
@patch('backend.services.agent_service.update_agent')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_update_agent_info_impl_with_enabled_tool_ids_disabled_existing_tool(
    mock_get_current_user_info,
    mock_update_agent,
    mock_query_tool_instances_by_agent_id,
    mock_create_or_update_tool
):
    """
    Test that existing tools not in enabled_tool_ids are disabled.

    This test verifies that:
    1. When enabled_tool_ids is provided, existing tools NOT in the list are disabled
    2. create_or_update_tool_by_tool_info is called with enabled=False for disabled tools
    """
    # Setup
    mock_get_current_user_info.return_value = ("test_user", "test_tenant", "en")

    # Mock existing tool instances: tool 1 exists, tool 2 is new
    mock_query_tool_instances_by_agent_id.return_value = [
        {"tool_id": 1, "params": {"key1": "value1"}},  # Existing tool 1
    ]

    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = [2]  # Only enable tool 2 (new tool)
    # Tool 1 exists but is NOT in enabled_tool_ids, so it should be disabled
    request.related_agent_ids = None

    # Execute
    result = await update_agent_info_impl(request, authorization="Bearer token")

    # Assert
    assert result["agent_id"] == 123
    mock_update_agent.assert_called_once()

    # Verify: tool 1 was disabled, tool 2 was enabled
    assert mock_create_or_update_tool.call_count == 2

    # Check tool 1: disabled (exists but not in enabled_tool_ids)
    call_args = mock_create_or_update_tool.call_args_list[0]
    tool_info = call_args.kwargs['tool_info']
    assert tool_info.tool_id == 1
    assert tool_info.enabled is False
    assert tool_info.params == {"key1": "value1"}

    # Check tool 2: enabled (new tool)
    call_args = mock_create_or_update_tool.call_args_list[1]
    tool_info = call_args.kwargs['tool_info']
    assert tool_info.tool_id == 2
    assert tool_info.enabled is True
    assert tool_info.params == {}


@patch('backend.services.agent_service.update_related_agents')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.update_agent')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_update_agent_info_impl_with_related_agent_ids(
    mock_get_current_user_info,
    mock_update_agent,
    mock_query_sub_agents_id_list,
    mock_update_related_agents
):
    """
    Test update_agent_info_impl with related_agent_ids parameter.

    This test verifies that:
    1. When related_agent_ids is provided, relationships are updated
    2. Circular dependency detection works correctly
    3. update_related_agents is called with correct parameters
    """
    # Setup
    mock_get_current_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_query_sub_agents_id_list.return_value = []  # No sub-agents, no circular dependency

    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = None
    request.related_agent_ids = [456, 789]

    # Execute
    result = await update_agent_info_impl(request, authorization="Bearer token")

    # Assert
    assert result["agent_id"] == 123
    mock_update_agent.assert_called_once()
    mock_update_related_agents.assert_called_once_with(
        parent_agent_id=123,
        related_agent_ids=[456, 789],
        tenant_id="test_tenant",
        user_id="test_user"
    )


@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.update_agent')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_update_agent_info_impl_circular_dependency_detection(
    mock_get_current_user_info,
    mock_update_agent,
    mock_query_sub_agents_id_list
):
    """
    Test update_agent_info_impl circular dependency detection.

    This test verifies that:
    1. When agent tries to relate to itself, ValueError is raised
    2. When circular dependency is detected through sub-agents, ValueError is raised
    """
    # Setup
    mock_get_current_user_info.return_value = ("test_user", "test_tenant", "en")

    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = None
    request.related_agent_ids = [123]  # Agent tries to relate to itself

    # Execute & Assert - self-reference should raise ValueError
    with pytest.raises(ValueError, match="Circular dependency detected"):
        await update_agent_info_impl(request, authorization="Bearer token")

    # Test circular dependency through sub-agents
    request.related_agent_ids = [456]
    # Agent 456 has sub-agent 123 (circular)
    mock_query_sub_agents_id_list.return_value = [123]

    with pytest.raises(ValueError, match="Circular dependency detected"):
        await update_agent_info_impl(request, authorization="Bearer token")


@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.query_tool_instances_by_agent_id')
@patch('backend.services.agent_service.update_related_agents')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.update_agent')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_update_agent_info_impl_with_both_tool_and_related_agents(
    mock_get_current_user_info,
    mock_update_agent,
    mock_query_sub_agents_id_list,
    mock_update_related_agents,
    mock_query_tool_instances_by_agent_id,
    mock_create_or_update_tool
):
    """
    Test update_agent_info_impl with both enabled_tool_ids and related_agent_ids.

    This test verifies that:
    1. Both tools and related agents can be updated in the same call
    2. Operations are performed in correct order
    """
    # Setup
    mock_get_current_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_query_tool_instances_by_agent_id.return_value = []  # No existing instances
    mock_query_sub_agents_id_list.return_value = []

    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = [1]
    request.related_agent_ids = [456]

    # Execute
    result = await update_agent_info_impl(request, authorization="Bearer token")

    # Assert
    assert result["agent_id"] == 123
    mock_update_agent.assert_called_once()
    mock_create_or_update_tool.assert_called_once()
    mock_update_related_agents.assert_called_once_with(
        parent_agent_id=123,
        related_agent_ids=[456],
        tenant_id="test_tenant",
        user_id="test_user"
    )


@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.query_tool_instances_by_agent_id')
@patch('backend.services.agent_service.update_agent')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_update_agent_info_impl_tool_update_exception(
    mock_get_current_user_info,
    mock_update_agent,
    mock_query_tool_instances_by_agent_id,
    mock_create_or_update_tool
):
    """
    Test update_agent_info_impl exception handling for tool updates.

    This test verifies that:
    1. When tool update fails, ValueError is raised with appropriate message
    """
    # Setup
    mock_get_current_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_query_tool_instances_by_agent_id.return_value = []
    mock_create_or_update_tool.side_effect = Exception("Tool update failed")

    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = [1]
    request.related_agent_ids = None

    # Execute & Assert
    with pytest.raises(ValueError, match="Failed to update agent tools"):
        await update_agent_info_impl(request, authorization="Bearer token")


@patch('backend.services.agent_service.update_related_agents')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.update_agent')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_update_agent_info_impl_related_agent_update_exception(
    mock_get_current_user_info,
    mock_update_agent,
    mock_query_sub_agents_id_list,
    mock_update_related_agents
):
    """
    Test update_agent_info_impl exception handling for related agent updates.

    This test verifies that:
    1. When related agent update fails, ValueError is raised with appropriate message
    """
    # Setup
    mock_get_current_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_query_sub_agents_id_list.return_value = []
    mock_update_related_agents.side_effect = Exception("Related agent update failed")

    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = None
    request.related_agent_ids = [456]

    # Execute & Assert
    with pytest.raises(ValueError, match="Failed to update related agents"):
        await update_agent_info_impl(request, authorization="Bearer token")


@patch('backend.services.agent_service.get_user_language')
@patch('backend.services.agent_service.get_current_user_info')
def test_resolve_user_tenant_language_with_overrides(mock_get_current_user_info, mock_get_user_language):
    """
    Test _resolve_user_tenant_language with user_id and tenant_id overrides.

    This test verifies that:
    1. When user_id and tenant_id are provided, authorization is not parsed again
    2. Language is still retrieved from http_request
    """
    mock_get_user_language.return_value = "zh"
    mock_request = MagicMock()

    result = _resolve_user_tenant_language(
        authorization="Bearer token",
        http_request=mock_request,
        user_id="override_user",
        tenant_id="override_tenant"
    )

    assert result == ("override_user", "override_tenant", "zh")
    mock_get_current_user_info.assert_not_called()
    mock_get_user_language.assert_called_once_with(mock_request)


@patch('backend.services.agent_service.get_current_user_info')
def test_resolve_user_tenant_language_without_overrides(mock_get_current_user_info):
    """
    Test _resolve_user_tenant_language without user_id and tenant_id overrides.

    This test verifies that:
    1. When user_id or tenant_id is None, authorization is parsed
    2. get_current_user_info is called with authorization and http_request
    """
    mock_get_current_user_info.return_value = ("parsed_user", "parsed_tenant", "en")
    mock_request = MagicMock()

    result = _resolve_user_tenant_language(
        authorization="Bearer token",
        http_request=mock_request,
        user_id=None,
        tenant_id=None
    )

    assert result == ("parsed_user", "parsed_tenant", "en")
    mock_get_current_user_info.assert_called_once_with("Bearer token", mock_request)


@patch('backend.services.agent_service.get_user_language')
@patch('backend.services.agent_service.get_current_user_info')
def test_resolve_user_tenant_language_partial_override(mock_get_current_user_info, mock_get_user_language):
    """
    Test _resolve_user_tenant_language with partial override (only user_id).

    This test verifies that:
    1. When only user_id is provided, authorization is still parsed
    2. Both user_id and tenant_id must be provided to skip parsing
    """
    mock_get_current_user_info.return_value = ("parsed_user", "parsed_tenant", "en")
    mock_get_user_language.return_value = "fr"
    mock_request = MagicMock()

    result = _resolve_user_tenant_language(
        authorization="Bearer token",
        http_request=mock_request,
        user_id="override_user",
        tenant_id=None  # tenant_id is None, so parsing is needed
    )

    assert result == ("parsed_user", "parsed_tenant", "en")
    mock_get_current_user_info.assert_called_once_with("Bearer token", mock_request)


@patch('backend.services.agent_service.delete_agent_by_id')
@pytest.mark.asyncio
async def test_delete_agent_impl_exception_handling(mock_delete_agent):
    """
    Test exception handling in delete_agent_impl function.

    This test verifies that:
    1. When an exception occurs during agent deletion
    2. The function raises a ValueError with an appropriate message
    """
    # Setup
    mock_delete_agent.side_effect = Exception("Delete failed")

    # Execute & Assert
    with pytest.raises(ValueError) as context:
        await delete_agent_impl(123, "test_tenant", "test_user")

    assert "Failed to delete agent" in str(context.value)


@patch('backend.services.agent_service.query_group_ids_by_user')
def test_get_user_group_ids_success(mock_get_group_ids):
    """
    Test successful retrieval of user's group IDs as comma-separated string.

    This test verifies that:
    1. The _get_user_group_ids function calls get_group_ids_by_user
    2. Returns a comma-separated string of group IDs
    3. Uses convert_list_to_string utility function
    """
    # Setup
    from backend.services.agent_service import _get_user_group_ids
    mock_get_group_ids.return_value = [1, 2, 3]

    # Execute
    result = _get_user_group_ids("test_user", "test_tenant")

    # Assert
    assert result == "1,2,3"
    mock_get_group_ids.assert_called_once_with("test_user")


@patch('backend.services.agent_service.query_group_ids_by_user')
def test_get_user_group_ids_empty_groups(mock_get_group_ids):
    """
    Test _get_user_group_ids with empty group list.

    This test verifies that:
    1. When user has no groups, returns empty string
    """
    # Setup
    from backend.services.agent_service import _get_user_group_ids
    mock_get_group_ids.return_value = []

    # Execute
    result = _get_user_group_ids("test_user", "test_tenant")

    # Assert
    assert result == ""
    mock_get_group_ids.assert_called_once_with("test_user")


@patch('backend.services.agent_service.query_group_ids_by_user')
def test_get_user_group_ids_exception_handling(mock_get_group_ids):
    """
    Test _get_user_group_ids exception handling.

    This test verifies that:
    1. When get_group_ids_by_user raises exception, logs warning and returns empty string
    """
    # Setup
    from backend.services.agent_service import _get_user_group_ids
    mock_get_group_ids.side_effect = Exception("Database error")

    # Execute
    result = _get_user_group_ids("test_user", "test_tenant")

    # Assert
    assert result == ""
    mock_get_group_ids.assert_called_once_with("test_user")


@patch('backend.services.agent_service.query_group_ids_by_user')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_update_agent_info_impl_create_agent_auto_group_ids(mock_get_current_user_info, mock_create_agent, mock_get_group_ids):
    """
    Test creating a new agent with automatic group_ids assignment.

    This test verifies that:
    1. When agent_id is None, a new agent is created
    2. The group_ids are automatically set to the current user's groups
    3. The create_agent function is called with the correct parameters including group_ids
    """
    # Setup
    from backend.services.agent_service import update_agent_info_impl
    mock_get_current_user_info.return_value = (
        "test_user", "test_tenant", "en")
    mock_get_group_ids.return_value = [1, 2, 3]
    mock_create_agent.return_value = {"agent_id": 456}

    # Create a mock AgentInfoRequest object
    request = MagicMock()
    request.agent_id = None  # This triggers create mode
    request.name = "New Agent"
    request.display_name = "New Display Name"
    request.business_description = "New agent description"
    request.author = "test_author"
    request.model_id = 1
    request.model_name = "test-model"
    request.business_logic_model_id = None
    request.business_logic_model_name = None
    request.max_steps = 10
    request.provide_run_summary = True
    request.duty_prompt = "Test duty"
    request.constraint_prompt = "Test constraint"
    request.few_shots_prompt = "Test few shots"
    request.enabled = True
    request.enabled_tool_ids = None
    request.related_agent_ids = None
    request.group_ids = None

    # Execute
    result = await update_agent_info_impl(request, authorization="Bearer token")

    # Assert
    assert result["agent_id"] == 456
    mock_get_group_ids.assert_called_once_with("test_user")
    mock_create_agent.assert_called_once()
    # Verify that group_ids is included in the agent_info dict passed to create_agent
    # agent_info keyword argument
    call_args = mock_create_agent.call_args[1]["agent_info"]
    # Should be comma-separated string
    assert call_args["group_ids"] == "1,2,3"


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


@patch('backend.services.agent_service.check_agent_availability')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
async def test_get_agent_info_impl_with_tool_error(mock_search_agent_info, mock_get_model_by_model_id, mock_check_availability):
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
        "model_id": None,
        "business_description": "Test agent"
    }
    mock_search_agent_info.return_value = mock_agent_info
    mock_check_availability.return_value = (True, [])

    # Mock the search_tools_for_sub_agent function to raise an exception
    with patch('backend.services.agent_service.search_tools_for_sub_agent') as mock_search_tools, \
            patch('backend.services.agent_service.query_sub_agents_id_list') as mock_query_sub_agents_id:
        mock_search_tools.side_effect = Exception("Tool search error")
        mock_query_sub_agents_id.return_value = []
        mock_get_model_by_model_id.return_value = None

        # Execute
        result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

        # Assert
        assert result["agent_id"] == 123
        assert result["tools"] == []
        assert result["sub_agent_id_list"] == []
        assert result["model_name"] is None
        assert result["is_available"] == True
        assert result["unavailable_reasons"] == []
        mock_search_agent_info.assert_called_once_with(123, "test_tenant", 0)


@patch('backend.services.agent_service.check_agent_availability')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_get_agent_info_impl_sub_agent_error(mock_search_agent_info, mock_search_tools, mock_query_sub_agents_id, mock_get_model_by_model_id, mock_check_availability):
    """
    Test get_agent_info_impl with an error in retrieving sub agent id list.

    This test verifies that:
    1. The function correctly gets the agent information
    2. When an error occurs retrieving sub agent id list
    3. The function returns the agent information with an empty sub_agent_id_list
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent"
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1"}]
    mock_search_tools.return_value = mock_tools

    # Mock query_sub_agents_id_list to raise an exception
    mock_query_sub_agents_id.side_effect = Exception("Sub agent query error")
    mock_get_model_by_model_id.return_value = None
    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    assert result["agent_id"] == 123
    assert result["tools"] == mock_tools
    assert result["sub_agent_id_list"] == []
    assert result["model_name"] is None
    assert result["is_available"] == True
    assert result["unavailable_reasons"] == []
    mock_search_agent_info.assert_called_once_with(123, "test_tenant", 0)
    mock_search_tools.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant")
    mock_query_sub_agents_id.assert_called_once_with(
        main_agent_id=123, tenant_id="test_tenant")


@patch('backend.services.agent_service.check_agent_availability')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_model_id_success(mock_search_agent_info, mock_search_tools, mock_query_sub_agents_id, mock_get_model_by_model_id, mock_check_availability):
    """
    Test get_agent_info_impl with a valid model_id.

    This test verifies that:
    1. The function correctly retrieves model information when model_id is not None
    2. It sets model_name from the model's display_name
    3. It handles the case when model_info is None
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_id": 456,
        "business_description": "Test agent"
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1"}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock model info with display_name
    mock_model_info = {
        "model_id": 456,
        "display_name": "GPT-4",
        "provider": "openai"
    }
    mock_get_model_by_model_id.return_value = mock_model_info

    # Mock check_agent_availability - agent is available
    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_id": 456,
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "model_name": "GPT-4",
        "business_logic_model_name": None,
        "is_available": True,
        "unavailable_reasons": []
    }
    assert result == expected_result
    mock_get_model_by_model_id.assert_called_once_with(456)


@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.query_sub_agents_id_list")
@patch("backend.services.agent_service.search_tools_for_sub_agent")
@patch("backend.services.agent_service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_converts_group_ids_when_present(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_convert_string_to_list,
    mock_check_availability,
):
    """get_agent_info_impl should convert group_ids when present."""
    mock_search_agent_info.return_value = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent",
        "group_ids": "1,2",
        "business_logic_model_id": None,
    }
    mock_search_tools.return_value = []
    mock_query_sub_agents_id.return_value = []
    mock_convert_string_to_list.return_value = [1, 2]
    mock_check_availability.return_value = (True, [])

    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert result["group_ids"] == [1, 2]
    mock_convert_string_to_list.assert_called_once_with("1,2")


@patch('backend.services.agent_service.check_agent_availability')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_model_id_no_display_name(mock_search_agent_info, mock_search_tools, mock_query_sub_agents_id, mock_get_model_by_model_id, mock_check_availability):
    """
    Test get_agent_info_impl with model_id but model has no display_name.

    This test verifies that:
    1. The function correctly retrieves model information when model_id is not None
    2. It sets model_name to None when model_info exists but has no display_name
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_id": 456,
        "business_description": "Test agent"
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1"}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock model info without display_name
    mock_model_info = {
        "model_id": 456,
        "provider": "openai"
        # No display_name field
    }
    mock_get_model_by_model_id.return_value = mock_model_info
    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_id": 456,
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "model_name": None,
        "business_logic_model_name": None,
        "is_available": True,
        "unavailable_reasons": []
    }
    assert result == expected_result
    mock_get_model_by_model_id.assert_called_once_with(456)


@patch('backend.services.agent_service.check_agent_availability')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_model_id_none_model_info(mock_search_agent_info, mock_search_tools, mock_query_sub_agents_id, mock_get_model_by_model_id, mock_check_availability):
    """
    Test get_agent_info_impl with model_id but get_model_by_model_id returns None.

    This test verifies that:
    1. The function correctly handles when model_id is not None but get_model_by_model_id returns None
    2. It sets model_name to None when model_info is None
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_id": 456,
        "business_description": "Test agent"
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1"}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock get_model_by_model_id to return None
    mock_get_model_by_model_id.return_value = None
    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_id": 456,
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "model_name": None,
        "business_logic_model_name": None,
        "is_available": True,
        "unavailable_reasons": []
    }
    assert result == expected_result
    mock_get_model_by_model_id.assert_called_once_with(456)


@patch('backend.services.agent_service.check_agent_availability')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_business_logic_model(mock_search_agent_info, mock_search_tools, mock_query_sub_agents_id, mock_get_model_by_model_id, mock_check_availability):
    """
    Test get_agent_info_impl with business_logic_model_id.

    This test verifies that:
    1. The function correctly retrieves business logic model information when business_logic_model_id is not None
    2. It sets business_logic_model_name from the model's display_name
    3. It handles both main model and business logic model correctly
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_id": 456,
        "business_logic_model_id": 789,
        "business_description": "Test agent"
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1"}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [101, 102]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock model info for main model
    mock_main_model_info = {
        "model_id": 456,
        "display_name": "GPT-4",
        "provider": "openai"
    }

    # Mock model info for business logic model
    mock_business_logic_model_info = {
        "model_id": 789,
        "display_name": "Claude-3.5",
        "provider": "anthropic"
    }

    # Mock get_model_by_model_id to return different values based on input
    def mock_get_model(model_id):
        if model_id == 456:
            return mock_main_model_info
        elif model_id == 789:
            return mock_business_logic_model_info
        return None

    mock_get_model_by_model_id.side_effect = mock_get_model
    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_id": 456,
        "business_logic_model_id": 789,
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "model_name": "GPT-4",
        "business_logic_model_name": "Claude-3.5",
        "is_available": True,
        "unavailable_reasons": []
    }
    assert result == expected_result

    # Verify both models were looked up
    assert mock_get_model_by_model_id.call_count == 2
    mock_get_model_by_model_id.assert_any_call(456)
    mock_get_model_by_model_id.assert_any_call(789)


@patch('backend.services.agent_service.check_agent_availability')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_business_logic_model_none(mock_search_agent_info, mock_search_tools, mock_query_sub_agents_id, mock_get_model_by_model_id, mock_check_availability):
    """
    Test get_agent_info_impl with business_logic_model_id but get_model_by_model_id returns None.

    This test verifies that:
    1. The function correctly handles when business_logic_model_id is not None but get_model_by_model_id returns None
    2. It sets business_logic_model_name to None when model_info is None
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_id": 456,
        "business_logic_model_id": 789,
        "business_description": "Test agent"
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1"}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [101, 102]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock model info for main model
    mock_main_model_info = {
        "model_id": 456,
        "display_name": "GPT-4",
        "provider": "openai"
    }

    # Mock get_model_by_model_id to return None for business_logic_model_id
    def mock_get_model(model_id):
        if model_id == 456:
            return mock_main_model_info
        elif model_id == 789:
            return None  # Business logic model not found
        return None

    mock_get_model_by_model_id.side_effect = mock_get_model
    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_id": 456,
        "business_logic_model_id": 789,
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "model_name": "GPT-4",
        "business_logic_model_name": None,  # Should be None when model info is not found
        "is_available": True,
        "unavailable_reasons": []
    }
    assert result == expected_result

    # Verify both models were looked up
    assert mock_get_model_by_model_id.call_count == 2
    mock_get_model_by_model_id.assert_any_call(456)
    mock_get_model_by_model_id.assert_any_call(789)


@patch('backend.services.agent_service.check_agent_availability')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_business_logic_model_no_display_name(mock_search_agent_info, mock_search_tools, mock_query_sub_agents_id, mock_get_model_by_model_id, mock_check_availability):
    """
    Test get_agent_info_impl with business_logic_model_id but model has no display_name.

    This test verifies that:
    1. The function correctly retrieves business logic model information when business_logic_model_id is not None
    2. It sets business_logic_model_name to None when model_info exists but has no display_name
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_id": 456,
        "business_logic_model_id": 789,
        "business_description": "Test agent"
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1"}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [101, 102]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock model info for main model
    mock_main_model_info = {
        "model_id": 456,
        "display_name": "GPT-4",
        "provider": "openai"
    }

    # Mock model info for business logic model without display_name
    mock_business_logic_model_info = {
        "model_id": 789,
        "provider": "anthropic"
        # No display_name field
    }

    # Mock get_model_by_model_id to return different values based on input
    def mock_get_model(model_id):
        if model_id == 456:
            return mock_main_model_info
        elif model_id == 789:
            return mock_business_logic_model_info
        return None

    mock_get_model_by_model_id.side_effect = mock_get_model
    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_id": 456,
        "business_logic_model_id": 789,
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "model_name": "GPT-4",
        "business_logic_model_name": None,  # Should be None when display_name is not in model_info
        "is_available": True,
        "unavailable_reasons": []
    }
    assert result == expected_result

    # Verify both models were looked up
    assert mock_get_model_by_model_id.call_count == 2
    mock_get_model_by_model_id.assert_any_call(456)
    mock_get_model_by_model_id.assert_any_call(789)


@pytest.mark.asyncio
@patch("backend.services.agent_service.get_model_by_model_id")
@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_group_ids_by_user")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_success(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """
    Test successful retrieval of all agent information for admin user.

    This test verifies that:
    1. The function correctly queries all agents for a tenant
    2. It checks agent availability
    3. It returns a properly formatted list of agent information with permissions
    """
    # Setup mock agents
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "First test agent",
            "enabled": True,
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
            "current_version_no": None,  # Not published
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Second test agent",
            "enabled": True,
            "group_ids": "1,2,3",
            "created_by": "user2",
            "create_time": 2,
            "current_version_no": 1,  # Published
        }
    ]

    # Configure mocks
    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.side_effect = lambda x: [] if not x else [int(i) for i in x.split(",")]
    mock_check_availability.side_effect = lambda *args, **kwargs: (True, [])
    mock_get_model.return_value = None

    # Execute
    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="admin_user")

    # Assert
    assert len(result) == 2
    assert result[0]["agent_id"] == 1
    assert result[0]["name"] == "Agent 1"
    assert result[0]["display_name"] == "Display Agent 1"
    assert result[0]["is_available"] == True
    assert result[0]["unavailable_reasons"] == []
    assert result[0]["group_ids"] == []
    assert result[0]["permission"] == "EDIT"  # Admin can edit all
    assert result[0]["is_published"] == False  # current_version_no is None
    assert result[1]["agent_id"] == 2
    assert result[1]["name"] == "Agent 2"
    assert result[1]["display_name"] == "Display Agent 2"
    assert result[1]["is_available"] == True
    assert result[1]["unavailable_reasons"] == []
    assert result[1]["group_ids"] == [1, 2, 3]
    assert result[1]["permission"] == "EDIT"  # Admin can edit all
    assert result[1]["is_published"] == True  # current_version_no is not None

    # Verify mock calls
    mock_query_agents.assert_called_once_with(tenant_id="test_tenant")
    mock_get_user_tenant.assert_called_once_with("admin_user")


@pytest.mark.asyncio
@patch("backend.services.agent_service.get_model_by_model_id")
@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_group_ids_by_user")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_is_published_field(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """
    Test that is_published field is correctly set based on current_version_no.

    This test verifies that:
    1. is_published is False when current_version_no is None
    2. is_published is False when current_version_no field is missing
    3. is_published is True when current_version_no is not None
    """
    # Setup mock agents with different current_version_no values
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Unpublished agent",
            "enabled": True,
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
            "current_version_no": None,  # Not published
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Published agent",
            "enabled": True,
            "group_ids": "",
            "created_by": "user2",
            "create_time": 2,
            "current_version_no": 1,  # Published
        },
        {
            "agent_id": 3,
            "name": "Agent 3",
            "display_name": "Display Agent 3",
            "description": "Agent without current_version_no field",
            "enabled": True,
            "group_ids": "",
            "created_by": "user3",
            "create_time": 3,
            # current_version_no field is missing
        }
    ]

    # Configure mocks
    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.side_effect = lambda x: [] if not x else [int(i) for i in x.split(",")]
    mock_check_availability.side_effect = lambda *args, **kwargs: (True, [])
    mock_get_model.return_value = None

    # Execute
    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="admin_user")

    # Assert
    assert len(result) == 3
    # Agent 1: current_version_no is None -> is_published should be False
    assert result[0]["agent_id"] == 1
    assert result[0]["is_published"] == False
    # Agent 2: current_version_no is 1 -> is_published should be True
    assert result[1]["agent_id"] == 2
    assert result[1]["is_published"] == True
    # Agent 3: current_version_no field is missing -> is_published should be False
    assert result[2]["agent_id"] == 3
    assert result[2]["is_published"] == False

    # Verify mock calls
    mock_query_agents.assert_called_once_with(tenant_id="test_tenant")
    mock_get_user_tenant.assert_called_once_with("admin_user")


@pytest.mark.asyncio
@patch("backend.services.agent_service.get_model_by_model_id")
@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_group_ids_by_user")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_model_cache_miss_fetches_model(
    mock_query_all,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """list_all_agent_info_impl should fetch model when model_id not in cache."""
    mock_query_all.return_value = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "First test agent",
            "enabled": True,
            "model_id": 99,
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        }
    ]

    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.return_value = []
    # Do not mutate model_cache here so that the "model_id not in model_cache" branch runs.
    mock_check_availability.side_effect = lambda *args, **kwargs: (True, [])
    mock_get_model.return_value = {"model_name": "m", "display_name": "M"}

    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="admin_user")

    assert len(result) == 1
    assert result[0]["model_id"] == 99
    assert result[0]["model_name"] == "m"
    assert result[0]["model_display_name"] == "M"
    mock_get_model.assert_called_once_with(99, "test_tenant")


@pytest.mark.asyncio
@patch("backend.services.agent_service.get_model_by_model_id")
@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_group_ids_by_user")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_with_unavailable_tools(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
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
            "enabled": True,
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Agent with unavailable tools",
            "enabled": True,
            "group_ids": "5,6",
            "created_by": "user2",
            "create_time": 2,
        }
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.side_effect = lambda x: [] if not x else [int(i) for i in x.split(",")]
    # First agent has available tools, second agent has unavailable tools
    mock_check_availability.side_effect = [
        (True, []),  # Agent 1: available
        (False, ["tool_unavailable"])  # Agent 2: unavailable
    ]
    mock_get_model.return_value = None

    # Execute
    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="admin_user")

    # Assert
    assert len(result) == 2
    assert result[0]["is_available"] == True
    assert result[0]["unavailable_reasons"] == []
    assert result[0]["group_ids"] == []
    assert result[1]["is_available"] == False
    assert result[1]["unavailable_reasons"] == ["tool_unavailable"]
    assert result[1]["group_ids"] == [5, 6]

    # Verify mock calls
    mock_query_agents.assert_called_once_with(tenant_id="test_tenant")


@pytest.mark.asyncio
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_query_error(
    mock_query_agents,
    mock_get_user_tenant,
):
    """
    Test error handling when querying agent information fails.

    This test verifies that:
    1. When an error occurs during agent query
    2. The function raises a ValueError with an appropriate message
    """
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    # Configure mock to raise exception
    mock_query_agents.side_effect = Exception("Database error")

    # Execute & Assert
    with pytest.raises(ValueError) as context:
        await list_all_agent_info_impl(tenant_id="test_tenant", user_id="admin_user")

    assert "Failed to query all agent info" in str(context.value)
    mock_query_agents.assert_called_once_with(tenant_id="test_tenant")


@pytest.mark.asyncio
@patch("backend.services.agent_service.get_model_by_model_id")
@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_group_ids_by_user")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_model_unavailable(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent with unavailable model",
            "enabled": True,
            "model_id": 101,
            "group_ids": "7,8,9",
            "created_by": "user1",
            "create_time": 1,
            "current_version_no": None,
        }
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.side_effect = lambda x: [] if not x else [int(i) for i in x.split(",")]
    mock_check_availability.side_effect = lambda *args, **kwargs: (False, ["model_unavailable"])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="admin_user")

    assert len(result) == 1
    assert result[0]["is_available"] is False
    assert result[0]["unavailable_reasons"] == ["model_unavailable"]
    assert result[0]["group_ids"] == [7, 8, 9]
    assert result[0]["is_published"] == False  # current_version_no is None


@pytest.mark.asyncio
@patch("backend.services.agent_service.get_model_by_model_id")
@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_group_ids_by_user")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_duplicate_names(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Duplicated",
            "create_time": 1,
            "display_name": "Agent Display 1",
            "description": "First agent",
            "enabled": True,
            "group_ids": "10",
            "created_by": "user1",
        },
        {
            "agent_id": 2,
            "name": "Duplicated",
            "create_time": 2,
            "display_name": "Agent Display 2",
            "description": "Second agent",
            "enabled": True,
            "group_ids": "10,11",
            "created_by": "user2",
        }
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.side_effect = lambda x: [] if not x else [int(i) for i in x.split(",")]
    mock_check_availability.side_effect = lambda *args, **kwargs: (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="admin_user")

    assert len(result) == 2

    # The earliest created agent (agent_id=1) should remain available
    agent1 = next(a for a in result if a["agent_id"] == 1)
    assert agent1["is_available"] is True
    assert "duplicate_name" not in agent1["unavailable_reasons"]
    assert agent1["group_ids"] == [10]
    assert agent1["is_published"] == False  # current_version_no is missing/None

    # The later created agent (agent_id=2) should be unavailable due to duplication
    agent2 = next(a for a in result if a["agent_id"] == 2)
    assert agent2["is_available"] is False
    assert "duplicate_name" in agent2["unavailable_reasons"]
    assert agent2["group_ids"] == [10, 11]
    assert agent2["is_published"] == False  # current_version_no is missing/None


@pytest.mark.asyncio
@patch("backend.services.agent_service.get_model_by_model_id")
@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_group_ids_by_user")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_user_permission_read_only(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that regular users get READ_ONLY permission for agents they didn't create."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent created by user1",
            "enabled": True,
            "group_ids": "1",  # Agent in group 1
            "created_by": "user1",
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Agent created by current_user",
            "enabled": True,
            "group_ids": "1",  # Agent in group 1
            "created_by": "current_user",
            "create_time": 2,
        }
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "USER"}  # Regular user, not admin
    mock_query_groups.return_value = [1]  # User is in group 1, so can see both agents

    # Mock convert_string_to_list to handle both empty strings and comma-separated values
    # This should match the actual implementation in utils.str_utils
    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        # Handle comma-separated string like "1" or "1,2"
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result
    mock_convert_list.side_effect = convert_side_effect

    # Mock check_agent_availability to return (is_available, unavailable_reasons)
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="current_user")

    assert len(result) == 2
    # Agent created by user1 - current_user should have READ_ONLY
    agent1 = next(a for a in result if a["agent_id"] == 1)
    assert agent1["permission"] == "READ_ONLY"
    # Agent created by current_user - should have EDIT
    agent2 = next(a for a in result if a["agent_id"] == 2)
    assert agent2["permission"] == "EDIT"


@pytest.mark.asyncio
@patch("backend.services.agent_service.get_model_by_model_id")
@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_group_ids_by_user")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_group_filtering(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that regular users only see agents whose group_ids overlap with their groups."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent in group 1",
            "enabled": True,
            "group_ids": "1,2",
            "created_by": "user1",
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Agent in group 3",
            "enabled": True,
            "group_ids": "3,4",
            "created_by": "user2",
            "create_time": 2,
        },
        {
            "agent_id": 3,
            "name": "Agent 3",
            "display_name": "Display Agent 3",
            "description": "Agent in group 1 (same as user)",
            "enabled": True,
            "group_ids": "1",  # Agent in group 1, which overlaps with user's groups
            "created_by": "user3",
            "create_time": 3,
        }
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "USER"}  # Regular user
    mock_query_groups.return_value = [1, 2]  # User is in groups 1 and 2

    # Mock convert_string_to_list to handle both empty strings and comma-separated values
    # This should match the actual implementation in utils.str_utils
    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        # Handle comma-separated string like "1" or "1,2"
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result
    mock_convert_list.side_effect = convert_side_effect

    # Mock check_agent_availability to return (is_available, unavailable_reasons)
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="regular_user")

    # Should only see Agent 1 (overlaps with user's groups 1,2) and Agent 3 (overlaps with group 1)
    # Agent 2 should be filtered out (groups 3,4 don't overlap with user's groups 1,2)
    assert len(result) == 2
    agent_ids = [a["agent_id"] for a in result]
    assert 1 in agent_ids
    assert 3 in agent_ids
    assert 2 not in agent_ids


@pytest.mark.asyncio
@patch("backend.services.agent_service.get_model_by_model_id")
@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_group_ids_by_user")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_disabled_agents_filtered(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that disabled agents are filtered out."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Enabled agent",
            "enabled": True,
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Disabled agent",
            "enabled": False,
            "group_ids": "",
            "created_by": "user2",
            "create_time": 2,
        }
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    # For admin users, query_group_ids_by_user is not called, but we still need to mock it
    mock_query_groups.return_value = []
    mock_convert_list.return_value = []
    # Mock check_agent_availability to return (is_available, unavailable_reasons)
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="admin_user")

    # Should only see enabled agent (disabled agents are filtered out)
    assert len(result) == 1
    assert result[0]["agent_id"] == 1
    assert result[0]["name"] == "Agent 1"


@pytest.mark.asyncio
@patch("backend.services.agent_service.get_model_by_model_id")
@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_group_ids_by_user")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_group_query_error_handled(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that group query errors are handled gracefully - admin users are not affected."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Test agent",
            "enabled": True,
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        }
    ]

    mock_query_agents.return_value = mock_agents
    # Use ADMIN user - group query errors don't affect admin users since they bypass group filtering
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    # For admin users, query_group_ids_by_user is not called (can_edit_all is True)
    # But if it were called and failed, it should be handled gracefully
    mock_query_groups.side_effect = Exception("Database error")  # Simulate error
    mock_convert_list.return_value = []
    # Mock check_agent_availability to return (is_available, unavailable_reasons)
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    # Should not raise exception, but should handle gracefully
    # Admin users bypass group filtering, so they should see all agents
    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="admin_user")

    # Admin users should still see agents even if group query fails
    assert len(result) == 1
    assert result[0]["agent_id"] == 1


@pytest.mark.asyncio
@patch("backend.services.agent_service.get_model_by_model_id")
@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_group_ids_by_user")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_group_query_error_for_user_role(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that group query errors are handled gracefully for USER/DEV roles - covers lines 1274-1278."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Test agent",
            "enabled": True,
            "group_ids": "1,2",
            "created_by": "user1",
            "create_time": 1,
        }
    ]

    mock_query_agents.return_value = mock_agents
    # Use USER role - group query errors should be handled gracefully
    mock_get_user_tenant.return_value = {"user_role": "USER"}
    # Simulate exception when querying group IDs - this should trigger lines 1274-1278
    mock_query_groups.side_effect = Exception("Database connection error")
    mock_convert_list.return_value = []
    # Mock check_agent_availability to return (is_available, unavailable_reasons)
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    # Should not raise exception, but should handle gracefully
    # When group query fails, user_group_ids is set to empty set, so no agents match
    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="user1")

    # Since user_group_ids is empty set (due to exception), no agents should match group filter
    # So result should be empty
    assert len(result) == 0
    # Verify that query_group_ids_by_user was called (to trigger the exception)
    mock_query_groups.assert_called_once_with("user1")


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
            class_name="AnalyzeTextFileTool",
            name="Text Analyzer",
            source="source3",
            params={"param4": "value4"},
            metadata={"text": "data"},
            description="Text analysis tool",
            inputs="text file",
            output_type="analysis",
            usage=None
        ),
        ToolConfig(
            class_name="AnalyzeImageTool",
            name="Image Analyzer",
            source="source4",
            params={"param5": "value5"},
            metadata={"image": "data"},
            description="Image analysis tool",
            inputs="image file",
            output_type="analysis result",
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
    assert len(result.tools) == 5
    assert result.managed_agents == mock_sub_agent_ids

    # Verify KnowledgeBaseSearchTool metadata is empty
    knowledge_tool = next(
        tool for tool in result.tools if tool.class_name == "KnowledgeBaseSearchTool")
    assert knowledge_tool.metadata == {}

    analyze_text_tool = next(
        tool for tool in result.tools if tool.class_name == "AnalyzeTextFileTool")
    assert analyze_text_tool.metadata == {}

    analyze_image_tool = next(
        tool for tool in result.tools if tool.class_name == "AnalyzeImageTool")
    assert analyze_image_tool.metadata == {}

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


@patch('backend.services.agent_service.insert_related_agent')
@patch('backend.services.agent_service.import_agent_by_agent_id')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_import_agent_impl_imports_all_agents_and_links_relations(
    mock_get_current_user_info,
    mock_import_agent,
    mock_insert_relationship,
):
    """
    Import agent implementation should import sub-agents before their parents
    and create the relationship between the newly created agent IDs.
    """

    mock_get_current_user_info.return_value = ("test_user", "test_tenant", "en")
    # Sub-agent (ID 2) with no managed agents
    sub_agent_info = ExportAndImportAgentInfo(
        agent_id=2,
        name="SubAgent",
        display_name="Sub Agent",
        description="Sub agent desc",
        business_description="Business desc",
        max_steps=5,
        provide_run_summary=True,
        duty_prompt="Sub duty",
        constraint_prompt="Sub constraint",
        few_shots_prompt="Sub few shots",
        enabled=True,
        tools=[],
        managed_agents=[]
    )

    # Main agent references sub agent id 2
    main_agent_info = ExportAndImportAgentInfo(
        agent_id=1,
        name="MainAgent",
        display_name="Main Agent",
        description="Main desc",
        business_description="Business main",
        max_steps=10,
        provide_run_summary=True,
        duty_prompt="Main duty",
        constraint_prompt="Main constraint",
        few_shots_prompt="Main few shots",
        enabled=True,
        tools=[],
        managed_agents=[2]
    )

    export_data = ExportAndImportDataFormat(
        agent_id=1,
        agent_info={
            "1": main_agent_info,
            "2": sub_agent_info,
        },
        mcp_info=[
            MCPInfo(mcp_server_name="test_mcp_server",
                    mcp_url="http://test-mcp-server.com")
        ],
    )

    # The order of returns matches the import order: sub-agent first, then main agent
    mock_import_agent.side_effect = [101, 202]

    await import_agent_impl(export_data, authorization="Bearer token")

    # Sub-agent should be imported before main agent
    assert mock_import_agent.call_count == 2
    first_call = mock_import_agent.call_args_list[0]
    second_call = mock_import_agent.call_args_list[1]

    assert first_call.kwargs["import_agent_info"] is sub_agent_info
    assert first_call.kwargs["skip_duplicate_regeneration"] is False

    assert second_call.kwargs["import_agent_info"] is main_agent_info
    assert second_call.kwargs["skip_duplicate_regeneration"] is False

    # Relationship should link newly created ids (main -> sub)
    mock_insert_relationship.assert_called_once_with(
        parent_agent_id=202,
        child_agent_id=101,
        tenant_id="test_tenant",
    )


@patch('backend.services.agent_service.import_agent_by_agent_id')
@patch('backend.services.agent_service.get_current_user_info')
@pytest.mark.asyncio
async def test_import_agent_impl_force_import_passes_skip_flag(
    mock_get_current_user_info,
    mock_import_agent,
):
    """
    When force_import=True, skip_duplicate_regeneration should be True.
    """
    mock_get_current_user_info.return_value = ("test_user", "test_tenant", "en")

    agent_info = ExportAndImportAgentInfo(
        agent_id=1,
        name="Agent",
        display_name="Agent Display",
        description="desc",
        business_description="biz",
        max_steps=5,
        provide_run_summary=True,
        duty_prompt="duty",
        constraint_prompt="constraint",
        few_shots_prompt="few shots",
        enabled=True,
        tools=[],
        managed_agents=[]
    )

    export_data = ExportAndImportDataFormat(
        agent_id=1,
        agent_info={"1": agent_info},
        mcp_info=[]
    )

    await import_agent_impl(export_data, authorization="Bearer token", force_import=True)

    mock_get_current_user_info.assert_called_once_with("Bearer token")
    mock_import_agent.assert_called_once()
    call_kwargs = mock_import_agent.call_args.kwargs
    assert call_kwargs["import_agent_info"] is agent_info
    assert call_kwargs["skip_duplicate_regeneration"] is True


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
        "test_user", "test_tenant", 1, skip_query=False)
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
    mock_build_mem_ctx.reset_mock()

    await run_agent_stream(mock_agent_request, mock_http_request, "Bearer token")

    mock_save_messages.assert_not_called()
    # In debug mode, build_memory_context is called with skip_query=True to avoid database queries
    mock_build_mem_ctx.assert_called_once_with(None, None, 1, skip_query=True)

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

    mock_agent_run_manager.stop_agent_run.assert_called_once_with(
        123, "test_user")

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

    monkeypatch.setitem(
        sys.modules, "nexent.core.agents.run_agent", MagicMock())
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

    def failing_agent_run(*_, **__):
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

    # Enable memory switch in preview (memory enabled)
    monkeypatch.setattr(
        "backend.services.agent_service.build_memory_context",
        MagicMock(return_value=MagicMock(
            user_config=MagicMock(memory_switch=True))),
        raising=False,
    )

    # Prepare run returned values (agent_run_info, memory_context)
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
    from consts.const import MEMORY_SEARCH_START_MSG, MEMORY_SEARCH_DONE_MSG

    assert any("memory_search" in s and MEMORY_SEARCH_START_MSG in s for s in out)
    assert any("memory_search" in s and MEMORY_SEARCH_DONE_MSG in s for s in out)
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
        MagicMock(return_value=MagicMock(
            user_config=MagicMock(memory_switch=True))),
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

    from consts.const import MEMORY_SEARCH_FAIL_MSG

    assert any("memory_search" in s and MEMORY_SEARCH_FAIL_MSG in s for s in out)
    assert "data: fb1\n\n" in out
    assert called["unregistered"]


@pytest.mark.asyncio
@pytest.mark.asyncio
@patch("backend.services.agent_service.get_model_by_model_id")
@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_group_ids_by_user")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_with_disabled_agents(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
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
            "enabled": True,
            "group_ids": "12",
            "created_by": "user1",
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Disabled Agent",
            "display_name": "Display Disabled Agent",
            "description": "Disabled agent that should be skipped",
            "enabled": False,
            "group_ids": "13",
            "created_by": "user2",
            "create_time": 2,
        },
        {
            "agent_id": 3,
            "name": "Enabled Agent 2",
            "display_name": "Display Enabled Agent 2",
            "description": "Second enabled agent",
            "enabled": True,
            "group_ids": "12,14",
            "created_by": "user3",
            "create_time": 3,
        }
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.side_effect = lambda x: [] if not x else [int(i) for i in x.split(",")]
    mock_check_availability.side_effect = lambda *args, **kwargs: (True, [])
    mock_get_model.return_value = None

    # Execute
    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="admin_user")

    # Assert - only enabled agents should be in the result
    assert len(result) == 2
    assert result[0]["agent_id"] == 1
    assert result[0]["name"] == "Enabled Agent 1"
    assert result[0]["display_name"] == "Display Enabled Agent 1"
    assert result[0]["is_available"] == True
    assert result[0]["group_ids"] == [12]

    assert result[1]["agent_id"] == 3
    assert result[1]["name"] == "Enabled Agent 2"
    assert result[1]["display_name"] == "Display Enabled Agent 2"
    assert result[1]["is_available"] == True
    assert result[1]["group_ids"] == [12, 14]

    # Verify mock calls
    mock_query_agents.assert_called_once_with(tenant_id="test_tenant")


@pytest.mark.asyncio
@patch("backend.services.agent_service.get_model_by_model_id")
@patch("backend.services.agent_service.check_agent_availability")
@patch("backend.services.agent_service.convert_string_to_list")
@patch("backend.services.agent_service.get_user_tenant_by_user_id")
@patch("backend.services.agent_service.query_group_ids_by_user")
@patch("backend.services.agent_service.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_all_disabled_agents(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """
    Test list_all_agent_info_impl with all agents disabled.

    This test verifies that:
    1. When all agents are disabled, an empty list is returned
    2. No availability checks are made since no agents are processed
    """
    # Setup mock agents - all disabled
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Disabled Agent 1",
            "display_name": "Display Disabled Agent 1",
            "description": "First disabled agent",
            "enabled": False,
            "group_ids": "15",
            "created_by": "user1",
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Disabled Agent 2",
            "display_name": "Display Disabled Agent 2",
            "description": "Second disabled agent",
            "enabled": False,
            "group_ids": "16,17",
            "created_by": "user2",
            "create_time": 2,
        }
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.return_value = []
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    # Execute
    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="admin_user")

    # Assert - no agents should be in the result
    assert len(result) == 0
    assert result == []

    # Verify mock calls
    mock_query_agents.assert_called_once_with(tenant_id="test_tenant")
    # No availability checks should be made since no agents are enabled
    mock_check_availability.assert_not_called()


def test_apply_duplicate_name_availability_rules_handles_missing_fields():
    """
    Ensure duplicate detection gracefully handles agents without name/display_name.
    """
    enriched_agents = [
        {
            "raw_agent": {
                "agent_id": 1,
                "name": None,
                "display_name": None,
                "create_time": "2024-01-01T00:00:00",
            },
            "unavailable_reasons": [],
        },
        {
            "raw_agent": {
                "agent_id": 2,
                "name": "dup",
                "display_name": None,
                "create_time": "2024-01-01T00:00:00",
            },
            "unavailable_reasons": [],
        },
        {
            "raw_agent": {
                "agent_id": 3,
                "name": "dup",
                "display_name": None,
                "create_time": "2024-02-01T00:00:00",
            },
            "unavailable_reasons": [],
        },
        {
            "raw_agent": {
                "agent_id": 4,
                "name": None,
                "display_name": "display-dup",
                "create_time": "2024-01-01T00:00:00",
            },
            "unavailable_reasons": [],
        },
        {
            "raw_agent": {
                "agent_id": 5,
                "name": None,
                "display_name": "display-dup",
                "create_time": "2024-02-01T00:00:00",
            },
            "unavailable_reasons": [],
        },
    ]

    _apply_duplicate_name_availability_rules(enriched_agents)

    assert enriched_agents[0]["unavailable_reasons"] == []
    assert "duplicate_name" not in enriched_agents[1]["unavailable_reasons"]
    assert "duplicate_name" in enriched_agents[2]["unavailable_reasons"]
    assert "duplicate_display_name" not in enriched_agents[3]["unavailable_reasons"]
    assert "duplicate_display_name" in enriched_agents[4]["unavailable_reasons"]


# ============================================================================
# Tests for Agent Export/Import Integration with model_name fields
# ============================================================================


@patch('backend.services.agent_service.create_tool_config_list')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_export_agent_includes_model_names(
    mock_search_agent_info,
    mock_get_model_by_model_id,
    mock_query_sub_agents,
    mock_create_tool_config
):
    """
    Test that export_agent_by_agent_id correctly includes model_name and
    business_logic_model_name in the exported data.
    """
    # Setup - Agent info from database
    mock_agent_info_from_db = {
        "name": "test_agent",
        "display_name": "Test Agent",
        "description": "Test description",
        "business_description": "Test business description",
        "max_steps": 5,
        "provide_run_summary": False,
        "duty_prompt": "Test duty",
        "constraint_prompt": "Test constraints",
        "few_shots_prompt": "Test examples",
        "enabled": True,
        "model_id": 5,
        "business_logic_model_id": 4
    }
    mock_search_agent_info.return_value = mock_agent_info_from_db

    # Mock model lookup - this is where model_name comes from
    def get_model_side_effect(model_id):
        if model_id == 5:
            return {"display_name": "Qwen/Qwen3-8B", "model_id": 5}
        elif model_id == 4:
            return {"display_name": "Qwen/QwQ-32B", "model_id": 4}
        return None

    mock_get_model_by_model_id.side_effect = get_model_side_effect

    mock_query_sub_agents.return_value = []
    mock_create_tool_config.return_value = []

    # Execute export
    exported_agent = await export_agent_by_agent_id(
        agent_id=123,
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert - verify exported data includes model names
    assert isinstance(exported_agent, ExportAndImportAgentInfo)

    # Critical assertions - these fields must be present for import to work
    assert exported_agent.model_id == 5
    assert exported_agent.model_name == "Qwen/Qwen3-8B"  # ← Must be present
    assert exported_agent.business_logic_model_id == 4
    assert exported_agent.business_logic_model_name == "Qwen/QwQ-32B"  # ← Must be present

    # Verify other fields
    assert exported_agent.name == "test_agent"
    assert exported_agent.display_name == "Test Agent"


@patch('backend.services.agent_service.create_tool_config_list')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_export_agent_with_null_model_id(
    mock_search_agent_info,
    mock_get_model_by_model_id,
    mock_query_sub_agents,
    mock_create_tool_config
):
    """
    Test export when model_id is NULL in database.
    """
    # Setup - Agent with NULL model_id
    mock_agent_info_from_db = {
        "name": "agent_without_model",
        "display_name": "Agent Without Model",
        "description": "Test description",
        "business_description": "Test business description",
        "max_steps": 5,
        "provide_run_summary": False,
        "duty_prompt": "Test duty",
        "constraint_prompt": "Test constraints",
        "few_shots_prompt": "Test examples",
        "enabled": True,
        "model_id": None,  # NULL in database
        "business_logic_model_id": None  # NULL in database
    }
    mock_search_agent_info.return_value = mock_agent_info_from_db
    mock_query_sub_agents.return_value = []
    mock_create_tool_config.return_value = []

    # Execute export
    exported_agent = await export_agent_by_agent_id(
        agent_id=123,
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert - should handle NULL gracefully
    assert exported_agent.model_id is None
    assert exported_agent.model_name is None
    assert exported_agent.business_logic_model_id is None
    assert exported_agent.business_logic_model_name is None

    # get_model_by_model_id should not have been called
    mock_get_model_by_model_id.assert_not_called()


@patch('backend.services.agent_service.get_model_id_by_display_name')
@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@patch('backend.services.agent_service.create_tool_config_list')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_export_then_import_preserves_model_names(
    mock_search_agent_info,
    mock_get_model_by_model_id,
    mock_query_sub_agents,
    mock_create_tool_config,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
    mock_get_model_id_by_display_name
):
    """
    Integration test: Export an agent, then import it, verify model names are preserved.

    This test simulates the complete export/import cycle to ensure data integrity.
    """
    # ========== STEP 1: EXPORT ==========

    # Setup - Agent in source tenant
    mock_agent_info_from_db = {
        "name": "iot_knowledge_qa_assistant",
        "display_name": "物联网知识问答助手",
        "description": "IoT Q&A Assistant",
        "business_description": "IoT knowledge retrieval",
        "max_steps": 5,
        "provide_run_summary": False,
        "duty_prompt": "You are an IoT assistant",
        "constraint_prompt": "Follow safety rules",
        "few_shots_prompt": "Example tasks",
        "enabled": True,
        "model_id": 10,  # Model ID in source tenant
        "business_logic_model_id": 9  # Business logic model ID in source tenant
    }
    mock_search_agent_info.return_value = mock_agent_info_from_db

    # Mock model lookup for export
    def get_model_for_export(model_id):
        if model_id == 10:
            return {"display_name": "Qwen/Qwen3-8B", "model_id": 10}
        elif model_id == 9:
            return {"display_name": "Qwen/QwQ-32B", "model_id": 9}
        return None

    mock_get_model_by_model_id.side_effect = get_model_for_export
    mock_query_sub_agents.return_value = []
    mock_create_tool_config.return_value = []

    # Execute export
    exported_agent = await export_agent_by_agent_id(
        agent_id=123,
        tenant_id="source_tenant",
        user_id="source_user"
    )

    # Verify export includes model names
    assert exported_agent.model_id == 10
    assert exported_agent.model_name == "Qwen/Qwen3-8B"
    assert exported_agent.business_logic_model_id == 9
    assert exported_agent.business_logic_model_name == "Qwen/QwQ-32B"

    # ========== STEP 2: IMPORT ==========

    # Setup for import - simulate different model IDs in target tenant
    mock_query_all_tools.return_value = []

    # In target tenant, same models have different IDs
    # Source: model_id=10 → Target: model_id=5
    # Source: business_logic_model_id=9 → Target: business_logic_model_id=4
    mock_get_model_id_by_display_name.side_effect = [5, 4]

    mock_create_agent.return_value = {"agent_id": 999}

    # Execute import
    new_agent_id = await import_agent_by_agent_id(
        import_agent_info=exported_agent,
        tenant_id="target_tenant",
        user_id="target_user"
    )

    # Verify import was successful
    assert new_agent_id == 999

    # ========== STEP 3: VERIFY DATA INTEGRITY ==========

    # Verify create_agent was called with correct model information
    mock_create_agent.assert_called_once()
    call_kwargs = mock_create_agent.call_args[1]
    agent_info_dict = call_kwargs["agent_info"]

    # Model IDs should be REMAPPED to target tenant IDs
    assert agent_info_dict["model_id"] == 5  # Remapped from 10 to 5
    assert agent_info_dict["business_logic_model_id"] == 4  # Remapped from 9 to 4

    # Model NAMES should be PRESERVED (not remapped)
    assert agent_info_dict["model_name"] == "Qwen/Qwen3-8B"  # ← Preserved
    assert agent_info_dict["business_logic_model_name"] == "Qwen/QwQ-32B"  # ← Preserved

    # Other fields should also be preserved
    assert agent_info_dict["name"] == "iot_knowledge_qa_assistant"
    assert agent_info_dict["display_name"] == "物联网知识问答助手"
    assert agent_info_dict["description"] == "IoT Q&A Assistant"
    assert agent_info_dict["max_steps"] == 5

    # Verify model lookup was done by display name (model_name)
    assert mock_get_model_id_by_display_name.call_count == 2
    first_call = mock_get_model_id_by_display_name.call_args_list[0]
    second_call = mock_get_model_id_by_display_name.call_args_list[1]

    # get_model_id_by_display_name(display_name: str, tenant_id: str) uses positional args
    assert first_call[0][0] == "Qwen/Qwen3-8B"  # display_name
    assert first_call[0][1] == "target_tenant"  # tenant_id
    assert second_call[0][0] == "Qwen/QwQ-32B"  # display_name
    assert second_call[0][1] == "target_tenant"  # tenant_id


@patch('backend.services.agent_service.create_tool_config_list')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
@pytest.mark.asyncio
async def test_export_agent_model_not_found(
    mock_search_agent_info,
    mock_get_model_by_model_id,
    mock_query_sub_agents,
    mock_create_tool_config
):
    """
    Test export when model_id exists but model record is not found.

    This can happen if:
    - Model was deleted after agent creation
    - Database inconsistency
    """
    # Setup
    mock_agent_info_from_db = {
        "name": "orphaned_agent",
        "display_name": "Orphaned Agent",
        "description": "Agent with missing model",
        "business_description": "Test",
        "max_steps": 5,
        "provide_run_summary": False,
        "duty_prompt": "Test",
        "constraint_prompt": "Test",
        "few_shots_prompt": "Test",
        "enabled": True,
        "model_id": 999,  # This model doesn't exist
        "business_logic_model_id": 998  # This model doesn't exist
    }
    mock_search_agent_info.return_value = mock_agent_info_from_db

    # Model lookup returns None (model not found)
    mock_get_model_by_model_id.return_value = None

    mock_query_sub_agents.return_value = []
    mock_create_tool_config.return_value = []

    # Execute export
    exported_agent = await export_agent_by_agent_id(
        agent_id=123,
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert - should handle gracefully
    assert exported_agent.model_id == 999  # ID is preserved
    assert exported_agent.model_name is None  # But name is None (model not found)
    assert exported_agent.business_logic_model_id == 998
    assert exported_agent.business_logic_model_name is None


@patch('backend.services.agent_service.get_model_id_by_display_name')
@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@pytest.mark.asyncio
async def test_import_agent_model_name_consistency(
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
    mock_get_model_id_by_display_name
):
    """
    Test that both model_id and model_name are consistently saved during import.

    This test ensures that:
    1. model_id is looked up from model_name
    2. Both model_id AND model_name are saved to database
    3. This maintains data consistency and cross-tenant compatibility
    """
    # Setup
    mock_query_all_tools.return_value = []
    mock_get_model_id_by_display_name.side_effect = [5, 4]

    # Track what was passed to create_agent
    captured_agent_info = {}

    def capture_agent_info(agent_info, tenant_id, user_id):
        captured_agent_info.update(agent_info)
        return {"agent_id": 888}

    mock_create_agent.side_effect = capture_agent_info

    # Create import data
    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="consistency_test_agent",
        display_name="Consistency Test Agent",
        description="Testing model field consistency",
        business_description="Test",
        max_steps=5,
        provide_run_summary=False,
        duty_prompt="Test",
        constraint_prompt="Test",
        few_shots_prompt="Test",
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=100,  # Original ID (will be remapped)
        model_name="Qwen/Qwen3-8B",  # Used for lookup
        business_logic_model_id=99,  # Original ID (will be remapped)
        business_logic_model_name="Qwen/QwQ-32B"  # Used for lookup
    )

    # Execute import
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert
    assert result == 888

    # Verify BOTH model_id (remapped) AND model_name (preserved) are in database
    assert "model_id" in captured_agent_info
    assert "model_name" in captured_agent_info
    assert "business_logic_model_id" in captured_agent_info
    assert "business_logic_model_name" in captured_agent_info

    # Verify consistency between ID and name
    assert captured_agent_info["model_id"] == 5  # Remapped ID
    assert captured_agent_info["model_name"] == "Qwen/Qwen3-8B"  # Preserved name

    assert captured_agent_info["business_logic_model_id"] == 4  # Remapped ID
    assert captured_agent_info["business_logic_model_name"] == "Qwen/QwQ-32B"  # Preserved name

    # This consistency allows:
    # 1. Fast lookups by model_id (integer index)
    # 2. Human-readable model information (model_name)
    # 3. Cross-tenant import compatibility (lookup by name, save by ID)


# ============================================================================
# Tests for Agent Import with Quick Config Model Fallback
# ============================================================================


@pytest.fixture
def mock_tenant_id():
    """Fixture for tenant ID"""
    return "test_tenant_123"


@pytest.fixture
def mock_user_id():
    """Fixture for user ID"""
    return "test_user_456"


@pytest.fixture
def sample_agent_info():
    """Fixture for sample agent import information"""
    return {
        "agent_id": 1,
        "name": "test_agent",
        "display_name": "Test Agent",
        "description": "Test description",
        "business_description": "Test business description",
        "model_id": 10,  # Original model ID from source tenant
        "model_name": "Qwen/Qwen3-8B",  # Model that might not exist in target tenant
        "business_logic_model_id": 20,  # Original business logic model ID
        "business_logic_model_name": "Qwen/QwQ-32B",  # Business logic model
        "max_steps": 5,
        "provide_run_summary": True,
        "duty_prompt": "Test duty",
        "constraint_prompt": "Test constraint",
        "few_shots_prompt": "Test few shots",
        "enabled": True,
        "tools": [],
        "managed_agents": []
    }


@pytest.fixture
def sample_quick_config_model():
    """Fixture for quick config LLM model"""
    return {
        "model_id": 100,
        "model_name": "DeepSeek/DeepSeek-V3",
        "display_name": "DeepSeek V3",
        "model_repo": "DeepSeek",
        "model_type": "chat",
        "api_key": "test_key",
        "base_url": "https://api.deepseek.com"
    }


@pytest.fixture
def mock_import_agent_info(sample_agent_info):
    """Fixture for ExportAndImportAgentInfo object"""
    return ExportAndImportAgentInfo(**sample_agent_info)


@pytest.mark.asyncio
@patch("backend.services.agent_service.query_all_tools")
@patch("backend.services.agent_service.get_model_id_by_display_name")
@patch("backend.services.agent_service.tenant_config_manager")
@patch("backend.services.agent_service.create_agent")
async def test_main_model_fallback_to_quick_config(
    mock_create_agent,
    mock_tenant_config_manager,
    mock_get_model_id,
    mock_query_tools,
    mock_tenant_id,
    mock_user_id,
    sample_agent_info,
    sample_quick_config_model,
    mock_import_agent_info
):
    """
    Test that when main model is not found, system falls back to quick config LLM model

    Scenario:
    - Agent config specifies "Qwen/Qwen3-8B" as main model
    - Model not found in target tenant
    - System should fallback to quick config LLM model (DeepSeek V3)
    - Agent should be created with quick config model_id
    """
    # Setup: No tools to process
    mock_query_tools.return_value = []

    # Setup: Model not found by display name, but quick config exists
    mock_get_model_id.side_effect = [
        None,  # Main model not found
        50  # Business logic model found
    ]

    mock_tenant_config_manager.get_model_config.return_value = sample_quick_config_model

    mock_create_agent.return_value = {
        "agent_id": 999,
        "name": sample_agent_info["name"]
    }

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=mock_import_agent_info,
        tenant_id=mock_tenant_id,
        user_id=mock_user_id
    )

    # Verify: Quick config model was requested
    from consts.const import MODEL_CONFIG_MAPPING
    mock_tenant_config_manager.get_model_config.assert_called_with(
        key=MODEL_CONFIG_MAPPING["llm"],
        tenant_id=mock_tenant_id
    )

    # Verify: Agent was created with quick config model_id
    mock_create_agent.assert_called_once()
    call_args = mock_create_agent.call_args
    agent_info = call_args.kwargs["agent_info"]

    assert agent_info["model_id"] == sample_quick_config_model["model_id"]
    assert result == 999


@pytest.mark.asyncio
@patch("backend.services.agent_service.query_all_tools")
@patch("backend.services.agent_service.get_model_id_by_display_name")
@patch("backend.services.agent_service.tenant_config_manager")
@patch("backend.services.agent_service.create_agent")
async def test_business_logic_model_fallback_to_quick_config(
    mock_create_agent,
    mock_tenant_config_manager,
    mock_get_model_id,
    mock_query_tools,
    mock_tenant_id,
    mock_user_id,
    sample_agent_info,
    sample_quick_config_model,
    mock_import_agent_info
):
    """
    Test that when business logic model is not found, system falls back to quick config LLM model

    Scenario:
    - Agent config specifies "Qwen/QwQ-32B" as business logic model
    - Business logic model not found in target tenant
    - System should fallback to quick config LLM model
    - Agent should be created with quick config model_id for business logic
    """
    # Setup: No tools to process
    mock_query_tools.return_value = []

    # Setup: Main model found, but business logic model not found
    main_model_id = 50
    mock_get_model_id.side_effect = [
        main_model_id,  # Main model found
        None  # Business logic model not found
    ]

    mock_tenant_config_manager.get_model_config.return_value = sample_quick_config_model

    mock_create_agent.return_value = {
        "agent_id": 888,
        "name": sample_agent_info["name"]
    }

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=mock_import_agent_info,
        tenant_id=mock_tenant_id,
        user_id=mock_user_id
    )

    # Verify: Quick config model was requested for business logic model
    from consts.const import MODEL_CONFIG_MAPPING
    mock_tenant_config_manager.get_model_config.assert_called_with(
        key=MODEL_CONFIG_MAPPING["llm"],
        tenant_id=mock_tenant_id
    )

    # Verify: Agent was created with correct model IDs
    mock_create_agent.assert_called_once()
    call_args = mock_create_agent.call_args
    agent_info = call_args.kwargs["agent_info"]

    assert agent_info["model_id"] == main_model_id
    assert agent_info["business_logic_model_id"] == sample_quick_config_model["model_id"]
    assert result == 888


@pytest.mark.asyncio
@patch("backend.services.agent_service.query_all_tools")
@patch("backend.services.agent_service.get_model_id_by_display_name")
@patch("backend.services.agent_service.tenant_config_manager")
@patch("backend.services.agent_service.create_agent")
async def test_both_models_fallback_to_quick_config(
    mock_create_agent,
    mock_tenant_config_manager,
    mock_get_model_id,
    mock_query_tools,
    mock_tenant_id,
    mock_user_id,
    sample_agent_info,
    sample_quick_config_model,
    mock_import_agent_info
):
    """
    Test that both main and business logic models fallback to quick config when not found

    Scenario:
    - Neither main model nor business logic model found in target tenant
    - Both should fallback to quick config LLM model
    - Agent should be created with quick config model_id for both fields
    """
    # Setup: No tools to process
    mock_query_tools.return_value = []

    # Setup: Both models not found
    mock_get_model_id.side_effect = [
        None,  # Main model not found
        None  # Business logic model not found
    ]

    mock_tenant_config_manager.get_model_config.return_value = sample_quick_config_model

    mock_create_agent.return_value = {
        "agent_id": 777,
        "name": sample_agent_info["name"]
    }

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=mock_import_agent_info,
        tenant_id=mock_tenant_id,
        user_id=mock_user_id
    )

    # Verify: Quick config model was requested twice (once for each model)
    assert mock_tenant_config_manager.get_model_config.call_count == 2

    # Verify: Agent was created with quick config model_id for both fields
    mock_create_agent.assert_called_once()
    call_args = mock_create_agent.call_args
    agent_info = call_args.kwargs["agent_info"]

    assert agent_info["model_id"] == sample_quick_config_model["model_id"]
    assert agent_info["business_logic_model_id"] == sample_quick_config_model["model_id"]
    assert result == 777


@pytest.mark.asyncio
@patch("backend.services.agent_service.query_all_tools")
@patch("backend.services.agent_service.get_model_id_by_display_name")
@patch("backend.services.agent_service.tenant_config_manager")
@patch("backend.services.agent_service.create_agent")
async def test_no_quick_config_model_available(
    mock_create_agent,
    mock_tenant_config_manager,
    mock_get_model_id,
    mock_query_tools,
    mock_tenant_id,
    mock_user_id,
    sample_agent_info,
    mock_import_agent_info
):
    """
    Test behavior when model not found and no quick config model is available

    Scenario:
    - Main model not found in target tenant
    - Quick config LLM model also not configured
    - Agent should be created with model_id = None
    """
    # Setup: No tools to process
    mock_query_tools.return_value = []

    # Setup: Model not found and no quick config
    mock_get_model_id.side_effect = [
        None,  # Main model not found
        50  # Business logic model found
    ]

    mock_tenant_config_manager.get_model_config.return_value = None  # No quick config

    mock_create_agent.return_value = {
        "agent_id": 666,
        "name": sample_agent_info["name"]
    }

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=mock_import_agent_info,
        tenant_id=mock_tenant_id,
        user_id=mock_user_id
    )

    # Verify: Quick config was attempted
    from consts.const import MODEL_CONFIG_MAPPING
    mock_tenant_config_manager.get_model_config.assert_called_with(
        key=MODEL_CONFIG_MAPPING["llm"],
        tenant_id=mock_tenant_id
    )

    # Verify: Agent was created with model_id = None
    mock_create_agent.assert_called_once()
    call_args = mock_create_agent.call_args
    agent_info = call_args.kwargs["agent_info"]

    assert agent_info["model_id"] is None
    assert agent_info["business_logic_model_id"] == 50
    assert result == 666


@pytest.mark.asyncio
@patch("backend.services.agent_service.query_all_tools")
@patch("backend.services.agent_service.get_model_id_by_display_name")
@patch("backend.services.agent_service.tenant_config_manager")
@patch("backend.services.agent_service.create_agent")
async def test_model_found_no_fallback_needed(
    mock_create_agent,
    mock_tenant_config_manager,
    mock_get_model_id,
    mock_query_tools,
    mock_tenant_id,
    mock_user_id,
    sample_agent_info,
    mock_import_agent_info
):
    """
    Test that quick config fallback is NOT used when model is found

    Scenario:
    - Both main model and business logic model found in target tenant
    - Quick config should NOT be called
    - Agent should be created with found model IDs
    """
    # Setup: No tools to process
    mock_query_tools.return_value = []

    # Setup: Both models found
    main_model_id = 30
    business_logic_model_id = 40

    mock_get_model_id.side_effect = [
        main_model_id,  # Main model found
        business_logic_model_id  # Business logic model found
    ]

    mock_create_agent.return_value = {
        "agent_id": 555,
        "name": sample_agent_info["name"]
    }

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=mock_import_agent_info,
        tenant_id=mock_tenant_id,
        user_id=mock_user_id
    )

    # Verify: Quick config was NOT called
    mock_tenant_config_manager.get_model_config.assert_not_called()

    # Verify: Agent was created with found model IDs
    mock_create_agent.assert_called_once()
    call_args = mock_create_agent.call_args
    agent_info = call_args.kwargs["agent_info"]

    assert agent_info["model_id"] == main_model_id
    assert agent_info["business_logic_model_id"] == business_logic_model_id
    assert result == 555


# ============================================================================
# Tests for Model Name Fields in Import
# ============================================================================


@patch('backend.services.agent_service.get_model_id_by_display_name')
@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@pytest.mark.asyncio
async def test_import_agent_includes_model_names(
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
    mock_get_model_id
):
    """
    Test that import_agent_by_agent_id passes model_name and business_logic_model_name
    to create_agent, ensuring these fields are not NULL in the database.

    This test verifies the fix for the bug where these fields were missing from the
    agent_info dictionary passed to create_agent().
    """
    # Setup
    mock_tool_info = [
        {
            "tool_id": 101,
            "class_name": "TestTool",
            "source": "local",
            "params": [{"name": "param1", "type": "string"}],
            "description": "Test tool",
            "name": "Test Tool",
            "inputs": "test input",
            "output_type": "string"
        }
    ]
    mock_query_all_tools.return_value = mock_tool_info

    # Mock model ID lookup to return valid IDs
    mock_get_model_id.side_effect = [5, 4]  # First call for model_id, second for business_logic_model_id

    mock_create_agent.return_value = {"agent_id": 999}

    # Create import data with model_name and business_logic_model_name
    from nexent.core.agents.agent_model import ToolConfig as NexentToolConfig

    tool_config = NexentToolConfig(
        class_name="TestTool",
        name="Test Tool",
        source="local",
        params={"param1": "value1"},
        metadata={},
        description="Test tool",
        inputs="test input",
        output_type="string",
        usage=None
    )

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="iot_knowledge_qa_assistant",
        display_name="物联网知识问答助手",
        description="IoT Q&A Assistant",
        business_description="IoT knowledge retrieval assistant",
        max_steps=5,
        provide_run_summary=False,
        duty_prompt="You are an IoT Q&A assistant",
        constraint_prompt="Follow safety guidelines",
        few_shots_prompt="Example tasks...",
        enabled=True,
        tools=[tool_config],
        managed_agents=[],
        model_id=5,
        model_name="Qwen/Qwen3-8B",  # This is critical
        business_logic_model_id=4,
        business_logic_model_name="Qwen/QwQ-32B"  # This is critical
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert - verify the agent was created
    assert result == 999

    # Critical assertion: verify that model_name and business_logic_model_name
    # were passed to create_agent
    mock_create_agent.assert_called_once()
    call_kwargs = mock_create_agent.call_args[1]
    agent_info_dict = call_kwargs["agent_info"]

    # Verify all model-related fields are present
    assert "model_id" in agent_info_dict
    assert "model_name" in agent_info_dict  # ← This was missing before the fix
    assert "business_logic_model_id" in agent_info_dict
    assert "business_logic_model_name" in agent_info_dict  # ← This was missing before the fix

    # Verify the values are correct
    assert agent_info_dict["model_name"] == "Qwen/Qwen3-8B"
    assert agent_info_dict["business_logic_model_name"] == "Qwen/QwQ-32B"

    # Verify other fields are also present
    assert agent_info_dict["name"] == "iot_knowledge_qa_assistant"
    assert agent_info_dict["display_name"] == "物联网知识问答助手"
    assert agent_info_dict["max_steps"] == 5


@patch('backend.services.agent_service.get_model_id_by_display_name')
@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@pytest.mark.asyncio
async def test_import_agent_without_business_logic_model(
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
    mock_get_model_id
):
    """
    Test import when business_logic_model_name is None.

    Verifies that the function handles cases where business logic model is not set.
    """
    # Setup
    mock_query_all_tools.return_value = []
    mock_get_model_id.return_value = 5  # Only one model lookup
    mock_create_agent.return_value = {"agent_id": 888}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="simple_agent",
        display_name="Simple Agent",
        description="A simple agent",
        business_description="Simple agent description",
        max_steps=3,
        provide_run_summary=False,
        duty_prompt="Do your duty",
        constraint_prompt="Follow constraints",
        few_shots_prompt="Examples",
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=5,
        model_name="Qwen/Qwen3-8B",
        business_logic_model_id=None,  # No business logic model
        business_logic_model_name=None
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert
    assert result == 888
    mock_create_agent.assert_called_once()

    call_kwargs = mock_create_agent.call_args[1]
    agent_info_dict = call_kwargs["agent_info"]

    # Verify model fields are present
    assert agent_info_dict["model_name"] == "Qwen/Qwen3-8B"
    assert agent_info_dict["business_logic_model_name"] is None
    assert agent_info_dict["business_logic_model_id"] is None


@patch('backend.services.agent_service.get_model_id_by_display_name')
@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@pytest.mark.asyncio
async def test_import_agent_model_lookup_by_display_name(
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
    mock_get_model_id
):
    """
    Test that model_id is looked up by display_name (model_name) for cross-tenant compatibility.

    This test verifies that the import process uses model_name to find the corresponding
    model_id in the target tenant, rather than directly using the exported model_id.
    """
    # Setup
    mock_query_all_tools.return_value = []

    # Simulate cross-tenant import where model IDs are different
    # Exported: model_id=10, model_name="Qwen/Qwen3-8B"
    # Target tenant: model_id=5 for "Qwen/Qwen3-8B"
    mock_get_model_id.side_effect = [5, 4]  # Returns different IDs than exported

    mock_create_agent.return_value = {"agent_id": 777}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="cross_tenant_agent",
        display_name="Cross Tenant Agent",
        description="Agent imported from another tenant",
        business_description="Cross-tenant import test",
        max_steps=5,
        provide_run_summary=False,
        duty_prompt="Cross-tenant duty",
        constraint_prompt="Cross-tenant constraints",
        few_shots_prompt="Cross-tenant examples",
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=10,  # Original model_id in source tenant
        model_name="Qwen/Qwen3-8B",  # Used for lookup in target tenant
        business_logic_model_id=9,  # Original business logic model_id
        business_logic_model_name="Qwen/QwQ-32B"  # Used for lookup
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="target_tenant",
        user_id="test_user"
    )

    # Assert
    assert result == 777

    # Verify model lookup was called with display names (model_name)
    assert mock_get_model_id.call_count == 2
    first_call = mock_get_model_id.call_args_list[0]
    second_call = mock_get_model_id.call_args_list[1]

    # First call should be for model_name
    # get_model_id_by_display_name(display_name: str, tenant_id: str) uses positional args
    assert first_call[0][0] == "Qwen/Qwen3-8B"  # display_name
    assert first_call[0][1] == "target_tenant"  # tenant_id

    # Second call should be for business_logic_model_name
    assert second_call[0][0] == "Qwen/QwQ-32B"  # display_name
    assert second_call[0][1] == "target_tenant"  # tenant_id

    # Verify the NEW model IDs (from target tenant) were used, not the exported ones
    call_kwargs = mock_create_agent.call_args[1]
    agent_info_dict = call_kwargs["agent_info"]

    assert agent_info_dict["model_id"] == 5  # New ID, not 10
    assert agent_info_dict["business_logic_model_id"] == 4  # New ID, not 9

    # Verify model_name fields are preserved
    assert agent_info_dict["model_name"] == "Qwen/Qwen3-8B"
    assert agent_info_dict["business_logic_model_name"] == "Qwen/QwQ-32B"


@patch('backend.services.agent_service.tenant_config_manager')
@patch('backend.services.agent_service.get_model_id_by_display_name')
@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@pytest.mark.asyncio
async def test_import_agent_model_not_found_in_target_tenant(
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
    mock_get_model_id,
    mock_tenant_config_manager
):
    """
    Test that import fails gracefully when the model doesn't exist in target tenant.
    """
    # Setup
    mock_query_all_tools.return_value = []

    # Simulate model not found in target tenant
    mock_get_model_id.return_value = None

    # Mock the tenant config manager to return None (no quick config fallback)
    mock_tenant_config_manager.get_model_config.return_value = None

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="missing_model_agent",
        display_name="Agent with Missing Model",
        description="Test missing model",
        business_description="Missing model test",
        max_steps=5,
        provide_run_summary=False,
        duty_prompt="Duty",
        constraint_prompt="Constraints",
        few_shots_prompt="Examples",
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=10,
        model_name="NonExistent/Model",  # This model doesn't exist in target tenant
        business_logic_model_id=None,
        business_logic_model_name=None
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="target_tenant",
        user_id="test_user"
    )

    # Assert - should still create agent but with None model_id
    assert result is not None
    mock_create_agent.assert_called_once()

    call_kwargs = mock_create_agent.call_args[1]
    agent_info_dict = call_kwargs["agent_info"]

    # model_id should be None since model wasn't found
    assert agent_info_dict["model_id"] is None
    # But model_name should still be preserved
    assert agent_info_dict["model_name"] == "NonExistent/Model"


@patch('backend.services.agent_service.get_model_id_by_display_name')
@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@pytest.mark.asyncio
async def test_import_agent_all_model_fields_in_database(
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
    mock_get_model_id
):
    """
    Integration-style test to verify all model fields are correctly passed to the database.

    This test ensures that after the fix, all four model-related fields are included:
    - model_id
    - model_name
    - business_logic_model_id
    - business_logic_model_name
    """
    # Setup
    mock_query_all_tools.return_value = []
    mock_get_model_id.side_effect = [5, 4]

    # Mock create_agent to return the agent info as it would be inserted
    def mock_create_agent_impl(agent_info, tenant_id, user_id):
        return {
            "agent_id": 666,
            **agent_info  # Simulate returning all fields that were passed in
        }

    mock_create_agent.side_effect = mock_create_agent_impl

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="complete_agent",
        display_name="Complete Agent",
        description="Agent with all fields",
        business_description="Complete test",
        max_steps=5,
        provide_run_summary=True,
        duty_prompt="Complete duty",
        constraint_prompt="Complete constraints",
        few_shots_prompt="Complete examples",
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=10,
        model_name="Qwen/Qwen3-8B",
        business_logic_model_id=9,
        business_logic_model_name="Qwen/QwQ-32B"
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user"
    )

    # Assert
    assert result == 666

    # Verify all four model fields were passed to create_agent
    call_kwargs = mock_create_agent.call_args[1]
    agent_info_dict = call_kwargs["agent_info"]

    # All four fields should be present and not None
    assert "model_id" in agent_info_dict
    assert "model_name" in agent_info_dict
    assert "business_logic_model_id" in agent_info_dict
    assert "business_logic_model_name" in agent_info_dict

    assert agent_info_dict["model_id"] == 5
    assert agent_info_dict["model_name"] == "Qwen/Qwen3-8B"
    assert agent_info_dict["business_logic_model_id"] == 4
    assert agent_info_dict["business_logic_model_name"] == "Qwen/QwQ-32B"

    # Verify other standard fields
    assert agent_info_dict["name"] == "complete_agent"
    assert agent_info_dict["display_name"] == "Complete Agent"
    assert agent_info_dict["description"] == "Agent with all fields"
    assert agent_info_dict["business_description"] == "Complete test"
    assert agent_info_dict["max_steps"] == 5
    assert agent_info_dict["provide_run_summary"] is True
    assert agent_info_dict["duty_prompt"] == "Complete duty"
    assert agent_info_dict["constraint_prompt"] == "Complete constraints"
    assert agent_info_dict["few_shots_prompt"] == "Complete examples"
    assert agent_info_dict["enabled"] is True


# =====================================================================
# Additional tests for internal helper functions and import logic
# =====================================================================


def test_normalize_language_key_variants():
    """_normalize_language_key should normalize various language inputs."""
    from consts.const import LANGUAGE as LANG

    assert _normalize_language_key("zh-CN") == LANG["ZH"]
    assert _normalize_language_key("ZH") == LANG["ZH"]
    assert _normalize_language_key("en") == LANG["EN"]
    assert _normalize_language_key("EN-us") == LANG["EN"]
    # Fallback when language is None or empty
    assert _normalize_language_key("") == LANG["EN"]
    assert _normalize_language_key(None) == LANG["EN"]


def test_render_prompt_template_success(monkeypatch):
    """_render_prompt_template should render a jinja2 template successfully."""

    class FakeTemplate:
        def __init__(self, template_str):
            self.template_str = template_str

        def render(self, **context):
            # Very small fake renderer for test purposes
            return self.template_str.format(**context)

    monkeypatch.setattr(
        agent_service, "Template", FakeTemplate, raising=False
    )

    tpl = "Hello {name}"
    rendered = _render_prompt_template(tpl, name="World")
    assert rendered == "Hello World"


def test_render_prompt_template_on_error_returns_original(monkeypatch):
    """When Template.render fails, _render_prompt_template should return original template."""

    class FailingTemplate:
        def __init__(self, template_str):
            self.template_str = template_str

        def render(self, **context):
            raise ValueError("render failed")

    monkeypatch.setattr(
        agent_service, "Template", FailingTemplate, raising=False
    )

    tpl = "Broken {template"
    # Should not raise; should return original string
    assert _render_prompt_template(tpl, name="x") == tpl


def test_format_existing_values_for_languages():
    """_format_existing_values should format values and handle empty cases."""
    from consts.const import LANGUAGE as LANG

    # Non-empty set
    values = {"b", "a"}
    formatted = _format_existing_values(values, LANG["EN"])
    assert formatted in {"a, b", "b, a"}  # order not guaranteed

    # Empty set, English
    assert _format_existing_values(set(), LANG["EN"]) == "None"
    # Empty set, Chinese
    assert _format_existing_values(set(), LANG["ZH"]).startswith("无")


def test_check_agent_value_duplicate_with_and_without_exclude():
    """_check_agent_value_duplicate should respect exclude_agent_id and cache."""
    agents = [
        {"agent_id": 1, "name": "agent_one"},
        {"agent_id": 2, "name": "agent_two"},
    ]

    # Duplicate found
    assert agent_service._check_agent_value_duplicate(
        "name", "agent_one", tenant_id="t", agents_cache=agents
    )
    # No duplicate
    assert not agent_service._check_agent_value_duplicate(
        "name", "agent_three", tenant_id="t", agents_cache=agents
    )
    # Exclude matching id should skip that record
    assert not agent_service._check_agent_value_duplicate(
        "name", "agent_one", tenant_id="t", exclude_agent_id=1, agents_cache=agents
    )


@patch('backend.services.agent_service.query_all_agent_info_by_tenant_id')
def test_check_agent_value_duplicate_empty_value(mock_query_all):
    """_check_agent_value_duplicate should return False when value is empty."""
    # Test empty string
    assert not agent_service._check_agent_value_duplicate(
        "name", "", tenant_id="t", agents_cache=[]
    )
    # Test None value
    assert not agent_service._check_agent_value_duplicate(
        "name", None, tenant_id="t", agents_cache=[]
    )
    # Should not call query_all_agent_info_by_tenant_id when value is empty
    mock_query_all.assert_not_called()


@patch('backend.services.agent_service.query_all_agent_info_by_tenant_id')
def test_check_agent_value_duplicate_cache_none(mock_query_all):
    """_check_agent_value_duplicate should query database when agents_cache is None."""
    mock_query_all.return_value = [
        {"agent_id": 1, "name": "agent_one"},
        {"agent_id": 2, "name": "agent_two"},
    ]

    # Should query database when cache is None
    assert agent_service._check_agent_value_duplicate(
        "name", "agent_one", tenant_id="t", agents_cache=None
    )
    mock_query_all.assert_called_once_with("t")

    # Reset mock
    mock_query_all.reset_mock()
    mock_query_all.return_value = [
        {"agent_id": 1, "name": "agent_one"},
        {"agent_id": 2, "name": "agent_two"},
    ]

    # Should query database when cache is None and no duplicate found
    assert not agent_service._check_agent_value_duplicate(
        "name", "agent_three", tenant_id="t", agents_cache=None
    )
    mock_query_all.assert_called_once_with("t")


def test_generate_unique_value_with_suffix_success():
    """_generate_unique_value_with_suffix should find first available suffix."""

    taken = {"base_1"}

    def dup_check(candidate, **_):
        return candidate in taken

    result = _generate_unique_value_with_suffix(
        "base",
        tenant_id="tenant",
        duplicate_check_fn=dup_check,
        agents_cache=[],
        max_suffix_attempts=5,
    )
    # base_1 is taken, so should start from base_2
    assert result == "base_2"


def test_generate_unique_value_with_suffix_exhausts_attempts():
    """When all candidates are duplicates, _generate_unique_value_with_suffix should raise."""

    def always_duplicate(*args, **kwargs):
        return True

    with pytest.raises(ValueError, match="Failed to generate unique value"):
        _generate_unique_value_with_suffix(
            "dup",
            tenant_id="tenant",
            duplicate_check_fn=always_duplicate,
            agents_cache=[],
            max_suffix_attempts=3,
        )


def test_generate_unique_agent_and_display_name_wrappers(monkeypatch):
    """Wrapper helpers should delegate to _generate_unique_value_with_suffix."""
    calls = []

    def fake_generate(base_value, tenant_id, duplicate_check_fn, agents_cache, exclude_agent_id=None, max_suffix_attempts=100):
        calls.append(
            (base_value, tenant_id, duplicate_check_fn, tuple(agents_cache), exclude_agent_id, max_suffix_attempts)
        )
        return f"{base_value}_unique"

    monkeypatch.setattr(
        agent_service, "_generate_unique_value_with_suffix", fake_generate, raising=False
    )

    name = _generate_unique_agent_name_with_suffix(
        "agent", tenant_id="t", agents_cache=[{"agent_id": 1}], exclude_agent_id=1
    )
    display = _generate_unique_display_name_with_suffix(
        "Agent Display", tenant_id="t2", agents_cache=[{"agent_id": 2}]
    )

    assert name == "agent_unique"
    assert display == "Agent Display_unique"
    # Ensure both calls delegated correctly
    assert len(calls) == 2
    assert calls[0][0] == "agent"
    assert calls[1][0] == "Agent Display"


def test_regenerate_agent_value_with_llm_success(monkeypatch):
    """_regenerate_agent_value_with_llm should return first non-duplicate LLM value."""

    # Avoid dependency on real prompt templates
    monkeypatch.setattr(
        agent_service,
        "get_prompt_generate_prompt_template",
        lambda lang: {},
        raising=False,
    )

    # Provide a fake LLM call that returns a new unique value
    def fake_call_llm(model_id, user_prompt, system_prompt, callback, tenant_id):
        assert model_id == 1
        assert tenant_id == "tenant"
        # Callback is not used in this helper, but should be passed through
        return "new_name\nextra"

    # Ensure the dynamic import `from services.prompt_service import ...` in
    # `_regenerate_agent_value_with_llm` can succeed by registering a fake
    # module in `sys.modules` with the expected attribute.
    monkeypatch.setattr(
        agent_service,
        "call_llm_for_system_prompt",
        fake_call_llm,
        raising=False,
    )

    result = _regenerate_agent_value_with_llm(
        original_value="old",
        existing_values=["existing"],
        task_description="task",
        model_id=1,
        tenant_id="tenant",
        language="en",
        system_prompt_key="SYS_KEY",
        user_prompt_key="USER_KEY",
        default_system_prompt="sys",
        default_user_prompt_builder=lambda ctx: "user",
        fallback_fn=lambda base: f"fallback_{base}",
    )
    assert result == "new_name"


def test_regenerate_agent_value_with_llm_fallback_on_error(monkeypatch):
    """When LLM keeps failing, _regenerate_agent_value_with_llm should use fallback."""

    monkeypatch.setattr(
        agent_service,
        "get_prompt_generate_prompt_template",
        lambda lang: {},
        raising=False,
    )

    def failing_llm(*args, **kwargs):
        raise RuntimeError("llm failed")

    monkeypatch.setattr(
        agent_service,
        "call_llm_for_system_prompt",
        failing_llm,
        raising=False,
    )

    used = {}

    def fallback(base):
        used["called"] = True
        return f"fb_{base}"

    result = _regenerate_agent_value_with_llm(
        original_value="orig",
        existing_values=["a", "b"],
        task_description="task",
        model_id=1,
        tenant_id="tenant",
        language="en",
        system_prompt_key="SYS_KEY",
        user_prompt_key="USER_KEY",
        default_system_prompt="sys",
        default_user_prompt_builder=lambda ctx: "user",
        fallback_fn=fallback,
    )

    assert result == "fb_orig"
    assert used.get("called") is True


def test_regenerate_agent_value_with_llm_empty_system_prompt(monkeypatch):
    """_regenerate_agent_value_with_llm should use default_system_prompt when system_prompt is empty."""

    monkeypatch.setattr(
        agent_service,
        "get_prompt_generate_prompt_template",
        lambda lang: {},
        raising=False,
    )
    monkeypatch.setattr(
        agent_service,
        "_render_prompt_template",
        lambda template_str, **kwargs: "",  # Return empty string
        raising=False,
    )

    def fake_call_llm(model_id, user_prompt, system_prompt, callback, tenant_id):
        # Verify that default_system_prompt was used
        assert system_prompt == "default_system"
        return "new_name"

    monkeypatch.setattr(
        agent_service,
        "call_llm_for_system_prompt",
        fake_call_llm,
        raising=False,
    )

    result = _regenerate_agent_value_with_llm(
        original_value="old",
        existing_values=["existing"],
        task_description="task",
        model_id=1,
        tenant_id="tenant",
        language="en",
        system_prompt_key="SYS_KEY",
        user_prompt_key="USER_KEY",
        default_system_prompt="default_system",
        default_user_prompt_builder=lambda ctx: "user",
        fallback_fn=lambda base: f"fallback_{base}",
    )
    assert result == "new_name"


def test_regenerate_agent_value_with_llm_empty_user_prompt(monkeypatch):
    """_regenerate_agent_value_with_llm should use default_user_prompt_builder when user_prompt is empty (line 302)."""

    monkeypatch.setattr(
        agent_service,
        "get_prompt_generate_prompt_template",
        lambda lang: {},
        raising=False,
    )

    call_count = {"render_count": 0}

    def mock_render(template_str, **kwargs):
        call_count["render_count"] += 1
        # First call is for system_prompt, return non-empty
        if call_count["render_count"] == 1:
            return "system_prompt"
        # Second call is for user_prompt, return empty string to trigger line 302
        return ""

    monkeypatch.setattr(
        agent_service,
        "_render_prompt_template",
        mock_render,
        raising=False,
    )

    builder_called = {"called": False}

    def default_user_prompt_builder(ctx):
        builder_called["called"] = True
        # Verify context is passed correctly
        assert "task_description" in ctx
        assert "original_value" in ctx
        assert "existing_values" in ctx
        return "default_user"

    def fake_call_llm(model_id, user_prompt, system_prompt, callback, tenant_id):
        # Verify that default_user_prompt_builder was used (line 302-303)
        assert user_prompt == "default_user"
        assert builder_called["called"], "default_user_prompt_builder should have been called"
        return "new_name"

    monkeypatch.setattr(
        agent_service,
        "call_llm_for_system_prompt",
        fake_call_llm,
        raising=False,
    )

    result = _regenerate_agent_value_with_llm(
        original_value="old",
        existing_values=["existing"],
        task_description="task",
        model_id=1,
        tenant_id="tenant",
        language="en",
        system_prompt_key="SYS_KEY",
        user_prompt_key="USER_KEY",
        default_system_prompt="system_prompt",
        default_user_prompt_builder=default_user_prompt_builder,
        fallback_fn=lambda base: f"fallback_{base}",
    )
    assert result == "new_name"
    assert builder_called["called"], "default_user_prompt_builder should have been called to cover line 302"


def test_regenerate_agent_value_with_llm_duplicate_candidate(monkeypatch):
    """_regenerate_agent_value_with_llm should raise ValueError when generated candidate is duplicate."""

    monkeypatch.setattr(
        agent_service,
        "get_prompt_generate_prompt_template",
        lambda lang: {},
        raising=False,
    )

    attempt_count = {"count": 0}

    def fake_call_llm(model_id, user_prompt, system_prompt, callback, tenant_id):
        attempt_count["count"] += 1
        # Return a value that exists in existing_values
        if attempt_count["count"] == 1:
            return "existing"  # This is a duplicate
        # On retry, return a unique value
        return "new_unique_name"

    monkeypatch.setattr(
        agent_service,
        "call_llm_for_system_prompt",
        fake_call_llm,
        raising=False,
    )

    result = _regenerate_agent_value_with_llm(
        original_value="old",
        existing_values=["existing", "another"],
        task_description="task",
        model_id=1,
        tenant_id="tenant",
        language="en",
        system_prompt_key="SYS_KEY",
        user_prompt_key="USER_KEY",
        default_system_prompt="sys",
        default_user_prompt_builder=lambda ctx: "user",
        fallback_fn=lambda base: f"fallback_{base}",
    )
    # Should retry and eventually return a unique value
    assert result == "new_unique_name"
    assert attempt_count["count"] == 2


def test_regenerate_agent_name_with_llm(monkeypatch):
    """_regenerate_agent_name_with_llm should call _regenerate_agent_value_with_llm with correct parameters."""

    monkeypatch.setattr(
        agent_service,
        "get_prompt_generate_prompt_template",
        lambda lang: {},
        raising=False,
    )

    def fake_call_llm(model_id, user_prompt, system_prompt, callback, tenant_id):
        return "new_agent_name"

    monkeypatch.setattr(
        agent_service,
        "call_llm_for_system_prompt",
        fake_call_llm,
        raising=False,
    )

    result = agent_service._regenerate_agent_name_with_llm(
        original_name="old_name",
        existing_names=["existing1", "existing2"],
        task_description="task desc",
        model_id=1,
        tenant_id="tenant",
        language="en",
        agents_cache=[],
        exclude_agent_id=None
    )

    assert result == "new_agent_name"


def test_regenerate_agent_display_name_with_llm(monkeypatch):
    """_regenerate_agent_display_name_with_llm should call _regenerate_agent_value_with_llm with correct parameters."""

    monkeypatch.setattr(
        agent_service,
        "get_prompt_generate_prompt_template",
        lambda lang: {},
        raising=False,
    )

    def fake_call_llm(model_id, user_prompt, system_prompt, callback, tenant_id):
        return "New Display Name"

    monkeypatch.setattr(
        agent_service,
        "call_llm_for_system_prompt",
        fake_call_llm,
        raising=False,
    )

    result = agent_service._regenerate_agent_display_name_with_llm(
        original_display_name="Old Display Name",
        existing_display_names=["Display1", "Display2"],
        task_description="task desc",
        model_id=1,
        tenant_id="tenant",
        language="en",
        agents_cache=[],
        exclude_agent_id=None
    )

    assert result == "New Display Name"


@pytest.mark.asyncio
async def test_import_agent_impl_dfs_import_order(monkeypatch):
    """
    import_agent_impl should handle DFS ordering and establish relationships correctly.
    This covers the branch where managed agents are not yet imported (agent_stack.extend path).
    """
    # Mock user and tenant
    monkeypatch.setattr(
        "backend.services.agent_service.get_current_user_info",
        lambda authorization: ("user1", "tenant1", "en"),
        raising=False,
    )

    # Skip MCP handling by providing no mcp_info and making update_tool_list a no-op
    from consts.model import ExportAndImportAgentInfo, ExportAndImportDataFormat

    root_agent = ExportAndImportAgentInfo(
        agent_id=1,
        name="root",
        display_name="Root",
        description="root",
        business_description="root",
        max_steps=5,
        provide_run_summary=False,
        duty_prompt=None,
        constraint_prompt=None,
        few_shots_prompt=None,
        enabled=True,
        tools=[],
        managed_agents=[2],
    )
    child_agent = ExportAndImportAgentInfo(
        agent_id=2,
        name="child",
        display_name="Child",
        description="child",
        business_description="child",
        max_steps=5,
        provide_run_summary=False,
        duty_prompt=None,
        constraint_prompt=None,
        few_shots_prompt=None,
        enabled=True,
        tools=[],
        managed_agents=[],
    )

    export_data = ExportAndImportDataFormat(
        agent_id=1,
        agent_info={"1": root_agent, "2": child_agent},
        mcp_info=[],
    )

    # Track import order and relationship creation
    imported_ids = []

    async def fake_import_agent_by_agent_id(import_agent_info, tenant_id, user_id, skip_duplicate_regeneration=False):
        # Assign synthetic new IDs based on source id
        new_id = 100 + import_agent_info.agent_id
        imported_ids.append(import_agent_info.agent_id)
        return new_id

    relationships = []

    def fake_insert_related_agent(parent_agent_id, child_agent_id, tenant_id):
        relationships.append((parent_agent_id, child_agent_id, tenant_id))

    async def fake_update_tool_list(tenant_id, user_id):
        return None

    monkeypatch.setattr(
        "backend.services.agent_service.import_agent_by_agent_id",
        fake_import_agent_by_agent_id,
        raising=False,
    )
    monkeypatch.setattr(
        "backend.services.agent_service.insert_related_agent",
        fake_insert_related_agent,
        raising=False,
    )
    monkeypatch.setattr(
        "backend.services.agent_service.update_tool_list",
        fake_update_tool_list,
        raising=False,
    )

    # Execute
    await import_agent_impl(export_data, authorization="Bearer token", force_import=False)

    # Child (2) must be imported before parent (1)
    assert imported_ids == [2, 1]
    # Relationship should be created between new IDs 101 (child) and 100 (parent)
    assert relationships == [(100 + 1, 100 + 2, "tenant1")]


# =====================================================================
# Tests for batch agent name conflict and regeneration
# =====================================================================


@pytest.mark.asyncio
async def test_check_agent_name_conflict_batch_impl_detects_conflicts(monkeypatch):
    monkeypatch.setattr(
        "backend.services.agent_service.get_current_user_info",
        lambda authorization: ("user-x", "tenant-x", "en"),
        raising=False,
    )
    existing_agents = [
        {"agent_id": 10, "name": "dup_name", "display_name": "Dup Display"},
        {"agent_id": 11, "name": "unique", "display_name": "Unique"},
    ]
    monkeypatch.setattr(
        "backend.services.agent_service.query_all_agent_info_by_tenant_id",
        lambda tenant_id: existing_agents,
        raising=False,
    )

    from consts.model import AgentNameBatchCheckItem, AgentNameBatchCheckRequest

    request = AgentNameBatchCheckRequest(
        items=[
            AgentNameBatchCheckItem(name="dup_name", display_name="Another"),
            AgentNameBatchCheckItem(name="", display_name=None),
        ]
    )

    result = await agent_service.check_agent_name_conflict_batch_impl(
        request, authorization="Bearer token"
    )

    assert result[0]["name_conflict"] is True
    assert result[0]["display_name_conflict"] is False
    assert result[0]["conflict_agents"] == [
        {"name": "dup_name", "display_name": "Dup Display"}
    ]
    assert result[1]["name_conflict"] is False
    assert result[1]["display_name_conflict"] is False
    assert result[1]["conflict_agents"] == []


@pytest.mark.asyncio
async def test_check_agent_name_conflict_batch_impl_display_conflict(monkeypatch):
    monkeypatch.setattr(
        "backend.services.agent_service.get_current_user_info",
        lambda authorization: ("user-x", "tenant-x", "en"),
        raising=False,
    )
    existing_agents = [
        {"agent_id": 3, "name": "alpha", "display_name": "Shown"},
    ]
    monkeypatch.setattr(
        "backend.services.agent_service.query_all_agent_info_by_tenant_id",
        lambda tenant_id: existing_agents,
        raising=False,
    )

    request = AgentNameBatchCheckRequest(
        items=[AgentNameBatchCheckItem(name="beta", display_name="Shown")]
    )

    result = await agent_service.check_agent_name_conflict_batch_impl(
        request, authorization="Bearer token"
    )

    assert result[0]["name_conflict"] is False
    assert result[0]["display_name_conflict"] is True
    assert result[0]["conflict_agents"] == [
        {"name": "alpha", "display_name": "Shown"}
    ]


@pytest.mark.asyncio
async def test_check_agent_name_conflict_batch_impl_skips_same_agent(monkeypatch):
    monkeypatch.setattr(
        "backend.services.agent_service.get_current_user_info",
        lambda authorization: ("user-x", "tenant-x", "en"),
        raising=False,
    )
    existing_agents = [
        {"agent_id": 7, "name": "self", "display_name": "Self Display"},
    ]
    monkeypatch.setattr(
        "backend.services.agent_service.query_all_agent_info_by_tenant_id",
        lambda tenant_id: existing_agents,
        raising=False,
    )

    request = AgentNameBatchCheckRequest(
        items=[
            AgentNameBatchCheckItem(
                agent_id=7, name="self", display_name="Self Display"
            )
        ]
    )

    result = await agent_service.check_agent_name_conflict_batch_impl(
        request, authorization="Bearer token"
    )

    assert result[0]["name_conflict"] is False
    assert result[0]["display_name_conflict"] is False
    assert result[0]["conflict_agents"] == []


@pytest.mark.asyncio
async def test_regenerate_agent_name_batch_impl_uses_llm(monkeypatch):
    monkeypatch.setattr(
        "backend.services.agent_service.get_current_user_info",
        lambda authorization: ("user-x", "tenant-x", "en"),
        raising=False,
    )
    monkeypatch.setattr(
        "backend.services.agent_service.query_all_agent_info_by_tenant_id",
        lambda tenant_id: [{"agent_id": 2, "name": "dup_name", "display_name": "Dup"}],
        raising=False,
    )
    monkeypatch.setattr(
        "backend.services.agent_service.tenant_config_manager.get_model_config",
        lambda key, tenant_id: {"model_id": "model-1", "display_name": "LLM"},
        raising=False,
    )

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread, raising=False)
    monkeypatch.setattr(
        "backend.services.agent_service._regenerate_agent_name_with_llm",
        lambda **kwargs: "regenerated_name",
        raising=False,
    )
    monkeypatch.setattr(
        "backend.services.agent_service._regenerate_agent_display_name_with_llm",
        lambda **kwargs: "Regenerated Display",
        raising=False,
    )



    request = AgentNameBatchRegenerateRequest(
        items=[
            AgentNameBatchRegenerateItem(
                agent_id=1,
                name="dup_name",
                display_name="Dup",
                task_description="desc",
            )
        ]
    )

    result = await agent_service.regenerate_agent_name_batch_impl(
        request, authorization="Bearer token"
    )

    assert result == [{"name": "regenerated_name", "display_name": "Regenerated Display"}]


@pytest.mark.asyncio
async def test_regenerate_agent_name_batch_impl_no_model(monkeypatch):
    monkeypatch.setattr(
        "backend.services.agent_service.get_current_user_info",
        lambda authorization: ("user-x", "tenant-x", "en"),
        raising=False,
    )
    monkeypatch.setattr(
        "backend.services.agent_service.query_all_agent_info_by_tenant_id",
        lambda tenant_id: [],
        raising=False,
    )
    monkeypatch.setattr(
        "backend.services.agent_service.tenant_config_manager.get_model_config",
        lambda key, tenant_id: None,
        raising=False,
    )

    from consts.model import AgentNameBatchRegenerateItem, AgentNameBatchRegenerateRequest

    request = AgentNameBatchRegenerateRequest(
        items=[AgentNameBatchRegenerateItem(agent_id=1, name="dup", display_name="Dup")]
    )

    with pytest.raises(ValueError):
        await agent_service.regenerate_agent_name_batch_impl(
            request, authorization="Bearer token"
        )


@pytest.mark.asyncio
async def test_regenerate_agent_name_batch_impl_llm_failure_fallback(monkeypatch):
    monkeypatch.setattr(
        "backend.services.agent_service.get_current_user_info",
        lambda authorization: ("user-x", "tenant-x", "en"),
        raising=False,
    )
    # existing agent ensures duplicate detection
    monkeypatch.setattr(
        "backend.services.agent_service.query_all_agent_info_by_tenant_id",
        lambda tenant_id: [{"agent_id": 2, "name": "dup", "display_name": "Dup"}],
        raising=False,
    )
    monkeypatch.setattr(
        "backend.services.agent_service.tenant_config_manager.get_model_config",
        lambda key, tenant_id: {"model_id": "model-1", "display_name": "LLM"},
        raising=False,
    )

    async def run_in_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", run_in_thread, raising=False)
    monkeypatch.setattr(
        "backend.services.agent_service._regenerate_agent_name_with_llm",
        lambda **kwargs: (_ for _ in ()).throw(Exception("llm-fail")),
        raising=False,
    )
    monkeypatch.setattr(
        "backend.services.agent_service._regenerate_agent_display_name_with_llm",
        lambda **kwargs: (_ for _ in ()).throw(Exception("llm-fail")),
        raising=False,
    )
    monkeypatch.setattr(
        "backend.services.agent_service._generate_unique_agent_name_with_suffix",
        lambda base_value, **kwargs: f"{base_value}_fallback",
        raising=False,
    )
    monkeypatch.setattr(
        "backend.services.agent_service._generate_unique_display_name_with_suffix",
        lambda base_value, **kwargs: f"{base_value}_fallback",
        raising=False,
    )

    request = AgentNameBatchRegenerateRequest(
        items=[
            AgentNameBatchRegenerateItem(
                agent_id=1,
                name="dup",
                display_name="Dup",
                task_description="desc",
            )
        ]
    )

    result = await agent_service.regenerate_agent_name_batch_impl(
        request, authorization="Bearer token"
    )

    assert result == [{"name": "dup_fallback", "display_name": "Dup_fallback"}]


# =====================================================================
# Tests for _resolve_model_with_fallback helper function
# =====================================================================


class TestResolveModelWithFallback:
    """Test suite for the _resolve_model_with_fallback helper function."""

    @pytest.mark.asyncio
    @patch('backend.services.agent_service.get_model_id_by_display_name')
    @patch('backend.services.agent_service.tenant_config_manager.get_model_config')
    async def test_resolve_model_success_found_in_tenant(
        self,
        mock_get_model_config,
        mock_get_model_id,
    ):
        """Test successful model resolution when model exists in tenant."""
        # Arrange
        mock_get_model_id.return_value = "resolved_model_123"

        # Import the function
        from backend.services.agent_service import _resolve_model_with_fallback

        # Act
        result = _resolve_model_with_fallback(
            model_display_name="GPT-4",
            exported_model_id="old_model_456",
            model_label="Model",
            tenant_id="tenant_001"
        )

        # Assert
        assert result == "resolved_model_123"
        mock_get_model_id.assert_called_once_with("GPT-4", "tenant_001")
        mock_get_model_config.assert_not_called()

    @pytest.mark.asyncio
    @patch('backend.services.agent_service.get_model_id_by_display_name')
    @patch('backend.services.agent_service.tenant_config_manager.get_model_config')
    async def test_resolve_model_fallback_to_quick_config(
        self,
        mock_get_model_config,
        mock_get_model_id,
    ):
        """Test fallback to quick config LLM model when model not found in tenant."""
        # Arrange
        mock_get_model_id.return_value = None  # Model not found in tenant
        mock_get_model_config.return_value = {
            "model_id": "quick_config_model_789",
            "display_name": "Default LLM Model"
        }

        from backend.services.agent_service import _resolve_model_with_fallback

        # Act
        result = _resolve_model_with_fallback(
            model_display_name="NonExistentModel",
            exported_model_id="exported_999",
            model_label="Model",
            tenant_id="tenant_002"
        )

        # Assert
        assert result == "quick_config_model_789"
        mock_get_model_id.assert_called_once_with("NonExistentModel", "tenant_002")
        mock_get_model_config.assert_called_once()

    @pytest.mark.asyncio
    @patch('backend.services.agent_service.get_model_id_by_display_name')
    @patch('backend.services.agent_service.tenant_config_manager.get_model_config')
    async def test_resolve_model_no_fallback_available(
        self,
        mock_get_model_config,
        mock_get_model_id,
    ):
        """Test when neither tenant model nor quick config model is available."""
        # Arrange
        mock_get_model_id.return_value = None
        mock_get_model_config.return_value = None  # No quick config model

        from backend.services.agent_service import _resolve_model_with_fallback

        # Act
        result = _resolve_model_with_fallback(
            model_display_name="NonExistentModel",
            exported_model_id="exported_999",
            model_label="Model",
            tenant_id="tenant_003"
        )

        # Assert
        assert result is None
        mock_get_model_id.assert_called_once_with("NonExistentModel", "tenant_003")
        mock_get_model_config.assert_called_once()

    @pytest.mark.asyncio
    @patch('backend.services.agent_service.get_model_id_by_display_name')
    @patch('backend.services.agent_service.tenant_config_manager.get_model_config')
    async def test_resolve_model_none_model_name(
        self,
        mock_get_model_config,
        mock_get_model_id,
    ):
        """Test when model_name is None."""
        # Arrange
        from backend.services.agent_service import _resolve_model_with_fallback

        # Act
        result = _resolve_model_with_fallback(
            model_display_name=None,
            exported_model_id="exported_123",
            model_label="Model",
            tenant_id="tenant_004"
        )

        # Assert
        assert result is None
        mock_get_model_id.assert_not_called()
        mock_get_model_config.assert_not_called()

    @pytest.mark.asyncio
    @patch('backend.services.agent_service.get_model_id_by_display_name')
    @patch('backend.services.agent_service.tenant_config_manager.get_model_config')
    async def test_resolve_model_empty_model_name(
        self,
        mock_get_model_config,
        mock_get_model_id,
    ):
        """Test when model_name is an empty string."""
        # Arrange
        from backend.services.agent_service import _resolve_model_with_fallback

        # Act
        result = _resolve_model_with_fallback(
            model_display_name="",
            exported_model_id="exported_456",
            model_label="Model",
            tenant_id="tenant_005"
        )

        # Assert
        assert result is None
        mock_get_model_id.assert_not_called()
        mock_get_model_config.assert_not_called()

    @pytest.mark.asyncio
    @patch('backend.services.agent_service.get_model_id_by_display_name')
    @patch('backend.services.agent_service.tenant_config_manager.get_model_config')
    async def test_resolve_business_logic_model_success(
        self,
        mock_get_model_config,
        mock_get_model_id,
    ):
        """Test successful resolution of business logic model."""
        # Arrange
        mock_get_model_id.return_value = "business_model_555"

        from backend.services.agent_service import _resolve_model_with_fallback

        # Act
        result = _resolve_model_with_fallback(
            model_display_name="Qwen/QwQ-32B",
            exported_model_id="old_business_model_777",
            model_label="Business logic model",
            tenant_id="tenant_006"
        )

        # Assert
        assert result == "business_model_555"
        mock_get_model_id.assert_called_once_with("Qwen/QwQ-32B", "tenant_006")
        mock_get_model_config.assert_not_called()

    @pytest.mark.asyncio
    @patch('backend.services.agent_service.get_model_id_by_display_name')
    @patch('backend.services.agent_service.tenant_config_manager.get_model_config')
    async def test_resolve_model_quick_config_no_model_id(
        self,
        mock_get_model_config,
        mock_get_model_id,
    ):
        """Test when quick config exists but has no model_id."""
        # Arrange
        mock_get_model_id.return_value = None
        mock_get_model_config.return_value = {
            "display_name": "Default Model",
            # No model_id field
        }

        from backend.services.agent_service import _resolve_model_with_fallback

        # Act
        result = _resolve_model_with_fallback(
            model_display_name="SomeModel",
            exported_model_id="exported_888",
            model_label="Model",
            tenant_id="tenant_007"
        )

        # Assert
        assert result is None  # Should return None when model_id is missing
        mock_get_model_id.assert_called_once_with("SomeModel", "tenant_007")
        mock_get_model_config.assert_called_once()

    @pytest.mark.asyncio
    @patch('backend.services.agent_service.get_model_id_by_display_name')
    @patch('backend.services.agent_service.tenant_config_manager.get_model_config')
    async def test_resolve_model_with_various_labels(
        self,
        mock_get_model_config,
        mock_get_model_id,
    ):
        """Test that different model_labels are handled correctly."""
        # Arrange
        mock_get_model_id.return_value = "model_111"

        from backend.services.agent_service import _resolve_model_with_fallback

        # Act & Assert - Test with "Model" label
        result1 = _resolve_model_with_fallback(
            model_display_name="TestModel",
            exported_model_id="exp_1",
            model_label="Model",
            tenant_id="tenant_008"
        )
        assert result1 == "model_111"

        # Reset mock
        mock_get_model_id.reset_mock()
        mock_get_model_id.return_value = "model_222"

        # Act & Assert - Test with "Business logic model" label
        result2 = _resolve_model_with_fallback(
            model_display_name="TestModel2",
            exported_model_id="exp_2",
            model_label="Business logic model",
            tenant_id="tenant_009"
        )
        assert result2 == "model_222"

    @pytest.mark.asyncio
    @patch('backend.services.agent_service.get_model_id_by_display_name')
    @patch('backend.services.agent_service.tenant_config_manager.get_model_config')
    async def test_resolve_model_exception_handling(
        self,
        mock_get_model_config,
        mock_get_model_id,
    ):
        """Test that exceptions from database calls are propagated."""
        # Arrange
        mock_get_model_id.side_effect = Exception("Database connection error")

        from backend.services.agent_service import _resolve_model_with_fallback

        # Act & Assert
        with pytest.raises(Exception, match="Database connection error"):
            _resolve_model_with_fallback(
                model_display_name="TestModel",
                exported_model_id="exp_3",
                model_label="Model",
                tenant_id="tenant_010"
            )

        mock_get_model_config.assert_not_called()

    @pytest.mark.asyncio
    @patch('backend.services.agent_service.get_model_id_by_display_name')
    @patch('backend.services.agent_service.tenant_config_manager.get_model_config')
    async def test_resolve_model_quick_config_exception(
        self,
        mock_get_model_config,
        mock_get_model_id,
    ):
        """Test when quick config retrieval raises an exception."""
        # Arrange
        mock_get_model_id.return_value = None
        mock_get_model_config.side_effect = Exception("Config service error")

        from backend.services.agent_service import _resolve_model_with_fallback

        # Act & Assert
        with pytest.raises(Exception, match="Config service error"):
            _resolve_model_with_fallback(
                model_display_name="TestModel",
                exported_model_id="exp_4",
                model_label="Model",
                tenant_id="tenant_011"
            )


def test_check_single_model_availability_no_model_id():
    reasons = _check_single_model_availability(
        model_id=None,
        tenant_id="tenant",
        model_cache={},
        reason_key="model_unavailable",
    )
    assert reasons == []


@patch("backend.services.agent_service.get_model_by_model_id")
def test_check_single_model_availability_fetches_and_handles_missing_model(mock_get_model):
    model_cache = {}
    mock_get_model.return_value = None

    reasons = _check_single_model_availability(
        model_id=123,
        tenant_id="tenant",
        model_cache=model_cache,
        reason_key="model_unavailable",
    )

    assert reasons == ["model_unavailable"]
    assert 123 in model_cache
    mock_get_model.assert_called_once_with(123, "tenant")


def test_check_single_model_availability_uses_cached_unavailable_model():
    model_cache = {
        456: {"connect_status": agent_service.ModelConnectStatusEnum.UNAVAILABLE.value}
    }

    reasons = _check_single_model_availability(
        model_id=456,
        tenant_id="tenant",
        model_cache=model_cache,
        reason_key="model_unavailable",
    )

    assert reasons == ["model_unavailable"]


def test_check_single_model_availability_returns_empty_for_available_model():
    model_cache = {
        789: {"connect_status": agent_service.ModelConnectStatusEnum.AVAILABLE.value}
    }

    reasons = _check_single_model_availability(
        model_id=789,
        tenant_id="tenant",
        model_cache=model_cache,
        reason_key="model_unavailable",
    )

    assert reasons == []


# ============================================================================
# Tests for check_agent_availability function
# ============================================================================


@patch('backend.services.agent_service._collect_model_availability_reasons')
@patch('backend.services.agent_service.check_tool_is_available')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
def test_check_agent_availability_all_available(
    mock_search_agent_info,
    mock_search_tools,
    mock_check_tool,
    mock_collect_model_reasons
):
    """Test check_agent_availability when all tools and models are available."""
    from backend.services.agent_service import check_agent_availability

    mock_agent_info = {"agent_id": 123, "model_id": 456}
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = [{"tool_id": 1}, {"tool_id": 2}]
    mock_check_tool.return_value = [True, True]
    mock_collect_model_reasons.return_value = []

    is_available, reasons = check_agent_availability(
        agent_id=123,
        tenant_id="test_tenant"
    )

    assert is_available is True
    assert reasons == []
    mock_search_agent_info.assert_called_once_with(123, "test_tenant")
    mock_search_tools.assert_called_once_with(agent_id=123, tenant_id="test_tenant")
    mock_check_tool.assert_called_once_with([1, 2])


@patch('backend.services.agent_service._collect_model_availability_reasons')
@patch('backend.services.agent_service.check_tool_is_available')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
def test_check_agent_availability_tool_unavailable(
    mock_search_agent_info,
    mock_search_tools,
    mock_check_tool,
    mock_collect_model_reasons
):
    """Test check_agent_availability when some tools are unavailable."""
    from backend.services.agent_service import check_agent_availability

    mock_agent_info = {"agent_id": 123, "model_id": 456}
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = [{"tool_id": 1}, {"tool_id": 2}]
    mock_check_tool.return_value = [True, False]  # One tool unavailable
    mock_collect_model_reasons.return_value = []

    is_available, reasons = check_agent_availability(
        agent_id=123,
        tenant_id="test_tenant"
    )

    assert is_available is False
    assert reasons == ["tool_unavailable"]


@patch('backend.services.agent_service._collect_model_availability_reasons')
@patch('backend.services.agent_service.check_tool_is_available')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
def test_check_agent_availability_model_unavailable(
    mock_search_agent_info,
    mock_search_tools,
    mock_check_tool,
    mock_collect_model_reasons
):
    """Test check_agent_availability when model is unavailable."""
    from backend.services.agent_service import check_agent_availability

    mock_agent_info = {"agent_id": 123, "model_id": 456}
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = [{"tool_id": 1}]
    mock_check_tool.return_value = [True]
    mock_collect_model_reasons.return_value = ["model_unavailable"]

    is_available, reasons = check_agent_availability(
        agent_id=123,
        tenant_id="test_tenant"
    )

    assert is_available is False
    assert reasons == ["model_unavailable"]


@patch('backend.services.agent_service._collect_model_availability_reasons')
@patch('backend.services.agent_service.check_tool_is_available')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
def test_check_agent_availability_both_unavailable(
    mock_search_agent_info,
    mock_search_tools,
    mock_check_tool,
    mock_collect_model_reasons
):
    """Test check_agent_availability when both tools and model are unavailable."""
    from backend.services.agent_service import check_agent_availability

    mock_agent_info = {"agent_id": 123, "model_id": 456}
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = [{"tool_id": 1}]
    mock_check_tool.return_value = [False]
    mock_collect_model_reasons.return_value = ["model_unavailable"]

    is_available, reasons = check_agent_availability(
        agent_id=123,
        tenant_id="test_tenant"
    )

    assert is_available is False
    assert "tool_unavailable" in reasons
    assert "model_unavailable" in reasons


@patch('backend.services.agent_service._collect_model_availability_reasons')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
def test_check_agent_availability_no_tools(
    mock_search_agent_info,
    mock_search_tools,
    mock_collect_model_reasons
):
    """Test check_agent_availability when agent has no tools."""
    from backend.services.agent_service import check_agent_availability

    mock_agent_info = {"agent_id": 123, "model_id": 456}
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = []  # No tools
    mock_collect_model_reasons.return_value = []

    is_available, reasons = check_agent_availability(
        agent_id=123,
        tenant_id="test_tenant"
    )

    assert is_available is True
    assert reasons == []


@patch('backend.services.agent_service.search_agent_info_by_agent_id')
def test_check_agent_availability_agent_not_found(mock_search_agent_info):
    """Test check_agent_availability when agent is not found."""
    from backend.services.agent_service import check_agent_availability

    mock_search_agent_info.return_value = None

    is_available, reasons = check_agent_availability(
        agent_id=999,
        tenant_id="test_tenant"
    )

    assert is_available is False
    assert reasons == ["agent_not_found"]


@patch('backend.services.agent_service._collect_model_availability_reasons')
@patch('backend.services.agent_service.check_tool_is_available')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
def test_check_agent_availability_with_pre_fetched_agent_info(
    mock_search_tools,
    mock_check_tool,
    mock_collect_model_reasons
):
    """Test check_agent_availability with pre-fetched agent_info (avoids duplicate DB query)."""
    from backend.services.agent_service import check_agent_availability

    pre_fetched_agent_info = {"agent_id": 123, "model_id": 456}
    mock_search_tools.return_value = [{"tool_id": 1}]
    mock_check_tool.return_value = [True]
    mock_collect_model_reasons.return_value = []

    is_available, reasons = check_agent_availability(
        agent_id=123,
        tenant_id="test_tenant",
        agent_info=pre_fetched_agent_info
    )

    assert is_available is True
    assert reasons == []
    # search_agent_info_by_agent_id should NOT be called since agent_info was provided
    mock_search_tools.assert_called_once_with(agent_id=123, tenant_id="test_tenant")


@patch('backend.services.agent_service._collect_model_availability_reasons')
@patch('backend.services.agent_service.check_tool_is_available')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
def test_check_agent_availability_with_model_cache(
    mock_search_tools,
    mock_check_tool,
    mock_collect_model_reasons
):
    """Test check_agent_availability with pre-populated model cache."""
    from backend.services.agent_service import check_agent_availability

    pre_fetched_agent_info = {"agent_id": 123, "model_id": 456}
    model_cache = {456: {"connect_status": "available"}}
    mock_search_tools.return_value = [{"tool_id": 1}]
    mock_check_tool.return_value = [True]
    mock_collect_model_reasons.return_value = []

    is_available, reasons = check_agent_availability(
        agent_id=123,
        tenant_id="test_tenant",
        agent_info=pre_fetched_agent_info,
        model_cache=model_cache
    )

    assert is_available is True
    assert reasons == []
    # Verify model_cache was passed to _collect_model_availability_reasons
    mock_collect_model_reasons.assert_called_once()
    call_args = mock_collect_model_reasons.call_args
    assert call_args.kwargs.get("model_cache") == model_cache or call_args[1].get("model_cache") == model_cache


@pytest.mark.asyncio
@patch('backend.services.agent_service.check_agent_availability')
@patch('backend.services.agent_service.get_model_by_model_id')
@patch('backend.services.agent_service.query_sub_agents_id_list')
@patch('backend.services.agent_service.search_tools_for_sub_agent')
@patch('backend.services.agent_service.search_agent_info_by_agent_id')
async def test_get_agent_info_impl_with_unavailable_agent(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability
):
    """Test get_agent_info_impl returns is_available=False when agent is unavailable."""
    mock_agent_info = {
        "agent_id": 123,
        "model_id": 456,
        "business_description": "Test agent"
    }
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = [{"tool_id": 1}]
    mock_query_sub_agents_id.return_value = []
    mock_get_model_by_model_id.return_value = {"display_name": "GPT-4"}
    # Agent is unavailable due to tool issues
    mock_check_availability.return_value = (False, ["tool_unavailable"])

    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert result["is_available"] is False
    assert result["unavailable_reasons"] == ["tool_unavailable"]


@pytest.mark.asyncio
@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@patch('backend.services.agent_service._resolve_model_with_fallback')
async def test_import_agent_by_agent_id_allows_duplicate_name_without_regen(
    mock_resolve_model,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool
):
    """
    New behavior: import_agent_by_agent_id no longer performs duplicate-name regeneration.
    It should create the agent with the provided name/display_name even if duplicates exist.
    """
    mock_query_all_tools.return_value = []
    mock_resolve_model.side_effect = [1, 2]
    mock_create_agent.return_value = {"agent_id": 456}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="duplicate_name",
        display_name="Test Display",
        description="Test",
        business_description="Test business",
        max_steps=5,
        provide_run_summary=True,
        duty_prompt="",
        constraint_prompt="",
        few_shots_prompt="",
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=1,
        model_name="Model1",
        business_logic_model_id=2,
        business_logic_model_name="Model2"
    )

    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        skip_duplicate_regeneration=False
    )

    assert result == 456
    mock_create_agent.assert_called_once()
    assert mock_create_agent.call_args[1]["agent_info"]["name"] == "duplicate_name"
    assert mock_create_agent.call_args[1]["agent_info"]["display_name"] == "Test Display"


@pytest.mark.asyncio
@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@patch('backend.services.agent_service._resolve_model_with_fallback')
async def test_import_agent_by_agent_id_duplicate_name_no_regen_fallback(
    mock_resolve_model,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool
):
    """
    New behavior: even when duplicate name, import proceeds without regeneration or fallback.
    """
    mock_query_all_tools.return_value = []
    mock_resolve_model.side_effect = [1, 2]
    mock_create_agent.return_value = {"agent_id": 456}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="duplicate_name",
        display_name="Test Display",
        description="Test",
        business_description="Test business",
        max_steps=5,
        provide_run_summary=True,
        duty_prompt="",
        constraint_prompt="",
        few_shots_prompt="",
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=1,
        model_name="Model1",
        business_logic_model_id=2,
        business_logic_model_name="Model2"
    )

    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        skip_duplicate_regeneration=False
    )

    assert result == 456
    mock_create_agent.assert_called_once()
    assert mock_create_agent.call_args[1]["agent_info"]["name"] == "duplicate_name"


@pytest.mark.asyncio
@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@patch('backend.services.agent_service._resolve_model_with_fallback')
async def test_import_agent_by_agent_id_duplicate_name_no_model_still_allows(
    mock_resolve_model,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool
):
    """
    New behavior: even without model, duplicate name passes through unchanged.
    """
    mock_query_all_tools.return_value = []
    mock_resolve_model.side_effect = [None, None]
    mock_create_agent.return_value = {"agent_id": 456}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="duplicate_name",
        display_name="Test Display",
        description="Test",
        business_description="Test business",
        max_steps=5,
        provide_run_summary=True,
        duty_prompt="",
        constraint_prompt="",
        few_shots_prompt="",
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=None,
        model_name=None,
        business_logic_model_id=None,
        business_logic_model_name=None
    )

    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        skip_duplicate_regeneration=False
    )

    assert result == 456
    mock_create_agent.assert_called_once()
    assert mock_create_agent.call_args[1]["agent_info"]["name"] == "duplicate_name"


@pytest.mark.asyncio
@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@patch('backend.services.agent_service._resolve_model_with_fallback')
async def test_import_agent_by_agent_id_duplicate_display_name_allowed(
    mock_resolve_model,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool
):
    """New behavior: duplicate display_name passes through without regeneration."""
    mock_query_all_tools.return_value = []
    mock_resolve_model.side_effect = [1, 2]
    mock_create_agent.return_value = {"agent_id": 456}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="unique_name",
        display_name="duplicate_display",
        description="Test",
        business_description="Test business",
        max_steps=5,
        provide_run_summary=True,
        duty_prompt="",
        constraint_prompt="",
        few_shots_prompt="",
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=1,
        model_name="Model1",
        business_logic_model_id=2,
        business_logic_model_name="Model2"
    )

    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        skip_duplicate_regeneration=False
    )

    assert result == 456
    mock_create_agent.assert_called_once()
    assert mock_create_agent.call_args[1]["agent_info"]["display_name"] == "duplicate_display"


@pytest.mark.asyncio
@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@patch('backend.services.agent_service._resolve_model_with_fallback')
async def test_import_agent_by_agent_id_duplicate_display_name_no_llm_fallback(
    mock_resolve_model,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool
):
    """
    New behavior: duplicate display_name passes through without LLM; fallback not invoked.
    """
    mock_query_all_tools.return_value = []
    mock_resolve_model.side_effect = [1, 2]
    mock_create_agent.return_value = {"agent_id": 456}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="unique_name",
        display_name="duplicate_display",
        description="Test",
        business_description="Test business",
        max_steps=5,
        provide_run_summary=True,
        duty_prompt="",
        constraint_prompt="",
        few_shots_prompt="",
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=1,
        model_name="Model1",
        business_logic_model_id=2,
        business_logic_model_name="Model2"
    )

    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        skip_duplicate_regeneration=False
    )

    assert result == 456
    mock_create_agent.assert_called_once()
    assert mock_create_agent.call_args[1]["agent_info"]["display_name"] == "duplicate_display"


@pytest.mark.asyncio
@patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
@patch('backend.services.agent_service.create_agent')
@patch('backend.services.agent_service.query_all_tools')
@patch('backend.services.agent_service._resolve_model_with_fallback')
async def test_import_agent_by_agent_id_duplicate_display_name_no_model_still_allowed(
    mock_resolve_model,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool
):
    """
    New behavior: even without model, duplicate display_name passes through unchanged.
    """
    mock_query_all_tools.return_value = []
    mock_resolve_model.side_effect = [None, None]
    mock_create_agent.return_value = {"agent_id": 456}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="unique_name",
        display_name="duplicate_display",
        description="Test",
        business_description="Test business",
        max_steps=5,
        provide_run_summary=True,
        duty_prompt="",
        constraint_prompt="",
        few_shots_prompt="",
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=None,
        model_name=None,
        business_logic_model_id=None,
        business_logic_model_name=None
    )

    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        skip_duplicate_regeneration=False
    )

    assert result == 456
    mock_create_agent.assert_called_once()
    assert mock_create_agent.call_args[1]["agent_info"]["display_name"] == "duplicate_display"


@pytest.mark.asyncio
async def test_clear_agent_new_mark_impl_success():
    """
    Test successful clearing of agent NEW mark through service layer.

    This test verifies that:
    1. The function correctly calls the database helper
    2. Returns the correct row count
    3. Logs the operation with correct parameters
    """
    # Setup
    mock_module = MagicMock()
    mock_module.clear_agent_new_mark.return_value = 1
    with patch('backend.services.agent_service.clear_agent_new_mark', new=mock_module.clear_agent_new_mark), \
         patch('backend.services.agent_service.logger') as mock_logger:

        # Execute
        result = await clear_agent_new_mark_impl(
            agent_id=123,
            tenant_id="test_tenant",
            user_id="test_user"
        )

        # Assert
        assert result == 1
        mock_module.clear_agent_new_mark.assert_called_once_with(123, "test_tenant", "test_user")
        mock_logger.info.assert_called_once_with(
            "clear_agent_new_mark_impl called for agent_id=123, tenant_id=test_tenant, user_id=test_user, affected_rows=1"
        )


@pytest.mark.asyncio
async def test_clear_agent_new_mark_impl_no_rows_affected():
    """
    Test clearing agent NEW mark when no rows are affected.

    This test verifies that:
    1. The function handles zero affected rows correctly
    2. Still logs the operation appropriately
    """
    # Setup
    mock_module = MagicMock()
    mock_module.clear_agent_new_mark.return_value = 0
    with patch('backend.services.agent_service.clear_agent_new_mark', new=mock_module.clear_agent_new_mark), \
         patch('backend.services.agent_service.logger') as mock_logger:

        # Execute
        result = await clear_agent_new_mark_impl(
            agent_id=999,
            tenant_id="test_tenant",
            user_id="test_user"
        )

        # Assert
        assert result == 0
        mock_module.clear_agent_new_mark.assert_called_once_with(999, "test_tenant", "test_user")
        mock_logger.info.assert_called_once_with(
            "clear_agent_new_mark_impl called for agent_id=999, tenant_id=test_tenant, user_id=test_user, affected_rows=0"
        )


@pytest.mark.asyncio
async def test_clear_agent_new_mark_impl_multiple_rows_affected():
    """
    Test clearing agent NEW mark when multiple rows are affected.

    This test verifies that:
    1. The function handles multiple affected rows correctly
    2. Logs the correct count
    """
    # Setup
    mock_module = MagicMock()
    mock_module.clear_agent_new_mark.return_value = 3
    with patch('backend.services.agent_service.clear_agent_new_mark', new=mock_module.clear_agent_new_mark), \
         patch('backend.services.agent_service.logger') as mock_logger:

        # Execute
        result = await clear_agent_new_mark_impl(
            agent_id=456,
            tenant_id="another_tenant",
            user_id="another_user"
        )

        # Assert
        assert result == 3
        mock_module.clear_agent_new_mark.assert_called_once_with(456, "another_tenant", "another_user")
        mock_logger.info.assert_called_once_with(
            "clear_agent_new_mark_impl called for agent_id=456, tenant_id=another_tenant, user_id=another_user, affected_rows=3"
        )


@pytest.mark.asyncio
async def test_clear_agent_new_mark_impl_database_error():
    """
    Test clear_agent_new_mark_impl when database operation fails.

    This test verifies that:
    1. The function propagates database errors
    2. Does not log success when operation fails
    """
    # Setup
    mock_module = MagicMock()
    mock_module.clear_agent_new_mark.side_effect = Exception("Database connection failed")
    with patch('backend.services.agent_service.clear_agent_new_mark', new=mock_module.clear_agent_new_mark), \
         patch('backend.services.agent_service.logger') as mock_logger:

        # Execute and Assert
        with pytest.raises(Exception, match="Database connection failed"):
            await clear_agent_new_mark_impl(
                agent_id=123,
                tenant_id="test_tenant",
                user_id="test_user"
            )

        mock_module.clear_agent_new_mark.assert_called_once_with(123, "test_tenant", "test_user")
        mock_logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_clear_agent_new_mark_impl_with_special_characters():
    """
    Test clear_agent_new_mark_impl with special characters in parameters.

    This test verifies that:
    1. The function handles special characters in tenant_id and user_id
    2. Properly passes through all parameters
    """
    # Setup
    mock_module = MagicMock()
    mock_module.clear_agent_new_mark.return_value = 1
    with patch('backend.services.agent_service.clear_agent_new_mark', new=mock_module.clear_agent_new_mark), \
         patch('backend.services.agent_service.logger') as mock_logger:

        # Execute
        result = await clear_agent_new_mark_impl(
            agent_id=789,
            tenant_id="tenant-with-dashes_and_underscores",
            user_id="user@domain.com"
        )

        # Assert
        assert result == 1
        mock_module.clear_agent_new_mark.assert_called_once_with(789, "tenant-with-dashes_and_underscores", "user@domain.com")
        mock_logger.info.assert_called_once_with(
            "clear_agent_new_mark_impl called for agent_id=789, tenant_id=tenant-with-dashes_and_underscores, user_id=user@domain.com, affected_rows=1"
        )

# Deprecated tests for mark_agents_as_new_impl have been removed as the API is cleaned up.
