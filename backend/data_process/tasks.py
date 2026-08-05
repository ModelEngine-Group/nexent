"""
Celery tasks for data processing and vector storage
"""
import asyncio
import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple

import aiohttp
import requests
import re
import ray
from celery import Task, chain, states, group, chord
from celery.exceptions import Retry

from utils.file_management_utils import get_file_size
from database.attachment_db import get_file_stream_raw
from database.knowledge_db import get_knowledge_record
from services.redis_service import get_redis_service
from .app import app
from .ray_actors import DataProcessorRayActor
from consts.const import (
    ELASTICSEARCH_SERVICE,
    REDIS_BACKEND_URL,
    FORWARD_REDIS_RETRY_DELAY_S,
    FORWARD_REDIS_RETRY_MAX,
    DP_REDIS_CHUNKS_WAIT_TIMEOUT_S,
    DP_REDIS_CHUNKS_POLL_INTERVAL_MS,
    RAY_ACTOR_NUM_CPUS,
    RAY_NUM_CPUS,
    DISABLE_RAY_DASHBOARD,
    ROOT_DIR,
    PER_WAVE_TIMEOUT,
    MAX_TIMEOUT,
    RAY_GLOBAL_ACTOR_POOL_SIZE,
    RAY_ACTOR_WARM_TIMEOUT_S,
    RAY_GLOBAL_ACTOR_POOL_NAME,
    RAY_GLOBAL_ACTOR_POOL_NAMESPACE,
    DP_RAY_OPERATION_TIMEOUT_S,
    DP_FORWARD_REQUEST_TIMEOUT_S,
    DP_FORWARD_FILE_TIMEOUT_S,
    DP_SPLIT_STATE_TTL_S,
    MAX_CHUNKS_PER_FILE,
    MAX_DATA_PROCESS_FILE_SIZE_BYTES,
)


logger = logging.getLogger("data_process.tasks")
ASYNC_SPLIT_RETRY_MAX = max(
    FORWARD_REDIS_RETRY_MAX * 5, FORWARD_REDIS_RETRY_MAX)
FORWARD_ES_CHUNK_BATCH_SIZE = 64
IMAGE_METADATA_PROCESS_SOURCE = "UniversalImageExtractor"
REDIS_SOCKET_TIMEOUT_SECONDS = 5


def _processing_limit_error(message: str, error_code: str) -> RuntimeError:
    return RuntimeError(json.dumps({
        "message": message,
        "error_code": error_code,
    }, ensure_ascii=False))


def _validate_file_size(file_size_bytes: int, source: str) -> None:
    if file_size_bytes > MAX_DATA_PROCESS_FILE_SIZE_BYTES:
        raise _processing_limit_error(
            (
                f"File '{source}' is {file_size_bytes / 1024 / 1024:.2f}MB; "
                f"the data-process limit is "
                f"{MAX_DATA_PROCESS_FILE_SIZE_BYTES / 1024 / 1024:.0f}MB"
            ),
            "file_too_large",
        )


def _validate_chunk_count(chunk_count: int, filename: str) -> None:
    if chunk_count > MAX_CHUNKS_PER_FILE:
        raise _processing_limit_error(
            (
                f"File '{filename}' produced {chunk_count} chunks; "
                f"the safety limit is {MAX_CHUNKS_PER_FILE}"
            ),
            "too_many_chunks",
        )


def _split_state_keys(redis_key: str) -> Tuple[str, str, str]:
    return (
        f"{redis_key}:ready",
        f"{redis_key}:error",
        f"{redis_key}:cancelled",
    )


def _get_split_redis_client():
    if not REDIS_BACKEND_URL:
        raise RuntimeError("REDIS_BACKEND_URL not configured")

    import redis

    return redis.Redis.from_url(
        REDIS_BACKEND_URL,
        decode_responses=True,
        socket_connect_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
    )


def _mark_split_failed(redis_key: str, error: str) -> None:
    """Publish a terminal failure so the file-level parent stops waiting."""
    client = _get_split_redis_client()
    ready_key, error_key, cancelled_key = _split_state_keys(redis_key)
    payload = json.dumps({
        "status": "failed",
        "message": str(error),
    }, ensure_ascii=False)
    for key, value in (
        (error_key, payload),
        (cancelled_key, "1"),
        (ready_key, "1"),
    ):
        client.set(key, value)
        client.expire(key, DP_SPLIT_STATE_TTL_S)


def _is_split_cancelled(redis_key: str) -> bool:
    try:
        _, _, cancelled_key = _split_state_keys(redis_key)
        return bool(_get_split_redis_client().get(cancelled_key))
    except Exception as exc:
        logger.warning("Failed to check split cancellation for '%s': %s", redis_key, exc)
        return False


def _cleanup_split_payloads(redis_key: str, keep_cancelled: bool = False) -> None:
    """Best-effort cleanup scoped to one file's split state."""
    try:
        client = _get_split_redis_client()
        ready_key, error_key, cancelled_key = _split_state_keys(redis_key)
        keys_to_delete = [redis_key, ready_key, error_key]
        if not keep_cancelled:
            keys_to_delete.append(cancelled_key)
        client.delete(*keys_to_delete)

        part_prefix = redis_key.rsplit(":chunks", 1)[0]
        part_keys = list(client.scan_iter(match=f"{part_prefix}:part:*", count=100))
        if part_keys:
            client.delete(*part_keys)
    except Exception as exc:
        logger.warning("Failed to clean split payloads for '%s': %s", redis_key, exc)


def _claim_process_attempt(task_id: str) -> int:
    """Detect redelivery after a worker/container loss without retrying poison work."""
    if not task_id:
        return 1
    try:
        client = _get_split_redis_client()
        attempt_key = f"dp:{task_id}:attempts"
        attempt = int(client.incr(attempt_key))
        client.expire(attempt_key, DP_SPLIT_STATE_TTL_S)
        return attempt
    except Exception as exc:
        logger.warning("Failed to claim process attempt for '%s': %s", task_id, exc)
        return 1


def _wait_for_split_ready(redis_key: str, timeout_s: int, poll_interval_ms: int) -> int:
    """
    Wait until async split aggregation is marked ready in Redis.
    Returns aggregated chunk count.
    Raises TimeoutError on timeout.
    """
    if not REDIS_BACKEND_URL:
        raise RuntimeError("REDIS_BACKEND_URL not configured")

    client = _get_split_redis_client()
    ready_key, error_key, cancelled_key = _split_state_keys(redis_key)
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        error_payload = client.get(error_key)
        if error_payload:
            try:
                parsed_error = json.loads(error_payload)
                error_message = (
                    parsed_error.get("message", error_payload)
                    if isinstance(parsed_error, dict)
                    else error_payload
                )
            except Exception:
                error_message = error_payload
            raise RuntimeError(f"Async split processing failed: {error_message}")

        if client.get(cancelled_key):
            raise RuntimeError("Async split processing was cancelled")

        if client.get(ready_key):
            cached = client.get(redis_key)
            if cached:
                try:
                    chunks = json.loads(cached)
                    return len(chunks) if isinstance(chunks, list) else 0
                except Exception:
                    return 0
            return 0
        time.sleep(max(0.01, poll_interval_ms / 1000.0))

    raise TimeoutError(
        f"Timed out waiting for async split aggregation at key '{ready_key}' after {timeout_s}s"
    )


