"""Tests for ContextItem projection integration in ContextManager.

Verifies that when use_context_items=True, ContextManager correctly:
1. Projects ContextComponent instances into ContextItem candidates
2. Converts ContextItems back to messages for the assembly pipeline
3. Includes projected items in ContextEvidence
4. Maintains backward compatibility when use_context_items=False
"""

import pytest
from unittest.mock import MagicMock

from nexent.core.agents.agent_context import ContextManager
from nexent.core.agents.agent_model import (
    ExternalAgentsComponent,
    KnowledgeBaseComponent,
    ManagedAgentsComponent,
    MemoryComponent,
    SkillsComponent,
    SystemPromptComponent,
    ToolsComponent,
)
from nexent.core.agents.summary_config import ContextManagerConfig
from nexent.core.agents.context.context_item import AuthorityTier, ContextItemType
from nexent.core.agents.context.handlers import register_all


@pytest.fixture(autouse=True)
def ensure_handlers_registered():
    """Ensure all handlers are registered before each test."""
    register_all()


class TestContextItemProjectionDisabled:
    """Verify backward compatibility when use_context_items=False (default)."""

    def test_default_config_has_use_context_items_false(self):
        """ContextManagerConfig defaults to use_context_items=False."""
        config = ContextManagerConfig(enabled=True, token_threshold=10000)
        assert config.use_context_items is False

    def test_assemble_final_context_without_projection(self):
        """When use_context_items=False, context_items in evidence is empty."""
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=False,
        )
        manager = ContextManager(config=config)

        manager.register_component(SystemPromptComponent(content="You are helpful"))
        manager.register_component(
            ToolsComponent(
                tools=[{"name": "search", "description": "Search the web"}],
                formatted_description="Available tools: search",
            )
        )

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        final = manager.assemble_final_context(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        assert final.evidence.context_items == ()
        assert len(final.messages) > 0


class TestContextItemProjectionEnabled:
    """Verify ContextItem projection when use_context_items=True."""

    def test_config_accepts_use_context_items_true(self):
        """ContextManagerConfig can be initialized with use_context_items=True."""
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        assert config.use_context_items is True

    def test_project_context_items_returns_list(self):
        """project_context_items() returns a list of ContextItem objects."""
        config = ContextManagerConfig(enabled=True, token_threshold=10000)
        manager = ContextManager(config=config)

        manager.register_component(SystemPromptComponent(content="System prompt"))
        manager.register_component(
            ToolsComponent(
                tools=[
                    {"name": "tool1", "description": "First tool"},
                    {"name": "tool2", "description": "Second tool"},
                ],
                formatted_description="Tools: tool1, tool2",
            )
        )

        items = manager.project_context_items()

        assert isinstance(items, list)
        assert len(items) == 3
        assert items[0].item_type == ContextItemType.SYSTEM_PROMPT
        assert items[1].item_type == ContextItemType.TOOL
        assert items[2].item_type == ContextItemType.TOOL

    def test_assemble_final_context_with_projection_includes_context_items(self):
        """When use_context_items=True, evidence.context_items contains projected items."""
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        manager.register_component(SystemPromptComponent(content="Be helpful"))
        manager.register_component(
            MemoryComponent(
                memories=[{"content": "User prefers Python", "memory_type": "user"}],
                formatted_content="User preferences: Python",
            )
        )

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        final = manager.assemble_final_context(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        assert len(final.evidence.context_items) > 0
        item_types = {item.item_type for item in final.evidence.context_items}
        assert ContextItemType.SYSTEM_PROMPT in item_types
        assert ContextItemType.MEMORY in item_types

    def test_projection_preserves_message_roles(self):
        """Projected items are converted to messages with correct roles."""
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        manager.register_component(SystemPromptComponent(content="System instruction"))
        manager.register_component(
            MemoryComponent(
                memories=[{"content": "Retrieved fact", "memory_type": "user"}],
                formatted_content="Memory: Retrieved fact",
            )
        )
        manager.register_component(
            KnowledgeBaseComponent(
                summary="KB summary",
                kb_ids=["kb1"],
            )
        )

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        final = manager.assemble_final_context(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        roles = [msg["role"] for msg in final.messages]

        assert "system" in roles
        assert "user" in roles

    def test_projection_uses_formatted_description(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        tool_dict = {"name": "calculator", "description": "Performs math"}
        manager.register_component(
            ToolsComponent(
                tools=[tool_dict],
                formatted_description="Calculator tool",
            )
        )

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        final = manager.assemble_final_context(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        assert len(final.messages) > 0
        tool_msg = None
        for msg in final.messages:
            if msg["role"] == "system":
                content = msg["content"]
                if isinstance(content, list) and len(content) > 0:
                    text = content[0].get("text", "")
                    if "Calculator tool" in text:
                        tool_msg = msg
                        break

        assert tool_msg is not None
        assert "Calculator tool" in tool_msg["content"][0]["text"]

    def test_projection_maintains_stable_dynamic_partition(self):
        """Projected items are correctly partitioned into stable/dynamic."""
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        manager.register_component(SystemPromptComponent(content="Stable system prompt"))
        manager.register_component(
            MemoryComponent(
                memories=[{"content": "Dynamic memory", "memory_type": "user"}],
                formatted_content="Dynamic memory content",
            )
        )

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        final = manager.assemble_final_context(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        assert final.evidence.stable_message_count > 0
        assert final.evidence.dynamic_message_count > 0

    def test_empty_components_returns_empty_projection(self):
        """When no components are registered, projection returns empty list."""
        config = ContextManagerConfig(enabled=True, token_threshold=10000)
        manager = ContextManager(config=config)

        items = manager.project_context_items()
        assert items == []


class TestContextItemProjectionEdgeCases:
    """Edge cases and error handling for ContextItem projection."""

    def test_projection_with_none_content_items(self):
        """Items with None content are skipped during message conversion."""
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        manager.register_component(SystemPromptComponent(content=""))

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        final = manager.assemble_final_context(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        assert final is not None
        assert final.evidence.context_items is not None

    def test_projection_with_multiple_tools(self):
        """Multiple tools are projected as separate ContextItems."""
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        tools = [
            {"name": "tool1", "description": "First"},
            {"name": "tool2", "description": "Second"},
            {"name": "tool3", "description": "Third"},
        ]
        manager.register_component(
            ToolsComponent(tools=tools, formatted_description="Three tools")
        )

        items = manager.project_context_items()

        tool_items = [item for item in items if item.item_type == ContextItemType.TOOL]
        assert len(tool_items) == 3
        assert tool_items[0].item_id != tool_items[1].item_id
        assert tool_items[1].item_id != tool_items[2].item_id

    def test_projection_preserves_authority_tiers(self):
        """Different component types have correct authority tiers."""
        config = ContextManagerConfig(enabled=True, token_threshold=10000)
        manager = ContextManager(config=config)

        manager.register_component(SystemPromptComponent(content="System"))
        manager.register_component(
            MemoryComponent(
                memories=[{"content": "Memory", "memory_type": "user"}],
                formatted_content="Memory",
            )
        )
        manager.register_component(
            KnowledgeBaseComponent(summary="KB", kb_ids=["kb1"])
        )

        items = manager.project_context_items()

        system_item = next(
            item for item in items if item.item_type == ContextItemType.SYSTEM_PROMPT
        )
        assert system_item.authority_tier == AuthorityTier.PLATFORM

        memory_item = next(
            item for item in items if item.item_type == ContextItemType.MEMORY
        )
        assert memory_item.authority_tier == AuthorityTier.RETRIEVED_MEMORY

        kb_item = next(
            item for item in items if item.item_type == ContextItemType.KNOWLEDGE_BASE
        )
        assert kb_item.authority_tier == AuthorityTier.RETRIEVED_MEMORY

    def test_projection_handles_skills_component(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        manager.register_component(
            SkillsComponent(
                skills=[{"name": "skill1", "description": "First skill"}],
                formatted_description="Available skills: skill1",
            )
        )

        items = manager.project_context_items()
        assert len(items) == 1
        assert items[0].item_type == ContextItemType.SKILL
        assert items[0].authority_tier == AuthorityTier.PLATFORM

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        final = manager.assemble_final_context(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        skill_msg = None
        for msg in final.messages:
            if msg["role"] == "system":
                content = msg["content"]
                if isinstance(content, list) and len(content) > 0:
                    text = content[0].get("text", "")
                    if "Available skills" in text:
                        skill_msg = msg
                        break

        assert skill_msg is not None

    def test_projection_handles_managed_agents_component(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        manager.register_component(
            ManagedAgentsComponent(
                agents=[{"name": "agent1", "description": "First agent"}],
                formatted_description="Managed agents: agent1",
            )
        )

        items = manager.project_context_items()
        assert len(items) == 1
        assert items[0].item_type == ContextItemType.MANAGED_AGENT
        assert items[0].authority_tier == AuthorityTier.PLATFORM

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        final = manager.assemble_final_context(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        agent_msg = None
        for msg in final.messages:
            if msg["role"] == "system":
                content = msg["content"]
                if isinstance(content, list) and len(content) > 0:
                    text = content[0].get("text", "")
                    if "Managed agents" in text:
                        agent_msg = msg
                        break

        assert agent_msg is not None

    def test_projection_handles_external_agents_component(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        manager.register_component(
            ExternalAgentsComponent(
                agents=[{"agent_id": "ext1", "name": "external1", "description": "External agent"}],
                formatted_description="External agents: external1",
            )
        )

        items = manager.project_context_items()
        assert len(items) == 1
        assert items[0].item_type == ContextItemType.EXTERNAL_AGENT
        assert items[0].authority_tier == AuthorityTier.PLATFORM

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        final = manager.assemble_final_context(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        ext_msg = None
        for msg in final.messages:
            if msg["role"] == "system":
                content = msg["content"]
                if isinstance(content, list) and len(content) > 0:
                    text = content[0].get("text", "")
                    if "External agents" in text:
                        ext_msg = msg
                        break

        assert ext_msg is not None
