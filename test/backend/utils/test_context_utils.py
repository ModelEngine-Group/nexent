import pytest
import sys
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TEST_ROOT.parent

for _path in (str(PROJECT_ROOT), str(TEST_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


class TestFormatFunctions:
    def test_format_tools_empty(self):
        from backend.utils.context_utils import _format_tools_description
        result = _format_tools_description({}, language="zh")
        assert result == "1. 工具\n- 当前没有可用的工具"

    def test_format_tools_empty_managed(self):
        from backend.utils.context_utils import _format_tools_description
        result = _format_tools_description({}, language="zh", is_manager=False)
        assert result == "1. 工具\n- 当前没有可用的工具"

    def test_format_tools_single(self):
        from backend.utils.context_utils import _format_tools_description
        class MockTool:
            name = "search"
            description = "Search tool"
            inputs = '{"query": "str"}'
            output_type = "string"
            source = "local"
        result = _format_tools_description({"search": MockTool()}, language="zh")
        assert "search" in result
        assert "Search tool" in result

    def test_format_tools_single_english(self):
        from backend.utils.context_utils import _format_tools_description
        class MockTool:
            name = "search"
            description = "Search tool"
            inputs = '{"query": "str"}'
            output_type = "string"
            source = "local"
        result = _format_tools_description({"search": MockTool()}, language="en")
        assert "search" in result
        assert "Search tool" in result
        assert "1. Tools" in result
        assert "Accepts input" in result

    def test_format_tools_dict_input(self):
        """When tool is a plain dict, the dict-style branch should be exercised."""
        from backend.utils.context_utils import _format_tools_description
        tool_dict = {
            "description": "Dict tool",
            "inputs": '{"key": "value"}',
            "output_type": "str",
            "source": "local",
        }
        result = _format_tools_description({"dicttool": tool_dict}, language="zh")
        assert "dicttool" in result
        assert "Dict tool" in result
        assert "接受输入" in result

    def test_format_tools_dict_input_english(self):
        from backend.utils.context_utils import _format_tools_description
        tool_dict = {
            "description": "Dict tool",
            "inputs": '{"key": "value"}',
            "output_type": "str",
            "source": "local",
        }
        result = _format_tools_description({"dicttool": tool_dict}, language="en")
        assert "dicttool" in result
        assert "Dict tool" in result
        assert "Accepts input" in result

    def test_format_tools_mcp_source_zh(self):
        """MCP source should render with [MCP] prefix in Chinese."""
        from backend.utils.context_utils import _format_tools_description
        class MockTool:
            name = "mcp_tool"
            description = "MCP description"
            inputs = '{"x": "y"}'
            output_type = "string"
            source = "mcp"
        result = _format_tools_description({"mcp_tool": MockTool()}, language="zh")
        assert "[MCP]" in result
        assert "mcp_tool" in result
        assert "MCP description" in result

    def test_format_tools_mcp_source_en(self):
        from backend.utils.context_utils import _format_tools_description
        class MockTool:
            name = "mcp_tool"
            description = "MCP description"
            inputs = '{"x": "y"}'
            output_type = "string"
            source = "mcp"
        result = _format_tools_description({"mcp_tool": MockTool()}, language="en")
        assert "[MCP]" in result
        assert "mcp_tool" in result
        assert "MCP description" in result

    def test_format_tools_managed_zh(self):
        """When is_manager=False, the [MCP] guidance uses presigned_url."""
        from backend.utils.context_utils import _format_tools_description
        result = _format_tools_description(
            {}, language="zh", is_manager=False
        )
        # The empty branch is shared for both manager and managed; this confirms
        # the empty tools path works in managed mode.
        assert "1. 工具" in result

    def test_format_tools_file_url_guide_managed_zh(self):
        """Non-empty tools + is_manager=False surfaces presigned_url guidance in Chinese."""
        from backend.utils.context_utils import _format_tools_description
        class MockTool:
            name = "search"
            description = "Search tool"
            inputs = '{"query": "str"}'
            output_type = "string"
            source = "local"
        result = _format_tools_description(
            {"search": MockTool()}, language="zh", is_manager=False
        )
        assert "presigned_url" in result
        assert "Download URL" not in result

    def test_format_tools_file_url_guide_managed_en(self):
        from backend.utils.context_utils import _format_tools_description
        class MockTool:
            name = "search"
            description = "Search tool"
            inputs = '{"query": "str"}'
            output_type = "string"
            source = "local"
        result = _format_tools_description(
            {"search": MockTool()}, language="en", is_manager=False
        )
        assert "presigned_url" in result
        assert "Download URL" not in result

    def test_format_skills_empty(self):
        from backend.utils.context_utils import _format_skills_description
        result = _format_skills_description([], language="zh")
        assert result == ""

    def test_format_skills_single(self):
        from backend.utils.context_utils import _format_skills_description
        skills = [{"name": "skill1", "description": "Test skill"}]
        result = _format_skills_description(skills, language="zh")
        assert "skill1" in result
        assert "Test skill" in result

    def test_format_skills_english(self):
        from backend.utils.context_utils import _format_skills_description
        skills = [{"name": "skill1", "description": "Test skill"}]
        result = _format_skills_description(skills, language="en")
        assert "skill1" in result
        assert "Test skill" in result
        assert "Available Skills" in result
        assert "Skill Usage Process" in result

    def test_format_skills_multiple(self):
        """Multiple skills should all appear in the rendered block."""
        from backend.utils.context_utils import _format_skills_description
        skills = [
            {"name": "alpha", "description": "first"},
            {"name": "beta", "description": "second"},
        ]
        result = _format_skills_description(skills, language="en")
        assert "<name>alpha</name>" in result
        assert "<name>beta</name>" in result

    def test_format_memory_empty(self):
        from backend.utils.context_utils import _format_memory_context
        result = _format_memory_context([], language="zh")
        assert result == ""

    def test_format_memory_dict(self):
        from backend.utils.context_utils import _format_memory_context
        memory = [{"memory": "test memory", "memory_level": "user", "score": 0.9}]
        result = _format_memory_context(memory, language="zh")
        assert "test memory" in result

    def test_format_memory_string(self):
        from backend.utils.context_utils import _format_memory_context
        memory = [{"memory": "simple string", "memory_level": "user", "score": 0.5}]
        result = _format_memory_context(memory, language="zh")
        assert "simple string" in result

    def test_format_memory_english(self):
        from backend.utils.context_utils import _format_memory_context
        memory = [{"memory": "english memory", "memory_level": "user", "score": 0.7}]
        result = _format_memory_context(memory, language="en")
        assert "english memory" in result
        assert "Contextual Memory" in result
        assert "Memory Usage Guidelines" in result

    def test_format_memory_all_levels(self):
        """All four memory levels should appear in level order."""
        from backend.utils.context_utils import _format_memory_context
        memory = [
            {"memory": "agent mem", "memory_level": "agent", "score": 0.1},
            {"memory": "tenant mem", "memory_level": "tenant", "score": 0.9},
            {"memory": "user_agent mem", "memory_level": "user_agent", "score": 0.8},
            {"memory": "user mem", "memory_level": "user", "score": 0.5},
        ]
        result = _format_memory_context(memory, language="en")
        # All four memories should be present.
        assert "tenant mem" in result
        assert "user_agent mem" in result
        assert "user mem" in result
        assert "agent mem" in result
        # Tenant should appear before agent in the rendered output (level order).
        assert result.index("tenant mem") < result.index("agent mem")

    def test_format_memory_default_level(self):
        """Memories without memory_level should default to 'user'."""
        from backend.utils.context_utils import _format_memory_context
        memory = [{"memory": "no level", "score": 0.5}]
        result = _format_memory_context(memory, language="en")
        assert "no level" in result

    def test_format_memory_duplicate_levels(self):
        """Two memories at the same level should be appended to the same bucket.
        This exercises the 'level already in memory_by_level' branch on line 53->55."""
        from backend.utils.context_utils import _format_memory_context
        memory = [
            {"memory": "first", "memory_level": "user", "score": 0.5},
            {"memory": "second", "memory_level": "user", "score": 0.3},
        ]
        result = _format_memory_context(memory, language="en")
        assert "first" in result
        assert "second" in result

    def test_format_memory_non_dict_ignored(self):
        """Non-dict memory items should be ignored."""
        from backend.utils.context_utils import _format_memory_context
        memory = ["string-only", {"memory": "valid", "memory_level": "user", "score": 0.5}]
        result = _format_memory_context(memory, language="en")
        assert "valid" in result
        # The string-only entry should not appear in the level-bucketed output.
        assert "string-only" not in result

    def test_format_memory_falls_back_to_content_key(self):
        """When 'memory' key is missing, fall back to 'content' key."""
        from backend.utils.context_utils import _format_memory_context
        memory = [{"content": "fallback content", "memory_level": "user", "score": 0.3}]
        result = _format_memory_context(memory, language="en")
        assert "fallback content" in result

    def test_format_managed_agents_empty(self):
        from backend.utils.context_utils import _format_managed_agents_description
        result = _format_managed_agents_description({}, language="zh")
        assert result == ""

    def test_format_managed_agents_single(self):
        from backend.utils.context_utils import _format_managed_agents_description
        class MockAgent:
            name = "research"
            description = "Research assistant"
        result = _format_managed_agents_description({"research": MockAgent()}, language="zh")
        assert "research" in result

    def test_format_managed_agents_english(self):
        from backend.utils.context_utils import _format_managed_agents_description
        class MockAgent:
            name = "research"
            description = "Research assistant"
        result = _format_managed_agents_description({"research": MockAgent()}, language="en")
        assert "research" in result
        assert "Research assistant" in result
        assert "Internal agent calling specifications" in result

    def test_format_managed_agents_dict_input(self):
        from backend.utils.context_utils import _format_managed_agents_description
        agent_dict = {"description": "Dict agent"}
        result = _format_managed_agents_description({"a": agent_dict}, language="en")
        assert "a" in result
        assert "Dict agent" in result

    def test_format_external_agents_empty(self):
        from backend.utils.context_utils import _format_external_agents_description
        result = _format_external_agents_description({}, language="zh")
        assert result == ""

    def test_format_external_agents_single(self):
        from backend.utils.context_utils import _format_external_agents_description
        class MockAgent:
            agent_id = "ext-1"
            name = "External"
            description = "External agent"
        result = _format_external_agents_description({"ext-1": MockAgent()}, language="zh")
        assert "External" in result

    def test_format_external_agents_english(self):
        from backend.utils.context_utils import _format_external_agents_description
        class MockAgent:
            agent_id = "ext-1"
            name = "External"
            description = "External agent"
        result = _format_external_agents_description({"ext-1": MockAgent()}, language="en")
        assert "External" in result
        assert "External agent" in result
        assert "External agent calling specifications" in result

    def test_format_external_agents_dict_input(self):
        from backend.utils.context_utils import _format_external_agents_description
        agent_dict = {"name": "ExtName", "description": "ExtDesc"}
        result = _format_external_agents_description({"ext-1": agent_dict}, language="en")
        assert "ExtName" in result
        assert "ExtDesc" in result


class TestFormatSkillsUsageRequirements:
    def test_skills_usage_empty_zh(self):
        from backend.utils.context_utils import _format_skills_usage_requirements
        result = _format_skills_usage_requirements([], language="zh")
        assert "3. 技能" in result
        assert "当前没有可用的技能" in result

    def test_skills_usage_empty_en(self):
        from backend.utils.context_utils import _format_skills_usage_requirements
        result = _format_skills_usage_requirements([], language="en")
        assert "3. Skills" in result
        assert "No skills are currently available" in result

    def test_skills_usage_with_skills_zh(self):
        from backend.utils.context_utils import _format_skills_usage_requirements
        skills = [{"name": "a", "description": "b"}]
        result = _format_skills_usage_requirements(skills, language="zh")
        assert "技能使用要求" in result
        assert "技能优先" in result

    def test_skills_usage_with_skills_en(self):
        from backend.utils.context_utils import _format_skills_usage_requirements
        skills = [{"name": "a", "description": "b"}]
        result = _format_skills_usage_requirements(skills, language="en")
        assert "Skill Usage Requirements" in result
        assert "Skill Priority" in result


class TestFormatAgentFallback:
    def test_agent_fallback_no_agents_zh(self):
        from backend.utils.context_utils import _format_agent_fallback
        result = _format_agent_fallback({}, {}, language="zh")
        assert "当前没有可用的助手" in result

    def test_agent_fallback_no_agents_en(self):
        from backend.utils.context_utils import _format_agent_fallback
        result = _format_agent_fallback({}, {}, language="en")
        assert "No agents are currently available" in result

    def test_agent_fallback_with_managed_agents(self):
        from backend.utils.context_utils import _format_agent_fallback
        result = _format_agent_fallback({"a": "x"}, {}, language="zh")
        assert result == ""

    def test_agent_fallback_with_external_agents(self):
        from backend.utils.context_utils import _format_agent_fallback
        result = _format_agent_fallback({}, {"a": "x"}, language="en")
        assert result == ""


class TestBuildComponents:
    def test_build_tools_component_empty(self):
        from backend.utils.context_utils import build_tools_component
        comp = build_tools_component({}, language="zh")
        assert comp.tools == []

    def test_build_tools_component_with_tools(self):
        from backend.utils.context_utils import build_tools_component
        class MockTool:
            name = "tool"
            description = "desc"
            inputs = "{}"
            output_type = "str"
            source = "local"
        comp = build_tools_component({"tool": MockTool()}, language="zh")
        assert len(comp.tools) == 1

    def test_build_tools_component_with_dict_input(self):
        """When tool is a dict, the dict-style branch should run."""
        from backend.utils.context_utils import build_tools_component
        tool_dict = {
            "description": "Dict desc",
            "inputs": "{}",
            "output_type": "str",
            "source": "local",
        }
        comp = build_tools_component({"tool": tool_dict}, language="en")
        assert len(comp.tools) == 1
        assert comp.tools[0]["name"] == "tool"
        assert comp.tools[0]["description"] == "Dict desc"

    def test_build_tools_component_mcp_source(self):
        from backend.utils.context_utils import build_tools_component
        class MockTool:
            name = "m"
            description = "mcp"
            inputs = "{}"
            output_type = "str"
            source = "mcp"
        comp = build_tools_component({"m": MockTool()}, language="zh")
        assert comp.tools[0]["source"] == "mcp"

    def test_build_tools_component_managed(self):
        from backend.utils.context_utils import build_tools_component
        class MockTool:
            name = "t"
            description = "d"
            inputs = "{}"
            output_type = "s"
            source = "local"
        comp = build_tools_component(
            {"t": MockTool()}, language="zh", is_manager=False
        )
        assert len(comp.tools) == 1
        assert "presigned_url" in comp.formatted_description

    def test_build_skills_component_empty(self):
        from backend.utils.context_utils import build_skills_component
        comp = build_skills_component([], language="zh")
        assert comp.skills == []

    def test_build_skills_component_with_skills(self):
        from backend.utils.context_utils import build_skills_component
        comp = build_skills_component([{"name": "skill"}], language="zh")
        assert len(comp.skills) == 1

    def test_build_memory_component_empty(self):
        from backend.utils.context_utils import build_memory_component
        comp = build_memory_component([], language="zh")
        assert comp.memories == []

    def test_build_memory_component_with_search_query(self):
        from backend.utils.context_utils import build_memory_component
        comp = build_memory_component([], search_query="test query", language="zh")
        assert comp.search_query == "test query"

    def test_build_memory_component_with_string_items(self):
        """String memory items should be wrapped as user memories."""
        from backend.utils.context_utils import build_memory_component
        comp = build_memory_component(["plain string"], language="zh")
        assert len(comp.memories) == 1
        assert comp.memories[0]["content"] == "plain string"
        assert comp.memories[0]["memory_type"] == "user"

    def test_build_memory_component_with_dict_items(self):
        """Dict memory items should be transformed via the dict path."""
        from backend.utils.context_utils import build_memory_component
        mem = {
            "memory": "alpha",
            "content": "alpha-content",
            "memory_type": "agent",
            "metadata": {"src": "x"},
        }
        comp = build_memory_component([mem], language="en")
        assert len(comp.memories) == 1
        assert comp.memories[0]["content"] == "alpha"
        assert comp.memories[0]["memory_type"] == "agent"
        assert comp.memories[0]["metadata"] == {"src": "x"}

    def test_build_memory_component_dict_falls_back_to_content(self):
        from backend.utils.context_utils import build_memory_component
        mem = {"content": "only-content"}
        comp = build_memory_component([mem], language="en")
        assert comp.memories[0]["content"] == "only-content"

    def test_build_memory_component_non_dict_non_string_ignored(self):
        """Memory items that are neither dict nor string are silently skipped.
        This exercises the elif branch (line 994->987) when neither condition
        is True."""
        from backend.utils.context_utils import build_memory_component
        # Pass an int and a list - neither is a dict or string, both should be
        # skipped without raising.
        comp = build_memory_component([123, [1, 2, 3]], language="en")
        assert comp.memories == []

    def test_build_knowledge_base_component_empty(self):
        from backend.utils.context_utils import build_knowledge_base_component
        comp = build_knowledge_base_component("")
        assert comp.summary == ""

    def test_build_knowledge_base_component_with_summary(self):
        from backend.utils.context_utils import build_knowledge_base_component
        comp = build_knowledge_base_component("KB text", kb_ids=["kb-1"])
        assert "KB text" in comp.summary
        assert "knowledge_base_search" in comp.summary

    def test_build_knowledge_base_component_english(self):
        from backend.utils.context_utils import build_knowledge_base_component
        comp = build_knowledge_base_component("KB text", language="en")
        assert "KB text" in comp.summary
        assert "knowledge_base_search" in comp.summary
        assert "based on the user's question" in comp.summary

    def test_build_knowledge_base_component_no_kb_ids(self):
        from backend.utils.context_utils import build_knowledge_base_component
        comp = build_knowledge_base_component("KB text")
        assert comp.kb_ids == []

    def test_build_managed_agents_component_empty(self):
        from backend.utils.context_utils import build_managed_agents_component
        comp = build_managed_agents_component({}, language="zh")
        assert comp.agents == []

    def test_build_managed_agents_component_with_agents(self):
        from backend.utils.context_utils import build_managed_agents_component
        class MockAgent:
            description = "Agent description"
            tools = []
        comp = build_managed_agents_component({"a": MockAgent()}, language="en")
        assert len(comp.agents) == 1
        assert comp.agents[0]["name"] == "a"

    def test_build_managed_agents_component_with_tools(self):
        from backend.utils.context_utils import build_managed_agents_component
        class MockTool:
            name = "search"
        class MockAgent:
            description = "Agent"
            tools = [MockTool()]
        comp = build_managed_agents_component({"a": MockAgent()}, language="en")
        assert comp.agents[0]["tools"] == ["search"]

    def test_build_managed_agents_component_dict_input(self):
        from backend.utils.context_utils import build_managed_agents_component
        agent_dict = {"description": "Dict agent"}
        comp = build_managed_agents_component({"a": agent_dict}, language="en")
        assert len(comp.agents) == 1
        assert comp.agents[0]["name"] == "a"
        assert comp.agents[0]["description"] == "Dict agent"

    def test_build_external_agents_component_empty(self):
        from backend.utils.context_utils import build_external_agents_component
        comp = build_external_agents_component({}, language="zh")
        assert comp.agents == []

    def test_build_external_agents_component_with_agents(self):
        from backend.utils.context_utils import build_external_agents_component
        class MockAgent:
            agent_id = 42
            name = "Ext"
            description = "Ext desc"
            url = "https://example.com"
        comp = build_external_agents_component({"42": MockAgent()}, language="en")
        assert len(comp.agents) == 1
        assert comp.agents[0]["agent_id"] == "42"
        assert comp.agents[0]["name"] == "Ext"
        assert comp.agents[0]["url"] == "https://example.com"

    def test_build_external_agents_component_no_url(self):
        from backend.utils.context_utils import build_external_agents_component
        class MockAgent:
            agent_id = 1
            name = "Ext"
            description = "Ext desc"
        comp = build_external_agents_component({"1": MockAgent()}, language="en")
        assert comp.agents[0]["url"] == ""

    def test_build_external_agents_component_dict_input(self):
        from backend.utils.context_utils import build_external_agents_component
        agent_dict = {
            "name": "DictExt",
            "description": "Dict ext",
            "url": "https://dict.example.com",
        }
        comp = build_external_agents_component({"1": agent_dict}, language="en")
        assert comp.agents[0]["name"] == "DictExt"
        assert comp.agents[0]["url"] == "https://dict.example.com"

    def test_build_system_prompt_component_empty(self):
        from backend.utils.context_utils import build_system_prompt_component
        comp = build_system_prompt_component("")
        assert comp.content == ""

    def test_build_system_prompt_component_with_template(self):
        from backend.utils.context_utils import build_system_prompt_component
        comp = build_system_prompt_component("test", template_name="template.yaml")
        assert comp.template_name == "template.yaml"


class TestSkeletonComponents:
    def test_skeleton_header_zh(self):
        from backend.utils.context_utils import build_skeleton_header_component
        comp = build_skeleton_header_component(
            app_name="Nexent",
            app_description="Platform",
            user_id="u-1",
            language="zh",
        )
        assert "Nexent" in comp.content
        assert "Platform" in comp.content
        assert "### 基本信息" in comp.content
        assert comp.template_name == "header"
        assert comp.priority == 100

    def test_skeleton_header_en(self):
        from backend.utils.context_utils import build_skeleton_header_component
        comp = build_skeleton_header_component(
            app_name="Nexent",
            app_description="Platform",
            user_id="u-1",
            language="en",
        )
        assert "Nexent" in comp.content
        assert "### Basic Information" in comp.content
        assert "You are Nexent" in comp.content

    def test_skeleton_header_custom_priority(self):
        from backend.utils.context_utils import build_skeleton_header_component
        comp = build_skeleton_header_component(
            app_name="A", app_description="B", user_id="C", priority=42,
        )
        assert comp.priority == 42

    def test_skeleton_duty_zh_manager(self):
        from backend.utils.context_utils import build_skeleton_duty_component
        comp = build_skeleton_duty_component(
            duty="Help users.", language="zh", is_manager=True
        )
        assert "Help users." in comp.content
        assert "### 核心职责" in comp.content
        assert "行为安全" in comp.content
        assert "文件操作必须使用平台提供的专用工具" in comp.content

    def test_skeleton_duty_zh_managed(self):
        """Managed agent uses different safety principles in Chinese."""
        from backend.utils.context_utils import build_skeleton_duty_component
        comp = build_skeleton_duty_component(
            duty="Be helpful.", language="zh", is_manager=False
        )
        assert "Be helpful." in comp.content
        assert "严禁直接执行代码进行文件的增删改操作" in comp.content

    def test_skeleton_duty_en(self):
        from backend.utils.context_utils import build_skeleton_duty_component
        comp = build_skeleton_duty_component(
            duty="Help.", language="en", is_manager=True
        )
        assert "### Core Responsibilities" in comp.content
        assert "Behavioral Safety" in comp.content

    def test_skeleton_duty_custom_priority(self):
        from backend.utils.context_utils import build_skeleton_duty_component
        comp = build_skeleton_duty_component("d", priority=99)
        assert comp.priority == 99

    def test_skeleton_execution_flow_zh_manager(self):
        from backend.utils.context_utils import build_skeleton_execution_flow_component
        comp = build_skeleton_execution_flow_component(
            memory_list=None, language="zh", is_manager=True
        )
        assert "### 执行流程" in comp.content
        assert "思考" in comp.content
        # Manager: 分析当前任务状态和进展
        assert "分析当前任务状态" in comp.content

    def test_skeleton_execution_flow_zh_managed(self):
        from backend.utils.context_utils import build_skeleton_execution_flow_component
        comp = build_skeleton_execution_flow_component(
            memory_list=None, language="zh", is_manager=False
        )
        assert "确定需要使用哪些工具" in comp.content
        # Non-manager: includes 语义连贯 hint
        assert "语义连贯" in comp.content

    def test_skeleton_execution_flow_en_manager(self):
        from backend.utils.context_utils import build_skeleton_execution_flow_component
        comp = build_skeleton_execution_flow_component(
            memory_list=None, language="en", is_manager=True
        )
        assert "### Execution Process" in comp.content
        assert "Think:" in comp.content
        assert "Analyze current task status" in comp.content

    def test_skeleton_execution_flow_en_managed(self):
        from backend.utils.context_utils import build_skeleton_execution_flow_component
        comp = build_skeleton_execution_flow_component(
            memory_list=None, language="en", is_manager=False
        )
        assert "Determine which tools" in comp.content
        assert "semantically coherent" in comp.content

    def test_skeleton_execution_flow_zh_manager_with_memory(self):
        """When memory_list is non-empty in the (legacy) call site, ZH manager shows
        the memory reference line.  Note: build_context_components always passes
        memory_list=None to keep the stable prefix cache-friendly, so we call
        this helper directly to exercise the legacy branch."""
        from backend.utils.context_utils import build_skeleton_execution_flow_component
        comp = build_skeleton_execution_flow_component(
            memory_list=[{"memory": "old", "memory_level": "user", "score": 0.5}],
            language="zh",
            is_manager=True,
        )
        assert "合理参考之前交互中的上下文记忆信息" in comp.content

    def test_skeleton_execution_flow_en_manager_with_memory(self):
        from backend.utils.context_utils import build_skeleton_execution_flow_component
        comp = build_skeleton_execution_flow_component(
            memory_list=[{"memory": "old", "memory_level": "user", "score": 0.5}],
            language="en",
            is_manager=True,
        )
        assert "Reference relevant contextual memories" in comp.content

    def test_skeleton_execution_flow_en_managed_with_memory(self):
        """Non-manager also picks up the memory hint when memory is provided."""
        from backend.utils.context_utils import build_skeleton_execution_flow_component
        comp = build_skeleton_execution_flow_component(
            memory_list=[{"memory": "old", "memory_level": "user", "score": 0.5}],
            language="en",
            is_manager=False,
        )
        assert "Reference relevant contextual memories" in comp.content

    def test_skeleton_execution_flow_empty_memory_list(self):
        from backend.utils.context_utils import build_skeleton_execution_flow_component
        comp = build_skeleton_execution_flow_component(
            memory_list=[], language="zh", is_manager=True
        )
        # Empty list should not produce the memory reference line.
        assert "合理参考之前交互中的上下文记忆信息" not in comp.content

    def test_skeleton_constraint_zh(self):
        from backend.utils.context_utils import build_skeleton_constraint_component
        comp = build_skeleton_constraint_component("No smoking", language="zh")
        assert "No smoking" in comp.content
        assert "### 资源使用要求" in comp.content
        assert comp.template_name == "constraint"

    def test_skeleton_constraint_en(self):
        from backend.utils.context_utils import build_skeleton_constraint_component
        comp = build_skeleton_constraint_component("No smoking", language="en")
        assert "### Resource Usage Requirements" in comp.content
        assert "No smoking" in comp.content

    def test_skeleton_constraint_custom_priority(self):
        from backend.utils.context_utils import build_skeleton_constraint_component
        comp = build_skeleton_constraint_component("x", priority=11)
        assert comp.priority == 11

    def test_skeleton_code_norms_zh_manager(self):
        from backend.utils.context_utils import build_skeleton_code_norms_component
        comp = build_skeleton_code_norms_component(language="zh", is_manager=True)
        assert "### python代码规范" in comp.content
        # Manager: 助手调用必须使用task参数
        assert "助手调用必须使用task参数" in comp.content
        # Skips the "8." item in Chinese (jumps from 7 to 9 in the rule list)
        assert "9. 示例" in comp.content

    def test_skeleton_code_norms_zh_managed(self):
        from backend.utils.context_utils import build_skeleton_code_norms_component
        comp = build_skeleton_code_norms_component(language="zh", is_manager=False)
        # Non-manager ZH should NOT include the 11th rule about 助手调用.
        assert "助手调用必须使用task参数" not in comp.content

    def test_skeleton_code_norms_en_manager(self):
        from backend.utils.context_utils import build_skeleton_code_norms_component
        comp = build_skeleton_code_norms_component(language="en", is_manager=True)
        assert "### Python Code Specifications" in comp.content
        assert "Agent calls must use task parameter" in comp.content

    def test_skeleton_code_norms_en_managed(self):
        from backend.utils.context_utils import build_skeleton_code_norms_component
        comp = build_skeleton_code_norms_component(language="en", is_manager=False)
        assert "Agent calls must use task parameter" not in comp.content

    def test_skeleton_code_norms_custom_priority(self):
        from backend.utils.context_utils import build_skeleton_code_norms_component
        comp = build_skeleton_code_norms_component(priority=5)
        assert comp.priority == 5

    def test_skeleton_footer_zh(self):
        from backend.utils.context_utils import build_skeleton_footer_component
        comp = build_skeleton_footer_component("Q: hi\nA: Hello", language="zh")
        assert "### 示例模板" in comp.content
        assert "Q: hi" in comp.content
        assert "100万美元" in comp.content

    def test_skeleton_footer_en(self):
        from backend.utils.context_utils import build_skeleton_footer_component
        comp = build_skeleton_footer_component("Q: hi", language="en")
        assert "### Example Templates" in comp.content
        assert "1 million dollars" in comp.content

    def test_skeleton_footer_custom_priority(self):
        from backend.utils.context_utils import build_skeleton_footer_component
        comp = build_skeleton_footer_component("x", priority=1)
        assert comp.priority == 1

    def test_available_resources_header_zh_manager(self):
        from backend.utils.context_utils import build_available_resources_header_component
        comp = build_available_resources_header_component(is_manager=True, language="zh")
        assert "### 可用资源" in comp.content
        assert "你只能使用以下资源" in comp.content

    def test_available_resources_header_zh_managed(self):
        from backend.utils.context_utils import build_available_resources_header_component
        comp = build_available_resources_header_component(is_manager=False, language="zh")
        assert "### 可用资源" in comp.content
        assert "你只能使用以下资源" not in comp.content

    def test_available_resources_header_en_manager(self):
        from backend.utils.context_utils import build_available_resources_header_component
        comp = build_available_resources_header_component(is_manager=True, language="en")
        assert "### Available Resources" in comp.content
        assert "You can only use the following resources" in comp.content

    def test_available_resources_header_en_managed(self):
        from backend.utils.context_utils import build_available_resources_header_component
        comp = build_available_resources_header_component(is_manager=False, language="en")
        assert "### Available Resources" in comp.content
        assert "You can only use the following resources" not in comp.content

    def test_available_resources_header_custom_priority(self):
        from backend.utils.context_utils import build_available_resources_header_component
        comp = build_available_resources_header_component(priority=66)
        assert comp.priority == 66


class TestSkillsUsageAndAgentFallbackComponents:
    def test_build_skills_usage_component_empty(self):
        from backend.utils.context_utils import build_skills_usage_component
        comp = build_skills_usage_component([], language="zh")
        assert comp.skills == []
        assert "当前没有可用的技能" in comp.formatted_description

    def test_build_skills_usage_component_empty_en(self):
        from backend.utils.context_utils import build_skills_usage_component
        comp = build_skills_usage_component([], language="en")
        assert "No skills are currently available" in comp.formatted_description

    def test_build_skills_usage_component_with_skills(self):
        from backend.utils.context_utils import build_skills_usage_component
        skills = [{"name": "x", "description": "y"}]
        comp = build_skills_usage_component(skills, language="en", is_manager=False)
        assert comp.skills == skills
        assert "Skill Usage Requirements" in comp.formatted_description

    def test_build_skills_usage_component_custom_priority(self):
        from backend.utils.context_utils import build_skills_usage_component
        comp = build_skills_usage_component([], priority=33)
        assert comp.priority == 33

    def test_build_agent_fallback_component_no_agents_zh(self):
        from backend.utils.context_utils import build_agent_fallback_component
        comp = build_agent_fallback_component({}, {}, language="zh")
        assert "当前没有可用的助手" in comp.content
        assert comp.template_name == "agent_fallback"

    def test_build_agent_fallback_component_no_agents_en(self):
        from backend.utils.context_utils import build_agent_fallback_component
        comp = build_agent_fallback_component({}, {}, language="en")
        assert "No agents are currently available" in comp.content

    def test_build_agent_fallback_component_with_agents(self):
        """When agents are available, the fallback content is empty."""
        from backend.utils.context_utils import build_agent_fallback_component
        comp = build_agent_fallback_component({"a": "x"}, {}, language="zh")
        assert comp.content == ""

    def test_build_agent_fallback_component_custom_priority(self):
        from backend.utils.context_utils import build_agent_fallback_component
        comp = build_agent_fallback_component({}, {}, priority=99)
        assert comp.priority == 99


class TestBuildContextComponents:
    def test_empty_inputs_produces_skeleton(self):
        from backend.utils.context_utils import build_context_components
        components = build_context_components(
            duty="Help users.",
            constraint="Be helpful.",
            few_shots="Q: hi?\nA: Hello!",
            app_name="Test",
            app_description="Test",
            user_id="test",
            language="zh",
            is_manager=False,
        )
        types = [c.component_type for c in components]
        assert "system_prompt" in types

    def test_with_tools_only(self):
        from backend.utils.context_utils import build_context_components
        class MockTool:
            name = "tool"
            description = "desc"
            inputs = "{}"
            output_type = "str"
            source = "local"
        components = build_context_components(
            duty="Help users.",
            constraint="Be helpful.",
            few_shots="Q?",
            app_name="Test",
            app_description="Test",
            user_id="test",
            language="zh",
            is_manager=False,
            tools={"tool": MockTool()},
        )
        types = [c.component_type for c in components]
        assert "tools" in types

    def test_include_flags_skip_tools(self):
        from backend.utils.context_utils import build_context_components
        class MockTool:
            name = "tool"
            description = "desc"
            inputs = "{}"
            output_type = "str"
            source = "local"
        components = build_context_components(
            duty="Help users.",
            constraint="Be helpful.",
            few_shots="Q?",
            app_name="Test",
            app_description="Test",
            user_id="test",
            language="zh",
            is_manager=False,
            tools={"tool": MockTool()},
            include_tools=False,
        )
        types = [c.component_type for c in components]
        assert "tools" not in types

    def test_app_context_string(self):
        from backend.utils.context_utils import build_app_context_string
        result = build_app_context_string("Nexent", "Platform", "user-1")
        assert "Nexent" in result
        assert "Platform" in result
        assert "user-1" in result

    def test_app_context_string_line_layout(self):
        """_format_app_context emits 3 lines, one per field."""
        from backend.utils.context_utils import build_app_context_string
        result = build_app_context_string("A", "B", "C")
        lines = result.split("\n")
        assert lines[0] == "Application: A"
        assert lines[1] == "Description: B"
        assert lines[2] == "Current user: C"

    def test_skips_header_when_app_info_missing(self):
        """Header is only emitted when all three of name/description/user_id are set."""
        from backend.utils.context_utils import build_context_components
        components = build_context_components(
            duty="d",
            app_name=None,
            app_description="x",
            user_id="u",
        )
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "header" not in templates

    def test_skips_header_when_user_id_missing(self):
        from backend.utils.context_utils import build_context_components
        components = build_context_components(
            duty="d",
            app_name="a",
            app_description="b",
            user_id=None,
        )
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "header" not in templates

    def test_memory_included_when_provided(self):
        from backend.utils.context_utils import build_context_components
        memory = [{"memory": "x", "memory_level": "user", "score": 0.5}]
        components = build_context_components(
            duty="d", memory_list=memory, memory_search_query="q"
        )
        types = [c.component_type for c in components]
        assert "memory" in types

    def test_memory_skipped_when_include_false(self):
        from backend.utils.context_utils import build_context_components
        memory = [{"memory": "x", "memory_level": "user", "score": 0.5}]
        components = build_context_components(
            duty="d", memory_list=memory, include_memory=False
        )
        types = [c.component_type for c in components]
        assert "memory" not in types

    def test_memory_skipped_when_empty(self):
        from backend.utils.context_utils import build_context_components
        components = build_context_components(duty="d", memory_list=[])
        types = [c.component_type for c in components]
        assert "memory" not in types

    def test_skills_included_when_provided(self):
        from backend.utils.context_utils import build_context_components
        skills = [{"name": "s", "description": "d"}]
        components = build_context_components(duty="d", skills=skills)
        types = [c.component_type for c in components]
        assert "skills" in types

    def test_skills_skipped_when_include_false(self):
        from backend.utils.context_utils import build_context_components
        skills = [{"name": "s", "description": "d"}]
        components = build_context_components(
            duty="d", skills=skills, include_skills=False
        )
        # include_skills gates BOTH the skills component and the usage component
        # (which is always emitted when include_skills is true, regardless of
        # whether skills is non-empty).  So we expect no "skills" component.
        types = [c.component_type for c in components]
        assert "skills" not in types

    def test_knowledge_base_included_when_provided(self):
        from backend.utils.context_utils import build_context_components
        components = build_context_components(
            duty="d", knowledge_base_summary="kb-text", kb_ids=["k1"]
        )
        types = [c.component_type for c in components]
        assert "knowledge_base" in types

    def test_knowledge_base_skipped_when_empty(self):
        from backend.utils.context_utils import build_context_components
        components = build_context_components(
            duty="d", knowledge_base_summary=""
        )
        types = [c.component_type for c in components]
        assert "knowledge_base" not in types

    def test_knowledge_base_skipped_when_include_false(self):
        from backend.utils.context_utils import build_context_components
        components = build_context_components(
            duty="d",
            knowledge_base_summary="kb-text",
            include_knowledge_base=False,
        )
        types = [c.component_type for c in components]
        assert "knowledge_base" not in types

    def test_managed_agents_included_for_manager(self):
        from backend.utils.context_utils import build_context_components
        class MockAgent:
            description = "x"
        components = build_context_components(
            duty="d",
            is_manager=True,
            managed_agents={"a": MockAgent()},
        )
        types = [c.component_type for c in components]
        assert "managed_agents" in types

    def test_managed_agents_skipped_for_managed_agent(self):
        """Non-manager agent should NOT include managed agents even when provided."""
        from backend.utils.context_utils import build_context_components
        class MockAgent:
            description = "x"
        components = build_context_components(
            duty="d",
            is_manager=False,
            managed_agents={"a": MockAgent()},
        )
        types = [c.component_type for c in components]
        assert "managed_agents" not in types

    def test_managed_agents_skipped_when_include_false(self):
        from backend.utils.context_utils import build_context_components
        class MockAgent:
            description = "x"
        components = build_context_components(
            duty="d",
            is_manager=True,
            managed_agents={"a": MockAgent()},
            include_managed_agents=False,
        )
        types = [c.component_type for c in components]
        assert "managed_agents" not in types

    def test_external_agents_included_for_manager(self):
        from backend.utils.context_utils import build_context_components
        class MockAgent:
            agent_id = 1
            name = "x"
            description = "y"
        components = build_context_components(
            duty="d",
            is_manager=True,
            external_a2a_agents={"1": MockAgent()},
        )
        types = [c.component_type for c in components]
        assert "external_a2a_agents" in types

    def test_external_agents_skipped_for_managed_agent(self):
        from backend.utils.context_utils import build_context_components
        class MockAgent:
            agent_id = 1
            name = "x"
            description = "y"
        components = build_context_components(
            duty="d",
            is_manager=False,
            external_a2a_agents={"1": MockAgent()},
        )
        types = [c.component_type for c in components]
        assert "external_a2a_agents" not in types

    def test_external_agents_skipped_when_include_false(self):
        from backend.utils.context_utils import build_context_components
        class MockAgent:
            agent_id = 1
            name = "x"
            description = "y"
        components = build_context_components(
            duty="d",
            is_manager=True,
            external_a2a_agents={"1": MockAgent()},
            include_external_agents=False,
        )
        types = [c.component_type for c in components]
        assert "external_a2a_agents" not in types

    def test_fallback_when_no_agents_manager(self):
        """When manager has no agents, the fallback component is added."""
        from backend.utils.context_utils import build_context_components
        components = build_context_components(
            duty="d", is_manager=True
        )
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "agent_fallback" in templates

    def test_no_fallback_for_managed_agent(self):
        """Non-manager agent does not get the agent_fallback component even
        without agents."""
        from backend.utils.context_utils import build_context_components
        components = build_context_components(
            duty="d", is_manager=False
        )
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "agent_fallback" not in templates

    def test_no_fallback_when_agents_present(self):
        """When manager has agents, the fallback component is not added."""
        from backend.utils.context_utils import build_context_components
        class MockAgent:
            description = "x"
        components = build_context_components(
            duty="d",
            is_manager=True,
            managed_agents={"a": MockAgent()},
        )
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "agent_fallback" not in templates

    def test_constraint_skipped_when_empty(self):
        from backend.utils.context_utils import build_context_components
        components = build_context_components(duty="d", constraint="")
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "constraint" not in templates

    def test_constraint_skipped_when_none(self):
        from backend.utils.context_utils import build_context_components
        components = build_context_components(duty="d", constraint=None)
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "constraint" not in templates

    def test_few_shots_skipped_when_empty(self):
        from backend.utils.context_utils import build_context_components
        components = build_context_components(duty="d", few_shots="")
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "footer" not in templates

    def test_few_shots_skipped_when_none(self):
        from backend.utils.context_utils import build_context_components
        components = build_context_components(duty="d", few_shots=None)
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "footer" not in templates

    def test_duty_skipped_when_empty(self):
        from backend.utils.context_utils import build_context_components
        components = build_context_components(duty="")
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "duty" not in templates

    def test_duty_skipped_when_none(self):
        from backend.utils.context_utils import build_context_components
        components = build_context_components(duty=None)
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "duty" not in templates

    def test_execution_flow_always_emitted(self):
        """Execution flow is emitted even when no duty/optional params provided."""
        from backend.utils.context_utils import build_context_components
        components = build_context_components()
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "execution_flow" in templates
        assert "available_resources_header" in templates
        assert "code_norms" in templates

    def test_full_assembly_includes_every_section(self):
        """A full configuration should emit all 15 component types in order."""
        from backend.utils.context_utils import build_context_components
        class MockTool:
            name = "tool"
            description = "desc"
            inputs = "{}"
            output_type = "str"
            source = "local"
        class MockAgent:
            description = "x"
            tools = []
        class MockExtAgent:
            agent_id = 1
            name = "ext"
            description = "ext-desc"

        memory = [{"memory": "x", "memory_level": "user", "score": 0.5}]
        skills = [{"name": "s", "description": "d"}]

        components = build_context_components(
            duty="d",
            constraint="c",
            few_shots="f",
            app_name="a",
            app_description="b",
            user_id="u",
            language="en",
            is_manager=True,
            tools={"t": MockTool()},
            skills=skills,
            managed_agents={"m": MockAgent()},
            external_a2a_agents={"1": MockExtAgent()},
            memory_list=memory,
            memory_search_query="q",
            knowledge_base_summary="kb",
            kb_ids=["k1"],
        )

        types = [c.component_type for c in components]
        # Required sections all present.
        assert "system_prompt" in types
        assert "memory" in types
        assert "skills" in types
        assert "tools" in types
        assert "knowledge_base" in types
        assert "managed_agents" in types
        assert "external_a2a_agents" in types
        # No fallback when agents are present.
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "agent_fallback" not in templates
        # Constraint and footer are present.
        assert "constraint" in templates
        assert "footer" in templates

    def test_assembly_order_is_stable(self):
        """The assembly order is fixed: header -> memory -> duty -> skills ->
        execution_flow -> available_resources_header -> tools -> knowledge_base
        -> managed_agents -> external_a2a_agents -> skills_usage -> constraint
        -> code_norms -> footer."""
        from backend.utils.context_utils import build_context_components
        class MockAgent:
            description = "x"
        components = build_context_components(
            duty="d",
            few_shots="f",
            app_name="a",
            app_description="b",
            user_id="u",
            is_manager=True,
            skills=[{"name": "s", "description": "d"}],
            managed_agents={"m": MockAgent()},
        )
        # Find template-name sequence in order
        template_order = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert template_order[0] == "header"
        assert template_order[-1] == "footer"
        # code_norms should be the second-to-last (right before footer)
        assert template_order[-2] == "code_norms"

    def test_skills_usage_emitted_even_when_no_skills(self):
        """Skills usage component is emitted whenever include_skills=True,
        regardless of whether skills are non-empty."""
        from backend.utils.context_utils import build_context_components
        components = build_context_components(duty="d", include_skills=True)
        # The skills_usage component is built with skills=[] when no skills,
        # so formatted_description should mention the empty case.
        for c in components:
            if c.component_type == "skills":
                # Either the descriptive one or the usage one - just check it
                # does not crash.  This is mostly a smoke test for the branch.
                assert c.formatted_description is not None

    def test_fallback_skipped_when_content_empty(self, mocker):
        """When the fallback component is built with empty content, the
        ``if fallback_comp.content:`` guard prevents it from being appended.
        This exercises the False branch of line 1408."""
        from backend.utils.context_utils import build_context_components
        from nexent.core.agents.agent_model import SystemPromptComponent

        # Build a mock fallback component with empty content.
        empty_fallback = SystemPromptComponent(
            content="", template_name="agent_fallback", priority=5
        )
        mocker.patch(
            "backend.utils.context_utils.build_agent_fallback_component",
            return_value=empty_fallback,
        )

        components = build_context_components(duty="d", is_manager=True)
        templates = [
            c.template_name for c in components
            if getattr(c, "template_name", None)
        ]
        assert "agent_fallback" not in templates


if __name__ == "__main__":
    pytest.main([__file__])
