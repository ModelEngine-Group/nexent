"""Tests for deterministic context selection engine."""

from typing import Any, Dict, List

import pytest

from nexent.core.agents.context import reason_codes
from nexent.core.agents.context.context_item import (
    AuthorityTier,
    ContextItem,
    ContextItemType,
    RepresentationTier,
)
from nexent.core.agents.context.item_handler import ContextItemHandler
from nexent.core.agents.context.item_handler_registry import ItemHandlerRegistry
from nexent.core.agents.context.policy_models import ContextPolicy, resolve_policy
from nexent.core.agents.context.selection_engine import select_context


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the shared handler registry before and after each test."""

    ItemHandlerRegistry.reset()
    yield
    ItemHandlerRegistry.reset()


class _ScoredHandler(ContextItemHandler):
    """Test handler that records score calls and reads score from metadata."""

    def __init__(self):
        self.calls: List[str] = []

    def supported_types(self) -> List[ContextItemType]:
        return list(ContextItemType)

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        self.calls.append(item.item_id)
        return float(item.metadata.get("score", 1.0))


def _register_scored_handler() -> _ScoredHandler:
    handler = _ScoredHandler()
    ItemHandlerRegistry.register(handler)
    return handler


def _item(
    item_id: str,
    item_type: ContextItemType,
    *,
    authority: AuthorityTier = AuthorityTier.AGENT_INFERENCE,
    tokens: int = 100,
    minimum: RepresentationTier = RepresentationTier.STRUCTURED,
    score: float = 1.0,
    metadata: Dict[str, Any] | None = None,
    content: Any | None = None,
) -> ContextItem:
    item_metadata = {"score": score, **(metadata or {})}
    return ContextItem(
        item_id=item_id,
        item_type=item_type,
        authority_tier=authority,
        minimum_fidelity=minimum,
        current_representation=RepresentationTier.FULL,
        content=item_id if content is None else content,
        token_estimate=tokens,
        metadata=item_metadata,
    )


class TestSelectContext:
    """Selection engine behavior tests."""

    def test_mandatory_system_prompt_is_selected_at_minimum(self):
        _register_scored_handler()
        policy = resolve_policy()
        items = [
            _item(
                "system",
                ContextItemType.SYSTEM_PROMPT,
                authority=AuthorityTier.PLATFORM,
                tokens=50,
                minimum=RepresentationTier.FULL,
            ),
            _item("tool", ContextItemType.TOOL, tokens=100),
        ]

        decision = select_context(policy, items, safe_input_budget=60)

        assert "system" in decision.selected_item_ids
        assert decision.representation_requirements["system"] == RepresentationTier.FULL
        assert reason_codes.SELECTED_MANDATORY_MINIMUM in decision.reason_codes

    def test_disabled_item_types_are_excluded_by_policy(self):
        _register_scored_handler()
        policy = ContextPolicy(
            enabled_item_types=(ContextItemType.SYSTEM_PROMPT,),
            mandatory_item_types=(ContextItemType.SYSTEM_PROMPT,),
        )
        items = [
            _item(
                "system",
                ContextItemType.SYSTEM_PROMPT,
                authority=AuthorityTier.PLATFORM,
                tokens=10,
                minimum=RepresentationTier.FULL,
            ),
            _item("tool", ContextItemType.TOOL, tokens=10),
        ]

        decision = select_context(policy, items, safe_input_budget=100)

        assert "tool" in decision.excluded_item_ids
        assert reason_codes.EXCLUDED_POLICY_DISABLED in decision.reason_codes

    def test_budget_pressure_excludes_lower_priority_items(self):
        _register_scored_handler()
        policy = resolve_policy()
        items = [
            _item(
                "system",
                ContextItemType.SYSTEM_PROMPT,
                authority=AuthorityTier.PLATFORM,
                tokens=10,
                minimum=RepresentationTier.FULL,
            ),
            _item("high-score-tool", ContextItemType.TOOL, tokens=100, score=0.9),
            _item("low-score-tool", ContextItemType.TOOL, tokens=100, score=0.1),
        ]

        decision = select_context(policy, items, safe_input_budget=30)

        assert "high-score-tool" in decision.selected_item_ids
        assert "low-score-tool" in decision.excluded_item_ids
        assert reason_codes.EXCLUDED_BUDGET in decision.reason_codes

    def test_selection_is_deterministic_for_same_inputs(self):
        _register_scored_handler()
        policy = resolve_policy()
        items = [
            _item("b-tool", ContextItemType.TOOL, tokens=100, score=0.5),
            _item(
                "system",
                ContextItemType.SYSTEM_PROMPT,
                authority=AuthorityTier.PLATFORM,
                tokens=10,
                minimum=RepresentationTier.FULL,
            ),
            _item("a-tool", ContextItemType.TOOL, tokens=100, score=0.5),
        ]

        first = select_context(policy, items, safe_input_budget=35)
        second = select_context(policy, list(reversed(items)), safe_input_budget=35)

        assert first.selected_item_ids == second.selected_item_ids
        assert first.excluded_item_ids == second.excluded_item_ids
        assert first.decision_fingerprint == second.decision_fingerprint

    def test_mandatory_over_budget_returns_conflict(self):
        _register_scored_handler()
        policy = resolve_policy()
        items = [
            _item(
                "system",
                ContextItemType.SYSTEM_PROMPT,
                authority=AuthorityTier.PLATFORM,
                tokens=100,
                minimum=RepresentationTier.FULL,
            ),
            _item("tool", ContextItemType.TOOL, tokens=10),
        ]

        decision = select_context(policy, items, safe_input_budget=50)

        assert decision.selected_item_ids == ["system"]
        assert decision.excluded_item_ids == ["tool"]
        assert decision.remaining_budget == 0
        assert reason_codes.MANDATORY_BUDGET_IMPOSSIBLE in decision.reason_codes
        assert decision.conflicts[0]["type"] == reason_codes.MANDATORY_BUDGET_IMPOSSIBLE

    def test_handler_score_is_called_for_enabled_items(self):
        handler = _register_scored_handler()
        policy = resolve_policy()
        items = [
            _item(
                "system",
                ContextItemType.SYSTEM_PROMPT,
                authority=AuthorityTier.PLATFORM,
                tokens=10,
                minimum=RepresentationTier.FULL,
            ),
            _item("tool", ContextItemType.TOOL, tokens=10),
        ]

        select_context(policy, items, safe_input_budget=100)

        assert handler.calls == ["system", "tool"]

    def test_authority_conflict_excludes_lower_authority_item(self):
        handler = _register_scored_handler()
        policy = resolve_policy()
        items = [
            _item(
                "user-fact",
                ContextItemType.WORKING_MEMORY,
                authority=AuthorityTier.USER,
                tokens=10,
                metadata={"conflict_key": "preference"},
                content={"theme": "light"},
            ),
            _item(
                "inferred-fact",
                ContextItemType.WORKING_MEMORY,
                authority=AuthorityTier.AGENT_INFERENCE,
                tokens=10,
                metadata={"conflict_key": "preference"},
                content={"theme": "dark"},
            ),
        ]

        decision = select_context(policy, items, safe_input_budget=100)

        assert "user-fact" in decision.selected_item_ids
        assert "inferred-fact" in decision.excluded_item_ids
        assert reason_codes.EXCLUDED_LOWER_AUTHORITY in decision.reason_codes
        assert decision.conflicts[0]["type"] == reason_codes.EXCLUDED_LOWER_AUTHORITY
        assert handler.calls == ["user-fact"]

    def test_equal_authority_conflict_is_recorded_as_unresolved(self):
        _register_scored_handler()
        policy = resolve_policy()
        items = [
            _item(
                "first-fact",
                ContextItemType.WORKING_MEMORY,
                authority=AuthorityTier.USER,
                tokens=10,
                metadata={"conflict_key": "deadline"},
                content={"deadline": "Monday"},
            ),
            _item(
                "second-fact",
                ContextItemType.WORKING_MEMORY,
                authority=AuthorityTier.USER,
                tokens=10,
                metadata={"conflict_key": "deadline"},
                content={"deadline": "Tuesday"},
            ),
        ]

        decision = select_context(policy, items, safe_input_budget=100)

        assert decision.selected_item_ids == ["first-fact", "second-fact"]
        assert decision.excluded_item_ids == []
        assert reason_codes.AUTHORITY_CONFLICT_UNRESOLVED in decision.reason_codes
        assert decision.conflicts[0]["type"] == reason_codes.AUTHORITY_CONFLICT_UNRESOLVED
