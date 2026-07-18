"""Policy layering and selection behavior for the unified context domain."""

import pytest
from pydantic import ValidationError

from nexent.core.agents.context import (
    ContextItemInput,
    ContextManager,
    ContextManagerConfig,
    ContextPolicy,
    PolicyLayers,
    normalize_context_inputs,
    resolve_policy,
    select_context_items,
)


def _item(
    item_id: str,
    item_type: str = "knowledge_base",
    *,
    text: str = "content",
    priority: int = 10,
    required: bool = False,
    metadata: dict | None = None,
):
    return ContextItemInput(
        id=item_id,
        type=item_type,
        content={"text": text},
        priority=priority,
        required=required,
        metadata=metadata or {},
    )


def test_default_policy_preserves_phase4_selection_and_order():
    items = normalize_context_inputs([
        _item("low", priority=1),
        _item("high", priority=20),
    ])

    selected, decision = select_context_items(items, resolve_policy())

    assert [item.id for item in selected] == ["high", "low"]
    assert decision.excluded_item_ids == ()
    assert {item.reason_code for item in decision.item_decisions} == {
        "selected_compatibility_default"
    }


def test_policy_layers_merge_in_documented_precedence():
    policy = resolve_policy(PolicyLayers(
        platform={"version": "1.0", "source_trust": {"kb": 1.0}},
        tenant={"version": "1.1", "source_trust": {"tenant": 2.0}},
        agent={"version": "1.2", "relevance_weight": 2.0},
        request={"version": "1.3", "enabled": True},
    ))

    assert policy.enabled is True
    assert policy.version == "1.3"
    assert policy.relevance_weight == 2.0
    assert policy.source_trust == {"kb": 1.0, "tenant": 2.0}


def test_required_system_type_cannot_be_disabled():
    with pytest.raises(ValidationError, match="required context item types cannot be disabled"):
        resolve_policy(PolicyLayers(request={
            "enabled": True,
            "enabled_item_types": ["knowledge_base"],
        }))


def test_unknown_policy_version_and_untrusted_platform_override_are_rejected():
    with pytest.raises(ValidationError, match="unsupported context policy major"):
        resolve_policy(PolicyLayers(request={"version": "2.0"}))
    with pytest.raises(ValidationError, match="platform authority must remain highest"):
        resolve_policy(PolicyLayers(request={
            "authority_order": [
                "user", "platform", "tenant", "agent", "tool", "retrieved", "inferred"
            ]
        }))


def test_enabled_policy_filters_types_and_keeps_explicit_required_item():
    policy = ContextPolicy(
        enabled=True,
        enabled_item_types=("system_prompt", "knowledge_base"),
    )
    items = normalize_context_inputs([
        _item("system", "system_prompt", required=True),
        _item("kb"),
        ContextItemInput(
            id="required-tool",
            type="tool",
            content={"name": "required"},
            required=True,
        ),
        ContextItemInput(id="tool", type="tool", content={"name": "optional"}),
    ])

    selected, decision = select_context_items(items, policy)

    assert {item.id for item in selected} == {"system", "kb", "required-tool"}
    assert decision.excluded_item_ids == ("tool",)


def test_higher_authority_wins_declared_conflict_but_required_is_never_dropped():
    policy = ContextPolicy(enabled=True)
    items = normalize_context_inputs([
        _item("platform", text="safe", metadata={"conflict_key": "rule", "authority": "platform"}),
        _item("user", text="unsafe", metadata={"conflict_key": "rule", "authority": "user"}),
        _item(
            "required-user",
            text="required",
            required=True,
            metadata={"conflict_key": "rule", "authority": "user"},
        ),
    ])

    selected, decision = select_context_items(items, policy)

    assert {item.id for item in selected} == {"platform", "required-user"}
    assert decision.excluded_item_ids == ("user",)
    assert decision.conflicts[0]["reason_code"] == "lower_authority_excluded"


def test_manager_evidence_matches_items_sent_to_renderer():
    manager = ContextManager(ContextManagerConfig(policy_layers={
        "request": {
            "enabled": True,
            "enabled_item_types": ["system_prompt", "knowledge_base"],
        }
    }))
    items = [_item("system", "system_prompt", required=True), _item("kb")]

    run_context = manager.prepare_run_context(
        memory=type("Memory", (), {"system_prompt": None})(),
        fallback_system_prompt="fallback",
        items=items,
    )

    assert run_context.selection_decision.selected_item_ids == tuple(
        item.id for item in run_context.items
    )
    assert run_context.selection_decision.policy_version == "1.0"
