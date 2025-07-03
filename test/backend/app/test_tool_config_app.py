import unittest
from unittest.mock import patch, MagicMock
import sys

# Mock modules before importing anything else
sys.modules['database.agent_db'] = MagicMock()
sys.modules['database.client'] = MagicMock()
sys.modules['consts.model'] = MagicMock()
sys.modules['services.tool_configuration_service'] = MagicMock()
sys.modules['utils.auth_utils'] = MagicMock()
sys.modules['fastapi'] = MagicMock()
sys.modules['fastapi.Header'] = MagicMock()

# Import the actual functions to test from source
import importlib.util
import os

# Get the absolute path to the file
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..', 'backend'))
target_file = os.path.join(backend_dir, 'apps', 'tool_config_app.py')

# Load the module
spec = importlib.util.spec_from_file_location("tool_config_app", target_file)
tool_config_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool_config_app)

# Get the functions directly from the module
list_tools_api = tool_config_app.list_tools_api
search_tool_info_api = tool_config_app.search_tool_info_api
update_tool_info_api = tool_config_app.update_tool_info_api

# Mock request classes
class MockToolInstanceSearchRequest:
    def __init__(self, agent_id, tool_id):
        self.agent_id = agent_id
        self.tool_id = tool_id

class MockToolInstanceInfoRequest:
    def __init__(self, agent_id, tool_id, configuration):
        self.agent_id = agent_id
        self.tool_id = tool_id
        self.configuration = configuration

# Mock HTTPException
class MockHTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")

# Replace FastAPI's HTTPException with our mock
tool_config_app.HTTPException = MockHTTPException

class TestToolConfigApp(unittest.TestCase):
    def setUp(self):
        pass
        
    @patch("utils.auth_utils.get_current_user_id")
    @patch("database.agent_db.query_all_tools")
    async def test_list_tools_api_success(self, mock_query_all_tools, mock_get_current_user_id):
        # Setup
        mock_get_current_user_id.return_value = ("user123", "tenant456")
        expected_tools = [{"id": 1, "name": "Tool1"}, {"id": 2, "name": "Tool2"}]
        mock_query_all_tools.return_value = expected_tools
        
        # Execute
        result = await list_tools_api(authorization="Bearer fake_token")
        
        # Assert
        mock_get_current_user_id.assert_called_once_with("Bearer fake_token")
        mock_query_all_tools.assert_called_once_with(tenant_id="tenant456")
        self.assertEqual(result, expected_tools)
    
    @patch("utils.auth_utils.get_current_user_id")
    async def test_list_tools_api_error(self, mock_get_current_user_id):
        # Setup
        mock_get_current_user_id.side_effect = Exception("Auth error")
        
        # Execute and Assert
        with self.assertRaises(MockHTTPException) as context:
            await list_tools_api(authorization="Bearer fake_token")
        
        self.assertEqual(context.exception.status_code, 500)
        self.assertTrue("Failed to get tool info" in context.exception.detail)
    
    @patch("services.tool_configuration_service.search_tool_info_impl")
    async def test_search_tool_info_api_success(self, mock_search_tool_info_impl):
        # Setup
        request = MockToolInstanceSearchRequest(agent_id="agent123", tool_id="tool456")
        expected_result = {"tool": "info"}
        mock_search_tool_info_impl.return_value = expected_result
        
        # Execute
        result = await search_tool_info_api(request, authorization="Bearer fake_token")
        
        # Assert
        mock_search_tool_info_impl.assert_called_once_with("agent123", "tool456", "Bearer fake_token")
        self.assertEqual(result, expected_result)
    
    @patch("services.tool_configuration_service.search_tool_info_impl")
    async def test_search_tool_info_api_error(self, mock_search_tool_info_impl):
        # Setup
        request = MockToolInstanceSearchRequest(agent_id="agent123", tool_id="tool456")
        mock_search_tool_info_impl.side_effect = Exception("Search error")
        
        # Execute and Assert
        with self.assertRaises(MockHTTPException) as context:
            await search_tool_info_api(request, authorization="Bearer fake_token")
        
        self.assertEqual(context.exception.status_code, 500)
        self.assertTrue("Failed to update tool" in context.exception.detail)
    
    @patch("services.tool_configuration_service.update_tool_info_impl")
    async def test_update_tool_info_api_success(self, mock_update_tool_info_impl):
        # Setup
        request = MockToolInstanceInfoRequest(
            agent_id="agent123", 
            tool_id="tool456",
            configuration={"key": "value"}
        )
        expected_result = {"updated": True}
        mock_update_tool_info_impl.return_value = expected_result
        
        # Execute
        result = await update_tool_info_api(request, authorization="Bearer fake_token")
        
        # Assert
        mock_update_tool_info_impl.assert_called_once_with(request, "Bearer fake_token")
        self.assertEqual(result, expected_result)
    
    @patch("services.tool_configuration_service.update_tool_info_impl")
    async def test_update_tool_info_api_error(self, mock_update_tool_info_impl):
        # Setup
        request = MockToolInstanceInfoRequest(
            agent_id="agent123", 
            tool_id="tool456",
            configuration={"key": "value"}
        )
        mock_update_tool_info_impl.side_effect = Exception("Update error")
        
        # Execute and Assert
        with self.assertRaises(MockHTTPException) as context:
            await update_tool_info_api(request, authorization="Bearer fake_token")
        
        self.assertEqual(context.exception.status_code, 500)
        self.assertTrue("Failed to update tool" in context.exception.detail)


if __name__ == "__main__":
    unittest.main()
