'''D5 reliability special case for the config service lifespan.

Covers F-156: config_app switched from on_event to lifespan. Verifies that a
cold start recovers interrupted config tasks and schedules interrupted-upload
cleanup, that /internal/thread-capacity exposes the live thread-manager
snapshot, and that shutdown stops the dreaming scheduler and eval maintenance
before shutting the thread manager down with the configured grace timeout and
clearing the default thread manager.
'''

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass

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
    from consts import const
    from consts.task_recovery import CONFIG_SERVICE_NAME

    import services.evaluation_maintenance as evaluation_maintenance
    import services.startup_recovery_service as startup_recovery

    from fastapi.testclient import TestClient

    from apps import config_app
    from nexent.core.concurrency import ManagerState

    # --- Static anchors ------------------------------------------------------
    grace = const.RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
    assert isinstance(grace, (int, float)) and grace > 0
    assert CONFIG_SERVICE_NAME == 'nexent-config'

    manager = config_app.config_thread_manager

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

    original_start = evaluation_maintenance.start

    def spy_start(mgr):
        events.append('start_eval_maintenance')
        calls['start_eval_maintenance'].append(mgr)
        return original_start(mgr)

    original_stop = evaluation_maintenance.stop

    def spy_stop():
        events.append('stop_eval_maintenance')
        calls['stop_eval_maintenance'].append(True)
        return original_stop()

    monkeypatch.setattr(evaluation_maintenance, 'start', spy_start)
    monkeypatch.setattr(evaluation_maintenance, 'stop', spy_stop)

    original_schedule = startup_recovery.schedule_interrupted_upload_cleanup

    async def spy_schedule(*args, **kwargs):
        events.append('schedule_cleanup')
        calls['schedule_cleanup'].append(args[0] if args else kwargs.get('service_name'))
        return await original_schedule(*args, **kwargs)

    monkeypatch.setattr(startup_recovery, 'schedule_interrupted_upload_cleanup', spy_schedule)

    original_stop_dreaming = config_app.stop_dreaming_scheduler

    async def spy_stop_dreaming():
        events.append('stop_dreaming')
        calls['stop_dreaming'].append(True)
        return await original_stop_dreaming()

    monkeypatch.setattr(config_app, 'stop_dreaming_scheduler', spy_stop_dreaming)

    original_set_default = config_app.set_default_thread_manager

    def spy_set_default(mgr):
        events.append('set_default')
        calls['set_default'].append(mgr)
        return original_set_default(mgr)

    original_clear_default = config_app.clear_default_thread_manager

    def spy_clear_default(mgr):
        events.append('clear_default')
        calls['clear_default'].append(mgr)
        return original_clear_default(mgr)

    monkeypatch.setattr(config_app, 'set_default_thread_manager', spy_set_default)
    monkeypatch.setattr(config_app, 'clear_default_thread_manager', spy_clear_default)

    caplog.set_level(logging.DEBUG)

    with TestClient(config_app.app) as client:
        # Startup path has run (config_app.py:126-131).
        state_running = manager.state
        assert state_running is not ManagerState.CREATED

        # Capacity probe returns the live snapshot (config_app.py:158-161).
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

    # --- Startup dispatch (config_app.py:79-95) -----------------------------
    recover_runs = [c for c in calls['run'] if c[1] == 'recover-config-tasks']
    assert len(recover_runs) == 1
    pool_name, task_name, owner = recover_runs[0]
    assert pool_name == 'control-io'
    assert owner == 'apps.config_app'

    assert 'nexent-config' in calls['schedule_cleanup']
    assert calls['start_eval_maintenance'] == [manager]
    assert calls['set_default'] == [manager]

    # --- Shutdown ordering (config_app.py:132-146) --------------------------
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
