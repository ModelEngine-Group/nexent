import asyncio
from datetime import datetime, timezone

import pytest

from nexent.scheduler import (
    ClaimedJob,
    ExecutionLease,
    LeaseScheduler,
    ScheduleMode,
    ScheduleRuleType,
    ScheduleSpec,
    SchedulerConfig,
    compute_next_fire_at,
)
from nexent.scheduler import triggers as trigger_engine


async def _wait_until(predicate, timeout=1.0):
    async def wait_loop():
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(wait_loop(), timeout=timeout)


class MemoryLeaseStore:
    def __init__(self, jobs):
        self.due = list(jobs)
        self.owners = {}
        self.claim_limits = []
        self.recover_count = 0
        self.renew_result = True
        self.claim_failures = 0
        self.recover_failures = 0

    async def recover(self):
        self.recover_count += 1
        if self.recover_failures:
            self.recover_failures -= 1
            raise RuntimeError("database unavailable during recovery")

    async def claim_due(self, owner_id, limit, lease_seconds):
        self.claim_limits.append(limit)
        if self.claim_failures:
            self.claim_failures -= 1
            raise RuntimeError("database unavailable")
        claimed = []
        while self.due and len(claimed) < limit:
            job = self.due.pop(0)
            self.owners[job.job_id] = owner_id
            claimed.append(job)
        return claimed

    async def renew(self, job_id, owner_id, lease_seconds):
        return self.renew_result and self.owners.get(job_id) == owner_id

    async def release(self, job_id, owner_id):
        if self.owners.get(job_id) != owner_id:
            return False
        self.owners.pop(job_id)
        return True


def _config(**overrides):
    values = {
        "poll_interval_seconds": 0.01,
        "lease_seconds": 0.09,
        "max_concurrency": 2,
        "shutdown_grace_seconds": 0.05,
        "error_backoff_seconds": 0.01,
        "max_error_backoff_seconds": 0.02,
    }
    values.update(overrides)
    return SchedulerConfig(**values)


def test_schedule_engine_is_framework_independent():
    spec = ScheduleSpec(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.INTERVAL,
        timezone="UTC",
        start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        interval_seconds=60,
    )

    assert compute_next_fire_at(
        spec,
        datetime(2026, 1, 1, 0, 2, 30, tzinfo=timezone.utc),
        fire_count=2,
    ) == datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_scheduler_claims_only_available_capacity():
    store = MemoryLeaseStore([ClaimedJob(index, {"id": index}) for index in range(3)])
    started = []
    gate = asyncio.Event()

    async def execute(job, lease):
        started.append(job.job_id)
        await gate.wait()

    scheduler = LeaseScheduler(store, execute, _config(), owner_id="scheduler-a")
    await scheduler.start()
    await _wait_until(lambda: len(started) == 2)

    assert store.recover_count == 1
    assert store.claim_limits[0] == 2
    assert scheduler.active_count == 2

    gate.set()
    await scheduler.stop()


@pytest.mark.asyncio
async def test_lease_loss_cancels_stale_executor():
    store = MemoryLeaseStore([ClaimedJob(1, {"id": 1})])
    store.renew_result = False
    canceled = asyncio.Event()
    observed_lost = []

    async def execute(job, lease):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            observed_lost.append(lease.lost.is_set())
            canceled.set()
            raise

    scheduler = LeaseScheduler(store, execute, _config(max_concurrency=1), owner_id="scheduler-a")
    await scheduler.start()
    await asyncio.wait_for(canceled.wait(), timeout=1)
    await scheduler.stop()

    assert observed_lost == [True]


@pytest.mark.asyncio
async def test_scheduler_recovers_after_transient_claim_failure():
    store = MemoryLeaseStore([ClaimedJob(1, {"id": 1})])
    store.claim_failures = 1
    executed = asyncio.Event()

    async def execute(job, lease):
        executed.set()

    scheduler = LeaseScheduler(store, execute, _config(max_concurrency=1), owner_id="scheduler-a")
    await scheduler.start()
    await asyncio.wait_for(executed.wait(), timeout=1)
    await scheduler.stop()

    assert len(store.claim_limits) >= 2


