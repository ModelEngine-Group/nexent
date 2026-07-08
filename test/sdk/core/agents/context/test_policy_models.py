"""Tests for policy decision models."""

import pytest

from nexent.core.agents.context import reason_codes
from nexent.core.agents.context.context_item import ContextItemType, RepresentationTier
from nexent.core.agents.context.policy_models import (
    ContextPolicy,
    MemoryDecision,
    PolicyInvalidError,
    SelectionDecision,
    resolve_policy,
    validate_policy,
)


class TestContextPolicy:
    """Tests for ContextPolicy model and resolution."""

    def test_context_policy_is_frozen(self):
        policy = ContextPolicy()

        with pytest.raises(AttributeError):
            policy.policy_version = "2.0"

    def test_default_policy_resolves_successfully(self):
        policy = resolve_policy()

        assert policy.policy_version == "1.0"
        assert ContextItemType.SYSTEM_PROMPT in policy.enabled_item_types
        assert ContextItemType.MEMORY in policy.enabled_item_types
        assert policy.mandatory_item_types == (ContextItemType.SYSTEM_PROMPT,)
        assert policy.minimum_fidelity_by_type[ContextItemType.SYSTEM_PROMPT] == RepresentationTier.FULL
        assert policy.minimum_fidelity_by_type[ContextItemType.TOOL] == RepresentationTier.STRUCTURED

    def test_policy_resolution_merges_layers_in_precedence_order(self):
        policy = resolve_policy(
            platform_default={
                "policy_version": "platform",
                "max_input_budget": 1000,
                "mandatory_reserve_tokens": 100,
            },
            tenant_config={
                "policy_version": "tenant",
                "mandatory_reserve_tokens": 200,
                "type_budget_allocations": {"tool": 300},
            },
            agent_config={
                "policy_version": "agent",
                "minimum_fidelity_by_type": {"tool": "pointer"},
            },
            request_override={
                "policy_version": "request",
                "max_input_budget": 1200,
            },
        )

        assert policy.policy_version == "request"
        assert policy.max_input_budget == 1200
        assert policy.mandatory_reserve_tokens == 200
        assert policy.type_budget_allocations == {ContextItemType.TOOL: 300}
        assert policy.minimum_fidelity_by_type[ContextItemType.TOOL] == RepresentationTier.POINTER
        assert policy.minimum_fidelity_by_type[ContextItemType.SYSTEM_PROMPT] == RepresentationTier.FULL

    def test_policy_validation_rejects_negative_budget(self):
        policy = ContextPolicy(max_input_budget=-1)

        with pytest.raises(PolicyInvalidError) as exc_info:
            validate_policy(policy)

        assert reason_codes.POLICY_BUDGET_INVALID in exc_info.value.reason_codes

    def test_policy_validation_rejects_allocations_over_budget(self):
        policy = ContextPolicy(
            max_input_budget=100,
            mandatory_reserve_tokens=60,
            type_budget_allocations={ContextItemType.TOOL: 50},
        )

        with pytest.raises(PolicyInvalidError) as exc_info:
            validate_policy(policy)

        assert reason_codes.POLICY_BUDGET_INVALID in exc_info.value.reason_codes

    def test_policy_validation_rejects_disabled_mandatory_type(self):
        policy = ContextPolicy(
            enabled_item_types=(ContextItemType.TOOL,),
            mandatory_item_types=(ContextItemType.SYSTEM_PROMPT,),
        )

        with pytest.raises(PolicyInvalidError) as exc_info:
            validate_policy(policy)

        assert reason_codes.POLICY_DISABLED_MANDATORY in exc_info.value.reason_codes

    def test_policy_resolution_rejects_invalid_representation(self):
        with pytest.raises(PolicyInvalidError) as exc_info:
            resolve_policy(request_override={"minimum_fidelity_by_type": {"tool": "invalid-tier"}})

        assert reason_codes.POLICY_INVALID_REPRESENTATION in exc_info.value.reason_codes


class TestSelectionDecision:
    """Tests for SelectionDecision frozen dataclass."""

    def test_selection_decision_is_frozen(self):
        decision = SelectionDecision(
            selected_item_ids=["item-1"],
            excluded_item_ids=["item-2"],
            representation_requirements={"item-1": RepresentationTier.FULL},
            budget_allocations={"item-1": 100},
            remaining_budget=500,
            conflicts=[],
            reason_codes=["selected_mandatory_minimum"],
            policy_version="1.0",
            decision_fingerprint="abc123",
        )

        with pytest.raises(AttributeError):
            decision.selected_item_ids = ["other"]

    def test_selection_decision_creation(self):
        decision = SelectionDecision(
            selected_item_ids=["item-1", "item-2"],
            excluded_item_ids=["item-3"],
            representation_requirements={
                "item-1": RepresentationTier.FULL,
                "item-2": RepresentationTier.COMPRESSED,
            },
            budget_allocations={"item-1": 200, "item-2": 100},
            remaining_budget=300,
            conflicts=[{"type": "budget", "items": ["item-1", "item-3"]}],
            reason_codes=["selected_mandatory_minimum", "selected_budget_upgrade"],
            policy_version="2.0",
            decision_fingerprint="def456",
        )

        assert decision.selected_item_ids == ["item-1", "item-2"]
        assert decision.excluded_item_ids == ["item-3"]
        assert decision.remaining_budget == 300
        assert decision.policy_version == "2.0"
        assert decision.decision_fingerprint == "def456"
        assert len(decision.conflicts) == 1
        assert len(decision.reason_codes) == 2

    def test_selection_decision_with_empty_lists(self):
        decision = SelectionDecision(
            selected_item_ids=[],
            excluded_item_ids=[],
            representation_requirements={},
            budget_allocations={},
            remaining_budget=1000,
            conflicts=[],
            reason_codes=[],
            policy_version="1.0",
            decision_fingerprint="empty",
        )

        assert decision.selected_item_ids == []
        assert decision.excluded_item_ids == []
        assert decision.representation_requirements == {}
        assert decision.budget_allocations == {}
        assert decision.conflicts == []
        assert decision.reason_codes == []


class TestMemoryDecision:
    """Tests for MemoryDecision frozen dataclass."""

    def test_memory_decision_is_frozen(self):
        decision = MemoryDecision(
            operation="read",
            allowed_scopes=["user"],
            excluded_candidates=[],
            conflict_decisions=[],
            confirmation_required=None,
            reason_codes=["memory_operation_allowed"],
        )

        with pytest.raises(AttributeError):
            decision.operation = "write"

    def test_memory_decision_creation(self):
        decision = MemoryDecision(
            operation="write",
            allowed_scopes=["user", "agent"],
            excluded_candidates=["candidate-1"],
            conflict_decisions=[{"conflict": "scope_overlap", "resolution": "merge"}],
            confirmation_required={"reason": "sensitive_data", "scope": "tenant"},
            reason_codes=["memory_operation_allowed", "confirmation_required"],
        )

        assert decision.operation == "write"
        assert decision.allowed_scopes == ["user", "agent"]
        assert decision.excluded_candidates == ["candidate-1"]
        assert len(decision.conflict_decisions) == 1
        assert decision.confirmation_required is not None
        assert decision.confirmation_required["reason"] == "sensitive_data"
        assert len(decision.reason_codes) == 2
