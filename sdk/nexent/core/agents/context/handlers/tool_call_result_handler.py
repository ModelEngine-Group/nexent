"""Handler for tool call result context items."""

import hashlib
from typing import Any, Dict, List

from ..context_item import ContextItem, ContextItemType, RepresentationTier
from ..item_handler import ContextItemHandler
from ..reducer_models import ReductionResult


_GENERATOR_DETERMINISTIC = "tool_call_result_handler_deterministic"
_VERSION = "1.0.0"


def _fingerprint(content: Any) -> str:
    return hashlib.sha256(str(content).encode()).hexdigest()[:16]


def _token_estimate(content: Any) -> int:
    return len(str(content)) // 4


class ToolCallResultHandler(ContextItemHandler):
    """Scores and reduces tool call results from the current conversation."""

    def supported_types(self) -> List[ContextItemType]:
        return [ContextItemType.TOOL_CALL_RESULT]

    def score(self, item: ContextItem, query: str, context: Dict[str, Any]) -> float:
        # TODO(W13): Implement weighted scoring:
        #   score = recency * 0.4
        #         + is_active_tool * 0.4
        #         + result_relevance * 0.2
        #   Signals: item.metadata["message_id"], item.metadata["tool_name"]
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
                generator=_GENERATOR_DETERMINISTIC,
                generator_version=_VERSION,
                admissible=True,
                loss_metadata={},
                content=content,
            )

        tool_name = ""
        execution_result = ""
        status = ""
        if isinstance(content, dict):
            tool_name = str(content.get("tool_name", ""))
            execution_result = str(content.get("execution_result", ""))
            status = str(content.get("status", ""))

        if target == RepresentationTier.COMPRESSED:
            # COMPRESSED falls through to STRUCTURED for tool call results
            reduced = {
                "tool_name": tool_name,
                "execution_result": execution_result[:200],
            }
            return ReductionResult(
                representation=RepresentationTier.COMPRESSED,
                source_fingerprint=fp,
                token_count=_token_estimate(reduced),
                generator=_GENERATOR_DETERMINISTIC,
                generator_version=_VERSION,
                admissible=True,
                loss_metadata={},
                content=reduced,
            )

        if target == RepresentationTier.STRUCTURED:
            reduced = {
                "tool_name": tool_name,
                "execution_result": execution_result[:200],
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

        # POINTER: tool_name + status only
        reduced = {
            "tool_name": tool_name,
            "status": status,
        }
        return ReductionResult(
            representation=RepresentationTier.POINTER,
            source_fingerprint=fp,
            token_count=_token_estimate(reduced),
            generator=_GENERATOR_DETERMINISTIC,
            generator_version=_VERSION,
            admissible=True,
            loss_metadata={},
            content=reduced,
        )

    def to_messages(self, item: ContextItem) -> List[Dict[str, Any]]:
        content = item.content or {}
        tool_call = content.get("tool_call", "")
        execution_result = content.get("execution_result", "")
        text = f"[Tool Call]\n{tool_call}\n\n[Execution Result]\n{execution_result}"
        return [{"role": "user", "content": [{"type": "text", "text": text}]}]
