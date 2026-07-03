"""Handler for tool call result context items."""

from typing import Any, Dict, List

from ..context_item import ContextItem, ContextItemType, RepresentationTier
from ..item_handler import ContextItemHandler
from ..reducer_models import ReductionResult


class ToolCallResultHandler(ContextItemHandler):
    """Scores and reduces tool call results from the current conversation."""

    def supported_types(self) -> List[ContextItemType]:
        return [ContextItemType.TOOL_CALL_RESULT]

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        # TODO(W13): Implement weighted scoring:
        #   score = recency * 0.4
        #         + is_active_tool * 0.4
        #         + result_relevance * 0.2
        #   Signals: item.metadata["run_id"], item.metadata["tool_name"]
        return 1.0

    def reduce(
        self, item: ContextItem, target: RepresentationTier, budget: int
    ) -> ReductionResult:
        # TODO(W8): Implement tiered reduction:
        #   STRUCTURED: tool name + result summary (deterministic)
        #   POINTER: tool name + status only (deterministic)
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
