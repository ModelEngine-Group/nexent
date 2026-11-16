# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Synchronous single-owner consumption; the worker root owns process restart."""

import math
from time import monotonic
from uuid import uuid4

from management.services.file.cleanse_worker import consume_once
from nexent.storage.errors import InvalidInput, OperationCancelled
from nexent.storage.models import OperationContext


def serve(queue, registry, *, stop, operation_seconds=300, poll_seconds=1):
    if (
        isinstance(operation_seconds, bool)
        or not isinstance(operation_seconds, (int, float))
        or not math.isfinite(operation_seconds)
        or not 1 <= operation_seconds <= 3600
        or isinstance(poll_seconds, bool)
        or not isinstance(poll_seconds, (int, float))
        or not math.isfinite(poll_seconds)
        or not 0 < poll_seconds <= 30
    ):
        raise InvalidInput()
    try:
        while not stop.is_set():
            context = OperationContext(
                "cleanse-" + uuid4().hex,
                monotonic() + operation_seconds,
                cancelled=stop,
            )
            try:
                consume_once(
                    queue,
                    registry,
                    max_wait=min(poll_seconds, operation_seconds),
                    context=context,
                )
            except OperationCancelled:
                if not stop.is_set():
                    raise
    finally:
        queue.close()
