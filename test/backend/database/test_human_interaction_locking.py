"""Real PostgreSQL regressions for HITL locks and dispatch isolation.

Uses the existing opt-in hitl_test fixture; never runs on a business database.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from consts.exceptions import RuntimeQueueTimeoutError
from database.db_models import ConversationRecord
from nexent.core.human_interaction.contracts import AttemptSuspended, RunTerminated
from nexent.scheduler import LeaseScheduler, SchedulerConfig
from services.human_interaction import application
from sqlalchemy import insert
from sqlalchemy.exc import OperationalError

from test.backend.services import test_human_interaction as support

service = support.service


def create_conversation_run(service, conversation_id):
    with service.repository.session_factory() as session:
        session.execute(insert(ConversationRecord).values(
            conversation_id=conversation_id, created_by="owner", updated_by="owner", delete_flag="N",
        ))
    return service.create("tenant-a", "owner", conversation_id, {})


def waiting_run(service):
    run_id = support.create_run(service)
    port = support.port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("slot", "send", {})
    return run_id, port


def test_resume_flush_commits_before_acquiring_run_lock(service):
    run_id, port = waiting_run(service)
    service.repository.lock_timeout_ms = 150
    support.decide_pending(service, run_id)
    port.add_chunk('data: {"type":"model_output","content":"before resume"}\n\n')

    port._wait_until_ready()

    events = service.repository.events(run_id)
    assert "chunk_cipher" in events[-2]["payload"]
    assert events[-1]["payload"]["content"]["status"] == "RUNNING"
    assert service.light_snapshot(run_id, "tenant-a", "owner")["status"] == "RUNNING"


def test_row_lock_wait_is_bounded_and_does_not_poison_next_transaction(service):
    run_id = support.create_run(service)
    service.repository.lock_timeout_ms = 50
    with service.repository.transaction(run_id):
        with pytest.raises(OperationalError) as exc, service.repository.transaction(run_id):
            pytest.fail("A second session acquired the locked row")
        assert exc.value.orig.pgcode == "55P03"
    assert service.snapshot(run_id, "tenant-a", "owner")["status"] == "READY"


def test_guidance_reads_do_not_wait_for_run_writer(service):
    run_id, port = waiting_run(service)
    service.repository.lock_timeout_ms = 50
    with service.repository.transaction(run_id):
        assert port.visible_guidance() == []
    service.repository.release(run_id, "worker")
    with pytest.raises(RunTerminated):
        port.visible_guidance()


async def test_locked_waiting_run_cannot_block_unrelated_dispatch(service, monkeypatch):
    run_id, _ = waiting_run(service)
    next_id = create_conversation_run(service, 8)
    monkeypatch.setattr(application, "get_service", lambda: service)
    store = application.HumanRunLeaseStore()

    with service.repository.transaction(run_id):
        jobs = await asyncio.wait_for(store.claim_due("next-worker", 1, 120), timeout=2)

    assert [job.job_id for job in jobs] == [next_id]


@pytest.mark.parametrize("claim_first", [False, True])
def test_queue_timeout_and_claim_are_mutually_exclusive(service, claim_first):
    run_id = support.create_run(service)
    if claim_first:
        assert service.repository.claim("worker", 1, 120)
        assert not service.cancel_queued(run_id, "tenant-a", "owner")
        assert service.light_snapshot(run_id, "tenant-a", "owner")["status"] == "RUNNING"
    else:
        assert service.cancel_queued(run_id, "tenant-a", "owner")
        assert service.repository.claim("worker", 1, 120) == []
        assert service.light_snapshot(run_id, "tenant-a", "owner")["status"] == "FAILED"


def test_concurrent_queue_timeout_never_cancels_a_claimed_run(service):
    run_id = support.create_run(service)
    barrier = Barrier(2)

    def claim():
        barrier.wait(timeout=2)
        return service.repository.claim("worker", 1, 120)

    def cancel():
        barrier.wait(timeout=2)
        return service.cancel_queued(run_id, "tenant-a", "owner")

    with ThreadPoolExecutor(max_workers=2) as workers:
        claimed, cancelled = workers.submit(claim), workers.submit(cancel)
        jobs, stopped = claimed.result(timeout=2), cancelled.result(timeout=2)
    assert bool(jobs) != stopped
    assert service.light_snapshot(run_id, "tenant-a", "owner")["status"] == (
        "RUNNING" if jobs else "FAILED"
    )


async def test_two_waiting_attempts_cannot_leave_third_request_heartbeating_forever(service, monkeypatch):
    support.create_run(service)
    create_conversation_run(service, 8)
    next_id = create_conversation_run(service, 9)
    waiting = asyncio.Event()
    release = asyncio.Event()
    started = []

    async def execute(job, lease):
        with service.repository.transaction(job.job_id) as tx:
            service.request(tx, kind="CLARIFICATION", slot="ask", action_digest="0" * 64,
                            payload={"question": "Continue?"})
        started.append(job.job_id)
        if len(started) == 2:
            waiting.set()
        await release.wait()

    monkeypatch.setattr(application, "get_service", lambda: service)
    monkeypatch.setattr(application, "RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS", 0.05)
    scheduler = LeaseScheduler(application.HumanRunLeaseStore(), execute, SchedulerConfig(
        max_concurrency=2, poll_interval_seconds=0.01, shutdown_grace_seconds=0.1,
    ))
    await scheduler.start()
    try:
        await asyncio.wait_for(waiting.wait(), 2)
        with pytest.raises(RuntimeQueueTimeoutError):
            await asyncio.wait_for(application._wait_for_dispatch(service, next_id, "tenant-a", "owner"), 2)
        assert next_id not in started
        assert service.light_snapshot(next_id, "tenant-a", "owner")["status"] == "FAILED"
    finally:
        release.set()
        await scheduler.stop()
    assert service.repository.claim("later-worker", 1, 120) == []
