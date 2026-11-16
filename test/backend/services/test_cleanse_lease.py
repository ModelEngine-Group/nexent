# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Lease checks retain tenant, attempt and authorization boundaries."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from management.services.file.cleanse_lease import CleanseLeaseGuard
from nexent.storage.errors import (
    InvalidInput,
    OperationCancelled,
    ScopeDenied,
    Unavailable,
)

from test.backend.services.test_cleanse_jobs import context, lookup, request
from test.backend.services.test_cleanse_jobs import setup as setup  # noqa: PLC0414


def guard(jobs, authorize=None, clock=None):
    return CleanseLeaseGuard(
        jobs,
        authorize_execution=authorize or Mock(),
        lease_seconds=60,
        clock=clock or (lambda: 0),
    )


def test_renewal_extends_current_attempt_and_throttles(setup, mocker):
    make, wall = setup
    jobs = make()
    jobs.submit(request(), context=context())
    row = jobs.claim("worker", lease_seconds=60, context=context())
    auth, timer = Mock(), [0]
    check = guard(jobs, auth, lambda: timer[0])
    renew = mocker.patch.object(jobs, "transition", wraps=jobs.transition)
    wall[0] += timedelta(seconds=30)
    check(row, context=context())
    check(row, context=context())
    assert renew.call_count == auth.call_count == 1
    wall[0] += timedelta(seconds=31)
    assert jobs.claim("other", lease_seconds=60, context=context()) is None
    timer[0] = 21
    check(row, context=context())
    assert renew.call_count == auth.call_count == 2


def test_cancelled_attempt_cannot_renew(setup):
    make, _ = setup
    jobs = make()
    state = jobs.submit(request(), context=context())
    row = jobs.claim("worker", lease_seconds=60, context=context())
    jobs.cancel(lookup(state), context=context())
    with pytest.raises(OperationCancelled):
        guard(jobs)(row, context=context())


def test_replaced_attempt_cannot_renew(setup):
    make, wall = setup
    jobs = make()
    jobs.submit(request(), context=context())
    old = jobs.claim("old", lease_seconds=60, context=context())
    wall[0] += timedelta(seconds=61)
    new = jobs.claim("new", lease_seconds=60, context=context())
    with pytest.raises(OperationCancelled):
        guard(jobs)(old, context=context())
    assert new["attempt_id"] != old["attempt_id"]


def test_revoked_authorization_prevents_renewal(setup, mocker):
    make, _ = setup
    jobs = make()
    jobs.submit(request(), context=context())
    row = jobs.claim("worker", lease_seconds=60, context=context())
    renew = mocker.patch.object(jobs, "transition", wraps=jobs.transition)
    with pytest.raises(PermissionError):
        guard(jobs, Mock(side_effect=PermissionError()))(row, context=context())
    renew.assert_not_called()


def test_foreign_tenant_rejected_before_authorization(setup):
    make, _ = setup
    jobs = make()
    jobs.submit(request(), context=context())
    row = jobs.claim("worker", lease_seconds=60, context=context())
    auth = Mock()
    with pytest.raises(ScopeDenied):
        guard(make(tenant="other"), auth)(row, context=context())
    auth.assert_not_called()


def test_storage_failure_does_not_cache_success(setup, mocker):
    make, _ = setup
    jobs = make()
    jobs.submit(request(), context=context())
    row = jobs.claim("worker", lease_seconds=60, context=context())
    check = guard(jobs)
    mocker.patch.object(jobs, "transition", side_effect=Unavailable())
    with pytest.raises(Unavailable):
        check(row, context=context())
    assert check._attempt is None


@pytest.mark.parametrize("interval", [0, 30, True, float("nan")])
def test_interval_must_be_bounded_by_half_lease(interval):
    with pytest.raises(InvalidInput):
        CleanseLeaseGuard(
            Mock(),
            authorize_execution=Mock(),
            lease_seconds=60,
            interval_seconds=interval,
        )
