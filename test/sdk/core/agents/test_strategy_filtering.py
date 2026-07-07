"""
Strategy filtering fix verification tests.

Verifies that use_context_items=True respects strategy-based component selection
instead of bypassing it. The fix adds selected_components to ManagedRunContext
and ensures assemble_final_context() uses strategy-filtered components.

Tests:
  1. Budget-pressure equivalence between use_context_items=True/False
  2. Strategy drop propagation when use_context_items=True
  3. selected_component_types accuracy after strategy filtering
  4. Fingerprint stability across use_context_items toggle
  5. History items unaffected by strategy filtering
"""
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_project_root / "sdk"))
sys.path.insert(0, str(_project_root / "backend"))

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from smolagents.memory import AgentMemory, SystemPromptStep

from nexent.core.agents.context.handlers import register_all
from nexent.core.agents.summary_config import ContextManagerConfig
from nexent.core.agents.agent_context import ContextManager, ManagedRunContext
from nexent.core.agents.agent_model import (
    SystemPromptComponent,
    ToolsComponent,
    MemoryComponent,
    KnowledgeBaseComponent,
)
from nexent.core.agents.context.history_projector import HistoryProjector
from nexent.core.agents.context.context_item import ContextItemType

register_all()


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def create_mock_model() -> MagicMock:
    """Create a mock model that satisfies compress_if_needed interface."""
    model = MagicMock()
    model.model_id = "test-model"
    return model


def create_components_with_sizes(
    system_prompt_chars: int = 150,
    tools_chars: int = 300,
    memory_chars: int = 200,
    kb_chars: int = 400,
) -> List[Any]:
    """Create four components with controllable text sizes.

    Token estimates use chars_per_token=1.5 (default), so:
      150 chars ~ 100 tokens, 300 chars ~ 200 tokens, etc.
    """
    return [
        SystemPromptComponent(
            content="S" * system_prompt_chars,
            priority=100,
        ),
        ToolsComponent(
            tools=[{"name": "search", "description": "Search the web"}],
            formatted_description="T" * tools_chars,
            priority=80,
        ),
        MemoryComponent(
            memories=[{"content": "User fact", "memory_type": "user"}],
            formatted_content="M" * memory_chars,
            priority=50,
        ),
        KnowledgeBaseComponent(
            summary="K" * kb_chars,
            kb_ids=["kb_1"],
            priority=30,
        ),
    ]


def build_memory() -> AgentMemory:
    """Build a minimal AgentMemory for prepare_run_context."""
    return AgentMemory(system_prompt=SystemPromptStep(system_prompt=""))


# ---------------------------------------------------------------------------
#  Test 1: Budget-pressure equivalence
# ---------------------------------------------------------------------------

def test_budget_pressure_equivalence() -> bool:
    """Verify use_context_items=True and False produce same component set under budget pressure."""
    print("\n" + "=" * 70)
    print("Test 1: Budget-pressure equivalence")
    print("=" * 70)

    components = create_components_with_sizes(
        system_prompt_chars=150,  # ~100 tokens
        tools_chars=300,          # ~200 tokens
        memory_chars=200,         # ~133 tokens
        kb_chars=400,             # ~267 tokens
    )
    # Total ~700 tokens. Set budget so only ~3 components fit.
    # component_budgets total (excluding conversation_history) controls selection.
    config_false = ContextManagerConfig(
        enabled=True,
        use_context_items=False,
        token_threshold=500,
        strategy="token_budget",
        component_budgets={
            "system_prompt": 200,
            "tools": 300,
            "memory": 200,
            "knowledge_base": 200,
            "conversation_history": 0,
        },
    )
    config_true = ContextManagerConfig(
        enabled=True,
        use_context_items=True,
        token_threshold=500,
        strategy="token_budget",
        component_budgets={
            "system_prompt": 200,
            "tools": 300,
            "memory": 200,
            "knowledge_base": 200,
            "conversation_history": 0,
        },
    )

    cm_false = ContextManager(config=config_false)
    cm_true = ContextManager(config=config_true)

    memory_false = build_memory()
    memory_true = build_memory()

    run_ctx_false = cm_false.prepare_run_context(
        memory=memory_false,
        fallback_system_prompt="",
        components=components,
    )
    run_ctx_true = cm_true.prepare_run_context(
        memory=memory_true,
        fallback_system_prompt="",
        components=components,
    )

    types_false = set(run_ctx_false.selected_component_types)
    types_true = set(run_ctx_true.selected_component_types)

    print(f"  use_context_items=False selected: {sorted(types_false)}")
    print(f"  use_context_items=True  selected: {sorted(types_true)}")

    if types_false == types_true:
        print("  \u2705 PASSED: Both paths selected same component types")
        return True
    else:
        print(f"  \u274c FAILED: Mismatch - False={sorted(types_false)}, True={sorted(types_true)}")
        return False


