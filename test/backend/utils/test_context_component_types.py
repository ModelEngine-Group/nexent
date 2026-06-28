import sys
from pathlib import Path
from unittest.mock import MagicMock

TEST_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TEST_ROOT.parent

for _path in (str(PROJECT_ROOT), str(TEST_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

_sdk_dir = str(PROJECT_ROOT / "sdk")
if _sdk_dir not in sys.path:
    sys.path.insert(0, _sdk_dir)

_mem0_stubs = {
    "mem0": MagicMock(),
    "mem0.memory": MagicMock(),
    "mem0.memory.main": MagicMock(),
    "mem0.embeddings": MagicMock(),
    "mem0.embeddings.base": MagicMock(),
    "mem0.configs": MagicMock(),
    "mem0.configs.embeddings": MagicMock(),
    "mem0.configs.embeddings.base": MagicMock(),
    "smolagents": MagicMock(),
    "smolagents.memory": MagicMock(),
    "smolagents.agents": MagicMock(),
    "smolagents.tools": MagicMock(),
    "smolagents.models": MagicMock(),
    "smolagents.local_python_executor": MagicMock(),
    "smolagents.utils": MagicMock(),
    "smolagents.monitoring": MagicMock(),
    "openai": MagicMock(),
    "openai.types": MagicMock(),
    "openai.types.chat": MagicMock(),
    "openai.types.chat.chat_completion_message": MagicMock(),
    "openai.types.chat.chat_completion": MagicMock(),
    "openai.types.chat.completion_create_params": MagicMock(),
    "tiktoken": MagicMock(),
    "tiktoken.encoding_for_model": MagicMock(),
    "websockets": MagicMock(),
    "websockets.client": MagicMock(),
    "websockets.server": MagicMock(),
    "dashscope": MagicMock(),
    "dashscope.audio": MagicMock(),
    "dashscope.audio.asr": MagicMock(),
    "requests": MagicMock(),
    "requests.exceptions": MagicMock(),
    "boto3": MagicMock(),
    "boto3.exceptions": MagicMock(),
    "botocore": MagicMock(),
    "botocore.exceptions": MagicMock(),
    "botocore.client": MagicMock(),
    "minio": MagicMock(),
    "minio.error": MagicMock(),
    "docker": MagicMock(),
    "docker.errors": MagicMock(),
    "docker.types": MagicMock(),
    "fastmcp": MagicMock(),
    "fastmcp.client": MagicMock(),
    "fastmcp.client.transports": MagicMock(),
    "kubernetes": MagicMock(),
    "kubernetes.client": MagicMock(),
    "kubernetes.config": MagicMock(),
    "rich": MagicMock(),
    "rich.console": MagicMock(),
    "rich.markdown": MagicMock(),
    "rich.panel": MagicMock(),
    "rich.text": MagicMock(),
}
for _mod, _mock in _mem0_stubs.items():
    if _mod not in sys.modules:
        sys.modules[_mod] = _mock

_nexent_sub_stubs = {
    "nexent.memory": MagicMock(),
    "nexent.memory.memory_core": MagicMock(),
    "nexent.memory.memory_service": MagicMock(),
    "nexent.memory.embedder_adaptor": MagicMock(),
    "nexent.datamate": MagicMock(),
    "nexent.datamate.datamate_client": MagicMock(),
    "nexent.storage": MagicMock(),
    "nexent.storage.storage_client_factory": MagicMock(),
    "nexent.storage.minio": MagicMock(),
    "nexent.storage.local": MagicMock(),
    "nexent.container": MagicMock(),
    "nexent.container.container_client_factory": MagicMock(),
    "nexent.container.docker_client": MagicMock(),
    "nexent.container.k8s_client": MagicMock(),
    "nexent.core.models": MagicMock(),
    "nexent.core.models.openai_llm": MagicMock(),
    "nexent.core.models.openai_long_context_model": MagicMock(),
    "nexent.core.models.embedding_model": MagicMock(),
    "nexent.core.models.ali_stt_model": MagicMock(),
    "nexent.core.agents.core_agent": MagicMock(),
    "nexent.core.agents.agent_context": MagicMock(),
    "nexent.core.agents.summary_cache": MagicMock(),
    "nexent.core.agents.summary_config": MagicMock(),
    "nexent.skills": MagicMock(),
    "nexent.skills.skill_loader": MagicMock(),
}
for _mod, _mock in _nexent_sub_stubs.items():
    if _mod not in sys.modules:
        sys.modules[_mod] = _mock

import pytest


class _MockTool:
    name = "tool1"
    description = "Test tool"
    inputs = "{}"
    output_type = "str"
    source = "local"


class _MockManagedAgent:
    name = "agent1"
    description = "Test agent"


class _MockExternalAgent:
    agent_id = "ext-1"
    name = "External"
    description = "External agent"


def _base_kwargs(**overrides):
    base = dict(
        duty="Help users.",
        app_name="Test",
        app_description="Desc",
        user_id="u1",
    )
    base.update(overrides)
    return base


def _full_kwargs(**overrides):
    base = dict(
        duty="Help users.",
        constraint="Be helpful.",
        few_shots="Q: hi? A: Hello!",
        app_name="Test",
        app_description="Desc",
        user_id="u1",
        is_manager=True,
        tools={"tool1": _MockTool()},
        skills=[{"name": "s1", "description": "d1"}],
        managed_agents={"agent1": _MockManagedAgent()},
        external_a2a_agents={"ext-1": _MockExternalAgent()},
        memory_list=[{"memory": "test", "score": 0.9, "memory_level": "user"}],
        knowledge_base_summary="KB text",
        kb_ids=["kb-1"],
    )
    base.update(overrides)
    return base


class TestBuilderReturnTypes:
    def test_build_skeleton_header_returns_system_prompt(self):
        from backend.utils.context_utils import build_skeleton_header_component
        from nexent.core.agents.agent_model import SystemPromptComponent

        comp = build_skeleton_header_component(
            app_name="Test",
            app_description="Desc",
            user_id="u1",
        )
        assert isinstance(comp, SystemPromptComponent)
        assert comp.component_type == "system_prompt"

    def test_build_skeleton_duty_returns_system_prompt(self):
        from backend.utils.context_utils import build_skeleton_duty_component
        from nexent.core.agents.agent_model import SystemPromptComponent

        comp = build_skeleton_duty_component(duty="Help users.")
        assert isinstance(comp, SystemPromptComponent)
        assert comp.component_type == "system_prompt"

    def test_build_skeleton_execution_flow_returns_system_prompt(self):
        from backend.utils.context_utils import build_skeleton_execution_flow_component
        from nexent.core.agents.agent_model import SystemPromptComponent

        comp = build_skeleton_execution_flow_component()
        assert isinstance(comp, SystemPromptComponent)
        assert comp.component_type == "system_prompt"

    def test_build_skeleton_constraint_returns_system_prompt(self):
        from backend.utils.context_utils import build_skeleton_constraint_component
        from nexent.core.agents.agent_model import SystemPromptComponent

        comp = build_skeleton_constraint_component(constraint="Be helpful.")
        assert isinstance(comp, SystemPromptComponent)
        assert comp.component_type == "system_prompt"

    def test_build_skeleton_code_norms_returns_system_prompt(self):
        from backend.utils.context_utils import build_skeleton_code_norms_component
        from nexent.core.agents.agent_model import SystemPromptComponent

        comp = build_skeleton_code_norms_component()
        assert isinstance(comp, SystemPromptComponent)
        assert comp.component_type == "system_prompt"

    def test_build_skeleton_footer_returns_system_prompt(self):
        from backend.utils.context_utils import build_skeleton_footer_component
        from nexent.core.agents.agent_model import SystemPromptComponent

        comp = build_skeleton_footer_component(few_shots="Q: hi? A: Hello!")
        assert isinstance(comp, SystemPromptComponent)
        assert comp.component_type == "system_prompt"

    def test_build_tools_returns_tools_component(self):
        from backend.utils.context_utils import build_tools_component
        from nexent.core.agents.agent_model import ToolsComponent

        comp = build_tools_component(tools={})
        assert isinstance(comp, ToolsComponent)
        assert comp.component_type == "tools"

    def test_build_skills_returns_skills_component(self):
        from backend.utils.context_utils import build_skills_component
        from nexent.core.agents.agent_model import SkillsComponent

        comp = build_skills_component(
            skills=[{"name": "test", "description": "desc"}]
        )
        assert isinstance(comp, SkillsComponent)
        assert comp.component_type == "skills"

    def test_build_memory_returns_memory_component(self):
        from backend.utils.context_utils import build_memory_component
        from nexent.core.agents.agent_model import MemoryComponent

        comp = build_memory_component(
            memory_list=[{"memory": "test", "score": 0.9, "memory_level": "user"}]
        )
        assert isinstance(comp, MemoryComponent)
        assert comp.component_type == "memory"

    def test_build_knowledge_base_returns_kb_component(self):
        from backend.utils.context_utils import build_knowledge_base_component
        from nexent.core.agents.agent_model import KnowledgeBaseComponent

        comp = build_knowledge_base_component(
            knowledge_base_summary="KB text", kb_ids=["kb-1"]
        )
        assert isinstance(comp, KnowledgeBaseComponent)
        assert comp.component_type == "knowledge_base"

    def test_build_managed_agents_returns_managed_component(self):
        from backend.utils.context_utils import build_managed_agents_component
        from nexent.core.agents.agent_model import ManagedAgentsComponent

        comp = build_managed_agents_component(managed_agents={})
        assert isinstance(comp, ManagedAgentsComponent)
        assert comp.component_type == "managed_agents"

    def test_build_external_agents_returns_external_component(self):
        from backend.utils.context_utils import build_external_agents_component
        from nexent.core.agents.agent_model import ExternalAgentsComponent

        comp = build_external_agents_component(external_a2a_agents={})
        assert isinstance(comp, ExternalAgentsComponent)
        assert comp.component_type == "external_a2a_agents"

    def test_build_skills_usage_returns_skills_component(self):
        from backend.utils.context_utils import build_skills_usage_component
        from nexent.core.agents.agent_model import SkillsComponent

        comp = build_skills_usage_component(
            skills=[{"name": "test", "description": "desc"}]
        )
        assert isinstance(comp, SkillsComponent)
        assert comp.component_type == "skills"

    def test_build_agent_fallback_returns_system_prompt(self):
        from backend.utils.context_utils import build_agent_fallback_component
        from nexent.core.agents.agent_model import SystemPromptComponent

        comp = build_agent_fallback_component(
            managed_agents={}, external_a2a_agents={}
        )
        assert isinstance(comp, SystemPromptComponent)
        assert comp.component_type == "system_prompt"

    def test_build_available_resources_header_returns_system_prompt(self):
        from backend.utils.context_utils import build_available_resources_header_component
        from nexent.core.agents.agent_model import SystemPromptComponent

        comp = build_available_resources_header_component()
        assert isinstance(comp, SystemPromptComponent)
        assert comp.component_type == "system_prompt"

    def test_execution_flow_managed_text(self):
        from backend.utils.context_utils import build_skeleton_execution_flow_component

        comp = build_skeleton_execution_flow_component(is_manager=False, language="zh")
        assert "确定需要使用哪些工具" in comp.content
        assert "注意最后生成的回答要语义连贯" in comp.content

    def test_execution_flow_manager_text(self):
        from backend.utils.context_utils import build_skeleton_execution_flow_component

        comp = build_skeleton_execution_flow_component(is_manager=True, language="zh")
        assert "分析当前任务状态和进展" in comp.content
        assert "分配给助手" in comp.content

    def test_duty_managed_zh(self):
        from backend.utils.context_utils import build_skeleton_duty_component

        comp = build_skeleton_duty_component(duty="test", is_manager=False, language="zh")
        assert "严禁直接执行代码" in comp.content

    def test_duty_manager_zh(self):
        from backend.utils.context_utils import build_skeleton_duty_component

        comp = build_skeleton_duty_component(duty="test", is_manager=True, language="zh")
        assert "文件操作必须使用平台提供的专用工具" in comp.content

    def test_kb_not_duplicated_in_tools(self):
        from backend.utils.context_utils import build_tools_component

        class MockTool:
            name = "t"
            description = "Test tool"
            inputs = "{}"
            output_type = "str"
            source = "local"

        comp = build_tools_component(
            tools={"t": MockTool()},
            knowledge_base_summary="KB text",
        )
        assert "KB text" not in comp.formatted_description

    def test_available_resources_header_manager(self):
        from backend.utils.context_utils import build_available_resources_header_component

        comp = build_available_resources_header_component(is_manager=True, language="zh")
        assert "你只能使用以下资源" in comp.content

    def test_available_resources_header_managed(self):
        from backend.utils.context_utils import build_available_resources_header_component

        comp = build_available_resources_header_component(is_manager=False, language="zh")
        assert comp.content == "### 可用资源"


class TestBuildContextComponentsAssembly:
    def test_knowledge_base_included_when_flag_true_and_summary_exists(self):
        from backend.utils.context_utils import build_context_components

        components = build_context_components(
            **_base_kwargs(
                include_knowledge_base=True,
                knowledge_base_summary="KB text",
                kb_ids=["kb-1"],
            ),
        )
        types = [c.component_type for c in components]
        assert "knowledge_base" in types

    def test_knowledge_base_excluded_when_flag_false(self):
        from backend.utils.context_utils import build_context_components

        components = build_context_components(
            **_base_kwargs(
                include_knowledge_base=False,
                knowledge_base_summary="KB text",
                kb_ids=["kb-1"],
            ),
        )
        types = [c.component_type for c in components]
        assert "knowledge_base" not in types

    def test_knowledge_base_excluded_when_summary_empty(self):
        from backend.utils.context_utils import build_context_components

        components = build_context_components(
            **_base_kwargs(
                include_knowledge_base=True,
                knowledge_base_summary="",
                kb_ids=["kb-1"],
            ),
        )
        types = [c.component_type for c in components]
        assert "knowledge_base" not in types

    def test_skills_usage_has_skills_type(self):
        from backend.utils.context_utils import build_context_components

        components = build_context_components(
            **_base_kwargs(skills=[{"name": "s1", "description": "d1"}]),
        )
        skills_components = [c for c in components if c.component_type == "skills"]
        assert len(skills_components) >= 1
        skills_usage = [
            c
            for c in skills_components
            if hasattr(c, "skills") and c.skills == [{"name": "s1", "description": "d1"}]
        ]
        assert len(skills_usage) >= 1
        assert skills_usage[0].component_type == "skills"

    def test_all_component_types_present_with_full_inputs(self):
        from backend.utils.context_utils import build_context_components

        components = build_context_components(**_full_kwargs())
        types = [c.component_type for c in components]
        assert "system_prompt" in types
        assert "memory" in types
        assert "skills" in types
        assert "tools" in types
        assert "managed_agents" in types
        assert "external_a2a_agents" in types

    def test_component_order_preserved(self):
        from backend.utils.context_utils import build_context_components

        components = build_context_components(**_full_kwargs())
        types = [c.component_type for c in components]
        expected_order = [
            "system_prompt",
            "memory",
            "system_prompt",
            "skills",
            "system_prompt",
            "system_prompt",
            "tools",
            "knowledge_base",
            "managed_agents",
            "external_a2a_agents",
            "skills",
            "system_prompt",
            "system_prompt",
            "system_prompt",
        ]
        assert types == expected_order

    def test_kb_ids_passed_through(self):
        from backend.utils.context_utils import build_context_components
        from nexent.core.agents.agent_model import KnowledgeBaseComponent

        components = build_context_components(
            **_base_kwargs(
                kb_ids=["kb-1", "kb-2"],
                knowledge_base_summary="text",
            ),
        )
        kb_components = [
            c for c in components if isinstance(c, KnowledgeBaseComponent)
        ]
        assert len(kb_components) >= 1
        assert kb_components[0].kb_ids == ["kb-1", "kb-2"]


class TestComponentToMessages:
    def test_skills_component_to_messages(self):
        from nexent.core.agents.agent_model import SkillsComponent

        comp = SkillsComponent(
            skills=[{"name": "test", "description": "desc"}],
            formatted_description="test desc",
        )
        messages = comp.to_messages()
        assert messages == [{"role": "system", "content": "test desc"}]

    def test_knowledge_base_component_to_messages(self):
        from nexent.core.agents.agent_model import KnowledgeBaseComponent

        comp = KnowledgeBaseComponent(summary="KB summary")
        messages = comp.to_messages()
        assert messages == [{"role": "user", "content": "KB summary"}]

    def test_knowledge_base_component_empty_summary_no_messages(self):
        from nexent.core.agents.agent_model import KnowledgeBaseComponent

        comp = KnowledgeBaseComponent(summary="")
        messages = comp.to_messages()
        assert messages == []

    def test_memory_component_to_messages(self):
        from nexent.core.agents.agent_model import MemoryComponent

        comp = MemoryComponent(formatted_content="memory text")
        messages = comp.to_messages()
        assert messages == [{"role": "user", "content": "memory text"}]

    def test_tools_component_to_messages(self):
        from nexent.core.agents.agent_model import ToolsComponent

        comp = ToolsComponent(formatted_description="tools text")
        messages = comp.to_messages()
        assert messages == [{"role": "system", "content": "tools text"}]


class TestFullPromptAssembly:
    def test_full_assembly_produces_system_messages(self):
        from backend.utils.context_utils import build_context_components

        components = build_context_components(**_full_kwargs())
        all_messages = []
        for comp in components:
            all_messages.extend(comp.to_messages())
        assert len(all_messages) > 0
        for msg in all_messages:
            assert msg["role"] in {"system", "user"}
            assert msg["content"]

    def test_full_assembly_contains_key_sections(self):
        from backend.utils.context_utils import build_context_components

        kw = _full_kwargs()
        for k in ("tools", "skills", "managed_agents", "external_a2a_agents",
                   "memory_list", "knowledge_base_summary", "kb_ids"):
            kw.pop(k, None)
        components = build_context_components(**kw)
        all_messages = []
        for comp in components:
            all_messages.extend(comp.to_messages())
        combined = "\n".join(msg["content"] for msg in all_messages)
        assert "\u57fa\u672c\u4fe1\u606f" in combined or "Basic Information" in combined
        assert "\u6838\u5fc3\u804c\u8d23" in combined or "Core Responsibilities" in combined
        assert "\u6267\u884c\u6d41\u7a0b" in combined or "Execution Process" in combined
        assert "python\u4ee3\u7801\u89c4\u8303" in combined or "Python Code Specifications" in combined
        assert "\u53ef\u7528\u8d44\u6e90" in combined or "Available Resources" in combined

    def test_english_language_produces_english_content(self):
        from backend.utils.context_utils import build_context_components

        kw = _full_kwargs(language="en")
        for k in ("tools", "skills", "managed_agents", "external_a2a_agents",
                   "memory_list", "knowledge_base_summary", "kb_ids"):
            kw.pop(k, None)
        components = build_context_components(**kw)
        all_messages = []
        for comp in components:
            all_messages.extend(comp.to_messages())
        combined = "\n".join(msg["content"] for msg in all_messages)
        assert "Basic Information" in combined
        assert "Core Responsibilities" in combined
        assert "Execution Process" in combined

    def test_component_count_matches_expected(self):
        from backend.utils.context_utils import build_context_components

        components = build_context_components(**_full_kwargs())
        assert len(components) == 14


if __name__ == "__main__":
    pytest.main([__file__])
