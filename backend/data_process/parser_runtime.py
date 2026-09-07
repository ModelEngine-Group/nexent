"""Process-local parser runtime used by the Celery prefork children."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional

from consts.const import (
    DEFAULT_EXPECTED_CHUNK_SIZE,
    DEFAULT_MAXIMUM_CHUNK_SIZE,
    DP_PARSE_THREADS_PER_PROCESS,
    DP_PRELOAD_MODELS,
    TABLE_TRANSFORMER_MODEL_PATH,
    UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH,
)

logger = logging.getLogger("data_process.parser_runtime")

_runtime: Optional["ParserRuntime"] = None
_runtime_pid: Optional[int] = None
_runtime_lock = threading.Lock()


def _aliases_from_config(value: str) -> List[str]:
    return [alias.strip() for alias in (value or "").split(",") if alias.strip()]


def _set_native_thread_limits(thread_count: int) -> None:
    """Set native library limits before importing heavy numerical packages."""
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = str(thread_count)


def _normalize_model_config_path(path_value: Optional[str]) -> Optional[str]:
    if not path_value:
        return None
    if os.path.isdir(path_value):
        path_value = os.path.join(path_value, "config.json")
    if not os.path.isfile(path_value):
        raise FileNotFoundError(f"Model configuration does not exist: {path_value}")
    return path_value


def _configure_third_party_model_paths(model_paths: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
    """Normalize the existing deployment values in the parser child only."""
    normalized = {
        "unstructured_default": _normalize_model_config_path(
            model_paths.get("unstructured_default")
        ),
        "table_transformer": model_paths.get("table_transformer"),
    }
    table_path = normalized["table_transformer"]
    if table_path and not os.path.exists(table_path):
        raise FileNotFoundError(f"Model path does not exist: {table_path}")
    unstructured_path = normalized.get("unstructured_default")
    if unstructured_path:
        # unstructured-inference 1.2.0 reads this established variable inside
        # its own loader.  The backend owns the value; the SDK never reads it.
        os.environ["UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH"] = unstructured_path
    return normalized


class ParserRuntime:
    """One Core and model registry per OS process."""

    def __init__(self, thread_count: int, preload_models: Iterable[str]):
        self.thread_count = thread_count
        self.preload_models = list(preload_models)
        self.model_paths = {
            "unstructured_default": UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH,
            "table_transformer": TABLE_TRANSFORMER_MODEL_PATH,
        }
        self._core: Any = None
        self._initialized = False
        self._initializing = False
        self._lock = threading.Lock()
        self.initialized_at: Optional[float] = None

    @property
    def core(self) -> Any:
        self.ensure_initialized()
        return self._core

    @property
    def initialized(self) -> bool:
        return self._initialized

    def ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            if self._initializing:
                raise RuntimeError("Parser runtime initialization is already in progress")
            self._initializing = True
            started = time.perf_counter()
            try:
                _set_native_thread_limits(self.thread_count)
                normalized_paths = _configure_third_party_model_paths(self.model_paths)
                # Importing the SDK Core is intentionally inside the prefork
                # child task path, after native thread limits are applied.
                from nexent.data_process import DataProcessCore

                self._core = DataProcessCore(model_paths=normalized_paths)
                self._core.preload_models(self.preload_models)
                self._initialized = True
                self.initialized_at = time.time()
                logger.info(
                    "Parser runtime ready pid=%s preload_models=%s elapsed=%.3fs",
                    os.getpid(),
                    self.preload_models,
                    time.perf_counter() - started,
                )
            except Exception:
                self._core = None
                logger.exception(
                    "Parser runtime initialization failed pid=%s preload_models=%s elapsed=%.3fs",
                    os.getpid(),
                    self.preload_models,
                    time.perf_counter() - started,
                )
                raise
            finally:
                self._initializing = False

    def _prepare_params(
        self,
        *,
        task_id: Optional[str],
        model_id: Optional[int],
        tenant_id: Optional[str],
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        process_params = dict(params)
        process_params["table_transformer_model_path"] = self.model_paths.get("table_transformer")
        process_params[
            "unstructured_default_model_initialize_params_json_path"
        ] = self.model_paths.get("unstructured_default")
        if task_id:
            process_params["task_id"] = task_id
        if model_id and tenant_id:
            try:
                from database.model_management_db import get_model_by_model_id

                record = get_model_by_model_id(model_id=model_id, tenant_id=tenant_id)
                if record:
                    process_params["max_characters"] = record.get(
                        "maximum_chunk_size", DEFAULT_MAXIMUM_CHUNK_SIZE
                    )
                    process_params["new_after_n_chars"] = record.get(
                        "expected_chunk_size", DEFAULT_EXPECTED_CHUNK_SIZE
                    )
                    if record.get("model_type"):
                        process_params["model_type"] = record["model_type"]
            except Exception:
                logger.warning("Unable to load chunk-size configuration for model_id=%s", model_id, exc_info=True)
        return process_params

    @staticmethod
    def read_source(source: str, source_type: str) -> bytes:
        if source_type == "local":
            with open(source, "rb") as source_file:
                return source_file.read()
        if source_type == "minio":
            from database.attachment_db import get_file_stream

            stream = get_file_stream(source)
            if stream is None:
                raise FileNotFoundError(f"Unable to fetch file from URL: {source}")
            try:
                return stream.read()
            finally:
                stream.close()
        raise NotImplementedError(f"Source type '{source_type}' not yet supported")

    def process_source(
        self,
        *,
        file_data: bytes,
        filename: str,
        chunking_strategy: str,
        task_id: Optional[str] = None,
        model_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        self.ensure_initialized()
        result = self._core.file_process(
            file_data=file_data,
            filename=filename,
            chunking_strategy=chunking_strategy,
            **self._prepare_params(
                task_id=task_id,
                model_id=model_id,
                tenant_id=tenant_id,
                params=params or {},
            ),
        )
        chunks, images_info = self._normalize_result(result)
        if images_info:
            self._append_image_chunks(filename, chunks, images_info)
        return self._validate_chunks(chunks, filename)

    def split_source(
        self,
        *,
        file_data: bytes,
        filename: str,
        target_parts: int,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[bytes]:
        self.ensure_initialized()
        split_params = dict(params or {})
        split_params.pop("max_size", None)
        split_params.pop("target_parts", None)
        parts = self._core.file_split(
            file_data=file_data,
            filename=filename,
            target_parts=target_parts,
            **split_params,
        )
        return [part.getvalue() for part in parts or [] if hasattr(part, "getvalue")]

    @staticmethod
    def _normalize_result(result: Any) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        if isinstance(result, tuple) and len(result) == 2:
            return result[0] or [], result[1] or []
        return result or [], []

    @staticmethod
    def _validate_chunks(chunks: Any, source: str) -> List[Dict[str, Any]]:
        if not isinstance(chunks, list):
            logger.warning("Parser returned non-list chunks for source=%s", source)
            return []
        return chunks

    @staticmethod
    def _append_image_chunks(source: str, chunks: List[Dict[str, Any]], images_info: List[Dict[str, Any]]) -> None:
        from database.attachment_db import build_s3_url, upload_fileobj

        for index, image_data in enumerate(images_info):
            if not isinstance(image_data, dict) or "image_bytes" not in image_data:
                continue
            result = upload_fileobj(
                file_obj=BytesIO(image_data["image_bytes"]),
                file_name=f"{index}.{image_data.get('image_format', 'png')}",
                prefix="images_in_attachments",
            )
            image_url = build_s3_url(result.get("object_name", ""))
            chunks.append(
                {
                    "content": json.dumps(
                        {
                            "source_file": source,
                            "position": image_data.get("position"),
                            "image_url": image_url,
                        }
                    ),
                    "filename": source,
                    "metadata": {
                        "chunk_index": len(chunks) + index,
                        "process_source": "UniversalImageExtractor",
                        "image_url": image_url,
                    },
                }
            )


def get_parser_runtime() -> ParserRuntime:
    """Return a PID-safe singleton; a forked child always receives a new one."""
    global _runtime, _runtime_pid
    pid = os.getpid()
    if _runtime is None or _runtime_pid != pid:
        with _runtime_lock:
            if _runtime is None or _runtime_pid != pid:
                _runtime = ParserRuntime(
                    thread_count=DP_PARSE_THREADS_PER_PROCESS,
                    preload_models=_aliases_from_config(DP_PRELOAD_MODELS),
                )
                _runtime_pid = pid
    return _runtime


def ensure_parser_runtime() -> ParserRuntime:
    runtime = get_parser_runtime()
    runtime.ensure_initialized()
    return runtime
