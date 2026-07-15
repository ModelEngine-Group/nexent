"""Handler for system prompt context items."""

import hashlib
from typing import Any, Dict, List

from ..context_item import ContextItem, ContextItemType, RepresentationTier
from ..item_handler import ContextItemHandler
from ..reducer_models import ReductionResult


_GENERATOR = "system_prompt_passthrough"
_VERSION = "1.0.0"


def _fingerprint(content: Any) -> str:
    return hashlib.sha256(str(content).encode()).hexdigest()[:16]


def _token_estimate(content: Any) -> int:
    return len(str(content)) // 4


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
        fp = _fingerprint(content)

        if target != RepresentationTier.FULL:
            return ReductionResult(
                representation=RepresentationTier.FULL,
                source_fingerprint=fp,
                token_count=_token_estimate(content),
                generator=_GENERATOR,
                generator_version=_VERSION,
                admissible=False,
                loss_metadata={"reason": "system_prompt_irreducible"},
                content=content,
            )

        return ReductionResult(
            representation=RepresentationTier.FULL,
            source_fingerprint=fp,
            token_count=_token_estimate(content),
            generator=_GENERATOR,
            generator_version=_VERSION,
            admissible=True,
            loss_metadata={},
            content=content,
        )
