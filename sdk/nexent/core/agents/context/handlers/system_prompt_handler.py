"""Handler for system prompt context items."""

from typing import Any, Dict, List

from ..context_item import ContextItem, ContextItemType, RepresentationTier
from ..item_handler import ContextItemHandler
from ..reducer_models import ReductionResult


class SystemPromptHandler(ContextItemHandler):
    """System prompts are mandatory and irreducible."""

    def supported_types(self) -> List[ContextItemType]:
        return [ContextItemType.SYSTEM_PROMPT]

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        # TODO: Not selectable -- mandatory item, score=inf to guarantee inclusion
        return float("inf")

    def reduce(
        self, item: ContextItem, target: RepresentationTier, budget: int
    ) -> ReductionResult:
        # TODO: Not reducible -- minimum_fidelity=FULL, reject any reduction attempt
        # Suggested: raise MinimumFidelityViolation if target != FULL
        return ReductionResult(
            representation=RepresentationTier.FULL,
            source_fingerprint="",
            token_count=item.token_estimate,
            generator="passthrough",
            generator_version="0.1.0",
            admissible=True,
            loss_metadata={},
            content=item.content,
        )
