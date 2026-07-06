"""Handler for working memory context items."""

from typing import Any, Dict, List

from ..context_item import ContextItem, ContextItemType, RepresentationTier
from ..item_handler import ContextItemHandler
from ..reducer_models import ReductionResult


class WorkingMemoryHandler(ContextItemHandler):
    """Working memory is mandatory and partially reducible."""

    def supported_types(self) -> List[ContextItemType]:
        return [ContextItemType.WORKING_MEMORY]

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        # TODO(W13): Not selectable -- mandatory item, score=inf to guarantee inclusion
        return float("inf")

    def reduce(
        self, item: ContextItem, target: RepresentationTier, budget: int
    ) -> ReductionResult:
        # TODO(W8): Implement tiered reduction:
        #   STRUCTURED: retain active goals + constraints fields, discard details
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

    def to_messages(self, item: ContextItem) -> List[Dict[str, Any]]:
        content = item.content or {}
        wm_type = content.get("type", "working_memory")
        if wm_type == "active_goal":
            text = f"[Active Goal]\n{content.get('text', '')}"
        elif wm_type == "pending_tool_call":
            text = f"[Pending Tool Call: {content.get('tool_call_id', 'unknown')}]\n{content.get('tool_content', '')}"
        else:
            text = f"[Working Memory]\n{content}"
        return [{"role": "user", "content": [{"type": "text", "text": text}]}]
