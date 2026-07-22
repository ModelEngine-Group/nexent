"""Regression tests for SDK local tool catalog discovery."""

from backend.services.tool_configuration_service import get_local_tools
from backend.utils.tool_utils import get_local_tools_classes


NON_CATALOG_TOOL_CLASSES = {
    "NL2AgentSearchLocalResourcesTool",
    "NL2AgentSearchWebMcpsTool",
    "NL2AgentSearchWebSkillsTool",
    "ParallelExecutorTool",
}


def test_real_sdk_discovery_excludes_builtin_and_system_managed_tools():
    """Builtin-only SDK exports must not be discovered as local catalog tools."""
    class_names = {tool_class.__name__ for tool_class in get_local_tools_classes()}

    assert "TavilySearchTool" in class_names
    assert class_names.isdisjoint(NON_CATALOG_TOOL_CLASSES)


def test_real_sdk_local_tools_can_be_serialized():
    """All discovered local SDK tools must satisfy ToolInfo serialization."""
    tools = get_local_tools()
    class_names = {tool.class_name for tool in tools}

    assert "TavilySearchTool" in class_names
    assert class_names.isdisjoint(NON_CATALOG_TOOL_CLASSES)
