import pytest
from pydantic import ValidationError

from nexent.core.agents.context import (
    ContextItemInput, ContextManager, ContextManagerConfig, ContextPolicy,
    PolicyLayers, normalize_context_inputs, resolve_policy, select_context_items,
)


def _item(item_id, item_type="knowledge_base", text="content", priority=10):
    return ContextItemInput(
        id=item_id, type=item_type, content={"text": text}, priority=priority,
    )


def test_policy_has_only_passthrough_and_adaptive_compact():
    assert ContextPolicy().processing_mode.value == "passthrough"
    assert ContextPolicy(processing_mode="adaptive_compact").processing_mode.value == "adaptive_compact"
    with pytest.raises(ValidationError):
        ContextPolicy(processing_mode="reduce_then_compress")
    with pytest.raises(ValidationError):
        ContextPolicy(processing_mode="semantic_compress")


def test_policy_layers_merge_without_selection_configuration():
    policy = resolve_policy(PolicyLayers(
        tenant={"processing_mode": "passthrough"},
        request={"processing_mode": "adaptive_compact"},
    ))
    assert policy.processing_mode.value == "adaptive_compact"
    with pytest.raises(ValidationError):
        ContextPolicy(version="1")
    with pytest.raises(ValidationError):
        ContextPolicy(enabled_item_types=("memory",))


def test_selection_never_scores_filters_or_drops_and_uses_stable_layout():
    items = normalize_context_inputs([
        _item("kb:2", text="second", priority=1),
        ContextItemInput(id="system", type="system", content={"text": "system"}),
        _item("kb:1", text="first", priority=20),
    ])
    selected, decision = select_context_items(items, ContextPolicy(processing_mode="adaptive_compact"))
    assert [item.id for item in selected] == ["system", "kb:1", "kb:2"]
    assert decision.selected_item_ids == tuple(item.id for item in selected)
    assert not hasattr(decision, "excluded_item_ids")
    assert not hasattr(decision, "embedding_mode")


def test_manager_passthrough_keeps_raw_items():
    ContextManager(ContextManagerConfig(policy_layers={
        "request": {"processing_mode": "passthrough"}
    }))
    item = normalize_context_inputs([_item("kb", text="x" * 3000)])[0]
    assert item.supported_representations == ("raw", "compact")
    assert item.representation_cache_stats == (0, 0)


def test_compact_has_one_lazy_cached_budget_independent_result():
    item = normalize_context_inputs([_item("kb", text="x" * 3000)])[0]
    first = item.compact()
    second = item.compact()
    assert first is second
    assert first.token_estimate < item.token_estimate
    assert item.representation_cache_stats == (1, 1)
    with pytest.raises(TypeError):
        item.compact(max_tokens=10)
    with pytest.raises(ValueError, match="unsupported representation"):
        item.represent("drop")
