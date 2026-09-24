"""
Utility functions for Celery tasks
"""
import asyncio
import json
import logging
import time
from typing import Any

import redis
from celery.result import AsyncResult

from .app import app as celery_app


logger = logging.getLogger("data_process.utils")


class DocumentDeleteRequested(RuntimeError):
    """Raised when processing reaches a document with an active delete fence."""


def update_file_lifecycle(
    *,
    file_id: str | None,
    tenant_id: str | None,
    index_name: str | None,
    source: str | None,
    status: str | None,
    stage: str,
    task_id: str | None = None,
    updated_by: str | None = None,
    **fields: Any,
) -> None:
    """Best-effort lifecycle transition shared by parser and forward tasks."""
    if not index_name:
        return
    try:
        from database.knowledge_file_lifecycle_db import (
            get_file_record,
            transition_file_record,
        )

        record = None
        if file_id and tenant_id:
            record = get_file_record(
                file_id=file_id,
                tenant_id=tenant_id,
                index_name=index_name,
                include_hidden=True,
            )
        if not record and source:
            record = get_file_record(
                tenant_id=tenant_id,
                index_name=index_name,
                object_name=source,
                include_hidden=True,
            )
        if not record or record.get("status") in {"DELETE_REQUESTED", "DELETED"}:
            return
        transition_file_record(
            record["file_id"],
            status=status,
            stage=stage,
            expected_statuses=(record.get("status"),),
            updated_by=updated_by,
            **fields,
        )
    except Exception:
        logger.warning(
            "File lifecycle update failed task_id=%s index=%s source=%s",
            task_id,
            index_name,
            source,
            exc_info=True,
        )


def is_document_delete_requested(
    *,
    index_name: str | None,
    source: str | None,
    file_id: str | None = None,
    tenant_id: str | None = None,
) -> bool:
    """Read the Redis deletion fence and fall back to the lifecycle row on Redis errors."""
    if not file_id:
        return False

    try:
        from services.redis_service import get_redis_service

        # A healthy Redis miss is the normal path. Query PostgreSQL only when
        # Redis is unavailable so regular processing does not add a DB read.
        return bool(get_redis_service().is_document_delete_requested(file_id=file_id))
    except Exception as redis_exc:
        logger.warning(
            "Deletion fence lookup failed for index=%s source=%s file_id=%s: %s",
            index_name,
            source,
            file_id,
            redis_exc,
        )

    try:
        from database.knowledge_file_lifecycle_db import get_file_record

        record = get_file_record(
            file_id=file_id,
            tenant_id=tenant_id,
            index_name=index_name,
            include_hidden=True,
        )
        return bool(record and str(record.get("status") or "").upper() in {"DELETE_REQUESTED", "DELETED"})
    except Exception as lifecycle_exc:
        # Keep deployments without the lifecycle migration compatible with the
        # legacy behavior: an unavailable fallback must not cancel work.
        logger.debug(
            "Durable deletion status lookup unavailable for index=%s source=%s file_id=%s: %s",
            index_name,
            source,
            file_id,
            lifecycle_exc,
        )
        return False


def ensure_document_not_deleted(
    *,
    index_name: str | None,
    source: str | None,
    file_id: str | None = None,
    tenant_id: str | None = None,
) -> None:
    """Raise a chain-aware exception when deletion wins a processing race."""
    if is_document_delete_requested(
        index_name=index_name,
        source=source,
        file_id=file_id,
        tenant_id=tenant_id,
    ):
        raise DocumentDeleteRequested(
            f"Document deletion requested for index={index_name}, source={source}, file_id={file_id}"
        )


