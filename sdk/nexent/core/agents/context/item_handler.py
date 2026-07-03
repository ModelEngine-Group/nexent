"""Abstract base class for context item handlers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from .context_item import ContextItem, ContextItemType, RepresentationTier
from .reducer_models import ReductionResult


class ContextItemHandler(ABC):
    """Base handler providing default passthrough implementations for scoring and reduction."""

    @abstractmethod
    def supported_types(self) -> List[ContextItemType]:
        """Return the list of ContextItemType values this handler supports."""
        ...

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        """Score an item's relevance. Default passthrough returns 1.0."""
        return 1.0

    def reduce(
        self, item: ContextItem, target: RepresentationTier, budget: int
    ) -> ReductionResult:
        """Reduce an item to a target representation. Default passthrough returns content unchanged."""
        return ReductionResult(
            representation=item.current_representation,
            source_fingerprint="",
            token_count=item.token_estimate,
            generator="passthrough",
            generator_version="0.1.0",
            admissible=True,
            loss_metadata={},
            content=item.content,
        )
