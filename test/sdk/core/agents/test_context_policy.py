"""Policy, MMR, and stable item selection behavior."""

import pytest
from pydantic import ValidationError

from nexent.core.agents.context import (
    ContextItemInput,
    ContextManager,
    ContextManagerConfig,
    ContextPolicy,
    EmbeddingProviderChain,
    PolicyLayers,
    normalize_context_inputs,
    rank_by_mmr,
    resolve_policy,
    select_context_items,
)
from nexent.core.agents.context.evidence import ContextEvidenceCollector
from nexent.core.context_runtime.contracts import ContextEvidence


def _item(
    item_id: str,
    item_type: str = "knowledge_base",
    *,
    text: str = "content",
    priority: int = 10,
    required: bool = False,
    metadata: dict | None = None,
):
    content = {"text": text}
    if item_type == "history":
        content["role"] = "user"
    return ContextItemInput(
        id=item_id,
        type=item_type,
        content=content,
        priority=priority,
        required=required,
        metadata=metadata or {},
    )


class _Provider:
    def __init__(self, vectors=None, error=None, name="provider"):
        self.vectors = vectors
        self.error = error
        self.calls = 0
        self._name = name

    @property
    def fingerprint(self):
        return self._name

    def embed(self, texts):
        self.calls += 1
        if self.error:
            raise self.error
        return self.vectors[: len(texts)]


def test_default_policy_preserves_all_items_in_stable_layout_order():
    items = normalize_context_inputs([_item("low", priority=1), _item("high", priority=20)])

    selected, decision = select_context_items(items, resolve_policy())

    assert [item.id for item in selected] == ["high", "low"]
    assert decision.excluded_item_ids == ()
    assert {item.reason_code for item in decision.item_decisions} == {"selected_mmr"}


def test_policy_layers_merge_without_a_version_field():
    policy = resolve_policy(PolicyLayers(
        platform={"resolve_conflicts": False},
        tenant={"processing_mode": "semantic_compress"},
        request={"processing_mode": "reduce_then_compress"},
    ))

    assert policy.processing_mode.value == "reduce_then_compress"
    assert policy.resolve_conflicts is False
    with pytest.raises(ValidationError, match="version"):
        ContextPolicy(version="1.0")


def test_required_is_the_only_required_source_and_is_never_scored_or_filtered():
    required_tool = ContextItemInput(
        id="tool", type="tool", content={"name": "tool"}, required=True
    )
    optional_tool = ContextItemInput(
        id="optional-tool", type="tool", content={"name": "optional"}
    )
    items = normalize_context_inputs([required_tool, optional_tool, _item("kb")])
    policy = ContextPolicy(
        processing_mode="reduce_then_compress",
        enabled_item_types=("knowledge_base",),
    )

    selected, decision = select_context_items(items, policy, allow_reduction=True)

    assert {item.id for item in selected} == {"tool", "kb"}
    assert decision.excluded_item_ids == ("optional-tool",)
    with pytest.raises(ValueError, match="must not be scored"):
        selected[0].score()


def test_platform_authority_cannot_be_moved_from_first_position():
    with pytest.raises(ValidationError, match="platform authority must remain highest"):
        resolve_policy(PolicyLayers(request={
            "authority_order": [
                "user", "platform", "tenant", "agent", "tool", "retrieved", "inferred"
            ]
        }))


def test_higher_authority_wins_optional_declared_conflict():
    policy = ContextPolicy(processing_mode="reduce_then_compress")
    items = normalize_context_inputs([
        _item("platform", text="safe", metadata={"conflict_key": "rule", "authority": "platform"}),
        _item("user", text="unsafe", metadata={"conflict_key": "rule", "authority": "user"}),
    ])

    selected, decision = select_context_items(items, policy, allow_reduction=True)

    assert [item.id for item in selected] == ["platform"]
    assert decision.excluded_item_ids == ("user",)


def test_embedding_provider_priority_external_then_cpu_then_none():
    vectors = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    external = _Provider(vectors=vectors, name="external")
    cpu = _Provider(vectors=vectors, name="cpu")
    chain = EmbeddingProviderChain(external=external, cpu=cpu)

    first = chain.embed(["query", "a", "b"])
    assert first.mode == "external"
    assert external.calls == 1 and cpu.calls == 0

    broken_external = _Provider(error=RuntimeError("offline"), name="external")
    second = EmbeddingProviderChain(external=broken_external, cpu=cpu).embed(["query", "a", "b"])
    assert second.mode == "cpu"
    assert second.failures == ("external:RuntimeError",)

    broken_cpu = _Provider(error=RuntimeError("missing"), name="cpu")
    third = EmbeddingProviderChain(external=broken_external, cpu=broken_cpu).embed(["query"])
    assert third.mode == "none"
    assert third.vectors is None


