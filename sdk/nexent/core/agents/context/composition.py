"""Content-free semantic composition estimates for final provider requests."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Iterable, Mapping, Optional

from ...utils.token_estimation import estimate_tokens_text
from .models import ContextItemType


CONTEXT_COMPOSITION_ESTIMATOR_VERSION = "context-composition-v2"
SEGMENT_NAMES = (
    "system_instructions",
    "user_history",
    "assistant_history",
    "current_request",
    "retrieved_context",
    "tool_definitions",
    "tool_calls_results",
    "attachments_media",
    "provider_overhead",
)


@dataclass(frozen=True)
class ContextComposition:
    source: str
    denominator_tokens: int
    estimator_version: str
    segments: dict[str, int]
    adjustment_ratio: float
    high_adjustment: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_context_segments(
    items: Iterable[Any],
    *,
    purpose_messages: Iterable[Any] = (),
    tools: Iterable[Any] = (),
) -> dict[str, int]:
    """Estimate semantic segments from ContextItem provenance before reconciliation."""
    result = {name: 0 for name in SEGMENT_NAMES}
    for item in items:
        item_type = getattr(item, "type", None)
        content = getattr(item, "content", {}) or {}
        estimate = max(0, int(getattr(item, "token_estimate", 0) or 0))
        if item_type in {
            ContextItemType.SYSTEM,
            ContextItemType.SKILL,
        }:
            result["system_instructions"] += estimate
        elif item_type in {
            ContextItemType.MEMORY,
            ContextItemType.KNOWLEDGE_BASE,
        }:
            result["retrieved_context"] += estimate
        elif item_type == ContextItemType.HISTORY_SUMMARY:
            result["assistant_history"] += estimate
        elif item_type == ContextItemType.CONVERSATION_TURN:
            result["user_history"] += _estimate_value(content.get("user_message"))
            result["assistant_history"] += _estimate_value(
                content.get("assistant_final_answer")
            )
        elif item_type == ContextItemType.CURRENT_TASK:
            result["current_request"] += estimate
        elif item_type in {
            ContextItemType.TOOL,
            ContextItemType.MANAGED_AGENT,
            ContextItemType.EXTERNAL_AGENT,
        }:
            result["tool_definitions"] += estimate
        elif item_type in {
            ContextItemType.CURRENT_PLANNING,
            ContextItemType.CURRENT_ACTION,
        }:
            result["tool_calls_results"] += estimate
        else:
            result["provider_overhead"] += estimate

    for message in purpose_messages:
        role = _message_role(message)
        estimate = _estimate_value(_message_content(message))
        if role in {"system", "developer"}:
            result["system_instructions"] += estimate
        elif role == "user":
            result["current_request"] += estimate
        else:
            result["tool_calls_results"] += estimate

    tool_list = list(tools)
    if tool_list:
        result["tool_definitions"] += _estimate_value(tool_list)
    return result


def reconcile_context_composition(
    estimated_segments: Mapping[str, Any],
    provider_input_tokens: Optional[int],
) -> ContextComposition:
    """Reconcile non-negative semantic estimates to an exact input denominator."""
    segments = {
        name: max(0, int(estimated_segments.get(name, 0) or 0))
        for name in SEGMENT_NAMES
    }
    segments["provider_overhead"] = 0
    estimated_sum = sum(segments.values())

    if provider_input_tokens is None:
        denominator = estimated_sum
        return ContextComposition(
            source="estimated",
            denominator_tokens=denominator,
            estimator_version=CONTEXT_COMPOSITION_ESTIMATOR_VERSION,
            segments=segments,
            adjustment_ratio=0.0,
            high_adjustment=False,
        )

    denominator = max(0, int(provider_input_tokens))
    if estimated_sum <= denominator:
        adjustment = denominator - estimated_sum
        segments["provider_overhead"] = adjustment
    elif estimated_sum:
        scale = denominator / estimated_sum
        for name in SEGMENT_NAMES:
            if name != "provider_overhead":
                segments[name] = int(segments[name] * scale)
        segments["provider_overhead"] = denominator - sum(segments.values())
        adjustment = estimated_sum - denominator
    else:
        segments["provider_overhead"] = denominator
        adjustment = denominator

    ratio = round(adjustment / denominator, 4) if denominator else (1.0 if adjustment else 0.0)
    return ContextComposition(
        source="estimated",
        denominator_tokens=denominator,
        estimator_version=CONTEXT_COMPOSITION_ESTIMATOR_VERSION,
        segments=segments,
        adjustment_ratio=ratio,
        high_adjustment=ratio > 0.1,
    )


def _estimate_value(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    return max(0, estimate_tokens_text(text))


def _message_role(message: Any) -> str:
    value = message.get("role") if isinstance(message, Mapping) else getattr(message, "role", "")
    return str(getattr(value, "value", value) or "").lower()


def _message_content(message: Any) -> Any:
    return message.get("content") if isinstance(message, Mapping) else getattr(message, "content", None)
