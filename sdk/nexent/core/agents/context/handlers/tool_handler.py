"""Handler for tool context items."""

from typing import Any, Dict, List

from ..context_item import ContextItem, ContextItemType, RepresentationTier
from ..item_handler import ContextItemHandler
from ..reducer_models import ReductionResult


class ToolHandler(ContextItemHandler):
    """Scores and reduces tool definitions based on query relevance and usage."""

    def supported_types(self) -> List[ContextItemType]:
        return [ContextItemType.TOOL]

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        # TODO(W13): Implement weighted scoring:
        #   score = priority * 0.4
        #         + keyword_overlap(query, description) * 0.3
        #         + usage_frequency * 0.3
        #   Boost if tool was called in current run.
        #   Signals: item.metadata["priority"], item.metadata["usage_count"]
        return 1.0

    def reduce(
        self, item: ContextItem, target: RepresentationTier, budget: int
    ) -> ReductionResult:
        # TODO(W8): Implement tiered reduction:
        #   STRUCTURED: template trim - keep name + one-line description + param names
        #   POINTER: keep only name + param count metadata
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