@pytest.mark.asyncio
async def test_startup_is_non_blocking_and_retries_recovery():
    store = MemoryLeaseStore([ClaimedJob(1, {"id": 1})])
    store.recover_failures = 1
    executed = asyncio.Event()

    async def execute(job, lease):
        executed.set()

    scheduler = LeaseScheduler(store, execute, _config(max_concurrency=1), owner_id="scheduler-a")
    await scheduler.start()
    await asyncio.wait_for(executed.wait(), timeout=1)
    await scheduler.stop()

    assert store.recover_count == 2


@pytest.mark.asyncio
async def test_stop_is_bounded_and_releases_interrupted_job():
    store = MemoryLeaseStore([ClaimedJob(1, {"id": 1})])
    started = asyncio.Event()
    canceled = asyncio.Event()

    async def execute(job, lease):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            canceled.set()
            raise

    scheduler = LeaseScheduler(
        store,
        execute,
        _config(max_concurrency=1, shutdown_grace_seconds=0.01),
        owner_id="scheduler-a",
    )
    await scheduler.start()
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.wait_for(scheduler.stop(), timeout=0.5)

    assert canceled.is_set()
    assert store.owners == {}


@pytest.mark.asyncio
async def test_new_scheduler_resumes_persisted_job_after_restart():
    job = ClaimedJob(1, {"id": 1})

    class RestartableStore:
        def __init__(self):
            self.owner = None
            self.completed = False
            self.recover_count = 0

        async def recover(self):
            self.recover_count += 1

        async def claim_due(self, owner_id, limit, lease_seconds):
            if self.owner is None and not self.completed:
                self.owner = owner_id
                return [job]
            return []

        async def renew(self, job_id, owner_id, lease_seconds):
            return self.owner == owner_id

        async def release(self, job_id, owner_id):
            if self.owner != owner_id:
                return False
            self.owner = None
            return True

    store = RestartableStore()
    first_started = asyncio.Event()

    async def interrupted_execution(job, lease):
        first_started.set()
        await asyncio.Event().wait()

    first = LeaseScheduler(
        store,
        interrupted_execution,
        _config(max_concurrency=1, shutdown_grace_seconds=0.01),
        owner_id="scheduler-before-restart",
    )
    await first.start()
    await asyncio.wait_for(first_started.wait(), timeout=1)
    await first.stop()

    resumed = asyncio.Event()

    async def resumed_execution(job, lease):
        store.completed = True
        resumed.set()

    second = LeaseScheduler(
        store,
        resumed_execution,
        _config(max_concurrency=1),
        owner_id="scheduler-after-restart",
    )
    await second.start()
    await asyncio.wait_for(resumed.wait(), timeout=1)
    await second.stop()

    assert store.completed is True
    assert store.recover_count == 2


def test_scheduler_config_and_lease_validation():
    with pytest.raises(ValueError, match="must be positive"):
        SchedulerConfig(poll_interval_seconds=0)

    lease = ExecutionLease(job_id=1, owner_id="scheduler-a")
    assert lease.is_valid is True
    lease.lost.set()
    assert lease.is_valid is False


@pytest.mark.asyncio
async def test_scheduler_start_is_idempotent_and_job_failures_release_lease():
    class FailingStore(MemoryLeaseStore):
        async def release(self, job_id, owner_id):
            raise RuntimeError("release failed")

    store = FailingStore([])

    async def fail(job, lease):
        raise RuntimeError("execution failed")

    scheduler = LeaseScheduler(store, fail, _config(), owner_id="scheduler-a")
    await scheduler.start()
    first_loop = scheduler._loop_task
    await scheduler.start()
    assert scheduler._loop_task is first_loop

    await scheduler._run_claimed(ClaimedJob(1, {"id": 1}))
    await scheduler.stop()


def test_cron_validation_fallback_rejects_invalid_fields(monkeypatch):
    monkeypatch.setattr(trigger_engine, "croniter", None)

    assert trigger_engine._is_valid_cron_field("", 0, 59) is False
    assert trigger_engine._is_valid_cron_field("*/0", 0, 59) is False
    assert trigger_engine._is_valid_cron_field("x-y", 0, 59) is False
    assert trigger_engine._is_valid_cron_field("10-5", 0, 59) is False
    assert trigger_engine._is_valid_cron_field("*/5", 0, 59) is True
    assert trigger_engine._is_valid_cron_field("10-20/5", 0, 59) is True
    assert trigger_engine._is_valid_cron_field("60", 0, 59) is False
    assert trigger_engine.is_valid_cron_expression("*/5 9-17 * * 1-5") is True
    assert trigger_engine.is_valid_cron_expression("bad cron") is False


