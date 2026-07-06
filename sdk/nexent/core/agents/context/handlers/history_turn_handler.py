"""Handler for history turn context items."""

from typing import Any, Dict, List

from ..context_item import ContextItem, ContextItemType, RepresentationTier
from ..item_handler import ContextItemHandler
from ..reducer_models import ReductionResult


class HistoryTurnHandler(ContextItemHandler):
    """Scores and reduces conversation history turns."""

    def supported_types(self) -> List[ContextItemType]:
        return [ContextItemType.HISTORY_TURN]

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        # TODO(W13): Implement weighted scoring:
        #   score = recency * 0.5
        #         + has_pending_action * 0.3
        #         + keyword_overlap * 0.2
        #   Signals: item.metadata["run_id"], item.metadata["step_id"],
        #            item.metadata["has_pending_action"]
        return 1.0

    def reduce(
        self, item: ContextItem, target: RepresentationTier, budget: int
    ) -> ReductionResult:
        # TODO(W8): Implement tiered reduction:
        #   COMPRESSED: LLM summary (reuse existing compression logic)
        #   STRUCTURED: user query summary + assistant conclusion (deterministic)
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

    def to_messages(self, item: ContextItem) -> List[Dict[str, Any]]:
        content = item.content or {}
        messages = []
        user_query = content.get("user_query", "")
        if user_query:
            messages.append({"role": "user", "content": [{"type": "text", "text": user_query}]})
        assistant_response = content.get("assistant_response", "")
        if assistant_response:
            messages.append({"role": "assistant", "content": [{"type": "text", "text": assistant_response}]})
        return messages
