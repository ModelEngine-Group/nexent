# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise config lifespan reliability without external service side effects."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import logging
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from nexent.core.concurrency import LanePolicy, ManagerState, ThreadManager
from nexent.core.concurrency.context import (
    clear_default_thread_manager,
    get_default_thread_manager,
    set_default_thread_manager,
)

import management.api.application as config_app
import management.recovery as startup_recovery
import management.services.evaluation.maintenance as evaluation_maintenance
import management.services.memory.dreaming.scheduler as memory_scheduler
from shared.case_evidence import write_case_evidence


CASE_ID = 'REL-AUTO-AF6CA560E762D682'
SERVICE = 'config-lifespan-reliability-fixture'
SENSITIVE_MARKER = 'synthetic-aidp-credential-not-a-real-key'
pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage('D5'), pytest.mark.rel]


def _owned_threads():
    return [thread.name for thread in threading.enumerate()
            if thread.name.startswith(f'nexent-{SERVICE}-')]


async def _settle_owned_threads(timeout):
    """Allow executor workers to consume their shutdown sentinel, within budget."""
    deadline = asyncio.get_running_loop().time() + timeout
    while _owned_threads() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)


def _observe(context):
    snapshot = context.manager.snapshot()
    return {
        'calls': list(context.calls),
        'manager_state': snapshot.state.value,
        'active_count': snapshot.active_count,
        'stuck_count': snapshot.stuck_count,
        'default_is_owned': get_default_thread_manager() is context.manager,
        'owned_threads': _owned_threads(),
        'run_calls': context.run_calls,
        'shutdown_timeouts': list(context.shutdown_timeouts),
        'observations': context.observations,
    }


@pytest_asyncio.fixture
async def lifecycle(monkeypatch, request, caplog):
    """Keep lifecycle/health/manager real and control only side-effect boundaries."""
    previous = get_default_thread_manager()
    manager = ThreadManager(service_name=SERVICE, lane_policies={
        'control-io': LanePolicy(name='control-io', max_workers=1, max_queue_size=2,
                                 shutdown_grace_seconds=2),
    })
    context = SimpleNamespace(manager=manager, calls=[], run_calls=[], shutdown_timeouts=[],
                              observations={}, startup_fault=None)
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config_app, 'config_thread_manager', manager)
    monkeypatch.setattr(config_app.app.state, 'thread_manager', manager)
    monkeypatch.setattr(config_app, 'ENABLE_AGENT_WORKBENCH', False)
    monkeypatch.setattr(config_app, 'ENABLE_AIDP_KNOWLEDGE', False)
    monkeypatch.setattr(config_app, 'AIDP_SERVER_URL', '')
    monkeypatch.setattr(config_app, 'AIDP_API_KEY', '')
    original_start, original_run, original_shutdown = manager.start, manager.run, manager.shutdown
    original_validate = config_app.validate_external_service_configuration

    def start():
        context.calls.append('manager_start')
        return original_start()

    def register(value):
        assert value is manager
        context.calls.append('set_default')
        set_default_thread_manager(value)

    def unregister(value):
        assert value is manager
        context.calls.append('clear_default')
        clear_default_thread_manager(value)

    async def run(lane, spec, function, *args, **kwargs):
        context.run_calls.append((lane, spec.task_name, spec.owner))
        return await original_run(lane, spec, function, *args, **kwargs)

    async def shutdown(timeout=None):
        context.calls.append('manager_shutdown')
        context.shutdown_timeouts.append(timeout)
        return await original_shutdown(timeout=timeout)

    def recover():
        context.calls.append('recover_config_tasks')
        if context.startup_fault == 'recovery':
            raise RuntimeError('controlled recovery failure')
        return {}

    async def upload_cleanup(service_name):
        assert service_name == config_app.CONFIG_SERVICE_NAME
        context.calls.append('upload_cleanup')
        if context.startup_fault == 'upload':
            raise RuntimeError('controlled upload failure')

    def evaluation_start(value):
        assert value is manager
        context.calls.append('eval_start')

    async def validate():
        context.calls.append('validate_external')
        return await original_validate()

    async def dreaming_start():
        context.calls.append('dreaming_start')

    async def dreaming_stop():
        context.calls.append('dreaming_stop')

    monkeypatch.setattr(manager, 'start', start)
    monkeypatch.setattr(manager, 'run', run)
    monkeypatch.setattr(manager, 'shutdown', shutdown)
    monkeypatch.setattr(config_app, 'set_default_thread_manager', register)
    monkeypatch.setattr(config_app, 'clear_default_thread_manager', unregister)
    monkeypatch.setattr(config_app, 'validate_external_service_configuration', validate)
    monkeypatch.setattr(startup_recovery, 'recover_config_tasks', recover)
    monkeypatch.setattr(startup_recovery, 'schedule_interrupted_upload_cleanup', upload_cleanup)
    monkeypatch.setattr(startup_recovery, 'schedule_workbench_main_backfill',
                        lambda: context.calls.append('workbench_backfill'))
    monkeypatch.setattr(evaluation_maintenance, 'start', evaluation_start)
    monkeypatch.setattr(evaluation_maintenance, 'stop', lambda: context.calls.append('eval_stop'))
    monkeypatch.setattr(memory_scheduler.dreaming_scheduler, 'start', dreaming_start)
    monkeypatch.setattr(memory_scheduler.dreaming_scheduler, 'stop', dreaming_stop)
    try:
        yield context
    finally:
        # Observe product ownership before the test's separate safety cleanup.
        product = _observe(context)
        try:
            await original_shutdown(timeout=2)
            await _settle_owned_threads(2)
        finally:
            clear_default_thread_manager(manager)
            if previous is not None:
                set_default_thread_manager(previous)
        cleanup = _observe(context)
        messages = [record.getMessage() for phase in ('setup', 'call')
                    for record in caplog.get_records(phase)]
        evidence_name = re.sub(r'[^A-Za-z0-9_-]', '-', f'{CASE_ID}-{request.node.name}')
        write_case_evidence(evidence_name, {
            'product_before_test_cleanup': product,
            'test_safety_cleanup': cleanup,
            'sensitive_marker_logged': any(SENSITIVE_MARKER in message for message in messages),
        }, secrets=(SENSITIVE_MARKER,))
        assert not _owned_threads(), 'Test safety cleanup left owned worker threads'
        assert get_default_thread_manager() is previous, 'Test polluted the process default manager'
        assert all(SENSITIVE_MARKER not in message for message in messages), 'Credential appeared in logs'


