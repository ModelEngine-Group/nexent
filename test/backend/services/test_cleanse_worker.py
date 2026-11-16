# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Worker dispatch acknowledges only after durable job policy has run."""

from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import FileCleanseLookup
from management.services.file.cleanse_worker import (
    HANDLER,
    CleanseHandler,
    HandlerRegistry,
    consume_once,
    enqueue_ready,
)
from nexent.storage.errors import InvalidInput, OutcomeUnknown
from nexent.storage.models import TaskEnvelope
from nexent.storage.queue import Delivery

from test.backend.services.test_cleanse_jobs import artifact, context, request
from test.backend.services.test_cleanse_jobs import (
    setup as setup,  # noqa: PLC0414 - Re-export pytest fixture.
)


def task(state):
    return TaskEnvelope(state.job_id, HANDLER, {"job_id": state.job_id})


def test_dispatch_persists_completion_before_ack_and_deduplicates(setup):
    make, _ = setup
    public = make()
    state = public.submit(request(), context=context())
    execute = Mock(return_value=artifact())
    authorize = Mock()
    handler = CleanseHandler(
        make("worker"),
        owner_id="worker-pod",
        lease_seconds=60,
        authorize_execution=authorize,
        execute=execute,
    )
    registry = HandlerRegistry({HANDLER: handler})
    queue = Mock()
    queue.consume.return_value = Delivery("receipt", task(state))

    def acknowledged(*args, **kwargs):
        assert (
            public.inspect(
                FileCleanseLookup(job_id=state.job_id, run_id=state.run_id),
                context=context(),
            ).status
            == "completed"
        )

    queue.ack.side_effect = acknowledged
    assert consume_once(queue, registry, max_wait=0.1, context=context())
    assert consume_once(queue, registry, max_wait=0.1, context=context())
    execute.assert_called_once()
    assert authorize.call_args.args[0]["user_id"] == "user-a"
    assert queue.ack.call_count == 2


@pytest.mark.parametrize(
    "failure", [PermissionError("private"), RuntimeError("private"), None]
)
def test_handler_failure_is_sanitized(setup, failure):
    make, _ = setup
    jobs = make()
    state = jobs.submit(request(), context=context())
    execute = Mock(side_effect=failure) if failure else Mock(return_value=None)
    handler = CleanseHandler(
        make("worker"),
        owner_id="worker",
        lease_seconds=60,
        authorize_execution=Mock(),
        execute=execute,
    )
    handler(task(state), context=context())
    result = jobs.inspect(
        FileCleanseLookup(job_id=state.job_id, run_id=state.run_id), context=context()
    )
    assert result.status == "failed" and result.error_code == "CLEANSE_FAILED"
    assert "private" not in result.model_dump_json()


def test_unknown_publication_blocks_automatic_rescheduling(setup):
    make, _ = setup
    jobs = make()
    state = jobs.submit(request(), context=context())
    handler = CleanseHandler(
        make("worker"),
        owner_id="worker",
        lease_seconds=60,
        authorize_execution=Mock(),
        execute=Mock(side_effect=OutcomeUnknown()),
    )
    handler(task(state), context=context())
    queue = Mock()
    assert enqueue_ready(jobs, queue, context=context()) == 0
    queue.enqueue.assert_not_called()


def test_ready_submission_uses_only_job_reference(setup):
    make, _ = setup
    jobs = make()
    state = jobs.submit(request(), context=context())
    queue = Mock()
    assert enqueue_ready(jobs, queue, context=context()) == 1
    assert queue.enqueue.call_args.args[0] == task(state)


def test_unknown_registry_handler_requeues_instead_of_ack():
    queue = Mock()
    queue.consume.return_value = Delivery("receipt", TaskEnvelope("job", "unknown", {}))
    with pytest.raises(InvalidInput):
        consume_once(
            queue, HandlerRegistry({HANDLER: Mock()}), max_wait=0.1, context=context()
        )
    queue.retry.assert_called_once()
    queue.ack.assert_not_called()


def test_empty_queue_does_not_dispatch():
    queue = Mock()
    queue.consume.return_value = None
    callback = Mock()
    assert not consume_once(
        queue, HandlerRegistry({HANDLER: callback}), max_wait=0.1, context=context()
    )
    callback.assert_not_called()
