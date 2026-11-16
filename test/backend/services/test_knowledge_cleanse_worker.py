# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Production worker composition preserves durable policy and live authorization."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import FileCleanseLookup
from contracts.knowledge_cleanse import KnowledgeCleanseLookup
from management.services.file import cleanse_execution as worker
from management.services.file.cleanse_lease import CleanseLeaseGuard
from management.services.file.cleanse_worker import HANDLER
from nexent.storage.errors import OutcomeUnknown, ScopeDenied
from nexent.storage.models import PageRequest, RecordQuery, StorageScope, TaskEnvelope
from nexent.storage.queue import Delivery

from infrastructure.rdb.cleanse_jobs import DATASET
from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import artifact, context
from test.backend.services.test_cleanse_jobs import setup as setup  # noqa: PLC0414
from test.backend.services.test_knowledge_cleanse_jobs import knowledge_request
from test.backend.services.test_run_cleanse_service import request as run_request


@pytest.fixture(params=["knowledge", "run"])
def prepared(setup, resources, monkeypatch, request):
    make, _ = setup
    public = make()
    reference = knowledge_request() if request.param == "knowledge" else run_request()
    state = public.submit(reference, context=context())
    _, update, engine, _ = resources
    closed = Mock()

    @contextmanager
    def ports(tenant_id, user_id, *, context):
        handle = make(user_id, tenant_id).records
        authority = bind_cleanse_resources(
            StorageScope("management", tenant_id, user_id, set(TABLES)), engine
        )
        try:
            yield handle, authority
        finally:
            authority.close()
            handle.close()
            closed()

    monkeypatch.setattr(worker, "knowledge_cleanse_ports", ports)
    queue = Mock(
        scope=StorageScope("management", "tenant-a", "worker", {"file-cleanse"})
    )
    queue.consume.return_value = Delivery(
        "receipt", TaskEnvelope(state.job_id, HANDLER, {"job_id": state.job_id})
    )
    lookup = KnowledgeCleanseLookup(
        knowledge_id=1, file_id=state.file_id, file_version=0, job_id=state.job_id
    ) if request.param == "knowledge" else FileCleanseLookup(run_id=state.run_id, job_id=state.job_id)
    return public, queue, lookup, update, closed


def consume(queue, execute):
    return worker.consume_cleanse_once(
        queue,
        owner_id="worker-pod",
        parser_version="parser-v1",
        execute=execute,
        lease_seconds=60,
        max_wait=0.1,
        context=context(),
    )


def test_worker_authorizes_persists_then_acks_and_deduplicates(prepared):
    public, queue, lookup, _, closed = prepared
    execute = Mock(return_value=artifact())
    queue.ack.side_effect = lambda *args, **kwargs: (
        pytest.fail("ack preceded persistence")
        if public.inspect(lookup, context=context()).status != "completed"
        else None
    )
    assert consume(queue, execute)
    assert consume(queue, execute)
    execute.assert_called_once()
    assert callable(execute.call_args.kwargs["tick"])
    assert queue.ack.call_count == closed.call_count == 2


def test_revoked_permission_never_starts_parser(prepared):
    public, queue, lookup, update, _ = prepared
    update("cleanse_accounts", user_roles=[])
    execute = Mock()
    assert consume(queue, execute)
    execute.assert_not_called()
    assert public.inspect(lookup, context=context()).status == "failed"


def test_unknown_output_is_quarantined(prepared):
    public, queue, lookup, _, _ = prepared
    execute = Mock(side_effect=OutcomeUnknown())
    assert consume(queue, execute)
    state = public.inspect(lookup, context=context())
    assert state.status == "running" and public.ready(context=context()) == ()
    queue.ack.assert_called_once()


def test_wrong_queue_role_never_opens_ports(prepared):
    _, queue, _, _, closed = prepared
    queue.scope = StorageScope("runtime", "tenant-a", "worker", {"file-cleanse"})
    with pytest.raises(ScopeDenied):
        consume(queue, Mock())
    queue.consume.assert_not_called()
    closed.assert_not_called()


def test_cancel_during_execution_is_observed_by_parent_tick(prepared, mocker):
    public, queue, lookup, _, _ = prepared
    clock = [0]
    mocker.patch.object(
        worker,
        "CleanseLeaseGuard",
        side_effect=lambda *args, **kwargs: CleanseLeaseGuard(
            *args, **kwargs, clock=lambda: clock[0]
        ),
    )

    def execute(row, request, *, tick, context):
        public.cancel(lookup, context=context)
        clock[0] += 30
        tick(context=context)
        pytest.fail("cancelled parser continued")

    assert consume(queue, execute)
    assert public.inspect(lookup, context=context()).status == "cancelled"
    queue.ack.assert_called_once()


def test_default_parser_factory_defers_all_handles_until_child(mocker):
    objects = mocker.patch.object(worker, "bind_cleanse_objects")
    isolate = mocker.patch.object(worker, "ProcessCleanseExecutor")
    snapshot = {"tenant_id": "tenant-a", "user_id": "user-a", "parser_version": "v1"}
    request = knowledge_request()
    ctx = context()
    tick = Mock()
    worker.execute_cleanse(snapshot, request, tick=tick, context=ctx)
    isolate.call_args.kwargs["tick"](snapshot, context=ctx)
    tick.assert_called_once_with(context=ctx)
    objects.assert_not_called()
    child = isolate.call_args.args[0](context=ctx)
    assert not child.runtime.initialized
    objects.assert_called_once_with("tenant-a", "user-a", request.source, context=ctx)
    assert child.parser_version == "v1"
    child.close()
    objects.return_value.close.assert_called_once()


def test_worker_crash_after_dispatch_cannot_be_reclaimed_on_lease_expiry(
    prepared, setup
):
    public, queue, lookup, _, _ = prepared
    make, now = setup

    def execute(*args, **kwargs):
        admitted = public.records.query(
            DATASET, RecordQuery(), PageRequest(), context=context()
        ).items[0]
        assert admitted["reconcile_required"] is True
        raise SystemExit("controlled root crash")

    with pytest.raises(SystemExit):
        consume(queue, execute)
    row = public.records.query(
        DATASET, RecordQuery(), PageRequest(), context=context()
    ).items[0]
    now[0] = datetime.fromisoformat(row["lease_until"]) + timedelta(seconds=1)
    assert row["reconcile_required"] is True
    assert public.ready(context=context()) == ()
    assert (
        make("new-worker").claim(
            "new-root", job_id=lookup.job_id, lease_seconds=60, context=context()
        )
        is None
    )
    queue.retry.assert_called_once()
    queue.ack.assert_not_called()
