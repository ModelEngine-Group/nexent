from types import SimpleNamespace

from nexent.core.agents.context.composition import (
    SEGMENT_NAMES,
    estimate_context_segments,
    reconcile_context_composition,
)
from nexent.core.agents.context.models import ContextItemType


def _item(item_type, tokens, **content):
    return SimpleNamespace(type=item_type, token_estimate=tokens, content=content)


def test_ac_tu_006_classifies_context_item_provenance():
    segments = estimate_context_segments(
        [
            _item(ContextItemType.SYSTEM, 10, text="system"),
            _item(ContextItemType.MEMORY, 7, text="memory"),
            _item(ContextItemType.KNOWLEDGE_BASE, 8, text="knowledge"),
            _item(ContextItemType.CURRENT_TASK, 5, text="task"),
            _item(ContextItemType.TOOL, 6, name="tool"),
            _item(ContextItemType.CURRENT_ACTION, 9, text="result"),
        ],
        purpose_messages=[{"role": "system", "content": "header"}],
        tools=[{"type": "function", "function": {"name": "search"}}],
    )

    assert segments["system_instructions"] >= 10
    assert segments["retrieved_context"] == 15
    assert segments["current_request"] == 5
    assert segments["tool_definitions"] > 6
    assert segments["tool_calls_results"] == 9
    assert set(segments) == set(SEGMENT_NAMES)


def test_ac_tu_006_reconciles_shortfall_to_provider_overhead_exactly():
    composition = reconcile_context_composition(
        {"system_instructions": 30, "current_request": 10},
        100,
    )

    assert composition.source == "estimated"
    assert composition.segments["provider_overhead"] == 60
    assert sum(composition.segments.values()) == 100
    assert composition.adjustment_ratio == 0.6
    assert composition.high_adjustment is True


def test_ac_tu_006_scales_overestimate_and_assigns_rounding_remainder():
    composition = reconcile_context_composition(
        {"system_instructions": 70, "current_request": 70, "tool_definitions": 10},
        100,
    )

    assert all(value >= 0 for value in composition.segments.values())
    assert sum(composition.segments.values()) == 100
    assert composition.segments["provider_overhead"] >= 0
    assert composition.high_adjustment is True


def test_ac_tu_006_estimated_fallback_has_no_fabricated_overhead():
    composition = reconcile_context_composition(
        {"system_instructions": 3, "current_request": 2},
        None,
    )

    assert composition.source == "estimated"
    assert composition.denominator_tokens == 5
    assert composition.segments["provider_overhead"] == 0
    assert sum(composition.segments.values()) == 5
