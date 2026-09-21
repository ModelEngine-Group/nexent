"""Container startup recovery for durable task states."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

UPLOAD_RECOVERY_GRACE_SECONDS = 30 * 60
_upload_cleanup_tasks: set[asyncio.Task] = set()


def recover_runtime_tasks() -> dict[str, int]:
    """Fail work that was owned by the previous runtime process."""
    from database.agent_automation_db import (
        recover_orphaned_runs,
        release_all_task_locks,
    )
    from database.agent_evaluation_db import (
        list_evaluation_tenant_ids,
        reap_stale_runs,
    )
    from database.conversation_db import fail_streaming_assistant_messages
    from services.runtime_state_service import runtime_state_service

    messages = fail_streaming_assistant_messages()
    for message in messages:
        user_id = message.get("user_id")
        if user_id:
            runtime_state_service.mark_run_finished(
                str(user_id), int(message["conversation_id"]), "failed"
            )
            runtime_state_service.mark_stream_completed(
                str(user_id), int(message["conversation_id"]), "failed"
            )

    evaluations = 0
    for tenant_id in list_evaluation_tenant_ids():
        evaluations += reap_stale_runs(tenant_id, timeout_minutes=0)

    result = {
        "conversation_messages": len(messages),
        "agent_evaluations": evaluations,
        "automation_runs": recover_orphaned_runs(),
        "automation_locks": release_all_task_locks(),
    }
    logger.info("Runtime startup recovery completed: %s", result)
    return result


def recover_config_tasks() -> dict[str, int]:
    """Fail config-owned background work lost during process restart."""
    from database.agent_evaluation_db import fail_interrupted_no_set_runs_on_startup
    from database.evaluation_set_db import (
        cleanup_orphaned_virtual_evaluation_sets,
        recover_interrupted_generations,
    )
    from database.model_management_db import fail_detecting_models_on_startup
    from database.memory_dreaming_db import recover_stale

    result = {
        "agent_evaluation_setups": fail_interrupted_no_set_runs_on_startup(),
        "evaluation_set_generations": recover_interrupted_generations(),
        "orphaned_virtual_sets": cleanup_orphaned_virtual_evaluation_sets(),
        "model_connectivity_checks": fail_detecting_models_on_startup(),
        "dreaming_runs": recover_stale(include_unexpired=True),
    }
    logger.info("Config startup recovery completed: %s", result)
    return result


def recover_data_process_tasks() -> dict[str, int]:
    """Fail tasks that had started in the previous data-process worker set."""
    from database.knowledge_file_lifecycle_db import fail_interrupted_file_tasks
    from services.redis_service import get_redis_service

    records = fail_interrupted_file_tasks()
    task_ids = {
        str(task_id)
        for record in records
        for task_id in (
            record.get("process_task_id"),
            record.get("forward_task_id"),
            record.get("parent_task_id"),
        )
        if task_id
    }
    redis_service = get_redis_service()
    canceled = sum(redis_service.mark_task_cancelled(task_id) for task_id in task_ids)
    result = {"knowledge_files": len(records), "cancel_markers": int(canceled)}
    logger.info("Data-process startup recovery completed: %s", result)
    return result


def recover_northbound_tasks() -> dict[str, int]:
    """Fail protocol tasks owned by the previous northbound process."""
    from database.a2a_agent_db import fail_active_tasks_on_startup

    result = {"a2a_tasks": fail_active_tasks_on_startup()}
    logger.info("Northbound startup recovery completed: %s", result)
    return result


def fail_interrupted_uploads(cutoff: datetime, upload_owner_service: str) -> int:
    """Fail old uploads owned by a restarted service and remove partial objects."""
    from database.attachment_db import delete_file
    from database.client import minio_client
    from database.knowledge_file_lifecycle_db import (
        list_uploading_files_created_before,
        transition_file_record,
    )

    failed = 0
    for record in list_uploading_files_created_before(
        cutoff,
        upload_owner_service,
    ):
        claimed = transition_file_record(
            record["file_id"],
            status="FAILED",
            stage="UPLOAD",
            expected_statuses=("UPLOADING",),
            expected_version=record.get("version"),
            error_code="CONTAINER_RESTARTED",
            error_message="Upload was interrupted by a service restart",
            error_stage="UPLOAD",
            failed_at=datetime.utcnow(),
        )
        if not claimed:
            continue

        failed += 1
        object_name = record.get("object_name")
        bucket_name = record.get("bucket_name")
        try:
            if object_name:
                delete_result = delete_file(object_name, bucket_name)
                if not delete_result.get("success") and minio_client.file_exists(
                    object_name, bucket_name
                ):
                    raise RuntimeError(
                        delete_result.get("error") or "Failed to delete upload object"
                    )
        except Exception as exc:
            logger.warning(
                "Interrupted upload cleanup failed for file_id=%s: %s",
                record["file_id"],
                exc,
            )
            transition_file_record(
                record["file_id"],
                status="FAILED",
                stage="UPLOAD_RECOVERY",
                expected_statuses=("FAILED",),
                expected_version=claimed.get("version"),
                error_code="UPLOAD_RECOVERY_FAILED",
                error_message=str(exc),
                error_stage="UPLOAD_RECOVERY",
                failed_at=datetime.utcnow(),
            )
    if failed:
        logger.info("Failed %d interrupted uploads created before %s", failed, cutoff)
    return failed


async def schedule_interrupted_upload_cleanup(upload_owner_service: str) -> None:
    """Clean this service's old uploads now and again after the grace period."""
    startup_time = datetime.utcnow()
    immediate_cutoff = startup_time - timedelta(seconds=UPLOAD_RECOVERY_GRACE_SECONDS)
    await asyncio.to_thread(
        fail_interrupted_uploads,
        immediate_cutoff,
        upload_owner_service,
    )

    async def _delayed_cleanup() -> None:
        await asyncio.sleep(UPLOAD_RECOVERY_GRACE_SECONDS)
        await asyncio.to_thread(
            fail_interrupted_uploads,
            startup_time,
            upload_owner_service,
        )

    task = asyncio.create_task(_delayed_cleanup())
    _upload_cleanup_tasks.add(task)
    task.add_done_callback(_upload_cleanup_tasks.discard)
