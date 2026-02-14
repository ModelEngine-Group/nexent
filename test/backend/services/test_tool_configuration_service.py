"""
Tests for tool_configuration_service module.
"""
import sys
import pytest
from unittest.mock import patch, MagicMock

# Mock consts module before importing the service
consts_mock = MagicMock()
consts_mock.const = MagicMock()
consts_mock.const.LOCAL_MCP_SERVER = "http://localhost:8000"
consts_mock.const.DATA_PROCESS_SERVICE = "http://localhost:8001"
sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const

# Mock other dependencies
sys.modules['fastmcp'] = MagicMock()
sys.modules['mcpadapt'] = MagicMock()
sys.modules['mcpadapt.smolagents_adapter'] = MagicMock()

# Mock consts.exceptions
consts_exceptions_mock = MagicMock()
sys.modules['consts.exceptions'] = consts_exceptions_mock

# Mock other required modules
sys.modules['pydantic_core'] = MagicMock()
sys.modules['jsonref'] = MagicMock()

from backend.services.tool_configuration_service import (
    get_local_tools_description_zh,
    get_local_tools_classes
)


class MockToolClass:
    """Mock tool class for testing."""
    name = "test_tool"
    description = "Test tool description"
    description_zh = "测试工具描述"
    
    inputs = {
        "query": {
            "type": "string",
            "description": "Search query",
            "description_zh": "搜索查询"
        }
    }
    
    init_param_descriptions = {
        "api_key": {
            "description": "API key",
            "description_zh": "API密钥"
        }
    }
    
    def __init__(self, api_key: str = "default"):
        self.api_key = api_key


class TestGetLocalToolsDescriptionZh:
    """Tests for get_local_tools_description_zh function."""
    
    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_returns_correct_structure(self, mock_get_classes):
        """Test that function returns correct structure with description_zh."""
        mock_get_classes.return_value = [MockToolClass]
        
        result = get_local_tools_description_zh()
        
        assert "test_tool" in result
        tool_info = result["test_tool"]
        assert "description_zh" in tool_info
        assert tool_info["description_zh"] == "测试工具描述"
        assert "params" in tool_info
        assert "inputs" in tool_info
    
    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_extracts_param_description_zh(self, mock_get_classes):
        """Test that function extracts description_zh from params."""
        mock_get_classes.return_value = [MockToolClass]
        
        result = get_local_tools_description_zh()
        
        tool_info = result["test_tool"]
        params = tool_info["params"]
        
        # Check that params include description_zh
        api_key_param = next(p for p in params if p["name"] == "api_key")
        assert api_key_param["description_zh"] == "API密钥"
    
    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_extracts_inputs_description_zh(self, mock_get_classes):
        """Test that function extracts description_zh from inputs."""
        mock_get_classes.return_value = [MockToolClass]
        
        result = get_local_tools_description_zh()
        
        tool_info = result["test_tool"]
        inputs = tool_info["inputs"]
        
        assert "query" in inputs
        assert inputs["query"]["description_zh"] == "搜索查询"
    
    @patch('backend.services.tool_configuration_service.get_local_tools_classes')
    def test_returns_empty_dict_when_no_tools(self, mock_get_classes):
        """Test that function returns empty dict when no tools available."""
        mock_get_classes.return_value = []
        
        result = get_local_tools_description_zh()
        
        assert result == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
