import unittest
from unittest.mock import patch, MagicMock, mock_open, call

# Mock boto3 and minio client before importing the module under test
import sys
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Mock MinioClient class before importing the services
minio_client_mock = MagicMock()
with patch('backend.database.client.MinioClient', return_value=minio_client_mock):
    from backend.services.agent_service import (
        get_enable_tool_id_by_agent_id,
        get_enable_sub_agent_id_by_agent_id,
        get_creating_sub_agent_id_service,
        query_sub_agents_api,
        list_main_agent_info_impl,
        get_agent_info_impl,
        get_creating_sub_agent_info_impl,
        update_agent_info_impl,
        delete_agent_impl,
        export_agent_impl,
        import_agent_impl,
        search_sub_agents,
        load_default_agents_json_file,
        import_default_agents_to_pg
    )
    from backend.consts.model import AgentInfoRequest, ExportAndImportAgentInfo, ToolInstanceInfoRequest


class TestAgentService(unittest.TestCase):
    """Test suite for the agent service module which handles agent-related operations."""

    def setUp(self):
        """Reset all mocks before each test to ensure a clean test environment."""
        minio_client_mock.reset_mock()

    def test_get_enable_tool_id_by_agent_id(self):
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
            self.assertEqual(sorted(result), [1, 3, 4])
            mock_query.assert_called_once_with(
                tenant_id="test_tenant", 
                agent_id=123
            )

    def test_get_enable_sub_agent_id_by_agent_id(self):
        """
        Test the function that retrieves enabled sub-agent IDs for a specific agent.
        
        This test verifies that:
        1. The function correctly filters and returns only enabled sub-agent IDs
        2. The underlying query function is called with correct parameters
        """
        # Setup
        mock_sub_agents = [
            {"agent_id": 101, "enabled": True},
            {"agent_id": 102, "enabled": False},
            {"agent_id": 103, "enabled": True}
        ]
        
        with patch('backend.services.agent_service.query_sub_agents') as mock_query:
            mock_query.return_value = mock_sub_agents
            
            # Execute
            result = get_enable_sub_agent_id_by_agent_id(
                agent_id=123, 
                tenant_id="test_tenant", 
                user_id="test_user"
            )
            
            # Assert
            self.assertEqual(sorted(result), [101, 103])
            mock_query.assert_called_once_with(
                main_agent_id=123, 
                tenant_id="test_tenant", 
                user_id="test_user"
            )

    @patch('backend.services.agent_service.create_agent')
    @patch('backend.services.agent_service.search_sub_agent_by_main_agent_id')
    def test_get_creating_sub_agent_id_service_existing_agent(self, mock_search, mock_create):
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
            main_agent_id=123, 
            tenant_id="test_tenant", 
            user_id="test_user"
        )
        
        # Assert
        self.assertEqual(result, 456)
        mock_search.assert_called_once_with(123, "test_tenant")
        mock_create.assert_not_called()

    @patch('backend.services.agent_service.create_agent')
    @patch('backend.services.agent_service.search_sub_agent_by_main_agent_id')
    def test_get_creating_sub_agent_id_service_new_agent(self, mock_search, mock_create):
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
            main_agent_id=123, 
            tenant_id="test_tenant", 
            user_id="test_user"
        )
        
        # Assert
        self.assertEqual(result, 789)
        mock_search.assert_called_once_with(123, "test_tenant")
        mock_create.assert_called_once_with(
            agent_info={"enabled": False, "parent_agent_id": 123},
            tenant_id="test_tenant",
            user_id="test_user"
        )

    @patch('backend.services.agent_service.check_tool_is_available')
    @patch('backend.services.agent_service.search_tools_for_sub_agent')
    @patch('backend.services.agent_service.query_sub_agents')
    def test_query_sub_agents_api(self, mock_query_sub_agents, mock_search_tools, mock_check_tool_is_available):
        """
        Test the API that queries sub-agents with their associated tools.
        
        This test verifies that:
        1. The function correctly retrieves sub-agents
        2. For each sub-agent, it fetches the associated tools
        3. It checks if the tools are available
        4. The returned structure contains all expected information
        """
        # Setup
        mock_sub_agents = [
            {"agent_id": 101, "name": "Agent 1"},
            {"agent_id": 102, "name": "Agent 2"}
        ]
        mock_query_sub_agents.return_value = mock_sub_agents
        
        mock_search_tools.side_effect = [
            [{"tool_id": 1, "name": "Tool 1"}],
            [{"tool_id": 2, "name": "Tool 2"}]
        ]
        
        # Set up the mock to return a list of True values
        mock_check_tool_is_available.return_value = [True, True]  # All tools are available
        
        # Execute
        result = query_sub_agents_api(
            main_agent_id=123, 
            tenant_id="test_tenant", 
            user_id="test_user"
        )
        
        # Assert
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["tools"], [{"tool_id": 1, "name": "Tool 1"}])
        self.assertEqual(result[1]["tools"], [{"tool_id": 2, "name": "Tool 2"}])
        self.assertEqual(result[0]["is_available"], True)
        self.assertEqual(result[1]["is_available"], True)
        
        mock_query_sub_agents.assert_called_once_with(123, "test_tenant", "test_user")
        self.assertEqual(mock_search_tools.call_count, 2)

    @patch('backend.services.agent_service.get_enable_sub_agent_id_by_agent_id')
    @patch('backend.services.agent_service.get_enable_tool_id_by_agent_id')
    @patch('backend.services.agent_service.query_sub_agents_api')
    @patch('backend.services.agent_service.search_agent_info_by_agent_id')
    @patch('backend.services.agent_service.query_or_create_main_agent_id')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_list_main_agent_info_impl_success(self, mock_get_current_user_id, mock_query_main_agent,
                                              mock_search_agent_info, mock_query_sub_agents,
                                              mock_get_enable_tools, mock_get_enable_agents):
        """
        Test successful retrieval of main agent information.
        
        This test verifies that:
        1. The function correctly gets the current user and tenant IDs
        2. It retrieves or creates the main agent ID
        3. It fetches the agent's information, sub-agents, and enabled tools
        4. It returns a complete data structure with all required information
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        mock_query_main_agent.return_value = 123
        mock_search_agent_info.return_value = {
            "model_name": "gpt-4",
            "max_steps": 10,
            "business_description": "Test agent",
            "prompt": "Test prompt"
        }
        mock_query_sub_agents.return_value = [{"agent_id": 456, "name": "Sub Agent"}]
        mock_get_enable_tools.return_value = [1, 2, 3]
        mock_get_enable_agents.return_value = [456]
        
        # Execute
        result = list_main_agent_info_impl()
        
        # Assert
        expected_result = {
            "main_agent_id": 123,
            "sub_agent_list": [{"agent_id": 456, "name": "Sub Agent"}],
            "enable_tool_id_list": [1, 2, 3],
            "enable_agent_id_list": [456],
            "model_name": "gpt-4",
            "max_steps": 10,
            "business_description": "Test agent",
            "prompt": "Test prompt"
        }
        self.assertEqual(result, expected_result)

    @patch('backend.services.agent_service.search_agent_info_by_agent_id')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_get_agent_info_impl_success(self, mock_get_current_user_id, mock_search_agent_info):
        """
        Test successful retrieval of an agent's information by ID.
        
        This test verifies that:
        1. The function correctly gets the current user and tenant IDs
        2. It retrieves the agent's information using the correct IDs
        3. It returns the agent information directly
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        mock_agent_info = {
            "agent_id": 123,
            "model_name": "gpt-4",
            "business_description": "Test agent"
        }
        mock_search_agent_info.return_value = mock_agent_info
        
        # Execute
        result = get_agent_info_impl(123)
        
        # Assert
        self.assertEqual(result, mock_agent_info)
        mock_search_agent_info.assert_called_once_with(123, "test_tenant", "test_user")

    @patch('backend.services.agent_service.get_enable_tool_id_by_agent_id')
    @patch('backend.services.agent_service.search_agent_info_by_agent_id')
    @patch('backend.services.agent_service.get_creating_sub_agent_id_service')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_get_creating_sub_agent_info_impl_success(self, mock_get_current_user_id, mock_get_creating_sub_agent,
                                                     mock_search_agent_info, mock_get_enable_tools):
        """
        Test successful retrieval of creating sub-agent information.
        
        This test verifies that:
        1. The function correctly gets the current user and tenant IDs
        2. It retrieves or creates the sub-agent ID for the main agent
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
            "prompt": "Sub prompt"
        }
        mock_get_enable_tools.return_value = [1, 2]
        
        # Execute
        result = get_creating_sub_agent_info_impl(123)
        
        # Assert
        expected_result = {
            "agent_id": 456,
            "enable_tool_id_list": [1, 2],
            "model_name": "gpt-4",
            "max_steps": 5,
            "business_description": "Sub agent",
            "prompt": "Sub prompt"
        }
        self.assertEqual(result, expected_result)

    @patch('backend.services.agent_service.update_agent')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_update_agent_info_impl_success(self, mock_get_current_user_id, mock_update_agent):
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
            business_description="Updated agent"
        )
        
        # Execute
        update_agent_info_impl(request)
        
        # Assert
        mock_update_agent.assert_called_once_with(123, request, "test_tenant", "test_user")

    @patch('backend.services.agent_service.delete_agent_by_id')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_delete_agent_impl_success(self, mock_get_current_user_id, mock_delete_agent):
        """
        Test successful deletion of an agent.
        
        This test verifies that:
        1. The function correctly gets the current user and tenant IDs
        2. It calls the delete_agent_by_id function with the correct parameters
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        
        # Execute
        delete_agent_impl(123)
        
        # Assert
        mock_delete_agent.assert_called_once_with(123, "test_tenant", "test_user")

    @patch('backend.services.agent_service.query_or_create_main_agent_id')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_list_main_agent_info_impl_exception_handling(self, mock_get_current_user_id, mock_query_main_agent):
        """
        Test exception handling in list_main_agent_info_impl function.
        
        This test verifies that:
        1. When an exception occurs during main agent ID retrieval
        2. The function raises a ValueError with an appropriate message
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        mock_query_main_agent.side_effect = Exception("Database error")
        
        # Execute & Assert
        with self.assertRaises(ValueError) as context:
            list_main_agent_info_impl()
        
        self.assertIn("Failed to get main agent id", str(context.exception))

    @patch('backend.services.agent_service.search_agent_info_by_agent_id')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_get_agent_info_impl_exception_handling(self, mock_get_current_user_id, mock_search_agent_info):
        """
        Test exception handling in get_agent_info_impl function.
        
        This test verifies that:
        1. When an exception occurs during agent info retrieval
        2. The function raises a ValueError with an appropriate message
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        mock_search_agent_info.side_effect = Exception("Database error")
        
        # Execute & Assert
        with self.assertRaises(ValueError) as context:
            get_agent_info_impl(123)
        
        self.assertIn("Failed to get agent info", str(context.exception))

    @patch('backend.services.agent_service.update_agent')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_update_agent_info_impl_exception_handling(self, mock_get_current_user_id, mock_update_agent):
        """
        Test exception handling in update_agent_info_impl function.
        
        This test verifies that:
        1. When an exception occurs during agent info update
        2. The function raises a ValueError with an appropriate message
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        mock_update_agent.side_effect = Exception("Update failed")
        request = AgentInfoRequest(agent_id=123, model_name="gpt-4")
        
        # Execute & Assert
        with self.assertRaises(ValueError) as context:
            update_agent_info_impl(request)
        
        self.assertIn("Failed to update agent info", str(context.exception))
        
    @patch('backend.services.agent_service.delete_agent_by_id')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_delete_agent_impl_exception_handling(self, mock_get_current_user_id, mock_delete_agent):
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
        with self.assertRaises(ValueError) as context:
            delete_agent_impl(123)
        
        self.assertIn("Failed to delete agent", str(context.exception))

    @patch('backend.services.agent_service.create_tool_config_list')
    @patch('backend.services.agent_service.search_agent_info_by_agent_id')
    @patch('backend.services.agent_service.get_current_user_id')
    async def test_export_agent_impl_success(self, mock_get_current_user_id, mock_search_agent, mock_create_tool_config):
        """
        Test successful export of agent information.
        
        This test verifies that:
        1. The function correctly gets the current user and tenant IDs
        2. It retrieves the agent's tools and information
        3. It returns the properly formatted agent information as JSON
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        
        mock_agent_info = {
            "name": "Test Agent",
            "description": "A test agent",
            "business_description": "For testing purposes",
            "model_name": "main_model",
            "max_steps": 10,
            "provide_run_summary": True,
            "prompt": "Test prompt",
            "enabled": True
        }
        mock_search_agent.return_value = mock_agent_info
        
        mock_tools = [
            {"class_name": "Tool1", "source": "source1", "params": {"param1": "value1"}}
        ]
        mock_create_tool_config.return_value = mock_tools
        
        # Execute
        result = await export_agent_impl(
            agent_id=123,
            authorization="Bearer token"
        )
        
        # Assert
        self.assertIn("Test Agent", result)
        self.assertIn("For testing purposes", result)
        mock_get_current_user_id.assert_called_once_with("Bearer token")
        mock_search_agent.assert_called_once_with(agent_id=123, tenant_id="test_tenant", user_id="test_user")
        mock_create_tool_config.assert_called_once_with(agent_id=123, tenant_id="test_tenant", user_id="test_user")

    @patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
    @patch('backend.services.agent_service.create_agent')
    @patch('backend.services.agent_service.query_all_tools')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_import_agent_impl_success(self, mock_get_current_user_id, mock_query_all_tools, 
                                       mock_create_agent, mock_create_tool):
        """
        Test successful import of agent information.
        
        This test verifies that:
        1. The function correctly validates tool parameters
        2. It validates agent parameters
        3. It creates a new agent with the provided information
        4. It creates tool instances for the agent
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        
        # Mock tool database records
        mock_tool_info = [
            {
                "tool_id": 101,
                "class_name": "Tool1",
                "source": "source1",
                "params": [{"name": "param1", "type": "string"}]
            }
        ]
        mock_query_all_tools.return_value = mock_tool_info
        
        # Mock new agent creation
        mock_create_agent.return_value = {"agent_id": 456}
        
        # Create import data
        tool_config = {
            "class_name": "Tool1",
            "source": "source1",
            "params": {"param1": "value1"}
        }
        
        agent_info = ExportAndImportAgentInfo(
            name="Imported Agent",
            description="Imported description",
            business_description="Imported business description",
            model_name="main_model",
            max_steps=5,
            provide_run_summary=True,
            prompt="Imported prompt",
            enabled=True,
            tools=[tool_config],
            managed_agents=[]
        )
        
        # Execute
        import_agent_impl(
            parent_agent_id=123,
            agent_info=agent_info,
            authorization="Bearer token"
        )
        
        # Assert
        mock_create_agent.assert_called_once()
        self.assertEqual(mock_create_agent.call_args[1]["agent_info"]["name"], "Imported Agent")
        mock_create_tool.assert_called_once()

    @patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
    @patch('backend.services.agent_service.query_all_tools')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_import_agent_impl_invalid_tool(self, mock_get_current_user_id, mock_query_all_tools, 
                                           mock_create_tool):
        """
        Test import of agent information with an invalid tool.
        
        This test verifies that:
        1. The function correctly validates tool parameters
        2. It raises an appropriate error for invalid tools
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        
        # Mock tool database records
        mock_tool_info = [
            {
                "tool_id": 101,
                "class_name": "OtherTool",
                "source": "source1",
                "params": [{"name": "param1", "type": "string"}]
            }
        ]
        mock_query_all_tools.return_value = mock_tool_info
        
        # Create import data with non-existent tool
        tool_config = {
            "class_name": "Tool1",
            "source": "source1",
            "params": {"param1": "value1"}
        }
        
        agent_info = ExportAndImportAgentInfo(
            name="Imported Agent",
            description="Imported description",
            business_description="Imported business description",
            model_name="main_model",
            max_steps=5,
            provide_run_summary=True,
            prompt="Imported prompt",
            enabled=True,
            tools=[tool_config],
            managed_agents=[]
        )
        
        # Execute & Assert
        with self.assertRaises(ValueError) as context:
            import_agent_impl(
                parent_agent_id=123,
                agent_info=agent_info,
                authorization="Bearer token"
            )
        
        self.assertIn("Cannot find tool Tool1", str(context.exception))
        mock_create_tool.assert_not_called()

    @patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
    @patch('backend.services.agent_service.query_all_tools')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_import_agent_impl_invalid_parameters(self, mock_get_current_user_id, mock_query_all_tools, 
                                                mock_create_tool):
        """
        Test import of agent information with invalid tool parameters.
        
        This test verifies that:
        1. The function correctly validates tool parameter names
        2. It raises an appropriate error for invalid parameter names
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        
        # Mock tool database records with specific param names
        mock_tool_info = [
            {
                "tool_id": 101,
                "class_name": "Tool1",
                "source": "source1",
                "params": [{"name": "valid_param", "type": "string"}]
            }
        ]
        mock_query_all_tools.return_value = mock_tool_info
        
        # Create import data with invalid parameter
        tool_config = {
            "class_name": "Tool1",
            "source": "source1",
            "params": {"invalid_param": "value1"}
        }
        
        agent_info = ExportAndImportAgentInfo(
            name="Imported Agent",
            description="Imported description",
            business_description="Imported business description",
            model_name="main_model",
            max_steps=5,
            provide_run_summary=True,
            prompt="Imported prompt",
            enabled=True,
            tools=[tool_config],
            managed_agents=[]
        )
        
        # Execute & Assert
        with self.assertRaises(ValueError) as context:
            import_agent_impl(
                parent_agent_id=123,
                agent_info=agent_info,
                authorization="Bearer token"
            )
        
        self.assertIn("Parameter invalid_param in tool Tool1", str(context.exception))
        mock_create_tool.assert_not_called()

    @patch('backend.services.agent_service.create_or_update_tool_by_tool_info')
    @patch('backend.services.agent_service.create_agent')
    @patch('backend.services.agent_service.query_all_tools')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_import_agent_impl_invalid_model_name(self, mock_get_current_user_id, mock_query_all_tools,
                                                mock_create_agent, mock_create_tool):
        """
        Test import of agent information with an invalid model name.
        
        This test verifies that:
        1. The function correctly validates the model name
        2. It raises an appropriate error for invalid model names
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        
        # Mock tool database records
        mock_tool_info = [
            {
                "tool_id": 101,
                "class_name": "Tool1",
                "source": "source1",
                "params": [{"name": "param1", "type": "string"}]
            }
        ]
        mock_query_all_tools.return_value = mock_tool_info
        
        # Create import data with invalid model name
        tool_config = {
            "class_name": "Tool1",
            "source": "source1",
            "params": {"param1": "value1"}
        }
        
        agent_info = ExportAndImportAgentInfo(
            name="Imported Agent",
            description="Imported description",
            business_description="Imported business description",
            model_name="invalid_model",  # Not main_model or sub_model
            max_steps=5,
            provide_run_summary=True,
            prompt="Imported prompt",
            enabled=True,
            tools=[tool_config],
            managed_agents=[]
        )
        
        # Execute & Assert
        with self.assertRaises(ValueError) as context:
            import_agent_impl(
                parent_agent_id=123,
                agent_info=agent_info,
                authorization="Bearer token"
            )
        
        self.assertIn("Invalid model name: invalid_model", str(context.exception))
        mock_create_agent.assert_not_called()
        mock_create_tool.assert_not_called()

    @patch('backend.services.agent_service.query_sub_agents')
    @patch('backend.services.agent_service.query_or_create_main_agent_id')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_search_sub_agents_success(self, mock_get_current_user_id, mock_query_main_agent, mock_query_sub_agents):
        """
        Test successful search of sub-agents.
        
        This test verifies that:
        1. The function correctly gets the current user and tenant IDs
        2. It retrieves or creates the main agent ID
        3. It fetches the sub-agents for the main agent
        4. It returns the main agent ID and sub-agent list
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        mock_query_main_agent.return_value = 123
        
        mock_sub_agents = [
            {"agent_id": 456, "name": "Sub Agent 1"},
            {"agent_id": 789, "name": "Sub Agent 2"}
        ]
        mock_query_sub_agents.return_value = mock_sub_agents
        
        # Execute
        main_agent_id, sub_agents = search_sub_agents()
        
        # Assert
        self.assertEqual(main_agent_id, 123)
        self.assertEqual(sub_agents, mock_sub_agents)
        mock_query_main_agent.assert_called_once_with(tenant_id="test_tenant", user_id="test_user")
        mock_query_sub_agents.assert_called_once_with(123, "test_tenant", "test_user")

    @patch('backend.services.agent_service.query_or_create_main_agent_id')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_search_sub_agents_main_agent_error(self, mock_get_current_user_id, mock_query_main_agent):
        """
        Test search sub-agents with an error in retrieving the main agent ID.
        
        This test verifies that:
        1. When an error occurs retrieving the main agent ID
        2. The function raises a ValueError with an appropriate message
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        mock_query_main_agent.side_effect = Exception("Database error")
        
        # Execute & Assert
        with self.assertRaises(ValueError) as context:
            search_sub_agents()
        
        self.assertIn("Failed to get main agent id", str(context.exception))

    @patch('backend.services.agent_service.query_sub_agents')
    @patch('backend.services.agent_service.query_or_create_main_agent_id')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_search_sub_agents_sub_agents_error(self, mock_get_current_user_id, mock_query_main_agent, mock_query_sub_agents):
        """
        Test search sub-agents with an error in retrieving the sub-agents.
        
        This test verifies that:
        1. When an error occurs retrieving the sub-agents
        2. The function raises a ValueError with an appropriate message
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        mock_query_main_agent.return_value = 123
        mock_query_sub_agents.side_effect = Exception("Database error")
        
        # Execute & Assert
        with self.assertRaises(ValueError) as context:
            search_sub_agents()
        
        self.assertIn("Failed to get sub agent list", str(context.exception))

    @patch('os.path.join', return_value='test_path')
    @patch('os.listdir')
    @patch('builtins.open', new_callable=mock_open)
    def test_load_default_agents_json_file(self, mock_file, mock_listdir, mock_join):
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
            "name": "Agent1",
            "description": "Agent 1 description",
            "business_description": "Business description",
            "model_name": "main_model",
            "max_steps": 10,
            "provide_run_summary": true,
            "prompt": "Agent 1 prompt",
            "enabled": true,
            "tools": [],
            "managed_agents": []
        }"""
        
        json_content2 = """{
            "name": "Agent2",
            "description": "Agent 2 description",
            "business_description": "Business description",
            "model_name": "sub_model",
            "max_steps": 5,
            "provide_run_summary": false,
            "prompt": "Agent 2 prompt",
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
                    "name": "Agent1",
                    "description": "Agent 1 description",
                    "business_description": "Business description",
                    "model_name": "main_model",
                    "max_steps": 10,
                    "provide_run_summary": True,
                    "prompt": "Agent 1 prompt",
                    "enabled": True,
                    "tools": [],
                    "managed_agents": []
                },
                {
                    "name": "Agent2",
                    "description": "Agent 2 description",
                    "business_description": "Business description",
                    "model_name": "sub_model",
                    "max_steps": 5,
                    "provide_run_summary": False,
                    "prompt": "Agent 2 prompt",
                    "enabled": True,
                    "tools": [],
                    "managed_agents": []
                }
            ]
            
            # Execute
            result = load_default_agents_json_file("default/path")
            
            # Assert
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0].name, "Agent1")
            self.assertEqual(result[1].name, "Agent2")
            self.assertEqual(mock_file.call_count, 2)
            mock_listdir.assert_called_once_with("default/path")

    @patch('backend.services.agent_service.import_agent_impl')
    @patch('backend.services.agent_service.load_default_agents_json_file')
    @patch('backend.services.agent_service.search_sub_agents')
    def test_import_default_agents_to_pg_success(self, mock_search_sub_agents, mock_load_defaults, mock_import_agent):
        """
        Test successful import of default agents to PostgreSQL.
        
        This test verifies that:
        1. The function retrieves existing sub-agents
        2. It loads default agent configurations
        3. It imports agents that don't already exist
        4. It skips agents that already exist
        """
        # Setup
        mock_search_sub_agents.return_value = (123, [{"name": "ExistingAgent"}])
        
        agent1 = ExportAndImportAgentInfo(
            name="ExistingAgent",
            description="Already exists",
            business_description="Business description",
            model_name="main_model",
            max_steps=10,
            provide_run_summary=True,
            prompt="Agent prompt",
            enabled=True,
            tools=[],
            managed_agents=[]
        )
        
        agent2 = ExportAndImportAgentInfo(
            name="NewAgent",
            description="New agent",
            business_description="Business description",
            model_name="sub_model",
            max_steps=5,
            provide_run_summary=True,
            prompt="Agent prompt",
            enabled=True,
            tools=[],
            managed_agents=[]
        )
        
        mock_load_defaults.return_value = [agent1, agent2]
        
        # Execute
        import_default_agents_to_pg()
        
        # Assert
        mock_import_agent.assert_called_once_with(parent_agent_id=123, agent_info=agent2)

    @patch('backend.services.agent_service.load_default_agents_json_file')
    @patch('backend.services.agent_service.search_sub_agents')
    def test_import_default_agents_to_pg_load_error(self, mock_search_sub_agents, mock_load_defaults):
        """
        Test import of default agents with an error in loading the default agents.
        
        This test verifies that:
        1. When an error occurs loading default agent configurations
        2. The function raises a ValueError with an appropriate message
        """
        # Setup
        mock_search_sub_agents.return_value = (123, [{"name": "ExistingAgent"}])
        mock_load_defaults.side_effect = Exception("File error")
        
        # Execute & Assert
        with self.assertRaises(ValueError) as context:
            import_default_agents_to_pg()
        
        self.assertIn("Failed to load default agents", str(context.exception))

    @patch('backend.services.agent_service.search_agent_info_by_agent_id')
    @patch('backend.services.agent_service.get_current_user_id')
    def test_get_agent_info_impl_with_tool_error(self, mock_get_current_user_id, mock_search_agent_info):
        """
        Test get_agent_info_impl with an error in retrieving tool information.
        
        This test verifies that:
        1. The function correctly gets the agent information
        2. When an error occurs retrieving tool information
        3. The function returns the agent information with an empty tools list
        """
        # Setup
        mock_get_current_user_id.return_value = ("test_user", "test_tenant")
        mock_agent_info = {
            "agent_id": 123,
            "model_name": "gpt-4",
            "business_description": "Test agent"
        }
        mock_search_agent_info.return_value = mock_agent_info
        
        # Mock the search_tools_for_sub_agent function to raise an exception
        with patch('backend.services.agent_service.search_tools_for_sub_agent') as mock_search_tools:
            mock_search_tools.side_effect = Exception("Tool search error")
            
            # Execute
            result = get_agent_info_impl(123)
            
            # Assert
            self.assertEqual(result["agent_id"], 123)
            self.assertEqual(result["tools"], [])
            mock_search_agent_info.assert_called_once_with(123, "test_tenant", "test_user")

if __name__ == '__main__':
    unittest.main() 