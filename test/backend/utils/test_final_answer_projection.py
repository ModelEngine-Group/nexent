# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit regressions for final-answer ownership and persisted step cleanup."""

from copy import deepcopy

import pytest

from management.services.agent.stream import (
    remove_answer_only_steps,
    resolve_answer_completion,
)


def unit(kind, content, step="current", invocation=None, **fields):
    return {"type": kind, "content": content, "_step_id": step,
            "invocation_id": invocation, **fields}


def test_new_answer_delta_replaces_only_previous_answer_in_same_invocation():
    old = unit("final_answer", "Discarded", "previous")
    current = unit("final_answer", "Current")
    sibling = unit("final_answer", "Child result", "previous", "child")
    thought = unit("model_output_thinking", "Reasoning", "previous")
    units = [old, current, sibling, thought]
    before = deepcopy([current, sibling, thought])

    assert resolve_answer_completion(units, {
        "answer_phase": "delta", "step_id": "current", "content": "continued",
    })
    assert units == before
    assert units[0] is current and units[1] is sibling


@pytest.mark.parametrize("phase", ["delta", "complete", None])
def test_empty_event_keeps_existing_answer_without_adding_another_body(phase):
    units = [unit("final_answer", "Already streamed")]
    before = deepcopy(units)
    assert not resolve_answer_completion(units, {"answer_phase": phase, "content": ""})
    assert units == before


def test_canonical_completion_replaces_owned_answers_and_preserves_other_units():
    thought = unit("model_output_deep_thinking", "Evidence")
    sibling = unit("final_answer", "Sibling", invocation="other")
    units = [unit("final_answer", "Draft", "previous"), thought,
             unit("final_answer", "More draft"), sibling]
    assert resolve_answer_completion(units, {"answer_phase": "complete", "content": "Verified"})
    assert units == [thought, sibling]


def test_empty_legacy_completion_promotes_fragments_once_with_scoped_ownership():
    first = unit("model_output_thinking", "", _content_fragments=["Hello ", "世界"])
    code = unit("model_output_code", "!")
    deep = unit("model_output_deep_thinking", "Keep reasoning")
    sibling = unit("model_output_thinking", "Child body", invocation="child")
    other_step = unit("model_output_thinking", "Earlier thought", "earlier")
    units = [first, deep, code, sibling, other_step]

    assert not resolve_answer_completion(units, {
        "answer_phase": "complete", "reclassify_step": True, "step_id": "current", "content": "",
    })
    assert units == [first, deep, sibling, other_step]
    assert first["type"] == first["unit_type"] == "final_answer"
    assert first["content"] == first["unit_content"] == ""
    assert "".join(first["_content_fragments"]) == "Hello 世界!"
    assert sibling["content"] == "Child body" and other_step["content"] == "Earlier thought"


@pytest.mark.parametrize("content", ["", "Canonical result"])
def test_reclassification_without_ordinary_body_preserves_deep_reasoning(content):
    deep = unit("model_output_deep_thinking", "Independent reasoning")
    units = [deep]
    assert resolve_answer_completion(units, {
        "reclassify_step": True, "step_id": "current", "content": content,
    }) is bool(content)
    assert units == [deep]


def test_reclassification_requires_explicit_step_identity():
    units = [unit("model_output_thinking", "Keep body")]
    before = deepcopy(units)
    assert resolve_answer_completion(units, {"reclassify_step": True, "content": "Result"})
    assert units == before


def test_canonical_legacy_answer_removes_only_reclassified_body():
    deep = unit("model_output_deep_thinking", "Keep reasoning")
    sibling = unit("model_output_code", "Child action", invocation="child")
    earlier = unit("model_output_thinking", "Earlier thought", "earlier")
    units = [unit("model_output_thinking", "Rejected body"), deep,
             unit("model_output_code", "Rejected code"), sibling, earlier]
    assert resolve_answer_completion(units, {
        "answer_phase": "complete", "reclassify_step": True,
        "step_id": "current", "content": "Canonical result",
    })
    assert units == [deep, sibling, earlier]


@pytest.mark.parametrize("kind,content,keep", [
    ("model_output_thinking", " ", False),
    ("model_output_deep_thinking", "\n\t", False),
    ("model_output_code", "", False),
    ("model_output_thinking", "Thought", True),
    ("model_output_deep_thinking", "Provider reasoning", True),
    ("model_output_code", "print(1)", True),
    ("tool", "", True),
    ("tool-call", "", True),
    ("parse", "", True),
    ("token_count", "42", False),
])
def test_answer_step_marker_depends_on_actual_reasoning_or_actions(kind, content, keep):
    marker = unit("step_count", "Step 1")
    units = [marker, unit(kind, content), unit("final_answer", "Result")]
    remove_answer_only_steps(units)
    assert any(item is marker for item in units) is keep
    assert units[-1]["type"] == "final_answer" and units[-1]["content"] == "Result"
    assert all("_step_id" not in item for item in units)


def test_fragmented_thinking_preserves_only_its_own_step_marker():
    parent_marker = unit("step_count", "Parent")
    child_marker = unit("step_count", "Child", invocation="child")
    units = [parent_marker, unit("final_answer", "Parent result"), child_marker,
             unit("model_output_thinking", "", invocation="child", _content_fragments=["Real", " thought"]),
             unit("final_answer", "Child result", invocation="child")]
    remove_answer_only_steps(units)
    assert not any(item is parent_marker for item in units)
    assert any(item is child_marker for item in units)
    assert [item["content"] for item in units if item["type"] == "final_answer"] == ["Parent result", "Child result"]


def test_step_without_answer_is_not_removed_and_empty_buffer_is_supported():
    units = [unit("step_count", "Pending step")]
    remove_answer_only_steps(units)
    assert units == [{"type": "step_count", "content": "Pending step", "invocation_id": None}]
    remove_answer_only_steps([])
    assert not resolve_answer_completion([], {})
