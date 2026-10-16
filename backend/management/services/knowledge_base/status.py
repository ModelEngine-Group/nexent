# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Knowledge file processing task status projection."""

import logging
import time
import traceback

import httpx
from consts.const import DATA_PROCESS_SERVICE

logger = logging.getLogger(__name__)


async def get_all_files_status(index_name: str):
    """
    Get status for all files according to index_name, matching corresponding tasks,
    and then convert to custom state

    Args:
        index_name: Index name to filter tasks

    Returns:
        Dictionary with path_or_url as keys and dict values: {state, latest_task_id}
    """
    start_time = time.time()
    try:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{DATA_PROCESS_SERVICE}/tasks/indices/{index_name}", timeout=10.0
                )
            http_duration = time.time() - start_time
            logger.info(
                f"[get_all_files_status] HTTP request to {DATA_PROCESS_SERVICE}/tasks/indices/{index_name} "
                f"completed in {http_duration:.3f}s, status={response.status_code}"
            )
            if response.status_code == 200:
                tasks_list = response.json()
            else:
                logger.error(
                    f"Error from data process service: {response.status_code} - {response.text}"
                )
                return {}
        except Exception as e:
            logger.error(f"Failed to connect to data process service: {str(e)}")
            return {}

        logging.debug(f"Found {len(tasks_list)} tasks for index '{index_name}'")
        if not tasks_list:
            logger.warning(f"No tasks found for index '{index_name}'")
            return {}

        # Dictionary to store file statuses:
        # {path_or_url: {process_state, forward_state, timestamps, progress fields}}
        file_states = {}
        for task_info in tasks_list:
            # No need to check index_name since get_index_tasks already filters by it
            task_path_or_url = task_info.get("path_or_url", "")
            task_name = task_info.get("task_name", "")
            task_status = task_info.get("status", "")
            task_created_at = task_info.get("created_at", 0)
            task_id = task_info.get("id", "")
            original_filename = task_info.get("original_filename", "")
            source_type = task_info.get("source_type", "")
            if task_path_or_url:
                # Initialize file state if not exists
                if task_path_or_url not in file_states:
                    file_states[task_path_or_url] = {
                        "process_state": "",
                        "forward_state": "",
                        "latest_process_created_at": 0,
                        "latest_forward_created_at": 0,
                        "created_at": 0,
                        "latest_task_id": "",
                        "original_filename": "",
                        "source_type": "",
                        # Optional progress fields provided by data-process service
                        "processed_chunks": None,
                        "total_chunks": None,
                    }
                file_state = file_states[task_path_or_url]
                # Process task
                if (
                    task_name == "process"
                    and task_created_at > file_state["latest_process_created_at"]
                ):
                    file_state["latest_process_created_at"] = task_created_at
                    file_state["process_state"] = task_status
                    file_state["latest_task_id"] = task_id
                    file_state["original_filename"] = original_filename
                    file_state["source_type"] = source_type
                    file_state["created_at"] = task_created_at
                    # Update optional progress metrics if present
                    file_state["processed_chunks"] = task_info.get(
                        "processed_chunks", file_state.get("processed_chunks")
                    )
                    file_state["total_chunks"] = task_info.get(
                        "total_chunks", file_state.get("total_chunks")
                    )
                # Forward task
                elif (
                    task_name == "forward"
                    and task_created_at > file_state["latest_forward_created_at"]
                ):
                    file_state["latest_forward_created_at"] = task_created_at
                    file_state["forward_state"] = task_status
                    file_state["latest_task_id"] = task_id
                    file_state["original_filename"] = original_filename
                    file_state["source_type"] = source_type
                    file_state["created_at"] = max(
                        file_state.get("created_at", 0), task_created_at
                    )
                    # Forward tasks may also carry progress metrics
                    file_state["processed_chunks"] = task_info.get(
                        "processed_chunks", file_state.get("processed_chunks")
                    )
                    file_state["total_chunks"] = task_info.get(
                        "total_chunks", file_state.get("total_chunks")
                    )
        result = {}
        # Use local fallback logic for state conversion (avoiding HTTP call to external service)
        # The conversion logic is simple and can be done locally
        step_local_start = time.time()

        # Batch fetch progress info from Redis for all task_ids (single round-trip)
        redis_progress_batch = {}
        if file_states:
            try:
                from services.redis_service import get_redis_service

                redis_service = get_redis_service()
                all_task_ids = [
                    fs.get("latest_task_id", "") for fs in file_states.values()
                ]
                all_task_ids = [tid for tid in all_task_ids if tid]
                if all_task_ids:
                    redis_progress_batch = (
                        redis_service.batch_get_progress_info(all_task_ids) or {}
                    )
            except Exception as e:
                logger.debug(f"Failed to batch get Redis progress info: {e}")

        for path_or_url, file_state in file_states.items():
            custom_state = _convert_to_custom_state_local(
                process_celery_state=file_state["process_state"] or "",
                forward_celery_state=file_state["forward_state"] or "",
            )

            # Get progress from pre-fetched batch Redis data
            processed_chunks = file_state.get("processed_chunks")
            total_chunks = file_state.get("total_chunks")
            task_id = file_state["latest_task_id"] or ""

            # Use pre-fetched batch Redis data for progress
            if task_id and task_id in redis_progress_batch:
                progress_info = redis_progress_batch.get(task_id)
                if progress_info:
                    redis_processed = progress_info.get("processed_chunks")
                    redis_total = progress_info.get("total_chunks")
                    if redis_processed is not None:
                        processed_chunks = redis_processed
                    if redis_total is not None:
                        total_chunks = redis_total
                    logger.debug(
                        f"Retrieved progress from batch Redis for task {task_id}: {processed_chunks}/{total_chunks}"
                    )

            result[path_or_url] = {
                "state": custom_state,
                "latest_task_id": task_id,
                "original_filename": file_state["original_filename"] or "",
                "source_type": file_state["source_type"] or "",
                "created_at": file_state.get("created_at", 0),
                # Expose optional progress metrics for downstream consumers
                "processed_chunks": processed_chunks,
                "total_chunks": total_chunks,
            }
        step_local_duration = time.time() - step_local_start
        logger.info(
            f"[get_all_files_status] Local processing: {len(result)} files in {step_local_duration:.3f}s"
        )
        total_duration = time.time() - start_time
        logger.info(
            f"[get_all_files_status] Complete: {len(result)} files processed in {total_duration:.3f}s"
        )
        return result
    except Exception as e:
        logger.error(
            f"Error getting all files status for index {index_name}, details: {str(e)} {traceback.format_exc()}"
        )
        return {}


