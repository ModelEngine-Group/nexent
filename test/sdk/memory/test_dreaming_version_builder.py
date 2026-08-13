from datetime import datetime

from nexent.memory.dreaming import (
    DreamingMemoryUnit,
    DreamingSummarizationOutput,
    build_dreaming_version,
)


def _unit(unit_id, content, *, new=False, evidence=None, constraint=False):
    return DreamingMemoryUnit(unit_id=unit_id, content=content, evidence_ids=evidence or [unit_id],
                              is_new=new, strong_constraint=constraint, source_updated_at=datetime(2026, 8, 13))


def test_ac057_builder_calls_model_once_for_under_limit_and_inherits_evidence_ids():
    calls = []
    result = build_dreaming_version(
        parent_units=[_unit("old", "manual rule 7", constraint=True)],
        new_units=[_unit("new", "account ABC-42", new=True)], max_chars=500, prior_source="manual",
        summarizer=lambda request: calls.append(request) or DreamingSummarizationOutput(
            markdown="## Operating Constraints\n\n- manual rule 7\n\n## Account Details\n\n- account ABC-42"),
    )
    assert len(calls) == 1
    assert calls[0].prior_source == "manual"
    assert "E0001" in calls[0].new_evidence_markdown
    assert result.summarization_status == "summarized"
    assert result.published_units[0].evidence_ids == ["new", "old"]


def test_ac060_retries_validation_then_accepts():
    calls = []
    def summarize(request):
        calls.append(request)
        if request.attempt == 1:
            return DreamingSummarizationOutput(markdown="bad")
        return DreamingSummarizationOutput(markdown="## Measured Value\n\n- value 7")
    result = build_dreaming_version(parent_units=[], new_units=[_unit("n", "value 7", new=True)],
                                    max_chars=100, summarizer=summarize, backoff_base_seconds=0)
    assert len(calls) == 2
    assert "first_line_must_be_section_heading" in calls[1].validation_feedback
    assert result.summarization_attempts == 2


def test_ac061_invalid_markup_missing_literal_and_timeout_error_use_fallback():
    for output in (
        DreamingSummarizationOutput(markdown="## Contact Details\n\n```x```"),
        DreamingSummarizationOutput(markdown="## Contact Details\n\n- omitted"),
    ):
        result = build_dreaming_version(parent_units=[], new_units=[_unit("n", "email a@example.com rule 7", new=True)],
                                        max_chars=120, summarizer=lambda _: output, max_attempts=1)
        assert result.summarization_status == "mechanical_fallback"
        assert result.summarization_audit[0]["outcome"] == "rejected"

    result = build_dreaming_version(parent_units=[], new_units=[_unit("n", "value", new=True)], max_chars=80,
                                    summarizer=lambda _: (_ for _ in ()).throw(TimeoutError()), max_attempts=1)
    assert result.summarization_status == "mechanical_fallback"
    assert result.summarization_audit[0]["outcome"] == "model_error"


def test_ac062_no_new_evidence_skips_model_and_preserves_active_content():
    calls = []
    parent = _unit("old", "## Existing Preference\n\n- unchanged")
    result = build_dreaming_version(parent_units=[parent], new_units=[], summarizer=lambda req: calls.append(req))
    assert calls == []
    assert result.summarization_status == "no_new_evidence"


def test_ac063_fallback_prioritizes_manual_constraint_and_records_omissions():
    result = build_dreaming_version(
        parent_units=[_unit("manual", "must keep", constraint=True)],
        new_units=[_unit("new", "new information", new=True), _unit("extra", "extra information", new=True)],
        max_chars=65, summarizer=None,
    )
    assert result.summarization_status == "mechanical_fallback"
    assert "must keep" in result.published_content
    assert result.omitted_evidence_ids
    assert result.published_char_count <= 90


def test_ac069_requires_topical_unique_sections_with_bullets_and_no_h1():
    invalid_values = (
        "# User Memory\n\n## Projects\n\n- alpha",
        "## Facts\n\n- alpha",
        "## Projects\n\n- alpha\n\n## Projects\n\n- beta",
        "## Projects\n\nA paragraph without bullets",
        "## E0001\n\n- alpha",
        "## Map Summary 1\n\n- alpha",
    )
    for value in invalid_values:
        result = build_dreaming_version(
            parent_units=[], new_units=[_unit("n", "alpha", new=True)], max_chars=200,
            summarizer=lambda _request, value=value: DreamingSummarizationOutput(markdown=value),
            max_attempts=1,
        )
        assert result.summarization_status == "mechanical_fallback"


def test_ac071_preserves_high_value_ids_and_manual_numbers_but_not_narrative_numbers():
    accepted = DreamingSummarizationOutput(
        markdown="## Account Access\n\n- Use ABC-42 at a@example.com\n- Manual limit is 7"
    )
    result = build_dreaming_version(
        parent_units=[_unit("manual", "Manual limit is 7", constraint=True)],
        new_units=[_unit("story", "Chapter 12 used account ABC-42 and a@example.com", new=True)],
        max_chars=300, summarizer=lambda _request: accepted,
    )
    assert result.summarization_status == "summarized"
    assert "Chapter 12" not in result.published_content


def test_ac072_fallback_has_one_safe_section_and_no_document_title():
    result = build_dreaming_version(
        parent_units=[], new_units=[_unit("n", "用户偏好简洁回答", new=True)],
        max_chars=100, summarizer=None,
    )
    assert result.published_content.startswith("## 未分类记忆\n\n-")
    assert "# User Memory" not in result.published_content
