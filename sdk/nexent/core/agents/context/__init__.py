"""Context management module for fine-grained context assembly, policy, and reduction."""

from .admissibility_validator import AdmissibilityValidator
from .context_item import (
    AuthorityTier,
    ContextItem,
    ContextItemType,
    RepresentationTier,
)
from .history_projector import HistoryProjector
from .item_handler import ContextItemHandler
from .item_handler_registry import ItemHandlerRegistry
from .policy_models import (
    ContextPolicy,
    MemoryDecision,
    PolicyInvalidError,
    SelectionDecision,
    resolve_policy,
    validate_policy,
)
from .reducer_models import ReductionResult
from .selection_engine import select_context


__all__ = [
    "AdmissibilityValidator",
    "AuthorityTier",
    "ContextItem",
    "ContextItemHandler",
    "ContextItemType",
    "ContextPolicy",
    "HistoryProjector",
    "ItemHandlerRegistry",
    "MemoryDecision",
    "PolicyInvalidError",
    "ReductionResult",
    "RepresentationTier",
    "SelectionDecision",
    "resolve_policy",
    "select_context",
    "validate_policy",
]
