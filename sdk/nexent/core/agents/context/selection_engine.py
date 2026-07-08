"""Deterministic non-memory context item selection engine."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from . import reason_codes
from .context_item import AuthorityTier, ContextItem, RepresentationTier
from .item_handler import ContextItemHandler
from .item_handler_registry import ItemHandlerRegistry
from .policy_models import ContextPolicy, SelectionDecision


_TIER_RANK: Dict[RepresentationTier, int] = {
    RepresentationTier.POINTER: 0,
    RepresentationTier.STRUCTURED: 1,
    RepresentationTier.COMPRESSED: 2,
    RepresentationTier.FULL: 3,
}

_RANK_TIER: Dict[int, RepresentationTier] = {rank: tier for tier, rank in _TIER_RANK.items()}

_TIER_COST_RATIO: Dict[RepresentationTier, float] = {
    RepresentationTier.POINTER: 0.05,
    RepresentationTier.STRUCTURED: 0.2,
    RepresentationTier.COMPRESSED: 0.35,
    RepresentationTier.FULL: 1.0,
}


@dataclass(frozen=True)
class _ScoredItem:
    """Internal deterministic scoring record."""

    item: ContextItem
    score: float
    authority_rank: int
    minimum_tier: RepresentationTier
    minimum_cost: int


def select_context(
    policy: ContextPolicy,
    context_items: Sequence[ContextItem],
    safe_input_budget: int,
    *,
    query: str = "",
    context: Dict[str, Any] | None = None,
) -> "SelectionDecision":
    """Select context items and representation tiers within a safe input budget.

    The engine is intentionally non-memory-specific. Memory items may be selected
    or excluded as ordinary ContextItems, but memory retrieval/write policy is
    deferred until the memory module refactor lands.
    """

    budget = min(_non_negative(safe_input_budget), _policy_budget(policy, safe_input_budget))
    runtime_context = {"policy": policy, "safe_input_budget": budget, **(context or {})}

    selected_item_ids: List[str] = []
    excluded_item_ids: List[str] = []
    representation_requirements: Dict[str, RepresentationTier] = {}
    budget_allocations: Dict[str, int] = {}
    conflicts: List[Dict[str, Any]] = []
    decision_reasons: List[str] = []

    enabled_types = set(policy.enabled_item_types)
    mandatory_types = set(policy.mandatory_item_types)

    enabled_items: List[ContextItem] = []
    for item in _stable_items(context_items):
        if item.item_type not in enabled_types:
            excluded_item_ids.append(item.item_id)
            _append_reason(decision_reasons, reason_codes.EXCLUDED_POLICY_DISABLED)
            continue
        enabled_items.append(item)

    conflict_filtered_items, conflict_excluded_ids, conflict_records, conflict_reasons = _resolve_authority_conflicts(
        policy,
        enabled_items,
    )
    excluded_item_ids.extend(conflict_excluded_ids)
    conflicts.extend(conflict_records)
    for reason in conflict_reasons:
        _append_reason(decision_reasons, reason)

    scored_items = [_score_item(policy, item, query, runtime_context) for item in conflict_filtered_items]
    mandatory_items = [scored for scored in scored_items if scored.item.item_type in mandatory_types]
    optional_items = [scored for scored in scored_items if scored.item.item_type not in mandatory_types]

    remaining_budget = budget
    for scored in _sort_for_selection(mandatory_items):
        selected_item_ids.append(scored.item.item_id)
        representation_requirements[scored.item.item_id] = scored.minimum_tier
        budget_allocations[scored.item.item_id] = scored.minimum_cost
        remaining_budget -= scored.minimum_cost
        _append_reason(decision_reasons, reason_codes.SELECTED_MANDATORY_MINIMUM)

    if remaining_budget < 0:
        conflicts.append(
            {
                "type": reason_codes.MANDATORY_BUDGET_IMPOSSIBLE,
                "required_budget": sum(budget_allocations.values()),
                "available_budget": budget,
                "item_ids": [scored.item.item_id for scored in mandatory_items],
            }
        )
        _append_reason(decision_reasons, reason_codes.MANDATORY_BUDGET_IMPOSSIBLE)
        for scored in _sort_for_selection(optional_items):
            excluded_item_ids.append(scored.item.item_id)
        return _make_decision(
            selected_item_ids=selected_item_ids,
            excluded_item_ids=excluded_item_ids,
            representation_requirements=representation_requirements,
            budget_allocations=budget_allocations,
            remaining_budget=0,
            conflicts=conflicts,
            reason_codes=decision_reasons,
            policy_version=policy.policy_version,
        )

    selected_scored_items: List[_ScoredItem] = list(mandatory_items)
    for scored in _sort_for_selection(optional_items):
        if scored.minimum_cost <= remaining_budget:
            selected_item_ids.append(scored.item.item_id)
            selected_scored_items.append(scored)
            representation_requirements[scored.item.item_id] = scored.minimum_tier
            budget_allocations[scored.item.item_id] = scored.minimum_cost
            remaining_budget -= scored.minimum_cost
            _append_reason(decision_reasons, reason_codes.SELECTED_BUDGET_UPGRADE)
        else:
            excluded_item_ids.append(scored.item.item_id)
            _append_reason(decision_reasons, reason_codes.EXCLUDED_BUDGET)

    remaining_budget = _upgrade_selected_items(
        selected_items=_sort_for_selection(selected_scored_items),
        representation_requirements=representation_requirements,
        budget_allocations=budget_allocations,
        remaining_budget=remaining_budget,
        reason_codes_out=decision_reasons,
    )

    return _make_decision(
        selected_item_ids=selected_item_ids,
        excluded_item_ids=excluded_item_ids,
        representation_requirements=representation_requirements,
        budget_allocations=budget_allocations,
        remaining_budget=remaining_budget,
        conflicts=conflicts,
        reason_codes=decision_reasons,
        policy_version=policy.policy_version,
    )


def _score_item(
    policy: ContextPolicy,
    item: ContextItem,
    query: str,
    context: Dict[str, Any],
) -> _ScoredItem:
    """Score one item with its registered type handler."""

    handler = _get_handler(item)
    minimum_tier = _minimum_tier(policy, item)
    return _ScoredItem(
        item=item,
        score=handler.score(item, query, context),
        authority_rank=_authority_rank(policy.authority_order, item.authority_tier),
        minimum_tier=minimum_tier,
        minimum_cost=_estimate_tier_tokens(item, minimum_tier),
    )


def _resolve_authority_conflicts(
    policy: ContextPolicy,
    items: Sequence[ContextItem],
) -> tuple[List[ContextItem], List[str], List[Dict[str, Any]], List[str]]:
    """Resolve explicit conflicts declared with item.metadata["conflict_key"]."""

    grouped: Dict[tuple[str, str], List[ContextItem]] = {}
    passthrough_items: List[ContextItem] = []
    for item in items:
        conflict_key = item.metadata.get("conflict_key")
        if not conflict_key:
            passthrough_items.append(item)
            continue
        grouped.setdefault((item.item_type.value, str(conflict_key)), []).append(item)

    kept_items = list(passthrough_items)
    excluded_item_ids: List[str] = []
    conflicts: List[Dict[str, Any]] = []
    reasons: List[str] = []

    for (item_type, conflict_key), group in sorted(grouped.items(), key=lambda entry: entry[0]):
        if len({_content_fingerprint(item.content) for item in group}) <= 1:
            kept_items.extend(group)
            continue

        ranked = sorted(group, key=lambda item: (_authority_rank(policy.authority_order, item.authority_tier), item.item_id))
        best_rank = _authority_rank(policy.authority_order, ranked[0].authority_tier)
        winners = [item for item in ranked if _authority_rank(policy.authority_order, item.authority_tier) == best_rank]
        losers = [item for item in ranked if item not in winners]

        kept_items.extend(winners)
        excluded_item_ids.extend(item.item_id for item in losers)
        if losers:
            reasons.append(reason_codes.EXCLUDED_LOWER_AUTHORITY)

        conflict_type = (
            reason_codes.AUTHORITY_CONFLICT_UNRESOLVED
            if len({_content_fingerprint(item.content) for item in winners}) > 1
            else reason_codes.EXCLUDED_LOWER_AUTHORITY
        )
        if conflict_type == reason_codes.AUTHORITY_CONFLICT_UNRESOLVED:
            reasons.append(reason_codes.AUTHORITY_CONFLICT_UNRESOLVED)

        conflicts.append(
            {
                "type": conflict_type,
                "item_type": item_type,
                "conflict_key": conflict_key,
                "kept_item_ids": [item.item_id for item in winners],
                "excluded_item_ids": [item.item_id for item in losers],
            }
        )

    return _stable_items(kept_items), sorted(excluded_item_ids), conflicts, reasons


def _content_fingerprint(content: Any) -> str:
    """Return a stable fingerprint for conflict comparison."""

    encoded = json.dumps(content, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _get_handler(item: ContextItem) -> ContextItemHandler:
    """Return a handler, lazily registering built-ins if the registry is empty."""

    try:
        return ItemHandlerRegistry.get(item.item_type)
    except KeyError:
        from .handlers import register_all

        register_all()
        return ItemHandlerRegistry.get(item.item_type)


def _minimum_tier(policy: ContextPolicy, item: ContextItem) -> RepresentationTier:
    """Return the stricter minimum tier from item metadata and policy."""

    policy_tier = policy.minimum_fidelity_by_type.get(item.item_type, item.minimum_fidelity)
    return _max_tier(item.minimum_fidelity, policy_tier)


def _max_tier(left: RepresentationTier, right: RepresentationTier) -> RepresentationTier:
    """Return the higher-fidelity tier."""

    return left if _TIER_RANK[left] >= _TIER_RANK[right] else right


def _estimate_tier_tokens(item: ContextItem, tier: RepresentationTier) -> int:
    """Estimate token cost for an item at a representation tier."""

    base_tokens = max(0, item.token_estimate)
    if base_tokens == 0:
        return 0
    return max(1, int(round(base_tokens * _TIER_COST_RATIO[tier])))


def _upgrade_selected_items(
    *,
    selected_items: Sequence[_ScoredItem],
    representation_requirements: Dict[str, RepresentationTier],
    budget_allocations: Dict[str, int],
    remaining_budget: int,
    reason_codes_out: List[str],
) -> int:
    """Spend remaining budget on deterministic fidelity upgrades."""

    upgraded = True
    while upgraded:
        upgraded = False
        for scored in selected_items:
            item_id = scored.item.item_id
            current_tier = representation_requirements[item_id]
            next_tier = _next_tier(current_tier, scored.item.current_representation)
            if next_tier is None:
                continue

            next_cost = _estimate_tier_tokens(scored.item, next_tier)
            additional_cost = next_cost - budget_allocations[item_id]
            if additional_cost <= remaining_budget:
                representation_requirements[item_id] = next_tier
                budget_allocations[item_id] = next_cost
                remaining_budget -= additional_cost
                upgraded = True
                _append_reason(reason_codes_out, reason_codes.SELECTED_BUDGET_UPGRADE)

    return remaining_budget


def _next_tier(current: RepresentationTier, maximum: RepresentationTier) -> RepresentationTier | None:
    """Return the next higher tier up to the current available representation."""

    next_rank = _TIER_RANK[current] + 1
    if next_rank > _TIER_RANK[maximum]:
        return None
    return _RANK_TIER[next_rank]


def _sort_for_selection(scored_items: Sequence[_ScoredItem]) -> List[_ScoredItem]:
    """Sort items deterministically by policy priority and stable tie breakers."""

    return sorted(
        scored_items,
        key=lambda scored: (
            scored.authority_rank,
            -scored.score,
            scored.minimum_cost,
            scored.item.item_id,
        ),
    )


def _stable_items(context_items: Sequence[ContextItem]) -> List[ContextItem]:
    """Return context items in deterministic item_id order."""

    return sorted(context_items, key=lambda item: item.item_id)


def _authority_rank(authority_order: Sequence[AuthorityTier], authority: AuthorityTier) -> int:
    """Return rank for an authority tier, unknown authorities last."""

    try:
        return list(authority_order).index(authority)
    except ValueError:
        return len(authority_order)


def _policy_budget(policy: ContextPolicy, safe_input_budget: int) -> int:
    """Return the effective budget imposed by policy and caller safety limit."""

    if policy.max_input_budget is None:
        return _non_negative(safe_input_budget)
    return _non_negative(policy.max_input_budget)


def _non_negative(value: int) -> int:
    """Clamp an integer budget to zero or higher."""

    return max(0, int(value))


def _append_reason(reasons: List[str], reason: str) -> None:
    """Append a reason code once while preserving insertion order."""

    if reason not in reasons:
        reasons.append(reason)


def _make_decision(
    *,
    selected_item_ids: List[str],
    excluded_item_ids: List[str],
    representation_requirements: Dict[str, RepresentationTier],
    budget_allocations: Dict[str, int],
    remaining_budget: int,
    conflicts: List[Dict[str, Any]],
    reason_codes: List[str],
    policy_version: str,
) -> "SelectionDecision":
    """Build a SelectionDecision with a deterministic fingerprint."""

    from .policy_models import SelectionDecision

    fingerprint_payload = {
        "selected_item_ids": selected_item_ids,
        "excluded_item_ids": excluded_item_ids,
        "representation_requirements": {
            item_id: tier.value for item_id, tier in sorted(representation_requirements.items())
        },
        "budget_allocations": dict(sorted(budget_allocations.items())),
        "remaining_budget": remaining_budget,
        "conflicts": conflicts,
        "reason_codes": reason_codes,
        "policy_version": policy_version,
    }
    encoded = json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"), default=str)
    return SelectionDecision(
        selected_item_ids=selected_item_ids,
        excluded_item_ids=excluded_item_ids,
        representation_requirements=representation_requirements,
        budget_allocations=budget_allocations,
        remaining_budget=remaining_budget,
        conflicts=conflicts,
        reason_codes=reason_codes,
        policy_version=policy_version,
        decision_fingerprint=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    )