def test_mmr_uses_embedding_relevance_and_penalizes_redundancy():
    items = normalize_context_inputs([
        _item("a", text="same"),
        _item("b", text="duplicate"),
        _item("c", text="different"),
    ])
    provider = _Provider(vectors=[
        [1.0, 0.0],  # query
        [0.8, 0.6],  # a
        [0.8, 0.6],  # b: relevant but redundant
        [0.7, -0.714],  # c: slightly less relevant but novel
    ])

    result = rank_by_mmr(
        items,
        intent="query",
        providers=EmbeddingProviderChain(external=provider),
        lambda_value=0.7,
    )

    assert [scored.item.id for scored in result.scored_items] == ["a", "c", "b"]
    assert result.embedding_mode == "external"


def test_no_embedding_fallback_is_deterministic_and_detects_exact_duplicates():
    items = normalize_context_inputs([
        _item("a", text="same", priority=20),
        _item("b", text="same", priority=10),
        _item("c", text="different", priority=1),
    ])

    result = rank_by_mmr(items, intent="query")

    assert result.embedding_mode == "none"
    assert [scored.item.id for scored in result.scored_items] == ["a", "c", "b"]


def test_manager_evidence_matches_stably_rendered_items():
    manager = ContextManager(ContextManagerConfig(policy_layers={
        "request": {"processing_mode": "passthrough"}
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
    assert run_context.selection_decision.embedding_mode == "none"


def test_optional_representation_is_owned_by_item_and_lazily_cached():
    item = normalize_context_inputs([_item("kb", text="x" * 200)])[0]

    first = item.represent("compact", max_tokens=20, config_fingerprint="policy")
    second = item.represent("compact", max_tokens=20, config_fingerprint="policy")

    assert first is second
    assert first is not None and first.token_estimate < item.token_estimate
    assert item.representation_cache_stats == (1, 1)


def test_required_item_has_only_raw_representation():
    item = normalize_context_inputs([_item("system", "system_prompt", required=True)])[0]

    assert item.supported_representations == ("raw",)
    with pytest.raises(ValueError, match="unsupported representation"):
        item.represent("compact")


def test_reduce_mode_compacts_optional_item_but_keeps_required_item():
    items = normalize_context_inputs([
        _item("required", "system_prompt", text="always", required=True),
        _item("kb", text="x" * 300),
    ])

    selected, decision = select_context_items(
        items,
        ContextPolicy(processing_mode="reduce_then_compress"),
        allow_reduction=True,
        optional_budget_tokens=100,
    )

    assert [item.id for item in selected] == ["required", "kb"]
    assert selected[1].token_estimate <= 100
    kb_decision = next(item for item in decision.item_decisions if item.item_id == "kb")
    assert kb_decision.representation == "compact"


def test_selection_rank_does_not_change_class_defined_context_layout():
    items = normalize_context_inputs([
        _item("history", "history", text="latest", priority=100),
        _item("kb-low", text="low", priority=1),
        _item("system", "system_prompt", text="rules", priority=1, required=True),
        _item("kb-high", text="high", priority=20),
    ])

    selected, _ = select_context_items(items, resolve_policy())

    assert [item.id for item in selected] == ["system", "kb-high", "kb-low", "history"]


def test_loop_evidence_is_aggregated_and_finalized_once():
    collector = ContextEvidenceCollector()
    collector.record_call(ContextEvidence(selected_item_ids=("first",), compression_records=("a",)))
    collector.record_call(ContextEvidence(selected_item_ids=("final",), compression_records=("b",)))

    evidence = collector.finalize(status="completed")

    assert evidence.selected_item_ids == ("final",)
    assert evidence.compression_records == ("a", "b")
    assert evidence.model_call_count == 2
    assert evidence.loop_status == "completed"
    assert collector.finalize(status="error") is evidence


@pytest.mark.parametrize(
    ("mode", "compression_enabled"),
    [
        ("passthrough", False),
        ("semantic_compress", True),
        ("reduce_then_compress", True),
    ],
)
def test_processing_mode_controls_semantic_compression(mode, compression_enabled):
    manager = ContextManager(ContextManagerConfig(policy_layers={
        "request": {"processing_mode": mode}
    }))
    manager._msg_token_count = lambda messages: 0
    calls = []

    def _compress(model, memory, messages, current_run_start_idx, **kwargs):
        calls.append(kwargs["enabled_override"])
        return messages

    manager.compress_if_needed = _compress
    memory = type("Memory", (), {"system_prompt": None, "steps": []})()
    run_context = manager.prepare_run_context(
        memory=memory,
        fallback_system_prompt="fallback",
        items=[_item("system", "system_prompt", required=True)],
    )
    manager.assemble_final_context(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        run_context=run_context,
    )

    assert calls == [compression_enabled]
