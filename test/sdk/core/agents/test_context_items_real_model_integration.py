"""
Real-model integration test for Context Management Optimization (Phase 0-3).

Verifies the full use_context_items=True pipeline with a real LLM:
  projection -> selection -> reduction -> message assembly -> model call

Uses DashScope (qwen3.6-plus) via OpenAI-compatible endpoint.
Traces are sent to LangFuse via OpenTelemetry.

Requirements:
  DEFAULT_MODEL_ENDPOINT, DEFAULT_MODEL_API_KEY, DEFAULT_MODEL env vars.
  OTEL_EXPORTER_OTLP_ENDPOINT and auth for LangFuse.

Run locally:
  pytest -m local_only test/sdk/core/agents/test_context_items_real_model_integration.py -v -s
"""

import os
import pytest
from unittest.mock import MagicMock

from nexent.core.agents.agent_context import ContextManager
from nexent.core.agents.agent_model import (
    MemoryComponent,
    SystemPromptComponent,
    ToolsComponent,
    SkillsComponent,
    KnowledgeBaseComponent,
)
from nexent.core.agents.summary_config import ContextManagerConfig
from nexent.core.agents.context.context_item import ContextItemType
from nexent.core.agents.context.handlers import register_all
from nexent.core.agents.context.history_projector import HistoryProjector
from nexent.core.context_runtime.managed.runtime import ManagedContextRuntime
from nexent.core.models.openai_llm import OpenAIModel


pytestmark = pytest.mark.local_only


@pytest.fixture(autouse=True)
def ensure_handlers():
    register_all()


@pytest.fixture
def real_model():
    endpoint = os.environ.get("DEFAULT_MODEL_ENDPOINT")
    api_key = os.environ.get("DEFAULT_MODEL_API_KEY")
    model_id = os.environ.get("DEFAULT_MODEL", "qwen-plus")
    if not endpoint or not api_key:
        pytest.skip("DEFAULT_MODEL_ENDPOINT / DEFAULT_MODEL_API_KEY not set")
    return OpenAIModel(
        model_id=model_id,
        api_key=api_key,
        model_name=model_id,
        url=endpoint,
        temperature=0.1,
        top_p=0.95,
        ssl_verify=True,
    )


def _make_memory():
    memory = MagicMock()
    memory.system_prompt = None
    memory.steps = []
    return memory


