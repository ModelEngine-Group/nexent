"""Build bounded, evidence-traceable Dreaming long-term memory versions."""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Callable, Iterable, List, Optional

from pydantic import BaseModel, Field

from .models import DreamingDecision


class DreamingMemoryUnit(BaseModel):
    """One semantic unit used to build a Dreaming version."""

    unit_id: str
    content: str
    evidence_ids: List[str] = Field(default_factory=list)
    strong_constraint: bool = False
    is_new: bool = False
    source_agent_id: Optional[str] = None
    source_conversation_id: Optional[str] = None
    source_created_at: Optional[datetime] = None
    source_updated_at: Optional[datetime] = None
    score: float = 0.0
    recall_count: int = 0
    query_diversity: int = 0


class DreamingSummarizationRequest(BaseModel):
    """Markdown input supplied to the Dreaming summarizer."""

    prior_markdown: str
    prior_source: str = "none"
    new_evidence_markdown: str
    units: List[DreamingMemoryUnit]
    max_chars: int
    attempt: int
    run_id: Optional[int] = None
    agent_id: Optional[str] = None
    validation_feedback: List[str] = Field(default_factory=list)


class DreamingSummarizationOutput(BaseModel):
    """Parsed Markdown returned from the summary envelope."""

    markdown: str
    metadata: dict = Field(default_factory=dict)


class DreamingVersionBuildResult(BaseModel):
    """Immutable content and evidence produced for one version."""

    raw_content: str
    published_content: str
    published_units: List[DreamingMemoryUnit]
    raw_char_count: int
    published_char_count: int
    summarization_status: str
    summarization_attempts: int = 0
    omitted_evidence_ids: List[str] = Field(default_factory=list)
    mechanical_truncation: bool = False
    summarization_audit: List[dict] = Field(default_factory=list)


DreamingSummarizer = Callable[[DreamingSummarizationRequest], DreamingSummarizationOutput]


def units_from_decisions(
    decisions: Iterable[DreamingDecision],
    *,
    source_limit: int,
    excluded_evidence_ids: Optional[set[str]] = None,
) -> List[DreamingMemoryUnit]:
    """Return eligible units after deterministic ranking and then apply Top-N."""
    if source_limit < 0:
        raise ValueError("source_limit must be non-negative")
    excluded = excluded_evidence_ids or set()
    selected = [
        decision for decision in decisions if decision.promote and str(decision.candidate.memory_id) not in excluded
    ]
    selected.sort(
        key=lambda item: (
            -item.score,
            -item.metrics.signal_count,
            item.candidate.memory_id,
        )
    )
    if source_limit == 0:
        return []
    return [
        DreamingMemoryUnit(
            unit_id=f"short-term:{decision.candidate.memory_id}",
            content=decision.candidate.content,
            evidence_ids=[str(decision.candidate.memory_id)],
            is_new=True,
            source_agent_id=decision.candidate.agent_id,
            source_conversation_id=decision.candidate.conversation_id,
            source_created_at=decision.candidate.source_created_at,
            source_updated_at=decision.candidate.source_updated_at,
            score=decision.score,
            recall_count=decision.metrics.signal_count,
            query_diversity=decision.metrics.context_diversity,
        )
        for decision in selected[:source_limit]
    ]


