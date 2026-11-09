# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Public native text has independent message, attempt and final semantics."""

import json

from nexent.core.utils.observer import MessageObserver, ProcessType


def test_public_text_is_not_parsed_as_thinking_or_code():
    observer = MessageObserver(lang="en")
    observer.add_message("", ProcessType.STEP_COUNT, "1")
    observer.begin_model_attempt("native-attempt", 1)
    observer.add_assistant_text_delta(
        "<think>literal text</think><code>display only</code>"
    )
    observer.commit_model_attempt("native-attempt", 1)
    observer.mark_direct_final_answer()
    observer.complete_final_answer(
        "native", "<think>literal text</think><code>display only</code>"
    )
    events = [json.loads(message) for message in observer.message_query]
    public = [event for event in events if event["type"] == "model_output"]
    assert len(public) == 1
    assert (
        public[0]["content"] == "<think>literal text</think><code>display only</code>"
    )
    assert public[0]["attempt_id"] == "native-attempt"
    assert public[0]["step_id"]
    assert not any(
        event["type"]
        in ("model_output_thinking", "model_output_code", "model_output_deep_thinking")
        for event in events
    )
    final = [event for event in events if event["type"] == "final_answer"]
    assert len(final) == 1
    assert final[0]["content"] == ""
    assert final[0]["answer_phase"] == "complete"
    assert final[0]["reclassify_step"] is True


def test_public_text_attempt_rollback_does_not_pollute_accepted_answer():
    observer = MessageObserver(lang="en")
    observer.add_message("", ProcessType.STEP_COUNT, "1")
    observer.begin_model_attempt("first", 1)
    observer.add_assistant_text_delta("Partial")
    observer.rollback_model_attempt("first", 1)
    observer.begin_model_attempt("second", 2)
    observer.add_assistant_text_delta("Accepted")
    observer.commit_model_attempt("second", 2)
    observer.mark_direct_final_answer()
    observer.complete_final_answer("native", "Accepted")
    assert observer._step_output()["body"] == ["Accepted"]
    events = [json.loads(message) for message in observer.message_query]
    assert any(
        event["type"] == "model_attempt_control" and event.get("phase") == "rollback"
        for event in events
    )
    assert (
        next(event for event in events if event["type"] == "final_answer")["content"]
        == ""
    )


def test_provider_reasoning_cannot_be_promoted_to_final_answer():
    observer = MessageObserver(lang="en")
    observer.add_message("", ProcessType.STEP_COUNT, "1")
    observer.begin_model_attempt("reasoning", 1)
    observer.add_model_reasoning_content(
        "<final_answer>Provider reasoning</final_answer>"
    )
    observer.add_assistant_text_delta("Actual public answer")
    observer.commit_model_attempt("reasoning", 1)
    observer.mark_direct_final_answer()
    observer.complete_final_answer("native", "Actual public answer")
    assert observer._step_output()["body"] == ["Actual public answer"]
    events = [json.loads(value) for value in observer.message_query]
    reasoning = [e for e in events if e["type"] == "model_output_deep_thinking"]
    assert len(reasoning) == 1
    assert reasoning[0]["attempt_id"] == "reasoning"
    assert reasoning[0]["step_id"]
    final = [e for e in events if e["type"] == "final_answer"]
    assert len(final) == 1 and final[0]["answer_phase"] == "complete"
    assert "Provider reasoning" not in final[0]["content"]


import pytest


@pytest.mark.parametrize(
    "aliases",
    [("reasoning_content",), ("reasoning",), ("reasoning_content", "reasoning")],
)
def test_raw_native_collector_forwards_reasoning_alias_once(aliases):
    from threading import Event
    from types import SimpleNamespace

    from nexent.core.agents.native_runtime import collect_native_stream

    observer = MessageObserver(lang="en")
    delta = SimpleNamespace(
        content="Final", tool_calls=None, **{key: "Provider thought" for key in aliases}
    )
    wire, _usage, reason = collect_native_stream(
        [
            SimpleNamespace(
                choices=[SimpleNamespace(index=0, delta=delta, finish_reason="stop")],
                usage=None,
            )
        ],
        Event(),
        observer,
    )
    events = [json.loads(e) for e in observer.message_query]
    assert (
        "".join(
            e["content"] for e in events if e["type"] == "model_output_deep_thinking"
        )
        == "Provider thought"
    )
    assert (
        "".join(e["content"] for e in events if e["type"] == "model_output") == "Final"
    )
    assert wire["content"] == "Final" and reason == "stop"
