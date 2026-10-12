from __future__ import annotations

import httpx
import pytest
from fastapi.encoders import jsonable_encoder

from consts.const import NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS
from consts.task_recovery import NORTHBOUND_SERVICE_NAME
from nexent.core.concurrency import ManagerState, get_default_thread_manager
from services import startup_recovery_service
from services.runtime_state_service import runtime_state_service
from services.thread_lifecycle_service import northbound_thread_manager


@pytest.mark.asyncio
@pytest.mark.case_id('REL-AUTO-BCE0AAF43667C67B')
@pytest.mark.stage('D5')
async def test_northbound_lifespan_start_snapshot_and_graceful_shutdown(monkeypatch):
    import apps.northbound_base_app as northbound_base_app

    assert northbound_thread_manager.state is ManagerState.CREATED

    recover_calls = []
    cleanup_calls = []

    def fake_recover_northbound_tasks():
        recover_calls.append(1)
        return {'a2a_tasks': 0}

    async def fake_schedule_interrupted_upload_cleanup(service_name):
        cleanup_calls.append(service_name)

    monkeypatch.setattr(
        startup_recovery_service,
        'recover_northbound_tasks',
        fake_recover_northbound_tasks,
    )
    monkeypatch.setattr(
        startup_recovery_service,
        'schedule_interrupted_upload_cleanup',
        fake_schedule_interrupted_upload_cleanup,
    )

    real_shutdown = northbound_thread_manager.shutdown
    shutdown_kwargs = []

    async def spy_shutdown(**kwargs):
        shutdown_kwargs.append(kwargs)
        return await real_shutdown(**kwargs)

    monkeypatch.setattr(northbound_thread_manager, 'shutdown', spy_shutdown)

    async with northbound_base_app.northbound_lifespan(None):
        assert northbound_thread_manager.state is ManagerState.RUNNING
        assert get_default_thread_manager() is northbound_thread_manager
        assert runtime_state_service._thread_manager is northbound_thread_manager

        assert recover_calls == [1]
        assert cleanup_calls == [NORTHBOUND_SERVICE_NAME]

        expected_snapshot = northbound_thread_manager.snapshot()
        transport = httpx.ASGITransport(app=northbound_base_app.northbound_app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/internal/thread-capacity')

        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_snapshot)

    assert northbound_thread_manager.state is not ManagerState.RUNNING
    assert get_default_thread_manager() is not northbound_thread_manager
    assert len(shutdown_kwargs) == 1
    assert shutdown_kwargs[0].get('timeout') == NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS
