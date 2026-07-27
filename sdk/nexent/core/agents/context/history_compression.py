"""Incremental semantic compression of completed historical conversation turns."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

from .llm_summary import LLMSummary
from .models import ContextItem, ContextItemInput, ContextItemType


@dataclass(frozen=True)
class HistorySummaryCandidate:
    summary: dict[str, Any]
    covered_through_message_id: int
    previous_summary_unit_id: int | None = None
    trigger: str = "soft_budget_exceeded"

    def as_item(self) -> ContextItem:
        return ContextItem.from_input(ContextItemInput(
            id=f"history_summary:candidate:{self.covered_through_message_id}",
            type=ContextItemType.HISTORY_SUMMARY,
            content={
                "summary": self.summary,
                "covered_through_message_id": self.covered_through_message_id,
                "previous_summary_unit_id": self.previous_summary_unit_id,
                "trigger": self.trigger,
            },
        ))


@dataclass(frozen=True)
class HistoryCompressionResult:
    candidate: HistorySummaryCandidate | None = None
    records: tuple[object, ...] = ()
    fallback_turns: tuple[ContextItem, ...] = ()


class HistoryCompressor:
    """The only LLM semantic compression boundary in the context runtime."""

    def __init__(self, llm: LLMSummary):
        self._llm = llm

    def compress(
        self,
        summary: ContextItem | None,
        turns: Sequence[ContextItem],
        model: Any,
    ) -> HistoryCompressionResult:
        if not turns:
            return HistoryCompressionResult()
        previous = summary.content if summary else None
        sections: list[str] = []
        if previous:
            sections.append("## Previous Summary\n" + json.dumps(
                previous.get("summary", {}), ensure_ascii=False, indent=2
            ))
        rendered_turns = [
            "## User\n{user}\n\n## Assistant final answer\n{assistant}".format(
                user=turn.content["user_message"],
                assistant=turn.content["assistant_final_answer"],
            )
            for turn in turns
        ]
        sections.append("## New Conversations\n" + "\n\n".join(rendered_turns))
        generated = self._llm.generate_summary(
            "\n\n".join(sections), model,
            call_type="history_incremental" if summary else "history_summary",
            prompt_type="incremental" if summary else "initial",
        )
        if not generated.summary_text:
            return HistoryCompressionResult(
                records=tuple(generated.records),
                fallback_turns=self._safe_fallback(turns),
            )
        try:
            payload = json.loads(generated.summary_text)
        except (TypeError, json.JSONDecodeError):
            # A checkpoint must be structured. Plain-text/fallback output remains transient.
            return HistoryCompressionResult(
                records=tuple(generated.records),
                fallback_turns=self._safe_fallback(turns),
            )
        if not isinstance(payload, dict):
            return HistoryCompressionResult(
                records=tuple(generated.records),
                fallback_turns=self._safe_fallback(turns),
            )
        last_message_id = int(turns[-1].content["assistant_message_id"])
        previous_id = summary.content.get("unit_id") if summary else None
        return HistoryCompressionResult(
            candidate=HistorySummaryCandidate(
                summary=payload,
                covered_through_message_id=last_message_id,
                previous_summary_unit_id=int(previous_id) if previous_id is not None else None,
            ),
            records=tuple(generated.records),
        )

    def _safe_fallback(self, turns: Sequence[ContextItem]) -> tuple[ContextItem, ...]:
        """Bound failed-summary input in memory without creating a checkpoint."""
        total_chars = max(
            256,
            int(self._llm.config.max_summary_reduce_tokens * self._llm.config.chars_per_token),
        )
        field_limit = max(64, total_chars // max(1, len(turns) * 2))
        result = []
        for turn in turns:
            content = dict(turn.content)
            for field in ("user_message", "assistant_final_answer"):
                text = str(content[field])
                if len(text) > field_limit:
                    half = max(0, (field_limit - 31) // 2)
                    content[field] = text[:half] + "\n...[history limited]...\n" + text[-half:]
            result.append(turn.model_copy(update={
                "content": content,
                "token_estimate": max(1, int(len(json.dumps(content, ensure_ascii=False)) / 1.5)),
                "metadata": {**turn.metadata, "history_fallback_limited": True},
            }))
        return tuple(result)
