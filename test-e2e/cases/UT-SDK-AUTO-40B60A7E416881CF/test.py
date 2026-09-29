from __future__ import annotations

import asyncio
import threading

import pytest

from nexent.core.concurrency import telemetry as telemetry_module
from nexent.core.concurrency.errors import ThreadCapacityExceeded
from nexent.core.concurrency.manager import ThreadManager
from nexent.core.concurrency.models import (
    ExecutionState,
    LanePolicy,
    ManagedExecution,
    ManagedTaskSpec,
)
from nexent.core.concurrency.telemetry import OpenTelemetryThreadTelemetry

CASE_ID = 'UT-SDK-AUTO-40B60A7E416881CF'
SPAN_NAME = 'thread.manager.snapshot'
REQUIRED_ATTRIBUTES = (
    'thread.lane',
    'thread.execution.id',
    'thread.state',
    'thread.counts.managed_active',
    'thread.counts.queued',
    'thread.counts.running',
    'thread.counts.stuck',
    'thread.counts.python_active_threads',
)
FAILURE_RESULTS = {'failed', 'timed_out', 'stuck', 'rejected', 'submit_failed'}
SECRET_KEY_FRAGMENTS = (
    'password', 'secret', 'token', 'api_key', 'access_key',
    'credential', 'authorization', 'bearer',
)
SECRET_VALUE_PREFIXES = ('sk-', 'sk_')


class FakeSpanKind:
    INTERNAL = 'INTERNAL'


class FakeStatusCode:
    ERROR = 'ERROR'


class FakeStatus:
    def __init__(self, status_code, description=''):
        self.status_code = status_code
        self.description = description


class FakeSpan:
    def __init__(self, fail_set_status=False, fail_end=False):
        self.name = None
        self.kind = None
        self.attributes = {}
        self.status = None
        self.ended = False
        self._fail_set_status = fail_set_status
        self._fail_end = fail_end

    def set_status(self, status):
        if self._fail_set_status:
            raise RuntimeError('set_status exploded')
        self.status = status

    def end(self):
        if self._fail_end:
            raise RuntimeError('end exploded')
        self.ended = True


class FakeTracer:
    def __init__(self, fail_start=False, fail_set_status=False, fail_end=False):
        self.spans = []
        self._fail_start = fail_start
        self._fail_set_status = fail_set_status
        self._fail_end = fail_end

    def start_span(self, name, kind=None, attributes=None):
        if self._fail_start:
            raise RuntimeError('start_span exploded')
        span = FakeSpan(
            fail_set_status=self._fail_set_status,
            fail_end=self._fail_end,
        )
        span.name = name
        span.kind = kind
        span.attributes = dict(attributes or {})
        self.spans.append(span)
        return span


def _patch_otel_globals(monkeypatch):
    monkeypatch.setattr(telemetry_module, 'SpanKind', FakeSpanKind)
    monkeypatch.setattr(telemetry_module, 'Status', FakeStatus)
    monkeypatch.setattr(telemetry_module, 'StatusCode', FakeStatusCode)


def _build_telemetry(monkeypatch, tracer):
    _patch_otel_globals(monkeypatch)
    telemetry = OpenTelemetryThreadTelemetry()
    telemetry._tracer = tracer
    return telemetry


def _build_manager(monkeypatch, tracer, max_workers=1, max_queue_size=0):
    telemetry = _build_telemetry(monkeypatch, tracer)
    policy = LanePolicy(name='lane1', max_workers=max_workers, max_queue_size=max_queue_size)
    manager = ThreadManager('test-service', {'lane1': policy}, telemetry=telemetry)
    manager.start()
    return manager


def _close_manager(manager):
    try:
        asyncio.run(manager.shutdown(1.0))
    except Exception:
        pass


def _spec():
    return ManagedTaskSpec(
        task_name='job',
        owner='owner',
        run_id='run-1',
        attempt_id='attempt-1',
    )


def _assert_span_shape(span, event, state):
    assert span.name == SPAN_NAME
    assert span.kind == FakeSpanKind.INTERNAL
    for attr in REQUIRED_ATTRIBUTES:
        assert attr in span.attributes
    assert span.attributes['thread.event'] == event
    assert span.attributes['thread.state'] == state
    assert span.attributes['thread.lane'] == 'lane1'
    assert span.attributes['thread.service.name'] == 'test-service'
    assert span.attributes['thread.execution.id']
    assert span.attributes['thread.run.id'] == 'run-1'
    assert span.attributes['thread.attempt.id'] == 'attempt-1'
    return span


def _assert_no_secret_leak(attributes):
    for key, value in attributes.items():
        key_lower = str(key).lower()
        for fragment in SECRET_KEY_FRAGMENTS:
            assert fragment not in key_lower
        value_str = str(value).lower()
        assert not value_str.startswith(SECRET_VALUE_PREFIXES)


