import pytest
import sys
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TEST_ROOT.parent

for _path in (str(PROJECT_ROOT), str(TEST_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


class TestFormatFunctions:
    """Tests for formatting helper functions."""
    
    def test_format_tools_empty(self):
        from backend.utils.context_utils import _format_tools_description
        result = _format_tools_description({})
        assert result == ""
    
    def test_format_tools_single(self):
        from backend.utils.context_utils import _format_tools_description
        class MockTool:
            name = "search"
            description = "Search tool"
            inputs = '{"query": "str"}'
            output_type = "string"
        result = _format_tools_description({"search": MockTool()})
        assert "Available tools:" in result
        assert "search" in result
    
    def test_format_skills_empty(self):
        from backend.utils.context_utils import _format_skills_description
        result = _format_skills_description([])
        assert result == ""
    
    def test_format_skills_single(self):
        from backend.utils.context_utils import _format_skills_description
        skills = [{"name": "skill1", "description": "Test skill"}]
        result = _format_skills_description(skills)
        assert "Available skills:" in result
        assert "skill1" in result
    
    def test_format_memory_empty(self):
        from backend.utils.context_utils import _format_memory_context
        result = _format_memory_context([])
        assert result == ""
    
    def test_format_memory_dict(self):
        from backend.utils.context_utils import _format_memory_context
        memory = [{"memory": "test memory"}]
        result = _format_memory_context(memory)
        assert "test memory" in result
    
    def test_format_memory_string(self):
        from backend.utils.context_utils import _format_memory_context
        memory = ["simple string"]
        result = _format_memory_context(memory)
        assert "simple string" in result
    
    def test_format_managed_agents_empty(self):
        from backend.utils.context_utils import _format_managed_agents_description
        result = _format_managed_agents_description({})
        assert result == ""
    
    def test_format_managed_agents_single(self):
        from backend.utils.context_utils import _format_managed_agents_description
        class MockAgent:
            name = "research"
            description = "Research assistant"
        result = _format_managed_agents_description({"research": MockAgent()})
        assert "Available sub-agents" in result
    
    def test_format_external_agents_empty(self):
        from backend.utils.context_utils import _format_external_agents_description
        result = _format_external_agents_description({})
        assert result == ""
    
    def test_format_external_agents_single(self):
        from backend.utils.context_utils import _format_external_agents_description
        class MockAgent:
            agent_id = "ext-1"
            name = "External"
            description = "External agent"
        result = _format_external_agents_description({"ext-1": MockAgent()})
        assert "Available external agents" in result


class TestBuildComponents:
    """Tests for component builder functions."""
    
    def test_build_tools_component_empty(self):
        from backend.utils.context_utils import build_tools_component
        comp = build_tools_component({})
        assert comp.tools == []
    
    def test_build_tools_component_with_tools(self):
        from backend.utils.context_utils import build_tools_component
        class MockTool:
            name = "tool"
            description = "desc"
            inputs = "{}"
            output_type = "str"
        comp = build_tools_component({"tool": MockTool()})
        assert len(comp.tools) == 1
    
    def test_build_skills_component_empty(self):
        from backend.utils.context_utils import build_skills_component
        comp = build_skills_component([])
        assert comp.skills == []
    
    def test_build_skills_component_with_skills(self):
        from backend.utils.context_utils import build_skills_component
        comp = build_skills_component([{"name": "skill"}])
        assert len(comp.skills) == 1
    
    def test_build_memory_component_empty(self):
        from backend.utils.context_utils import build_memory_component
        comp = build_memory_component([])
        assert comp.memories == []
    
    def test_build_memory_component_with_search_query(self):
        from backend.utils.context_utils import build_memory_component
        comp = build_memory_component([], search_query="test query")
        assert comp.search_query == "test query"
    
    def test_build_knowledge_base_component_empty(self):
        from backend.utils.context_utils import build_knowledge_base_component
        comp = build_knowledge_base_component("")
        assert comp.summary == ""
    
    def test_build_knowledge_base_component_with_summary(self):
        from backend.utils.context_utils import build_knowledge_base_component
        comp = build_knowledge_base_component("KB text", kb_ids=["kb-1"])
        assert comp.summary == "KB text"
    
    def test_build_managed_agents_component_empty(self):
        from backend.utils.context_utils import build_managed_agents_component
        comp = build_managed_agents_component({})
        assert comp.agents == []
    
    def test_build_external_agents_component_empty(self):
        from backend.utils.context_utils import build_external_agents_component
        comp = build_external_agents_component({})
        assert comp.agents == []
    
    def test_build_system_prompt_component_empty(self):
        from backend.utils.context_utils import build_system_prompt_component
        comp = build_system_prompt_component("")
        assert comp.content == ""
    
    def test_build_system_prompt_component_with_template(self):
        from backend.utils.context_utils import build_system_prompt_component
        comp = build_system_prompt_component("test", template_name="template.yaml")
        assert comp.template_name == "template.yaml"


class TestBuildContextComponents:
    """Tests for main build_context_components function."""
    
    def test_empty_inputs(self):
        from backend.utils.context_utils import build_context_components
        components = build_context_components()
        assert components == []
    
    def test_with_tools_only(self):
        from backend.utils.context_utils import build_context_components
        class MockTool:
            name = "tool"
            description = "desc"
            inputs = "{}"
            output_type = "str"
        components = build_context_components(tools={"tool": MockTool()})
        assert len(components) == 1
    
    def test_include_flags(self):
        from backend.utils.context_utils import build_context_components
        class MockTool:
            name = "tool"
            description = "desc"
            inputs = "{}"
            output_type = "str"
        components = build_context_components(
            tools={"tool": MockTool()},
            include_tools=False,
        )
        assert components == []
    
    def test_app_context_string(self):
        from backend.utils.context_utils import build_app_context_string
        result = build_app_context_string("Nexent", "Platform", "user-1")
        assert "Nexent" in result
        assert "Platform" in result
        assert "user-1" in result


if __name__ == "__main__":
    pytest.main([__file__])
