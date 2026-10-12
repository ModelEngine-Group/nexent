from __future__ import annotations

import asyncio
import logging
import threading

import pytest

import sdk.nexent.core.concurrency.helpers as helpers
from sdk.nexent.core.concurrency.context import (
    clear_default_thread_manager,
    get_current_thread_manager,
    set_default_thread_manager,
)
from sdk.nexent.core.concurrency.helpers import (
    get_fallback_thread_manager,
    run_blocking,
    shutdown_fallback_thread_manager,
)
from sdk.nexent.core.concurrency.manager import ThreadManager
from sdk.nexent.core.concurrency.models import (
    DrainResult,
    LanePolicy,
    ManagedTaskSpec,
    ManagerState,
)


_EXPECTED_LANES = {
    'agent-run': (4, 16),
    'model-tool-io': (4, 16),
    'control-io': (16, 8),
    'evaluation': (2, 8),
    'background-service': (12, 4),
    'mcp-session': (4, 0),
    'sandbox': (200, 4),
}

_SECRET_MARKERS = (
    'bearer ',
    'sk-',
    'api_key',
    'apikey',
    'access_key',
    'password',
    'secret',
    'access_token',
    'refresh_token',
)


def _leaks_credentials(message):
    lowered = message.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


class RecordingTelemetry:
    def __init__(self):
        self.records = []

    def record_snapshot(self, service_name, event, execution, counts, *, dedicated, **fields):
        self.records.append((execution.lane, execution.spec.task_name, execution.spec.owner))


def _make_probe(marker, sink):
    def fn():
        sink['thread'] = threading.current_thread().name
        return marker

    return fn


@pytest.mark.case_id('UT-SDK-AUTO-6951D0D43C14D4A4')
@pytest.mark.stage('D1')
@pytest.mark.asyncio
async def test_fallback_thread_manager_journey(caplog):
    caplog.set_level(logging.DEBUG, logger='thread_manager')

    custom = None
    try:
        m1 = get_fallback_thread_manager()
        assert isinstance(m1, ThreadManager)
        assert helpers._fallback_thread_manager is m1

        snap = m1.snapshot()
        assert snap.service_name == 'sdk-fallback'
        assert snap.state == ManagerState.RUNNING

        policy_map = dict(m1._policies)
        assert len(policy_map) == 7
        assert set(policy_map) == set(_EXPECTED_LANES)
        for name, (workers, queue_size) in _EXPECTED_LANES.items():
            policy = policy_map[name]
            assert policy.max_workers == workers
            assert policy.max_queue_size == queue_size
            assert policy.queue_timeout_seconds == 0
            assert policy.cancel_grace_seconds == 5
            assert policy.shutdown_grace_seconds == 15

        assert {lane.name for lane in snap.lanes} == set(_EXPECTED_LANES)

        m2 = get_fallback_thread_manager()
        assert m2 is m1

        fallback_sink = {}
        fallback_result = await run_blocking('probe', _make_probe('MARKER_FALLBACK', fallback_sink))
        assert fallback_result == 'MARKER_FALLBACK'
        assert fallback_sink['thread'].startswith('nexent-sdk-fallback-model-tool-io')

        recorder = RecordingTelemetry()
        custom = ThreadManager(
            'custom-default',
            {'model-tool-io': LanePolicy(name='model-tool-io', max_workers=2, max_queue_size=4)},
            telemetry=recorder,
        )
        custom.start()
        set_default_thread_manager(custom)

        default_sink = {}
        default_result = await run_blocking('probe-default', _make_probe('MARKER_DEFAULT', default_sink))
        assert default_result == 'MARKER_DEFAULT'
        assert default_sink['thread'].startswith('nexent-custom-default-model-tool-io')
        assert ('model-tool-io', 'probe-default', 'sdk') in recorder.records

        outer = {}

        def inner_fn():
            outer['inner_thread'] = threading.current_thread().name
            return 'MARKER_CURRENT'

        def outer_fn():
            outer['current_manager'] = get_current_thread_manager()
            outer['inner_result'] = asyncio.run(run_blocking('probe', inner_fn))

        await m1.run(
            'model-tool-io',
            ManagedTaskSpec(task_name='outer', owner='sdk'),
            outer_fn,
        )
        assert outer['current_manager'] is m1
        assert outer['inner_result'] == 'MARKER_CURRENT'
        assert outer['inner_thread'].startswith('nexent-sdk-fallback-model-tool-io')

        first_shutdown = await shutdown_fallback_thread_manager(timeout=15.0)
        assert isinstance(first_shutdown, DrainResult)
        assert helpers._fallback_thread_manager is None

        second_shutdown = await shutdown_fallback_thread_manager()
        assert second_shutdown is None

        m3 = get_fallback_thread_manager()
        snap3 = m3.snapshot()
        assert m3 is not m1
        assert snap3.service_name == 'sdk-fallback'
        assert snap3.state == ManagerState.RUNNING
        assert {lane.name for lane in snap3.lanes} == set(_EXPECTED_LANES)
    finally:
        if custom is not None:
            clear_default_thread_manager(custom)
            try:
                await custom.shutdown(timeout=15.0)
            except Exception:
                pass
        try:
            await shutdown_fallback_thread_manager(timeout=15.0)
        except Exception:
            pass

    for record in caplog.records:
        if record.name == 'thread_manager':
            assert not _leaks_credentials(record.getMessage())
