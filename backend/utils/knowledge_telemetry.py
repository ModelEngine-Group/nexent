"""Best-effort telemetry helpers for the knowledge-base ingestion pipeline."""

from __future__ import annotations

import functools
import hashlib
import inspect
import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Mapping, Optional

logger = logging.getLogger(__name__)
BYTES_PER_MB = 1024 * 1024
KNOWLEDGE_SPAN_DESCRIPTIONS = {
    "knowledge.upload.batch": "`读取一批上传文件并组织 MinIO 上传。",
    "knowledge.minio.upload": "`执行实际的 MinIO 对象写入。",
    "knowledge.process.submit": "`从 backend 调用 data-process HTTP 接口，提交单文件或批量处理请求。",
    "knowledge.chain.submit": "`创建并投递 Celery process → forward → cleanup 任务链。它只表示任务成功进入队列，不代表文件已经处理完成。",
    "knowledge.process": "单个文件的顶层解析任务，负责获取文件、拆分、调度处理并统计 chunk。",
    "knowledge.minio.fetch": "从 MinIO 下载待处理文件字节。",
    "knowledge.process.split_and_ray": "判断是否拆分文件，并向 Ray 或 Celery 子任务分发解析工作。",
    "knowledge.process.split_actor_acquire": "请求已预热的 Ray actor 执行文件拆分任务。",
    "knowledge.process.file_split_rpc": "在选定的 Ray actor 中执行文件拆分任务。",
    "knowledge.process.part_dispatch": "分发给 Celery 到并等待聚合。",
    "knowledge.process.part_wait": "等待 Celery part tasks 和 Redis 聚合完成。",
    "knowledge.process.part": "处理一个拆分后的文档分片。",
    "knowledge.process.ray_actor": "在独立 Ray actor 进程内执行文档预处理。",
    "knowledge.preprocess.split": "使用 FileSplitter 拆分大文件。",
    "knowledge.preprocess.image_extract": "为多模态知识库提取图片及图片元数据。",
    "knowledge.preprocess.typed": "根据文件类型调用不同解析器。",
    "knowledge.process.redis_aggregate": "合并各分片的 chunk，并将结果写入 Redis，供 forward 阶段读取。",
    "knowledge.forward": "顶层索引任务，读取、过滤、格式化 chunk，并决定同步或分批提交。",
    "knowledge.forward.redis_read": "`从 Redis 读取 process 阶段生成的 chunk。",
    "knowledge.forward.batch": "`处理并提交一个 chunk batch。",
    "knowledge.forward.elasticsearch": "调用 Elasticsearch 接口写入向量。",
    "knowledge.forward.aggregate": "`汇总多个 batch 的结果，验证提交数和索引数。",
    "knowledge.cleanup": "索引成功后按清理策略删除上传源文件；取消、失败或策略不允许时会跳过删除。",
}


def _span_kind(name: str) -> str:
    """Return the Phoenix/OpenInference kind appropriate for the operation."""
    tool_markers = (".minio.", ".redis_", ".redis_aggregate", ".elasticsearch")
    return "TOOL" if any(marker in name for marker in tool_markers) else "CHAIN"


def _is_celery_retry(error: BaseException) -> bool:
    """Recognize Celery's control-flow retry without requiring Celery in backend."""
    error_type = type(error)
    return error_type.__name__ == "Retry" and error_type.__module__.startswith("celery")

try:
    from opentelemetry import context as otel_context
    from opentelemetry import metrics, propagate, trace
    from opentelemetry.trace import Status, StatusCode

    OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    OTEL_AVAILABLE = False


def _safe_hash(value: Any) -> str:
    if not value:
        return ""
    return hashlib.sha256(str(value).encode("utf-8", errors="ignore")).hexdigest()[:16]


def _extension(filename: Any) -> str:
    return os.path.splitext(str(filename or ""))[1].lower()[:16]