def _parse_failure_info(info: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Parse Celery failure metadata as structured JSON or plain error text."""
    if isinstance(info, dict):
        return info, None
    if info is None:
        return None, None

    info_text = str(info).strip()
    if not info_text:
        return None, None

    try:
        parsed_info = json.loads(info_text)
    except (json.JSONDecodeError, TypeError):
        return None, info_text

    if isinstance(parsed_info, dict):
        return parsed_info, None
    return None, info_text


def get_all_task_ids_from_redis(redis_client: redis.Redis) -> list[str]:
    """
    Get all task IDs from Redis backend

    Returns:
        List of task IDs found in Redis
    """
    task_ids = []
    try:
        # Get all keys matching Celery result pattern
        for key in redis_client.scan_iter(
                match='celery-task-meta-*', count=500):
            if isinstance(key, bytes):
                key = key.decode('utf-8')

            # Extract task ID from key format: celery-task-meta-<task_id>
            if key.startswith('celery-task-meta-'):
                task_id = key.replace('celery-task-meta-', '')
                task_ids.append(task_id)

        logger.debug(f"Found {len(task_ids)} task IDs in Redis")
    except Exception as e:
        logger.warning(f"Failed to get task IDs from Redis: {e!s}")

    return task_ids


async def get_task_info(task_id: str) -> dict[str, Any]:
    """
    Get task status and metadata

    Args:
        task_id: Celery task ID

    Returns:
        Task status information
    """
    loop = asyncio.get_running_loop()

    def sync_get():
        result = AsyncResult(task_id, app=celery_app)

        # Get current time for updated_at if not available
        current_time = time.time()

        # Construct basic status information
        status_info = {
            'id': task_id,
            'index_name': '',
            'task_name': '',
            'path_or_url': '',
            'original_filename': '',
            'file_id': None,
            'status': result.status if result.status else 'PENDING',
            'created_at': current_time,
            'updated_at': current_time,
            'error': None
        }

        # Check if result backend is available
        backend_available = True
        try:
            status = result.status
            if status:
                status_info['status'] = status
        except AttributeError as e:
            if 'DisabledBackend' in str(e):
                logger.warning(
                    f"Result backend is disabled for task {task_id}: {e!s}")
                backend_available = False
                status_info['error'] = "Result backend disabled - cannot retrieve task status"
            else:
                logger.warning(f"Backend error for task {task_id}: {e!s}")
                backend_available = False
                status_info['error'] = f"Backend error: {e!s}"
        except Exception as e:
            logger.warning(
                f"Error accessing task status for {task_id}: {e!s}")
            backend_available = False
            status_info['error'] = f"Status access error: {e!s}"

        # If backend is available, try to get metadata
        if backend_available:
            try:
                # Add metadata from task state
                if result.info:
                    if isinstance(result.info, dict):
                        # For successful tasks, the result may contain metadata
                        metadata = result.info

                        # Get task_name from metadata if available
                        if 'task_name' in metadata:
                            status_info['task_name'] = metadata['task_name']

                        # Add timestamps if available
                        if 'start_time' in metadata:
                            status_info['created_at'] = metadata['start_time']

                        # Extract index_name from metadata
                        if 'index_name' in metadata:
                            status_info['index_name'] = metadata['index_name']

                        if 'source' in metadata:
                            status_info['path_or_url'] = metadata['source']

                        if 'original_filename' in metadata:
                            status_info['original_filename'] = metadata['original_filename']

                        if 'file_id' in metadata:
                            status_info['file_id'] = metadata['file_id']

                        # Get progress info from metadata
                        if 'total_chunks' in metadata:
                            status_info['total_chunks'] = metadata['total_chunks']
                        if 'processed_chunks' in metadata:
                            status_info['processed_chunks'] = metadata['processed_chunks']

                        # Always try to get latest progress from Redis (real-time updates during vectorization)
                        # Redis progress takes precedence over metadata for active tasks
                        try:
                            from services.redis_service import get_redis_service
                            redis_service = get_redis_service()
                            progress_info = redis_service.get_progress_info(task_id)
                            if progress_info:
                                # Use Redis progress as primary source (updated in real-time)
                                status_info['processed_chunks'] = progress_info.get('processed_chunks', status_info.get('processed_chunks'))
                                status_info['total_chunks'] = progress_info.get('total_chunks', status_info.get('total_chunks'))
                        except Exception as e:
                            logger.debug(f"Failed to get progress from Redis for task {task_id}: {e!s}")
                # Add error information for failed tasks
                if result.failed():
                    try:
                        error_json, plain_error = _parse_failure_info(
                            result.info)
                        if plain_error:
                            status_info['error'] = plain_error

                        if error_json:
                            if error_json.get('message') is not None:
                                status_info['error'] = error_json.get(
                                    'message')
                            if error_json.get('index_name') is not None:
                                status_info['index_name'] = error_json.get(
                                    'index_name')
                            if error_json.get('task_name') is not None:
                                status_info['task_name'] = error_json.get(
                                    'task_name')
                            if error_json.get('source') is not None:
                                status_info['path_or_url'] = error_json.get(
                                    'source')
                            if error_json.get('original_filename') is not None:
                                status_info['original_filename'] = error_json.get(
                                    'original_filename')
                            if error_json.get('file_id') is not None:
                                status_info['file_id'] = error_json.get('file_id')
                        elif not status_info['error']:
                            # fallback: compatible with previous format
                            status_info['error'] = str(
                                result.result) if result.result else "Unknown error"
                        if (
                            isinstance(result.result, dict)
                            and result.result.get('file_id') is not None
                        ):
                            status_info['file_id'] = result.result.get('file_id')
                    except Exception as e:
                        logger.warning(
                            f"Could not parse error info for task {task_id}, falling back. Error: {e}")
                        status_info['error'] = str(
                            result.result) if result.result else "Unknown error"
                    logger.debug(
                        f"Task {task_id} failed with error: {status_info['error']}")

                # Add result information for successful tasks
                if result.successful() and result.result:
                    if isinstance(result.result, dict):
                        # Include specific result fields that are useful for API
                        for key in [
                            'chunks_count',
                            'processing_time',
                            'storage_time',
                            'es_result',
                            'file_id',
                        ]:
                            if key in result.result:
                                status_info[key] = result.result[key]
            except Exception as e:
                logger.warning(
                    f"Error getting metadata for task {task_id}: {e!s}")
                status_info['error'] = f"Metadata access error: {e!s}"
        logger.debug(
            f"Task {task_id} status: {status_info['status']}, index: {status_info['index_name']}, task_name: {status_info['task_name']}")
        return status_info
    try:
        return await loop.run_in_executor(None, sync_get)
    except ValueError as e:
        if "Exception information must include the exception type" in str(e):
            logger.warning(
                f"Task {task_id} has legacy bad exception format, marking as FAILURE for forced update.")
            return {
                'id': task_id,
                'status': 'FAILURE',
                'created_at': '',
                'updated_at': '',
                'error': 'Legacy task error: exception type missing, forcibly marked as FAILURE.',
                'index_name': '',
                'task_name': '',
                'path_or_url': '',
                'original_filename': '',
                'file_id': None,
            }
        else:
            logger.error(f"Error getting status for task {task_id}: {e!s}")
            return {
                'id': task_id,
                'status': 'FAILURE',
                'created_at': '',
                'updated_at': '',
                'error': f"Cannot retrieve task status: {e!s}",
                'index_name': '',
                'task_name': '',
                'path_or_url': '',
                'original_filename': '',
                'file_id': None,
            }
    except Exception as e:
        logger.warning(f"Error getting status for task {task_id}: {e!s}")
        # Return minimal information if task status cannot be retrieved
        return {
            'id': task_id,
            'status': 'FAILURE',
            'created_at': "",
            'updated_at': "",
            'error': f"Cannot retrieve task status: {e!s}",
            'index_name': '',
            'task_name': '',
            'path_or_url': '',
            'original_filename': '',
            'file_id': None,
        }


async def get_task_details(task_id: str) -> dict[str, Any] | None:
    """
    Get detailed task information

    Args:
        task_id: Celery task ID

    Returns:
        Detailed task information or None if not found
    """
    task_info = await get_task_info(task_id)
    loop = asyncio.get_running_loop()

    def sync_result():
        result = AsyncResult(task_id, app=celery_app)
        if result.successful() and result.result:
            if isinstance(result.result, dict):
                if 'chunks_count' in result.result:
                    task_info['chunks_count'] = result.result['chunks_count']
                if 'processing_time' in result.result:
                    task_info['processing_time'] = result.result['processing_time']
                if 'storage_time' in result.result:
                    task_info['storage_time'] = result.result['storage_time']
                if 'es_result' in result.result:
                    task_info['es_result'] = result.result['es_result']
                task_info['result'] = result.result
        return task_info
    return await loop.run_in_executor(None, sync_result)
