"""Handler for system prompt context items."""

from typing import Any, Dict, List

from ..context_item import ContextItem, ContextItemType, RepresentationTier
from ..item_handler import ContextItemHandler
from ..reducer_models import ReductionResult
from ._utils import fingerprint, token_estimate


_GENERATOR = "system_prompt_passthrough"
_VERSION = "1.0.0"


class SystemPromptHandler(ContextItemHandler):
    """System prompts are mandatory and irreducible."""

    def supported_types(self) -> List[ContextItemType]:
        return [ContextItemType.SYSTEM_PROMPT]

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        return float("inf")

    def reduce(
        self, item: ContextItem, target: RepresentationTier, budget: int
    ) -> ReductionResult:
        content = item.content
        fp = fingerprint(content)

        if target != RepresentationTier.FULL:
            return ReductionResult(
                representation=RepresentationTier.FULL,
                source_fingerprint=fp,
                token_count=token_estimate(content),
                generator=_GENERATOR,
                generator_version=_VERSION,
                admissible=False,
                loss_metadata={"reason": "system_prompt_irreducible"},
                content=content,
            )

        return ReductionResult(
            representation=RepresentationTier.FULL,
            source_fingerprint=fp,
            token_count=token_estimate(content),
            generator=_GENERATOR,
            generator_version=_VERSION,
            admissible=True,
            loss_metadata={},
            content=content,
        )