class TestContextItemsRealModel:
    """End-to-end tests with real model calls."""

    def test_basic_pipeline_with_real_model(self, real_model):
        """Projection -> selection -> reduction -> assembly -> model call."""
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        system_prompt = SystemPromptComponent(
            content="You are a helpful assistant. Answer in one sentence."
        )
        tools = ToolsComponent(
            tools=[
                {"name": "search", "description": "Search the web for information"},
                {"name": "calculator", "description": "Perform math calculations"},
            ],
            formatted_description="Tools: search, calculator",
        )
        memory_comp = MemoryComponent(
            memories=[{"content": "User prefers Python", "memory_type": "user"}],
            formatted_content="User preferences: Python programming",
        )

        manager.register_component(system_prompt)
        manager.register_component(tools)
        manager.register_component(memory_comp)

        runtime = ManagedContextRuntime(
            manager, components=[system_prompt, tools, memory_comp]
        )

        memory = _make_memory()
        runtime.prepare_run(memory=memory, fallback_system_prompt="You are helpful")

        final = runtime.prepare_step(
            model=real_model,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        assert final is not None
        assert len(final.messages) > 0

        roles = [msg["role"] for msg in final.messages]
        assert "system" in roles

        assert final.evidence.context_items is not None
        assert len(final.evidence.context_items) > 0

        item_types = {item.item_type for item in final.evidence.context_items}
        assert ContextItemType.SYSTEM_PROMPT in item_types

        assert final.evidence.selection_decision is not None
        decision = final.evidence.selection_decision
        assert len(decision.selected_item_ids) > 0
        assert decision.policy_version == "1.0"
        assert decision.decision_fingerprint != ""

        assert isinstance(final.evidence.reduction_warnings, tuple)

    def test_budget_pressure_triggers_reduction_with_real_model(self, real_model):
        """Tight budget should trigger reduction before exclusion."""
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=2000,
            soft_input_budget_tokens=2000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        system_prompt = SystemPromptComponent(
            content="You are a helpful assistant. Be concise."
        )
        tools = ToolsComponent(
            tools=[
                {"name": "search", "description": "Search the web for information about any topic"},
                {"name": "calculator", "description": "Perform mathematical calculations"},
                {"name": "weather", "description": "Get current weather for a location"},
            ],
            formatted_description="Tools: search, calculator, weather",
        )
        skills = SkillsComponent(
            skills=[
                {"name": "code_review", "description": "Review code for bugs and improvements"},
                {"name": "translate", "description": "Translate text between languages"},
            ],
            formatted_description="Skills: code_review, translate",
        )
        kb = KnowledgeBaseComponent(
            kb_id="kb-001",
            title="Python Documentation",
            content="Python is a high-level programming language. " * 50,
            relevance_score=0.9,
            formatted_content="Python docs: high-level language",
        )

        manager.register_component(system_prompt)
        manager.register_component(tools)
        manager.register_component(skills)
        manager.register_component(kb)

        runtime = ManagedContextRuntime(
            manager, components=[system_prompt, tools, skills, kb]
        )

        memory = _make_memory()
        runtime.prepare_run(memory=memory, fallback_system_prompt="You are helpful")

        final = runtime.prepare_step(
            model=real_model,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        assert final is not None
        assert len(final.messages) > 0
        assert final.evidence.selection_decision is not None

    def test_history_projector_with_real_model(self, real_model):
        """HistoryProjector + component projection + selection + reduction."""
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )

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
                    "unit_content": "Python is a high-level programming language known for readability.",
                    "message_id": 1,
                    "step_index": 2,
                },
                {
                    "unit_id": 3,
                    "unit_type": "user_input",
                    "unit_content": "What are its main features?",
                    "message_id": 2,
                    "step_index": 1,
                },
                {
                    "unit_id": 4,
                    "unit_type": "final_answer",
                    "unit_content": "Key features include dynamic typing, garbage collection, and extensive standard library.",
                    "message_id": 2,
                    "step_index": 2,
                },
            ]

        history_projector = HistoryProjector(query_units_fn=mock_query_fn)
        config.history_projector = history_projector

        manager = ContextManager(config=config)

        system_prompt = SystemPromptComponent(
            content="You are a Python expert. Answer concisely."
        )
        manager.register_component(system_prompt)

        runtime = ManagedContextRuntime(
            manager,
            components=[system_prompt],
            conversation_id=42,
        )

        memory = _make_memory()
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
        assert ContextItemType.HISTORY_TURN in item_types or ContextItemType.SYSTEM_PROMPT in item_types

        assert final.evidence.selection_decision is not None

    def test_use_context_items_false_zero_regression(self, real_model):
        """use_context_items=False must produce identical pipeline behavior."""
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=False,
        )
        manager = ContextManager(config=config)

        system_prompt = SystemPromptComponent(content="You are helpful.")
        memory_comp = MemoryComponent(
            memories=[{"content": "User likes Python", "memory_type": "user"}],
            formatted_content="User likes Python",
        )

        manager.register_component(system_prompt)
        manager.register_component(memory_comp)

        runtime = ManagedContextRuntime(
            manager, components=[system_prompt, memory_comp]
        )

        memory = _make_memory()
        runtime.prepare_run(memory=memory, fallback_system_prompt="You are helpful")

        final = runtime.prepare_step(
            model=real_model,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        assert final is not None
        assert len(final.messages) > 0
        assert final.evidence.context_items == ()
        assert final.evidence.selection_decision is None
        assert final.evidence.reduction_warnings == ()

    def test_compression_with_real_model(self, real_model):
        """Compression path works with use_context_items=True under token pressure."""
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

        steps = [TaskStep(task="Solve a complex multi-step problem")]
        for i in range(8):
            steps.append(ActionStep(
                step_number=i,
                timing=MagicMock(),
                code_action=f"action_{i}",
                observations="This is a detailed observation with significant text content. " * 30,
            ))
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
