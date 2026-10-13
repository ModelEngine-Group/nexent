"""Answer streaming regressions for completion, retries and invocation ownership."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from nexent.core.utils.observer import MessageObserver, ProcessType


def events(observer):
    return [json.loads(raw) for raw in observer.get_cached_message()]


@pytest.mark.parametrize("opening,closing", [
    ("<final_answer>", "</final_answer>"),
    ("<FINAL_ANSWER>", "</FINAL_ANSWER>"),
    ("<Final_Answer>", "</Final_Answer>"),
])
@pytest.mark.parametrize("prefix,kind", [
    ("", None), ("Thought. ", "model_output_thinking"),
    ("<think>Evidence.</think>", "model_output_deep_thinking"),
])
def test_streamed_answer_keeps_prefix_role_and_completion_does_not_repeat_body(opening, closing, prefix, kind):
    observer = MessageObserver()
    observer.add_message("agent", ProcessType.STEP_COUNT, 1)
    observer.begin_model_attempt("accepted", 1)
    for fragment in (prefix + opening[:5], opening[5:] + "Answer", closing + " tail"):
        observer.add_model_new_token(fragment)
    observer.flush_remaining_tokens()
    assert observer.get_final_answer() == "Answer tail"
    observer.complete_final_answer("agent", "Answer tail")
    result = events(observer)
    answers = [item for item in result if item["type"] == "final_answer"]
    assert "".join(item["content"] for item in answers) == "Answer tail"
    assert answers[-1]["content"] == "" and answers[-1]["answer_phase"] == "complete"
    assert all(item["attempt_id"] == "accepted" for item in answers)
    thoughts = [item for item in result if item["type"].startswith("model_output")]
    assert {item["type"] for item in thoughts} == ({kind} if kind else set())
    assert len({item["step_id"] for item in result}) == 1


def test_answer_opening_flushes_existing_legacy_buffer_before_answer():
    observer = MessageObserver()
    observer.token_buffer = deque(["Pending reasoning"])
    observer.add_model_new_token("<final_answer>Result</final_answer>")
    result = events(observer)
    assert [(item["type"], item["content"]) for item in result] == [
        ("model_output_thinking", "Pending reasoning"), ("final_answer", "Result")]
    assert not observer.token_buffer


def test_single_chunk_mixed_response_keeps_thought_outside_answer():
    observer = MessageObserver()
    observer.add_model_new_token("Thought. <final_answer>Answer</final_answer>")
    result = events(observer)
    assert [(item["type"], item["content"]) for item in result] == [
        ("model_output_thinking", "Thought. "), ("final_answer", "Answer")]


def test_incomplete_opening_tag_stays_in_thinking_when_generation_ends():
    observer = MessageObserver()
    observer.add_model_new_token("Ordinary text <fi")
    observer.flush_remaining_tokens()
    result = events(observer)
    assert all(item["type"] == "model_output_thinking" for item in result)
    assert "".join(item["content"] for item in result) == "Ordinary text <fi"


@pytest.mark.parametrize("text,kind,expected", [
    ("<final_answer>Reply <fi", "final_answer", "Reply <fi"),
    ("<think>Evidence </th", "model_output_deep_thinking", "Evidence </th"),
])
def test_truncated_tag_suffix_is_preserved_in_its_original_role(text, kind, expected):
    observer = MessageObserver()
    observer.add_model_new_token(text)
    observer.flush_remaining_tokens()
    assert "".join(item["content"] for item in events(observer) if item["type"] == kind) == expected


def test_verification_replacement_and_unstreamed_completion_have_one_canonical_body():
    observer = MessageObserver()
    observer.add_model_new_token("<final_answer>Draft</final_answer>")
    observer.complete_final_answer("agent", "Verified")
    assert observer.get_final_answer() == "Verified"
    assert events(observer)[-1]["content"] == "Verified"
    observer.add_message("agent", ProcessType.STEP_COUNT, 2)
    observer.complete_final_answer("agent", "Runtime result")
    assert observer.get_final_answer() == "Runtime result"
    assert [item["content"] for item in events(observer) if item["type"] == "final_answer"] == ["Runtime result"]


def test_direct_answer_completion_marks_body_for_move_without_retransmission():
    observer = MessageObserver()
    observer.add_model_new_token("Legacy result")
    observer.mark_direct_final_answer()
    observer.complete_final_answer("agent", "Legacy result")
    assert observer.get_final_answer() == "Legacy result"
    completion = events(observer)[-1]
    assert completion["reclassify_step"] is True and completion["content"] == ""


def test_completed_event_without_cached_fragments_falls_back_to_event_content():
    observer = MessageObserver()
    observer.add_message("agent", ProcessType.FINAL_ANSWER, "Fallback", answer_phase="complete")
    assert observer.get_final_answer() == "Fallback"


def test_retry_discards_failed_answer_state_before_accepted_completion():
    observer = MessageObserver()
    observer.begin_model_attempt("failed", 1)
    observer.add_model_new_token("<final_answer>Rejected</final_answer>")
    observer.complete_final_answer("agent", "Rejected")
    observer.rollback_model_attempt("failed", 1)
    events(observer)
    observer.begin_model_attempt("retry", 2)
    observer.add_model_new_token("<final_answer>Accepted</final_answer>")
    observer.complete_final_answer("agent", "Accepted")
    assert observer.get_final_answer() == "Accepted"
    result = events(observer)
    assert "Rejected" not in str(result)
    assert "".join(item["content"] for item in result if item["type"] == "final_answer") == "Accepted"


def test_parallel_subagents_never_share_answer_fragments_or_step_identity():
    observer = MessageObserver()
    barrier = threading.Barrier(2)

    def run_child(name):
        observer.add_subagent_start(1, name, invocation_id=name)
        observer.add_message(name, ProcessType.STEP_COUNT, 1)
        observer.begin_model_attempt(name, 1)
        observer.add_model_new_token("<final_answer>" + name)
        barrier.wait(timeout=5)
        observer.add_model_new_token(" result</final_answer>")
        observer.complete_final_answer(name, name + " result")
        observer.add_subagent_end(1, name, invocation_id=name)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run_child, ["left", "right"]))
    result = events(observer)
    steps = []
    for name in ("left", "right"):
        child = [item for item in result if item.get("invocation_id") == name]
        answers = [item for item in child if item["type"] == "final_answer"]
        assert "".join(item["content"] for item in answers) == name + " result"
        assert answers[-1]["content"] == ""
        steps.append(next(item["step_id"] for item in child if item["type"] == "step_count"))
    assert steps[0] != steps[1]
