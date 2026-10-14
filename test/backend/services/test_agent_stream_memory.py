"""Acceptance-driven tests for Agent stream memory helpers."""

from management.services.agent.run import _finalize_buffered_unit_fragments


def test_ac_003_mergeable_fragments_finalize_once_without_private_fields():
    units = [{
        "type": "model_output",
        "content": "",
        "unit_content": "",
        "_content_fragments": ["alpha", "-", "beta"],
    }]

    byte_count = _finalize_buffered_unit_fragments(units)

    assert units == [{
        "type": "model_output",
        "content": "alpha-beta",
        "unit_content": "alpha-beta",
    }]
    assert byte_count == len("alpha-beta".encode("utf-8"))


def test_ac_003_non_mergeable_units_are_unchanged():
    units = [{"type": "tool", "content": "结果", "unit_content": "结果"}]

    byte_count = _finalize_buffered_unit_fragments(units)

    assert units == [{"type": "tool", "content": "结果", "unit_content": "结果"}]
    assert byte_count == len("结果".encode("utf-8"))
