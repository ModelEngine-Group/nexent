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
