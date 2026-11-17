# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Summary cancellation closes in-worker HTTP and drains its managed execution."""

import asyncio
from threading import Event
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from management.clients import model
from management.services.knowledge_base import summary_service
from nexent.core.concurrency import (
    LanePolicy,
    RunCancellationScope,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.storage.errors import DeadlineExceeded

from infrastructure.agentos_client import AgentOSClient


@pytest.fixture
async def manager():
    value = ThreadManager(service_name='summary-cancel-test', lane_policies={
        'model-tool-io': LanePolicy('model-tool-io', 1, 0, cancel_grace_seconds=1),
    })
    value.start()
    set_default_thread_manager(value)
    try:
        yield value
    finally:
        clear_default_thread_manager(value)
        assert not (await value.shutdown(timeout=3)).stuck_execution_ids


@pytest.fixture
def transport(monkeypatch):
    started, exited, closed, requests = Event(), Event(), [], []

    async def blocked(request):
        requests.append(request)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    class Client(httpx.AsyncClient):
        async def __aexit__(self, *args):
            closed.append(True)
            return await super().__aexit__(*args)

    client = AgentOSClient('http://runtime', lambda **kw: Client(transport=httpx.MockTransport(blocked), **kw))
    monkeypatch.setattr(client, '_request', lambda *a: ('http://runtime/invoke', b'{}', {}))
    monkeypatch.setattr(model, '_model_client', lambda: client)
    return started, exited, closed, requests


def invoke():
    return model.invoke_chat_prompt_in_worker(model_id=1, system_prompt='secret-system',
        user_prompt='secret-user', user_id='actual-user', tenant_id='actual-tenant')


async def started(event):
    async with asyncio.timeout(3):
        while not event.is_set():
            await asyncio.sleep(0.001)


async def test_parent_cancel_closes_blocked_http_once_and_drains(manager, transport):
    service = summary_service.KnowledgeSummaryService()
    service._summarize = lambda *args: invoke()
    task = asyncio.create_task(service.summarize_sample(Mock(), user_id='actual-user', tenant_id='actual-tenant', model_id=1))
    await started(transport[0])
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport[1].is_set() and transport[2] == [True] and len(transport[3]) == 1
    assert manager.snapshot().active_count == 0


async def test_manager_close_hook_also_cancels_active_http(manager, transport):
    service = summary_service.KnowledgeSummaryService()
    service._summarize = lambda *args: invoke()
    task = asyncio.create_task(service.summarize_sample(Mock(), user_id='actual-user', tenant_id='actual-tenant'))
    await started(transport[0])
    execution_id = manager.snapshot().active_execution_ids[0]
    manager.cancel(execution_id, reason='lifespan stop', wait_timeout=0, mark_stuck_on_timeout=False)
    with pytest.raises(RunTerminated):
        await task
    assert transport[1].is_set() and transport[2] == [True] and len(transport[3]) == 1
    assert manager.snapshot().active_count == 0


async def test_model_deadline_cancels_without_retry_or_secret_logs(manager, transport, caplog):
    service = summary_service.KnowledgeSummaryService(operation_seconds=0.05)
    service._summarize = lambda *args: invoke()
    with pytest.raises(DeadlineExceeded):
        await service.summarize_sample(Mock(), user_id='actual-user', tenant_id='actual-tenant', model_id=1)
    assert transport[1].is_set() and transport[2] == [True] and len(transport[3]) == 1
    assert manager.snapshot().active_count == 0
    logs = [r for r in caplog.records if 'knowledge_summary_model_timeout' in r.message]
    assert len(logs) == 1 and logs[0].levelname == 'WARNING'
    assert 'phase=model' in logs[0].message and 'threshold_seconds=0.05' in logs[0].message
    assert 'secret' not in caplog.text and not any(r.levelname == 'ERROR' for r in caplog.records)


def test_cancel_before_model_starts_never_opens_transport(transport):
    scope = RunCancellationScope()
    scope.cancel()
    with pytest.raises(RunTerminated), model.worker_model_cancellation(scope):
        invoke()
    assert not transport[0].is_set() and transport[2] == [] and transport[3] == []


def test_scope_reset_does_not_leak_cancel_to_unrelated_worker(monkeypatch):
    from contracts.agentos import ModelResult
    client = Mock(invoke_model=AsyncMock(return_value=ModelResult(revision='v1', output={'content': 'answer'})))
    monkeypatch.setattr(model, '_model_client', lambda: client)
    scope = RunCancellationScope()
    with model.worker_model_cancellation(scope):
        scope.cancel()
    assert invoke() == 'answer'
    client.invoke_model.assert_awaited_once()


async def test_pre_sampled_input_is_used_once_with_exact_model_parameters(manager):
    sample = Mock()
    service = summary_service.KnowledgeSummaryService()
    service._summarize = Mock(return_value='summary')
    assert await service.summarize_sample(sample, language='zh', model_id=5,
        user_id='actual-user', tenant_id='actual-tenant') == 'summary'
    service._summarize.assert_called_once_with(sample, 'zh', 5, 'actual-user', 'actual-tenant')
    assert manager.snapshot().active_count == 0


async def test_worker_error_is_propagated_and_capacity_released(manager):
    service = summary_service.KnowledgeSummaryService()
    service._summarize = Mock(side_effect=ValueError('invalid sample'))
    with pytest.raises(ValueError, match='invalid sample'):
        await service.summarize_sample(Mock(), user_id='actual-user', tenant_id='actual-tenant')
    assert manager.snapshot().active_count == 0


async def test_capacity_rejection_never_starts_model(manager):
    from nexent.core.concurrency import ManagedTaskSpec, ThreadCapacityExceeded

    release = Event()
    occupied = manager.submit('model-tool-io', ManagedTaskSpec(task_name='occupied', owner='test'), release.wait, 3)
    service = summary_service.KnowledgeSummaryService()
    service._summarize = Mock()
    try:
        with pytest.raises(ThreadCapacityExceeded):
            await service.summarize_sample(Mock(), user_id='actual-user', tenant_id='actual-tenant')
        service._summarize.assert_not_called()
    finally:
        release.set()
        await asyncio.wrap_future(occupied.future)


@pytest.mark.parametrize('repeat_cancel', [False, True])
async def test_undrained_worker_is_marked_stuck_instead_of_claimed_closed(manager, monkeypatch, repeat_cancel):
    monkeypatch.setattr(summary_service, '_MODEL_CLOSE_GRACE_SECONDS', 3 if repeat_cancel else 0.02)
    entered, release = Event(), Event()
    service = summary_service.KnowledgeSummaryService()

    def stuck(*args):
        entered.set()
        release.wait(3)
        return 'late summary'

    service._summarize = stuck
    task = asyncio.create_task(service.summarize_sample(Mock(), user_id='actual-user', tenant_id='actual-tenant'))
    try:
        await started(entered)
        task.cancel()
        if repeat_cancel:
            async with asyncio.timeout(1):
                while not any(item.state.value == 'stop_requested' for item in manager.snapshot().executions):
                    await asyncio.sleep(0.001)
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert manager.snapshot().stuck_count == 1
    finally:
        release.set()
        async with asyncio.timeout(3):
            while manager.snapshot().active_count:
                await asyncio.sleep(0.001)


@pytest.mark.parametrize('user_id,tenant_id', [(None, 'tenant'), ('user', None)])
async def test_missing_identity_never_submits_model(manager, user_id, tenant_id):
    from nexent.storage.errors import ScopeDenied

    service = summary_service.KnowledgeSummaryService()
    service._summarize = Mock()
    with pytest.raises(ScopeDenied):
        await service.summarize_sample(Mock(), user_id=user_id, tenant_id=tenant_id)
    service._summarize.assert_not_called()
    assert manager.snapshot().active_count == 0


async def test_lifespan_manager_is_required_without_fallback_thread():
    from nexent.core.concurrency import ThreadManagerNotRunning

    service = summary_service.KnowledgeSummaryService()
    service._summarize = Mock()
    with pytest.raises(ThreadManagerNotRunning):
        await service.summarize_sample(Mock(), user_id='user', tenant_id='tenant')
    service._summarize.assert_not_called()
