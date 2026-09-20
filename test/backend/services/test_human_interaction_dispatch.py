"""Bounded HITL admission without starting timed-out or cancelled requests."""

import asyncio
import logging
from unittest.mock import MagicMock

import pytest
from consts.exceptions import RuntimeQueueTimeoutError
from services.human_interaction import application


@pytest.fixture
def service(mocker):
    async def blocking(_name, fn, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return fn(*args, **kwargs)

    mocker.patch.object(application, "run_blocking", blocking)
    mocker.patch.object(application, "RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS", 0.02)
    return MagicMock()


async def test_saturated_scheduler_returns_retryable_timeout(service, caplog):
    service.light_snapshot.return_value = {"status": "READY", "attempt_active": False}
    service.cancel_queued.return_value = True

    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeQueueTimeoutError) as exc:
        await application._wait_for_dispatch(service, "run", "tenant", "user")

    assert exc.value.retry_after_seconds == 1
    service.cancel_queued.assert_called_once_with("run", "tenant", "user")
    assert "event=hitl_queue_timeout" in caplog.text
    assert "phase=dispatch" in caplog.text


@pytest.mark.parametrize("status,active", [("RUNNING", True), ("READY", True), ("FAILED", False)])
async def test_dispatch_or_terminal_status_ends_admission(service, status, active):
    service.light_snapshot.return_value = {"status": status, "attempt_active": active}

    await application._wait_for_dispatch(service, "run", "tenant", "user")

    service.cancel_queued.assert_not_called()


async def test_claim_winning_timeout_race_keeps_its_execution(service):
    service.light_snapshot.return_value = {"status": "READY", "attempt_active": False}
    service.cancel_queued.return_value = False

    await application._wait_for_dispatch(service, "run", "tenant", "user")

    service.cancel_queued.assert_called_once_with("run", "tenant", "user")


async def test_disconnect_cancels_only_unclaimed_run(service):
    observed = asyncio.Event()

    def snapshot(*_):
        observed.set()
        return {"status": "READY", "attempt_active": False}

    service.light_snapshot.side_effect = snapshot
    task = asyncio.create_task(application._wait_for_dispatch(service, "run", "tenant", "user"))
    await observed.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    service.cancel_queued.assert_called_once_with("run", "tenant", "user")
