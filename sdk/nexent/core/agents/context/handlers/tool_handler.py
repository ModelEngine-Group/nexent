"""Handler for tool context items."""

import hashlib
import re
from typing import Any, Dict, List

from ..context_item import ContextItem, ContextItemType, RepresentationTier
from ..item_handler import ContextItemHandler
from ..reducer_models import ReductionResult


_GENERATOR = "tool_handler_deterministic"
_VERSION = "1.0.0"


def _first_sentence(text: str) -> str:
    """Extract the first sentence from text, splitting on '.' or newline."""
    match = re.split(r"[.\n]", text, maxsplit=1)
    return match[0].strip() if match else text.strip()


def _fingerprint(content: Any) -> str:
    return hashlib.sha256(str(content).encode()).hexdigest()[:16]


def _token_estimate(content: Any) -> int:
    return len(str(content)) // 4


class ToolHandler(ContextItemHandler):
    """Scores and reduces tool definitions based on query relevance and usage."""

    def supported_types(self) -> List[ContextItemType]:
        return [ContextItemType.TOOL]

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        return 1.0

    def reduce(
        self, item: ContextItem, target: RepresentationTier, budget: int
    ) -> ReductionResult:
        content = item.content
        fp = _fingerprint(content)

        if target == RepresentationTier.FULL:
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

        if target == RepresentationTier.COMPRESSED:
            return ReductionResult(
                representation=RepresentationTier.COMPRESSED,
                source_fingerprint=fp,
                token_count=_token_estimate(content),
                generator=_GENERATOR,
                generator_version=_VERSION,
                admissible=True,
                loss_metadata={},
                content=content,
            )

        name = ""
        description = ""
        parameters: List[str] = []

        if isinstance(content, dict):
            name = str(content.get("name", ""))
            description = str(content.get("description", ""))
            raw_params = content.get("parameters", [])
            parameters = [str(p) for p in raw_params]
        else:
            name = str(content)

        if target == RepresentationTier.STRUCTURED:
            reduced = {
                "name": name,
                "description": _first_sentence(description),
                "parameters": parameters,
            }
            return ReductionResult(
                representation=RepresentationTier.STRUCTURED,
                source_fingerprint=fp,
                token_count=_token_estimate(reduced),
                generator=_GENERATOR,
                generator_version=_VERSION,
                admissible=True,
                loss_metadata={},
                content=reduced,
            )

        reduced = {"name": name, "param_count": len(parameters)}
        return ReductionResult(
            representation=RepresentationTier.POINTER,
            source_fingerprint=fp,
            token_count=_token_estimate(reduced),
            generator=_GENERATOR,
            generator_version=_VERSION,
            admissible=True,
            loss_metadata={},
            content=reduced,
        )