async def _ready(context):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config_app.app),
                                 base_url='http://test') as client:
        response = await client.get('/health/ready')
    context.observations.setdefault('readiness', []).append({
        'http_status': response.status_code, 'body': response.json(),
    })
    return response


async def _assert_released(context):
    observed = _observe(context)
    context.observations['release_assertion'] = {
        'state': observed['manager_state'], 'default_is_owned': observed['default_is_owned'],
        'active_count': observed['active_count'], 'owned_threads': observed['owned_threads'],
    }
    assert observed['manager_state'] == 'closed', f'Lifecycle did not close manager: {observed}'
    assert observed['active_count'] == 0 and observed['stuck_count'] == 0
    assert not observed['default_is_owned'], 'Lifecycle left the default manager registered'
    await _settle_owned_threads(min(2, config_app.RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS))
    assert not _owned_threads(), 'Lifecycle left owned worker threads alive beyond its grace budget'


@pytest.mark.asyncio
@pytest.mark.parametrize('workbench_enabled', [False, True], ids=['workbench-off', 'workbench-on'])
async def test_startup_order_and_conditional_backfill(lifecycle, monkeypatch, workbench_enabled):
    monkeypatch.setattr(config_app, 'ENABLE_AGENT_WORKBENCH', workbench_enabled)
    async with config_app.config_lifespan(config_app.app):
        expected = ['manager_start', 'set_default', 'recover_config_tasks', 'eval_start', 'upload_cleanup']
        if workbench_enabled:
            expected.append('workbench_backfill')
        assert lifecycle.calls == [*expected, 'validate_external', 'dreaming_start']
        assert lifecycle.run_calls == [('control-io', 'recover-config-tasks', 'management.api.application')]
        assert lifecycle.manager.state is ManagerState.RUNNING
        assert get_default_thread_manager() is lifecycle.manager
    await _assert_released(lifecycle)


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled,url,key', [
    (False, '', ''), (True, 'http://aidp-fixture.invalid', SENSITIVE_MARKER),
    (True, '', SENSITIVE_MARKER), (True, 'http://aidp-fixture.invalid', ''),
], ids=['disabled', 'configured', 'missing-url', 'missing-key'])
async def test_external_configuration_validation(lifecycle, monkeypatch, enabled, url, key):
    monkeypatch.setattr(config_app, 'ENABLE_AIDP_KNOWLEDGE', enabled)
    monkeypatch.setattr(config_app, 'AIDP_SERVER_URL', url)
    monkeypatch.setattr(config_app, 'AIDP_API_KEY', key)
    if enabled and (not url or not key):
        with pytest.raises(RuntimeError, match='AIDP_SERVER_URL and AIDP_API_KEY'):
            async with config_app.config_lifespan(config_app.app):
                pytest.fail('Invalid external configuration entered service')
        assert 'dreaming_start' not in lifecycle.calls
    else:
        async with config_app.config_lifespan(config_app.app):
            assert lifecycle.calls[-1] == 'dreaming_start'


