# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Graceful creator boundaries must survive the SDK stream bridge."""

import asyncio
import json
from concurrent.futures import Future
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from management.services.conversation import creation_history
from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
from nexent.core.agents.orchestration.entry import agent_run
from nexent.core.utils.observer import ProcessType
from services.nl2agent_service import _Nl2AgentBoundaryObserver


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_finished", [False, True])
@pytest.mark.parametrize(
    "subtype", ["requirement_clarification", "installed_resource_binding"]
)
async def test_boundary_reaches_history_before_worker_cleanup(
    monkeypatch, worker_finished, subtype
):
    stop = Event()
    observer = _Nl2AgentBoundaryObserver(lang="en", stop_event=stop)
    future = Future()
    manager = MagicMock()
    manager.submit.return_value = SimpleNamespace(
        future=future, execution_id="boundary-test"
    )
    info = SimpleNamespace(
        observer=observer,
        stop_event=stop,
        runtime_metadata={},
        cancellation_scope=SimpleNamespace(cancel=MagicMock()),
    )
    save = MagicMock(return_value=101)
    monkeypatch.setattr(creation_history, "save_message", save)
    monkeypatch.setattr(creation_history, "save_message_unit", MagicMock())
    observer.add_message("creator", ProcessType.PARSE, "print(card)")

    async def source():
        async for event in agent_run(info, thread_manager=manager):
            yield f"data: {event}\n\n"

    stream = creation_history.persist_creation_stream(
        source(),
        conversation_id=91,
        assistant_index=3,
        user_id="user",
        tenant_id="tenant",
    )
    assert json.loads((await anext(stream)).removeprefix("data: "))["type"] == "parse"
    payload = {
        "subtype": subtype,
        "agent_id": 42,
        "resources": [],
        "questions": [
            {
                "question_id": "next",
                "question_type": "text",
                "title": "Next requirement?",
                "required": True,
                "options": [],
                "allow_other": False,
                "other_input_expanded": False,
            }
        ],
    }
    observer.add_message(
        "creator",
        ProcessType.EXECUTION_LOGS,
        "<nl2a>" + json.dumps(payload) + "</nl2a>",
    )
    if worker_finished:
        future.set_result(None)
    try:
        event = await asyncio.wait_for(anext(stream), timeout=1)
        assert json.loads(event.removeprefix("data: "))["type"] == "nl2a"
        if not future.done():
            future.set_result(None)
        async for _ in stream:
            pass
        assert save.call_args.kwargs["status"] == "completed"
        assert not stop.is_set()
    finally:
        if not future.done():
            future.set_result(None)
        await stream.aclose()


@pytest.mark.asyncio
async def test_explicit_stop_still_cancels_before_worker_cleanup():
    stop = Event()
    future = Future()
    manager = MagicMock()
    manager.submit.return_value = SimpleNamespace(
        future=future, execution_id="stop-test"
    )
    observer = _Nl2AgentBoundaryObserver(lang="en", stop_event=stop)
    info = SimpleNamespace(
        observer=observer,
        stop_event=stop,
        runtime_metadata={},
        cancellation_scope=SimpleNamespace(cancel=MagicMock()),
    )
    stop.set()
    with pytest.raises(asyncio.CancelledError):
        await anext(agent_run(info, thread_manager=manager))
    manager.cancel.assert_called_once()
    future.cancel()


@pytest.mark.parametrize("max_steps", [1, 3])
def test_card_boundary_prevents_another_action_or_max_steps_fallback(max_steps):
    stop = Event()
    observer = _Nl2AgentBoundaryObserver(lang="en", stop_event=stop)
    agent = object.__new__(CoreAgent)
    agent.observer, agent.stop_event = observer, stop
    agent.enable_planning = False
    agent.agent_name = "creator"
    agent.memory = SimpleNamespace(steps=[])
    agent._finalize_step = MagicMock()
    agent._collect_step_metrics = MagicMock()
    agent._handle_max_steps_reached = MagicMock()
    calls = []

    def step(_action):
        calls.append(1)
        observer.add_message(
            "creator",
            ProcessType.EXECUTION_LOGS,
            '<nl2a>{"subtype":"requirement_clarification","agent_id":42,"questions":[]}</nl2a>',
        )
        yield None

    agent._step_stream = step
    list(agent._run_stream("create", max_steps))
    assert len(calls) == 1
    assert len(agent.memory.steps) == 1
    agent._handle_max_steps_reached.assert_not_called()
    assert not stop.is_set()