@pytest.mark.stage('D1')
@pytest.mark.case_id(CASE_ID)
def test_thread_telemetry_span_attributes_and_degradation(monkeypatch):
    tracer = FakeTracer()
    manager = _build_manager(monkeypatch, tracer)
    try:
        result = manager.run_sync('lane1', _spec(), lambda: 42, timeout=5.0)
    finally:
        _close_manager(manager)

    assert result == 42
    assert [s.attributes['thread.event'] for s in tracer.spans] == [
        'thread.queued',
        'thread.started',
        'thread.finished',
    ]
    queued, started, finished = tracer.spans
    _assert_span_shape(queued, 'thread.queued', 'queued')
    _assert_span_shape(started, 'thread.started', 'running')
    _assert_span_shape(finished, 'thread.finished', 'succeeded')
    assert finished.status is None
    for span in tracer.spans:
        _assert_no_secret_leak(span.attributes)

    failed_tracer = FakeTracer()
    failed_manager = _build_manager(monkeypatch, failed_tracer)

    def boom():
        raise ValueError('boom')

    try:
        with pytest.raises(ValueError):
            failed_manager.run_sync('lane1', _spec(), boom, timeout=5.0)
    finally:
        _close_manager(failed_manager)
    failed_finished = [s for s in failed_tracer.spans if s.attributes['thread.event'] == 'thread.finished']
    assert len(failed_finished) == 1
    assert failed_finished[0].status is not None
    assert failed_finished[0].status.status_code == FakeStatusCode.ERROR

    reject_tracer = FakeTracer()
    reject_manager = _build_manager(monkeypatch, reject_tracer, max_workers=1, max_queue_size=0)
    release = threading.Event()

    def blocking():
        release.wait(timeout=5.0)
        return 'done'

    try:
        first = reject_manager.submit('lane1', _spec(), blocking)
        with pytest.raises(ThreadCapacityExceeded):
            reject_manager.submit('lane1', _spec(), lambda: 'second')
        release.set()
        assert first.future.result(timeout=5.0) == 'done'
    finally:
        _close_manager(reject_manager)
    rejected_spans = [s for s in reject_tracer.spans if s.attributes['thread.event'] == 'thread.rejected']
    assert len(rejected_spans) == 1
    assert rejected_spans[0].status is not None
    assert rejected_spans[0].status.status_code == FakeStatusCode.ERROR

    unit_tracer = FakeTracer()
    unit_telemetry = _build_telemetry(monkeypatch, unit_tracer)
    unit_execution = ManagedExecution(
        lane='lane1',
        spec=ManagedTaskSpec(task_name='job', owner='owner'),
        state=ExecutionState.FAILED,
    )
    for result in sorted(FAILURE_RESULTS):
        unit_telemetry.record_snapshot(
            'test-service',
            'thread.finished',
            unit_execution,
            (0, 0, 0, 0),
            dedicated=False,
            result=result,
        )
        span = unit_tracer.spans[-1]
        assert span.status is not None
        assert span.status.status_code == FakeStatusCode.ERROR
    unit_telemetry.record_snapshot(
        'test-service',
        'thread.finished',
        unit_execution,
        (0, 0, 0, 0),
        dedicated=False,
        result='succeeded',
    )
    assert unit_tracer.spans[-1].status is None

    monkeypatch.setattr(telemetry_module, 'trace', None)
    monkeypatch.setattr(telemetry_module, 'OTEL_AVAILABLE', False)
    unavailable = OpenTelemetryThreadTelemetry()
    assert unavailable._tracer is None
    unavailable.record_snapshot(
        'test-service',
        'thread.queued',
        unit_execution,
        (0, 0, 0, 0),
        dedicated=False,
    )

    span_kind_none_telemetry = OpenTelemetryThreadTelemetry()
    span_kind_none_telemetry._tracer = FakeTracer()
    monkeypatch.setattr(telemetry_module, 'SpanKind', None)
    span_kind_none_telemetry.record_snapshot(
        'test-service',
        'thread.queued',
        unit_execution,
        (0, 0, 0, 0),
        dedicated=False,
    )
    assert span_kind_none_telemetry._tracer.spans == []

    _patch_otel_globals(monkeypatch)
    fail_start_tracer = FakeTracer(fail_start=True)
    fail_start_telemetry = _build_telemetry(monkeypatch, fail_start_tracer)
    fail_start_telemetry.record_snapshot(
        'test-service',
        'thread.queued',
        unit_execution,
        (0, 0, 0, 0),
        dedicated=False,
    )
    assert fail_start_tracer.spans == []

    fail_set_status_tracer = FakeTracer(fail_set_status=True)
    fail_set_status_telemetry = _build_telemetry(monkeypatch, fail_set_status_tracer)
    fail_set_status_telemetry.record_snapshot(
        'test-service',
        'thread.finished',
        unit_execution,
        (0, 0, 0, 0),
        dedicated=False,
        result='failed',
    )
    assert len(fail_set_status_tracer.spans) == 1
    assert fail_set_status_tracer.spans[0].ended is True

    fail_end_tracer = FakeTracer(fail_end=True)
    fail_end_telemetry = _build_telemetry(monkeypatch, fail_end_tracer)
    fail_end_telemetry.record_snapshot(
        'test-service',
        'thread.queued',
        unit_execution,
        (0, 0, 0, 0),
        dedicated=False,
    )
    assert len(fail_end_tracer.spans) == 1
    assert fail_end_tracer.spans[0].ended is False

    failing_telemetry = OpenTelemetryThreadTelemetry()
    failing_telemetry._tracer = FakeTracer(fail_start=True)
    _patch_otel_globals(monkeypatch)
    policy = LanePolicy(name='lane1', max_workers=1, max_queue_size=0)
    degrade_manager = ThreadManager('test-service', {'lane1': policy}, telemetry=failing_telemetry)
    degrade_manager.start()
    try:
        assert degrade_manager.run_sync('lane1', _spec(), lambda: 'ok', timeout=5.0) == 'ok'
    finally:
        _close_manager(degrade_manager)
