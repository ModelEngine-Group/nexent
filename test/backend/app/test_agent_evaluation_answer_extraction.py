# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Answer extraction regressions for the final_answer delta/complete protocol.

Covers ``collect_observer_output`` and its pure extractor ``_collect_final_answer``
against the three event shapes the observer emits today:

* ``answer_phase="delta"`` fragments plus an empty ``complete`` trailer whose
  authoritative answer lives only in ``accepted_answer`` metadata,
* ``complete`` trailers carrying a full (rewritten) answer in ``content``,
* ``reclassify_step`` trailers whose answer is the step's body events,
* plus legacy events without ``answer_phase`` and multi-invocation streams.
"""

import json
from unittest.mock import Mock

import pytest

from runtime.agentos.evaluation import _collect_final_answer, collect_observer_output


def _evt(etype: str, content, **extra) -> dict:
    return {"type": etype, "content": content, **extra}


def _delta(text: str, invocation_id=None, step_id="s1") -> dict:
    event = _evt("final_answer", text, answer_phase="delta", step_id=step_id)
    if invocation_id is not None:
        event["invocation_id"] = invocation_id
    return event


def _complete(content="", *, accepted=None, reclassify=False, invocation_id=None, step_id="s1") -> dict:
    event = _evt("final_answer", content, answer_phase="complete", step_id=step_id)
    event["reclassify_step"] = reclassify
    if accepted is not None:
        event["accepted_answer"] = accepted
    if invocation_id is not None:
        event["invocation_id"] = invocation_id
    return event


def _body(text: str, invocation_id=None, step_id="s1") -> dict:
    event = _evt("model_output_thinking", text, step_id=step_id)
    if invocation_id is not None:
        event["invocation_id"] = invocation_id
    return event


def test_delta_only_stream_is_concatenated():
    events = [_delta("Hello "), _delta("world")]
    assert _collect_final_answer(events) == "Hello world"


def test_delta_plus_empty_complete_uses_accepted_answer():
    # The v2.8.4 incident shape: streamed deltas, empty trailer content.
    events = [_delta("An"), _delta("swer"), _complete(content="", accepted="Answer")]
    assert _collect_final_answer(events) == "Answer"


def test_complete_with_content_overrides_streamed_deltas():
    # Rewritten answer must replace the streamed draft (no duplication).
    events = [_delta("Draft"), _complete(content="Verified", accepted="Verified")]
    assert _collect_final_answer(events) == "Verified"


def test_accepted_answer_wins_over_conflicting_content():
    # accepted_answer is the observer-state authority; if both are present
    # and disagree, the metadata wins.
    events = [_complete(content="Stale", accepted="Authoritative")]
    assert _collect_final_answer(events) == "Authoritative"


def test_reclassify_trailer_rebuilds_from_body_events():
    events = [
        _body("Bare "),
        _body("body result"),
        _complete(content="", reclassify=True, accepted="Bare body result"),
    ]
    # accepted_answer present: authoritative path.
    assert _collect_final_answer(events) == "Bare body result"

    # Without accepted_answer (older observer), the reclassify rebuild path
    # joins the step's body events.
    legacy_events = [
        _body("Bare "),
        _body("body result"),
        _complete(content="", reclassify=True),
    ]
    assert _collect_final_answer(legacy_events) == "Bare body result"


def test_reclassify_rebuild_scopes_to_same_step_and_invocation():
    # Body fragments from another step or invocation must not leak in.
    events = [
        _body("noise from step 2", step_id="s2"),
        _body("left "),
        _body("answer"),
        _complete(content="", reclassify=True, step_id="s1"),
    ]
    assert _collect_final_answer(events) == "left answer"


def test_legacy_events_without_answer_phase_still_concatenate():
    # Pre-#4077 observers emit plain final_answer events with full bodies.
    events = [_evt("final_answer", "one "), _evt("final_answer", "answer")]
    assert _collect_final_answer(events) == "one answer"


def test_multiple_invocations_are_joined_with_newline():
    events = [
        _delta("left answer", invocation_id="left"),
        _complete(content="", accepted="left answer", invocation_id="left"),
        _body("right body", invocation_id="right"),
        _complete(content="", reclassify=True, invocation_id="right"),
    ]
    assert _collect_final_answer(events) == "left answer\nright body"


def test_no_answer_events_yields_empty_string():
    events = [_evt("thought", "step"), _evt("tool", "call")]
    assert _collect_final_answer(events) == ""


@pytest.mark.asyncio
async def test_collect_observer_output_extracts_straggler_complete_trailer():
    # Straggler messages flushed after the runner generator ends must flow
    # through the same extraction path (the v2.8.4 run-10 shape: answer events
    # arrived only in the final drain).
    observer = Mock()
    observer.get_cached_message.return_value = [
        json.dumps(_delta("Straggler ")),
        json.dumps(_complete(content="", accepted="Straggler answer")),
    ]

    async def runner(run_info, *, thread_manager):
        yield json.dumps(_evt("thought", "step"))

    info = Mock(observer=observer)
    result = await collect_observer_output(info, runner, thread_manager=None)
    assert result.answer == "Straggler answer"
    assert [event["type"] for event in result.events] == ["thought", "final_answer", "final_answer"]


@pytest.mark.asyncio
async def test_collect_observer_output_uses_main_stream_answer():
    observer = Mock()
    observer.get_cached_message.return_value = []

    async def runner(run_info, *, thread_manager):
        yield json.dumps(_delta("Main "))
        yield json.dumps(_delta("stream"))
        yield json.dumps(_complete(content="", accepted="Main stream"))

    info = Mock(observer=observer)
    result = await collect_observer_output(info, runner, thread_manager=None)
    assert result.answer == "Main stream"


@pytest.mark.asyncio
async def test_collect_observer_output_skips_unparseable_chunks():
    observer = Mock()
    observer.get_cached_message.return_value = ["not json"]

    async def runner(run_info, *, thread_manager):
        yield "bad chunk"
        yield json.dumps(_evt("final_answer", "legacy answer"))

    info = Mock(observer=observer)
    result = await collect_observer_output(info, runner, thread_manager=None)
    assert result.answer == "legacy answer"
