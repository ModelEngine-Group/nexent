# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Delivery contracts using real Kombu memory transport and a controlled KV port."""

from time import monotonic
from unittest.mock import Mock
from uuid import uuid4

import pytest
from nexent.storage.errors import Conflict, InvalidInput, NotFound, ScopeDenied
from nexent.storage.models import (
    KVEntry,
    Revision,
    StorageScope,
    TaskEnvelope,
    WriteReceipt,
)

from infrastructure.storage.work_queue import KombuWorkQueue, QueueBinding


def context():
    from nexent.storage.models import OperationContext

    return OperationContext("queue-test", monotonic() + 3)


class KV:
    def __init__(self, scope):
        self.scope = scope
        self.data = {}

    def get(self, key, *, context):
        return self.data.get(key)

    def put(self, key, value, *, ttl, context):
        self.data[key] = KVEntry(value, Revision(uuid4().hex))
        return WriteReceipt(context.operation_id, True)

    def compare_exchange(self, key, expected, value, *, ttl, context):
        if key in self.data:
            return WriteReceipt(context.operation_id, False)
        return self.put(key, value, ttl=ttl, context=context)


@pytest.fixture
def queue():
    namespace = "queue." + uuid4().hex
    scope = StorageScope("management", "tenant-a", "actor", {namespace})
    binding = QueueBinding(namespace, "memory://", {"management"}, {"cleanse"})
    queue = KombuWorkQueue(scope, binding, KV(scope))
    yield queue
    queue.close()


def task(value=1):
    return TaskEnvelope("job-1", "cleanse", {"value": value})


def test_enqueue_consume_ack(queue):
    queue.enqueue(task(), context=context())
    assert queue.inspect_delivery("job-1", context=context()).phase == "queued"
    delivery = queue.consume(max_wait=0.01, context=context())
    assert delivery.task == task()
    assert isinstance(delivery.receipt, str)
    queue.ack(delivery.receipt, context=context())
    assert queue.inspect_delivery("job-1", context=context()).phase == "acked"
    assert queue.consume(max_wait=0.01, context=context()) is None


def test_retry_requeues_and_invalidates_old_receipt(queue):
    queue.enqueue(task(), context=context())
    first = queue.consume(max_wait=0.01, context=context())
    queue.retry(first.receipt, context=context())
    second = queue.consume(max_wait=0.01, context=context())
    assert second.task == first.task and second.receipt != first.receipt
    with pytest.raises(NotFound):
        queue.ack(first.receipt, context=context())
    queue.ack(second.receipt, context=context())


def test_cancel_marker_survives_ack(queue):
    queue.enqueue(task(), context=context())
    queue.cancel_request("job-1", context=context())
    delivery = queue.consume(max_wait=0.01, context=context())
    queue.ack(delivery.receipt, context=context())
    state = queue.inspect_delivery("job-1", context=context())
    assert state.cancel_requested and state.phase == "acked"


def test_same_id_different_input_is_conflict(queue):
    queue.enqueue(task(), context=context())
    with pytest.raises(Conflict):
        queue.enqueue(task(2), context=context())


def test_unknown_handler_and_non_json_are_rejected(queue):
    for envelope in [
        TaskEnvelope("job", "unknown", {}),
        TaskEnvelope("job", "cleanse", {"x": object()}),
    ]:
        with pytest.raises(InvalidInput):
            queue.enqueue(envelope, context=context())


def test_prefetch_is_bounded_to_one_delivery(queue):
    queue.enqueue(task(), context=context())
    delivery = queue.consume(max_wait=0.01, context=context())
    with pytest.raises(Conflict):
        queue.consume(max_wait=0.01, context=context())
    queue.ack(delivery.receipt, context=context())


def test_metadata_scope_must_match(queue):
    scope = StorageScope("management", "tenant-b", "actor", queue.scope.namespaces)
    with pytest.raises(ScopeDenied):
        KombuWorkQueue(scope, queue._binding, queue._kv)


@pytest.mark.parametrize("value", [0, -1, 31, True, float("nan")])
def test_wait_is_bounded(queue, value):
    with pytest.raises(InvalidInput):
        queue.consume(max_wait=value, context=context())


def test_unknown_delivery_is_not_job_completion(queue):
    state = queue.inspect_delivery("unknown", context=context())
    assert state.phase == "unknown" and not state.cancel_requested


def test_publish_transport_failure_is_sanitized_and_not_replayed(queue, mocker):
    from nexent.storage.errors import OutcomeUnknown
    from redis.exceptions import ConnectionError

    connection = Mock()
    channel = connection.SimpleQueue.return_value
    channel.put.side_effect = ConnectionError("private-password-endpoint")
    queue._factory = Mock(return_value=connection)
    with pytest.raises(OutcomeUnknown) as error:
        queue.enqueue(task(), context=context())
    assert "private" not in str(error.value)
    channel.put.assert_called_once()
    channel.close.assert_called_once()
    connection.release.assert_called_once()
    assert connection.ensure_connection.call_args.kwargs["max_retries"] == 0


def test_failed_delivery_metadata_does_not_keep_an_unreachable_lease(queue, mocker):
    from nexent.storage.errors import Unavailable

    queue.enqueue(task(), context=context())
    mocker.patch.object(queue, "_state", side_effect=Unavailable())
    with pytest.raises(Unavailable):
        queue.consume(max_wait=0.01, context=context())
    assert queue._lease is None


def test_tenant_queues_are_distinct(queue):
    scope = StorageScope("management", "tenant-b", "actor", queue.scope.namespaces)
    other = KombuWorkQueue(scope, queue._binding, KV(scope))
    try:
        queue.enqueue(task(), context=context())
        assert other.consume(max_wait=0.01, context=context()) is None
        assert other.inspect_delivery("job-1", context=context()).phase == "unknown"
    finally:
        other.close()


def test_binding_repr_hides_broker_password():
    binding = QueueBinding(
        "queue",
        "redis://user:private-password@localhost/0",
        {"management"},
        {"cleanse"},
    )
    assert "private-password" not in repr(binding)


@pytest.mark.asyncio
async def test_event_loop_cannot_open_broker(queue):
    from nexent.storage.errors import CapabilityUnsupported

    with pytest.raises(CapabilityUnsupported):
        queue.enqueue(task(), context=context())