def _safe_attributes(values: Mapping[str, Any]) -> Dict[str, Any]:
    """Return low-cardinality, non-content attributes accepted by OTel."""
    attrs: Dict[str, Any] = {}
    aliases = {
        "task_id": "task.id",
        "chain_id": "chain.id",
        "index_name": "knowledge_base.id",
        "tenant_id": "tenant.id_hash",
        "source_type": "source.type",
        "stage": "ingestion.stage",
        "file_size": "file.size_mb",
        "file_size_bytes": "file.size_mb",
        "chunk_count": "chunk.count",
        "chunks_count": "chunk.count",
        "batch_index": "batch.index",
        "total_batches": "batch.total",
        "processor": "processor.name",
        "part_count": "file.parts_count",
        "processor_count": "processor.count",
        "parallel_parts": "processor.parallel_count",
        "timeout_seconds": "timeout.seconds",
        "poll_interval_ms": "poll.interval_ms",
        "queue_name": "messaging.destination.name",
    }
    for key, target in aliases.items():
        value = values.get(key)
        if value is None:
            continue
        if key in {"tenant_id", "index_name"}:
            value = _safe_hash(value)
        if key in {"file_size", "file_size_bytes"}:
            try:
                value = round(float(value) / BYTES_PER_MB, 3)
            except (TypeError, ValueError):
                continue
        if isinstance(value, (str, bool, int, float)):
            attrs[target] = value
    filename = values.get("original_filename") or values.get("filename") or values.get("file_name")
    if filename:
        attrs["file.extension"] = _extension(filename)
    return attrs


def inject_trace_context() -> Dict[str, str]:
    """Create a safe W3C propagation carrier for HTTP/Celery boundaries."""
    carrier: Dict[str, str] = {}
    if OTEL_AVAILABLE:
        try:
            propagate.inject(carrier)
        except Exception:
            logger.debug("Unable to inject telemetry context", exc_info=True)
    return carrier


def _resource_snapshot() -> Dict[str, Any]:
    """Collect process and host resources without making psutil mandatory."""
    try:
        import psutil

        process = psutil.Process()
        memory = psutil.virtual_memory()
        children = process.children(recursive=True)
        process_rss = process.memory_info().rss
        process_tree_rss = process_rss + sum(
            child.memory_info().rss for child in children if child.is_running()
        )
        snapshot = {
            "process.rss_memory_mb": round(process_rss / BYTES_PER_MB, 3),
            "process.cpu_percent": round(process.cpu_percent(interval=None), 3),
            "process.thread_count": process.num_threads(),
            "process_tree.rss_memory_mb": round(process_tree_rss / BYTES_PER_MB, 3),
            "process_tree.child_count": len(children),
            "host.used_memory_percent": round(memory.percent, 3),
            "host.available_memory_mb": round(memory.available / BYTES_PER_MB, 3),
            "host.cpu_percent": round(psutil.cpu_percent(interval=None), 3),
        }
        for path, key in (
            ("/sys/fs/cgroup/memory.current", "container.used_memory_mb"),
            ("/sys/fs/cgroup/memory.max", "container.memory_limit_mb"),
        ):
            try:
                with open(path, encoding="ascii") as cgroup_file:
                    value = cgroup_file.read().strip()
                if value != "max":
                    snapshot[key] = round(int(value) / BYTES_PER_MB, 3)
            except (OSError, ValueError):
                pass
        return snapshot
    except Exception:
        return {}


def _record_metrics(stage: str, duration_ms: float, snapshot: Mapping[str, Any]) -> None:
    if not OTEL_AVAILABLE:
        return
    try:
        meter = metrics.get_meter("nexent.knowledge_ingestion")
        labels = {"ingestion.stage": stage}
        meter.create_histogram("nexent.ingestion.stage.duration", unit="ms").record(duration_ms, labels)
        if "process.rss_memory_mb" in snapshot:
            meter.create_histogram("nexent.ingestion.process.rss", unit="By").record(
                snapshot["process.rss_memory_mb"] * BYTES_PER_MB, labels
            )
        if "process.cpu_percent" in snapshot:
            meter.create_histogram("nexent.ingestion.process.cpu", unit="%").record(
                snapshot["process.cpu_percent"], labels
            )
    except Exception:
        logger.debug("Unable to record ingestion resource metrics", exc_info=True)


