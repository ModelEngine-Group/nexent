"""Stable layout only; relevance selection and item deletion are intentionally absent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .models import ContextItem
from .policy import ContextPolicy, policy_fingerprint


@dataclass(frozen=True)
class ItemDecision:
    item_id: str
    representation: str = "raw"


@dataclass(frozen=True)
class SelectionDecision:
    selected_item_ids: tuple[str, ...]
    item_decisions: tuple[ItemDecision, ...]
    policy_fingerprint: str
    representation_cache_hits: int = 0
    representation_cache_misses: int = 0


def select_context_items(
    items: Sequence[ContextItem], policy: ContextPolicy, **_: object,
) -> tuple[list[ContextItem], SelectionDecision]:
    """Preserve every item and apply only the class-defined stable layout."""
    selected = sorted(items, key=lambda item: item.layout_key)
    return selected, SelectionDecision(
        selected_item_ids=tuple(item.id for item in selected),
        item_decisions=tuple(ItemDecision(item.id) for item in selected),
        policy_fingerprint=policy_fingerprint(policy),
    )
