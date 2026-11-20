# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
from contextlib import contextmanager, nullcontext
from threading import Event
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError

from contracts.evaluation import EvalRunStatus
from management.services.evaluation import dispatch
from management.services.execution_coordination import ExecutionAlreadyActiveError, RuntimeCoordinationUnavailableError
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager, ThreadQueueTimedOut


@pytest.fixture
def admission(monkeypatch):
    session = object()
    reserve = Mock(return_value=45)
    claim = Mock(return_value=True)
    transition = Mock(return_value=True)
    transaction = []

    @contextmanager
    def managed_session():
        try:
            yield session
        except BaseException:
            transaction.append("rollback")
            raise
        else:
            transaction.append("commit")

    monkeypatch.setattr(dispatch, "get_db_session", managed_session)
    monkeypatch.setattr(dispatch, "NEXENT_RECOVERY_MODE", "maintenance")
    monkeypatch.setattr(dispatch, "NEXENT_MAINTENANCE_EPOCH", "test-epoch")
    monkeypatch.setattr(dispatch, "reserve_runtime_execution", reserve)
    monkeypatch.setattr(dispatch, "claim_agent_evaluation_run", claim)
    monkeypatch.setattr(dispatch, "transition_runtime_execution", transition)
    return session, reserve, claim, transition, transaction


def test_evaluation_reservation_and_pending_claim_share_the_transaction(admission):
    session, reserve, claim, transition, transaction = admission

    assert dispatch._claim_evaluation(7, "t1", "u1") == 45

    assert reserve.call_args.kwargs["execution_key"] == "evaluation:7"
    assert reserve.call_args.kwargs["execution_kind"] == "evaluation"
    assert reserve.call_args.kwargs["agent_scope"] is None
    assert reserve.call_args.kwargs["agent_limit"] is None
    assert reserve.call_args.kwargs["db_session"] is session
    claim.assert_called_once_with(7, "t1", "u1", db_session=session)
    transition.assert_called_once_with(45, dispatch.RUNTIME_OWNER_INSTANCE_ID, "RUNNING", db_session=session)
    assert transaction == ["commit"]


@pytest.mark.parametrize("loses_claim", [True, False])
def test_unaccepted_evaluation_rolls_back_reservation(admission, loses_claim):
    _, reserve, claim, transition, transaction = admission
    claim.return_value = not loses_claim
    transition.return_value = False

    error = ExecutionAlreadyActiveError if loses_claim else RuntimeCoordinationUnavailableError
    with pytest.raises(error):
        dispatch._claim_evaluation(7, "t1", "u1")

    reserve.assert_called_once()
    assert transition.called is not loses_claim
    assert transaction == ["rollback"]


def test_database_failure_is_retryable_and_does_not_claim(admission):
    _, reserve, claim, _, transaction = admission
    reserve.side_effect = OperationalError(None, None, ConnectionError("unavailable"))

    with pytest.raises(RuntimeCoordinationUnavailableError):
        dispatch._claim_evaluation(7, "t1", "u1")

    claim.assert_not_called()
    assert transaction == ["rollback"]


@pytest.fixture
async def evaluation_manager(monkeypatch):
    manager = ThreadManager(service_name="evaluation-admission-test", lane_policies={
        "evaluation": LanePolicy(name="evaluation", max_workers=1, max_queue_size=1, queue_timeout_seconds=0.5),
        "control-io": LanePolicy(name="control-io", max_workers=1, max_queue_size=1),
    })
    manager.start()
    monkeypatch.setattr(dispatch, "runtime_thread_manager", manager)
    try:
        yield manager
    finally:
        await manager.shutdown(timeout=3)


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_fails", [False, True])
async def test_accepted_evaluation_settles_only_after_the_managed_worker_exits(monkeypatch, evaluation_manager, worker_fails):
    loop = asyncio.get_running_loop()
    finalizing, settled = asyncio.Event(), asyncio.Event()
    allow_completion = Event()
    claim = Mock(return_value=45)
    begin = Mock()
    terminal = Mock()

    def execute(tenant_id, user_id, evaluation_id, judge_model_id, *, before_finalize):
        assert (tenant_id, user_id, evaluation_id, judge_model_id) == ("t1", "u1", 7, 9)
        claim.assert_called_once_with(7, "t1", "u1")
        before_finalize()
        loop.call_soon_threadsafe(finalizing.set)
        assert allow_completion.wait(timeout=3)
        if worker_fails:
            raise RuntimeError("worker failed")
        return EvalRunStatus.COMPLETED

    def finish(*args):
        terminal(*args)
        loop.call_soon_threadsafe(settled.set)

    monkeypatch.setattr(dispatch, "_claim_evaluation", claim)
    monkeypatch.setattr(dispatch, "_begin_finalizing", begin)
    monkeypatch.setattr(dispatch, "_settle_evaluation", finish)
    try:
        await asyncio.wait_for(dispatch.start_pending_evaluation(7, "t1", "u1", 9, execute), timeout=2)
        await asyncio.wait_for(finalizing.wait(), timeout=2)
        begin.assert_called_once_with(45)
        terminal.assert_not_called()
    finally:
        allow_completion.set()

    await asyncio.wait_for(settled.wait(), timeout=2)
    terminal.assert_called_once_with(45, 7, "t1", "u1", EvalRunStatus.FAILED if worker_fails else EvalRunStatus.COMPLETED)


@pytest.mark.asyncio
async def test_queue_timeout_never_claims_the_evaluation(monkeypatch, evaluation_manager):
    loop = asyncio.get_running_loop()
    began = asyncio.Event()
    unblock = Event()

    def hold_lane():
        loop.call_soon_threadsafe(began.set)
        assert unblock.wait(timeout=3)

    blocker = evaluation_manager.submit("evaluation", ManagedTaskSpec(task_name="hold-evaluation", owner="test"), hold_lane)
    claim, execute = Mock(), Mock()
    monkeypatch.setattr(dispatch, "_claim_evaluation", claim)
    try:
        await asyncio.wait_for(began.wait(), timeout=2)
        with pytest.raises(ThreadQueueTimedOut):
            await asyncio.wait_for(dispatch.start_pending_evaluation(7, "t1", "u1", 9, execute), timeout=2)
    finally:
        unblock.set()

    await asyncio.wrap_future(blocker.future)
    claim.assert_not_called()
    execute.assert_not_called()


@pytest.mark.parametrize("still_owned", [False, True])
def test_crashed_worker_fails_only_its_running_evaluation(monkeypatch, still_owned):
    session = object()
    update = Mock()
    transition = Mock(return_value=still_owned)
    monkeypatch.setattr(dispatch, "get_db_session", lambda: nullcontext(session))
    monkeypatch.setattr(dispatch, "update_agent_evaluation_status", update)
    monkeypatch.setattr(dispatch, "transition_runtime_execution", transition)

    dispatch._settle_evaluation(45, 7, "t1", "u1", EvalRunStatus.FAILED)

    transition.assert_called_once_with(45, dispatch.RUNTIME_OWNER_INSTANCE_ID, "FAILED", db_session=session)
    if still_owned:
        assert update.call_args.args == (7, "t1", EvalRunStatus.FAILED)
        assert update.call_args.kwargs["expected_status"] == EvalRunStatus.RUNNING
        assert update.call_args.kwargs["db_session"] is session
    else:
        update.assert_not_called()
