# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Container startup recovery for durable task states."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from time import monotonic
from uuid import uuid4

from contracts.knowledge import INTERRUPTED_UPLOADS
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    OperationContext,
    PageRequest,
    RecordQuery,
    Revision,
    Sort,
    WriteOutcome,
)

from infrastructure.source_upload import interrupted_upload_ports

logger = logging.getLogger(__name__)

UPLOAD_RECOVERY_GRACE_SECONDS = 30 * 60
_upload_cleanup_tasks: set[asyncio.Task] = set()


def recover_config_tasks() -> dict[str, int]:
    """Fail config-owned background work lost during process restart."""
    from management.db.evaluation.runs import (
        fail_interrupted_no_set_runs_on_startup,
        list_evaluation_tenant_ids,
        reap_stale_runs,
    )
    from management.db.evaluation.sets import (
        cleanup_orphaned_virtual_evaluation_sets,
        recover_interrupted_generations,
    )
    from management.db.memory.dreaming import recover_stale

    result = {
        "agent_evaluation_setups": fail_interrupted_no_set_runs_on_startup(),
        "agent_evaluations": sum(
            reap_stale_runs(tenant_id, timeout_minutes=0) for tenant_id in list_evaluation_tenant_ids()
        ),
        "evaluation_set_generations": recover_interrupted_generations(),
        "orphaned_virtual_sets": cleanup_orphaned_virtual_evaluation_sets(),
        "dreaming_runs": recover_stale(include_unexpired=True),
    }
    logger.info("Config startup recovery completed: %s", result)
    return result


def recover_northbound_tasks() -> dict[str, int]:
    """Fail protocol tasks owned by the previous northbound process."""
    from management.db.a2a.repository import fail_active_tasks_on_startup

    result = {"a2a_tasks": fail_active_tasks_on_startup()}
    logger.info("Northbound startup recovery completed: %s", result)
    return result


def _delete_interrupted_object(record):
    from contracts.constants import environment
    from contracts.knowledge import StorageObjectReference
    from nexent.storage.errors import NotFound, OutcomeUnknown, Unavailable
    from nexent.storage.models import ObjectRef

    from infrastructure.agentos_identity import ServicePrincipal
    from infrastructure.file_objects import file_object_ports
    from infrastructure.file_reads import file_read_ports
    from infrastructure.object_storage.read_access import normalize_object_location

    key, bucket = normalize_object_location(record["object_name"], record.get("bucket_name"))
    reference = StorageObjectReference(bucket or environment.MINIO_DEFAULT_BUCKET, key)
    actor = ServicePrincipal("upload-recovery", record["tenant_id"])
    context = OperationContext(f'upload-recovery-{uuid4().hex}', monotonic() + 10)
    ref = ObjectRef("files", reference.object_name)
    try:
        with file_object_ports(actor, reference, context=context) as store:
            receipt = store.delete(ref, context=context)
            if receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.deleted:
                raise OutcomeUnknown(operation_id=context.operation_id)
    except (OutcomeUnknown, Unavailable):
        # Preserve the existing post-failure presence check without replaying the delete.
        try:
            with file_read_ports(key, bucket=reference.bucket_name, context=context) as store:
                store.stat(ref, context=context)
        except NotFound:
            return
        raise


def _interrupted_uploads(cutoff, owner):
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    where = Comparison("create_time", "lt", cutoff.isoformat())
    after = None
    while True:
        selection = where if after is None else Junction("and", (where, after))
        context = OperationContext(f"upload-recovery-scan-{uuid4().hex}", monotonic() + 10)
        with interrupted_upload_ports(owner, context=context) as store:
            page = store.query(INTERRUPTED_UPLOADS, RecordQuery(
                where=selection, order_by=(Sort("create_time"), Sort("file_id")),
            ), PageRequest(), context=context)
        yield from page.items
        if page.next_cursor is None:
            return
        # Claiming a row removes it from this read scope, so resume by sort key rather than offset.
        last = page.items[-1]
        after = Junction("or", (
            Comparison("create_time", "gt", last["create_time"]),
            Junction("and", (Comparison("create_time", "eq", last["create_time"]),
                             Comparison("file_id", "gt", last["file_id"]))),
        ))


def _record_interrupted_upload(owner, record, status, revision, *, stage, code, message):
    context = OperationContext(f"upload-recovery-cas-{uuid4().hex}", monotonic() + 10)
    with interrupted_upload_ports(owner, record=record, expected_status=status, context=context) as store:
        return store.patch(INTERRUPTED_UPLOADS, record["file_id"], FieldPatch(set_values={
            "status": "FAILED", "stage": stage, "error_stage": stage, "error_code": code,
            "error_message": message, "failed_at": datetime.now(timezone.utc).isoformat(),
        }), expected=revision, context=context)


def fail_interrupted_uploads(cutoff: datetime, upload_owner_service: str) -> int:
    """Fail old uploads owned by a restarted service and remove partial objects."""
    failed = 0
    for record in _interrupted_uploads(cutoff, upload_owner_service):
        if record.get("stage") == "SOURCE_UPLOAD" or record.get("source_upload_sha256") or record.get("source_revision"):
            logger.warning("source_upload_reconciliation_pending file_id=%s", record["file_id"])
            continue
        claimed = _record_interrupted_upload(
            upload_owner_service, record, "UPLOADING", Revision(str(record["version"])),
            stage="UPLOAD", code="CONTAINER_RESTARTED", message="Upload was interrupted by a service restart",
        )
        if claimed.outcome is not WriteOutcome.CONFIRMED or not claimed.matched or claimed.revision is None:
            continue

        failed += 1
        try:
            if record.get("object_name"):
                _delete_interrupted_object(record)
        except Exception as exc:
            logger.warning(
                "Interrupted upload cleanup failed for file_id=%s: %s",
                record["file_id"],
                exc,
            )
            _record_interrupted_upload(
                upload_owner_service, record, "FAILED", claimed.revision,
                stage="UPLOAD_RECOVERY", code="UPLOAD_RECOVERY_FAILED", message=str(exc),
            )
    if failed:
        logger.info("Failed %d interrupted uploads created before %s", failed, cutoff)
    return failed


async def schedule_interrupted_upload_cleanup(upload_owner_service: str, *, thread_manager=None) -> asyncio.Task:
    """Clean this service's old uploads now and again after the grace period."""
    startup_time = datetime.utcnow()
    immediate_cutoff = startup_time - timedelta(seconds=UPLOAD_RECOVERY_GRACE_SECONDS)

    async def cleanup(cutoff):
        if thread_manager is None:
            await asyncio.to_thread(fail_interrupted_uploads, cutoff, upload_owner_service)
        else:
            from nexent.core.concurrency import ManagedTaskSpec

            await thread_manager.run(
                "control-io",
                ManagedTaskSpec(task_name="recover-interrupted-uploads", owner="management.recovery"),
                fail_interrupted_uploads, cutoff, upload_owner_service,
            )

    await cleanup(immediate_cutoff)

    async def _delayed_cleanup() -> None:
        await asyncio.sleep(UPLOAD_RECOVERY_GRACE_SECONDS)
        await cleanup(startup_time)

    task = asyncio.create_task(_delayed_cleanup())
    _upload_cleanup_tasks.add(task)
    task.add_done_callback(_upload_cleanup_tasks.discard)
    return task
