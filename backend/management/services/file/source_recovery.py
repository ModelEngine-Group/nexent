# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded automatic source-identity reconciliation owned by Management lifespan."""

import asyncio
import logging
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from time import monotonic

from management.services.file.source_reconcile import SourceReconciler
from nexent.core.concurrency import ManagedTaskSpec
from nexent.core.concurrency.errors import ThreadManagerError
from nexent.storage.errors import StorageError
from nexent.storage.models import (
    Comparison,
    Junction,
    OperationContext,
    PageRequest,
    RecordQuery,
    Sort,
)

from infrastructure.rdb.source_candidates import DATASET, bind_source_candidates
from infrastructure.source_upload import source_engine, source_recovery_ports

logger = logging.getLogger(__name__)


def reconcile_sources(owner_service, *, context, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=300)
    engine = source_engine(context)
    candidates = None
    counts = {}
    try:
        candidates = bind_source_candidates(owner_service, engine)
        where = Junction(
            "and",
            (
                Comparison("source_upload_started_at", "lte", cutoff.isoformat()),
                Junction(
                    "or",
                    (
                        Comparison("source_reconcile_after", "is_null", True),
                        Comparison("source_reconcile_after", "lte", now.isoformat()),
                    ),
                ),
            ),
        )
        page = candidates.query(
            DATASET,
            RecordQuery(where=where, order_by=(Sort("source_upload_started_at"),)),
            PageRequest(limit=100),
            context=context,
        )
        for record in page.items:
            context.remaining()
            item = replace(context, deadline=min(context.deadline, monotonic() + 15))
            with source_recovery_ports(record, context=item) as (records, objects):
                result = SourceReconciler(
                    records, objects, clock=lambda: now
                ).reconcile(
                    record["file_id"],
                    owner_service=owner_service,
                    owner_user_id=record["created_by"],
                    expected_version=record["version"],
                    cutoff=cutoff,
                    context=item,
                )
            counts[result] = counts.get(result, 0) + 1
        return counts
    finally:
        try:
            if candidates is not None:
                candidates.close()
        finally:
            engine.dispose()


async def schedule_source_reconciliation(
    owner_service, *, thread_manager, interval_seconds=60
):
    """Return one lifespan-owned task; no unowned worker or implicit manager is created."""
    if (
        thread_manager is None
        or isinstance(interval_seconds, bool)
        or not isinstance(interval_seconds, (int, float))
        or not math.isfinite(interval_seconds)
        or not 0.01 <= interval_seconds <= 3600
    ):
        raise ValueError(
            "Expected an owned manager and bounded reconciliation interval"
        )

    async def run():
        while True:
            await asyncio.sleep(interval_seconds)
            deadline = monotonic() + 30

            def work(cancel_event, *, deadline=deadline):
                return reconcile_sources(
                    owner_service,
                    context=OperationContext(
                        "source-reconciliation", deadline, cancelled=cancel_event
                    ),
                )

            try:
                async with asyncio.timeout(30):
                    await thread_manager.run(
                        "file-upload",
                        ManagedTaskSpec(
                            task_name="reconcile-source-uploads",
                            owner="management.source-recovery",
                            deadline_monotonic=deadline,
                            pass_cancel_event=True,
                        ),
                        work,
                    )
            except (StorageError, ThreadManagerError, TimeoutError) as error:
                logger.warning(
                    "source_reconciliation_deferred error_type=%s", type(error).__name__
                )

    return asyncio.create_task(run(), name="source-reconciliation-" + owner_service)
