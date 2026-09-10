"""
Celery tasks for data processing and vector storage
"""
import asyncio
import json
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp
import requests
from celery import Task, chain, chord, group, states
from celery.exceptions import Retry
from celery.result import allow_join_result

from consts.const import (
    ELASTICSEARCH_SERVICE,
    FORWARD_REDIS_RETRY_DELAY_S,
    FORWARD_REDIS_RETRY_MAX,
    REDIS_BACKEND_URL,
)
from consts.error_code import ErrorCode
from database.knowledge_db import get_knowledge_record
from services.redis_service import get_redis_service
from utils.file_management_utils import get_file_size
from utils.knowledge_ingestion_errors import (
    ClassifiedIngestionException,
    classify_ingestion_exception,
)
from utils.knowledge_telemetry import set_span_attributes, trace_knowledge_operation

from .app import app
from .parse_tasks import process
from .utils import (
    DocumentDeleteRequested,
    ensure_document_not_deleted,
    is_document_delete_requested,
)
from .utils import (
    update_file_lifecycle as _update_file_lifecycle,
)


logger = logging.getLogger("data_process.tasks")


class LoggingTask(Task):
    """Base task class with consistent task lifecycle logging."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.debug("Task %s[%s] completed successfully", self.name, task_id)
        return super().on_success(retval, task_id, args, kwargs)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Task %s[%s] failed: %s", self.name, task_id, exc)
        return super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logger.warning("Task %s[%s] retrying: %s", self.name, task_id, exc)
        return super().on_retry(exc, task_id, args, kwargs, einfo)
ASYNC_SPLIT_RETRY_MAX = max(
    FORWARD_REDIS_RETRY_MAX * 5, FORWARD_REDIS_RETRY_MAX)
FORWARD_ES_CHUNK_BATCH_SIZE = 64
FORWARD_BATCH_TTL_SECONDS = 2 * 60 * 60
IMAGE_METADATA_PROCESS_SOURCE = "UniversalImageExtractor"
_NON_RETRYABLE_FORWARD_CODES = {
    ErrorCode.KNOWLEDGE_INDEX_WRITE_BLOCKED.value,
    "es_bulk_failed",
    "es_dim_mismatch",
}


def _get_next_available_batch_index(
    batches: list[list[dict[str, Any]]],
    start_idx: int,
    batch_size: int,
) -> int:
    total_batches = len(batches)
    idx = start_idx
    for _ in range(total_batches):
        if len(batches[idx]) < batch_size:
            return idx
        idx = (idx + 1) % total_batches
    raise RuntimeError("No available batch capacity")


def _distribute_chunks_round_robin(
    batches: list[list[dict[str, Any]]],
    chunks: list[dict[str, Any]],
    batch_size: int,
    error_context: str,
) -> None:
    idx = 0
    for chunk in chunks:
        try:
            idx = _get_next_available_batch_index(batches, idx, batch_size)
        except RuntimeError as exc:
            raise RuntimeError(
                f"No available batch capacity while distributing {error_context}"
            ) from exc
        batches[idx].append(chunk)
        idx = (idx + 1) % len(batches)


def _build_balanced_batches(
    formatted_chunks: list[dict[str, Any]],
    batch_size: int = FORWARD_ES_CHUNK_BATCH_SIZE,
) -> list[list[dict[str, Any]]]:
    """
    Split chunks into max-size batches and spread image-metadata chunks evenly.
    """
    total = len(formatted_chunks)
    if total == 0:
        return []
    if total <= batch_size:
        return [formatted_chunks]

    total_batches = math.ceil(total / batch_size)
    image_chunks = [
        chunk for chunk in formatted_chunks
        if chunk.get("process_source") == IMAGE_METADATA_PROCESS_SOURCE
    ]
    text_chunks = [
        chunk for chunk in formatted_chunks
        if chunk.get("process_source") != IMAGE_METADATA_PROCESS_SOURCE
    ]

    batches: list[list[dict[str, Any]]] = [[] for _ in range(total_batches)]

    _distribute_chunks_round_robin(
        batches=batches,
        chunks=image_chunks,
        batch_size=batch_size,
        error_context="image metadata chunks",
    )
    _distribute_chunks_round_robin(
        batches=batches,
        chunks=text_chunks,
        batch_size=batch_size,
        error_context="text chunks",
    )

    return batches


def _redis_error_reason(classified: ClassifiedIngestionException) -> str:
    """Keep Redis compatible with the lifecycle code-or-message representation."""
    if classified.error_code:
        return json.dumps({"error_code": classified.error_code}, ensure_ascii=False)
    message = classified.error_message or ""
    return message[:200] + "..." if len(message) > 200 else message


def save_error_to_redis(task_id: str, error_reason: str):
    """
    Save error information to Redis

    Args:
        task_id: Celery task ID
        error_reason: Short error reason summary
    """
    if not task_id:
        logger.warning("Cannot save error info: task_id is empty")
        return
    if not error_reason:
        logger.warning(
            f"Cannot save error info for task {task_id}: error_reason is empty")
        return
    try:
        redis_service = get_redis_service()
        success = redis_service.save_error_info(task_id, error_reason)
        if success:
            logger.info(
                f"Successfully saved error info for task {task_id}: {error_reason[:100]}...")
        else:
            logger.warning(
                f"Failed to save error info for task {task_id}: save_error_info returned False")
    except Exception as e:
        logger.error(
            f"Failed to save error info to Redis for task {task_id}: {e!s}", exc_info=True)


def run_async(coro):
    """Run an async HTTP operation from a synchronous Celery task."""
    return asyncio.run(coro)


def _forward_redis_client():
    if not REDIS_BACKEND_URL:
        raise RuntimeError("REDIS_BACKEND_URL is not configured")
    import redis

    return redis.Redis.from_url(REDIS_BACKEND_URL, decode_responses=True)


def _store_forward_batch(task_id: str, batch_index: int, chunks: list[dict[str, Any]]) -> str:
    """Store one ES batch and return its Redis reference."""
    key = f"dp:{task_id}:forward:batch:{batch_index}"
    _forward_redis_client().set(
        key,
        json.dumps(chunks, ensure_ascii=False),
        ex=FORWARD_BATCH_TTL_SECONDS,
    )
    return key


def _load_forward_batch(batch_key: str) -> list[dict[str, Any]]:
    cached = _forward_redis_client().get(batch_key)
    if not cached:
        raise RuntimeError(f"Forward batch is missing from Redis: {batch_key}")
    chunks = json.loads(cached)
    if not isinstance(chunks, list):
        raise RuntimeError(f"Forward batch is not a list: {batch_key}")
    return chunks


def _cleanup_forward_batches(batch_keys: list[str]) -> None:
    if not batch_keys:
        return
    try:
        _forward_redis_client().delete(*batch_keys)
    except Exception:
        logger.warning("Failed to clean forward batch keys=%s", batch_keys, exc_info=True)


def _delete_source_file_via_http_sync(
    *,
    base_url: str,
    index_name: str,
    path_or_url: str,
    scope: str,
    authorization: str | None = None,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    base = (base_url or "").rstrip("/")
    if not base:
        raise RuntimeError("ELASTICSEARCH_SERVICE is not configured")
    url = f"{base}/indices/{index_name}/documents"
    params = {"path_or_url": path_or_url, "scope": scope}
    headers: dict[str, str] = {}
    if authorization:
        headers["Authorization"] = authorization

    resp = requests.delete(
        url, params=params, headers=headers, timeout=timeout_s
    )
    body_text = getattr(resp, "text", "")
    parsed = None
    try:
        parsed = resp.json()
    except Exception:
        parsed = _parse_json_or_none(body_text) if body_text else None

    return {
        "http_status": getattr(resp, "status_code", None),
        "response_json": parsed if isinstance(parsed, dict) else None,
        "response_text": body_text if not isinstance(parsed, dict) else None,
    }


def _build_forward_error(
    message: str,
    index_name: str,
    source: str | None,
    original_filename: str | None,
    error_code: str | None = None,
) -> Exception:
    error = {
        "message": message,
        "index_name": index_name,
        "task_name": "forward",
        "source": source,
        "original_filename": original_filename,
    }
    if error_code:
        error["error_code"] = error_code
    return Exception(json.dumps(error, ensure_ascii=False))


def _parse_json_or_none(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


@dataclass(frozen=True)
class _ForwardContext:
    task_id: str
    request_id: str
    start_time: float
    source: str
    index_name: str
    original_filename: str | None
    file_id: str | None = None


def _init_forward_context(
    *,
    task_id: str,
    request_id: str,
    start_time: float,
    source: str,
    index_name: str,
    original_filename: str | None,
    file_id: str | None = None,
) -> _ForwardContext:
    return _ForwardContext(
        task_id=task_id,
        request_id=request_id,
        start_time=start_time,
        source=source,
        index_name=index_name,
        original_filename=original_filename,
        file_id=file_id,
    )


def _is_forward_task_cancelled(ctx: _ForwardContext) -> bool:
    try:
        redis_service = get_redis_service()
        return bool(redis_service.is_task_cancelled(ctx.task_id))
    except Exception as exc:
        logger.warning(
            f"[{ctx.request_id}] FORWARD TASK: Failed to check cancellation flag for task {ctx.task_id}: "
            f"{exc}"
        )
        return False


def _build_forward_cancelled_result(ctx: _ForwardContext) -> dict[str, Any]:
    return {
        'task_id': ctx.task_id,
        'file_id': ctx.file_id,
        'source': ctx.source,
        'index_name': ctx.index_name,
        'original_filename': ctx.original_filename,
        # Keep cancellation explicit for the cleanup task.  The deletion
        # fence may be cleared by the coordinator before this chain callback
        # runs, so cleanup must not infer cancellation from Redis alone.
        'cancelled': True,
        'chunks_stored': 0,
        'storage_time': 0,
        'es_result': {
            "success": False,
            "message": "Indexing cancelled because document was deleted.",
            "total_indexed": 0,
            "total_submitted": 0,
        },
    }


@trace_knowledge_operation("knowledge.forward.redis_read", "forward.redis_read")
def _load_forward_chunks(
    self: Task,
    *,
    processed_data: dict[str, Any],
    original_source: str,
    original_index_name: str,
    filename: str | None,
) -> tuple[list[dict[str, Any]] | None, bool, str, str, str | None]:
    chunks = processed_data.get('chunks')
    split_async = bool(processed_data.get('split_async'))

    # If chunks are not in payload, try loading from Redis via the redis_key
    if (not chunks) and processed_data.get('redis_key'):
        redis_key = processed_data.get('redis_key')
        try:
            client = _forward_redis_client()
            cached = client.get(redis_key)
            if cached:
                try:
                    logger.debug(
                        f"[{self.request.id}] FORWARD TASK: Retrieved Redis key '{redis_key}', payload_length={len(cached)}")
                    chunks = json.loads(cached)
                except json.JSONDecodeError as jde:
                    # Log raw prefix to help diagnose incorrect writes
                    raw_preview = cached[:120] if isinstance(
                        cached, str) else str(type(cached))
                    logger.error(
                        f"[{self.request.id}] FORWARD TASK: JSON decode error for key '{redis_key}': {jde!s}; raw_prefix={raw_preview!r}")
                    raise
            else:
                if split_async:
                    retry_num = getattr(self.request, 'retries', 0)
                    logger.info(
                        f"[{self.request.id}] FORWARD TASK: Async split chunks missing for key {redis_key}. Retry {retry_num + 1}/{ASYNC_SPLIT_RETRY_MAX} in {FORWARD_REDIS_RETRY_DELAY_S}s")
                    raise self.retry(
                        countdown=FORWARD_REDIS_RETRY_DELAY_S,
                        max_retries=ASYNC_SPLIT_RETRY_MAX,
                        exc=Exception(json.dumps({
                            "message": "Async split chunks missing; will retry",
                            "index_name": original_index_name,
                            "task_name": "forward",
                            "source": original_source,
                            "original_filename": filename
                        }, ensure_ascii=False))
                    )
                # No busy-wait: release the worker slot and retry later
                retry_num = getattr(self.request, 'retries', 0)
                logger.info(
                    f"[{self.request.id}] FORWARD TASK: Chunks not yet available for key {redis_key}. Retry {retry_num + 1}/{FORWARD_REDIS_RETRY_MAX} in {FORWARD_REDIS_RETRY_DELAY_S}s")
                raise self.retry(
                    countdown=FORWARD_REDIS_RETRY_DELAY_S,
                    max_retries=FORWARD_REDIS_RETRY_MAX,
                    exc=Exception(json.dumps({
                        "message": "Chunks missing in Redis; will retry",
                        "index_name": original_index_name,
                        "task_name": "forward",
                        "source": original_source,
                        "original_filename": filename
                    }, ensure_ascii=False))
                )
        except Retry:
            raise
        except Exception as exc:
            raise Exception(json.dumps({
                "message": f"Failed to retrieve chunks from Redis: {exc!s}",
                "index_name": original_index_name,
                "task_name": "forward",
                "source": original_source,
                "original_filename": filename
            }, ensure_ascii=False))

    if processed_data.get('source'):
        original_source = processed_data.get('source')
    if processed_data.get('index_name'):
        original_index_name = processed_data.get('index_name')
    if processed_data.get('original_filename'):
        filename = processed_data.get('original_filename')

    logger.info(
        f"[{self.request.id}] FORWARD TASK: Received data for source '{original_source}' with {len(chunks) if chunks else 'None'} chunks")

    if chunks is None:
        raise Exception(json.dumps({
            "message": "No chunks received for forwarding",
            "index_name": original_index_name,
            "task_name": "forward",
            "source": original_source,
            "original_filename": filename
        }, ensure_ascii=False))
    if len(chunks) == 0:
        if split_async and processed_data.get('redis_key'):
            retry_num = getattr(self.request, 'retries', 0)
            logger.info(
                f"[{self.request.id}] FORWARD TASK: Empty chunks while waiting for async split. Retry {retry_num + 1}/{ASYNC_SPLIT_RETRY_MAX} in {FORWARD_REDIS_RETRY_DELAY_S}s")
            raise self.retry(
                countdown=FORWARD_REDIS_RETRY_DELAY_S,
                    max_retries=ASYNC_SPLIT_RETRY_MAX,
                    exc=Exception(json.dumps({
                        "message": "Chunks empty in Redis; will retry",
                    "index_name": original_index_name,
                    "task_name": "forward",
                    "source": original_source,
                    "original_filename": filename
                }, ensure_ascii=False))
            )
        logger.warning(
            f"[{self.request.id}] FORWARD TASK: Empty chunks list received for source {original_source}")

    return chunks, split_async, original_source, original_index_name, filename


def _extract_error_code_from_es_response(
    parsed_body: dict[str, Any] | None,
    text: str,
) -> str | None:
    # Some gateways return a non-code JSON body while retaining the upstream
    # error_code in the raw response text. Check both representations.
    return (
        classify_ingestion_exception(parsed_body, "FORWARD").error_code
        if parsed_body is not None
        else None
    ) or classify_ingestion_exception(text, "FORWARD").error_code


@trace_knowledge_operation("knowledge.forward.elasticsearch", "forward.elasticsearch")
def _send_chunks_to_es(
    chunks: list[dict[str, Any]],
    index_name: str,
    authorization: str | None,
    task_id: str | None = None,
    source: str = "",
    original_filename: str = "",
    large_mode: bool = False,
    file_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    async def _post():
        elasticsearch_url = ELASTICSEARCH_SERVICE
        if not elasticsearch_url:
            raise _build_forward_error(
                message="ELASTICSEARCH_SERVICE env is not set",
                index_name=index_name,
                source=source,
                original_filename=original_filename,
            )
        route_url = f"/indices/{index_name}/documents"
        full_url = elasticsearch_url + route_url
        headers = {"Content-Type": "application/json"}
        if authorization:
            headers["Authorization"] = authorization
        if task_id:
            headers["X-Task-Id"] = task_id
        try:
            connector = aiohttp.TCPConnector(verify_ssl=False)
            timeout = aiohttp.ClientTimeout(total=600)

            request_params: dict[str, str] = {}

            if large_mode:
                request_params["large_mode"] = "true"

            # Check immediately before the external write so a delete request
            # that wins during formatting cannot start a new indexing request.
            ensure_document_not_deleted(
                index_name=index_name,
                source=source,
                file_id=file_id,
                tenant_id=tenant_id,
            )
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.post(
                    full_url,
                    headers=headers,
                    json=chunks,
                    params=request_params,
                    raise_for_status=False
                ) as response:
                    text = await response.text()
                    status = response.status
                    parsed_body = _parse_json_or_none(text)

                    if status >= 400:
                        error_code = _extract_error_code_from_es_response(
                            parsed_body, text)
                        if error_code:
                            raise _build_forward_error(
                                message=f"ElasticSearch service returned HTTP {status}",
                                index_name=index_name,
                                source=source,
                                original_filename=original_filename,
                                error_code=error_code,
                            )

                        raise Exception(
                            f"ElasticSearch service returned HTTP {status}")

                    result = parsed_body if isinstance(parsed_body, dict) else await response.json()
                    return result

        except DocumentDeleteRequested:
            raise
        except aiohttp.ClientConnectorError as e:
            logger.error(
                f"[{task_id}] FORWARD TASK: Connection error to {full_url}: {e!s}")
            raise _build_forward_error(
                message=f"Failed to connect to API: {e!s}",
                index_name=index_name,
                source=source,
                original_filename=original_filename,
            )
        except asyncio.TimeoutError as e:
            logger.warning(
                f"[{task_id}] FORWARD TASK: Timeout when indexing documents: {e!s}.")
            raise _build_forward_error(
                message=f"Timeout when indexing documents: {e!s}",
                index_name=index_name,
                source=source,
                original_filename=original_filename,
            )
        except Exception as e:
            classified = classify_ingestion_exception(e, "FORWARD")
            logger.error(
                f"[{task_id}] FORWARD TASK: Unexpected error when indexing documents: {e!s}.")
            raise _build_forward_error(
                message=f"Unexpected error when indexing documents: {e!s}",
                index_name=index_name,
                source=source,
                original_filename=original_filename,
                error_code=classified.error_code,
            )

    return run_async(_post())


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.forward_part', queue='forward_part_q')
@trace_knowledge_operation("knowledge.forward.batch", "forward.batch")
def forward_part(
        self,
        batch_key: str,
        index_name: str,
        authorization: str | None = None,
        parent_task_id: str | None = None,
        parent_total_chunks: int | None = None,
        source: str | None = None,
        original_filename: str | None = None,
        batch_index: int | None = None,
        total_batches: int | None = None,
        large_mode: bool | None = False,
        file_id: str | None = None,
        tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Forward one Redis-backed chunk batch.
    """
    try:
        # Respect cancellation from parent task if available
        if parent_task_id:
            try:
                redis_service = get_redis_service()
                parent_cancelled = redis_service.is_task_cancelled(parent_task_id)
            except Exception as cancellation_exc:
                logger.warning(
                    "Unable to read parent cancellation state for task %s: %s",
                    parent_task_id,
                    cancellation_exc,
                )
                parent_cancelled = False
            if parent_cancelled:
                logger.info(
                    "Skipping cancelled forward batch %s/%s for parent task %s",
                    batch_index,
                    total_batches,
                    parent_task_id,
                )
                return {
                    "success": True,
                    "total_indexed": 0,
                    "total_submitted": 0,
                    "batch_key": batch_key,
                    "batch_index": batch_index,
                    "total_batches": total_batches,
                    "cancelled": True,
                }

        chunks = _load_forward_batch(batch_key)
        es_result = _send_chunks_to_es(
            chunks=chunks,
            index_name=index_name,
            authorization=authorization,
            task_id=None,
            source=source,
            original_filename=original_filename,
            large_mode=large_mode,
            file_id=file_id,
            tenant_id=tenant_id,
        )

        if not isinstance(es_result, dict) or not es_result.get("success"):
            error_message = es_result.get(
                "message", "Unknown error from main_server") if isinstance(es_result, dict) else "Unknown error"
            raise Exception(json.dumps({
                "message": f"main_server API error: {error_message}",
                "index_name": index_name,
                "task_name": "forward_part",
                "source": source,
                "original_filename": original_filename
            }, ensure_ascii=False))

        ensure_document_not_deleted(
            index_name=index_name,
            source=source,
            file_id=file_id,
            tenant_id=tenant_id,
        )

        # Update parent task progress per finished batch so frontend can show real-time indexing count.
        if parent_task_id:
            try:
                processed_delta = int(es_result.get("total_indexed", 0) or 0)
                redis_service = get_redis_service()
                redis_service.increment_progress_info(
                    task_id=parent_task_id,
                    delta_processed=processed_delta,
                    total_chunks=parent_total_chunks,
                )
            except Exception as progress_exc:
                logger.warning(
                    f"[{self.request.id}] FORWARD PART: Failed to update parent progress "
                    f"for task {parent_task_id}: {progress_exc}"
                )

        return {
            "success": True,
            "total_indexed": es_result.get("total_indexed", 0),
            "total_submitted": es_result.get("total_submitted", len(chunks)),
            "batch_key": batch_key,
            "batch_index": batch_index,
            "total_batches": total_batches,
        }
    except DocumentDeleteRequested:
        logger.info(
            "Skipping forward batch because document deletion was requested parent_task_id=%s batch=%s/%s",
            parent_task_id,
            batch_index,
            total_batches,
        )
        return {
            "success": True,
            "total_indexed": 0,
            "total_submitted": 0,
            "batch_key": batch_key,
            "batch_index": batch_index,
            "total_batches": total_batches,
            "cancelled": True,
        }
    except Exception as e:
        classified = classify_ingestion_exception(e, "FORWARD")
        if classified.error_code in _NON_RETRYABLE_FORWARD_CODES:
            if parent_task_id:
                try:
                    get_redis_service().mark_task_cancelled(parent_task_id)
                except Exception as cancellation_exc:
                    logger.warning(
                        "Unable to mark parent task %s cancelled after a non-retryable forwarding failure: %s",
                        parent_task_id,
                        cancellation_exc,
                    )
            logger.error(
                "Forward batch %s/%s stopped because forwarding failed with non-retryable code %s",
                batch_index,
                total_batches,
                classified.error_code,
            )
            raise
        retry_num = getattr(self.request, 'retries', 0)
        logger.warning(
            f"[{self.request.id}] FORWARD PART: Failed batch {batch_index}/{total_batches} "
            f"(retry {retry_num + 1}/{FORWARD_REDIS_RETRY_MAX}): {e!s}"
        )
        raise self.retry(
            countdown=FORWARD_REDIS_RETRY_DELAY_S,
            max_retries=FORWARD_REDIS_RETRY_MAX,
            exc=e
        )


