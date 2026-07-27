"""Build bounded, evidence-traceable Dreaming long-term memory versions."""

from __future__ import annotations

import re
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
    source_updated_at: Optional[datetime] = None
    score: float = 0.0
    recall_count: int = 0
    query_diversity: int = 0


class DreamingCompressionRequest(BaseModel):
    """Grounded input supplied to a semantic compressor."""

    raw_content: str
    units: List[DreamingMemoryUnit]
    max_chars: int
    attempt: int
    run_id: Optional[int] = None
    agent_id: Optional[str] = None
    validation_feedback: List[str] = Field(default_factory=list)


class DreamingCompressionOutput(BaseModel):
    """Structured semantic-compression output."""

    content: str
    evidence_ids: List[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class DreamingVersionBuildResult(BaseModel):
    """Immutable content and evidence produced for one version."""

    raw_content: str
    published_content: str
    published_units: List[DreamingMemoryUnit]
    raw_char_count: int
    published_char_count: int
    compression_status: str
    compression_attempts: int = 0
    omitted_evidence_ids: List[str] = Field(default_factory=list)
    mechanical_truncation: bool = False
    compression_audit: List[dict] = Field(default_factory=list)


DreamingCompressor = Callable[[DreamingCompressionRequest], DreamingCompressionOutput]


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
    compressor: Optional[DreamingCompressor] = None,
    max_attempts: int = 2,
    run_id: Optional[int] = None,
    agent_id: Optional[str] = None,
) -> DreamingVersionBuildResult:
    """Build RAW and bounded published content without mutating parent data."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if max_attempts < 0:
        raise ValueError("max_attempts must be non-negative")

    units = _deduplicate_units([*parent_units, *new_units])
    raw_content = _render_units(units)
    if len(raw_content) <= max_chars:
        return DreamingVersionBuildResult(
            raw_content=raw_content,
            published_content=raw_content,
            published_units=units,
            raw_char_count=len(raw_content),
            published_char_count=len(raw_content),
            compression_status="not_needed",
        )

    feedback: List[str] = []
    compression_audit: List[dict] = []
    if compressor is not None:
        required_evidence = {evidence_id for unit in units for evidence_id in unit.evidence_ids}
        required_literals = _critical_literals(raw_content)
        for attempt in range(1, max_attempts + 1):
            try:
                output = compressor(
                    DreamingCompressionRequest(
                        raw_content=raw_content,
                        units=units,
                        max_chars=max_chars,
                        attempt=attempt,
                        run_id=run_id,
                        agent_id=agent_id,
                        validation_feedback=feedback,
                    )
                )
            except Exception as exc:
                feedback = [f"compressor_error:{type(exc).__name__}:{str(exc)[:100]}"]
                compression_audit.append(
                    {
                        "attempt": attempt,
                        "outcome": "model_error",
                        "validation": feedback,
                    }
                )
                continue
            # Extract coverage data from compressor metadata
            meta = output.metadata or {}
            source_unit_ids = {unit.unit_id for unit in units}
            fact_to_units_map = meta.get("fact_to_units_map", {})
            compressed_fact_ids = meta.get("covered_fact_ids", [])

            feedback = _validate_compression(
                output,
                required_evidence=required_evidence,
                required_literals=required_literals,
                max_chars=max_chars,
                source_unit_ids=source_unit_ids,
                fact_to_units_map=fact_to_units_map,
                compressed_fact_ids=compressed_fact_ids,
            )
            if not feedback:
                compression_audit.append(
                    {
                        "attempt": attempt,
                        "outcome": "accepted",
                        "validation": [],
                    }
                )
                compact_unit = DreamingMemoryUnit(
                    unit_id="semantic-compression",
                    content=output.content,
                    evidence_ids=sorted(required_evidence),
                )
                return DreamingVersionBuildResult(
                    raw_content=raw_content,
                    published_content=output.content,
                    published_units=[compact_unit],
                    raw_char_count=len(raw_content),
                    published_char_count=len(output.content),
                    compression_status="semantic",
                    compression_attempts=attempt,
                    compression_audit=compression_audit,
                )
            compression_audit.append(
                {
                    "attempt": attempt,
                    "outcome": "rejected",
                    "validation": list(feedback),
                }
            )
    else:
        compression_audit.append(
            {
                "attempt": 0,
                "outcome": "model_unavailable",
                "validation": ["compressor_not_configured"],
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
        compression_status="mechanical_fallback",
        compression_attempts=max_attempts if compressor is not None else 0,
        omitted_evidence_ids=omitted,
        mechanical_truncation=truncated,
        compression_audit=compression_audit,
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
    return "\n".join(_render_unit(unit) for unit in units if unit.content.strip())


def _validate_compression(
    output: DreamingCompressionOutput,
    *,
    required_evidence: set[str],
    required_literals: set[str],
    max_chars: int,
    source_unit_ids: Optional[set[str]] = None,
    fact_to_units_map: Optional[dict[str, List[str]]] = None,
    compressed_fact_ids: Optional[List[str]] = None,
) -> List[str]:
    feedback: List[str] = []
    if not output.content.strip():
        feedback.append("content_empty")
    if len(output.content) > max_chars:
        feedback.append(f"content_over_limit:{len(output.content) - max_chars}")
    missing = sorted(required_evidence - set(output.evidence_ids))
    if missing:
        feedback.append(f"missing_evidence:{','.join(missing)}")
    missing_literals = sorted(literal for literal in required_literals if literal not in output.content)
    if missing_literals:
        feedback.append(f"missing_critical_literals:{','.join(missing_literals)}")

    # Coverage check: which source units are represented in output?
    if source_unit_ids is not None and compressed_fact_ids is not None and fact_to_units_map is not None:
        covered_units: set[str] = set()
        for fact_id in compressed_fact_ids:
            if fact_id in fact_to_units_map:
                covered_units.update(fact_to_units_map[fact_id])

        if len(source_unit_ids) > 0:
            coverage = len(covered_units) / len(source_unit_ids)
            if coverage < 0.95:
                feedback.append(
                    f"fact_coverage_too_low:{len(covered_units)}/{len(source_unit_ids)}={coverage:.2f}"
                )

    return feedback


def _critical_literals(content: str) -> set[str]:
    """Return fact-bearing literals that semantic compression must preserve."""
    patterns = (
        r"https?://[^\s)\]}>,]+",
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        r"(?<![\w])[-+]?\d+(?:[.,]\d+)*(?:%|ms|s|MB|GB|TB|元|天|小时)?(?![\w])",
        r"\b[A-Za-z]+\s+\d+\b",
    )
    return {match.group(0) for pattern in patterns for match in re.finditer(pattern, content)}


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
    used = 0
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
            available = max(0, max_chars - len(prefix) - len(marker))
            compacted = _truncate_at_sentence(unit.content.strip(), available)
            truncated_unit = unit.model_copy(
                update={"content": f"{compacted}{marker}" if compacted else marker.strip()},
                deep=True,
            )
            selected.append(truncated_unit)
            truncated = True
            used = len(_render_unit(truncated_unit))
            continue
        omitted.extend(unit.evidence_ids or [unit.unit_id])

    content = _render_units(selected)
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
