# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management owns automatic summary discovery, health and shutdown without restarts."""

import asyncio
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from management.services.knowledge_base import summary_dispatch as module
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied, Unavailable
from nexent.storage.models import Page

from backend.http.server.health import install_health_contract


@pytest.fixture
def discovery(monkeypatch):
    candidate = {'knowledge_id': 1, 'index_name': 'kb', 'tenant_id': 'tenant', 'user_id': 'setter'}
    records = Mock(query=Mock(return_value=Page((candidate,), 'next')))
    closed, contexts = [], []

    @contextmanager
    def ports(*, context):
        contexts.append(context)
        try: yield records
        finally: closed.append(True)

    async def blocking(name, function, **kwargs):
        assert kwargs == {'lane': 'control-io', 'owner': 'management.knowledge.summary'}
        return function()
    monkeypatch.setattr(module, 'summary_dispatch_ports', ports)
    monkeypatch.setattr(module, 'run_blocking', blocking)
    return SimpleNamespace(records=records, candidate=candidate, closed=closed, contexts=contexts)


async def test_discovery_is_bounded_and_closed_before_actual_identity_execution(discovery):
    s = discovery
    async def advance(candidate):
        assert s.closed == [True] and candidate is s.candidate
    coordinator = SimpleNamespace(advance=AsyncMock(side_effect=advance))
    assert await module.dispatch_once(coordinator, stop=Event(), cursor='old') == 'next'
    coordinator.advance.assert_awaited_once_with(s.candidate)
    args = s.records.query.call_args.args
    assert args[0] == 'management_summary_dispatch' and args[2].limit == 100 and args[2].cursor == 'old'


async def test_stop_before_discovery_opens_nothing(discovery):
    stop = Event(); stop.set()
    assert await module.dispatch_once(SimpleNamespace(), stop=stop, cursor='old') == 'old'
    discovery.records.query.assert_not_called()


@pytest.mark.parametrize('error', [Conflict(), ScopeDenied()])
async def test_changed_candidate_is_skipped_without_execution_retry(discovery, error):
    coordinator = SimpleNamespace(advance=AsyncMock(side_effect=error))
    assert await module.dispatch_once(coordinator, stop=Event()) == 'next'
    coordinator.advance.assert_awaited_once()


async def test_storage_failure_is_propagated_without_fallback_or_next_candidate(discovery):
    coordinator = SimpleNamespace(advance=AsyncMock(side_effect=Unavailable()))
    with pytest.raises(Unavailable): await module.dispatch_once(coordinator, stop=Event())
    coordinator.advance.assert_awaited_once()


async def test_stop_during_page_does_not_start_next_candidate(discovery):
    s = discovery; stop = Event()
    s.records.query.return_value = Page((s.candidate, {**s.candidate, 'knowledge_id': 2}))
    async def advance(candidate): stop.set()
    coordinator = SimpleNamespace(advance=AsyncMock(side_effect=advance))
    await module.dispatch_once(coordinator, stop=stop)
    coordinator.advance.assert_awaited_once()


async def test_pages_are_drained_before_original_poll_interval(monkeypatch):
    stop, calls = Event(), []
    async def dispatch(coordinator, *, stop, cursor):
        calls.append(cursor)
        return 'next' if len(calls) == 1 else None
    async def sleep(seconds):
        assert seconds == 1800
        stop.set()
    monkeypatch.setattr(module, 'dispatch_once', dispatch)
    monkeypatch.setattr(module.asyncio, 'sleep', sleep)
    await module.serve(SimpleNamespace(), stop=stop)
    assert calls == [None, 'next']


@pytest.mark.parametrize('interval', [0, -1, float('nan'), True, 1801])
async def test_invalid_poll_budget_rejected(interval):
    with pytest.raises(InvalidInput): await module.serve(SimpleNamespace(), stop=Event(), poll_seconds=interval)


async def test_lifespan_owns_task_and_cancels_current_work(monkeypatch):
    entered, exited = asyncio.Event(), []
    async def serve(coordinator, *, stop):
        entered.set()
        try: await asyncio.Event().wait()
        finally: exited.append(stop.is_set())
    monkeypatch.setattr(module, 'serve', serve)
    app = FastAPI()
    async with module.summary_lifespan(app, coordinator=SimpleNamespace()):
        await entered.wait()
        task, = app.state.required_background_tasks
        assert task.get_name() == 'management-knowledge-summary' and not task.done()
    assert task.cancelled() and exited == [True] and app.state.required_background_tasks == ()


async def test_failed_dispatch_reduces_readiness_and_is_not_restarted(monkeypatch):
    async def fail(*args, **kwargs): raise Unavailable()
    serve = AsyncMock(side_effect=fail)
    monkeypatch.setattr(module, 'serve', serve)
    app = FastAPI(); install_health_contract(app)
    async with module.summary_lifespan(app, coordinator=SimpleNamespace()):
        task, = app.state.required_background_tasks
        await asyncio.gather(task, return_exceptions=True)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/health/ready')).status_code == 503
            assert (await client.get('/health/live')).status_code == 200
        serve.assert_awaited_once()
    assert app.state.required_background_tasks == ()
