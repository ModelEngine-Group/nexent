# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json

from nexent.core.utils.observer import MessageObserver, ProcessType


def _events(observer: MessageObserver) -> list[dict]:
    return [json.loads(item) for item in observer.get_cached_message()]


def test_cmsr_003_model_attempt_events_stamp_chunks_and_reset_parser_state():
    observer = MessageObserver(lang="en")

    observer.begin_model_attempt("attempt-one", 1)
    observer.add_model_reasoning_content("partial reasoning")
    observer.add_model_new_token("partial code")
    observer.rollback_model_attempt("attempt-one", 1)

    assert not observer.token_buffer
    assert not observer.think_buffer
    assert observer.current_mode is ProcessType.MODEL_OUTPUT_THINKING
    assert observer.in_think_mode is False

    events = _events(observer)
    assert events[0] == {
        "type": "model_attempt_control",
        "content": "",
        "phase": "begin",
        "attempt_id": "attempt-one",
        "attempt": 1,
    }
    assert events[1]["attempt_id"] == "attempt-one"
    assert events[-1]["phase"] == "rollback"


def test_cmsr_003_new_attempt_never_inherits_failed_attempt_identity():
    observer = MessageObserver(lang="en")
    observer.begin_model_attempt("attempt-one", 1)
    observer.rollback_model_attempt("attempt-one", 1)
    observer.begin_model_attempt("attempt-two", 2)
    observer.add_model_reasoning_content("clean")
    observer.commit_model_attempt("attempt-two", 2)

    events = _events(observer)
    model_event = next(event for event in events if event["type"] == "model_output_deep_thinking")
    assert model_event["attempt_id"] == "attempt-two"
    assert events[-1]["phase"] == "commit"


def test_cmsr_004_terminal_error_keeps_string_content_and_stable_metadata():
    observer = MessageObserver(lang="en")
    observer.add_message(
        "agent",
        ProcessType.ERROR,
        "The model request failed.",
        error_code="model_unknown_error",
        retryable=False,
    )

    assert _events(observer) == [
        {
            "type": "error",
            "content": "The model request failed.",
            "error_code": "model_unknown_error",
            "retryable": False,
        }
    ]


def test_split_internal_records_never_enter_sse_before_rollback():
    observer = MessageObserver(lang="en")
    observer.begin_model_attempt("echo", 1)
    for part in (
        'Leading <completed_act',
        'ion_history read_only="true"><completed_',
        'action>INTERNAL_BODY</completed_action></completed_ac',
        'tion_history><final_answer>Public result</final_answer>',
    ):
        observer.add_model_new_token(part)
    for part in ("Visible <code_ex", "ec_result>INTERNAL_REASON</code_exec_result> reasoning"):
        observer.add_model_reasoning_content(part)
    observer.flush_remaining_tokens()

    events = _events(observer)
    output = "".join(event["content"] for event in events if event["type"].startswith("model_output"))
    assert "INTERNAL" not in output
    assert "completed_action" not in output
    assert "Leading " in output
    assert "Visible  reasoning" in output
    assert "".join(event["content"] for event in events if event["type"] == "final_answer") == "Public result"

    observer.add_model_new_token("<completed_action_history>Never closed")
    observer.rollback_model_attempt("echo", 1)
    observer.begin_model_attempt("clean", 1)
    observer.add_model_new_token("New ordinary text <")
    observer.flush_remaining_tokens()
    assert "".join(event["content"] for event in _events(observer)) == "New ordinary text <"

def test_provider_tool_markup_never_streams_across_fragmented_tags():
    observer = MessageObserver(lang="en")
    observer.begin_model_attempt("dsml", 1)
    for part in (
        "Before <｜", "｜DS", 'ML｜｜ calls><｜｜DSML｜｜ invoke name="run_skill_script">',
        '<｜｜DSML｜｜ parameter name="script_path">PRIVATE_PARAMETER', '</｜｜DSML｜｜ parameter>',
        "</｜｜DSML｜｜ invoke></｜｜DSML｜｜ calls>", " after",
    ):
        observer.add_model_new_token(part)
    observer.add_model_reasoning_content("<|DS")
    observer.add_model_reasoning_content("ML|invoke>PRIVATE_REASON</|DSML|invoke>")
    observer.flush_remaining_tokens()

    output = "".join(event["content"] for event in _events(observer))
    assert output == "Before  after"
