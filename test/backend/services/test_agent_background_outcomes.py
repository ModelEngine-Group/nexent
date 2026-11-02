# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Background execution must report this execution's persisted terminal result."""

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from contracts.agent import AgentRequest
from management.services.agent import run


@pytest.fixture
def background(monkeypatch):
    monkeypatch.setattr(run, "build_agent_run_context", lambda *a, **k: SimpleNamespace(
        metadata={}, enable_memory=False,
    ))
    monkeypatch.setattr(run, "agent_monitoring_context", lambda *a: nullcontext())
    monkeypatch.setattr(run, "get_latest_assistant_message", lambda *a: pytest.fail(
        "A background run must never reuse the latest conversation message"
    ), raising=False)
    return AgentRequest(query="controlled", conversation_id=99, agent_id=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,persisted,expected", [
    ("completed", True, "completed"),
    ("failed", True, "failed"),
    ("completed", False, "failed"),
    (None, False, "failed"),
    ("stopped", True, "stopped"),
])
async def test_background_requires_current_terminal_outcome(monkeypatch, background, outcome, persisted, expected):
    async def stream(*args, **kwargs):
        state = kwargs.get("execution_state")
        if state is not None:
            state.assistant_message_id = 123
            state.outcome = outcome
            state.persisted = persisted
        yield 'data: {"type":"error","content":"controlled event"}\n\n'

    monkeypatch.setattr(run, "generate_stream", stream)
    result = await run.run_agent_background(background, "owner", "tenant", skip_user_save=True)
    assert result["status"] == expected
    assert result["assistant_message_id"] == 123
    assert result["chunks"] == 1
    assert background._message_source == "AUTOMATION"
    if expected == "failed":
        assert result["error_code"]


@pytest.mark.asyncio
async def test_preparation_failure_cannot_reuse_previous_assistant(monkeypatch, background):
    async def stream(*args, **kwargs):
        state = kwargs.get("execution_state")
        if state is not None:
            state.fail("AUTOMATION_PREPARATION_FAILED", "Preparation failed")
        yield 'data: {"type":"error","content":"preparation failed"}\n\n'

    monkeypatch.setattr(run, "generate_stream", stream)
    result = await run.run_agent_background(background, "owner", "tenant", skip_user_save=True)
    assert result["status"] == "failed"
    assert result["assistant_message_id"] is None
    assert result["error_code"] == "AUTOMATION_PREPARATION_FAILED"


@pytest.mark.asyncio
async def test_background_cancellation_closes_stream_and_propagates(monkeypatch, background):
    closed = asyncio.Event()

    async def stream(*args, **kwargs):
        try:
            await asyncio.sleep(60)
            yield "unreachable"
        finally:
            closed.set()

    monkeypatch.setattr(run, "generate_stream", stream)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(run.run_agent_background(
            background, "owner", "tenant", skip_user_save=True,
        ), timeout=0.02)
    assert closed.is_set()