# ---------------------------------------------------------------------------
#  Test 2: Strategy drop propagation
# ---------------------------------------------------------------------------

def test_strategy_drop_propagation() -> bool:
    """Verify low-priority components are dropped when use_context_items=True."""
    print("\n" + "=" * 70)
    print("Test 2: Strategy drop propagation")
    print("=" * 70)

    high_priority = SystemPromptComponent(
        content="H" * 150,
        priority=100,
    )
    medium_priority = ToolsComponent(
        tools=[{"name": "calc", "description": "Calculate"}],
        formatted_description="M" * 200,
        priority=50,
    )
    low_priority = KnowledgeBaseComponent(
        summary="L" * 300,
        kb_ids=["kb_low"],
        priority=10,
    )

    components = [high_priority, medium_priority, low_priority]

    # _calculate_component_budget sums component_budgets (excluding conversation_history).
    # high=100 tokens, medium=133 tokens, low=200 tokens.
    # Total budget = 120+150+50 = 320. After high+medium (233), low (200) won't fit (433>320).
    # Per-type: knowledge_base=50 also blocks low (200>50).
    config = ContextManagerConfig(
        enabled=True,
        use_context_items=True,
        token_threshold=300,
        strategy="token_budget",
        component_budgets={
            "system_prompt": 120,
            "tools": 150,
            "knowledge_base": 50,
            "conversation_history": 0,
        },
    )

    cm = ContextManager(config=config)
    memory = build_memory()

    run_ctx = cm.prepare_run_context(
        memory=memory,
        fallback_system_prompt="",
        components=components,
    )

    selected_types = set(run_ctx.selected_component_types)
    print(f"  Selected types: {sorted(selected_types)}")

    # Verify low-priority KB was dropped
    has_high = "system_prompt" in selected_types
    has_medium = "tools" in selected_types
    has_low = "knowledge_base" in selected_types

    if has_high and has_medium and not has_low:
        print("  \u2705 PASSED: Low-priority component correctly dropped")
        return True
    else:
        print(f"  \u274c FAILED: high={has_high}, medium={has_medium}, low={has_low}")
        return False


# ---------------------------------------------------------------------------
#  Test 3: selected_component_types accuracy
# ---------------------------------------------------------------------------

def test_selected_component_types_accuracy() -> bool:
    """Verify selected_component_types reflects strategy-filtered components, not all."""
    print("\n" + "=" * 70)
    print("Test 3: selected_component_types accuracy")
    print("=" * 70)

    # 4 components, budget drops 1
    components = create_components_with_sizes(
        system_prompt_chars=120,  # ~80 tokens, priority=100
        tools_chars=180,          # ~120 tokens, priority=80
        memory_chars=150,         # ~100 tokens, priority=50
        kb_chars=300,             # ~200 tokens, priority=30
    )

    # Total budget = 350 tokens. High+Medium+Memory = 300 tokens. KB (200) won't fit.
    config = ContextManagerConfig(
        enabled=True,
        use_context_items=True,
        token_threshold=350,
        strategy="token_budget",
        component_budgets={
            "system_prompt": 150,
            "tools": 200,
            "memory": 150,
            "knowledge_base": 150,
            "conversation_history": 0,
        },
    )

    cm = ContextManager(config=config)
    memory = build_memory()

    run_ctx = cm.prepare_run_context(
        memory=memory,
        fallback_system_prompt="",
        components=components,
    )

    selected_types = list(run_ctx.selected_component_types)
    all_types = [c.component_type for c in components]

    print(f"  All component types:      {all_types}")
    print(f"  Selected component types: {selected_types}")
    print(f"  Total components: {len(all_types)}, Selected: {len(selected_types)}")

    # Expect exactly 3 selected (KB dropped)
    expected_count = 3
    if len(selected_types) == expected_count and "knowledge_base" not in selected_types:
        print(f"  \u2705 PASSED: {expected_count} types selected, KB correctly excluded")
        return True
    else:
        print(f"  \u274c FAILED: Expected {expected_count} types without KB, got {len(selected_types)}: {selected_types}")
        return False


