"""Unit tests for memory_dreaming_scheduler (DreamingLeaseStore, execute_dreaming, DreamingScheduler)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
def mock_consts(monkeypatch):
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.DREAMING_SCHEDULER_ENABLED", True
    )
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.DREAMING_SCHEDULER_LEASE_SECONDS", 120.0
    )
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.DREAMING_SCHEDULER_MAX_CONCURRENCY", 2
    )
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.DREAMING_SCHEDULER_POLL_SECONDS", 30.0
    )


@pytest.fixture
def inline_to_thread(monkeypatch):
    """Keep adapter unit tests deterministic and free of executor threads."""

    async def run_inline(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.asyncio.to_thread",
        run_inline,
    )


# ---------------------------------------------------------------------------
# DreamingLeaseStore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lease_store_recover(monkeypatch, inline_to_thread):
    from services.memory_dreaming_scheduler import DreamingLeaseStore

    mock_recover = MagicMock(return_value=3)
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.memory_dreaming_db.recover_stale",
        mock_recover,
    )

    store = DreamingLeaseStore()
    await store.recover()

    mock_recover.assert_called_once_with(True)


@pytest.mark.asyncio
async def test_lease_store_claim_due_returns_job(monkeypatch, inline_to_thread):
    from services.memory_dreaming_scheduler import DreamingLeaseStore

    row = {
        "run_id": 42,
        "tenant_id": "t",
        "user_id": "u",
        "agent_id": "a",
        "trigger_source": "manual",
    }
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.memory_dreaming_db.claim_queued",
        lambda owner_id, lease_seconds: row,
    )
    materialize = MagicMock(return_value=1)
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.memory_dreaming_db.materialize_due_schedules",
        materialize,
    )

    store = DreamingLeaseStore()
    jobs = await store.claim_due("worker-1", 1, 120.0)

    assert len(jobs) == 1
    assert jobs[0].job_id == 42
    assert jobs[0].payload == row
    materialize.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_lease_store_claim_due_returns_empty(monkeypatch, inline_to_thread):
    from services.memory_dreaming_scheduler import DreamingLeaseStore

    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.memory_dreaming_db.claim_queued",
        lambda owner_id, lease_seconds: None,
    )
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.memory_dreaming_db.materialize_due_schedules",
        lambda limit: 0,
    )

    store = DreamingLeaseStore()
    jobs = await store.claim_due("worker-1", 1, 120.0)

    assert jobs == []


@pytest.mark.asyncio
async def test_lease_store_renew(monkeypatch, inline_to_thread):
    from services.memory_dreaming_scheduler import DreamingLeaseStore

    mock_renew = MagicMock(return_value=True)
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.memory_dreaming_db.renew_lease",
        mock_renew,
    )

    store = DreamingLeaseStore()
    result = await store.renew(42, "worker-1", 120.0)

    assert result is True
    mock_renew.assert_called_once_with(42, "worker-1", 120.0)


@pytest.mark.asyncio
async def test_lease_store_release(monkeypatch, inline_to_thread):
    from services.memory_dreaming_scheduler import DreamingLeaseStore

    mock_release = MagicMock(return_value=True)
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.memory_dreaming_db.release_lease",
        mock_release,
    )

    store = DreamingLeaseStore()
    result = await store.release(42, "worker-1")

    assert result is True
    mock_release.assert_called_once_with(42, "worker-1")


# ---------------------------------------------------------------------------
# execute_dreaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_dreaming_success(monkeypatch, inline_to_thread):
    from nexent.scheduler import ClaimedJob
    from services.memory_dreaming_scheduler import execute_dreaming

    mock_run = MagicMock()
    mock_service = MagicMock()
    mock_service.run = mock_run
    monkeypatch.setattr(
        "services.memory_dreaming_service.get_memory_dreaming_service",
        lambda: mock_service,
    )

    job = ClaimedJob(
        job_id=42,
        payload={
            "tenant_id": "t",
            "user_id": "u",
            "agent_id": "a",
            "trigger_source": "scheduler",
        },
    )
    lease = MagicMock()

    await execute_dreaming(job, lease)

    mock_run.assert_called_once_with(
        tenant_id="t",
        user_id="u",
        agent_id="a",
        run_id=42,
        trigger_source="scheduler",
    )


@pytest.mark.asyncio
async def test_execute_dreaming_default_trigger_source(monkeypatch, inline_to_thread):
    from nexent.scheduler import ClaimedJob
    from services.memory_dreaming_scheduler import execute_dreaming

    mock_run = MagicMock()
    mock_service = MagicMock()
    mock_service.run = mock_run
    monkeypatch.setattr(
        "services.memory_dreaming_service.get_memory_dreaming_service",
        lambda: mock_service,
    )

    job = ClaimedJob(
        job_id=10,
        payload={
            "tenant_id": "t",
            "user_id": "u",
            "agent_id": "a",
        },
    )
    lease = MagicMock()

    await execute_dreaming(job, lease)

    mock_run.assert_called_once_with(
        tenant_id="t",
        user_id="u",
        agent_id="a",
        run_id=10,
        trigger_source="scheduler",
    )


@pytest.mark.asyncio
async def test_execute_dreaming_failure_raises(monkeypatch, inline_to_thread):
    from nexent.scheduler import ClaimedJob
    from services.memory_dreaming_scheduler import execute_dreaming

    mock_service = MagicMock()
    mock_service.run = MagicMock(side_effect=RuntimeError("model down"))
    monkeypatch.setattr(
        "services.memory_dreaming_service.get_memory_dreaming_service",
        lambda: mock_service,
    )

    job = ClaimedJob(
        job_id=42,
        payload={
            "tenant_id": "t",
            "user_id": "u",
            "agent_id": "a",
            "trigger_source": "manual",
        },
    )
    lease = MagicMock()

    with pytest.raises(RuntimeError, match="model down"):
        await execute_dreaming(job, lease)


# ---------------------------------------------------------------------------
# DreamingScheduler
# ---------------------------------------------------------------------------


def test_dreaming_scheduler_properties(monkeypatch, mock_consts):
    with patch("services.memory_dreaming_scheduler.LeaseScheduler") as MockScheduler:
        mock_instance = MagicMock()
        mock_instance.owner_id = "worker-abc"
        mock_instance.is_running = True
        MockScheduler.return_value = mock_instance

        from services.memory_dreaming_scheduler import DreamingScheduler

        scheduler = DreamingScheduler()

        assert scheduler.instance_id == "worker-abc"
        assert scheduler.is_running is True


@pytest.mark.asyncio
async def test_dreaming_scheduler_start_disabled(monkeypatch):
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.DREAMING_SCHEDULER_ENABLED", False
    )
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.DREAMING_SCHEDULER_LEASE_SECONDS", 120.0
    )
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.DREAMING_SCHEDULER_MAX_CONCURRENCY", 2
    )
    monkeypatch.setattr(
        "services.memory_dreaming_scheduler.DREAMING_SCHEDULER_POLL_SECONDS", 30.0
    )

    with patch("services.memory_dreaming_scheduler.LeaseScheduler") as MockScheduler:
        mock_instance = AsyncMock()
        MockScheduler.return_value = mock_instance

        from services.memory_dreaming_scheduler import DreamingScheduler

        scheduler = DreamingScheduler()
        await scheduler.start()

        mock_instance.start.assert_not_called()


@pytest.mark.asyncio
async def test_dreaming_scheduler_start_enabled(monkeypatch, mock_consts):
    with patch("services.memory_dreaming_scheduler.LeaseScheduler") as MockScheduler:
        mock_instance = AsyncMock()
        MockScheduler.return_value = mock_instance

        from services.memory_dreaming_scheduler import DreamingScheduler

        scheduler = DreamingScheduler()
        await scheduler.start()

        mock_instance.start.assert_called_once()


@pytest.mark.asyncio
async def test_dreaming_scheduler_stop(monkeypatch, mock_consts):
    with patch("services.memory_dreaming_scheduler.LeaseScheduler") as MockScheduler:
        mock_instance = AsyncMock()
        MockScheduler.return_value = mock_instance

        from services.memory_dreaming_scheduler import DreamingScheduler

        scheduler = DreamingScheduler()
        await scheduler.stop()

        mock_instance.stop.assert_called_once()
