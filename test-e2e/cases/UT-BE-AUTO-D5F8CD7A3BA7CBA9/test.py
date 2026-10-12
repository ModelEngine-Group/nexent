'''D1 unit tests for the evaluation-maintenance scheduler lifecycle.'''

import logging
import re
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from nexent.core.concurrency import ManagedThreadSpec

import services.evaluation_maintenance as em


_SECRET_RE = re.compile(
    r'(?i)(api[_-]?key|access[_-]?key|password|secret|token|bearer|authorization)'
)


class FakeThreadManager:
    def __init__(self, execution_id='fixed-execution-id'):
        self.execution_id = execution_id
        self.register_calls = []
        self.start_calls = []
        self.cancel_calls = []

    def register_service(self, spec, target):
        self.register_calls.append((spec, target))
        return SimpleNamespace(execution_id=self.execution_id)

    def start_service(self, execution_id):
        self.start_calls.append(execution_id)

    def cancel(self, execution_id, reason=None):
        self.cancel_calls.append((execution_id, reason))


@contextmanager
def _null_session():
    yield None


@pytest.mark.case_id('UT-BE-AUTO-D5F8CD7A3BA7CBA9')
@pytest.mark.stage('D1')
def test_evaluation_maintenance_lifecycle(monkeypatch, caplog):
    monkeypatch.setattr(em, '_running', False)
    monkeypatch.setattr(em, '_thread_manager', None)
    monkeypatch.setattr(em, '_execution_id', None)
    monkeypatch.setattr(em, 'list_dispatchable_pending_runs', lambda: [])
    monkeypatch.setattr(em, 'get_db_session', _null_session)
    monkeypatch.setattr(em, 'reap_stale_runs', lambda tenant_id: 0)
    monkeypatch.setattr(em, 'cleanup_aged_evaluations', lambda tenant_id: 0)

    fake_tm = FakeThreadManager()

    with caplog.at_level(logging.INFO, logger='services.evaluation_maintenance'):
        em.start(fake_tm)
        assert em._running is True
        assert em._thread_manager is fake_tm
        assert em._execution_id == fake_tm.execution_id
        assert len(fake_tm.register_calls) == 1
        spec, target = fake_tm.register_calls[0]
        assert isinstance(spec, ManagedThreadSpec)
        assert spec.task_name == 'evaluation-maintenance'
        assert spec.owner == 'services.evaluation_maintenance'
        assert spec.close_hook is em._request_stop
        assert target is em._run_loop
        assert fake_tm.start_calls == [fake_tm.execution_id]

        em.start(fake_tm)
        assert len(fake_tm.register_calls) == 1
        assert len(fake_tm.start_calls) == 1

        em.stop()
        assert em._running is False
        assert fake_tm.cancel_calls == [
            (fake_tm.execution_id, 'evaluation maintenance shutdown')
        ]
        assert em._thread_manager is None
        assert em._execution_id is None

    log_text = caplog.text
    assert 'Evaluation maintenance scheduler started' in log_text
    assert 'Evaluation maintenance scheduler stopped' in log_text
    assert not _SECRET_RE.search(log_text)

    dispatched = []
    monkeypatch.setattr(
        em,
        'list_dispatchable_pending_runs',
        lambda: dispatched.append(True) or [],
    )
    em._running = True
    cancel_event = threading.Event()
    cancel_event.set()
    em._run_loop(cancel_event)
    assert dispatched == []

    em._running = False
    cancel_event.clear()
    em._run_loop(cancel_event)
    assert dispatched == []
