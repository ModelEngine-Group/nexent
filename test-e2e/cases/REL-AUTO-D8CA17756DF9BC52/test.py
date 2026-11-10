# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify closing or cancelling the NL2Agent response revokes its run grant."""

import asyncio
from types import SimpleNamespace

import pytest
from starlette.responses import StreamingResponse

from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent import creator_run


@pytest.mark.stage("D5")
@pytest.mark.case_id("REL-AUTO-D8CA17756DF9BC52")
@pytest.mark.asyncio
async def test_nl2agent_stream_sets_stop_event_on_close_and_cancellation(monkeypatch):
    actor = ServicePrincipal("owner", "tenant")
    payload = SimpleNamespace(run_id="a" * 32, agent_id=7, input=SimpleNamespace(query="Create"))
    grants = set()

    async def inline(_name, function, *args, **kwargs):
        return function(*args)

    monkeypatch.setattr(creator_run, "run_blocking", inline)
    monkeypatch.setattr(creator_run, "open_nl2agent_tool_grant", lambda run, *_: grants.add(run))
    monkeypatch.setattr(creator_run, "close_nl2agent_tool_grant", grants.remove)
    for cancelled in (False, True):
        closed = False
        entered = asyncio.Event()

        async def chunks():
            nonlocal closed
            try:
                yield b'data: {"type":"progress","content":"started"}\n\n'
                entered.set()
                await asyncio.Event().wait()
            finally:
                closed = True

        async def run(*_):
            return StreamingResponse(chunks())

        monkeypatch.setattr(creator_run, "forward_creator_run", run)
        stream = creator_run.create_nl2agent_stream(payload, actor)
        assert "started" in await anext(stream)
        assert payload.run_id in grants
        if cancelled:
            consumer = asyncio.create_task(anext(stream))
            await asyncio.wait_for(entered.wait(), timeout=1)
            consumer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await consumer
        else:
            await stream.aclose()
        assert closed and not grants
