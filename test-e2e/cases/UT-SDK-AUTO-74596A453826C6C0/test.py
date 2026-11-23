from __future__ import annotations

import threading
import uuid

import pytest

from nexent.core.concurrency.cancellation import ResourceToken, RunCancellationScope

CASE_ID = 'UT-SDK-AUTO-74596A453826C6C0'


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
def test_run_cancellation_scope_resource_closer_hooks():
    scope = RunCancellationScope()
    assert scope.cancelled is False
    assert isinstance(scope.stop_event, threading.Event)
    assert scope.stop_event.is_set() is False

    calls = []

    def make_closer(name):
        def _closer():
            calls.append(name)
        return _closer

    token_a = scope.register_closer(make_closer('a'))
    token_b = scope.register_closer(make_closer('b'))
    token_c = scope.register_closer(make_closer('c'))

    for token in (token_a, token_b, token_c):
        assert isinstance(token, ResourceToken)
        uuid.UUID(token.value)
        assert len(token.value) == 32

    assert len({token_a.value, token_b.value, token_c.value}) == 3
    assert scope.cancelled is False
    assert calls == []

    scope.unregister_closer(token_b)
    unknown = ResourceToken(uuid.uuid4().hex)
    scope.unregister_closer(unknown)
    scope.unregister_closer(token_b)

    scope.cancel()
    assert scope.cancelled is True
    assert scope.stop_event.is_set() is True
    assert calls == ['a', 'c']

    scope.cancel()
    assert calls == ['a', 'c']

    late_calls = []

    def close_c():
        late_calls.append('c')

    token_late = scope.register_closer(close_c)
    assert isinstance(token_late, ResourceToken)
    assert late_calls == ['c']

    scope2 = RunCancellationScope()
    ordered = []

    def good_closer():
        ordered.append('good')

    def bad_closer():
        ordered.append('bad')
        raise RuntimeError('boom')

    token_bad = scope2.register_closer(bad_closer)
    token_good = scope2.register_closer(good_closer)
    assert isinstance(token_bad, ResourceToken)
    assert isinstance(token_good, ResourceToken)
    scope2.cancel()
    assert ordered == ['bad', 'good']
    assert scope2.cancelled is True

    scope3 = RunCancellationScope()
    n = 8
    counters = [0] * n
    errors = []
    barrier = threading.Barrier(n)
    kept_tokens = []

    def make_thread_closer(i):
        def _closer():
            counters[i] += 1
        return _closer

    def worker(i):
        try:
            barrier.wait(timeout=10)
            token = scope3.register_closer(make_thread_closer(i))
            if i % 2 == 0:
                kept_tokens.append(token)
            else:
                scope3.unregister_closer(token)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()

    assert errors == []
    assert len(kept_tokens) == n // 2
    assert len({token.value for token in kept_tokens}) == len(kept_tokens)
    assert scope3.cancelled is False

    cancel_errors = []

    def cancel_worker():
        try:
            scope3.cancel()
        except Exception as exc:
            cancel_errors.append(exc)

    cancel_thread = threading.Thread(target=cancel_worker)
    cancel_thread.start()
    cancel_thread.join(timeout=10)
    assert not cancel_thread.is_alive()
    assert cancel_errors == []
    assert scope3.cancelled is True
    assert scope3.stop_event.is_set() is True

    for i in range(n):
        if i % 2 == 0:
            assert counters[i] == 1
        else:
            assert counters[i] == 0
