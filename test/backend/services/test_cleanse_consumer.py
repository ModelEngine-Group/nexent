# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Consumer stop/failures retain bounded acknowledgement and port ownership."""

from threading import Event
from unittest.mock import Mock

import pytest
from management.services.file.cleanse_consumer import serve
from nexent.storage.errors import InvalidInput, Unavailable
from nexent.storage.models import TaskEnvelope
from nexent.storage.queue import Delivery


def test_stop_after_dispatch_acknowledges_with_cleanup_budget():
    stop, queue, registry = Event(), Mock(), Mock()
    queue.consume.return_value = Delivery("receipt", TaskEnvelope("one", "handler", {}))
    registry.dispatch.side_effect = lambda *args, **kwargs: stop.set()
    serve(queue, registry, stop=stop)
    queue.ack.assert_called_once()
    cleanup = queue.ack.call_args.kwargs["context"]
    assert cleanup.cancelled is None and 0 < cleanup.remaining() <= 5
    queue.close.assert_called_once()
    queue.consume.assert_called_once()


def test_empty_poll_can_stop_and_close_without_dispatch():
    stop, queue, registry = Event(), Mock(), Mock()

    def consume(**kwargs):
        stop.set()

    queue.consume.side_effect = consume
    serve(queue, registry, stop=stop)
    registry.dispatch.assert_not_called()
    queue.close.assert_called_once()


def test_broker_failure_closes_and_propagates_without_busy_retry():
    queue = Mock()
    queue.consume.side_effect = Unavailable()
    with pytest.raises(Unavailable):
        serve(queue, Mock(), stop=Event())
    queue.consume.assert_called_once()
    queue.close.assert_called_once()


@pytest.mark.parametrize(
    "settings",
    [
        {"operation_seconds": 0},
        {"operation_seconds": float("inf")},
        {"poll_seconds": True},
        {"poll_seconds": 31},
    ],
)
def test_invalid_consumer_deadlines_reject_admission(settings):
    queue = Mock()
    with pytest.raises(InvalidInput):
        serve(queue, Mock(), stop=Event(), **settings)
    queue.consume.assert_not_called()
