from __future__ import annotations

import threading

import pytest

from nexent.core.models.model_concurrency import (
    ModelConcurrencyExceeded,
    ModelConcurrencyLimiter,
    ModelConcurrencyPermit,
)

CASE_ID = 'UT-SDK-AUTO-9A76928E3A7B1ADF'


def _unset_event():
    return threading.Event()


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
def test_model_concurrency_limiter_core_flow():
    assert issubclass(ModelConcurrencyExceeded, TimeoutError)

    key = ('tenant', 'provider', 'model')
    other_key = ('tenant', 'provider', 'other-model')

    limiter = ModelConcurrencyLimiter()
    ev = _unset_event()
    permit = limiter.acquire(key, 2, 1.0, ev)
    assert isinstance(permit, ModelConcurrencyPermit)
    entry = limiter._entries[key]
    assert entry.limit == 2
    assert entry.references == 1

    permit2 = limiter.acquire(key, 2, 1.0, ev)
    assert limiter._entries[key] is entry
    assert entry.references == 2

    other_permit = limiter.acquire(other_key, 2, 1.0, ev)
    assert limiter._entries[other_key] is not entry
    assert limiter._entries[other_key].references == 1

    for p in (permit, permit2, other_permit):
        p.release()
    assert key not in limiter._entries
    assert other_key not in limiter._entries

    for bad_limit in (0, -1):
        limiter_limit = ModelConcurrencyLimiter()
        with pytest.raises(ValueError, match='limit must be greater than zero'):
            limiter_limit.acquire(key, bad_limit, 1.0, _unset_event())
        assert limiter_limit._entries == {}

    for bad_timeout in (0, -0.1):
        limiter_timeout = ModelConcurrencyLimiter()
        with pytest.raises(ValueError, match='timeout must be greater than zero'):
            limiter_timeout.acquire(key, 2, bad_timeout, _unset_event())
        assert limiter_timeout._entries == {}

    limiter_conflict = ModelConcurrencyLimiter()
    conflict_permit = limiter_conflict.acquire(key, 2, 1.0, _unset_event())
    assert limiter_conflict._entries[key].references == 1
    with pytest.raises(ValueError, match='conflicting concurrency limits'):
        limiter_conflict.acquire(key, 3, 1.0, _unset_event())
    assert limiter_conflict._entries[key].references == 1
    conflict_permit.release()
    assert key not in limiter_conflict._entries

    limiter_timeout = ModelConcurrencyLimiter()
    ev_timeout = _unset_event()
    tp1 = limiter_timeout.acquire(key, 2, 1.0, ev_timeout)
    tp2 = limiter_timeout.acquire(key, 2, 1.0, ev_timeout)
    assert limiter_timeout._entries[key].references == 2
    with pytest.raises(ModelConcurrencyExceeded):
        limiter_timeout.acquire(key, 2, 0.05, ev_timeout)
    assert limiter_timeout._entries[key].references == 2
    tp1.release()
    tp2.release()
    assert key not in limiter_timeout._entries

    limiter_cancel = ModelConcurrencyLimiter()
    ev_cancel = threading.Event()
    ev_cancel.set()
    with pytest.raises(RuntimeError, match='cancelled'):
        limiter_cancel.acquire(key, 2, 1.0, ev_cancel)
    assert key not in limiter_cancel._entries

    limiter_idempotent = ModelConcurrencyLimiter()
    ip1 = limiter_idempotent.acquire(key, 2, 1.0, _unset_event())
    ip2 = limiter_idempotent.acquire(key, 2, 1.0, _unset_event())
    assert limiter_idempotent._entries[key].references == 2
    ip1.release()
    assert limiter_idempotent._entries[key].references == 1
    ip1.release()
    assert limiter_idempotent._entries[key].references == 1
    ip2.release()
    assert key not in limiter_idempotent._entries

    limiter_recycle = ModelConcurrencyLimiter()
    rp1 = limiter_recycle.acquire(key, 2, 1.0, _unset_event())
    rp2 = limiter_recycle.acquire(key, 2, 1.0, _unset_event())
    rp1.release()
    rp2.release()
    assert key not in limiter_recycle._entries
    rp3 = limiter_recycle.acquire(key, 3, 1.0, _unset_event())
    assert limiter_recycle._entries[key].limit == 3
    rp3.release()
    assert key not in limiter_recycle._entries
