# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Worker roots close discovery before parsing and bound every dispatch attempt."""

from contextlib import contextmanager
from threading import Event
from unittest.mock import Mock

import pytest
from management.services.file import cleanse_root as root
from nexent.storage.errors import InvalidInput, Unavailable


@pytest.fixture
def cycle(mocker):
    events = []
    records = Mock()
    records.query.return_value.items = (
        {"job_id": "a" * 32, "tenant_id": "tenant-a"},
        {"job_id": "b" * 32, "tenant_id": "tenant-b"},
    )

    @contextmanager
    def discovery(*, context):
        yield records
        events.append("discovery-closed")

    queues = []

    @contextmanager
    def queue(tenant, owner, *, context):
        assert "discovery-closed" in events
        value = Mock()
        queues.append((tenant, value, context))
        try:
            yield value
        finally:
            events.append(tenant + "-closed")

    mocker.patch.object(root, "cleanse_dispatch_ports", discovery)
    mocker.patch.object(root, "knowledge_cleanse_queue", queue)
    consume = mocker.patch.object(root, "consume_cleanse_once", return_value=True)
    return records, queues, consume, events


def test_dispatch_scopes_each_tenant_and_uses_separate_finite_budget(cycle):
    records, queues, consume, events = cycle
    execute = Mock()
    result = root.dispatch_ready(
        owner_id="worker",
        parser_version="v1",
        stop=Event(),
        operation_seconds=30,
        execute=execute,
    )
    assert result == {"enqueued": 2, "consumed": 2}
    assert [item[0] for item in queues] == ["tenant-a", "tenant-b"]
    assert queues[0][2].operation_id != queues[1][2].operation_id
    assert all(0 < item[2].remaining() <= 30 for item in queues)
    assert consume.call_args.kwargs["execute"] is execute
    assert events == ["discovery-closed", "tenant-a-closed", "tenant-b-closed"]
    assert records.query.call_args.args[2].limit == 100
    assert queues[0][1].enqueue.call_args.args[0].arguments == {"job_id": "a" * 32}


def test_stop_after_enqueue_does_not_start_another_parser(cycle):
    _, queues, consume, events = cycle
    stop = Event()
    consume.side_effect = lambda *args, **kwargs: stop.set()
    assert (
        root.dispatch_ready(owner_id="worker", parser_version="v1", stop=stop)[
            "enqueued"
        ]
        == 1
    )
    assert len(queues) == 1 and events[-1] == "tenant-a-closed"


@pytest.mark.parametrize("seconds", [True, 0, 3601, float("nan")])
def test_invalid_execution_budget_never_scans(cycle, seconds):
    records, _, _, _ = cycle
    with pytest.raises(InvalidInput):
        root.dispatch_ready(
            owner_id="worker",
            parser_version="v1",
            stop=Event(),
            operation_seconds=seconds,
        )
    records.query.assert_not_called()


def test_fenced_parser_root_does_not_discover_or_consume_more_work(cycle, mocker):
    records, queues, consume, _ = cycle
    mocker.patch.object(root, "ensure_isolation_available", side_effect=Unavailable())
    with pytest.raises(Unavailable):
        root.dispatch_ready(owner_id="worker", parser_version="v1", stop=Event())
    records.query.assert_not_called()
    assert queues == []
    consume.assert_not_called()


def test_storage_error_exits_without_retry(mocker):
    stop = Event()
    wait = mocker.patch.object(stop, "wait")
    dispatch = mocker.patch.object(root, "dispatch_ready", side_effect=Unavailable())
    with pytest.raises(Unavailable):
        root.serve(stop, owner_id="worker", parser_version="v1", poll_seconds=0.1)
    dispatch.assert_called_once()
    wait.assert_not_called()
