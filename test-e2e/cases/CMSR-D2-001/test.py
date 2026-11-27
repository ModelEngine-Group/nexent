# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Formal D2 SSE contract for model-attempt streams."""

import asyncio

import pytest

from shared.attempt_journal import observe_attempt_journal


pytestmark = [pytest.mark.case_id("CMSR-D2-001"), pytest.mark.stage("D2")]


def control(phase, attempt):
    return {"type": "model_attempt_control", "content": "", "phase": phase, "attempt_id": attempt}


def delta(content, attempt):
    return {"type": "model_output_thinking", "content": content, "attempt_id": attempt}


async def _success_delta_is_published_before_completion(monkeypatch, failed_content):
    allow_attempt = asyncio.Event()
    finish_attempt = asyncio.Event()

    async def runtime_events():
        yield {"type": "step_count", "content": "**Step 1**"}
        await allow_attempt.wait()
        yield control("begin", "failed")
        yield delta(failed_content, "failed")
        yield control("rollback", "failed")
        yield control("begin", "success")
        yield delta("<code>print", "success")
        await finish_attempt.wait()
        yield delta("(1)</code>", "success")
        yield control("commit", "success")
        yield {"type": "parse", "content": "print(1)"}

    async with observe_attempt_journal(monkeypatch, runtime_events()) as (stream, writes):
        step = await asyncio.wait_for(anext(stream), timeout=2)
        assert step["type"] == "step_count"
        assert not writes and not allow_attempt.is_set()
        allow_attempt.set()
        before = [await asyncio.wait_for(anext(stream), timeout=2) for _ in range(5)]
        assert before == [
            control("begin", "failed"), delta(failed_content, "failed"), control("rollback", "failed"),
            control("begin", "success"), delta("<code>print", "success"),
        ]
        assert not writes and not finish_attempt.is_set()
        finish_attempt.set()
        assert [event async for event in stream] == [
            delta("(1)</code>", "success"), control("commit", "success"), {"type": "parse", "content": "print(1)"},
        ]

    assert len(writes) == 1 and writes[0]["terminal_status"] == "completed"
    units = writes[0]["message_units"]
    assert not any(unit["unit_type"] == "model_attempt_control" for unit in units)
    contents = "".join(unit["unit_content"] for unit in units)
    assert failed_content not in contents
    assert "<code>print(1)</code>" in contents


async def _exhausted_raw_answer_streams_before_commit(monkeypatch):
    """OC-030: final fallback stays live and persists only its accepted attempt."""
    finish_attempt = asyncio.Event()

    async def runtime_events():
        for attempt in ("first", "second"):
            yield control("begin", attempt)
            yield delta("rejected", attempt)
            yield control("rollback", attempt)
        yield control("begin", "third")
        yield delta("final ", "third")
        await finish_attempt.wait()
        yield delta("answer", "third")
        yield control("commit", "third")
        yield {"type": "final_answer", "content": "final answer"}

    async with observe_attempt_journal(monkeypatch, runtime_events()) as (stream, writes):
        published = [await asyncio.wait_for(anext(stream), timeout=2) for _ in range(8)]
        assert published[-1] == delta("final ", "third")
        assert not any(event.get("phase") == "commit" for event in published)
        assert not writes
        finish_attempt.set()
        published.extend([event async for event in stream])

    assert [event["phase"] for event in published if event.get("phase") in {"rollback", "commit"}] == [
        "rollback", "rollback", "commit",
    ]
    assert len(writes) == 1 and writes[0]["terminal_status"] == "completed"
    units = writes[0]["message_units"]
    assert not any(unit["unit_type"] == "model_attempt_control" for unit in units)
    contents = "".join(unit["unit_content"] for unit in units)
    assert "rejected" not in contents and "final answer" in contents


@pytest.mark.asyncio
async def test_cmsr_d2_001(monkeypatch):
    """Publish the Case result only when all stream and persistence assertions finish."""
    for failed_content in ("failed text", "<code></code>"):
        with monkeypatch.context() as isolated:
            await _success_delta_is_published_before_completion(isolated, failed_content)
    with monkeypatch.context() as isolated:
        await _exhausted_raw_answer_streams_before_commit(isolated)
