"""Handler for knowledge base context items."""

import hashlib
from typing import Any, Dict, List

from ..context_item import ContextItem, ContextItemType, RepresentationTier
from ..item_handler import ContextItemHandler
from ..reducer_models import ReductionResult


_GENERATOR_SEMANTIC = "knowledge_base_handler"
_GENERATOR_DETERMINISTIC = "knowledge_base_handler_deterministic"
_VERSION = "1.0.0"


def _fingerprint(content: Any) -> str:
    return hashlib.sha256(str(content).encode()).hexdigest()[:16]


def _token_estimate(content: Any) -> int:
    return len(str(content)) // 4


def _extract_text(content: Any) -> str:
    """Extract text content from a KB item (dict or plain string)."""
    if isinstance(content, dict):
        return str(content.get("content", ""))
    return str(content)


class KnowledgeBaseHandler(ContextItemHandler):
    """Scores and reduces knowledge base retrieval results."""

    def supported_types(self) -> List[ContextItemType]:
        return [ContextItemType.KNOWLEDGE_BASE]

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        # TODO(W13): Implement scoring:
        #   score = relevance_score from KB retrieval
        #   Signals: item.metadata["relevance_score"]
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
                generator=_GENERATOR_SEMANTIC,
                generator_version=_VERSION,
                admissible=True,
                loss_metadata={},
                content=content,
            )

        if target == RepresentationTier.POINTER:
            # POINTER not supported for KB items (minimum_fidelity is COMPRESSED)
            return ReductionResult(
                representation=RepresentationTier.FULL,
                source_fingerprint=fp,
                token_count=_token_estimate(content),
                generator=_GENERATOR_DETERMINISTIC,
                generator_version=_VERSION,
                admissible=False,
                loss_metadata={"reason": "pointer_not_supported_for_knowledge_base"},
                content=content,
            )

        if target == RepresentationTier.COMPRESSED:
            # Use pre-computed LLM summary if available
            compressed_summary = item.metadata.get("compressed_summary")
            if compressed_summary:
                return ReductionResult(
                    representation=RepresentationTier.COMPRESSED,
                    source_fingerprint=fp,
                    token_count=_token_estimate(compressed_summary),
                    generator=_GENERATOR_SEMANTIC,
                    generator_version=_VERSION,
                    admissible=True,
                    loss_metadata={},
                    content=compressed_summary,
                )
            # Deterministic fallback: first 500 chars of content text
            text = _extract_text(content)
            truncated = text[:500]
            return ReductionResult(
                representation=RepresentationTier.COMPRESSED,
                source_fingerprint=fp,
                token_count=_token_estimate(truncated),
                generator=_GENERATOR_DETERMINISTIC,
                generator_version=_VERSION,
                admissible=True,
                loss_metadata={},
                content=truncated,
            )

        # STRUCTURED: keep kb_id + title + relevance_score (deterministic)
        if isinstance(content, dict):
            reduced = {
                "kb_id": str(content.get("kb_id", "")),
                "title": str(content.get("title", "")),
                "relevance_score": content.get("relevance_score", 0.0),
            }
        else:
            reduced = {
                "kb_id": "",
                "title": str(content),
                "relevance_score": 0.0,
            }
        return ReductionResult(
            representation=RepresentationTier.STRUCTURED,
            source_fingerprint=fp,
            token_count=_token_estimate(reduced),
            generator=_GENERATOR_DETERMINISTIC,
            generator_version=_VERSION,
            admissible=True,
            loss_metadata={},
            content=reduced,
        )