def build_dreaming_version(
    *,
    parent_units: Iterable[DreamingMemoryUnit],
    new_units: Iterable[DreamingMemoryUnit],
    max_chars: int = 10_000,
    summarizer: Optional[DreamingSummarizer] = None,
    prior_source: str = "none",
    max_attempts: int = 2,
    run_id: Optional[int] = None,
    agent_id: Optional[str] = None,
    backoff_base_seconds: float = 1.0,
) -> DreamingVersionBuildResult:
    """Build RAW and bounded published content without mutating parent data."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if max_attempts < 0:
        raise ValueError("max_attempts must be non-negative")

    parent_units = list(parent_units)
    new_units = list(new_units)
    units = _deduplicate_units([*parent_units, *new_units])
    raw_content = _render_units(units)
    if not new_units:
        return DreamingVersionBuildResult(
            raw_content=raw_content,
            published_content=raw_content,
            published_units=units,
            raw_char_count=len(raw_content),
            published_char_count=len(raw_content),
            summarization_status="no_new_evidence",
        )

    feedback: List[str] = []
    summarization_audit: List[dict] = []
    if summarizer is not None:
        required_evidence = {evidence_id for unit in units for evidence_id in unit.evidence_ids}
        required_literals = _critical_literals(raw_content)
        for unit in units:
            if unit.strong_constraint:
                required_literals.update(_constraint_literals(unit.content))
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                time.sleep(backoff_base_seconds * (attempt - 1))
            try:
                output = summarizer(
                    DreamingSummarizationRequest(
                        prior_markdown="\n\n".join(unit.content.strip() for unit in parent_units if unit.content.strip()),
                        prior_source=prior_source,
                        new_evidence_markdown=_render_evidence(new_units),
                        units=units,
                        max_chars=max_chars,
                        attempt=attempt,
                        run_id=run_id,
                        agent_id=agent_id,
                        validation_feedback=feedback,
                    )
                )
                if not isinstance(output, DreamingSummarizationOutput):
                    raise TypeError("summarizer must return DreamingSummarizationOutput")
            except Exception as exc:
                feedback = [f"summarizer_error:{type(exc).__name__}:{str(exc)[:100]}"]
                summarization_audit.append(
                    {
                        "attempt": attempt,
                        "outcome": "model_error",
                        "validation": feedback,
                    }
                )
                continue
            feedback = _validate_summary(
                output,
                required_literals=required_literals,
                max_chars=max_chars,
            )
            if not feedback:
                summarization_audit.append(
                    {
                        "attempt": attempt,
                        "outcome": "accepted",
                        "validation": [],
                    }
                )
                compact_unit = DreamingMemoryUnit(
                    unit_id="summarization",
                    content=output.markdown,
                    evidence_ids=sorted(required_evidence),
                )
                return DreamingVersionBuildResult(
                    raw_content=raw_content,
                    published_content=output.markdown,
                    published_units=[compact_unit],
                    raw_char_count=len(raw_content),
                    published_char_count=len(output.markdown),
                    summarization_status="summarized",
                    summarization_attempts=attempt,
                    summarization_audit=summarization_audit,
                )
            summarization_audit.append(
                {
                    "attempt": attempt,
                    "outcome": "rejected",
                    "validation": list(feedback),
                }
            )
    else:
        summarization_audit.append(
            {
                "attempt": 0,
                "outcome": "model_unavailable",
                "validation": ["summarizer_not_configured"],
            }
        )

    fallback_content, fallback_units, omitted, truncated = _mechanical_fallback(
        units,
        max_chars=max_chars,
    )
    return DreamingVersionBuildResult(
        raw_content=raw_content,
        published_content=fallback_content,
        published_units=fallback_units,
        raw_char_count=len(raw_content),
        published_char_count=len(fallback_content),
        summarization_status="mechanical_fallback",
        summarization_attempts=max_attempts if summarizer is not None else 0,
        omitted_evidence_ids=omitted,
        mechanical_truncation=truncated,
        summarization_audit=summarization_audit,
    )


def _deduplicate_units(units: List[DreamingMemoryUnit]) -> List[DreamingMemoryUnit]:
    by_id: dict[str, DreamingMemoryUnit] = {}
    order: List[str] = []
    for unit in units:
        if unit.unit_id not in by_id:
            order.append(unit.unit_id)
        by_id[unit.unit_id] = unit.model_copy(deep=True)
    return [by_id[unit_id] for unit_id in order]


def _render_unit(unit: DreamingMemoryUnit) -> str:
    return f"- {unit.content.strip()}"


def _render_units(units: Iterable[DreamingMemoryUnit]) -> str:
    body = "\n".join(_render_unit(unit) for unit in units if unit.content.strip())
    return body


def _render_evidence(units: Iterable[DreamingMemoryUnit]) -> str:
    """Render stable code-owned evidence labels for model input only."""
    blocks = []
    for index, unit in enumerate(units, start=1):
        evidence_id = f"E{index:04d}"
        blocks.append(f"### {evidence_id}\n\n{unit.content.strip()}")
    return "\n\n".join(blocks)


def _validate_summary(
    output: DreamingSummarizationOutput,
    *,
    required_literals: set[str],
    max_chars: int,
) -> List[str]:
    feedback: List[str] = []
    if not output.markdown.strip():
        feedback.append("content_empty")
    stripped = output.markdown.lstrip()
    if not re.match(r"^##\s+\S", stripped):
        feedback.append("first_line_must_be_section_heading")
    if re.search(r"(?m)^#\s+\S", output.markdown):
        feedback.append("level_one_heading_forbidden")
    headings = re.findall(r"(?m)^##\s+(.+?)\s*$", output.markdown)
    normalized_headings = [re.sub(r"[^\w\u4e00-\u9fff]+", " ", value.casefold()).strip() for value in headings]
    if len(normalized_headings) != len(set(normalized_headings)):
        feedback.append("duplicate_section_heading")
    generic_headings = {
        "user memory", "facts", "information", "summary", "miscellaneous",
        "remembered information", "memory", "用户记忆", "事实", "信息", "总结",
        "摘要", "杂项", "记忆", "已记住的信息", "未分类信息",
    }
    if any(heading in generic_headings for heading in normalized_headings):
        feedback.append("generic_section_heading")
    if re.search(r"(?mi)^#{2,3}\s+(?:map summary\s*\d*|e\d{4})\s*$", output.markdown):
        feedback.append("internal_label_heading")
    if re.search(r"\bE\d{4}\b", output.markdown):
        feedback.append("evidence_id_in_content")
    if headings:
        sections = re.split(r"(?m)^##\s+.+?\s*$", output.markdown)[1:]
        if any(not re.search(r"(?m)^\s*[-*+]\s+\S", section) for section in sections):
            feedback.append("section_without_bullets")
    if re.search(r"```|<\/?[A-Za-z][^>]*>", output.markdown):
        feedback.append("prohibited_markup")
    if len(output.markdown) > max_chars:
        feedback.append(f"content_over_limit:{len(output.markdown) - max_chars}")
    missing_literals = sorted(literal for literal in required_literals if literal not in output.markdown)
    if missing_literals:
        feedback.append(f"missing_critical_literals:{','.join(missing_literals)}")

    return feedback


def _critical_literals(content: str) -> set[str]:
    """Return globally high-value identifiers that summarization must preserve."""
    patterns = (
        r"https?://[^\s)\]}>,]+",
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
    )
    literals = {match.group(0) for pattern in patterns for match in re.finditer(pattern, content)}
    for match in re.finditer(r"(?<![\w])([A-Za-z0-9][A-Za-z0-9._:/-]*)(?![\w])", content):
        token = match.group(1)
        has_alpha = any(character.isalpha() for character in token)
        has_digit = any(character.isdigit() for character in token)
        has_identifier_shape = bool(re.search(r"[._:/-]", token)) or any(character.isupper() for character in token)
        if has_alpha and has_digit and has_identifier_shape:
            literals.add(token)
    return literals


def _constraint_literals(content: str) -> set[str]:
    """Preserve numeric values appearing in authoritative manual constraints."""
    return {
        match.group(0)
        for match in re.finditer(
            r"(?<![\w])[-+]?\d+(?:[.,]\d+)*(?:%|ms|s|MB|GB|TB|元|天|小时)?(?![\w])",
            content,
        )
    }


def _fallback_sort_key(unit: DreamingMemoryUnit) -> tuple:
    timestamp = unit.source_updated_at.timestamp() if unit.source_updated_at else 0.0
    return (
        not unit.strong_constraint,
        not unit.is_new,
        -timestamp,
        -unit.score,
        -unit.recall_count,
        -unit.query_diversity,
        unit.unit_id,
    )


def _mechanical_fallback(
    units: List[DreamingMemoryUnit],
    *,
    max_chars: int,
) -> tuple[str, List[DreamingMemoryUnit], List[str], bool]:
    selected: List[DreamingMemoryUnit] = []
    omitted: List[str] = []
    source_text = "\n".join(unit.content for unit in units)
    section_title = "未分类记忆" if re.search(r"[\u4e00-\u9fff]", source_text) else "Unclassified Memory"
    heading = f"## {section_title}\n\n"
    used = len(heading)
    truncated = False

    for unit in sorted(units, key=_fallback_sort_key):
        rendered = _render_unit(unit)
        separator = 1 if selected else 0
        if used + separator + len(rendered) <= max_chars:
            selected.append(unit.model_copy(deep=True))
            used += separator + len(rendered)
            continue
        if not selected:
            marker = " [mechanically truncated]"
            prefix = "- "
            available = max(0, max_chars - len(heading) - len(prefix) - len(marker))
            compacted = _truncate_at_sentence(unit.content.strip(), available)
            truncated_unit = unit.model_copy(
                update={"content": f"{compacted}{marker}" if compacted else marker.strip()},
                deep=True,
            )
            selected.append(truncated_unit)
            truncated = True
            used = len(heading) + len(_render_unit(truncated_unit))
            continue
        omitted.extend(unit.evidence_ids or [unit.unit_id])

    content = heading + "\n".join(_render_unit(unit) for unit in selected)
    return content[:max_chars], selected, sorted(set(omitted)), truncated


def _truncate_at_sentence(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 0:
        return ""
    prefix = text[:limit]
    boundaries = [match.end() for match in re.finditer(r"[。！？.!?](?:\s|$)", prefix)]
    if boundaries and boundaries[-1] >= max(1, int(limit * 0.5)):
        return prefix[: boundaries[-1]].rstrip()
    word_boundary = prefix.rfind(" ")
    if word_boundary >= max(1, int(limit * 0.6)):
        return prefix[:word_boundary].rstrip()
    return prefix.rstrip()
