from __future__ import annotations

import asyncio
import logging
import threading
from unittest.mock import AsyncMock

import pytest

from nexent.core.agents.a2a_agent_proxy import A2AAgentInfo, ExternalA2AAgentProxy


class FakeCancellationScope:
    """Minimal RunCancellationScope contract used only as a test double."""

    def __init__(self):
        self.stop_event = threading.Event()
        self.registered = []
        self.unregistered = []
        self._counter = 0

    def register_closer(self, closer):
        self._counter += 1
        token = 'token-%d' % self._counter
        self.registered.append((token, closer))
        return token

    def unregister_closer(self, token):
        self.unregistered.append(token)


async def _blocking_worker(marker):
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        marker['cancelled'] = True
        raise


@pytest.mark.case_id('UT-SDK-AUTO-ED416510CCE29002')
@pytest.mark.stage('D1')
@pytest.mark.asyncio
async def test_cancel_active_cancels_in_flight_task_and_closes_http_client(caplog):
    caplog.set_level(logging.INFO, logger='a2a_agent_proxy')
    info = A2AAgentInfo(
        agent_id='ext-a2a-1',
        name='External A2A',
        url='https://example.invalid/a2a',
        api_key='sk-super-secret-do-not-leak',
    )

    scope = FakeCancellationScope()
    http_client = AsyncMock()
    proxy = ExternalA2AAgentProxy(info, cancellation_scope=scope)
    proxy._client = http_client
    proxy._client_closed = False

    token = proxy._activate_call()
    assert token is not None
    assert proxy._active_token == token
    assert proxy._active_loop is asyncio.get_running_loop()
    assert proxy._active_task is asyncio.current_task()
    assert len(scope.registered) == 1
    assert scope.registered[0][1] == proxy.cancel_active

    proxy._deactivate_call(token)
    assert scope.unregistered == [token]
    assert proxy._active_loop is None
    assert proxy._active_task is None
    assert proxy._active_token is None

    marker = {'cancelled': False}
    child = asyncio.create_task(_blocking_worker(marker))
    await asyncio.sleep(0)
    proxy._active_loop = asyncio.get_running_loop()
    proxy._active_task = child

    proxy.cancel_active()

    assert scope.stop_event.is_set()
    for _ in range(10):
        await asyncio.sleep(0)
    assert marker['cancelled'] is True
    http_client.aclose.assert_awaited_once()

    try:
        await child
    except asyncio.CancelledError:
        pass

    proxy_no_scope = ExternalA2AAgentProxy(info)
    assert proxy_no_scope.cancellation_scope is None
    assert proxy_no_scope._client is None
    assert proxy_no_scope._activate_call() is None

    scope3 = FakeCancellationScope()
    proxy_no_loop = ExternalA2AAgentProxy(info, cancellation_scope=scope3)
    http_client3 = AsyncMock()
    proxy_no_loop._client = http_client3
    proxy_no_loop._client_closed = False
    proxy_no_loop.cancel_active()
    assert scope3.stop_event.is_set()
    http_client3.aclose.assert_not_awaited()

    scope4 = FakeCancellationScope()
    proxy_closed_loop = ExternalA2AAgentProxy(info, cancellation_scope=scope4)
    http_client4 = AsyncMock()
    proxy_closed_loop._client = http_client4
    proxy_closed_loop._client_closed = False
    closed_loop = asyncio.new_event_loop()
    closed_loop.close()
    proxy_closed_loop._active_loop = closed_loop
    proxy_closed_loop._active_task = asyncio.current_task()
    proxy_closed_loop.cancel_active()
    assert scope4.stop_event.is_set()
    http_client4.aclose.assert_not_awaited()

    assert 'sk-super-secret-do-not-leak' not in caplog.text
