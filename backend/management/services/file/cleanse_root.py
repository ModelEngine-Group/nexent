# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Single-thread worker root; all parser forks occur outside the API process."""

import math
import multiprocessing
import signal
from datetime import datetime, timezone
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.knowledge_cleanse import CLEANSE_DISPATCH_DATASET, CLEANSE_HANDLER
from management.services.file.knowledge_cleanse_worker import (
    consume_knowledge_once,
    execute_knowledge_cleanse,
)
from nexent.storage.errors import InvalidInput, OperationCancelled
from nexent.storage.models import (
    Comparison,
    Junction,
    OperationContext,
    PageRequest,
    RecordQuery,
    Sort,
    TaskEnvelope,
)

from infrastructure.file_processing.isolated import ensure_isolation_available
from infrastructure.knowledge_cleanse import (
    cleanse_dispatch_ports,
    knowledge_cleanse_queue,
)


def _seconds(value, minimum, maximum):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not minimum <= value <= maximum
    ):
        raise InvalidInput()


def _parameters(owner_id, parser_version, operation_seconds):
    _seconds(operation_seconds, 1, 3600)
    if any(
        not isinstance(value, str) or not value.strip() or len(value) > maximum
        for value, maximum in ((owner_id, 100), (parser_version, 128))
    ):
        raise InvalidInput()


def dispatch_ready(
    *,
    owner_id,
    parser_version,
    stop,
    operation_seconds=300,
    execute=execute_knowledge_cleanse,
):
    _parameters(owner_id, parser_version, operation_seconds)
    if not callable(execute):
        raise InvalidInput()
    ensure_isolation_available()
    discovery = OperationContext(
        "cleanse-discovery-" + uuid4().hex, monotonic() + 10, cancelled=stop
    )
    now = datetime.now(timezone.utc).isoformat()
    with cleanse_dispatch_ports(context=discovery) as records:
        candidates = records.query(
            CLEANSE_DISPATCH_DATASET,
            RecordQuery(
                where=Junction(
                    "or",
                    (
                        Comparison("status", "eq", "queued"),
                        Junction(
                            "and",
                            (
                                Comparison("status", "eq", "running"),
                                Comparison("lease_until", "lte", now),
                            ),
                        ),
                    ),
                ),
                order_by=(Sort("update_time"),),
            ),
            PageRequest(limit=100),
            context=discovery,
        ).items
    result = {"enqueued": 0, "consumed": 0}
    for row in candidates:
        if stop.is_set():
            break
        ensure_isolation_available()
        context = OperationContext(
            "cleanse-job-" + uuid4().hex,
            monotonic() + operation_seconds,
            cancelled=stop,
        )
        with knowledge_cleanse_queue(
            row["tenant_id"], owner_id, context=context
        ) as queue:
            queue.enqueue(
                TaskEnvelope(row["job_id"], CLEANSE_HANDLER, {"job_id": row["job_id"]}),
                context=context,
            )
            result["enqueued"] += 1
            consumed = consume_knowledge_once(
                queue,
                owner_id=owner_id,
                parser_version=parser_version,
                execute=execute,
                lease_seconds=300,
                max_wait=1,
                context=context,
            )
            result["consumed"] += bool(consumed)
    return result


def serve(
    stop,
    *,
    owner_id,
    parser_version,
    operation_seconds=300,
    poll_seconds=1,
    execute=execute_knowledge_cleanse,
):
    _parameters(owner_id, parser_version, operation_seconds)
    _seconds(poll_seconds, 0.01, 30)
    while not stop.is_set():
        try:
            dispatch_ready(
                owner_id=owner_id,
                parser_version=parser_version,
                stop=stop,
                operation_seconds=operation_seconds,
                execute=execute,
            )
        except OperationCancelled:
            if not stop.is_set():
                raise
        if not stop.is_set():
            stop.wait(poll_seconds)


def main():
    from contracts.constants.environment import APP_VERSION
    from nexent.storage.errors import CapabilityUnsupported

    if "fork" not in multiprocessing.get_all_start_methods():
        raise CapabilityUnsupported()
    stop = Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    serve(
        stop,
        owner_id="cleanse-root-" + uuid4().hex,
        parser_version=APP_VERSION + "-cleanse-v1",
    )


if __name__ == "__main__":
    main()
