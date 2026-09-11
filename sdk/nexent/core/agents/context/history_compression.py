"""Incremental semantic compression of completed historical conversation turns."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Sequence

from .llm_summary import LLMSummary
from .models import ContextItem, ContextItemInput, ContextItemType


logger = logging.getLogger("agent_context.history_compression")


_FACT_MARKER_RE = re.compile(
    r"\b(?=[A-Za-z0-9-]*\d)[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){2,}\b"
)
_ASSOCIATED_LITERAL_RE = re.compile(
    r"(?<![\w-])[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff]*-\d+(?![\w-])"
)


@dataclass(frozen=True)
class HistorySummaryCandidate:
    summary: dict[str, Any]
    covered_through_message_id: int
    previous_summary_unit_id: int | None = None
    trigger: str = "compaction_trigger_threshold_exceeded"
    history_tokens_before: int = 0
    history_tokens_after: int = 0
    compaction_attempts: int = 0
    compaction_trigger_threshold_tokens: int = 0
    compaction_target_tokens: int = 0

    def as_item(self) -> ContextItem:
        return ContextItem.from_input(ContextItemInput(
            id=f"history_summary:candidate:{self.covered_through_message_id}",
            type=ContextItemType.HISTORY_SUMMARY,
            content={
                "summary": self.summary,
                "covered_through_message_id": self.covered_through_message_id,
                "previous_summary_unit_id": self.previous_summary_unit_id,
                "trigger": self.trigger,
                "history_tokens_before": self.history_tokens_before,
                "history_tokens_after": self.history_tokens_after,
                "compaction_attempts": self.compaction_attempts,
                "compaction_trigger_threshold_tokens": self.compaction_trigger_threshold_tokens,
                "compaction_target_tokens": self.compaction_target_tokens,
            },
        ))


@dataclass(frozen=True)
class HistorySummaryInput:
    """Canonical and deliberately narrow input to semantic history compression."""

    previous_summary_markdown: str | None
    new_turns: tuple[tuple[str, str], ...]
    covered_through_message_id: int
    previous_summary_unit_id: int | None = None

    @classmethod
    def from_items(
        cls, summary: ContextItem | None, turns: Sequence[ContextItem]
    ) -> "HistorySummaryInput":
        previous_markdown = None
        previous_unit_id = None
        covered_through = 0
        if summary:
            payload = summary.content
            prior = payload.get("summary", "")
            if isinstance(prior, dict):
                prior = prior.get("markdown", "")
            previous_markdown = str(prior).strip() or None
            previous_unit_id = payload.get("unit_id")
            if previous_unit_id is None:
                previous_unit_id = payload.get("previous_summary_unit_id")
            covered_through = int(payload["covered_through_message_id"])
        canonical_turns = tuple(
            (
                str(turn.content["user_message"]),
                str(turn.content["assistant_final_answer"]),
            )
            for turn in turns
        )
        if turns:
            covered_through = int(turns[-1].content["assistant_message_id"])
        return cls(
            previous_summary_markdown=previous_markdown,
            new_turns=canonical_turns,
            covered_through_message_id=covered_through,
            previous_summary_unit_id=(
                int(previous_unit_id) if previous_unit_id is not None else None
            ),
        )

    def render(self) -> str:
        sections: list[str] = []
        if self.previous_summary_markdown:
            sections.append("## Previous Summary\n" + self.previous_summary_markdown)
        if self.new_turns:
            rendered = [
                f"## User\n{user}\n\n## Assistant final answer\n{answer}"
                for user, answer in self.new_turns
            ]
            sections.append("## New Conversations\n" + "\n\n".join(rendered))
        return "\n\n".join(sections)


def _protected_fact_literals(source_text: str) -> dict[str, tuple[str, ...]]:
    """Collect explicit fact identifiers and code-like literals on the same line."""
    protected: dict[str, set[str]] = {}
    for line in source_text.splitlines():
        markers = _FACT_MARKER_RE.findall(line)
        if not markers:
            continue
        literals = {
            re.sub(r"^.*[为是：:]", "", literal)
            for literal in _ASSOCIATED_LITERAL_RE.findall(line)
        }
        for marker in markers:
            protected.setdefault(marker, set()).update(literals)
    return {
        marker: tuple(sorted(literals))
        for marker, literals in protected.items()
    }


def _validate_summary_contract(
    text: str,
    section_keys: Sequence[str],
    *,
    source_text: str = "",
) -> str | None:
    """Return canonical Markdown only for the exact seven-section contract."""
    cleaned = text.strip()
    top = "# Compact Result of History"
    if not cleaned.startswith(top):
        return None
    headings = re.findall(r"(?m)^(#{1,6})\s+(.+?)\s*$", cleaned)
    if not headings or headings[0] != ("#", "Compact Result of History"):
        return None
    expected = [key.replace("_", " ").title() for key in section_keys]
    section_headings = [title for level, title in headings[1:] if level == "##"]
    if section_headings != expected or len(headings) != len(expected) + 1:
        return None
    forbidden = re.compile(
        r"(?im)^\s*(?:word\s*count|character\s*count|token\s*count|"
        r"as\s+an?\s+(?:ai|model)|i\s+(?:reasoned|thought|was asked)|"
        r"meta(?:data| commentary)?)\s*[:：]"
    )
    if forbidden.search(cleaned):
        return None
    parts = re.split(r"(?m)^##\s+.+?\s*$", cleaned)[1:]
    if len(parts) != len(expected) or any(not part.strip() for part in parts):
        return None
    for marker, literals in _protected_fact_literals(source_text).items():
        if marker not in cleaned or any(literal not in cleaned for literal in literals):
            logger.warning(
                "Rejected history summary candidate: protected fact omitted marker=%s literals=%s",
                marker,
                literals,
            )
            return None
    return cleaned


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
        if not turns and summary is None:
            return HistoryCompressionResult()
        summary_input = HistorySummaryInput.from_items(summary, turns)
        input_tokens = sum(
            item.token_estimate for item in ([summary] if summary else [])
        ) + sum(item.token_estimate for item in turns)
        target_tokens = self._llm.config.compaction_target_tokens or input_tokens
        max_output_tokens = max(
            64,
            min(
                max(64, input_tokens - 1),
                max(64, target_tokens),
                self._llm.config.max_summary_reduce_tokens or max(64, input_tokens // 2),
            ),
        )
        generated = self._llm.generate_summary(
            summary_input.render(), model,
            call_type="history_incremental" if summary else "history_summary",
            prompt_type="incremental" if summary else "initial",
            max_output_tokens=max_output_tokens,
        )
        validated = (
            _validate_summary_contract(
                generated.summary_text,
                tuple(self._llm.config.summary_json_schema),
                source_text=summary_input.render(),
            )
            if generated.summary_text else None
        )
        if validated is None:
            logger.warning(
                "Rejected history summary candidate: headings=%s starts_with_contract=%s",
                re.findall(r"(?m)^#{1,6}\s+(.+?)\s*$", generated.summary_text or ""),
                (generated.summary_text or "").lstrip().startswith(
                    "# Compact Result of History"
                ),
            )
            return HistoryCompressionResult(
                records=tuple(generated.records),
                fallback_turns=self._safe_fallback(turns),
            )
        return HistoryCompressionResult(
            candidate=HistorySummaryCandidate(
                summary={"markdown": validated},
                covered_through_message_id=summary_input.covered_through_message_id,
                previous_summary_unit_id=summary_input.previous_summary_unit_id,
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