# ---------------------------------------------------------------------------
#  Test 4: Fingerprint stability
# ---------------------------------------------------------------------------

def test_fingerprint_stability() -> bool:
    """Verify fingerprint is identical when toggling use_context_items with same components."""
    print("\n" + "=" * 70)
    print("Test 4: Fingerprint stability")
    print("=" * 70)

    components = create_components_with_sizes(
        system_prompt_chars=150,
        tools_chars=200,
        memory_chars=100,
        kb_chars=150,
    )

    model = create_mock_model()

    # Run with use_context_items=False
    config_false = ContextManagerConfig(
        enabled=True,
        use_context_items=False,
        token_threshold=10000,
        strategy="full",
    )
    cm_false = ContextManager(config=config_false)
    memory_false = build_memory()

    run_ctx_false = cm_false.prepare_run_context(
        memory=memory_false,
        fallback_system_prompt="",
        components=components,
    )

    final_ctx_false = cm_false.assemble_final_context(
        model=model,
        memory=memory_false,
        current_run_start_idx=0,
        run_context=run_ctx_false,
    )

    fp_false = final_ctx_false.evidence.stable_prefix_fingerprint

    # Run with use_context_items=True (same components, same strategy)
    config_true = ContextManagerConfig(
        enabled=True,
        use_context_items=True,
        token_threshold=10000,
        strategy="full",
    )
    cm_true = ContextManager(config=config_true)
    memory_true = build_memory()

    run_ctx_true = cm_true.prepare_run_context(
        memory=memory_true,
        fallback_system_prompt="",
        components=components,
    )

    final_ctx_true = cm_true.assemble_final_context(
        model=model,
        memory=memory_true,
        current_run_start_idx=0,
        run_context=run_ctx_true,
    )

    fp_true = final_ctx_true.evidence.stable_prefix_fingerprint

    print(f"  Fingerprint (use_context_items=False): {fp_false[:16]}...")
    print(f"  Fingerprint (use_context_items=True):  {fp_true[:16]}...")

    if fp_false == fp_true:
        print("  \u2705 PASSED: Fingerprints are identical")
        return True
    else:
        print("  \u274c FAILED: Fingerprints differ")
        return False


# ---------------------------------------------------------------------------
#  Test 5: History items unaffected
# ---------------------------------------------------------------------------