@pytest.mark.asyncio
async def test_readiness_created_running_stuck_and_closed(lifecycle, monkeypatch):
    before = await _ready(lifecycle)
    assert before.status_code == 503 and before.json()['manager_state'] == 'created'
    async with config_app.config_lifespan(config_app.app):
        running = await _ready(lifecycle)
        assert running.status_code == 200
        assert running.json() == {'status': 'ready', 'manager_state': 'running', 'stuck_count': 0}
        with monkeypatch.context() as fault:
            snapshot = lifecycle.manager.snapshot()
            fault.setattr(lifecycle.manager, 'snapshot', lambda: replace(snapshot, stuck_count=1))
            stuck = await _ready(lifecycle)
            assert stuck.status_code == 503
            assert stuck.json() == {'status': 'not_ready', 'manager_state': 'running', 'stuck_count': 1}
    closed = await _ready(lifecycle)
    assert closed.status_code == 503 and closed.json()['manager_state'] == 'closed'
    await _assert_released(lifecycle)


@pytest.mark.parametrize('fault', ['recovery', 'upload', 'configuration'])
def test_startup_failure_recovers_after_process_restart(tmp_path, fault):
    """Accept an explicit process reset only after a real replacement is ready."""
    probe = Path(__file__).with_name('startup_probe.py')
    processes, logs, event_paths = [], [], {}
    observations = {'fault': fault, 'automatic_recovery_required': False}

    def read_events(path):
        if not path.exists():
            return []
        # A child may still be finishing its latest append.
        lines = path.read_text(encoding='utf-8').splitlines()
        return [json.loads(line) for line in lines if line.endswith('}')]

    def launch(label, *, healthy=False):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        event_path = tmp_path / f'{label}.jsonl'
        event_paths[label] = event_path
        log = tempfile.TemporaryFile(mode='w+t', encoding='utf-8')
        logs.append((label, log))
        command = [sys.executable, str(probe), '--fault', fault,
                   '--events', str(event_path), '--port', str(port)]
        if healthy:
            command.append('--healthy')
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        processes.append(process)
        return process, event_path, port

    def finish(process):
        forced = process.poll() is None
        if forced:
            process.kill()
        process.wait(timeout=10)
        assert process.poll() is not None, 'Owned process survived forced termination'
        return {'pid': process.pid, 'forced_termination': forced, 'exit_code': process.returncode}

    def health(port):
        try:
            with httpx.Client(timeout=1, trust_env=False) as client:
                response = client.get(f'http://127.0.0.1:{port}/health/ready')
            return {'status': response.status_code, 'body': response.json()}
        except httpx.HTTPError:
            return {'status': None, 'body': None}

    message = {'recovery': 'controlled recovery failure', 'upload': 'controlled upload failure',
               'configuration': 'AIDP_SERVER_URL and AIDP_API_KEY'}[fault]
    try:
        failed, failed_events, failed_port = launch('failed')
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            captured = read_events(failed_events)
            if any(item['event'] == 'startup_exception' for item in captured):
                break
            assert failed.poll() is None, f'Child exited without the declared startup fault: {captured}'
            time.sleep(0.1)
        else:
            pytest.fail('Declared startup fault was not observed within 45 seconds')
        error = next(item for item in captured if item['event'] == 'startup_exception')
        assert error['error_type'] == 'RuntimeError' and message in error['message']
        assert not any(item['event'] in ('startup_completed', 'dreaming_start') for item in captured)
        if fault == 'recovery':
            assert not any(item['event'] == 'upload_cleanup' for item in captured)
        observations['failed_health'] = health(failed_port)
        assert observations['failed_health']['status'] != 200, 'Failed startup served healthy traffic'
        observations['failed_process'] = finish(failed)
        observations['failed_events'] = read_events(failed_events)

        recovered, recovered_events, recovered_port = launch('recovered', healthy=True)
        assert recovered.pid != failed.pid, 'Recovery reused the failed process'
        started = time.monotonic()
        while time.monotonic() - started < 45:
            assert recovered.poll() is None, 'Replacement process exited before readiness'
            captured = read_events(recovered_events)
            if any(item['event'] == 'startup_completed' for item in captured):
                status = health(recovered_port)
                if status == {'status': 200, 'body': {'status': 'ready', 'manager_state': 'running',
                                                       'stuck_count': 0}}:
                    break
            time.sleep(0.1)
        else:
            pytest.fail('Replacement process did not become healthy within 45 seconds')
        time.sleep(0.2)
        assert recovered.poll() is None and health(recovered_port) == status
        fresh = next(item for item in captured if item['event'] == 'probe_started')
        assert fresh['fresh_manager_state'] == 'created' and fresh['fresh_default_is_none']
        observations['recovered'] = {'pid': recovered.pid, 'health': status,
                                     'elapsed_seconds': round(time.monotonic() - started, 3),
                                     'events': captured}
    finally:
        try:
            cleanup, cleanup_errors = [], []
            for process in processes:
                try:
                    cleanup.append(finish(process))
                except Exception as error:
                    cleanup_errors.append(f'{process.pid}: {type(error).__name__}: {error}')
            observations['final_process_cleanup'] = cleanup
            assert not cleanup_errors, f'Owned-process cleanup failed: {cleanup_errors}'
        finally:
            observations['all_events'] = {label: read_events(path) for label, path in event_paths.items()}
            for label, log in logs:
                log.seek(0)
                observations[f'{label}_log'] = log.read()
                log.close()
            sensitive_logged = any(SENSITIVE_MARKER in observations[f'{label}_log'] for label, _ in logs)
            observations['sensitive_marker_logged'] = sensitive_logged
            write_case_evidence(f'{CASE_ID}-process-restart-{fault}', observations,
                                secrets=(SENSITIVE_MARKER,))
            assert not sensitive_logged, 'Credential appeared in subprocess logs'


