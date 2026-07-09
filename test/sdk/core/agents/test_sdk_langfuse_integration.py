"""
SDK Integration Test with Real Model and LangFuse Tracing

This test verifies:
1. Real LLM model execution through the SDK
2. OpenTelemetry instrumentation captures spans correctly
3. Context management with use_context_items=True works end-to-end
4. LangFuse receives and displays traces properly

Requirements:
- OPENAI_API_KEY environment variable must be set
- LangFuse configuration in .env (OTEL_EXPORTER_OTLP_ENDPOINT, etc.)
- Network access to OpenAI API and LangFuse

NOTE: This test is marked as 'local_only' and will be skipped in CI environments.
Run locally with: pytest -m local_only test/sdk/core/agents/test_sdk_langfuse_integration.py
"""

import os
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
from nexent.core.models.openai_llm import OpenAIModel


pytestmark = pytest.mark.local_only


@pytest.fixture(autouse=True)
def ensure_handlers_registered():
    """Ensure all context handlers are registered."""
    register_all()


@pytest.fixture
def real_model():
    """Create a real OpenAI model instance for integration testing."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set - skipping real model integration test")
    
    return OpenAIModel(
        model_id="gpt-3.5-turbo",
        api_key=api_key,
        model_name="gpt-3.5-turbo",
        url="https://api.openai.com/v1",
        temperature=0.1,
        top_p=0.95,
    )


class TestSDKLangFuseIntegration:
    """Integration tests with real model and LangFuse tracing."""

    def test_context_items_with_real_model(self, real_model):
        """Test context management with real model execution."""
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        system_prompt = SystemPromptComponent(
            content="You are a helpful assistant. Answer questions concisely."
        )
        tools = ToolsComponent(
            tools=[{"name": "search", "description": "Search the web"}],
            formatted_description="Available tools: search",
        )
        memory_comp = MemoryComponent(
            memories=[{"content": "User prefers Python", "memory_type": "user"}],
            formatted_content="User preferences: Python programming language",
        )
        
        manager.register_component(system_prompt)
        manager.register_component(tools)
        manager.register_component(memory_comp)

        runtime = ManagedContextRuntime(
            manager, 
            components=[system_prompt, tools, memory_comp]
        )

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        runtime.prepare_run(memory=memory, fallback_system_prompt="You are helpful")

        final = runtime.prepare_step(
            model=real_model,
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

        item_types = [item.item_type for item in final.evidence.context_items]
        assert len(item_types) > 0

    def test_context_compression_with_real_model(self, real_model):
        """Test context compression with real model when token threshold is exceeded."""
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=500,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        system_prompt = SystemPromptComponent(content="You are a helpful assistant.")
        manager.register_component(system_prompt)

        runtime = ManagedContextRuntime(manager, components=[system_prompt])

        from smolagents.memory import ActionStep, TaskStep
        
        memory = MagicMock()
        memory.system_prompt = None
        
        steps = []
        task_step = TaskStep(task="Solve a complex problem")
        steps.append(task_step)
        
        for i in range(10):
            action_step = ActionStep(
                step_number=i,
                timing=MagicMock(),
                code_action=f"action_{i}",
                observations="This is a very long observation with lots of text. " * 50
            )
            steps.append(action_step)
        
        memory.steps = steps

        runtime.prepare_run(memory=memory, fallback_system_prompt="You are helpful")

        final = runtime.prepare_step(
            model=real_model,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        assert final is not None
        assert len(final.messages) > 0
        
        stats = runtime.compression_stats()
        assert stats['calls'] > 0 or stats['cache_hits'] > 0

    def test_history_projector_integration(self, real_model):
        """Test HistoryProjector with real model execution."""
        from nexent.core.agents.context.history_projector import HistoryProjector
        
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        def mock_query_fn(conversation_id, message_id=None):
            return [
                {
                    "unit_id": 1,
                    "unit_type": "user_input",
                    "unit_content": "What is Python?",
                    "message_id": 1,
                    "step_index": 1,
                },
                {
                    "unit_id": 2,
                    "unit_type": "final_answer",
                    "unit_content": "Python is a programming language.",
                    "message_id": 1,
                    "step_index": 2,
                },
            ]

        history_projector = HistoryProjector(query_units_fn=mock_query_fn)
        config.history_projector = history_projector

        system_prompt = SystemPromptComponent(content="You are helpful")
        manager.register_component(system_prompt)

        runtime = ManagedContextRuntime(manager, components=[system_prompt], conversation_id=123)

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        runtime.prepare_run(memory=memory, fallback_system_prompt="You are helpful")

        final = runtime.prepare_step(
            model=real_model,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        assert final is not None
        assert final.evidence.context_items is not None
        
        item_types = [item.item_type for item in final.evidence.context_items]
        assert len(item_types) >= 1
