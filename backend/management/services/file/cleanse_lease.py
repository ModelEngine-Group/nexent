# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Parent-side attempt renewal and current resource authorization during parsing."""

import math
from time import monotonic

from contracts.knowledge_cleanse import parse_cleanse_request
from nexent.storage.errors import InvalidInput, OperationCancelled, ScopeDenied


class CleanseLeaseGuard:
    def __init__(
        self,
        jobs,
        *,
        authorize_execution,
        lease_seconds,
        interval_seconds=None,
        clock=monotonic,
    ):
        if (
            not callable(authorize_execution)
            or not callable(clock)
            or type(lease_seconds) is not int
            or not 1 <= lease_seconds <= 3600
        ):
            raise InvalidInput()
        interval = lease_seconds / 3 if interval_seconds is None else interval_seconds
        if (
            isinstance(interval, bool)
            or not isinstance(interval, (int, float))
            or not math.isfinite(interval)
            or not 0 < interval < lease_seconds / 2
        ):
            raise InvalidInput()
        self.jobs = jobs
        self.authorize = authorize_execution
        self.lease_seconds = lease_seconds
        self.interval = interval
        self.clock = clock
        self._attempt = None
        self._next = 0

    def __call__(self, row, *, context):
        context.remaining()
        if row["tenant_id"] != self.jobs.records.scope.tenant_id:
            raise ScopeDenied()
        attempt = (row["job_id"], row["owner_id"], row["attempt_id"])
        now = self.clock()
        if attempt == self._attempt and now < self._next:
            return
        self.authorize(row, parse_cleanse_request(row))
        context.remaining()
        if not self.jobs.transition(
            row, status="running", lease_seconds=self.lease_seconds, context=context
        ):
            raise OperationCancelled(operation_id=context.operation_id)
        self._attempt = attempt
        self._next = now + self.interval
