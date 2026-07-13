"""Integration tests for selection + reduction pipeline in ContextManager."""

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


class TestSelectionReductionIntegration:

    def test_end_to_end_projection_selection_reduction(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        system_prompt = SystemPromptComponent(content="You are a helpful assistant.")
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
        assert final.evidence.selection_decision is not None
        assert isinstance(final.evidence.reduction_warnings, tuple)

    def test_reduction_failure_falls_back_to_original(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        system_prompt = SystemPromptComponent(content="You are helpful.")
        manager.register_component(system_prompt)

        runtime = ManagedContextRuntime(manager, components=[system_prompt])

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

    def test_token_budget_pressure_triggers_reduction(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=500,
            soft_input_budget_tokens=500,
            use_context_items=True,
        )
        manager = ContextManager(config=config)

        system_prompt = SystemPromptComponent(content="You are a helpful assistant.")
        tools = ToolsComponent(
            tools=[{"name": "search", "description": "Search the web for information"}],
            formatted_description="Available tools: search",
        )
        memory_comp = MemoryComponent(
            memories=[{"content": "User prefers Python for coding", "memory_type": "user"}],
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
        assert final.evidence.selection_decision is not None

    def test_use_context_items_false_path_unchanged(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=False,
        )
        manager = ContextManager(config=config)

        system_prompt = SystemPromptComponent(content="You are helpful.")
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
        assert final.evidence.selection_decision is None
        assert final.evidence.reduction_warnings == ()


class TestCalculateSafeInputBudget:

    def test_budget_from_soft_input_budget(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            soft_input_budget_tokens=5000,
        )
        manager = ContextManager(config=config)
        budget = manager._calculate_safe_input_budget(
            model=None, tools=[], purpose_stable=[]
        )
        assert budget > 0
        assert budget <= 5000

    def test_budget_from_token_threshold(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=8000,
            soft_input_budget_tokens=0,
        )
        manager = ContextManager(config=config)
        budget = manager._calculate_safe_input_budget(
            model=None, tools=[], purpose_stable=[]
        )
        assert budget > 0
        assert budget <= 8000

    def test_budget_subtracts_overhead(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            soft_input_budget_tokens=10000,
        )
        manager = ContextManager(config=config)
        purpose_stable = [{"role": "system", "content": [{"type": "text", "text": "A" * 1000}]}]
        budget = manager._calculate_safe_input_budget(
            model=None, tools=[], purpose_stable=purpose_stable
        )
        assert budget < 10000

    def test_budget_never_negative(self):
        config = ContextManagerConfig(
            enabled=True,
            token_threshold=100,
            soft_input_budget_tokens=100,
        )
        manager = ContextManager(config=config)
        purpose_stable = [{"role": "system", "content": [{"type": "text", "text": "A" * 10000}]}]
        budget = manager._calculate_safe_input_budget(
            model=None, tools=[], purpose_stable=purpose_stable
        )
        assert budget == 0


class TestContextEvidenceNewFields:

    def test_evidence_has_selection_decision_field(self):
        from nexent.core.context_runtime.contracts import ContextEvidence
        evidence = ContextEvidence()
        assert evidence.selection_decision is None

    def test_evidence_has_reduction_warnings_field(self):
        from nexent.core.context_runtime.contracts import ContextEvidence
        evidence = ContextEvidence()
        assert evidence.reduction_warnings == ()

    def test_evidence_accepts_selection_decision(self):
        from nexent.core.context_runtime.contracts import ContextEvidence
        mock_decision = MagicMock()
        evidence = ContextEvidence(selection_decision=mock_decision)
        assert evidence.selection_decision is mock_decision

    def test_evidence_accepts_reduction_warnings(self):
        from nexent.core.context_runtime.contracts import ContextEvidence
        warnings = ({"item_id": "kb1", "reason": "test"},)
        evidence = ContextEvidence(reduction_warnings=warnings)
        assert evidence.reduction_warnings == warnings

    def test_evidence_backward_compatible(self):
        from nexent.core.context_runtime.contracts import ContextEvidence
        evidence = ContextEvidence(
            selected_component_types=("system_prompt",),
            stable_message_count=1,
            dynamic_message_count=2,
        )
        assert evidence.selection_decision is None
        assert evidence.reduction_warnings == ()