@pytest.mark.asyncio
@pytest.mark.parametrize('body_raises', [False, True], ids=['normal', 'body-error'])
async def test_shutdown_order_and_body_error_propagation(lifecycle, body_raises):
    async def exercise():
        async with config_app.config_lifespan(config_app.app):
            if body_raises:
                raise RuntimeError('controlled request-body failure')

    if body_raises:
        with pytest.raises(RuntimeError, match='controlled request-body failure'):
            await exercise()
    else:
        await exercise()
    assert lifecycle.calls[-4:] == ['dreaming_stop', 'eval_stop', 'manager_shutdown', 'clear_default']
    assert all(lifecycle.calls.count(name) == 1 for name in lifecycle.calls[-4:])
    assert lifecycle.shutdown_timeouts == [config_app.RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS]
    await _assert_released(lifecycle)


@pytest.mark.asyncio
async def test_shutdown_error_still_clears_default(lifecycle, monkeypatch):
    original_shutdown = lifecycle.manager.shutdown

    async def failing_shutdown(timeout=None):
        await original_shutdown(timeout=timeout)
        raise RuntimeError('controlled manager shutdown failure')

    monkeypatch.setattr(lifecycle.manager, 'shutdown', failing_shutdown)
    with pytest.raises(RuntimeError, match='controlled manager shutdown failure'):
        async with config_app.config_lifespan(config_app.app):
            pass
    assert lifecycle.calls[-2:] == ['manager_shutdown', 'clear_default']
    await _assert_released(lifecycle)