def test_croniter_validation_and_match_fail_closed(monkeypatch):
    class WorkingCroniter:
        @staticmethod
        def is_valid(expression):
            return True

        @staticmethod
        def match(expression, value):
            return True

    monkeypatch.setattr(trigger_engine, "croniter", WorkingCroniter)
    value = datetime(2030, 1, 1, 9, 0, tzinfo=timezone.utc)
    assert trigger_engine.is_valid_cron_expression("0 9 * * *") is True
    assert trigger_engine._cron_matches_start("0 9 * * *", value) is True

    class BrokenCroniter:
        @staticmethod
        def is_valid(expression):
            raise RuntimeError("invalid")

        @staticmethod
        def match(expression, value):
            raise RuntimeError("invalid")

    monkeypatch.setattr(trigger_engine, "croniter", BrokenCroniter)
    assert trigger_engine.is_valid_cron_expression("0 9 * * *") is False
    assert trigger_engine._cron_matches_start("0 9 * * *", value) is False


def test_schedule_calculation_rejects_invalid_combinations_and_honors_bounds(monkeypatch):
    monkeypatch.setattr(trigger_engine, "croniter", None)
    naive_start = datetime(2030, 1, 1, 9, 0)
    assert trigger_engine._ensure_aware(naive_start, "UTC").tzinfo is not None

    once = ScheduleSpec(
        mode=ScheduleMode.ONCE,
        rule_type=ScheduleRuleType.AT,
        timezone="UTC",
        start_at=naive_start,
    )
    assert compute_next_fire_at(once, datetime(2030, 1, 1, tzinfo=timezone.utc), 1) is None

    interval = ScheduleSpec(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.INTERVAL,
        timezone="UTC",
        start_at=naive_start,
        interval_seconds=0,
    )
    with pytest.raises(ValueError, match="interval_seconds"):
        compute_next_fire_at(interval, datetime(2030, 1, 1, tzinfo=timezone.utc), 0)

    interval = ScheduleSpec(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.INTERVAL,
        timezone="UTC",
        start_at=naive_start,
        interval_seconds=60,
        end_at=datetime(2030, 1, 1, 9, 0),
    )
    assert compute_next_fire_at(interval, datetime(2030, 1, 1, 8, 0), 0) == datetime(
        2030, 1, 1, 9, 0, tzinfo=timezone.utc
    )
    assert compute_next_fire_at(interval, datetime(2030, 1, 1, 9, 1), 0) is None

    invalid_cron = ScheduleSpec(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.CRON,
        timezone="UTC",
        start_at=naive_start,
        cron_expr="bad cron",
    )
    with pytest.raises(ValueError, match="Invalid cron"):
        compute_next_fire_at(invalid_cron, datetime(2030, 1, 1, tzinfo=timezone.utc), 0)

    unsupported = ScheduleSpec(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.AT,
        timezone="UTC",
        start_at=naive_start,
    )
    with pytest.raises(ValueError, match="Unsupported schedule combination"):
        compute_next_fire_at(unsupported, datetime(2030, 1, 1, tzinfo=timezone.utc), 0)


def test_fallback_cron_day_rules_and_invalid_expression(monkeypatch):
    monkeypatch.setattr(trigger_engine, "croniter", None)
    month_end = datetime(2030, 1, 31, 9, 0, tzinfo=timezone.utc)

    assert trigger_engine._cron_matches_start("0 9 L * *", month_end) is True
    assert trigger_engine._cron_matches_start("0 9 1 * 4", month_end) is True
    assert trigger_engine._cron_matches_start("bad", month_end) is False
    assert trigger_engine._cron_field_matches("*/3", 9) is True
    assert trigger_engine._cron_field_matches("5-10/2", 9) is True
    assert trigger_engine._cron_weekday_matches("7", datetime(2030, 1, 6, tzinfo=timezone.utc)) is True
    with pytest.raises(ValueError, match="Invalid cron expression"):
        trigger_engine._fallback_next_cron("bad", month_end)
