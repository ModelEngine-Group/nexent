"""Handler for external agent context items."""

from typing import Any, Dict, List

from ..context_item import ContextItem, ContextItemType, RepresentationTier
from ..item_handler import ContextItemHandler
from ..reducer_models import ReductionResult


class ExternalAgentHandler(ContextItemHandler):
    """Scores and reduces external A2A agent definitions."""

    def supported_types(self) -> List[ContextItemType]:
        return [ContextItemType.EXTERNAL_AGENT]

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        # TODO(W13): Implement scoring:
        #   score = keyword_overlap(query, description) * 0.5
        #         + priority * 0.5
        return 1.0

    def reduce(
        self, item: ContextItem, target: RepresentationTier, budget: int
    ) -> ReductionResult:
        # TODO(W8): Implement tiered reduction:
        #   STRUCTURED: name + routing metadata (description + capability tags)
        #   POINTER: name + capability tags only
        #   Deterministic, no LLM call needed.
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