def _estimate_parallel_parts() -> int:
    try:
        total_cpus = RAY_NUM_CPUS
    except Exception:
        total_cpus = os.cpu_count() or 1
    actor_cpus = max(1, int(RAY_ACTOR_NUM_CPUS))
    return max(1, total_cpus // actor_cpus)


def _compute_split_wait_timeout(parts_count: int) -> int:
    base_timeout = DP_REDIS_CHUNKS_WAIT_TIMEOUT_S
    waves = math.ceil(max(1, parts_count) / _estimate_parallel_parts())
    dynamic_timeout = base_timeout + waves * max(
        DP_RAY_OPERATION_TIMEOUT_S,
        PER_WAVE_TIMEOUT,
    )
    return min(MAX_TIMEOUT, dynamic_timeout)


def _count_image_metadata_chunks(chunks: Optional[List[Dict[str, Any]]]) -> int:
    if not chunks:
        return 0
    return sum(
        1
        for chunk in chunks
        if isinstance(chunk, dict)
        and (chunk.get("process_source") or chunk.get("metadata", {}).get("process_source"))
        == IMAGE_METADATA_PROCESS_SOURCE
    )


def _get_next_available_batch_index(
    batches: List[List[Dict[str, Any]]],
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
    batches: List[List[Dict[str, Any]]],
    chunks: List[Dict[str, Any]],
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
    formatted_chunks: List[Dict[str, Any]],
    batch_size: int = FORWARD_ES_CHUNK_BATCH_SIZE,
) -> List[List[Dict[str, Any]]]:
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

    batches: List[List[Dict[str, Any]]] = [[] for _ in range(total_batches)]

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


# Thread lock for initializing Ray to prevent race conditions
ray_init_lock = threading.Lock()

ROOT_DIR_DISPLAY = ROOT_DIR or "{ROOT_DIR}"


def extract_error_code(reason: str, parsed_error: Optional[Dict] = None) -> Optional[str]:
    """
    Extract error code from error message or parsed error dict.
    Returns error code if matched, None otherwise.
    """
    # 1) parsed_error dict
    if parsed_error and isinstance(parsed_error, dict):
        code = parsed_error.get("error_code")
        if code:
            return code

    # 2) try parse reason as JSON
    try:
        parsed = json.loads(reason)
        if isinstance(parsed, dict):
            code = parsed.get("error_code")
            if code:
                return code
            detail = parsed.get("detail")
            if isinstance(detail, dict) and detail.get("error_code"):
                return detail.get("error_code")
    except Exception:
        pass

    # 3) regex from raw string (supports single/double quotes)
    try:
        match = re.search(
            r'["\']error_code["\']\s*:\s*["\']([^"\']+)["\']', reason)
        if match:
            return match.group(1)
    except Exception:
        pass

    return "unknown_error"


def save_error_to_redis(task_id: str, error_reason: str, start_time: float):
    """
    Save error information to Redis

    Args:
        task_id: Celery task ID
        error_reason: Short error reason summary
        start_time: Task start timestamp (unused, kept for compatibility)
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
            f"Failed to save error info to Redis for task {task_id}: {str(e)}", exc_info=True)


def init_ray_in_worker():
    """
    Initializes Ray within a Celery worker, ensuring it is done only once.
    This function is designed to be called from within a task.
    """
    if ray.is_initialized():
        logger.debug("Ray is already initialized.")
        return

    logger.info("Ray not initialized. Initializing Ray for Celery worker...")
    try:
        # `configure_logging=False` prevents Ray from setting up its own loggers,
        # which can interfere with Celery's logging.
        # `faulthandler=False` is critical to prevent the
        # `AttributeError: 'LoggingProxy' object has no attribute 'fileno'`
        # error when running inside a Celery worker.
        # We also explicitly control the Ray dashboard behavior here to ensure
        # that Celery workers respect the global DISABLE_RAY_DASHBOARD setting.
        ray.init(
            configure_logging=False,
            faulthandler=False,
            include_dashboard=not DISABLE_RAY_DASHBOARD,
        )
        logger.info("Ray initialized successfully for Celery worker.")
    except Exception as e:
        logger.error(f"Failed to initialize Ray for Celery worker: {e}")
        raise RuntimeError("Failed to initialize Ray for Celery worker") from e


def run_async(coro):
    """
    Safely run async coroutine in Celery task context
    Handles existing event loops and avoids conflicts
    """
    try:
        # Check if we're already in an async context
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, safe to use asyncio.run
            return asyncio.run(coro)

        # We're in an existing event loop context
        if loop.is_running():
            # Try to use nest_asyncio for compatibility
            try:
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(coro)
            except ImportError:
                logger.warning(
                    "nest_asyncio not available, creating new thread for async operation")
                # Fallback: run in a new thread
                import concurrent.futures

                def run_in_thread():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(coro)
                    finally:
                        new_loop.close()
                        asyncio.set_event_loop(None)

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_thread)
                    return future.result()
        else:
            # Loop exists but not running, safe to use run_until_complete
            return loop.run_until_complete(coro)

    except Exception as e:
        logger.error(f"Error running async coroutine: {str(e)}")
        raise


def _delete_source_file_via_http_sync(
    *,
    base_url: str,
    index_name: str,
    path_or_url: str,
    scope: str,
    authorization: Optional[str] = None,
    timeout_s: float = 30.0,
) -> Dict[str, Any]:
    base = (base_url or "").rstrip("/")
    if not base:
        raise RuntimeError("ELASTICSEARCH_SERVICE is not configured")
    url = f"{base}/indices/{index_name}/documents"
    params = {"path_or_url": path_or_url, "scope": scope}
    headers: Dict[str, str] = {}
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
    source: Optional[str],
    original_filename: Optional[str],
) -> Exception:
    return Exception(json.dumps({
        "message": message,
        "index_name": index_name,
        "task_name": "forward",
        "source": source,
        "original_filename": original_filename
    }, ensure_ascii=False))


def _parse_json_or_none(text: str) -> Optional[Dict[str, Any]]:
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
    source_type: str
    original_filename: Optional[str]


def _init_forward_context(
    *,
    task_id: str,
    request_id: str,
    start_time: float,
    source: str,
    index_name: str,
    source_type: str,
    original_filename: Optional[str],
) -> _ForwardContext:
    return _ForwardContext(
        task_id=task_id,
        request_id=request_id,
        start_time=start_time,
        source=source,
        index_name=index_name,
        source_type=source_type,
        original_filename=original_filename,
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


def _build_forward_cancelled_result(ctx: _ForwardContext) -> Dict[str, Any]:
    return {
        'task_id': ctx.task_id,
        'source': ctx.source,
        'index_name': ctx.index_name,
        'original_filename': ctx.original_filename,
        'chunks_stored': 0,
        'storage_time': 0,
        'es_result': {
            "success": False,
            "message": "Indexing cancelled because document was deleted.",
            "total_indexed": 0,
            "total_submitted": 0,
        },
    }


def _load_forward_chunks(
    self: Task,
    *,
    processed_data: Dict[str, Any],
    original_source: str,
    original_index_name: str,
    filename: Optional[str],
) -> Tuple[Optional[List[Dict[str, Any]]], bool, str, str, Optional[str]]:
    chunks = processed_data.get('chunks')
    split_async = bool(processed_data.get('split_async'))

    # If chunks are not in payload, try loading from Redis via the redis_key
    if (not chunks) and processed_data.get('redis_key'):
        redis_key = processed_data.get('redis_key')
        if not REDIS_BACKEND_URL:
            raise Exception(json.dumps({
                "message": "REDIS_BACKEND_URL not configured to retrieve chunks",
                "index_name": original_index_name,
                "task_name": "forward",
                "source": original_source,
                "original_filename": filename
            }, ensure_ascii=False))
        try:
            client = _get_split_redis_client()
            ready_key, error_key, cancelled_key = _split_state_keys(redis_key)
            terminal_error = client.get(error_key)
            if terminal_error or client.get(cancelled_key):
                raise RuntimeError(
                    f"Process payload reached a terminal failure: {terminal_error or 'cancelled'}"
                )
            if split_async:
                ready_flag = client.get(ready_key)
                if not ready_flag:
                    retry_num = getattr(self.request, 'retries', 0)
                    logger.info(
                        f"[{self.request.id}] FORWARD TASK: Async split not ready for key {redis_key}. Retry {retry_num + 1}/{ASYNC_SPLIT_RETRY_MAX} in {FORWARD_REDIS_RETRY_DELAY_S}s")
                    raise self.retry(
                        countdown=FORWARD_REDIS_RETRY_DELAY_S,
                        max_retries=ASYNC_SPLIT_RETRY_MAX,
                        exc=Exception(json.dumps({
                            "message": "Async split not ready; will retry",
                            "index_name": original_index_name,
                            "task_name": "forward",
                            "source": original_source,
                            "original_filename": filename
                        }, ensure_ascii=False))
                    )
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
                        f"[{self.request.id}] FORWARD TASK: JSON decode error for key '{redis_key}': {str(jde)}; raw_prefix={raw_preview!r}")
                    raise
            else:
                if split_async:
                    retry_num = getattr(self.request, 'retries', 0)
                    logger.info(
                        f"[{self.request.id}] FORWARD TASK: Async split ready but chunks missing for key {redis_key}. Retry {retry_num + 1}/{ASYNC_SPLIT_RETRY_MAX} in {FORWARD_REDIS_RETRY_DELAY_S}s")
                    raise self.retry(
                        countdown=FORWARD_REDIS_RETRY_DELAY_S,
                        max_retries=ASYNC_SPLIT_RETRY_MAX,
                        exc=Exception(json.dumps({
                            "message": "Async split ready but chunks missing; will retry",
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
                        "message": "Chunks not ready in Redis; will retry",
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
                "message": f"Failed to retrieve chunks from Redis: {str(exc)}",
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
                    "message": "Chunks not ready in Redis (empty); will retry",
                    "index_name": original_index_name,
                    "task_name": "forward",
                    "source": original_source,
                    "original_filename": filename
                }, ensure_ascii=False))
            )
        logger.warning(
            f"[{self.request.id}] FORWARD TASK: Empty chunks list received for source {original_source}")

    return chunks, split_async, original_source, original_index_name, filename


def _cleanup_forward_chunks(processed_data: Dict[str, Any]) -> None:
    """Remove the process payload after a forward task reaches a terminal state."""
    redis_key = (processed_data or {}).get("redis_key")
    if redis_key:
        _cleanup_split_payloads(str(redis_key), keep_cancelled=False)
        try:
            task_prefix = str(redis_key).rsplit(":chunks", 1)[0]
            _get_split_redis_client().delete(f"{task_prefix}:attempts")
        except Exception as exc:
            logger.warning(
                "Failed to clean process attempt state for '%s': %s",
                redis_key,
                exc,
            )


def _extract_error_code_from_es_response(
    parsed_body: Optional[Dict[str, Any]],
    text: str,
) -> Optional[str]:
    error_code = None
    if isinstance(parsed_body, dict):
        error_code = parsed_body.get("error_code")
        detail = parsed_body.get("detail")
        if isinstance(detail, dict) and detail.get("error_code"):
            error_code = detail.get("error_code")
        elif isinstance(detail, str):
            parsed_detail = _parse_json_or_none(detail)
            if isinstance(parsed_detail, dict):
                error_code = parsed_detail.get("error_code", error_code)

    if error_code:
        return error_code

    try:
        match = re.search(
            r'["\']error_code["\']\s*:\s*["\']([^"\']+)["\']', text)
        return match.group(1) if match else None
    except Exception:
        return None


def _send_chunks_to_es(
    chunks: List[Dict[str, Any]],
    index_name: str,
    authorization: str | None,
    task_id: Optional[str] = None,
    source: str = "",
    original_filename: str = "",
    large_mode: bool = False,
    timeout_s: Optional[float] = None,
) -> Dict[str, Any]:
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
            effective_timeout = (
                DP_FORWARD_REQUEST_TIMEOUT_S
                if timeout_s is None
                else max(1.0, min(float(timeout_s), DP_FORWARD_REQUEST_TIMEOUT_S))
            )
            timeout = aiohttp.ClientTimeout(total=effective_timeout)

            request_params: Dict[str, str] = {}

            if large_mode:
                request_params["large_mode"] = "true"

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
                            raise Exception(json.dumps({
                                "error_code": error_code
                            }, ensure_ascii=False))

                        raise Exception(
                            f"ElasticSearch service returned HTTP {status}")

                    result = parsed_body if isinstance(parsed_body, dict) else await response.json()
                    return result

        except aiohttp.ClientConnectorError as e:
            logger.error(
                f"[{task_id}] FORWARD TASK: Connection error to {full_url}: {str(e)}")
            raise _build_forward_error(
                message=f"Failed to connect to API: {str(e)}",
                index_name=index_name,
                source=source,
                original_filename=original_filename,
            )
        except asyncio.TimeoutError as e:
            logger.warning(
                f"[{task_id}] FORWARD TASK: Timeout when indexing documents: {str(e)}.")
            raise _build_forward_error(
                message=f"Timeout when indexing documents: {str(e)}",
                index_name=index_name,
                source=source,
                original_filename=original_filename,
            )
        except Exception as e:
            logger.error(
                f"[{task_id}] FORWARD TASK: Unexpected error when indexing documents: {str(e)}.")
            raise _build_forward_error(
                message=f"Unexpected error when indexing documents: {str(e)}",
                index_name=index_name,
                source=source,
                original_filename=original_filename,
            )

    return run_async(_post())


@ray.remote(num_cpus=0)
class GlobalRayActorPoolManager:
    """
    Cluster-wide shared actor pool manager.
    A single detached manager serves all Celery worker processes.
    """

    def __init__(self, warm_timeout_s: float):
        self.warm_timeout_s = warm_timeout_s
        self.actors: List[Any] = []
        self.rr_index = 0

    def _create_and_warm_actor(self) -> Optional[Any]:
        actor = DataProcessorRayActor.remote()
        try:
            ray.get(actor.ping.remote(), timeout=self.warm_timeout_s)
            return actor
        except Exception as exc:
            try:
                ray.kill(actor, no_restart=True)
            except Exception:
                pass
            logger.warning(
                f"[GlobalRayActorPoolManager] Warm actor failed in {self.warm_timeout_s:.1f}s: {exc}"
            )
            return None

    def ensure_pool(self, desired: int, max_allowed: int) -> int:
        desired = max(0, int(desired))
        max_allowed = max(1, int(max_allowed))
        desired = min(desired, max_allowed)
        missing = max(0, desired - len(self.actors))
        for _ in range(missing):
            actor = self._create_and_warm_actor()
            if actor is not None:
                self.actors.append(actor)
        return len(self.actors)

    @staticmethod
    def _actor_identity(actor: Any) -> str:
        actor_id = getattr(actor, "_actor_id", None)
        if actor_id is not None:
            hex_method = getattr(actor_id, "hex", None)
            if callable(hex_method):
                return str(hex_method())
            return str(actor_id)
        return str(id(actor))

    def replace_actor(
        self,
        failed_actor_id: str,
        desired: int,
        max_allowed: int,
    ) -> int:
        """Remove one failed actor and restore the bounded pool size."""
        retained: List[Any] = []
        for actor in self.actors:
            if self._actor_identity(actor) != failed_actor_id:
                retained.append(actor)
                continue
            try:
                ray.kill(actor, no_restart=True)
            except Exception:
                pass

        self.actors = retained
        self.rr_index = self.rr_index % len(self.actors) if self.actors else 0
        return self.ensure_pool(desired=desired, max_allowed=max_allowed)

    def get_actor(self) -> Any:
        if not self.actors:
            actor = self._create_and_warm_actor()
            if actor is None:
                raise RuntimeError(
                    "Global actor pool is empty and actor warm-up failed")
            self.actors.append(actor)
        idx = self.rr_index % len(self.actors)
        self.rr_index += 1
        return self.actors[idx]


def _get_or_create_global_pool_manager() -> Any:
    with ray_init_lock:
        init_ray_in_worker()

    # Prefer atomic get/create when supported.
    try:
        return GlobalRayActorPoolManager.options(
            name=RAY_GLOBAL_ACTOR_POOL_NAME,
            namespace=RAY_GLOBAL_ACTOR_POOL_NAMESPACE,
            lifetime="detached",
            get_if_exists=True,
        ).remote(RAY_ACTOR_WARM_TIMEOUT_S)
    except TypeError:
        pass

    try:
        return ray.get_actor(
            RAY_GLOBAL_ACTOR_POOL_NAME, namespace=RAY_GLOBAL_ACTOR_POOL_NAMESPACE)
    except Exception:
        pass

    try:
        return GlobalRayActorPoolManager.options(
            name=RAY_GLOBAL_ACTOR_POOL_NAME,
            namespace=RAY_GLOBAL_ACTOR_POOL_NAMESPACE,
            lifetime="detached",
        ).remote(RAY_ACTOR_WARM_TIMEOUT_S)
    except Exception:
        # Name race: another worker may have created it in the meantime.
        return ray.get_actor(
            RAY_GLOBAL_ACTOR_POOL_NAME, namespace=RAY_GLOBAL_ACTOR_POOL_NAMESPACE)


def prewarm_ray_actors(target_size: Optional[int] = None) -> int:
    """
    Ensure a global shared pool of warm Ray actors exists for low-latency task execution.
    """
    desired = RAY_GLOBAL_ACTOR_POOL_SIZE if target_size is None else max(
        0, int(target_size))
    manager = _get_or_create_global_pool_manager()
    current_after = ray.get(
        manager.ensure_pool.remote(
            desired=desired, max_allowed=_estimate_parallel_parts()),
        timeout=RAY_ACTOR_WARM_TIMEOUT_S,
    )
    logger.info(
        f"Global Ray actor pool ready: current={current_after}, desired={desired}"
    )
    return current_after


def get_ray_actor() -> Any:
    """
    Return a warm actor from the global shared pool with round-robin selection.
    """
    manager = _get_or_create_global_pool_manager()
    current_after = ray.get(
        manager.ensure_pool.remote(
            desired=RAY_GLOBAL_ACTOR_POOL_SIZE,
            max_allowed=_estimate_parallel_parts(),
        ),
        timeout=RAY_ACTOR_WARM_TIMEOUT_S,
    )
    if current_after < 1:
        raise RuntimeError("Global Ray actor pool has no available actors")
    return ray.get(
        manager.get_actor.remote(),
        timeout=RAY_ACTOR_WARM_TIMEOUT_S,
    )


def _actor_identity(actor: Any) -> str:
    actor_id = getattr(actor, "_actor_id", None)
    if actor_id is not None:
        hex_method = getattr(actor_id, "hex", None)
        if callable(hex_method):
            return str(hex_method())
        return str(actor_id)
    return str(id(actor))


def _is_fatal_ray_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    return isinstance(exc, (TimeoutError, MemoryError)) or any(
        marker in name
        for marker in (
            "gettimeouterror",
            "rayactorerror",
            "outofmemoryerror",
            "workercrashederror",
        )
    ) or any(
        marker in message
        for marker in (
            "out of memory",
            "outofmemory",
            "oom killed",
            "worker died",
            "actor died",
        )
    )


def _replace_failed_ray_actor(actor: Any, operation: str, error: Exception) -> None:
    """Best-effort removal and replacement after a fatal Ray failure."""
    logger.warning(
        "Ray actor failed during %s; replacing it before later files: %s",
        operation,
        error,
    )
    try:
        try:
            ray.kill(actor, no_restart=True)
        except Exception:
            pass

        manager = _get_or_create_global_pool_manager()
        ray.get(
            manager.replace_actor.remote(
                failed_actor_id=_actor_identity(actor),
                desired=RAY_GLOBAL_ACTOR_POOL_SIZE,
                max_allowed=_estimate_parallel_parts(),
            ),
            timeout=RAY_ACTOR_WARM_TIMEOUT_S,
        )
    except Exception as repair_exc:
        logger.error(
            "Failed to restore Ray actor pool after %s failure: %s",
            operation,
            repair_exc,
        )


def _get_ray_result(
    ref: Any,
    actor: Any,
    operation: str,
    timeout_s: Optional[int] = None,
) -> Any:
    """Wait for one Ray operation with a hard deadline."""
    effective_timeout = DP_RAY_OPERATION_TIMEOUT_S if timeout_s is None else max(
        1, min(int(timeout_s), DP_RAY_OPERATION_TIMEOUT_S)
    )
    try:
        return ray.get(ref, timeout=effective_timeout)
    except Exception as exc:
        if _is_fatal_ray_error(exc):
            try:
                ray.cancel(ref, force=True)
            except Exception:
                pass
            _replace_failed_ray_actor(actor, operation, exc)
        raise


def _get_split_actor() -> Any:
    """
    Reuse warm DataProcessorRayActor instances for split operations.
    This keeps split path aligned with prewarmed actor pool.
    """
    return get_ray_actor()


class LoggingTask(Task):
    """Base task class with enhanced logging"""

    def on_success(self, retval, task_id, args, kwargs):
        """Log successful task completion"""
        logger.debug(f"Task {self.name}[{task_id}] completed successfully")
        return super().on_success(retval, task_id, args, kwargs)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Log task failure with enhanced error handling"""
        logger.error(f"Task {self.name}[{task_id}] failed: {exc}")
        # Log exception details for debugging
        if hasattr(exc, '__class__'):
            exc_type = exc.__class__.__name__
            exc_msg = str(exc)
            logger.error(f"Exception type: {exc_type}, message: {exc_msg}")
        # Let Celery handle the exception serialization automatically
        return super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Log task retry"""
        logger.warning(f"Task {self.name}[{task_id}] retrying: {exc}")
        return super().on_retry(exc, task_id, args, kwargs, einfo)


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.process_part', queue='process_part_q')
def process_part(
        self,
        part_bytes: bytes,
        filename: str,
        chunking_strategy: str,
        part_redis_key: str,
        split_redis_key: Optional[str] = None,
        source: Optional[str] = None,
        source_type: Optional[str] = None,
        model_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
        **params
) -> Dict[str, Any]:
    """
    Hidden sub-task to process a file part with Ray.
    """
    actor = get_ray_actor()
    try:
        chunks_ref = actor.process_bytes.remote(
            part_bytes,
            filename,
            chunking_strategy,
            task_id=None,
            model_id=model_id,
            tenant_id=tenant_id,
            **params
        )
        chunks = _get_ray_result(
            chunks_ref,
            actor,
            operation=f"process part '{filename}'",
        ) or []
        _validate_chunk_count(len(chunks), filename)

        if not REDIS_BACKEND_URL:
            raise RuntimeError("REDIS_BACKEND_URL not configured")

        client = _get_split_redis_client()
        if split_redis_key and _is_split_cancelled(split_redis_key):
            return {
                "success": False,
                "part_redis_key": part_redis_key,
                "chunks_count": 0,
                "error": "Parent split task was cancelled",
            }
        client.set(part_redis_key, json.dumps(chunks, ensure_ascii=False))
        client.expire(part_redis_key, DP_SPLIT_STATE_TTL_S)

        return {
            "success": True,
            "part_redis_key": part_redis_key,
            "chunks_count": len(chunks),
        }
    except Exception as e:
        logger.error(
            f"[process_part] Failed to process part for '{filename}': {str(e)}")
        if split_redis_key and not _is_split_cancelled(split_redis_key):
            try:
                _mark_split_failed(split_redis_key, str(e))
            except Exception as marker_exc:
                logger.error(
                    "Failed to publish split failure for '%s': %s",
                    split_redis_key,
                    marker_exc,
                )
        return {
            "success": False,
            "part_redis_key": part_redis_key,
            "chunks_count": 0,
            "error": str(e),
        }


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.aggregate_parts', queue='process_part_q')
def aggregate_parts(
        self,
        parts_results: List[List[Dict[str, Any]]],
        source: Optional[str] = None,
        index_name: Optional[str] = None,
        original_filename: Optional[str] = None
) -> Dict[str, Any]:
    """
    Hidden sub-task to aggregate part chunks.
    """
    merged: List[Dict[str, Any]] = []
    for part_chunks in parts_results or []:
        if part_chunks:
            merged.extend(part_chunks)
    return {
        "chunks": merged,
        "source": source,
        "index_name": index_name,
        "original_filename": original_filename
    }


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.aggregate_store_chunks', queue='process_part_q')
def aggregate_store_chunks(
        self,
        parts_results: List[Dict[str, Any]],
        redis_key: str,
        source: Optional[str] = None,
        index_name: Optional[str] = None,
        original_filename: Optional[str] = None
) -> Dict[str, Any]:
    """
    Hidden sub-task to aggregate part chunks and store into Redis for forward task.
    """
    if not REDIS_BACKEND_URL:
        raise Exception(json.dumps({
            "message": "REDIS_BACKEND_URL not configured to store chunks",
            "index_name": index_name,
            "task_name": "process",
            "source": source,
            "original_filename": original_filename
        }, ensure_ascii=False))

    try:
        client = _get_split_redis_client()
        ready_key, _, cancelled_key = _split_state_keys(redis_key)
        if client.get(cancelled_key):
            _cleanup_split_payloads(redis_key, keep_cancelled=True)
            return {
                "success": False,
                "chunks_count": 0,
                "redis_key": redis_key,
                "source": source,
                "index_name": index_name,
                "original_filename": original_filename,
                "error": "Parent split task was cancelled",
            }

        failed_results = [
            result for result in (parts_results or [])
            if not result or not result.get("success", False)
        ]
        if failed_results:
            error = next(
                (
                    str(result.get("error"))
                    for result in failed_results
                    if result and result.get("error")
                ),
                "One or more split parts failed",
            )
            _mark_split_failed(redis_key, error)
            _cleanup_split_payloads(redis_key, keep_cancelled=True)
            return {
                "success": False,
                "chunks_count": 0,
                "redis_key": redis_key,
                "source": source,
                "index_name": index_name,
                "original_filename": original_filename,
                "error": error,
            }

        reported_chunk_count = sum(
            int((result or {}).get("chunks_count", 0) or 0)
            for result in (parts_results or [])
        )
        _validate_chunk_count(
            reported_chunk_count,
            original_filename or source or redis_key,
        )

        merged: List[Dict[str, Any]] = []
        for part_result in parts_results or []:
            part_key = (part_result or {}).get("part_redis_key")
            if not part_key:
                raise RuntimeError("Split part result is missing its Redis key")
            cached = client.get(part_key)
            if not cached:
                raise RuntimeError(
                    f"Split part payload is missing at key '{part_key}'")
            try:
                part_chunks = json.loads(cached)
                if isinstance(part_chunks, list):
                    merged.extend(part_chunks)
                else:
                    raise RuntimeError(
                        f"Split part payload at key '{part_key}' is not a list")
            except Exception as exc:
                _mark_split_failed(redis_key, str(exc))
                raise
            # best-effort cleanup for part payload key
            try:
                client.delete(part_key)
            except Exception:
                pass

        _validate_chunk_count(
            len(merged),
            original_filename or source or redis_key,
        )
        serialized = json.dumps(merged, ensure_ascii=False)
        client.set(redis_key, serialized)
        client.expire(redis_key, DP_SPLIT_STATE_TTL_S)
        client.set(ready_key, "1")
        client.expire(ready_key, DP_SPLIT_STATE_TTL_S)
        logger.info(
            f"[{self.request.id}] PROCESS TASK: Stored aggregated chunks in Redis at key '{redis_key}', count={len(merged)}")
    except Exception as exc:
        try:
            _mark_split_failed(redis_key, str(exc))
        except Exception:
            pass
        raise Exception(json.dumps({
            "message": f"Failed to store chunks to Redis: {str(exc)}",
            "index_name": index_name,
            "task_name": "process",
            "source": source,
            "original_filename": original_filename
        }, ensure_ascii=False))

    return {
        "success": True,
        "chunks_count": len(merged),
        "redis_key": redis_key,
        "source": source,
        "index_name": index_name,
        "original_filename": original_filename
    }


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.forward_part', queue='forward_q')
def forward_part(
        self,
        chunks: List[Dict[str, Any]],
        index_name: str,
        authorization: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        parent_total_chunks: Optional[int] = None,
        source: Optional[str] = None,
        original_filename: Optional[str] = None,
        batch_index: Optional[int] = None,
        total_batches: Optional[int] = None,
        large_mode: Optional[bool] = False,
) -> Dict[str, Any]:
    """
    Forward sub-task that indexes a chunk batch.
    """
    try:
        # Respect cancellation from parent task if available
        if parent_task_id:
            try:
                redis_service = get_redis_service()
                if redis_service.is_task_cancelled(parent_task_id):
                    raise RuntimeError(
                        f"Parent task {parent_task_id} marked as cancelled")
            except Exception:
                pass

        es_result = _send_chunks_to_es(
            chunks=chunks,
            index_name=index_name,
            authorization=authorization,
            task_id=None,
            source=source,
            original_filename=original_filename,
            large_mode=large_mode,
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
            "batch_index": batch_index,
            "total_batches": total_batches,
        }
    except Exception as e:
        retry_num = getattr(self.request, 'retries', 0)
        logger.warning(
            f"[{self.request.id}] FORWARD PART: Failed batch {batch_index}/{total_batches} "
            f"(retry {retry_num + 1}/{FORWARD_REDIS_RETRY_MAX}): {str(e)}"
        )
        raise self.retry(
            countdown=FORWARD_REDIS_RETRY_DELAY_S,
            max_retries=FORWARD_REDIS_RETRY_MAX,
            exc=e
        )


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.aggregate_forward_parts', queue='forward_q')
def aggregate_forward_parts(
        self,
        parts_results: List[Dict[str, Any]],
        source: Optional[str] = None,
        index_name: Optional[str] = None,
        original_filename: Optional[str] = None
) -> Dict[str, Any]:
    """
    Aggregate forward_part results.
    """
    total_indexed = 0
    total_submitted = 0
    for result in parts_results or []:
        if not result:
            continue
        total_indexed += int(result.get("total_indexed", 0) or 0)
        total_submitted += int(result.get("total_submitted", 0) or 0)

    return {
        "success": True,
        "total_indexed": total_indexed,
        "total_submitted": total_submitted,
        "source": source,
        "index_name": index_name,
        "original_filename": original_filename
    }


def _split_file_for_processing(
    request_id: str,
    source: str,
    source_type: str,
    task_id: str,
    params: Dict[str, Any],
    file_data: Optional[bytes] = None,
) -> List[bytes]:
    max_size = 5 * 1024 * 1024
    params.pop("max_size", None)
    logger.info(
        f"[{request_id}] PROCESS TASK: Splitting file before processing (max_size={max_size})")

    split_actor_get_start = time.perf_counter()
    split_actor = _get_split_actor()
    split_actor_get_elapsed = time.perf_counter() - split_actor_get_start
    logger.info(
        f"[{request_id}] PROCESS TASK: split actor ready in {split_actor_get_elapsed:.3f}s")

    split_call_start = time.perf_counter()
    split_kwargs = {
        "source": source,
        "destination": source_type,
        "task_id": task_id,
        "max_size": max_size,
        **params,
    }
    if file_data is not None:
        split_kwargs["file_data"] = file_data

    parts_ref = split_actor.split_file.remote(**split_kwargs)
    parts = _get_ray_result(
        parts_ref,
        split_actor,
        operation=f"split file '{source}'",
    )
    split_call_elapsed = time.perf_counter() - split_call_start
    logger.info(
        f"[{request_id}] PROCESS TASK: split_file RPC done in {split_call_elapsed:.3f}s "
        f"(source_type={source_type})")

    if parts:
        part_sizes = [len(p) for p in parts]
        total_bytes = sum(part_sizes)
        min_size = min(part_sizes)
        max_part_size = max(part_sizes)
        avg_size = total_bytes / len(part_sizes)
        logger.info(
            f"[{request_id}] PROCESS TASK: Split stats: parts={len(part_sizes)}, "
            f"total={total_bytes/1024/1024:.2f}MB, "
            f"min={min_size/1024:.2f}KB, max={max_part_size/1024:.2f}KB, avg={avg_size/1024:.2f}KB")

    return parts


def _run_processing_for_parts(
    request_id: str,
    source: str,
    source_type: str,
    task_id: str,
    chunking_strategy: str,
    filename_for_processing: str,
    parts: List[bytes],
    index_name: Optional[str],
    original_filename: Optional[str],
    embedding_model_id: Optional[int],
    tenant_id: Optional[str],
    params: Dict[str, Any],
) -> Tuple[bool, Optional[List[Dict[str, Any]]], Optional[int]]:
    if not parts:
        logger.warning(
            f"[{request_id}] PROCESS TASK: Split returned no parts; fallback to full-file processing")
        process_actor = get_ray_actor()
        chunks_ref = process_actor.process_file.remote(
            source,
            chunking_strategy,
            destination=source_type,
            task_id=task_id,
            model_id=embedding_model_id,
            tenant_id=tenant_id,
            **params
        )
        logger.info(
            f"[{request_id}] PROCESS TASK: Waiting for Ray processing to complete...")
        chunks = _get_ray_result(
            chunks_ref,
            process_actor,
            operation=f"process file '{filename_for_processing}'",
        )
        _validate_chunk_count(len(chunks or []), filename_for_processing)
        return False, chunks, None

    if len(parts) == 1:
        process_actor = get_ray_actor()
        chunks_ref = process_actor.process_bytes.remote(
            parts[0],
            filename_for_processing,
            chunking_strategy,
            task_id=None,
            model_id=embedding_model_id,
            tenant_id=tenant_id,
            **params
        )
        logger.info(
            f"[{request_id}] PROCESS TASK: Waiting for Ray processing to complete...")
        chunks = _get_ray_result(
            chunks_ref,
            process_actor,
            operation=f"process file part '{filename_for_processing}'",
        )
        _validate_chunk_count(len(chunks or []), filename_for_processing)
        return False, chunks, None

    redis_key = f"dp:{task_id}:chunks"
    group_tasks = group(
        process_part.s(
            part_bytes=part,
            filename=filename_for_processing,
            chunking_strategy=chunking_strategy,
            part_redis_key=f"dp:{task_id}:part:{idx}",
            split_redis_key=redis_key,
            source=source,
            source_type=source_type,
            model_id=embedding_model_id,
            tenant_id=tenant_id,
            **params
        ) for idx, part in enumerate(parts)
    )
    callback = aggregate_store_chunks.s(
        redis_key=redis_key,
        source=source,
        index_name=index_name,
        original_filename=original_filename
    ).set(queue='process_part_q')
    logger.info(
        f"[{request_id}] PROCESS TASK: Dispatching {len(parts)} part tasks...")
    chord_result = chord(group_tasks)(callback)

    split_wait_timeout = _compute_split_wait_timeout(len(parts))
    logger.info(
        f"[{request_id}] PROCESS TASK: Waiting split aggregation, timeout={split_wait_timeout}s, "
        f"parts={len(parts)}, est_parallel={_estimate_parallel_parts()}")
    try:
        split_chunk_count = _wait_for_split_ready(
            redis_key=redis_key,
            timeout_s=split_wait_timeout,
            poll_interval_ms=DP_REDIS_CHUNKS_POLL_INTERVAL_MS,
        )
    except Exception as exc:
        if not _is_split_cancelled(redis_key):
            try:
                _mark_split_failed(redis_key, str(exc))
            except Exception as marker_exc:
                logger.warning(
                    "Failed to publish split cancellation for '%s': %s",
                    redis_key,
                    marker_exc,
                )
        try:
            group_result = getattr(chord_result, "parent", None)
            if group_result is not None:
                group_result.revoke(terminate=False)
        except Exception as revoke_exc:
            logger.warning(
                "Failed to revoke split tasks for '%s': %s",
                redis_key,
                revoke_exc,
            )
        _cleanup_split_payloads(redis_key, keep_cancelled=True)
        raise
    return True, None, split_chunk_count


def _process_source_with_split(
    request_id: str,
    source: str,
    source_type: str,
    task_id: str,
    chunking_strategy: str,
    index_name: Optional[str],
    original_filename: Optional[str],
    embedding_model_id: Optional[int],
    tenant_id: Optional[str],
    params: Dict[str, Any],
    file_data: Optional[bytes] = None,
) -> Tuple[bool, Optional[List[Dict[str, Any]]], Optional[int]]:
    parts = _split_file_for_processing(
        request_id=request_id,
        source=source,
        source_type=source_type,
        task_id=task_id,
        params=params,
        file_data=file_data,
    )
    filename_for_processing = original_filename or os.path.basename(source)
    split_async, chunks, split_chunk_count = _run_processing_for_parts(
        request_id=request_id,
        source=source,
        source_type=source_type,
        task_id=task_id,
        chunking_strategy=chunking_strategy,
        filename_for_processing=filename_for_processing,
        parts=parts,
        index_name=index_name,
        original_filename=original_filename,
        embedding_model_id=embedding_model_id,
        tenant_id=tenant_id,
        params=params,
    )

    if split_async:
        logger.info(
            f"[{request_id}] PROCESS TASK: Async split finished with {split_chunk_count or 0} chunks")
    else:
        logger.info(
            f"[{request_id}] PROCESS TASK: Ray processing completed, got {len(chunks) if chunks else 0} chunks")

    if not split_async and chunks:
        redis_key = f"dp:{task_id}:chunks"
        process_actor = get_ray_actor()
        store_ref = process_actor.store_chunks_in_redis.remote(redis_key, chunks)
        stored = _get_ray_result(
            store_ref,
            process_actor,
            operation=f"store chunks for '{filename_for_processing}'",
        )
        if not stored:
            raise RuntimeError(
                f"Failed to store processed chunks for '{filename_for_processing}'"
            )
        logger.info(
            f"[{request_id}] PROCESS TASK: Stored chunks in Redis at key '{redis_key}'")

    return split_async, chunks, split_chunk_count


def _build_no_valid_chunks_error(
    split_async: bool,
    index_name: Optional[str],
    source: str,
    original_filename: Optional[str],
) -> Exception:
    message = (
        "Async split completed but produced 0 chunks"
        if split_async else
        "Ray processing completed but produced 0 chunks"
    )
    return Exception(json.dumps({
        "message": message,
        "index_name": index_name,
        "task_name": "process",
        "source": source,
        "original_filename": original_filename,
        "error_code": "no_valid_chunks"
    }, ensure_ascii=False))


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.process', queue='process_q')
def process(
        self,
        source: str,
        source_type: str,
        chunking_strategy: str = "basic",
        index_name: Optional[str] = None,
        original_filename: Optional[str] = None,
        embedding_model_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
        **params
) -> Dict:
    """
    Process a file and extract text/chunks

    Args:
        source: Source file path, URL, or text content
        source_type: Type of source ("local", "minio")
        chunking_strategy: Strategy for chunking the document
        index_name: Name of the index (for metadata)
        original_filename: The original name of the file
        embedding_model_id: Embedding model ID for chunk size configuration
        tenant_id: Tenant ID for retrieving model configuration
        **params: Additional parameters
    """
    start_time = time.time()
    task_id = self.request.id
    # _warn_if_queue_mismatch("PROCESS TASK", "process_q", self.request)

    logger.info(
        f"[{self.request.id}] PROCESS TASK: source_type: {source_type}")

    self.update_state(
        state=states.STARTED,
        meta={
            'source': source,
            'source_type': source_type,
            'index_name': index_name,
            'original_filename': original_filename,
            'task_name': 'process',
            'start_time': start_time,
            'stage': 'extracting_text'
        }
    )
    try:
        attempt = _claim_process_attempt(task_id)
        if attempt > 1:
            raise _processing_limit_error(
                (
                    "This file task was redelivered after its worker terminated; "
                    "it is being failed to protect later uploads"
                ),
                "worker_lost",
            )

        # Process the file based on the source type
        file_size_mb = 0
        split_chunk_count = None
        image_metadata_chunk_count = 0
        elapsed_time = 0.0
        chunks: Optional[List[Dict[str, Any]]] = None
        split_async = False

        if source_type == "local":
            # Check file existence and size for optimization
            if not os.path.exists(source):
                raise FileNotFoundError(f"File does not exist: {source}")

            file_size = os.path.getsize(source)
            _validate_file_size(file_size, source)
            file_size_mb = file_size / (1024 * 1024)

            logger.info(
                f"[{self.request.id}] PROCESS TASK: File size: {file_size_mb:.2f}MB")

            split_async, chunks, split_chunk_count = _process_source_with_split(
                request_id=self.request.id,
                source=source,
                source_type=source_type,
                task_id=task_id,
                chunking_strategy=chunking_strategy,
                index_name=index_name,
                original_filename=original_filename,
                embedding_model_id=embedding_model_id,
                tenant_id=tenant_id,
                params=params,
            )
            elapsed_time = time.time() - start_time
            processing_speed = file_size_mb / \
                elapsed_time if file_size_mb > 0 and elapsed_time > 0 else 0
            logger.info(
                f"[{self.request.id}] PROCESS TASK: File processing completed. Processing speed {processing_speed:.2f} MB/s")

        elif source_type == "minio":
            logger.info(
                f"[{self.request.id}] PROCESS TASK: Processing from URL: {source}")

            reported_file_size = get_file_size(source_type, source)
            if reported_file_size > 0:
                _validate_file_size(reported_file_size, source)

            # Measure MinIO fetch time in process worker logs for observability
            fetch_start = time.perf_counter()
            file_stream = get_file_stream_raw(source)
            if file_stream is None:
                raise FileNotFoundError(
                    f"Unable to fetch file from URL: {source}")
            try:
                file_data = file_stream.read(MAX_DATA_PROCESS_FILE_SIZE_BYTES + 1)
            finally:
                try:
                    file_stream.close()
                except Exception:
                    pass
            _validate_file_size(len(file_data), source)
            file_size_mb = len(file_data) / (1024 * 1024)
            fetch_elapsed = time.perf_counter() - fetch_start
            logger.info(
                f"[{self.request.id}] PROCESS TASK: MinIO fetch done in {fetch_elapsed:.3f}s, "
                f"bytes={len(file_data)}")

            split_async, chunks, split_chunk_count = _process_source_with_split(
                request_id=self.request.id,
                source=source,
                source_type=source_type,
                task_id=task_id,
                chunking_strategy=chunking_strategy,
                index_name=index_name,
                original_filename=original_filename,
                embedding_model_id=embedding_model_id,
                tenant_id=tenant_id,
                params=params,
                file_data=file_data,
            )
            elapsed_time = time.time() - start_time
            logger.info(
                f"[{self.request.id}] PROCESS TASK: URL processing completed in {elapsed_time:.2f}s")

        else:
            # For other source types, implement accordingly
            raise NotImplementedError(
                f"Source type '{source_type}' not yet supported")

        if split_async:
            chunk_count = split_chunk_count or 0
            if chunk_count == 0:
                raise _build_no_valid_chunks_error(
                    split_async=True,
                    index_name=index_name,
                    source=source,
                    original_filename=original_filename,
                )
            # For async split, chunks are persisted in Redis; count image-metadata chunks from cached payload.
            try:
                if REDIS_BACKEND_URL:
                    import redis
                    redis_key = f"dp:{task_id}:chunks"
                    client = redis.Redis.from_url(
                        REDIS_BACKEND_URL, decode_responses=True)
                    cached = client.get(redis_key)
                    if cached:
                        cached_chunks = json.loads(cached)
                        if isinstance(cached_chunks, list):
                            image_metadata_chunk_count = _count_image_metadata_chunks(
                                cached_chunks)
            except Exception as image_count_exc:
                logger.warning(
                    f"[{self.request.id}] PROCESS TASK: Failed counting image metadata chunks for async split: {image_count_exc}")
        else:
            chunk_count = len(chunks) if chunks else 0
            if chunk_count == 0:
                raise _build_no_valid_chunks_error(
                    split_async=False,
                    index_name=index_name,
                    source=source,
                    original_filename=original_filename,
                )
            image_metadata_chunk_count = _count_image_metadata_chunks(chunks)

        _validate_chunk_count(
            chunk_count,
            original_filename or source,
        )

        logger.info(
            f"[{self.request.id}] PROCESS TASK: Chunk composition: total={chunk_count}, "
            f"image_metadata={image_metadata_chunk_count}, text={max(0, chunk_count - image_metadata_chunk_count)}")

        # Update task state to SUCCESS after Ray processing completes
        # This transitions from STARTED (PROCESSING) to SUCCESS (WAIT_FOR_FORWARDING)
        self.update_state(
            state=states.SUCCESS,
            meta={
                'chunks_count': chunk_count,
                'processing_time': elapsed_time,
                'source': source,
                'index_name': index_name,
                'original_filename': original_filename,
                'task_name': 'process',
                'stage': 'text_extracted',
                'file_size_mb': file_size_mb,
                'processing_speed_mb_s': file_size_mb / elapsed_time if file_size_mb > 0 and elapsed_time > 0 else 0
            }
        )

        logger.info(
            f"[{self.request.id}] PROCESS TASK: Processing complete, waiting for forward task")

        # Prepare data for the next task in the chain; pass redis_key
        returned_data = {
            'redis_key': f"dp:{task_id}:chunks",
            'chunks': None,
            'source': source,
            'index_name': index_name,
            'original_filename': original_filename,
            'task_id': task_id,
            'split_async': split_async,
            'image_metadata_chunk_count': image_metadata_chunk_count,
        }

        return returned_data

    except Exception as e:
        logger.error(f"Error processing file {source}: {str(e)}")
        redis_key = f"dp:{task_id}:chunks"
        try:
            if not _is_split_cancelled(redis_key):
                _mark_split_failed(redis_key, str(e))
        except Exception as marker_exc:
            logger.warning(
                "Failed to publish terminal process failure for '%s': %s",
                redis_key,
                marker_exc,
            )
        _cleanup_split_payloads(redis_key, keep_cancelled=True)
        # task_id is already defined at the start of the function
        try:
            # Try to parse the exception as JSON (it might be our custom JSON error)
            error_message = str(e)
            parsed_error = None

            try:
                parsed_error = json.loads(error_message)
                if isinstance(parsed_error, dict):
                    error_message = parsed_error.get("message", error_message)
                    logger.debug(
                        f"Parsed JSON error for task {task_id}"
                    )
            except (json.JSONDecodeError, TypeError):
                # Not a JSON string, use as-is
                logger.debug(
                    f"Exception is not JSON format for task {task_id}, using raw message"
                )

            # Build error_info for re-raising
            error_info = {
                "message": error_message,
                "index_name": index_name,
                "task_name": "process",
                "source": source,
                "original_filename": original_filename,
            }

            # Extract error code from parsed error or error message
            error_code = extract_error_code(error_message, parsed_error)
            if error_code:
                error_info["error_code"] = error_code

            # Store only error code (if available) or raw error message
            if error_code:
                reason_to_store = json.dumps({
                    "error_code": error_code
                }, ensure_ascii=False)
            else:
                # Fallback: store raw error message (truncated if too long)
                reason_to_store = error_message
                if len(reason_to_store) > 200:
                    reason_to_store = reason_to_store[:200] + "..."

            # Save error info to Redis BEFORE re-raising
            logger.info(
                f"Attempting to save error info for task {task_id} with reason: {reason_to_store[:100]}..."
            )
            save_error_to_redis(task_id, reason_to_store, start_time)

            self.update_state(
                meta={
                    "source": error_info.get("source", ""),
                    "index_name": error_info.get("index_name", ""),
                    "task_name": error_info.get("task_name", ""),
                    "original_filename": error_info.get(
                        "original_filename", ""
                    ),
                    "custom_error": error_info.get("message", str(e)),
                    "stage": "text_extraction_failed",
                }
            )
            raise Exception(json.dumps(error_info, ensure_ascii=False))
        except Exception as ex:
            logger.error(f"Error serializing process exception: {str(ex)}")
            # Try to save error even if serialization fails
            try:
                error_message = str(e)
                parsed_error = None

                try:
                    parsed_error = json.loads(error_message)
                    if isinstance(parsed_error, dict):
                        error_message = parsed_error.get(
                            "message", error_message
                        )
                        logger.debug(
                            "Fallback serialization: parsed JSON error for task "
                            f"{task_id}"
                        )
                except (json.JSONDecodeError, TypeError):
                    logger.debug(
                        "Fallback serialization: exception is not JSON format "
                        f"for task {task_id}, using raw message"
                    )
                    parsed_error = None

                # Extract error code from parsed error or error message
                error_code = extract_error_code(error_message, parsed_error)

                # Store only error code (if available) or raw error message
                if error_code:
                    reason_to_store = json.dumps({
                        "error_code": error_code
                    }, ensure_ascii=False)
                else:
                    # Fallback: store raw error message (truncated if too long)
                    reason_to_store = error_message
                    if len(reason_to_store) > 200:
                        reason_to_store = reason_to_store[:200] + "..."

                save_error_to_redis(task_id, reason_to_store, start_time)
            except Exception:
                pass
            self.update_state(
                meta={
                    "custom_error": str(e),
                    "stage": "text_extraction_failed",
                }
            )
            raise


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.forward', queue='forward_q')
def forward(
        self,
        processed_data: Dict,
        index_name: str,
        source: str,
        source_type: str = 'minio',
        original_filename: Optional[str] = None,
        authorization: Optional[str] = None
) -> Dict:
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

    try:
        ctx = _init_forward_context(
            task_id=task_id,
            request_id=str(self.request.id),
            start_time=start_time,
            source=source,
            index_name=index_name,
            source_type=source_type,
            original_filename=original_filename,
        )

        # Before doing any heavy work, check whether this task has been explicitly cancelled.
        if _is_forward_task_cancelled(ctx):
            logger.info(
                f"[{self.request.id}] FORWARD TASK: Detected cancellation flag for task {task_id}; "
                f"skipping chunk forwarding for source '{source}' in index '{index_name}'."
            )
            _cleanup_forward_chunks(processed_data)
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
                "process_source": chunk.get("process_source", "Unstructured"),
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
        forward_deadline = time.monotonic() + DP_FORWARD_FILE_TIMEOUT_S

        def _remaining_forward_time() -> float:
            remaining = forward_deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Forward task exceeded the {DP_FORWARD_FILE_TIMEOUT_S}s file deadline"
                )
            return remaining

        # Update task state with total chunks before starting vectorization
        self.update_state(
            state=states.STARTED,
            meta={
                'source': original_source,
                'index_name': original_index_name,
                'original_filename': filename,
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
                timeout_s=_remaining_forward_time(),
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
            total_indexed = 0
            total_submitted = 0
            for idx, batch in enumerate(batches, start=1):
                if _is_forward_task_cancelled(ctx):
                    raise RuntimeError(
                        f"Forward task {task_id} was cancelled while indexing"
                    )
                batch_result = _send_chunks_to_es(
                    chunks=batch,
                    index_name=original_index_name,
                    authorization=authorization,
                    task_id=None,
                    source=original_source,
                    original_filename=original_filename,
                    large_mode=True,
                    timeout_s=_remaining_forward_time(),
                )
                if not isinstance(batch_result, dict) or not batch_result.get("success"):
                    error_message = (
                        batch_result.get("message", "Unknown error from main_server")
                        if isinstance(batch_result, dict)
                        else "Unexpected API response"
                    )
                    raise _build_forward_error(
                        message=f"Batch {idx}/{total_batches} failed: {error_message}",
                        index_name=original_index_name,
                        source=original_source,
                        original_filename=original_filename,
                    )
                batch_indexed = int(batch_result.get("total_indexed", 0) or 0)
                batch_submitted = int(
                    batch_result.get("total_submitted", len(batch)) or 0
                )
                if batch_indexed < batch_submitted:
                    raise _build_forward_error(
                        message=(
                            f"Batch {idx}/{total_batches} indexed "
                            f"{batch_indexed}/{batch_submitted} chunks"
                        ),
                        index_name=original_index_name,
                        source=original_source,
                        original_filename=original_filename,
                    )
                total_indexed += batch_indexed
                total_submitted += batch_submitted
                try:
                    get_redis_service().save_progress_info(
                        task_id,
                        total_indexed,
                        total_chunks,
                    )
                except Exception as progress_exc:
                    logger.warning(
                        "[%s] FORWARD TASK: Failed updating batch progress: %s",
                        self.request.id,
                        progress_exc,
                    )
            es_result = {
                "success": True,
                "total_indexed": total_indexed,
                "total_submitted": total_submitted,
            }
        logger.debug(
            f"[{self.request.id}] FORWARD TASK: API response from main_server for source '{original_source}': {es_result}")

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
                'task_name': 'forward',
                'es_result': es_result,
                'stage': 'completed',
                'total_chunks': total_chunks,
                'processed_chunks': final_processed
            }
        )

        logger.info(
            f"[{self.request.id}] FORWARD TASK: Successfully stored {len(chunks)} chunks to index {original_index_name} in {end_time - start_time:.2f}s")

        _cleanup_forward_chunks(processed_data)
        return {
            'task_id': task_id,
            'source': original_source,
            'index_name': original_index_name,
            'original_filename': original_filename,
            'chunks_stored': len(chunks),
            'storage_time': end_time - start_time,
            'es_result': es_result
        }
    except Exception as e:
        # If it's an Exception, all go here (including our custom JSON message)
        # Important: if this is a Celery Retry, re-raise immediately without recording error_code
        if isinstance(e, Retry):
            raise

        _cleanup_forward_chunks(processed_data)
        task_id = self.request.id
        try:
            error_info = json.loads(str(e))
            error_message = error_info.get('message', str(e))
            logger.error(
                f"Error forwarding chunks for index '{error_info.get('index_name', '')}': {error_message}")

            # Extract error code from parsed error or error message
            error_code = extract_error_code(error_message, error_info)

            # Store only error code (if available) or raw error message
            if error_code:
                reason_to_store = json.dumps({
                    "error_code": error_code
                }, ensure_ascii=False)
            else:
                # Fallback: store raw error message (truncated if too long)
                reason_to_store = error_message
                if len(reason_to_store) > 200:
                    reason_to_store = reason_to_store[:200] + "..."

            # Save error info to Redis BEFORE re-raising
            logger.info(
                f"Attempting to save error info for task {task_id} with reason: {reason_to_store[:100]}...")
            save_error_to_redis(task_id, reason_to_store, start_time)

            self.update_state(
                meta={
                    'source': error_info.get('source', ''),
                    'index_name': error_info.get('index_name', ''),
                    'task_name': error_info.get('task_name', ''),
                    'original_filename': error_info.get('original_filename', ''),
                    'custom_error': error_message,
                    'stage': 'forward_task_failed'
                }
            )
        except Exception:
            logger.error(f"Error forwarding chunks: {str(e)}")
            # Try to save error even if parsing fails
            try:
                error_message = str(e)
                # Extract error code from error message
                error_code = extract_error_code(error_message, None)

                # Store only error code (if available) or raw error message
                if error_code:
                    reason_to_store = json.dumps({
                        "error_code": error_code
                    }, ensure_ascii=False)
                else:
                    # Fallback: store raw error message (truncated if too long)
                    reason_to_store = error_message
                    if len(reason_to_store) > 200:
                        reason_to_store = reason_to_store[:200] + "..."

                save_error_to_redis(task_id, reason_to_store, start_time)
            except Exception:
                pass
            self.update_state(
                meta={
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
def cleanup_source(
    self,
    forward_result: Dict[str, Any],
    authorization: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Conditionally delete the MinIO source file after successful indexing.

    If the knowledge base is configured with preserve_source_file=false, call:
    DELETE /indices/{index_name}/documents?path_or_url=...&scope=source_only

    authorization is passed as a Celery signature kwarg (not via forward_result)
    so tokens are not persisted in task result payloads.
    """
    index_name = (forward_result or {}).get("index_name")
    source = (forward_result or {}).get("source")

    cleanup_info: Dict[str, Any] = {
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


def submit_process_forward_chain(
        *,
        source: str,
        source_type: str,
        chunking_strategy: str,
        index_name: Optional[str] = None,
        original_filename: Optional[str] = None,
        authorization: Optional[str] = None,
        embedding_model_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
) -> str:
    """
    Build and enqueue a Celery chain: process -> forward.

    Returns:
        Celery chain task ID, or empty string if enqueue failed.
    """
    task_chain = chain(
        process.s(
            source=source,
            source_type=source_type,
            chunking_strategy=chunking_strategy,
            index_name=index_name,
            original_filename=original_filename,
            embedding_model_id=embedding_model_id,
            tenant_id=tenant_id
        ).set(queue='process_q'),
        forward.s(
            index_name=index_name,
            source=source,
            source_type=source_type,
            original_filename=original_filename,
            authorization=authorization
        ).set(queue='forward_q'),
        cleanup_source.s(authorization=authorization).set(queue='forward_q'),
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
        index_name: Optional[str] = None,
        original_filename: Optional[str] = None,
        authorization: Optional[str] = None,
        embedding_model_id: Optional[int] = None,
        tenant_id: Optional[str] = None
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
    logger.info(
        f"Starting processing chain for {source}, original_filename={original_filename}, strategy={chunking_strategy}, index={index_name}, model_id={embedding_model_id}")

    chain_id = submit_process_forward_chain(
        source=source,
        source_type=source_type,
        chunking_strategy=chunking_strategy,
        index_name=index_name,
        original_filename=original_filename,
        authorization=authorization,
        embedding_model_id=embedding_model_id,
        tenant_id=tenant_id,
    )
    if chain_id:
        logger.info(f"Created task chain ID: {chain_id}")
    return chain_id


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.process_sync')
def process_sync(
        self,
        source: str,
        source_type: str,
        chunking_strategy: str = "basic",
        timeout: int = 30,
        **params
) -> Dict:
    """
    Synchronous process task that returns text directly (for real-time API)

    Args:
        source: Source file path, URL, or text content
        source_type: source of the file("local", "minio")
        chunking_strategy: Strategy for chunking the document
        timeout: Timeout for the operation
        **params: Additional parameters

    Returns:
        Dict containing the extracted text and metadata
    """
    start_time = time.time()
    task_id = self.request.id

    # Check if we're in a valid Celery context before updating state
    is_celery_context = hasattr(
        self, 'request') and self.request.id is not None

    # Update task state to PROCESSING only if in Celery context
    if is_celery_context:
        self.update_state(
            state=states.STARTED,
            meta={
                'source': source,
                'source_type': source_type,
                'task_name': 'process_sync',
                'start_time': start_time,
                'sync_mode': True
            }
        )

    logger.info(
        f"Synchronous processing file: {source} with strategy: {chunking_strategy}")

    # Get the data processor instance
    actor = get_ray_actor()

    try:
        # Process the file based on the source type
        if source_type == "local":
            if not os.path.exists(source):
                raise FileNotFoundError(f"File does not exist: {source}")
            _validate_file_size(os.path.getsize(source), source)
            # The unified actor call, mapping 'file' source_type to 'local' destination
            chunks_ref = actor.process_file.remote(
                source,
                chunking_strategy,
                destination=source_type,
                task_id=task_id,
                **params
            )

            chunks = _get_ray_result(
                chunks_ref,
                actor,
                operation=f"synchronously process '{source}'",
                timeout_s=timeout,
            )
            _validate_chunk_count(len(chunks or []), source)
        else:
            raise NotImplementedError(
                f"Source type '{source_type}' not yet implemented")

        end_time = time.time()
        elapsed_time = end_time - start_time

        # Extract text from chunks
        text_content = "\n\n".join(
            [chunk.get("content", "") for chunk in chunks])

        # Update task state to COMPLETE only if in Celery context
        if is_celery_context:
            self.update_state(
                state=states.SUCCESS,
                meta={
                    'chunks_count': len(chunks),
                    'processing_time': elapsed_time,
                    'source': source,
                    'task_name': 'process_sync',
                    'text_length': len(text_content),
                    'sync_mode': True
                }
            )

        logger.info(
            f"Synchronously processed {len(chunks)} chunks from {source} in {elapsed_time:.2f}s")

        return {
            'task_id': task_id,
            'source': source,
            'text': text_content,
            'chunks': chunks,
            'chunks_count': len(chunks),
            'processing_time': elapsed_time,
            'text_length': len(text_content)
        }

    except Exception as e:
        logger.error(f"Error synchronously processing file {source}: {str(e)}")

        # Update task state to FAILURE with custom metadata only if in Celery context
        if is_celery_context:
            self.update_state(
                meta={
                    'source': source,
                    'task_name': 'process_sync',
                    'custom_error': str(e),
                    'sync_mode': True,
                    'stage': 'sync_processing_failed'
                }
            )

        # Re-raise to let Celery handle exception serialization
        raise
