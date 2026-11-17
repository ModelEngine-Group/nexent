# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-CLEANSE-DRAIN-01: cancellation retains physical execution ownership."""

import pytest

from test.backend.services.test_cleanse_jobs import context, lookup, request
from test.backend.services.test_cleanse_jobs import setup as setup  # noqa: PLC0414


def test_running_cancellation_is_not_an_execution_end_proof(setup):
    make, _ = setup
    public, worker = make(), make("worker")
    state = public.submit(request(), context=context())
    handle = worker.claim("worker", lease_seconds=60, context=context())
    assert worker.begin_execution(handle, context=context())
    assert public.record(lookup(state), context=context())["execution_ended"] is False
    assert public.cancel(lookup(state), context=context()).status == "cancelled"
    cancelled = public.record(lookup(state), context=context())
    assert cancelled["execution_ended"] is False
    assert cancelled["owner_id"] == handle["owner_id"] and cancelled["attempt_id"] == handle["attempt_id"]
    assert worker.finish_execution(handle, context=context())
    final = public.record(lookup(state), context=context())
    assert final["execution_ended"] is True and final["reconcile_required"] is True
    assert not worker.finish_execution(handle, context=context())


def test_queued_cancellation_has_no_running_parser(setup):
    make, _ = setup
    public = make()
    state = public.submit(request(), context=context())
    public.cancel(lookup(state), context=context())
    assert public.record(lookup(state), context=context())["execution_ended"] is True


@pytest.mark.parametrize("changes", [{"owner_id": "other"}, {"attempt_id": "f" * 32}])
def test_another_owner_or_attempt_cannot_claim_physical_completion(setup, changes):
    make, _ = setup
    public, worker = make(), make("worker")
    state = public.submit(request(), context=context())
    handle = worker.claim("worker", lease_seconds=60, context=context())
    worker.begin_execution(handle, context=context())
    assert not worker.finish_execution({**handle, **changes}, context=context())
    assert public.record(lookup(state), context=context())["execution_ended"] is False



@pytest.mark.parametrize("confirmed_end", [True, False])
def test_cancelled_unknown_execution_needs_the_process_owner_proof(setup, confirmed_end):
    from unittest.mock import Mock

    from management.services.file.cleanse_worker import HANDLER, CleanseHandler
    from nexent.storage.errors import OutcomeUnknown
    from nexent.storage.models import TaskEnvelope

    make, _ = setup
    public = make()
    state = public.submit(request(), context=context())

    def execute(row, value, *, context, on_finished):
        public.cancel(lookup(state), context=context)
        if confirmed_end:
            on_finished()
        raise OutcomeUnknown()

    CleanseHandler(make("worker"), owner_id="worker", lease_seconds=60,
                   authorize_execution=Mock(), execute=execute)(TaskEnvelope(state.job_id, HANDLER, {"job_id": state.job_id}), context=context())
    row = public.record(lookup(state), context=context())
    assert row["status"] == "cancelled" and row["execution_ended"] is confirmed_end
    assert row["reconcile_required"] is True
    assert public.ready(context=context()) == ()


def test_stale_worker_cannot_finish_a_replacement_attempt(setup):
    from datetime import timedelta

    make, clock = setup
    public, worker = make(), make("worker")
    state = public.submit(request(), context=context())
    old = worker.claim("old", lease_seconds=30, context=context())
    clock[0] += timedelta(seconds=31)
    current = worker.claim("new", lease_seconds=30, context=context())
    assert worker.begin_execution(current, context=context())
    assert not worker.finish_execution(old, context=context())
    assert public.record(lookup(state), context=context())["execution_ended"] is False



def test_duplicate_delivery_cannot_confirm_another_live_attempt(setup):
    from unittest.mock import Mock

    from management.services.file.cleanse_worker import HANDLER, CleanseHandler
    from nexent.storage.models import TaskEnvelope

    make, _ = setup
    public, original = make(), make("original")
    state = public.submit(request(), context=context())
    handle = original.claim("original", lease_seconds=60, context=context())
    original.begin_execution(handle, context=context())
    public.cancel(lookup(state), context=context())
    execute = Mock()
    CleanseHandler(make("replacement"), owner_id="replacement", lease_seconds=60,
                   authorize_execution=Mock(), execute=execute)(TaskEnvelope(state.job_id, HANDLER, {"job_id": state.job_id}), context=context())
    execute.assert_not_called()
    assert public.record(lookup(state), context=context())["execution_ended"] is False



def test_artifact_release_between_completion_and_end_ack_does_not_lose_the_proof(setup, monkeypatch):
    from unittest.mock import Mock

    from management.services.file.cleanse_worker import HANDLER, CleanseHandler
    from nexent.storage.models import FieldPatch, TaskEnvelope

    from test.backend.services.test_cleanse_jobs import artifact

    make, _ = setup
    public, worker = make(), make("worker")
    state = public.submit(request(), context=context())
    transition = worker.transition

    def release(handle, *, context, **kwargs):
        result = transition(handle, context=context, **kwargs)
        if kwargs["status"] == "completed":
            public.records.patch("file_cleanse_jobs", handle["id"],
                                 FieldPatch(set_values={"status": "released", "artifact": None}), context=context)
        return result

    monkeypatch.setattr(worker, "transition", release)
    CleanseHandler(worker, owner_id="worker", lease_seconds=60, authorize_execution=Mock(),
                   execute=Mock(return_value=artifact()))(TaskEnvelope(state.job_id, HANDLER, {"job_id": state.job_id}), context=context())
    row = public.record(lookup(state), context=context())
    assert row["status"] == "released" and row["execution_ended"] is True
