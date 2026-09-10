"""Celery tasks that execute CPU-heavy parsing in prefork children.

This module intentionally has no top-level import of the SDK Core or any
parsing library. The parser runtime imports those dependencies only inside a
prefork child immediately before the task body runs.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterable
from datetime import datetime
from io import BytesIO
from typing import Any

from celery import Task, chord, group, states
from celery.exceptions import Ignore

from consts.const import (
    DP_FILE_SPLIT_SIZE_MB,
    DP_PART_PROCESSOR_COUNT,
    DP_REDIS_CHUNKS_WAIT_TIMEOUT_S,
    REDIS_BACKEND_URL,
)
from utils.knowledge_ingestion_errors import (
    ClassifiedIngestionException,
    classify_ingestion_exception,
)
from utils.knowledge_telemetry import trace_knowledge_operation

from .app import app
from .parser_runtime import ensure_parser_runtime, get_parser_runtime
from .utils import (
    DocumentDeleteRequested,
    ensure_document_not_deleted,
    is_document_delete_requested,
    update_file_lifecycle,
)


logger = logging.getLogger("data_process.parse_tasks")
CHUNKS_TTL_SECONDS = 2 * 60 * 60
BOOTSTRAP_KEY_TTL_SECONDS = max(DP_REDIS_CHUNKS_WAIT_TIMEOUT_S * 2, 60)


class ParserTask(Task):
    """Base settings for parser tasks running in prefork children."""

    abstract = True
    acks_late = True
    reject_on_worker_lost = True


def _redis_client():
    if not REDIS_BACKEND_URL:
        raise RuntimeError("REDIS_BACKEND_URL is not configured")
    import redis

    return redis.Redis.from_url(REDIS_BACKEND_URL, decode_responses=True)


def store_chunks_atomically(redis_key: str, chunks: list[dict[str, Any]]) -> None:
    """Persist chunks directly in Redis."""
    client = _redis_client()
    client.set(
        redis_key,
        json.dumps(chunks, ensure_ascii=False),
        ex=CHUNKS_TTL_SECONDS,
    )


def load_chunks_from_redis(redis_key: str) -> list[dict[str, Any]]:
    client = _redis_client()
    cached = client.get(redis_key)
    if not cached:
        return []
    return json.loads(cached)


def cleanup_parser_artifacts(
    task_id: str,
    part_refs: Iterable[dict[str, Any]] | None = None,
    *,
    include_final: bool = False,
) -> None:
    """Best-effort idempotent cleanup for parser intermediate data."""
    refs = list(part_refs or [])
    keys: list[str] = []
    if include_final:
        keys.append(f"dp:{task_id}:chunks")
    for part_ref in refs:
        part_index = part_ref.get("part_index")
        if part_index is not None:
            part_key = f"dp:{task_id}:part:{part_index}:chunks"
            keys.append(part_key)
    if keys:
        try:
            _redis_client().delete(*keys)
        except Exception:
            logger.warning(
                "Failed to clean parser Redis artifacts task_id=%s keys=%s",
                task_id,
                keys,
                exc_info=True,
            )

    try:
        from database.attachment_db import delete_file
    except Exception:
        logger.warning("Unable to import parser object cleanup helper task_id=%s", task_id, exc_info=True)
        return

    for part_ref in refs:
        uri = part_ref.get("uri")
        if uri:
            try:
                result = delete_file(uri)
                if isinstance(result, dict) and not result.get("success", False):
                    logger.warning(
                        "Parser temporary object cleanup returned failure task_id=%s uri=%s result=%s",
                        task_id,
                        uri,
                        result,
                    )
            except Exception:
                logger.warning("Failed to clean parser part object task_id=%s uri=%s", task_id, uri, exc_info=True)


@app.task(name="data_process.tasks.cleanup_failed_parser_parts", ignore_result=True)
def cleanup_failed_parser_parts(
    _request: Any,
    _exc: BaseException,
    _traceback: Any,
    *,
    task_id: str,
    part_refs: list[dict[str, Any]],
) -> None:
    """Clean all parser artifacts after a parser chord fails."""
    # The callback may fail after publishing the final Redis reference.  Use
    # the same idempotent cleanup primitive for both part and final artifacts.
    cleanup_parser_artifacts(task_id, part_refs, include_final=True)


def _upload_part(task_id: str, index: int, filename: str, data: bytes) -> dict[str, Any]:
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
    }


def _error_payload(message: str, source: str, index_name: str | None, filename: str | None) -> Exception:
    return Exception(json.dumps({
        "message": message,
        "index_name": index_name,
        "task_name": "process",
        "source": source,
        "original_filename": filename,
        "error_code": classify_ingestion_exception(message, "PROCESS").error_code,
    }, ensure_ascii=False))


def _persist_parser_failure(
    task_id: str,
    error: Any,
    *,
    source: str,
    index_name: str | None,
    tenant_id: str | None,
    file_id: str | None,
) -> ClassifiedIngestionException:
    """Persist one parser failure in Redis and the file lifecycle record."""
    classified = classify_ingestion_exception(error, "PROCESS")
    try:
        from .tasks import _redis_error_reason, save_error_to_redis

        save_error_to_redis(
            task_id,
            _redis_error_reason(classified),
        )
    except Exception:
        logger.warning("Parser error persistence failed task_id=%s", task_id, exc_info=True)
    update_file_lifecycle(
        task_id=task_id,
        status="FAILED",
        stage="PROCESS",
        source=source,
        index_name=index_name,
        tenant_id=tenant_id,
        file_id=file_id,
        process_task_id=task_id,
        error_code=classified.error_code,
        error_message=classified.error_message,
        error_stage="PROCESS",
        failed_at=datetime.utcnow(),
    )
    return classified


def _build_process_cancelled_result(
    *,
    task_id: str,
    source: str,
    index_name: str | None,
    original_filename: str | None,
    file_id: str | None,
    split_async: bool = False,
) -> dict[str, Any]:
    """Return a chain-compatible result when deletion wins a processing race."""
    return {
        "task_id": task_id,
        "source": source,
        "index_name": index_name,
        "original_filename": original_filename,
        "file_id": file_id,
        "redis_key": f"dp:{task_id}:chunks",
        "chunks": None,
        "split_async": split_async,
        "cancelled": True,
        "message": "Processing cancelled because document deletion was requested.",
    }


def _count_image_metadata_chunks(chunks: list[dict[str, Any]] | None) -> int:
    if not chunks:
        return 0
    return sum(
        1
        for chunk in chunks
        if (
            chunk.get("process_source")
            or chunk.get("metadata", {}).get("process_source")
        )
        == "UniversalImageExtractor"
    )


@app.task(bind=True, base=ParserTask, name="data_process.tasks.parser_bootstrap", queue="parse_q")
def parser_bootstrap(self, worker_generation: str, target_children: int) -> dict[str, Any]:
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
    part_ref: dict[str, Any],
    filename: str,
    chunking_strategy: str,
    part_redis_key: str,
    source: str | None = None,
    index_name: str | None = None,
    file_id: str | None = None,
    model_id: int | None = None,
    tenant_id: str | None = None,
    parser_task_id: str | None = None,
    **params: Any,
) -> dict[str, Any]:
    """Parse one object-storage part; the task payload contains only a ref."""
    parent_task_id = parser_task_id or self.request.id
    try:
        ensure_document_not_deleted(
            index_name=index_name,
            source=source,
            file_id=file_id,
            tenant_id=tenant_id,
        )
        runtime = get_parser_runtime()
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
        ensure_document_not_deleted(
            index_name=index_name,
            source=source,
            file_id=file_id,
            tenant_id=tenant_id,
        )
        store_chunks_atomically(part_redis_key, chunks)
        return {
            "part_redis_key": part_redis_key,
            "part_index": part_ref["part_index"],
            "chunks_count": len(chunks),
        }
    except DocumentDeleteRequested:
        logger.info(
            "Parser part cancelled because document deletion was requested task_id=%s part=%s",
            parent_task_id,
            part_ref.get("part_index"),
        )
        return {
            "part_redis_key": part_redis_key,
            "part_index": part_ref.get("part_index"),
            "chunks_count": 0,
            "cancelled": True,
        }
    except Exception as exc:
        logger.exception("Parser part failed task_id=%s part=%s", parent_task_id, part_ref.get("part_index"))
        # Keep sibling part objects available until the chord reaches a
        # terminal state; the chord errback performs the shared cleanup.
        _persist_parser_failure(
            parent_task_id,
            exc,
            source=source or "",
            index_name=index_name,
            tenant_id=tenant_id,
            file_id=file_id,
        )
        raise


@app.task(bind=True, base=Task, name="data_process.tasks.aggregate_store_chunks", queue="process_q")
@trace_knowledge_operation("knowledge.process.redis_aggregate", "process.redis")
def aggregate_store_chunks(
    self,
    parts_results: list[dict[str, Any]],
    redis_key: str,
    source: str | None = None,
    index_name: str | None = None,
    original_filename: str | None = None,
    task_id: str | None = None,
    part_refs: list[dict[str, Any]] | None = None,
    file_id: str | None = None,
    tenant_id: str | None = None,
    **metadata: Any,
) -> dict[str, Any]:
    """Read part keys, aggregate in order, then publish the final ref."""
    task_id = task_id or self.request.id
    try:
        ensure_document_not_deleted(
            index_name=index_name,
            source=source,
            file_id=file_id,
            tenant_id=tenant_id,
        )
        ordered = sorted(parts_results or [], key=lambda value: int(value.get("part_index", 0)))
        if any(result.get("cancelled") for result in ordered):
            raise DocumentDeleteRequested(
                f"Document deletion requested while aggregating task_id={task_id}"
            )
        merged: list[dict[str, Any]] = []
        for result in ordered:
            part_key = result.get("part_redis_key")
            if not part_key:
                raise RuntimeError("Parser part result has no Redis key")
            merged.extend(load_chunks_from_redis(part_key))
        if not merged:
            raise _error_payload("Parser completed but produced 0 chunks", source or "", index_name, original_filename)
        ensure_document_not_deleted(
            index_name=index_name,
            source=source,
            file_id=file_id,
            tenant_id=tenant_id,
        )
        store_chunks_atomically(redis_key, merged)
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
    except DocumentDeleteRequested:
        logger.info(
            "Parser aggregation cancelled because document deletion was requested task_id=%s",
            task_id,
        )
        cleanup_parser_artifacts(task_id, part_refs, include_final=True)
        return _build_process_cancelled_result(
            task_id=task_id,
            source=source or "",
            index_name=index_name,
            original_filename=original_filename,
            file_id=file_id,
            split_async=True,
        )
    except Exception as exc:
        logger.exception("Parser part aggregation failed task_id=%s source=%s", task_id, source)
        # The callback errback owns cleanup so callback failures and header
        # failures follow one idempotent path.
        _persist_parser_failure(
            task_id,
            exc,
            source=source or "",
            index_name=index_name,
            tenant_id=tenant_id,
            file_id=file_id,
        )
        raise


@app.task(bind=True, base=ParserTask, name="data_process.tasks.process", queue="parse_q")
@trace_knowledge_operation("knowledge.process", "process")
def process(
    self,
    source: str,
    source_type: str,
    chunking_strategy: str = "basic",
    index_name: str | None = None,
    original_filename: str | None = None,
    embedding_model_id: int | None = None,
    tenant_id: str | None = None,
    **params: Any,
) -> dict[str, Any]:
    """Parse a source in a prefork child and return a small chunks reference."""
    started = time.perf_counter()
    task_id = self.request.id
    file_id = params.pop("file_id", None)
    telemetry_context = params.pop("telemetry_context", None)
    part_refs: list[dict[str, Any]] = []
    if is_document_delete_requested(
        index_name=index_name,
        source=source,
        file_id=file_id,
        tenant_id=tenant_id,
    ):
        logger.info(
            "Skipping parser task because document deletion was requested task_id=%s source=%s",
            task_id,
            source,
        )
        return _build_process_cancelled_result(
            task_id=task_id,
            source=source,
            index_name=index_name,
            original_filename=original_filename,
            file_id=file_id,
        )
    self.update_state(
        state=states.STARTED,
        meta={"task_name": "process", "stage": "extracting_text", "source": source},
    )
    update_file_lifecycle(
        task_id=task_id,
        status="PROCESSING",
        stage="PROCESS",
        source=source,
        index_name=index_name,
        tenant_id=tenant_id,
        file_id=file_id,
        process_task_id=task_id,
    )
    try:
        runtime = get_parser_runtime()
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
                # Build the reference list incrementally so a failure after a
                # partial upload still leaves the successful refs available
                # to the outer cleanup path.
                for idx, part in enumerate(parts):
                    part_refs.append(_upload_part(task_id, idx, filename, part))
                # The original bytes and the split list are no longer needed
                # after all temporary objects have been uploaded.
                del parts, file_data, part
                # The upload is temporary; this guard is the split-path
                # publish boundary that prevents dispatching parser parts
                # after a deletion request wins the race.
                ensure_document_not_deleted(
                    index_name=index_name,
                    source=source,
                    file_id=file_id,
                    tenant_id=tenant_id,
                )
                part_sigs = [
                    process_part.s(
                        part_ref=part_ref,
                        filename=filename,
                        chunking_strategy=chunking_strategy,
                        part_redis_key=f"dp:{task_id}:part:{idx}:chunks",
                        source=source,
                        index_name=index_name,
                        file_id=file_id,
                        model_id=embedding_model_id,
                        tenant_id=tenant_id,
                        parser_task_id=task_id,
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
                callback.link_error(
                    cleanup_failed_parser_parts.s(
                        task_id=task_id,
                        part_refs=part_refs,
                    )
                )
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
        ensure_document_not_deleted(
            index_name=index_name,
            source=source,
            file_id=file_id,
            tenant_id=tenant_id,
        )
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
        update_file_lifecycle(
            task_id=task_id,
            status="FORWARDING",
            stage="FORWARD",
            source=source,
            index_name=index_name,
            tenant_id=tenant_id,
            file_id=file_id,
            process_task_id=task_id,
        )
        return result
    except DocumentDeleteRequested:
        logger.info(
            "Parser task cancelled because document deletion was requested task_id=%s source=%s",
            task_id,
            source,
        )
        cleanup_parser_artifacts(task_id, part_refs)
        return _build_process_cancelled_result(
            task_id=task_id,
            source=source,
            index_name=index_name,
            original_filename=original_filename,
            file_id=file_id,
            split_async=bool(part_refs),
        )
    except Ignore:
        # Celery's replace() raises Ignore after handing execution to the chord.
        raise
    except Exception as exc:
        logger.exception("Parser failed task_id=%s source=%s", task_id, source)
        cleanup_parser_artifacts(task_id, part_refs)
        parsed_error: Any = exc
        try:
            parsed_candidate = json.loads(str(exc))
            if isinstance(parsed_candidate, dict):
                parsed_error = parsed_candidate
        except (TypeError, ValueError):
            pass
        classified = _persist_parser_failure(
            task_id,
            parsed_error,
            source=source,
            index_name=index_name,
            tenant_id=tenant_id,
            file_id=file_id,
        )
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
    **params: Any,
) -> dict[str, Any]:
    """Synchronous parser task; return a Redis reference, never chunks payload."""
    started = time.perf_counter()
    task_id = self.request.id
    self.update_state(
        state=states.STARTED,
        meta={"task_name": "process_sync", "sync_mode": True, "source": source},
    )
    try:
        runtime = get_parser_runtime()
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
                "chunks_key": redis_key,
                "chunks_count": len(chunks),
                "text_length": text_length,
                "processing_time": elapsed,
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
