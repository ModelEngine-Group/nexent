"""Formal D1 coverage for committed model stream visibility."""

import json

from nexent.core.utils.observer import MessageObserver, ProcessType


def _model_events(observer: MessageObserver) -> list[dict]:
    return [
        event
        for raw in observer.get_cached_message()
        if (event := json.loads(raw))["type"].startswith("model_output_")
    ]


def test_cmsr_d1_001_safe_content_streams_before_completion():
    observer = MessageObserver(lang="en")
    observer.begin_model_attempt("first", 1)
    observer.add_model_new_token("visible now")

    assert _model_events(observer) == [
        {
            "type": ProcessType.MODEL_OUTPUT_THINKING.value,
            "content": "visible now",
            "attempt_id": "first",
        }
    ]


def test_cmsr_d1_001_retry_resets_split_marker_state():
    observer = MessageObserver(lang="en")
    observer.begin_model_attempt("failed", 1)
    observer.add_model_new_token("<thi")
    observer.rollback_model_attempt("failed", 1)
    observer.begin_model_attempt("success", 2)
    observer.add_model_new_token("<")
    observer.add_model_new_token("think>reason")
    observer.add_model_new_token("</think>")
    observer.add_model_new_token("<code>print(1)</code>")
    observer.flush_remaining_tokens()
    observer.commit_model_attempt("success", 2)

    events = _model_events(observer)
    assert "".join(event["content"] for event in events) == "reason<code>print(1)</code>"
    assert all(event["attempt_id"] == "success" for event in events)
    assert events[0]["type"] == ProcessType.MODEL_OUTPUT_DEEP_THINKING.value
    assert any(event["type"] == ProcessType.MODEL_OUTPUT_THINKING.value for event in events)


def test_cmsr_d1_001_legacy_fence_survives_fragmentation_and_long_spacing():
    observer = MessageObserver(lang="en")
    observer.begin_model_attempt("legacy", 1)
    for fragment in ("First", " Co", "de:", " " * 40, "`", "``python", "\nprint(1)"):
        observer.add_model_new_token(fragment)
    observer.flush_remaining_tokens()

    events = _model_events(observer)
    assert "".join(event["content"] for event in events) == "First Code:" + " " * 40 + "```python\nprint(1)"
    assert observer.current_mode is ProcessType.MODEL_OUTPUT_CODE
    assert events[-1]["type"] == ProcessType.MODEL_OUTPUT_CODE.value


def test_cmsr_d1_001_raw_code_is_visible_before_flush():
    observer = MessageObserver(lang="en")
    observer.begin_model_attempt("code", 1)
    observer.add_model_new_token("<code>print(1)")
    events = _model_events(observer)
    assert "".join(event["content"] for event in events) == "<code>print(1)"
    assert events[-1]["attempt_id"] == "code"
