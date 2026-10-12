"""D5 cancellation and thread-lifecycle contract for NL2Agent streaming."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

import services.nl2agent_service as service


@pytest.mark.stage("D5")
@pytest.mark.case_id("REL-AUTO-D8CA17756DF9BC52")
@pytest.mark.asyncio
async def test_nl2agent_stream_sets_stop_event_on_close_and_cancellation(monkeypatch) -> None:
    stop_event = threading.Event()
    run_info = SimpleNamespace(stop_event=stop_event)

    async def build(**_kwargs):
        return run_info

    async def one_chunk(_run_info, *, thread_manager):
        assert thread_manager is service.runtime_thread_manager
        yield '{"type":"progress","content":"started"}'
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "build_nl2agent_run_info", build)
    monkeypatch.setattr(service, "agent_run", one_chunk)
    stream = await service.create_nl2agent_stream(
        request=SimpleNamespace(), tenant_id="tenant-a", language="zh", authorization="token"
    )
    assert "started" in await anext(stream)
    await stream.aclose()
    assert stop_event.is_set()

    cancelled_stop = threading.Event()
    cancelled_info = SimpleNamespace(stop_event=cancelled_stop)

    async def build_cancelled(**_kwargs):
        return cancelled_info

    async def cancelled_run(_run_info, *, thread_manager):
        if False:
            yield ""
        raise asyncio.CancelledError

    monkeypatch.setattr(service, "build_nl2agent_run_info", build_cancelled)
    monkeypatch.setattr(service, "agent_run", cancelled_run)
    cancelled_stream = await service.create_nl2agent_stream(
        request=SimpleNamespace(), tenant_id="tenant-a", language="zh", authorization="token"
    )
    with pytest.raises(asyncio.CancelledError):
        await anext(cancelled_stream)
    assert cancelled_stop.is_set()
