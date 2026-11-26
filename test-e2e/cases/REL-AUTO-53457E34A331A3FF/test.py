# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
'''D5 reliability special case for the config service lifespan.

Covers F-156: config_app switched from on_event to lifespan. Verifies that a
cold start recovers interrupted config tasks and schedules interrupted-upload
cleanup, that /internal/thread-capacity exposes the live thread-manager
snapshot, and that shutdown stops the dreaming scheduler and eval maintenance
before shutting the thread manager down with the configured grace timeout and
clearing the default thread manager.
'''

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, is_dataclass
from unittest.mock import AsyncMock, Mock

import pytest

from shared.cases import special_case_params

_SENSITIVE_KEY_PARTS = (
    'password',
    'passwd',
    'secret',
    'token',
    'api_key',
    'apikey',
    'access_key',
    'accesskey',
    'credential',
    'private_key',
)


@pytest.mark.parametrize('case', special_case_params(['REL-AUTO-53457E34A331A3FF']))
def test_config_lifespan_startup_recovery_shutdown_capacity(case, monkeypatch, caplog):
    import contracts.constants.environment as const
    from contracts.constants.constants import CONFIG_SERVICE_NAME

    from management.services.evaluation import maintenance as evaluation_maintenance
    from management import recovery as startup_recovery

    from fastapi.testclient import TestClient

    from management.api import application as config_app
    from management.api import northbound_application as northbound_app
    from management.services.agent import prepared_turn
    from management.services.automation import scheduler
    from management.services.conversation import creator_runtime
    from management.services.memory import prepared_completion
    from nexent.core.concurrency import ManagerState, ThreadManager

    # --- Static anchors ------------------------------------------------------
    grace = const.RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
    assert isinstance(grace, (int, float)) and grace > 0
    assert CONFIG_SERVICE_NAME == 'nexent-config'

    manager = ThreadManager("config", config_app.config_thread_manager._policies)
    monkeypatch.setattr(config_app, "config_thread_manager", manager)
    monkeypatch.setattr(northbound_app, "config_thread_manager", manager)
    monkeypatch.setattr(const, "GATEWAY_AUTH_ENABLED", False)
    monkeypatch.setattr(config_app.app, "middleware_stack", None)
    # Verify real lifespan dispatch and shutdown without touching deployed data.
    monkeypatch.setattr(config_app, "migrate_legacy_outlets", Mock(return_value={"migrated": 0, "failed": 0}))
    monkeypatch.setattr(config_app, "recover_config_tasks", Mock(return_value={}))
    monkeypatch.setattr(startup_recovery, "recover_northbound_tasks", Mock(return_value={}))
    monkeypatch.setattr(northbound_app, "start_system_configuration", AsyncMock())
    monkeypatch.setattr(northbound_app, "stop_system_configuration", AsyncMock())
    monkeypatch.setattr(config_app.dreaming_scheduler, "start", AsyncMock())
    monkeypatch.setattr(config_app.dreaming_scheduler, "stop", AsyncMock())
    monkeypatch.setattr(scheduler, "recover_automation_runs", Mock(return_value={}))
    monkeypatch.setattr(scheduler.agent_automation_scheduler, "start", AsyncMock())
    monkeypatch.setattr(scheduler.agent_automation_scheduler, "stop", AsyncMock())
    monkeypatch.setattr(prepared_turn, "_recover_pending_turns", AsyncMock())
    monkeypatch.setattr(prepared_completion, "recover_memory_jobs", AsyncMock())
    monkeypatch.setattr(creator_runtime, "shutdown_creator_streams", AsyncMock())
    monkeypatch.setattr(evaluation_maintenance, "_run_loop", lambda stop: stop.wait())

    events: list[str] = []
    calls: dict[str, list] = {
        'run': [],
        'shutdown': [],
        'start_eval_maintenance': [],
        'stop_eval_maintenance': [],
        'schedule_cleanup': [],
        'set_default': [],
        'clear_default': [],
        'stop_dreaming': [],
    }

    # --- Spies preserve real behavior while recording orchestration ---------
    original_run = manager.run

    async def spy_run(pool_name, spec, fn, *args, **kwargs):
        calls['run'].append(
            (pool_name, getattr(spec, 'task_name', None), getattr(spec, 'owner', None))
        )
        return await original_run(pool_name, spec, fn, *args, **kwargs)

    original_shutdown = manager.shutdown

    async def spy_shutdown(*args, **kwargs):
        timeout = kwargs.get('timeout', args[0] if args else None)
        events.append('shutdown')
        calls['shutdown'].append(timeout)
        return await original_shutdown(*args, **kwargs)

    monkeypatch.setattr(manager, 'run', spy_run)
    monkeypatch.setattr(manager, 'shutdown', spy_shutdown)

    original_start = config_app.start_eval_maintenance

    def spy_start(mgr):
        events.append('start_eval_maintenance')
        calls['start_eval_maintenance'].append(mgr)
        return original_start(mgr)

    original_stop = evaluation_maintenance.stop

    def spy_stop():
        events.append('stop_eval_maintenance')
        calls['stop_eval_maintenance'].append(True)
        return original_stop()

    monkeypatch.setattr(config_app, 'start_eval_maintenance', spy_start)
    monkeypatch.setattr(evaluation_maintenance, 'stop', spy_stop)

    cleanup_tasks: list[asyncio.Task] = []

    async def spy_schedule(*args, **kwargs):
        events.append('schedule_cleanup')
        calls['schedule_cleanup'].append(args[0] if args else kwargs.get('service_name'))
        task = asyncio.create_task(asyncio.sleep(3600))
        cleanup_tasks.append(task)
        return task

    monkeypatch.setattr(startup_recovery, 'schedule_interrupted_upload_cleanup', spy_schedule)

    original_stop_dreaming = config_app.stop_dreaming_scheduler

    async def spy_stop_dreaming():
        events.append('stop_dreaming')
        calls['stop_dreaming'].append(True)
        return await original_stop_dreaming()

    monkeypatch.setattr(config_app, 'stop_dreaming_scheduler', spy_stop_dreaming)

    original_set_default = northbound_app.set_default_thread_manager

    def spy_set_default(mgr):
        events.append('set_default')
        calls['set_default'].append(mgr)
        return original_set_default(mgr)

    original_clear_default = northbound_app.clear_default_thread_manager

    def spy_clear_default(mgr):
        events.append('clear_default')
        calls['clear_default'].append(mgr)
        return original_clear_default(mgr)

    monkeypatch.setattr(northbound_app, 'set_default_thread_manager', spy_set_default)
    monkeypatch.setattr(northbound_app, 'clear_default_thread_manager', spy_clear_default)

    caplog.set_level(logging.DEBUG)

    with TestClient(config_app.app) as client:
        # Startup has run through the real Management lifespan.
        state_running = manager.state
        assert state_running is not ManagerState.CREATED

        # Capacity probe returns the live snapshot.
        response = client.get('/internal/thread-capacity')
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, dict) and body
        direct = manager.snapshot()
        assert is_dataclass(direct)
        assert set(body.keys()) == set(asdict(direct).keys())

    state_stopped = manager.state
    assert state_stopped is not ManagerState.CREATED
    assert state_stopped is not state_running

    # --- Startup dispatch ---------------------------------------------------
    recover_runs = [c for c in calls['run'] if c[1] == 'recover-config-tasks']
    assert len(recover_runs) == 1
    pool_name, task_name, owner = recover_runs[0]
    assert pool_name == 'control-io'
    assert owner == 'management.api.application'

    assert 'nexent-config' in calls['schedule_cleanup']
    assert cleanup_tasks and all(task.cancelled() for task in cleanup_tasks)
    assert calls['start_eval_maintenance'] == [manager]
    assert calls['set_default'] == [manager]

    # --- Shutdown ordering --------------------------------------------------
    assert len(calls['shutdown']) == 1
    assert calls['shutdown'][0] == grace
    assert calls['clear_default'] == [manager]
    assert calls['stop_dreaming'] == [True]
    assert calls['stop_eval_maintenance'] == [True]

    def index(name):
        assert name in events, f'missing shutdown event {name!r} in {events}'
        return events.index(name)

    assert (
        index('stop_dreaming')
        < index('stop_eval_maintenance')
        < index('shutdown')
        < index('clear_default')
    )

    # --- Security: no plaintext credentials in captured logs ---------------
    from shared.config import load_secret_env

    log_text = caplog.text or ''
    leaked: list[str] = []
    for name, value in load_secret_env().items():
        value = str(value or '')
        if not value or len(value) < 6:
            continue
        normalized = name.lower().replace('-', '_')
        if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
            if value in log_text:
                leaked.append(name)
    assert not leaked, f'plaintext secrets leaked into logs: {leaked}'
