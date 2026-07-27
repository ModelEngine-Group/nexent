from datetime import datetime

import pytest

from nexent.memory.dreaming import (
    DreamingCandidate,
    DreamingCompressionOutput,
    DreamingMemoryUnit,
    DreamingThresholds,
    build_dreaming_version,
    select_candidates,
    units_from_decisions,
)


def candidate(**overrides):
    values = {
        "memory_id": 1,
        "tenant_id": "tenant",
        "user_id": "user",
        "agent_id": "agent",
        "content": "durable fact",
        "recall_count": 3,
        "daily_count": 2,
        "grounded_count": 1,
        "total_retrieval_score": 4.2,
        "query_hashes": ["q1", "q2"],
        "recall_days": ["2026-07-20", "2026-07-22"],
        "last_recalled_at": datetime(2026, 7, 22),
    }
    values.update(overrides)
    return DreamingCandidate(**values)


def test_ac027_limit_is_applied_after_deterministic_ranking():
    decisions = select_candidates(
        [
            candidate(memory_id=1, total_retrieval_score=1),
            candidate(memory_id=2, total_retrieval_score=9),
            candidate(memory_id=3, total_retrieval_score=5),
        ],
        thresholds=DreamingThresholds(
            min_score=0,
            min_recall_count=0,
            min_unique_queries=0,
        ),
        now=datetime(2026, 7, 23),
    )

    units = units_from_decisions(decisions, source_limit=2)

    assert [unit.unit_id for unit in units] == ["short-term:2", "short-term:3"]


def test_ac023_boundary_and_parent_are_preserved_without_model_call():
    calls = []
    parent = DreamingMemoryUnit(
        unit_id="parent:1",
        content="old fact",
        evidence_ids=["old"],
    )
    new = DreamingMemoryUnit(
        unit_id="short-term:2",
        content="new fact",
        evidence_ids=["2"],
        is_new=True,
    )

    result = build_dreaming_version(
        parent_units=[parent],
        new_units=[new],
        max_chars=len("- old fact\n- new fact"),
        compressor=lambda request: calls.append(request),
    )

    assert result.compression_status == "not_needed"
    assert result.published_content == "- old fact\n- new fact"
    assert calls == []


def test_ac024_semantic_compression_retries_with_validation_feedback():
    requests = []

    def compressor(request):
        requests.append(request)
        if request.attempt == 1:
            return DreamingCompressionOutput(
                content="x" * 30,
                evidence_ids=["new"],
                metadata={
                    "all_fact_ids": ["f001"],
                    "covered_fact_ids": ["f001"],
                    "fact_to_units_map": {"f001": ["new"]},
                },
            )
        return DreamingCompressionOutput(
            content="old and new",
            evidence_ids=["old", "new"],
            metadata={
                "all_fact_ids": ["f001", "f002"],
                "covered_fact_ids": ["f001", "f002"],
                "fact_to_units_map": {"f001": ["parent"], "f002": ["new"]},
            },
        )

    result = build_dreaming_version(
        parent_units=[
            DreamingMemoryUnit(
                unit_id="parent",
                content="old " * 20,
                evidence_ids=["old"],
            )
        ],
        new_units=[
            DreamingMemoryUnit(
                unit_id="new",
                content="new " * 20,
                evidence_ids=["new"],
                is_new=True,
            )
        ],
        max_chars=20,
        compressor=compressor,
    )

    assert result.compression_status == "semantic"
    assert result.published_content == "old and new"
    assert result.compression_attempts == 2
    assert "missing_evidence:old" in requests[1].validation_feedback
    assert result.compression_audit == [
        {
            "attempt": 1,
            "outcome": "rejected",
            "validation": [
                "content_over_limit:10",
                "missing_evidence:old",
                "fact_coverage_too_low:1/2=0.50",
            ],
        },
        {"attempt": 2, "outcome": "accepted", "validation": []},
    ]


def test_ac025_mechanical_fallback_prioritizes_new_content_and_records_omissions():
    result = build_dreaming_version(
        parent_units=[
            DreamingMemoryUnit(
                unit_id="parent",
                content="old information",
                evidence_ids=["old"],
            )
        ],
        new_units=[
            DreamingMemoryUnit(
                unit_id="new",
                content="new information",
                evidence_ids=["new"],
                is_new=True,
            )
        ],
        max_chars=len("- new information"),
        compressor=lambda _request: DreamingCompressionOutput(
            content="still too long" * 10,
            evidence_ids=[],
        ),
        max_attempts=2,
    )

    assert result.compression_status == "mechanical_fallback"
    assert result.published_content == "- new information"
    assert result.omitted_evidence_ids == ["old"]
    assert result.published_char_count <= len("- new information")
    assert [row["outcome"] for row in result.compression_audit] == [
        "rejected",
        "rejected",
    ]


def test_ac025_single_oversized_unit_uses_marked_sentence_boundary_fallback():
    result = build_dreaming_version(
        parent_units=[],
        new_units=[
            DreamingMemoryUnit(
                unit_id="new",
                content="First durable fact. Second durable fact is much longer.",
                evidence_ids=["new"],
                is_new=True,
            )
        ],
        max_chars=48,
    )

    assert result.mechanical_truncation is True
    assert "[mechanically truncated]" in result.published_content
    assert result.published_char_count <= 48


def test_ac017_semantic_compression_rejects_missing_fact_literals():
    requests = []

    def compressor(request):
        requests.append(request)
        return DreamingCompressionOutput(
            content="Keep the API latency below the agreed threshold.",
            evidence_ids=["new"],
        )

    result = build_dreaming_version(
        parent_units=[],
        new_units=[
            DreamingMemoryUnit(
                unit_id="new",
                content=(
                    "Keep API latency below 250ms and notify ops@example.com. " * 3
                ),
                evidence_ids=["new"],
                is_new=True,
            )
        ],
        max_chars=80,
        compressor=compressor,
    )

    assert len(requests) == 2
    assert result.compression_status == "mechanical_fallback"
    assert "missing_critical_literals:250ms,ops@example.com" in (
        requests[1].validation_feedback
    )


def test_ac035_named_pattern_literal_extraction():
    from nexent.memory.dreaming.version_builder import _critical_literals
    literals = _critical_literals("Follow pattern 10 and rule 3 for step 7")
    assert "pattern 10" in literals
    assert "rule 3" in literals
    assert "step 7" in literals


def test_ac043_coverage_validation_rejection():
    from nexent.memory.dreaming.version_builder import _validate_compression
    output = DreamingCompressionOutput(
        content="some content",
        evidence_ids=["1", "2", "3"],
    )
    source_unit_ids = {"u1", "u2", "u3", "u4", "u5", "u6", "u7", "u8", "u9", "u10"}
    fact_to_units_map = {
        "f001": ["u1"], "f002": ["u2"], "f003": ["u3"],
        "f004": ["u4"], "f005": ["u5"], "f006": ["u6"],
        "f007": ["u7"], "f008": ["u8"],
    }
    compressed_fact_ids = ["f001", "f002", "f003", "f004", "f005", "f006", "f007", "f008"]

    feedback = _validate_compression(
        output,
        required_evidence={"1", "2", "3"},
        required_literals=set(),
        max_chars=10_000,
        source_unit_ids=source_unit_ids,
        fact_to_units_map=fact_to_units_map,
        compressed_fact_ids=compressed_fact_ids,
    )
    assert any("fact_coverage_too_low" in f for f in feedback)


def test_ac044_coverage_validation_acceptance():
    from nexent.memory.dreaming.version_builder import _validate_compression
    output = DreamingCompressionOutput(
        content="some content",
        evidence_ids=["1", "2", "3"],
    )
    source_unit_ids = {"u1", "u2", "u3", "u4", "u5", "u6", "u7", "u8", "u9", "u10"}
    fact_to_units_map = {f"f{i:03d}": [f"u{i}"] for i in range(1, 11)}
    compressed_fact_ids = [f"f{i:03d}" for i in range(1, 11)]

    feedback = _validate_compression(
        output,
        required_evidence={"1", "2", "3"},
        required_literals=set(),
        max_chars=10_000,
        source_unit_ids=source_unit_ids,
        fact_to_units_map=fact_to_units_map,
        compressed_fact_ids=compressed_fact_ids,
    )
    assert not any("fact_coverage" in f for f in feedback)


def test_units_from_decisions_negative_source_limit():
    with pytest.raises(ValueError, match="non-negative"):
        units_from_decisions([], source_limit=-1)


def test_units_from_decisions_zero_source_limit():
    decisions = select_candidates(
        [candidate(memory_id=1)],
        thresholds=DreamingThresholds(
            min_score=0, min_recall_count=0, min_unique_queries=0
        ),
        now=datetime(2026, 7, 23),
    )
    result = units_from_decisions(decisions, source_limit=0)
    assert result == []


def test_build_dreaming_version_invalid_max_chars():
    with pytest.raises(ValueError, match="positive"):
        build_dreaming_version(parent_units=[], new_units=[], max_chars=0)


def test_build_dreaming_version_negative_max_attempts():
    with pytest.raises(ValueError, match="non-negative"):
        build_dreaming_version(parent_units=[], new_units=[], max_chars=100, max_attempts=-1)


def test_build_dreaming_version_compressor_exception():
    def failing_compressor(request):
        raise RuntimeError("model unavailable")

    result = build_dreaming_version(
        parent_units=[],
        new_units=[
            DreamingMemoryUnit(
                unit_id="new",
                content="important fact " * 20,
                evidence_ids=["1"],
                is_new=True,
            )
        ],
        max_chars=20,
        compressor=failing_compressor,
        max_attempts=2,
    )

    assert result.compression_status == "mechanical_fallback"
    assert result.compression_audit[0]["outcome"] == "model_error"
    assert "compressor_error" in result.compression_audit[0]["validation"][0]


def test_validate_compression_empty_content():
    from nexent.memory.dreaming.version_builder import _validate_compression

    output = DreamingCompressionOutput(
        content="   ",
        evidence_ids=["1"],
    )
    feedback = _validate_compression(
        output,
        required_evidence={"1"},
        required_literals=set(),
        max_chars=10_000,
    )
    assert "content_empty" in feedback


def test_truncate_at_sentence_short_text():
    from nexent.memory.dreaming.version_builder import _truncate_at_sentence

    assert _truncate_at_sentence("short", 100) == "short"


def test_truncate_at_sentence_zero_limit():
    from nexent.memory.dreaming.version_builder import _truncate_at_sentence

    assert _truncate_at_sentence("some text", 0) == ""


def test_truncate_at_sentence_word_boundary():
    from nexent.memory.dreaming.version_builder import _truncate_at_sentence

    text = "This is a long sentence without period marks"
    result = _truncate_at_sentence(text, 30)
    assert len(result) <= 30
    assert result == "This is a long sentence"
