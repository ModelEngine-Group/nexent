"""Quality-first deterministic selection for fine-grained context items."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Sequence

from .models import ContextItem
from .policy import AuthorityTier, ContextPolicy, policy_fingerprint


@dataclass(frozen=True)
class ItemDecision:
    """Explain one selected or excluded item."""

    item_id: str
    selected: bool
    reason_code: str
    score: float


@dataclass(frozen=True)
class SelectionDecision:
    """Explain the exact item set consumed by final rendering."""

    selected_item_ids: tuple[str, ...]
    excluded_item_ids: tuple[str, ...]
    item_decisions: tuple[ItemDecision, ...]
    conflicts: tuple[dict[str, Any], ...]
    policy_version: str
    policy_fingerprint: str
    decision_fingerprint: str


def select_context_items(
    items: Sequence[ContextItem],
    policy: ContextPolicy,
    *,
    query: str = "",
) -> tuple[list[ContextItem], SelectionDecision]:
    """Select and order items without applying budget or representation changes."""

    if not policy.enabled:
        selected = sorted(items, key=lambda item: item.priority, reverse=True)
        return selected, _decision(
            selected,
            (),
            tuple(ItemDecision(item.id, True, "selected_compatibility_default", 0.0) for item in selected),
            (),
            policy,
        )

    enabled_types = set(policy.enabled_item_types)
    required_types = set(policy.required_item_types)
    candidates: list[ContextItem] = []
    excluded: list[ContextItem] = []
    decisions: list[ItemDecision] = []

    for item in items:
        if item.type not in enabled_types and not item.required:
            excluded.append(item)
            decisions.append(ItemDecision(item.id, False, "excluded_policy_disabled", 0.0))
        else:
            candidates.append(item)

    candidates, conflict_excluded, conflicts = _resolve_conflicts(candidates, policy)
    excluded.extend(conflict_excluded)
    decisions.extend(
        ItemDecision(item.id, False, "excluded_lower_authority", 0.0)
        for item in conflict_excluded
    )

    scored = [(item, _score(item, policy, query)) for item in candidates]
    scored.sort(
        key=lambda pair: (
            0 if pair[0].required or pair[0].type in required_types else 1,
            _authority_rank(pair[0], policy),
            -pair[1],
            -pair[0].priority,
            pair[0].id,
        )
    )
    selected = [item for item, _ in scored]
    decisions.extend(
        ItemDecision(
            item.id,
            True,
            "selected_required" if item.required or item.type in required_types else "selected_policy_ranked",
            score,
        )
        for item, score in scored
    )
    selected_ids = {item.id for item in selected}
    decisions.sort(key=lambda decision: (decision.item_id not in selected_ids, decision.item_id))
    return selected, _decision(selected, excluded, tuple(decisions), tuple(conflicts), policy)


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
        fingerprints = {_content_fingerprint(item) for item in group}
        if len(fingerprints) <= 1:
            kept.extend(group)
            continue
        ordered = sorted(group, key=lambda item: (_authority_rank(item, policy), item.id))
        winning_rank = _authority_rank(ordered[0], policy)
        winners = [item for item in ordered if _authority_rank(item, policy) == winning_rank]
        losers = [item for item in ordered if item not in winners and not item.required]
        required_losers = [item for item in ordered if item not in winners and item.required]
        kept.extend(winners + required_losers)
        excluded.extend(losers)
        conflicts.append({
            "conflict_key": key,
            "kept_item_ids": tuple(item.id for item in winners + required_losers),
            "excluded_item_ids": tuple(item.id for item in losers),
            "reason_code": "authority_conflict_unresolved" if len(winners) > 1 else "lower_authority_excluded",
        })
    return kept, excluded, conflicts


def _score(item: ContextItem, policy: ContextPolicy, query: str) -> float:
    type_weight = policy.type_weights.get(item.type, 1.0)
    trust = max((policy.source_trust.get(source, 1.0) for source in item.source), default=1.0)
    relevance = _relevance(item, query)
    recency = float(item.metadata.get("recency", 0.0))
    return float(item.priority) + type_weight + trust + policy.relevance_weight * relevance + policy.recency_weight * recency


def _relevance(item: ContextItem, query: str) -> float:
    query_terms = set(_terms(query))
    if not query_terms:
        return 0.0
    content_terms = set(_terms(json.dumps(item.content, ensure_ascii=False, default=str)))
    return len(query_terms & content_terms) / len(query_terms)


def _terms(value: str) -> list[str]:
    return re.findall(r"[\w\u4e00-\u9fff]+", value.lower())


def _authority_rank(item: ContextItem, policy: ContextPolicy) -> int:
    raw = item.metadata.get("authority", AuthorityTier.INFERRED.value)
    try:
        authority = AuthorityTier(raw)
    except ValueError:
        authority = AuthorityTier.INFERRED
    return policy.authority_order.index(authority)


def _content_fingerprint(item: ContextItem) -> str:
    encoded = json.dumps(item.content, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _decision(
    selected: Sequence[ContextItem],
    excluded: Sequence[ContextItem],
    item_decisions: tuple[ItemDecision, ...],
    conflicts: tuple[dict[str, Any], ...],
    policy: ContextPolicy,
) -> SelectionDecision:
    payload = {
        "selected": [item.id for item in selected],
        "excluded": [item.id for item in excluded],
        "item_decisions": [decision.__dict__ for decision in item_decisions],
        "conflicts": conflicts,
        "policy_version": policy.version,
        "policy_fingerprint": policy_fingerprint(policy),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return SelectionDecision(
        selected_item_ids=tuple(payload["selected"]),
        excluded_item_ids=tuple(payload["excluded"]),
        item_decisions=item_decisions,
        conflicts=conflicts,
        policy_version=policy.version,
        policy_fingerprint=payload["policy_fingerprint"],
        decision_fingerprint=sha256(encoded.encode("utf-8")).hexdigest(),
    )
