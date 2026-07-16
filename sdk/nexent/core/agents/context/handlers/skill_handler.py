"""Handler for skill context items."""

import re
from typing import Any, Dict, List

from ..context_item import ContextItem, ContextItemType, RepresentationTier
from ..item_handler import ContextItemHandler
from ..reducer_models import ReductionResult
from ._utils import fingerprint, token_estimate


_GENERATOR = "skill_handler_deterministic"
_VERSION = "1.0.0"


def _first_sentence(text: str) -> str:
    match = re.split(r"[.\n]", text, maxsplit=1)
    return match[0].strip() if match else text.strip()


class SkillHandler(ContextItemHandler):
    """Scores and reduces skill summaries based on query relevance."""

    def supported_types(self) -> List[ContextItemType]:
        return [ContextItemType.SKILL]

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        return 1.0

    def reduce(
        self, item: ContextItem, target: RepresentationTier, budget: int
    ) -> ReductionResult:
        content = item.content
        fp = fingerprint(content)

        if target == RepresentationTier.FULL:
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

        if target == RepresentationTier.COMPRESSED:
            return ReductionResult(
                representation=RepresentationTier.COMPRESSED,
                source_fingerprint=fp,
                token_count=token_estimate(content),
                generator=_GENERATOR,
                generator_version=_VERSION,
                admissible=True,
                loss_metadata={},
                content=content,
            )

        name = ""
        description = ""

        if isinstance(content, dict):
            name = str(content.get("name", ""))
            description = str(content.get("description", ""))
        else:
            name = str(content)

        if target == RepresentationTier.STRUCTURED:
            first_sent = _first_sentence(description)
            reduced = {"name": name, "description": first_sent[:100]}
            return ReductionResult(
                representation=RepresentationTier.STRUCTURED,
                source_fingerprint=fp,
                token_count=token_estimate(reduced),
                generator=_GENERATOR,
                generator_version=_VERSION,
                admissible=True,
                loss_metadata={},
                content=reduced,
            )

        reduced = {"name": name}
        return ReductionResult(
            representation=RepresentationTier.POINTER,
            source_fingerprint=fp,
            token_count=token_estimate(reduced),
            generator=_GENERATOR,
            generator_version=_VERSION,
            admissible=True,
            loss_metadata={},
            content=reduced,
        )
