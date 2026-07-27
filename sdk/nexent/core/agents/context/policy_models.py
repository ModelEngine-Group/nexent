"""Policy decision models for context selection and memory operations."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .context_item import RepresentationTier


@dataclass(frozen=True)
class SelectionDecision:
    """Immutable record of a context selection policy decision.

    Captures which items were selected or excluded, their representation
    requirements, budget allocations, and the reason codes explaining
    each decision.
    """

    selected_item_ids: List[str]
    excluded_item_ids: List[str]
    representation_requirements: Dict[str, RepresentationTier]
    budget_allocations: Dict[str, int]
    remaining_budget: int
    conflicts: List[Dict[str, Any]]
    reason_codes: List[str]
    policy_version: str
    decision_fingerprint: str


@dataclass(frozen=True)
class MemoryDecision:
    """Immutable record of a memory operation policy decision.

    Captures the allowed operation, scopes, excluded candidates,
    conflict resolutions, and any confirmation requirements.
    """

    operation: str
    allowed_scopes: List[str]
    excluded_candidates: List[str]
    conflict_decisions: List[Dict[str, Any]]
    confirmation_required: Optional[Dict[str, Any]]
    reason_codes: List[str]
