# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Mixed action/final responses retain ordinary streaming and attempt isolation."""
import json

import pytest

from nexent.core.utils.observer import MessageObserver


@pytest.mark.parametrize('chunk_size', [1, 3, 1000])
@pytest.mark.parametrize('prefix', ['<CODE>actual()</CODE>', '```<run>actual()```'])
def test_mixed_answer_streams_without_waiting_for_runtime_result(prefix, chunk_size):
    observer = MessageObserver(lang='en')
    observer.begin_model_attempt('action', 1)
    output = prefix + '<final_answer>UNCONFIRMED</final_answer>'
    for offset in range(0, len(output), chunk_size):
        observer.add_model_new_token(output[offset:offset+chunk_size])
    observer.flush_remaining_tokens()
    events = [json.loads(value) for value in observer.message_query]
    assert ''.join(event.get('content', '') for event in events if event.get('type') == 'final_answer') == 'UNCONFIRMED'
    observer.commit_model_attempt('action', 1)
    observer.begin_model_attempt('next-response', 1)
    observer.add_model_new_token('<final_answer>CONFIRMED</final_answer>')
    observer.flush_remaining_tokens()
    events = [json.loads(value) for value in observer.message_query]
    for attempt, expected in [('action', 'UNCONFIRMED'), ('next-response', 'CONFIRMED')]:
        assert ''.join(event.get('content', '') for event in events
                       if event.get('type') == 'final_answer' and event.get('attempt_id') == attempt) == expected


def test_quoted_action_example_does_not_suppress_normal_answer():
    observer = MessageObserver(lang='en')
    observer.begin_model_attempt('answer', 1)
    observer.add_model_new_token('Example `<code>display()</code>`\n<final_answer>DISPLAY_ONLY</final_answer>')
    observer.flush_remaining_tokens()
    events = [json.loads(value) for value in observer.message_query]
    assert any(event.get('type') == 'final_answer' and event.get('content') == 'DISPLAY_ONLY' for event in events)
