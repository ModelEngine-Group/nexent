"""Integration test for ManagedContextRuntime with use_context_items=True."""

import pytest
from unittest.mock import MagicMock

from nexent.core.agents.agent_context import ContextManager
from nexent.core.agents.agent_model import (
    MemoryComponent,
    SystemPromptComponent,
    ToolsComponent,
)
from nexent.core.agents.summary_config import ContextManagerConfig
from nexent.core.agents.context.handlers import register_all
from nexent.core.context_runtime.managed.runtime import ManagedContextRuntime


@pytest.fixture(autouse=True)
def ensure_handlers_registered():
    register_all()


class TestManagedContextRuntimeWithContextItems:

    def test_prepare_step_with_context_items_enabled(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        system_prompt = SystemPromptComponent(content="You are helpful")
        tools = ToolsComponent(
            tools=[{"name": "search", "description": "Search the web"}],
            formatted_description="Available tools: search",
        )
        memory_comp = MemoryComponent(
            memories=[{"content": "User prefers Python", "memory_type": "user"}],
            formatted_content="User preferences: Python",
        )
        
        manager.register_component(system_prompt)
        manager.register_component(tools)
        manager.register_component(memory_comp)

        runtime = ManagedContextRuntime(manager, components=[system_prompt, tools, memory_comp])

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        runtime.prepare_run(memory=memory, fallback_system_prompt="Fallback")

        final = runtime.prepare_step(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        assert final is not None
        assert len(final.messages) > 0
        assert final.evidence.context_items is not None
        assert len(final.evidence.context_items) > 0

        roles = [msg["role"] for msg in final.messages]
        assert "system" in roles
        assert "user" in roles

    def test_prepare_final_answer_with_context_items_enabled(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        system_prompt = SystemPromptComponent(content="You are helpful")
        manager.register_component(system_prompt)

        runtime = ManagedContextRuntime(manager, components=[system_prompt])

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        runtime.prepare_run(memory=memory, fallback_system_prompt="Fallback")

        final_answer_templates = {
            "final_answer": {
                "pre_messages": "Generate final answer",
                "post_messages": "Task: {{ task }}",
            }
        }

        final = runtime.prepare_final_answer(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            task="Answer the question",
            final_answer_templates=final_answer_templates,
            tools=[],
        )

        assert final is not None
        assert len(final.messages) > 0
        assert final.evidence.context_items is not None

    def test_backward_compatibility_with_context_items_disabled(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=False,
        )
        manager = ContextManager(config=config)

        system_prompt = SystemPromptComponent(content="You are helpful")
        memory_comp = MemoryComponent(
            memories=[{"content": "User prefers Python", "memory_type": "user"}],
            formatted_content="User preferences: Python",
        )
        
        manager.register_component(system_prompt)
        manager.register_component(memory_comp)

        runtime = ManagedContextRuntime(manager, components=[system_prompt, memory_comp])

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        runtime.prepare_run(memory=memory, fallback_system_prompt="Fallback")

        final = runtime.prepare_step(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        assert final is not None
        assert len(final.messages) > 0
        assert final.evidence.context_items == ()
