"""Deterministic required/optional selection with MMR diagnostics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Sequence

from .models import ContextItem
from .policy import AuthorityTier, ContextPolicy, policy_fingerprint
from .scoring import EmbeddingProviderChain, rank_by_mmr


@dataclass(frozen=True)
class ItemDecision:
    item_id: str
    selected: bool
    reason_code: str
    relevance_score: float | None = None
    marginal_relevance: float | None = None
    selection_rank: int | None = None
    representation: str | None = None


@dataclass(frozen=True)
class SelectionDecision:
    selected_item_ids: tuple[str, ...]
    excluded_item_ids: tuple[str, ...]
    item_decisions: tuple[ItemDecision, ...]
    conflicts: tuple[dict[str, Any], ...]
    policy_fingerprint: str
    decision_fingerprint: str
    embedding_mode: str = "none"
    embedding_provider_fingerprint: str | None = None
    embedding_failures: tuple[str, ...] = ()
    representation_cache_hits: int = 0
    representation_cache_misses: int = 0


def select_context_items(
    items: Sequence[ContextItem],
    policy: ContextPolicy,
    *,
    query: str = "",
    providers: EmbeddingProviderChain | None = None,
    mmr_lambda: float = 0.7,
    allow_reduction: bool = False,
    marginal_threshold: float = 0.0,
    optional_budget_tokens: int | None = None,
) -> tuple[list[ContextItem], SelectionDecision]:
    """Select items, then restore their class-defined stable layout order."""

    required = [item for item in items if item.required]
    optional = [item for item in items if not item.required]
    decisions: list[ItemDecision] = [
        ItemDecision(item.id, True, "selected_required") for item in required
    ]
    excluded: list[ContextItem] = []
    conflicts: list[dict[str, Any]] = []

    if allow_reduction:
        enabled_types = set(policy.enabled_item_types)
        disabled = [item for item in optional if item.type not in enabled_types]
        optional = [item for item in optional if item.type in enabled_types]
        excluded.extend(disabled)
        decisions.extend(
            ItemDecision(item.id, False, "excluded_policy_disabled") for item in disabled
        )
        optional, conflict_excluded, conflicts = _resolve_conflicts(optional, policy)
        excluded.extend(conflict_excluded)
        decisions.extend(
            ItemDecision(item.id, False, "excluded_lower_authority")
            for item in conflict_excluded
        )

    mmr = rank_by_mmr(
        optional,
        intent=query,
        providers=providers,
        lambda_value=mmr_lambda,
    )
    selected_optional: list[ContextItem] = []
    remaining_budget = optional_budget_tokens
    for scored in mmr.scored_items:
        selected = not allow_reduction or scored.marginal_relevance >= marginal_threshold
        represented = None
        representation = None
        reason = "selected_mmr"
        if selected:
            if allow_reduction and remaining_budget is not None:
                if scored.item.token_estimate <= remaining_budget:
                    representation = "raw"
                    represented = scored.item.represent("raw")
                elif "compact" in scored.item.supported_representations and remaining_budget > 0:
                    representation = "compact"
                    represented = scored.item.represent(
                        "compact",
                        max_tokens=remaining_budget,
                        config_fingerprint=f"budget:{optional_budget_tokens}",
                    )
                    if represented is not None and represented.token_estimate > remaining_budget:
                        represented = None
                if represented is None:
                    selected = False
                    representation = "drop"
                    scored.item.represent("drop")
                    reason = "excluded_optional_budget"
                else:
                    remaining_budget -= represented.token_estimate
                    reason = f"selected_{representation}"
            else:
                representation = "raw"
                represented = scored.item.represent("raw")
        else:
            reason = "excluded_low_marginal_relevance"
        decisions.append(ItemDecision(
            item_id=scored.item.id,
            selected=selected,
            reason_code=reason,
            relevance_score=scored.relevance,
            marginal_relevance=scored.marginal_relevance,
            selection_rank=scored.selection_rank,
            representation=representation,
        ))
        if selected:
            selected_optional.append(represented or scored.item)
        else:
            excluded.append(scored.item)

    selected = sorted([*required, *selected_optional], key=lambda item: item.layout_key)
    decisions.sort(key=lambda decision: decision.item_id)
    return selected, _decision(
        selected,
        excluded,
        tuple(decisions),
        tuple(conflicts),
        policy,
        embedding_mode=mmr.embedding_mode,
        provider_fingerprint=mmr.provider_fingerprint,
        embedding_failures=mmr.embedding_failures,
        representation_cache_hits=sum(item.representation_cache_stats[0] for item in optional),
        representation_cache_misses=sum(item.representation_cache_stats[1] for item in optional),
    )


def _resolve_conflicts(
    items: Sequence[ContextItem], policy: ContextPolicy
) -> tuple[list[ContextItem], list[ContextItem], list[dict[str, Any]]]:
    if not policy.resolve_conflicts:
        return list(items), [], []
    grouped: dict[str, list[ContextItem]] = {}
    passthrough: list[ContextItem] = []
    for item in items:
        key = item.metadata.get("conflict_key")
        if key is None:
            passthrough.append(item)
        else:
            grouped.setdefault(str(key), []).append(item)

    kept = list(passthrough)
    excluded: list[ContextItem] = []
    conflicts: list[dict[str, Any]] = []
    for key in sorted(grouped):
        group = grouped[key]
        if len({item.content_fingerprint for item in group}) <= 1:
            kept.extend(group)
            continue
        ordered = sorted(group, key=lambda item: (_authority_rank(item, policy), item.id))
        winning_rank = _authority_rank(ordered[0], policy)
        winners = [item for item in ordered if _authority_rank(item, policy) == winning_rank]
        losers = [item for item in ordered if item not in winners]
        kept.extend(winners)
        excluded.extend(losers)
        conflicts.append({
            "conflict_key": key,
            "kept_item_ids": tuple(item.id for item in winners),
            "excluded_item_ids": tuple(item.id for item in losers),
            "reason_code": (
                "authority_conflict_unresolved" if len(winners) > 1
                else "lower_authority_excluded"
            ),
        })
    return kept, excluded, conflicts


def _authority_rank(item: ContextItem, policy: ContextPolicy) -> int:
    raw = item.metadata.get("authority", AuthorityTier.INFERRED.value)
    try:
        authority = AuthorityTier(raw)
    except ValueError:
        authority = AuthorityTier.INFERRED
    return policy.authority_order.index(authority)


def _decision(
    selected: Sequence[ContextItem],
    excluded: Sequence[ContextItem],
    item_decisions: tuple[ItemDecision, ...],
    conflicts: tuple[dict[str, Any], ...],
    policy: ContextPolicy,
    *,
    embedding_mode: str,
    provider_fingerprint: str | None,
    embedding_failures: tuple[str, ...],
    representation_cache_hits: int,
    representation_cache_misses: int,
) -> SelectionDecision:
    payload = {
        "selected": [item.id for item in selected],
        "excluded": [item.id for item in excluded],
        "item_decisions": [decision.__dict__ for decision in item_decisions],
        "conflicts": conflicts,
        "policy_fingerprint": policy_fingerprint(policy),
        "embedding_mode": embedding_mode,
        "embedding_provider_fingerprint": provider_fingerprint,
        "embedding_failures": embedding_failures,
        "representation_cache_hits": representation_cache_hits,
        "representation_cache_misses": representation_cache_misses,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return SelectionDecision(
        selected_item_ids=tuple(payload["selected"]),
        excluded_item_ids=tuple(payload["excluded"]),
        item_decisions=item_decisions,
        conflicts=conflicts,
        policy_fingerprint=payload["policy_fingerprint"],
        decision_fingerprint=sha256(encoded.encode("utf-8")).hexdigest(),
        embedding_mode=embedding_mode,
        embedding_provider_fingerprint=provider_fingerprint,
        embedding_failures=embedding_failures,
        representation_cache_hits=representation_cache_hits,
        representation_cache_misses=representation_cache_misses,
    )