def test_history_items_unaffected() -> bool:
    """Verify history-projected items still appear regardless of strategy filtering."""
    print("\n" + "=" * 70)
    print("Test 5: History items unaffected")
    print("=" * 70)

    def mock_query_units(conversation_id: int, run_id: Optional[int] = None) -> List[Dict[str, Any]]:
        return [
            {
                "unit_id": 1,
                "unit_type": "user_input",
                "unit_content": "What is AI?",
                "run_id": 1,
                "step_id": 1,
                "tool_call_id": None,
            },
            {
                "unit_id": 2,
                "unit_type": "final_answer",
                "unit_content": "AI is artificial intelligence",
                "run_id": 1,
                "step_id": 1,
                "tool_call_id": None,
            },
            {
                "unit_id": 3,
                "unit_type": "tool",
                "unit_content": "search('machine learning')",
                "run_id": 1,
                "step_id": 2,
                "tool_call_id": "tc_001",
            },
            {
                "unit_id": 4,
                "unit_type": "execution_logs",
                "unit_content": "Found 5 results about ML",
                "run_id": 1,
                "step_id": 2,
                "tool_call_id": "tc_001",
            },
        ]

    history_projector = HistoryProjector(query_units_fn=mock_query_units)

    # Tight budget that drops KB component
    components = create_components_with_sizes(
        system_prompt_chars=150,  # ~100 tokens
        tools_chars=200,          # ~133 tokens
        memory_chars=100,         # ~67 tokens
        kb_chars=400,             # ~267 tokens - will be dropped
    )

    config = ContextManagerConfig(
        enabled=True,
        use_context_items=True,
        token_threshold=400,
        strategy="token_budget",
        component_budgets={
            "system_prompt": 200,
            "tools": 200,
            "memory": 150,
            "knowledge_base": 150,
            "conversation_history": 0,
        },
        history_projector=history_projector,
    )

    cm = ContextManager(config=config)
    memory = build_memory()
    model = create_mock_model()

    run_ctx = cm.prepare_run_context(
        memory=memory,
        fallback_system_prompt="",
        components=components,
    )

    # Verify KB was dropped by strategy
    selected_types = set(run_ctx.selected_component_types)
    print(f"  Strategy-selected types: {sorted(selected_types)}")
    kb_dropped = "knowledge_base" not in selected_types

    # Now assemble final context with history projector
    final_ctx = cm.assemble_final_context(
        model=model,
        memory=memory,
        current_run_start_idx=0,
        run_context=run_ctx,
        conversation_id=12345,
    )

    context_items = final_ctx.evidence.context_items
    print(f"  Total context items in evidence: {len(context_items)}")

    # Check for history items (HISTORY_TURN and TOOL_CALL_RESULT)
    history_turn_items = [
        item for item in context_items
        if item.item_type == ContextItemType.HISTORY_TURN
    ]
    tool_result_items = [
        item for item in context_items
        if item.item_type == ContextItemType.TOOL_CALL_RESULT
    ]

    print(f"  HISTORY_TURN items: {len(history_turn_items)}")
    print(f"  TOOL_CALL_RESULT items: {len(tool_result_items)}")

    has_history = len(history_turn_items) > 0
    has_tool_results = len(tool_result_items) > 0

    if kb_dropped and has_history and has_tool_results:
        print("  \u2705 PASSED: KB dropped by strategy, but history items still projected")
        return True
    else:
        reasons = []
        if not kb_dropped:
            reasons.append("KB was NOT dropped (unexpected)")
        if not has_history:
            reasons.append("No HISTORY_TURN items found")
        if not has_tool_results:
            reasons.append("No TOOL_CALL_RESULT items found")
        print(f"  \u274c FAILED: {'; '.join(reasons)}")
        return False


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 70)
    print("Strategy Filtering Fix Verification Tests")
    print("=" * 70)

    results = {
        "Budget-pressure equivalence": test_budget_pressure_equivalence(),
        "Strategy drop propagation": test_strategy_drop_propagation(),
        "selected_component_types accuracy": test_selected_component_types_accuracy(),
        "Fingerprint stability": test_fingerprint_stability(),
        "History items unaffected": test_history_items_unaffected(),
    }

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    passed_count = 0
    total_count = len(results)

    for test_name, passed in results.items():
        status = "\u2705 PASSED" if passed else "\u274c FAILED"
        print(f"  {status}: {test_name}")
        if passed:
            passed_count += 1

    print("\n" + "=" * 70)
    if passed_count == total_count:
        print(f"ALL TESTS PASSED \u2705 ({passed_count}/{total_count})")
    else:
        print(f"SOME TESTS FAILED \u274c ({passed_count}/{total_count} passed)")
    print("=" * 70)

    return 0 if passed_count == total_count else 1


if __name__ == "__main__":
    sys.exit(main())
