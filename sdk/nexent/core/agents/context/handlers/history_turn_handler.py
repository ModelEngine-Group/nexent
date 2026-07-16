"""Handler for history turn context items."""

import re
from typing import Any, Dict, List

from ..context_item import ContextItem, ContextItemType, RepresentationTier
from ..item_handler import ContextItemHandler
from ..reducer_models import ReductionResult
from ._utils import fingerprint, token_estimate


_GENERATOR_SEMANTIC = "history_turn_handler"
_GENERATOR_DETERMINISTIC = "history_turn_handler_deterministic"
_VERSION = "1.0.0"


def _first_sentence(text: str) -> str:
    """Extract the first sentence from text, splitting on '.' or newline."""
    match = re.split(r"[.\n]", text, maxsplit=1)
    return match[0].strip() if match else text.strip()


class HistoryTurnHandler(ContextItemHandler):
    """Scores and reduces conversation history turns."""

    def supported_types(self) -> List[ContextItemType]:
        return [ContextItemType.HISTORY_TURN]

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        # TODO(W13): Implement weighted scoring:
        #   score = recency * 0.5
        #         + has_pending_action * 0.3
        #         + keyword_overlap * 0.2
        #   Signals: item.metadata["message_id"], item.metadata["step_index"],
        #            item.metadata["has_pending_action"]
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
                generator=_GENERATOR_SEMANTIC,
                generator_version=_VERSION,
                admissible=True,
                loss_metadata={},
                content=content,
            )

        if target == RepresentationTier.POINTER:
            # POINTER not supported for history turns (minimum_fidelity is STRUCTURED)
            return ReductionResult(
                representation=RepresentationTier.FULL,
                source_fingerprint=fp,
                token_count=token_estimate(content),
                generator=_GENERATOR_DETERMINISTIC,
                generator_version=_VERSION,
                admissible=False,
                loss_metadata={"reason": "pointer_not_supported_for_history_turn"},
                content=content,
            )

        if target == RepresentationTier.COMPRESSED:
            compressed_summary = item.metadata.get("compressed_summary")
            if compressed_summary:
                return ReductionResult(
                    representation=RepresentationTier.COMPRESSED,
                    source_fingerprint=fp,
                    token_count=token_estimate(compressed_summary),
                    generator=_GENERATOR_SEMANTIC,
                    generator_version=_VERSION,
                    admissible=True,
                    loss_metadata={},
                    content=compressed_summary,
                )
            # Deterministic fallback: truncated query + response
            user_query = ""
            assistant_response = ""
            if isinstance(content, dict):
                user_query = str(content.get("user_query", ""))
                assistant_response = str(content.get("assistant_response", ""))
            fallback = {
                "user_query": user_query[:200],
                "assistant_response": assistant_response[:200],
            }
            return ReductionResult(
                representation=RepresentationTier.COMPRESSED,
                source_fingerprint=fp,
                token_count=token_estimate(fallback),
                generator=_GENERATOR_DETERMINISTIC,
                generator_version=_VERSION,
                admissible=True,
                loss_metadata={},
                content=fallback,
            )

        # STRUCTURED: first sentence of each field, max 100 chars
        user_query = ""
        assistant_response = ""
        if isinstance(content, dict):
            user_query = str(content.get("user_query", ""))
            assistant_response = str(content.get("assistant_response", ""))
        reduced = {
            "user_query": _first_sentence(user_query)[:100],
            "assistant_response": _first_sentence(assistant_response)[:100],
        }
        return ReductionResult(
            representation=RepresentationTier.STRUCTURED,
            source_fingerprint=fp,
            token_count=token_estimate(reduced),
            generator=_GENERATOR_DETERMINISTIC,
            generator_version=_VERSION,
            admissible=True,
            loss_metadata={},
            content=reduced,
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
