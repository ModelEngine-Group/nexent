from __future__ import annotations

import logging
import types

import httpx
import pytest
from nexent.core.concurrency import ManagerState

import apps.config_app as config_app
import services.evaluation_maintenance as evaluation_maintenance
import services.memory_dreaming_scheduler as memory_dreaming_scheduler
import services.startup_recovery_service as startup_recovery


class _Snapshot:
    def __init__(self, state, stuck_count=0):
        self.state = state
        self.stuck_count = stuck_count


class _FakeManager:
    def __init__(self, calls):
        self._calls = calls
        self.state = ManagerState.CREATED
        self._snapshot_state = ManagerState.CREATED
        self.stuck_count = 0
        self.started = False
        self.run_calls = []
        self.shutdown_calls = []

    def start(self):
        self.started = True
        self.state = types.SimpleNamespace(value='running')
        self._snapshot_state = self.state

    async def run(self, lane, spec, fn, *args, **kwargs):
        self.run_calls.append((lane, spec.task_name, spec.owner))
        return fn(*args, **kwargs)

    async def shutdown(self, timeout=None):
        self.shutdown_calls.append(timeout)
        self._calls.append('manager_shutdown')
        self.state = types.SimpleNamespace(value='stopped')
        self._snapshot_state = self.state

    def snapshot(self):
        return _Snapshot(self._snapshot_state, self.stuck_count)


@pytest.mark.asyncio
@pytest.mark.case_id('REL-AUTO-AF6CA560E762D682')
@pytest.mark.stage('D5')
async def test_config_lifespan_recovery_order_failure_tolerance_and_shutdown(monkeypatch, caplog):
    calls: list[str] = []
    captured: dict = {}

    def set_default(m):
        captured['set_default_arg'] = m
        calls.append('set_default')

    def clear_default(m):
        captured['clear_default_arg'] = m
        calls.append('clear_default')

    def sync_prompt_ok():
        calls.append('prompt_sync')

    monkeypatch.setattr(config_app, 'set_default_thread_manager', set_default)
    monkeypatch.setattr(config_app, 'clear_default_thread_manager', clear_default)
    monkeypatch.setattr(config_app, 'sync_system_default_prompt_template', sync_prompt_ok)

    def recover_config_tasks():
        calls.append('recover_config_tasks')
        return {}

    async def schedule_cleanup(service_name):
        captured['upload_service_name'] = service_name
        calls.append('upload_cleanup')

    monkeypatch.setattr(startup_recovery, 'recover_config_tasks', recover_config_tasks)
    monkeypatch.setattr(startup_recovery, 'schedule_interrupted_upload_cleanup', schedule_cleanup)

    def eval_start(thread_manager):
        captured['eval_start_arg'] = thread_manager
        calls.append('eval_start')

    def eval_stop():
        calls.append('eval_stop')

    monkeypatch.setattr(evaluation_maintenance, 'start', eval_start)
    monkeypatch.setattr(evaluation_maintenance, 'stop', eval_stop)

    async def dreaming_start():
        calls.append('dreaming_start')

    async def dreaming_stop():
        calls.append('dreaming_stop')

    monkeypatch.setattr(memory_dreaming_scheduler.dreaming_scheduler, 'start', dreaming_start)
    monkeypatch.setattr(memory_dreaming_scheduler.dreaming_scheduler, 'stop', dreaming_stop)

    def install_manager():
        manager = _FakeManager(calls)
        monkeypatch.setattr(config_app, 'config_thread_manager', manager)
        monkeypatch.setattr(config_app.app.state, 'thread_manager', manager)
        return manager

    transport = httpx.ASGITransport(app=config_app.app)

    manager = install_manager()
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        async with config_app.config_lifespan(config_app.app):
            assert manager.started is True
            assert manager.state is not ManagerState.CREATED
            assert getattr(manager.state, 'value', None) == 'running'
            assert captured['set_default_arg'] is manager
            assert manager.run_calls == [('control-io', 'recover-config-tasks', 'apps.config_app')]
            assert calls.index('recover_config_tasks') < calls.index('eval_start') < calls.index('upload_cleanup')
            assert captured['eval_start_arg'] is manager
            assert captured['upload_service_name'] == config_app.CONFIG_SERVICE_NAME

            ready = await client.get('/health/ready')
            assert ready.status_code == 200
            assert ready.json()['manager_state'] == 'running'
            assert ready.json()['stuck_count'] == 0

        assert calls.index('dreaming_stop') < calls.index('eval_stop') < calls.index('manager_shutdown') < calls.index('clear_default')
        assert manager.shutdown_calls == [config_app.RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS]
        assert captured['clear_default_arg'] is manager

        not_ready = await client.get('/health/ready')
        assert not_ready.status_code == 503
        assert not_ready.json()['manager_state'] != 'running'

    calls.clear()
    captured.clear()
    manager = install_manager()

    def recover_raise():
        calls.append('recover_config_tasks')
        raise RuntimeError('recover_config_tasks failed')

    monkeypatch.setattr(startup_recovery, 'recover_config_tasks', recover_raise)

    yielded = False
    with pytest.raises(RuntimeError):
        async with config_app.config_lifespan(config_app.app):
            yielded = True
    assert yielded is False
    assert 'eval_start' not in calls
    assert 'upload_cleanup' not in calls
    assert 'dreaming_start' not in calls

    monkeypatch.setattr(startup_recovery, 'recover_config_tasks', recover_config_tasks)

    async def cleanup_raise(service_name):
        calls.append('upload_cleanup')
        raise RuntimeError('upload cleanup failed')

    monkeypatch.setattr(startup_recovery, 'schedule_interrupted_upload_cleanup', cleanup_raise)

    calls.clear()
    captured.clear()
    manager = install_manager()

    yielded = False
    with pytest.raises(RuntimeError):
        async with config_app.config_lifespan(config_app.app):
            yielded = True
    assert yielded is False
    assert 'recover_config_tasks' in calls
    assert 'eval_start' in calls
    assert 'dreaming_start' not in calls

    monkeypatch.setattr(startup_recovery, 'schedule_interrupted_upload_cleanup', schedule_cleanup)

    def sync_prompt_raise():
        calls.append('prompt_sync')
        raise RuntimeError('prompt template sync failed')

    monkeypatch.setattr(config_app, 'sync_system_default_prompt_template', sync_prompt_raise)

    calls.clear()
    captured.clear()
    manager = install_manager()

    yielded = False
    with caplog.at_level(logging.ERROR):
        async with config_app.config_lifespan(config_app.app):
            yielded = True
            assert 'dreaming_start' in calls
    assert yielded is True
    assert any('Failed to sync system default prompt template' in record.message for record in caplog.records)