def _convert_to_custom_state_local(
    process_celery_state: str, forward_celery_state: str
) -> str:
    """
    Local state conversion logic - handles all known Celery states.
    Returns "UNKNOWN" only if the states are not recognized.
    """
    success = "SUCCESS"
    failure = "FAILURE"
    pending = "PENDING"
    started = "STARTED"
    unknown = "UNKNOWN"

    if process_celery_state == failure:
        return "PROCESS_FAILED"
    if forward_celery_state == failure:
        return "FORWARD_FAILED"
    if process_celery_state == success and forward_celery_state == success:
        return "COMPLETED"
    if not process_celery_state and not forward_celery_state:
        return "WAIT_FOR_PROCESSING"

    # Check if states are known Celery states
    known_states = {success, failure, pending, started, ""}
    if (
        process_celery_state not in known_states
        or forward_celery_state not in known_states
    ):
        return unknown

    forward_state_map = {
        pending: "WAIT_FOR_FORWARDING",
        started: "FORWARDING",
        success: "COMPLETED",
        failure: "FORWARD_FAILED",
    }
    process_state_map = {
        pending: "WAIT_FOR_PROCESSING",
        started: "PROCESSING",
        success: "WAIT_FOR_FORWARDING",
        failure: "PROCESS_FAILED",
    }

    if forward_celery_state:
        return forward_state_map.get(forward_celery_state, "WAIT_FOR_FORWARDING")
    if process_celery_state:
        return process_state_map.get(process_celery_state, "WAIT_FOR_PROCESSING")
    return "WAIT_FOR_PROCESSING"