@app.task(
    bind=True,
    base=LoggingTask,
    name='data_process.tasks.aggregate_forward_parts',
    queue='forward_aggregate_q',
)
@trace_knowledge_operation("knowledge.forward.aggregate", "forward.aggregate")
def aggregate_forward_parts(
        self,
        parts_results: list[dict[str, Any]],
        source: str | None = None,
        index_name: str | None = None,
        original_filename: str | None = None,
        file_id: str | None = None,
        tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Aggregate forward_part results and remove their Redis batch references.
    """
    total_indexed = 0
    total_submitted = 0
    cancelled = False
    batch_keys = [
        result.get("batch_key")
        for result in parts_results or []
        if result and result.get("batch_key")
    ]
    try:
        for result in parts_results or []:
            if not result:
                continue
            if result.get("cancelled"):
                cancelled = True
                continue
            total_indexed += int(result.get("total_indexed", 0) or 0)
            total_submitted += int(result.get("total_submitted", 0) or 0)

        cancelled = cancelled or is_document_delete_requested(
            index_name=index_name,
            source=source,
            file_id=file_id,
            tenant_id=tenant_id,
        )
        result = {
            "success": True,
            "total_indexed": total_indexed,
            "total_submitted": total_submitted,
            "source": source,
            "index_name": index_name,
            "original_filename": original_filename,
            "file_id": file_id,
        }
        if cancelled:
            result["cancelled"] = True
        return result
    finally:
        _cleanup_forward_batches(batch_keys)


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.forward', queue='forward_q')
@trace_knowledge_operation("knowledge.forward", "forward")
def forward(
        self,
        processed_data: dict,
        index_name: str,
        source: str,
        source_type: str = 'minio',
        original_filename: str | None = None,
        authorization: str | None = None,
        telemetry_context: dict[str, str] | None = None,
        tenant_id: str | None = None,
        file_id: str | None = None,
) -> dict:
    """
    Vectorize and store processed chunks in Elasticsearch

    Args:
        processed_data: Dict containing chunks and metadata
        index_name: Name of the index to store documents
        source: Original source path (for metadata)
        source_type: The type of the source("local", "minio")
        original_filename: The original name of the file
        authorization: Authorization header for API calls

    Returns:
        Dict containing storage results and metadata
    """
    start_time = time.time()
    task_id = self.request.id
    # _warn_if_queue_mismatch("FORWARD TASK", "forward_q", self.request)
    original_source = source
    original_index_name = index_name
    filename = original_filename
    file_id = file_id or (processed_data or {}).get("file_id")
    _update_file_lifecycle(
        file_id=file_id,
        tenant_id=tenant_id,
        index_name=index_name,
        source=source,
        status="FORWARDING",
        stage="FORWARD",
        forward_task_id=task_id,
    )

    try:
        ctx = _init_forward_context(
            task_id=task_id,
            request_id=str(self.request.id),
            start_time=start_time,
            source=source,
            index_name=index_name,
            original_filename=original_filename,
            file_id=file_id,
        )

        # Avoid loading chunks or starting indexing after either cancellation
        # signal has won the race.
        if (
            (processed_data or {}).get("cancelled")
            or is_document_delete_requested(
                index_name=index_name,
                source=source,
                file_id=file_id,
                tenant_id=tenant_id,
            )
            or _is_forward_task_cancelled(ctx)
        ):
            logger.info(
                f"[{self.request.id}] FORWARD TASK: Detected cancellation for task {task_id}; "
                f"skipping chunk forwarding for source '{source}' in index '{index_name}'."
            )
            return _build_forward_cancelled_result(ctx)

        chunks, split_async, original_source, original_index_name, filename = _load_forward_chunks(
            self,
            processed_data=processed_data,
            original_source=original_source,
            original_index_name=original_index_name,
            filename=filename,
        )

        # Calculate total chunks for progress tracking
        total_chunks = len(chunks) if chunks else 0
        set_span_attributes(chunk_count=total_chunks, stage="forward.format")
        formatted_chunks = []
        # Compute once per file to avoid repeated IO/MinIO calls inside loop
        file_size = get_file_size(source_type, original_source) if isinstance(
            original_source, str) else 0
        filename_resolved = filename or (os.path.basename(original_source) if original_source and isinstance(
            original_source, str) else "")
        for i, chunk in enumerate(chunks):
            # Extract text and metadata
            content = chunk.get("content", "")
            metadata = chunk.get("metadata", {})

            # Validate chunk content
            if not content or len(content.strip()) == 0:
                logger.warning(
                    f"[{self.request.id}] FORWARD TASK: Chunk {i+1} has empty text content, skipping")
                continue

            # Format as expected by the Elasticsearch API
            formatted_chunk = {
                "metadata": metadata,
                "filename": filename_resolved,
                "path_or_url": original_source,
                "content": content,
                "process_source": (
                    chunk.get("process_source")
                    or metadata.get("process_source")
                    or "Unstructured"
                ),
                "source_type": source_type,
                "file_size": file_size,
                "create_time": metadata.get("creation_date"),
                "date": metadata.get("date"),
                "index": i,
            }
            formatted_chunks.append(formatted_chunk)

        if len(formatted_chunks) == 0:
            raise Exception(json.dumps({
                "message": "No valid chunks to forward after formatting",
                "index_name": original_index_name,
                "task_name": "forward",
                "source": original_source,
                "original_filename": original_filename,
                "error_code": "no_valid_chunks"
            }, ensure_ascii=False))

        logger.info(
            f"[{self.request.id}] FORWARD TASK: Starting ES indexing for {len(formatted_chunks)} chunks to index '{original_index_name}'...")

        # Update task state with total chunks before starting vectorization
        self.update_state(
            state=states.STARTED,
            meta={
                'source': original_source,
                'index_name': original_index_name,
                'original_filename': filename,
                'file_id': file_id,
                'task_name': 'forward',
                'start_time': start_time,
                'stage': 'vectorizing_and_storing',
                'total_chunks': total_chunks,
                'processed_chunks': 0  # Will be updated during vectorization via Redis
            }
        )

        try:
            redis_service = get_redis_service()
            redis_service.save_progress_info(task_id, 0, total_chunks)
        except Exception as progress_init_exc:
            logger.warning(
                f"[{self.request.id}] FORWARD TASK: Failed to initialize progress in Redis: "
                f"{progress_init_exc}"
            )

        if len(formatted_chunks) < FORWARD_ES_CHUNK_BATCH_SIZE:
            es_result = _send_chunks_to_es(
                chunks=formatted_chunks,
                index_name=original_index_name,
                authorization=authorization,
                task_id=task_id,
                source=original_source,
                original_filename=original_filename,
                large_mode=False,
                file_id=file_id,
                tenant_id=tenant_id,
            )
        else:
            batches = _build_balanced_batches(
                formatted_chunks=formatted_chunks,
                batch_size=FORWARD_ES_CHUNK_BATCH_SIZE,
            )
            total_batches = len(batches)
            image_chunks_total = sum(
                1 for chunk in formatted_chunks if chunk.get("process_source") == IMAGE_METADATA_PROCESS_SOURCE
            )
            image_distribution = [
                sum(
                    1
                    for chunk in batch
                    if chunk.get("process_source") == IMAGE_METADATA_PROCESS_SOURCE
                )
                for batch in batches
            ]
            logger.info(
                f"[{self.request.id}] FORWARD TASK: Batch distribution ready: total_batches={total_batches}, "
                f"batch_size={FORWARD_ES_CHUNK_BATCH_SIZE}, image_metadata_total={image_chunks_total}, "
                f"image_per_batch={image_distribution}")
            batch_refs = [
                _store_forward_batch(task_id, idx + 1, batch)
                for idx, batch in enumerate(batches)
            ]
            group_tasks = group(
                forward_part.s(
                    batch_key=batch_key,
                    index_name=original_index_name,
                    authorization=authorization,
                    parent_task_id=task_id,
                    parent_total_chunks=total_chunks,
                    source=original_source,
                    original_filename=original_filename,
                    batch_index=idx + 1,
                    total_batches=total_batches,
                    file_id=file_id,
                    tenant_id=tenant_id,
                    # If request was split into multiple groups, force all groups to use large path.
                    large_mode=True,
                ).set(queue='forward_part_q')
                for idx, batch_key in enumerate(batch_refs)
            )
            callback = aggregate_forward_parts.s(
                source=original_source,
                index_name=original_index_name,
                original_filename=original_filename,
                file_id=file_id,
                tenant_id=tenant_id,
            ).set(queue='forward_aggregate_q')
            result = chord(group_tasks)(callback)
            with allow_join_result():
                es_result = result.get()
        logger.debug(
            f"[{self.request.id}] FORWARD TASK: API response from main_server for source '{original_source}': {es_result}")

        if isinstance(es_result, dict) and es_result.get("cancelled"):
            return _build_forward_cancelled_result(ctx)
        ensure_document_not_deleted(
            index_name=original_index_name,
            source=original_source,
            file_id=file_id,
            tenant_id=tenant_id,
        )

        if isinstance(es_result, dict) and es_result.get("success"):
            total_indexed = es_result.get("total_indexed", 0)
            total_submitted = es_result.get(
                "total_submitted", len(formatted_chunks))
            logger.debug(f"[{self.request.id}] FORWARD TASK: main_server reported {total_indexed}/{total_submitted} documents indexed successfully for '{original_source}'. Message: {es_result.get('message')}")

            if total_indexed < total_submitted:
                logger.info("Value when raise Exception:")
                logger.info(f"original_source: {original_source}")
                logger.info(f"original_index_name: {original_index_name}")
                logger.info("task_name: forward")
                logger.info(f"source: {original_source}")
                raise Exception(json.dumps({
                    "message": f"Failure reported by main_server. Expected {total_submitted} chunks, indexed {total_indexed} chunks.",
                    "index_name": original_index_name,
                    "task_name": "forward",
                    "source": original_source,
                    "original_filename": original_filename,
                    "error_code": "es_bulk_failed"
                }, ensure_ascii=False))
        elif isinstance(es_result, dict) and not es_result.get("success"):
            error_message = es_result.get(
                "message", "Unknown error from main_server")
            raise Exception(json.dumps({
                "message": f"main_server API error: {error_message}",
                "index_name": original_index_name,
                "task_name": "forward",
                "source": original_source,
                "original_filename": original_filename
            }, ensure_ascii=False))
        else:
            raise Exception(json.dumps({
                "message": f"Unexpected API response format from main_server: {es_result}",
                "index_name": original_index_name,
                "task_name": "forward",
                "source": original_source,
                "original_filename": original_filename
            }, ensure_ascii=False))
        end_time = time.time()

        # Get final indexed count from result
        final_processed = 0
        if isinstance(es_result, dict) and es_result.get("success"):
            final_processed = es_result.get("total_indexed", len(chunks))

        logger.info(
            f"[{self.request.id}] FORWARD TASK: Updating task state to SUCCESS after ES indexing completion")
        self.update_state(
            state=states.SUCCESS,
            meta={
                'chunks_stored': len(chunks),
                'storage_time': end_time - start_time,
                'source': original_source,
                'index_name': original_index_name,
                'original_filename': original_filename,
                'file_id': file_id,
                'task_name': 'forward',
                'es_result': es_result,
                'stage': 'completed',
                'total_chunks': total_chunks,
                'processed_chunks': final_processed
            }
        )

        _update_file_lifecycle(
            file_id=file_id,
            tenant_id=tenant_id,
            index_name=original_index_name,
            source=original_source,
            status="COMPLETED",
            stage="COMPLETED",
            forward_task_id=task_id,
            completed_at=datetime.utcnow(),
        )

        logger.info(
            f"[{self.request.id}] FORWARD TASK: Successfully stored {len(chunks)} chunks to index {original_index_name} in {end_time - start_time:.2f}s")

        return {
            'task_id': task_id,
            'file_id': file_id,
            'source': original_source,
            'index_name': original_index_name,
            'original_filename': original_filename,
            'chunks_stored': len(chunks),
            'storage_time': end_time - start_time,
            'es_result': es_result
        }
    except DocumentDeleteRequested:
        logger.info(
            "Forward task cancelled because document deletion was requested task_id=%s source=%s",
            task_id,
            original_source,
        )
        return _build_forward_cancelled_result(ctx)
    except Exception as e:
        # If it's an Exception, all go here (including our custom JSON message)
        # Important: if this is a Celery Retry, re-raise immediately without recording error_code
        if isinstance(e, Retry):
            raise

        task_id = self.request.id
        try:
            error_info = json.loads(str(e))
            error_message = error_info.get('message', str(e))
            logger.error(
                f"Error forwarding chunks for index '{error_info.get('index_name', '')}': {error_message}")

            classified = classify_ingestion_exception(error_info, "FORWARD")
            error_code = classified.error_code
            _update_file_lifecycle(
                file_id=file_id,
                tenant_id=tenant_id,
                index_name=error_info.get("index_name") or original_index_name,
                source=error_info.get("source") or original_source,
                status="FAILED",
                stage="FORWARD",
                error_code=error_code,
                error_message=classified.error_message,
                error_stage="FORWARD",
                failed_at=datetime.utcnow(),
                forward_task_id=task_id,
            )

            reason_to_store = _redis_error_reason(classified)

            # Save error info to Redis BEFORE re-raising
            logger.info(
                f"Attempting to save error info for task {task_id} with reason: {reason_to_store[:100]}...")
            save_error_to_redis(task_id, reason_to_store)

            self.update_state(
                meta={
                    'source': error_info.get('source', ''),
                    'index_name': error_info.get('index_name', ''),
                    'task_name': error_info.get('task_name', ''),
                    'original_filename': error_info.get('original_filename', ''),
                    'file_id': file_id,
                    'custom_error': error_message,
                    'stage': 'forward_task_failed'
                }
            )
        except Exception:
            logger.error(f"Error forwarding chunks: {e!s}")
            # Try to save error even if parsing fails
            try:
                error_message = str(e)
                classified = classify_ingestion_exception(error_message, "FORWARD")
                error_code = classified.error_code
                _update_file_lifecycle(
                    file_id=file_id,
                    tenant_id=tenant_id,
                    index_name=original_index_name,
                    source=original_source,
                    status="FAILED",
                    stage="FORWARD",
                    error_code=error_code,
                    error_message=classified.error_message,
                    error_stage="FORWARD",
                    failed_at=datetime.utcnow(),
                    forward_task_id=task_id,
                )

                reason_to_store = _redis_error_reason(classified)

                save_error_to_redis(task_id, reason_to_store)
            except Exception:
                pass
            self.update_state(
                meta={
                    'file_id': file_id,
                    'custom_error': str(e),
                    'stage': 'forward_task_failed'
                }
            )
        raise


@app.task(
    bind=True,
    base=LoggingTask,
    name="data_process.tasks.cleanup_source",
    queue="forward_q",
)
@trace_knowledge_operation("knowledge.cleanup", "cleanup")
def cleanup_source(
    self,
    forward_result: dict[str, Any],
    authorization: str | None = None,
    telemetry_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Conditionally delete the MinIO source file after successful indexing.

    If the knowledge base is configured with preserve_source_file=false, call:
    DELETE /indices/{index_name}/documents?path_or_url=...&scope=source_only

    authorization is passed as a Celery signature kwarg (not via forward_result)
    so tokens are not persisted in task result payloads.
    """
    index_name = (forward_result or {}).get("index_name")
    source = (forward_result or {}).get("source")
    file_id = (forward_result or {}).get("file_id")

    cleanup_info: dict[str, Any] = {
        "attempted": False,
        "skipped_reason": None,
        "success": None,
        "http_status": None,
        "response": None,
        "error": None,
    }

    if not index_name or not source:
        cleanup_info["skipped_reason"] = "missing_index_name_or_source"
        forward_result = dict(forward_result or {})
        forward_result["source_cleanup"] = cleanup_info
        return forward_result

    if (forward_result or {}).get("cancelled") or is_document_delete_requested(
        index_name=index_name,
        source=source,
        file_id=file_id,
    ):
        cleanup_info["skipped_reason"] = "document_delete_requested"
        forward_result = dict(forward_result or {})
        forward_result["source_cleanup"] = cleanup_info
        return forward_result

    try:
        record = get_knowledge_record({"index_name": index_name}) or {}
        preserve_source_file = record.get("preserve_source_file", True)
    except Exception as exc:
        logger.warning(
            "[%s] CLEANUP TASK: Failed to load knowledge config for index '%s': %s",
            getattr(self.request, "id", "unknown"),
            index_name,
            exc,
        )
        cleanup_info["skipped_reason"] = "knowledge_record_lookup_failed"
        forward_result = dict(forward_result or {})
        forward_result["source_cleanup"] = cleanup_info
        return forward_result

    if preserve_source_file:
        cleanup_info["skipped_reason"] = "preserve_source_file_true"
        forward_result = dict(forward_result or {})
        forward_result["source_cleanup"] = cleanup_info
        return forward_result

    cleanup_info["attempted"] = True
    try:
        resp = _delete_source_file_via_http_sync(
            base_url=ELASTICSEARCH_SERVICE,
            index_name=index_name,
            path_or_url=source,
            scope="source_only",
            authorization=authorization,
        )
        cleanup_info["http_status"] = resp.get("http_status")
        cleanup_info["response"] = (
            resp.get("response_json")
            if resp.get("response_json") is not None
            else resp.get("response_text")
        )

        ok = False
        if isinstance(resp.get("response_json"), dict):
            ok = bool(resp["response_json"].get("status") == "success")
        elif resp.get("http_status") and 200 <= int(resp["http_status"]) < 300:
            ok = True

        cleanup_info["success"] = ok
        if not ok:
            logger.warning(
                "[%s] CLEANUP TASK: Source-only delete did not succeed. index='%s' source='%s' http_status=%s",
                getattr(self.request, "id", "unknown"),
                index_name,
                source,
                cleanup_info["http_status"],
            )
    except Exception as exc:
        cleanup_info["success"] = False
        cleanup_info["error"] = str(exc)
        logger.warning(
            "[%s] CLEANUP TASK: Source-only delete failed. index='%s' source='%s' error=%s",
            getattr(self.request, "id", "unknown"),
            index_name,
            source,
            exc,
        )

    forward_result = dict(forward_result or {})
    forward_result["source_cleanup"] = cleanup_info
    return forward_result


@trace_knowledge_operation("knowledge.chain.submit", "chain.submit")
def submit_process_forward_chain(
        *,
        source: str,
        source_type: str,
        chunking_strategy: str,
        index_name: str | None = None,
        original_filename: str | None = None,
        authorization: str | None = None,
        embedding_model_id: int | None = None,
        tenant_id: str | None = None,
        telemetry_context: dict[str, str] | None = None,
        file_id: str | None = None,
) -> str:
    """
    Build and enqueue a Celery chain: process -> forward.

    Returns:
        Celery chain task ID, or empty string if enqueue failed.
    """
    process_kwargs = {
        "source": source,
        "source_type": source_type,
        "chunking_strategy": chunking_strategy,
        "index_name": index_name,
        "original_filename": original_filename,
        "embedding_model_id": embedding_model_id,
        "tenant_id": tenant_id,
        "telemetry_context": telemetry_context or {},
    }
    forward_kwargs = {
        "index_name": index_name,
        "source": source,
        "source_type": source_type,
        "original_filename": original_filename,
        "authorization": authorization,
        "tenant_id": tenant_id,
        "telemetry_context": telemetry_context or {},
    }
    if file_id is not None:
        process_kwargs["file_id"] = file_id
        forward_kwargs["file_id"] = file_id

    task_chain = chain(
        process.s(
            **process_kwargs,
        ).set(queue='parse_q'),
        forward.s(
            **forward_kwargs,
        ).set(queue='forward_q'),
        cleanup_source.s(
            authorization=authorization,
            telemetry_context=telemetry_context or {},
        ).set(queue='forward_q'),
    )

    result = task_chain.apply_async()
    if result is None or not hasattr(result, 'id') or result.id is None:
        logger.error(
            "Celery chain apply_async() did not return a valid result or result.id")
        return ""
    return result.id


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.process_and_forward')
def process_and_forward(
        self,
        source: str,
        source_type: str,
        chunking_strategy: str,
        index_name: str | None = None,
        original_filename: str | None = None,
        authorization: str | None = None,
        embedding_model_id: int | None = None,
        tenant_id: str | None = None,
        telemetry_context: dict[str, str] | None = None,
        file_id: str | None = None,
) -> str:
    """
    Combined task that chains processing and forwarding

    This task delegates to a chain of process -> forward

    Args:
        source: Source file path, URL, or text content
        source_type: source of the file("local", "minio")
        chunking_strategy: Strategy for chunking the document
        index_name: Name of the index to store documents
        original_filename: The original name of the file
        authorization: Authorization header for API calls
        embedding_model_id: Embedding model ID for chunk size configuration
        tenant_id: Tenant ID for retrieving model configuration

    Returns:
        Task ID of the chain
    """
    if is_document_delete_requested(
        index_name=index_name,
        source=source,
        file_id=file_id,
        tenant_id=tenant_id,
    ):
        logger.info(
            "Skipping process-forward submission because document deletion was requested source=%s file_id=%s",
            source,
            file_id,
        )
        return ""
    logger.info(
        f"Starting processing chain for {source}, original_filename={original_filename}, strategy={chunking_strategy}, index={index_name}, model_id={embedding_model_id}")

    chain_kwargs = dict(
        source=source,
        source_type=source_type,
        chunking_strategy=chunking_strategy,
        index_name=index_name,
        original_filename=original_filename,
        authorization=authorization,
        embedding_model_id=embedding_model_id,
        tenant_id=tenant_id,
        telemetry_context=telemetry_context or {},
    )
    if file_id is not None:
        chain_kwargs["file_id"] = file_id
    chain_id = submit_process_forward_chain(**chain_kwargs)
    if chain_id:
        logger.info(f"Created task chain ID: {chain_id}")
    return chain_id
