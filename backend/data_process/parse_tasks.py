"""Celery tasks that execute CPU-heavy parsing in prefork children.

This module intentionally has no top-level import of the SDK Core or any
parsing library. The parser runtime imports those dependencies only inside a
prefork child immediately before the task body runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional

from celery import Task, chord, group, states
from celery.exceptions import Ignore

from consts.const import (
    DP_FILE_SPLIT_SIZE_MB,
    DP_PART_PROCESSOR_COUNT,
    DP_REDIS_CHUNKS_WAIT_TIMEOUT_S,
    REDIS_BACKEND_URL,
)
from utils.knowledge_ingestion_errors import classify_ingestion_exception
from utils.knowledge_telemetry import trace_knowledge_operation

from .app import app
from .parser_runtime import ensure_parser_runtime

logger = logging.getLogger("data_process.parse_tasks")
CHUNKS_TTL_SECONDS = 2 * 60 * 60
BOOTSTRAP_KEY_TTL_SECONDS = max(DP_REDIS_CHUNKS_WAIT_TIMEOUT_S * 2, 60)


class ParserTask(Task):
    """Base task that guarantees parser initialization inside the child."""

    abstract = True
    acks_late = True
    reject_on_worker_lost = True

    def before_start(self, task_id: str, args: tuple, kwargs: dict, **_kwargs: Any) -> None:
        ensure_parser_runtime()
        logger.debug("Parser child ready pid=%s task_id=%s", os.getpid(), task_id)


def _redis_client():
    if not REDIS_BACKEND_URL:
        raise RuntimeError("REDIS_BACKEND_URL is not configured")
    import redis

    return redis.Redis.from_url(REDIS_BACKEND_URL, decode_responses=True)


def _store_json_atomically(key: str, value: Any, ttl_seconds: int = CHUNKS_TTL_SECONDS) -> None:
    client = _redis_client()
    pending_key = f"{key}:pending:{os.getpid()}:{time.time_ns()}"
    serialized = json.dumps(value, ensure_ascii=False)
    client.set(pending_key, serialized, ex=ttl_seconds)
    client.rename(pending_key, key)


def store_chunks_atomically(redis_key: str, chunks: List[Dict[str, Any]]) -> None:
    """Persist complete chunks before publishing the ready marker."""
    client = _redis_client()
    ready_key = f"{redis_key}:ready"
    client.delete(ready_key)
    _store_json_atomically(redis_key, chunks)
    client.set(ready_key, "1", ex=CHUNKS_TTL_SECONDS)


def load_chunks_from_redis(redis_key: str) -> List[Dict[str, Any]]:
    client = _redis_client()
    cached = client.get(redis_key)
    if not cached:
        return []
    value = json.loads(cached)
    return value if isinstance(value, list) else []


def cleanup_parser_artifacts(
    task_id: str,
    part_refs: Optional[Iterable[Dict[str, Any]]] = None,
    *,
    include_final: bool = False,
) -> None:
    """Best-effort idempotent cleanup for parser intermediate data."""
    client = _redis_client()
    refs = list(part_refs or [])
    keys: List[str] = []
    if include_final:
        keys.extend([f"dp:{task_id}:chunks", f"dp:{task_id}:chunks:ready"])
    for part_ref in refs:
        part_index = part_ref.get("part_index")
        if part_index is not None:
            keys.append(f"dp:{task_id}:part:{part_index}:chunks")
    if keys:
        client.delete(*keys)

    from database.attachment_db import delete_file

    for part_ref in refs:
        uri = part_ref.get("uri")
        if uri:
            try:
                delete_file(uri)
            except Exception:
                logger.warning("Failed to clean parser part object task_id=%s uri=%s", task_id, uri, exc_info=True)


def _upload_part(task_id: str, index: int, filename: str, data: bytes) -> Dict[str, Any]:
    from database.attachment_db import build_s3_url, upload_fileobj

    object_name = f"data-process-tmp/{task_id}/parts/{index}"
    result = upload_fileobj(
        file_obj=BytesIO(data),
        file_name=filename,
        prefix="data-process-tmp",
        object_name=object_name,
        generate_presigned_url=False,
        file_size=len(data),
    )
    if not result.get("success", False):
        raise RuntimeError(f"Failed to upload parser part {index}: {result.get('error', 'unknown error')}")
    return {
        "uri": build_s3_url(object_name),
        "part_index": index,
        "total_parts": 0,
        "size_bytes": len(data),
        "checksum": hashlib.sha256(data).hexdigest(),
        "filename": filename,
        "source_type": "minio",
    }


def _mark_lifecycle(task_id: str, *, status: str, stage: str, source: str, index_name: Optional[str],
                    tenant_id: Optional[str], file_id: Optional[str], **fields: Any) -> None:
    if not index_name:
        return
    try:
        from database.knowledge_file_lifecycle_db import get_file_record, transition_file_record

        record = None
        if file_id and tenant_id:
            record = get_file_record(
                file_id=file_id, tenant_id=tenant_id, index_name=index_name, include_hidden=True
            )
        if not record:
            record = get_file_record(
                tenant_id=tenant_id, index_name=index_name, object_name=source, include_hidden=True
            )
        if not record or record.get("status") in {"DELETE_REQUESTED", "DELETED"}:
            return
        transition_file_record(
            record["file_id"],
            status=status,
            stage=stage,
            expected_statuses=(record.get("status"),),
            **fields,
        )
    except Exception:
        logger.warning("Parser lifecycle update failed task_id=%s", task_id, exc_info=True)


def _error_payload(message: str, source: str, index_name: Optional[str], filename: Optional[str]) -> Exception:
    return Exception(json.dumps({
        "message": message,
        "index_name": index_name,
        "task_name": "process",
        "source": source,
        "original_filename": filename,
        "error_code": classify_ingestion_exception(message, "PROCESS").error_code,
    }, ensure_ascii=False))


def _count_image_metadata_chunks(chunks: Optional[List[Dict[str, Any]]]) -> int:
    if not chunks:
        return 0
    return sum(
        1
        for chunk in chunks
        if isinstance(chunk, dict)
        and (
            chunk.get("process_source")
            or chunk.get("metadata", {}).get("process_source")
        )
        == "UniversalImageExtractor"
    )


@app.task(bind=True, base=ParserTask, name="data_process.tasks.parser_bootstrap", queue="parse_q")
def parser_bootstrap(self, worker_generation: str, target_children: int) -> Dict[str, Any]:
    """Warm one distinct child and coordinate parser worker readiness."""
    runtime = ensure_parser_runtime()
    client = _redis_client()
    key = f"dp:parser:bootstrap:{worker_generation}"
    client.sadd(key, str(os.getpid()))
    client.expire(key, BOOTSTRAP_KEY_TTL_SECONDS)
    deadline = time.time() + DP_REDIS_CHUNKS_WAIT_TIMEOUT_S
    while client.scard(key) < target_children:
        if time.time() >= deadline:
            raise TimeoutError(
                f"Parser bootstrap timed out waiting for {target_children} children; "
                f"ready={client.scard(key)}"
            )
        time.sleep(0.2)
    client.set(f"{key}:ready", "1", ex=BOOTSTRAP_KEY_TTL_SECONDS)
    return {
        "worker_generation": worker_generation,
        "pid": os.getpid(),
        "preload_models": runtime.preload_models,
        "ready": True,
    }


@app.task(bind=True, base=ParserTask, name="data_process.tasks.process_part", queue="parse_q")
@trace_knowledge_operation("knowledge.process.part", "process.prefork_part")
def process_part(
    self,
    part_ref: Dict[str, Any],
    filename: str,
    chunking_strategy: str,
    part_redis_key: str,
    source: Optional[str] = None,
    source_type: Optional[str] = None,
    index_name: Optional[str] = None,
    file_id: Optional[str] = None,
    model_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
    parser_task_id: Optional[str] = None,
    all_part_refs: Optional[List[Dict[str, Any]]] = None,
    **params: Any,
) -> Dict[str, Any]:
    """Parse one object-storage part; the task payload contains only a ref."""
    parent_task_id = parser_task_id or self.request.id
    refs_for_cleanup = all_part_refs or [part_ref]
    try:
        runtime = ensure_parser_runtime()
        data = runtime.read_source(part_ref["uri"], "minio")
        chunks = runtime.process_source(
            file_data=data,
            filename=filename,
            chunking_strategy=chunking_strategy,
            task_id=parent_task_id,
            model_id=model_id,
            tenant_id=tenant_id,
            params=params,
        )
        store_chunks_atomically(part_redis_key, chunks)
        return {
            "part_redis_key": part_redis_key,
            "part_index": part_ref["part_index"],
            "part_uri": part_ref["uri"],
            "chunks_count": len(chunks),
        }
    except Exception as exc:
        logger.exception("Parser part failed task_id=%s part=%s", parent_task_id, part_ref.get("part_index"))
        try:
            cleanup_parser_artifacts(parent_task_id, refs_for_cleanup)
        except Exception:
            logger.warning("Parser part cleanup failed task_id=%s", parent_task_id, exc_info=True)
        classified = classify_ingestion_exception(exc, "PROCESS")
        try:
            from .tasks import _redis_error_reason, save_error_to_redis

            save_error_to_redis(parent_task_id, _redis_error_reason(classified), time.time())
        except Exception:
            logger.warning("Parser part error persistence failed task_id=%s", parent_task_id, exc_info=True)
        _mark_lifecycle(
            parent_task_id,
            status="FAILED",
            stage="PROCESS",
            source=source or "",
            index_name=index_name,
            tenant_id=tenant_id,
            file_id=file_id,
            process_task_id=parent_task_id,
            error_code=classified.error_code,
            error_message=classified.error_message,
            error_stage="PROCESS",
            failed_at=datetime.utcnow(),
        )
        raise


@app.task(bind=True, base=Task, name="data_process.tasks.aggregate_parts", queue="process_q")
def aggregate_parts(
    self,
    parts_results: List[Any],
    redis_key: Optional[str] = None,
    **metadata: Any,
) -> Dict[str, Any]:
    """Compatibility aggregation task that publishes a Redis reference.

    Older callers may still submit inline part lists.  We accept those inputs,
    but never return the merged chunk payload through Celery's result backend.
    """
    merged: List[Dict[str, Any]] = []
    for result in parts_results or []:
        if isinstance(result, dict) and result.get("part_redis_key"):
            merged.extend(load_chunks_from_redis(result["part_redis_key"]))
        elif isinstance(result, list):
            merged.extend(result)
    output_key = redis_key or f"dp:{self.request.id}:chunks"
    if merged:
        store_chunks_atomically(output_key, merged)
    return {
        "redis_key": output_key,
        "chunks": None,
        "chunks_count": len(merged),
        "image_metadata_chunk_count": _count_image_metadata_chunks(merged),
        **metadata,
    }


@app.task(bind=True, base=Task, name="data_process.tasks.aggregate_store_chunks", queue="process_q")
@trace_knowledge_operation("knowledge.process.redis_aggregate", "process.redis")
def aggregate_store_chunks(
    self,
    parts_results: List[Dict[str, Any]],
    redis_key: str,
    source: Optional[str] = None,
    index_name: Optional[str] = None,
    original_filename: Optional[str] = None,
    task_id: Optional[str] = None,
    part_refs: Optional[List[Dict[str, Any]]] = None,
    file_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    **metadata: Any,
) -> Dict[str, Any]:
    """Read part keys, aggregate in order, then publish the final ref."""
    task_id = task_id or self.request.id
    try:
        ordered = sorted(parts_results or [], key=lambda value: int(value.get("part_index", 0)))
        if len(ordered) != len(parts_results or []):
            raise RuntimeError("Parser part result is missing")
        merged: List[Dict[str, Any]] = []
        for result in ordered:
            part_key = result.get("part_redis_key")
            if not part_key:
                raise RuntimeError("Parser part result has no Redis key")
            merged.extend(load_chunks_from_redis(part_key))
        if not merged:
            raise _error_payload("Parser completed but produced 0 chunks", source or "", index_name, original_filename)
        store_chunks_atomically(redis_key, merged)
        client = _redis_client()
        for result in ordered:
            if result.get("part_redis_key"):
                client.delete(result["part_redis_key"], f"{result['part_redis_key']}:ready")
        cleanup_parser_artifacts(task_id, part_refs)
        return {
            "redis_key": redis_key,
            "chunks": None,
            "chunks_count": len(merged),
            "source": source,
            "index_name": index_name,
            "original_filename": original_filename,
            "task_id": task_id,
            "split_async": True,
            "file_id": file_id,
            "tenant_id": tenant_id,
            **metadata,
        }
    except Exception as exc:
        logger.exception("Parser part aggregation failed task_id=%s source=%s", task_id, source)
        try:
            cleanup_parser_artifacts(task_id, part_refs, include_final=True)
        except Exception:
            logger.warning("Parser aggregate cleanup failed task_id=%s", task_id, exc_info=True)
        classified = classify_ingestion_exception(exc, "PROCESS")
        try:
            from .tasks import _redis_error_reason, save_error_to_redis

            save_error_to_redis(task_id, _redis_error_reason(classified), time.time())
        except Exception:
            logger.warning("Parser aggregate error persistence failed task_id=%s", task_id, exc_info=True)
        _mark_lifecycle(
            task_id,
            status="FAILED",
            stage="PROCESS",
            source=source or "",
            index_name=index_name,
            tenant_id=tenant_id,
            file_id=file_id,
            process_task_id=task_id,
            error_code=classified.error_code,
            error_message=classified.error_message,
            error_stage="PROCESS",
            failed_at=datetime.utcnow(),
        )
        raise


@app.task(bind=True, base=ParserTask, name="data_process.tasks.process", queue="parse_q")
@trace_knowledge_operation("knowledge.process", "process")
def process(
    self,
    source: str,
    source_type: str,
    chunking_strategy: str = "basic",
    index_name: Optional[str] = None,
    original_filename: Optional[str] = None,
    embedding_model_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
    **params: Any,
) -> Dict[str, Any]:
    """Parse a source in a prefork child and return a small chunks reference."""
    started = time.perf_counter()
    task_id = self.request.id
    file_id = params.pop("file_id", None)
    telemetry_context = params.pop("telemetry_context", None)
    part_refs: List[Dict[str, Any]] = []
    self.update_state(
        state=states.STARTED,
        meta={"task_name": "process", "stage": "extracting_text", "source": source},
    )
    _mark_lifecycle(
        task_id, status="PROCESSING", stage="PROCESS", source=source, index_name=index_name,
        tenant_id=tenant_id, file_id=file_id, process_task_id=task_id,
    )
    try:
        runtime = ensure_parser_runtime()
        filename = original_filename or os.path.basename(source)
        file_data = runtime.read_source(source, source_type)
        split_threshold = DP_FILE_SPLIT_SIZE_MB * 1024 * 1024
        if len(file_data) > split_threshold and DP_PART_PROCESSOR_COUNT > 1:
            parts = runtime.split_source(
                file_data=file_data,
                filename=filename,
                target_parts=DP_PART_PROCESSOR_COUNT,
                params=params,
            )
            if len(parts) > 1:
                part_refs = [_upload_part(task_id, idx, filename, part) for idx, part in enumerate(parts)]
                for part_ref in part_refs:
                    part_ref["total_parts"] = len(part_refs)
                part_sigs = [
                    process_part.s(
                        part_ref=part_ref,
                        filename=filename,
                        chunking_strategy=chunking_strategy,
                        part_redis_key=f"dp:{task_id}:part:{idx}:chunks",
                        source=source,
                        source_type=source_type,
                        index_name=index_name,
                        file_id=file_id,
                        model_id=embedding_model_id,
                        tenant_id=tenant_id,
                        parser_task_id=task_id,
                        all_part_refs=part_refs,
                        **params,
                    ).set(queue="parse_q")
                    for idx, part_ref in enumerate(part_refs)
                ]
                callback = aggregate_store_chunks.s(
                    redis_key=f"dp:{task_id}:chunks",
                    source=source,
                    index_name=index_name,
                    original_filename=original_filename,
                    task_id=task_id,
                    part_refs=part_refs,
                    file_id=file_id,
                    tenant_id=tenant_id,
                    telemetry_context=telemetry_context,
                ).set(queue="process_q")
                logger.info("Dispatching %s parser parts task_id=%s", len(part_sigs), task_id)
                return self.replace(chord(group(part_sigs), callback))

        chunks = runtime.process_source(
            file_data=file_data,
            filename=filename,
            chunking_strategy=chunking_strategy,
            task_id=task_id,
            model_id=embedding_model_id,
            tenant_id=tenant_id,
            params=params,
        )
        if not chunks:
            raise _error_payload("Parser completed but produced 0 chunks", source, index_name, original_filename)
        redis_key = f"dp:{task_id}:chunks"
        store_chunks_atomically(redis_key, chunks)
        elapsed = time.perf_counter() - started
        result = {
            "redis_key": redis_key,
            "chunks": None,
            "chunks_count": len(chunks),
            "image_metadata_chunk_count": _count_image_metadata_chunks(chunks),
            "source": source,
            "index_name": index_name,
            "original_filename": original_filename,
            "task_id": task_id,
            "split_async": False,
            "file_id": file_id,
            "telemetry_context": telemetry_context or {},
            "processing_time": elapsed,
        }
        self.update_state(
            state=states.SUCCESS,
            meta={"task_name": "process", "stage": "text_extracted", "chunks_count": len(chunks)},
        )
        _mark_lifecycle(
            task_id, status="FORWARDING", stage="FORWARD", source=source, index_name=index_name,
            tenant_id=tenant_id, file_id=file_id, process_task_id=task_id,
        )
        return result
    except Ignore:
        # Celery's replace() raises Ignore after handing execution to the chord.
        raise
    except Exception as exc:
        logger.exception("Parser failed task_id=%s source=%s", task_id, source)
        try:
            cleanup_parser_artifacts(task_id, part_refs)
        except Exception:
            logger.warning("Parser artifact cleanup failed task_id=%s", task_id, exc_info=True)
        parsed_error: Any = exc
        try:
            parsed_candidate = json.loads(str(exc))
            if isinstance(parsed_candidate, dict):
                parsed_error = parsed_candidate
        except (TypeError, ValueError):
            pass
        classified = classify_ingestion_exception(parsed_error, "PROCESS")
        error_info = {
            "message": (parsed_error.get("message") if isinstance(parsed_error, dict) else None)
            or classified.error_message
            or str(exc),
            "index_name": index_name,
            "task_name": "process",
            "source": source,
            "original_filename": original_filename,
            "file_id": file_id,
        }
        if classified.error_code:
            error_info["error_code"] = classified.error_code
        try:
            # Keep the existing task-error lookup contract while avoiding a
            # top-level import cycle between the forwarding and parser task
            # modules.
            from .tasks import _redis_error_reason, save_error_to_redis

            save_error_to_redis(task_id, _redis_error_reason(classified), started)
        except Exception:
            logger.warning("Parser error persistence failed task_id=%s", task_id, exc_info=True)
        _mark_lifecycle(
            task_id, status="FAILED", stage="PROCESS", source=source, index_name=index_name,
            tenant_id=tenant_id, file_id=file_id, process_task_id=task_id,
            error_code=classified.error_code,
            error_message=classified.error_message,
            error_stage="PROCESS",
            failed_at=datetime.utcnow(),
        )
        self.update_state(
            meta={
                "source": source,
                "index_name": index_name,
                "task_name": "process",
                "original_filename": original_filename,
                "file_id": file_id,
                "custom_error": error_info["message"],
                "stage": "text_extraction_failed",
            }
        )
        raise Exception(json.dumps(error_info, ensure_ascii=False)) from exc


@app.task(bind=True, base=ParserTask, name="data_process.tasks.process_sync", queue="parse_q")
@trace_knowledge_operation("knowledge.process", "process.sync")
def process_sync(
    self,
    source: str,
    source_type: str,
    chunking_strategy: str = "basic",
    timeout: int = 30,
    **params: Any,
) -> Dict[str, Any]:
    """Synchronous parser task; return a Redis reference, never chunks payload."""
    started = time.perf_counter()
    task_id = self.request.id
    self.update_state(
        state=states.STARTED,
        meta={"task_name": "process_sync", "sync_mode": True, "source": source},
    )
    try:
        runtime = ensure_parser_runtime()
        file_data = runtime.read_source(source, source_type)
        filename = params.pop("original_filename", None) or os.path.basename(source)
        chunks = runtime.process_source(
            file_data=file_data,
            filename=filename,
            chunking_strategy=chunking_strategy,
            task_id=task_id,
            model_id=params.pop("embedding_model_id", None),
            tenant_id=params.pop("tenant_id", None),
            params=params,
        )
        if not chunks:
            raise _error_payload("Parser completed but produced 0 chunks", source, None, filename)
        redis_key = f"dp:{task_id}:chunks"
        store_chunks_atomically(redis_key, chunks)
        elapsed = time.perf_counter() - started
        text_length = sum(len(str(chunk.get("content", ""))) for chunk in chunks)
        self.update_state(
            state=states.SUCCESS,
            meta={
                "task_name": "process_sync",
                "sync_mode": True,
                "chunks_count": len(chunks),
                "text_length": text_length,
            },
        )
        return {
            "task_id": task_id,
            "source": source,
            "chunks_key": redis_key,
            "chunks_count": len(chunks),
            "image_metadata_chunk_count": _count_image_metadata_chunks(chunks),
            "processing_time": elapsed,
            "text_length": text_length,
        }
    except Exception as exc:
        logger.exception("Synchronous parser failed task_id=%s source=%s", task_id, source)
        self.update_state(
            meta={
                "source": source,
                "task_name": "process_sync",
                "custom_error": str(exc),
                "sync_mode": True,
                "stage": "sync_processing_failed",
            }
        )
        raise
