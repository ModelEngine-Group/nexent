# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Project one invocation's completed SSE answer without counting frame chunks."""


def final_answer_text(events, *, invocation_id=None):
    answers = {}
    ordinary = {}
    complete = set()
    for wrapped in events:
        event = wrapped.get('data') if isinstance(wrapped.get('data'), dict) else wrapped
        if event.get('invocation_id') != invocation_id:
            continue
        if invocation_id is None and event.get('depth', 0) != 0:
            continue
        assert event.get('type') != 'error', 'Invocation ended with a runtime error'
        key = (event.get('step_id'), event.get('attempt_id'))
        if event.get('type') == 'final_answer' and event.get('attempt_id') is None:
            # Observer completion carries the step ID but omits attempt_id.
            # Close the last surviving attempt in that step, never a sibling.
            candidates = [candidate for candidate in dict.fromkeys([*ordinary, *answers])
                          if candidate[0] == key[0]]
            if candidates:
                key = candidates[-1]
        if event.get('type') == 'model_attempt_control' and event.get('phase') == 'rollback':
            answers.pop(key, None)
            ordinary.pop(key, None)
            complete.discard(key)
        if event.get('type') == 'model_output_thinking':
            ordinary[key] = ordinary.get(key, '') + (event.get('content') or '')
        if event.get('type') != 'final_answer':
            continue
        content = event.get('content') or ''
        phase = event.get('answer_phase')
        if phase == 'delta':
            answers[key] = answers.get(key, '') + content
        else:
            # A nonempty completion is authoritative; an empty completion closes
            # its accumulated deltas. Legacy final frames carry the full body.
            fallback = ordinary.get(key, '') if event.get('reclassify_step') is True else ''
            answers[key] = content or answers.get(key, '') or fallback
            complete.add(key)
    assert complete, 'Invocation has no completed final answer'
    result = ''.join(answers[key] for key in answers if key in complete)
    assert result.strip(), 'Invocation completed without a nonempty answer'
    return result


def assert_rejected_answer_stream(events):
    """Provisional final deltas are valid only inside explicitly rolled-back attempts."""
    begun, pending = set(), set()
    for wrapped in events:
        event = wrapped.get('data') if isinstance(wrapped.get('data'), dict) else wrapped
        key = (event.get('invocation_id'), event.get('step_id'), event.get('attempt_id'))
        if event.get('type') == 'model_attempt_control':
            if event.get('phase') == 'begin':
                begun.add(key)
            elif event.get('phase') == 'rollback':
                pending.discard(key)
            elif event.get('phase') == 'commit':
                assert key not in pending, 'Rejected final-answer fragments were committed'
        if event.get('type') == 'final_answer':
            assert event.get('answer_phase') == 'delta', 'Rejected stream completed a final answer'
            assert key in begun and key[1] and key[2], 'Rejected answer fragment lacks an owned attempt'
            pending.add(key)
    assert not pending, 'Rejected final-answer fragments did not roll back in their own attempts'
