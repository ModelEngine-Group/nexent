# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Retain the selected answer mode through subscriptions and memory fallback."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from . import test_agent_service as legacy
from .test_agent_subscription_lifecycle import lifecycle


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [None, "complete", "delta"])
async def test_subscription_propagates_mode_to_the_detached_producer(lifecycle, mode):
    env = lifecycle
    observed = []

    async def source(_request, **kwargs):
        observed.append(kwargs.get("final_answer_mode", "delta"))
        env.channel.complete()
        env.future.set_result(None)
        if False:
            yield ""

    await env.start(source, **({} if mode is None else {"final_answer_mode": mode}))
    await asyncio.wait_for(asyncio.gather(*env.service._agent_stream_producer_tasks), timeout=1)
    assert observed == [mode or "delta"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [None, "complete", "delta"])
@pytest.mark.parametrize("fallback", [False, True])
async def test_generator_retains_mode_during_memory_preparation_fallback(monkeypatch, mode, fallback):
    service = legacy.agent_run_service
    request = legacy.AgentRequest(agent_id=1, conversation_id=999, query="hello")
    info = SimpleNamespace()
    prepare = AsyncMock(return_value=(info, None))
    if fallback:
        prepare.side_effect = [RuntimeError("controlled preparation failure"), (info, None)]
    monkeypatch.setattr(service, "prepare_agent_run", prepare)
    monkeypatch.setattr(service, "build_memory_context", MagicMock(return_value=SimpleNamespace(
        user_config=SimpleNamespace(memory_switch=True))))
    monkeypatch.setattr(service, "_cancel_task_on_runtime_signal", AsyncMock())
    observed = []

    async def chunks(**kwargs):
        observed.append(kwargs["final_answer_mode"])
        yield "data: answer\n\n"

    monkeypatch.setattr(service, "_stream_agent_chunks", chunks)
    result = [chunk async for chunk in service.generate_stream(
        request, "user", "tenant", enable_memory=fallback,
        **({} if mode is None else {"final_answer_mode": mode}))]
    assert result == ["data: answer\n\n"]
    assert observed == [mode or "delta"]
    assert prepare.await_count == (2 if fallback else 1)
    assert prepare.await_args.kwargs["allow_memory_search"] is False