@contextmanager
def knowledge_span(name: str, stage: str, **attributes: Any) -> Iterator[Any]:
    """Create a non-blocking ingestion span, optionally continuing a remote trace."""
    if not OTEL_AVAILABLE:
        yield None
        return

    token = None
    span_cm = None
    span = None
    started = time.perf_counter()
    start_resources = _resource_snapshot()
    try:
        carrier = attributes.pop("telemetry_context", None)
        if isinstance(carrier, Mapping):
            remote_context = propagate.extract(dict(carrier))
            token = otel_context.attach(remote_context)
        tracer = trace.get_tracer("nexent.knowledge_ingestion")
        span_cm = tracer.start_as_current_span(name)
        span = span_cm.__enter__()
        span.set_attributes({
            "ingestion.stage": stage,
            "ingestion.operation.description": KNOWLEDGE_SPAN_DESCRIPTIONS.get(name, stage),
            "openinference.span.kind": _span_kind(name),
            **_safe_attributes(attributes),
            **{f"resource.start.{key}": value for key, value in start_resources.items()},
        })
    except Exception:
        logger.debug("Telemetry span setup failed for %s", name, exc_info=True)
        if span_cm is not None:
            try:
                span_cm.__exit__(None, None, None)
            except Exception:
                pass
        if token is not None:
            try:
                otel_context.detach(token)
            except Exception:
                pass
        yield None
        return

    try:
        yield span
    except Exception as exc:
        try:
            if _is_celery_retry(exc):
                span.set_attribute("ingestion.status", "retry")
                span.set_attribute("retry.attempt", int(attributes.get("retry_attempt", 0)))
                retry_delay = attributes.get("retry_delay_seconds", getattr(exc, "when", 0))
                if isinstance(retry_delay, (int, float)):
                    span.set_attribute("retry.delay_seconds", float(retry_delay))
                # Retry is expected control flow, not a failed ingestion operation.
                span.set_status(Status(StatusCode.OK))
            else:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
                span.set_attribute("error.type", type(exc).__name__)
        except Exception:
            logger.debug("Unable to record ingestion failure", exc_info=True)
        raise
    else:
        try:
            span.set_status(Status(StatusCode.OK))
            span.set_attribute("ingestion.status", "success")
        except Exception:
            logger.debug("Unable to record ingestion success", exc_info=True)
    finally:
        end_resources = _resource_snapshot()
        duration_ms = (time.perf_counter() - started) * 1000.0
        if span is not None:
            try:
                span.set_attribute("ingestion.duration_ms", duration_ms)
                span.set_attributes({f"resource.end.{key}": value for key, value in end_resources.items()})
            except Exception:
                logger.debug("Unable to attach ingestion resource snapshot", exc_info=True)
        _record_metrics(stage, duration_ms, end_resources)
        if span_cm is not None:
            try:
                span_cm.__exit__(None, None, None)
            except Exception:
                logger.debug("Telemetry span close failed", exc_info=True)
        if token is not None:
            try:
                otel_context.detach(token)
            except Exception:
                logger.debug("Telemetry context detach failed", exc_info=True)


def trace_knowledge_operation(name: str, stage: str):
    """Decorate sync or async ingestion operations without changing behavior."""
    def decorator(func):
        signature = inspect.signature(func)

        def span_args(args, kwargs):
            try:
                bound = signature.bind_partial(*args, **kwargs)
                values = dict(bound.arguments)
            except Exception:
                values = dict(kwargs)
            request = values.get("self")
            if request is not None and hasattr(request, "request"):
                values.setdefault("task_id", getattr(request.request, "id", None))
                values.setdefault("retry_attempt", getattr(request.request, "retries", 0) + 1)
            values["telemetry_context"] = values.get("telemetry_context") or values.get("params", {}).get(
                "telemetry_context"
            )
            return values

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                with knowledge_span(name, stage, **span_args(args, kwargs)):
                    return await func(*args, **kwargs)
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with knowledge_span(name, stage, **span_args(args, kwargs)):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def set_span_attributes(**attributes: Any) -> None:
    """Attach safe attributes to the active span, if any."""
    if not OTEL_AVAILABLE:
        return
    try:
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attributes(_safe_attributes(attributes))
    except Exception:
        logger.debug("Unable to set ingestion span attributes", exc_info=True)
