# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Process-local parser runtime used by the Celery prefork children."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterable
from io import BytesIO
from typing import Any

from contracts.constants.constants import (
    DEFAULT_EXPECTED_CHUNK_SIZE,
    DEFAULT_MAXIMUM_CHUNK_SIZE,
)
from contracts.constants.environment import (
    DP_PARSE_THREADS_PER_PROCESS,
    DP_PRELOAD_MODELS,
    TABLE_TRANSFORMER_MODEL_PATH,
    UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH,
)

from infrastructure.file_processing.parser import DocumentParserRuntime

logger = logging.getLogger("data_process.parser_runtime")

_runtime: ParserRuntime | None = None
_runtime_pid: int | None = None
_runtime_lock = threading.Lock()


def _aliases_from_config(value: str) -> list[str]:
    return [alias.strip() for alias in (value or "").split(",") if alias.strip()]


class ParserRuntime(DocumentParserRuntime):
    """Existing task orchestration; SDK initialization is infrastructure-owned."""

    def __init__(self, thread_count: int, preload_models: Iterable[str]):
        super().__init__(
            thread_count,
            preload_models,
            {
                "unstructured_default": UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH,
                "table_transformer": TABLE_TRANSFORMER_MODEL_PATH,
            },
        )

    def _prepare_params(
        self,
        *,
        task_id: str | None,
        model_id: int | None,
        tenant_id: str | None,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        process_params = dict(params)
        process_params["table_transformer_model_path"] = self.model_paths.get(
            "table_transformer"
        )
        process_params["unstructured_default_model_initialize_params_json_path"] = (
            self.model_paths.get("unstructured_default")
        )
        if task_id:
            process_params["task_id"] = task_id
        if model_id and tenant_id:
            try:
                from management.db.model.repository import get_model_by_model_id

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
                logger.warning(
                    "Unable to load chunk-size configuration for model_id=%s",
                    model_id,
                    exc_info=True,
                )
        return process_params

    @staticmethod
    def read_source(source: str, source_type: str) -> bytes:
        if source_type == "local":
            with open(source, "rb") as source_file:
                return source_file.read()
        if source_type == "minio":
            from management.db.file.attachment import get_file_stream

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
        task_id: str | None = None,
        model_id: int | None = None,
        tenant_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
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
        params: dict[str, Any] | None = None,
    ) -> list[bytes]:
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
        return [part.getvalue() for part in parts]

    @staticmethod
    def _normalize_result(
        result: Any,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        chunks, images_info = result
        return chunks or [], images_info or []

    @staticmethod
    def _validate_chunks(chunks: Any, source: str) -> list[dict[str, Any]]:
        if not isinstance(chunks, list):
            logger.warning("Parser returned non-list chunks for source=%s", source)
            return []
        return chunks

    @staticmethod
    def _append_image_chunks(
        source: str, chunks: list[dict[str, Any]], images_info: list[dict[str, Any]]
    ) -> None:
        from management.db.file.attachment import build_s3_url, upload_fileobj

        for index, image_data in enumerate(images_info):
            if not isinstance(image_data, dict) or "image_bytes" not in image_data:
                continue
            result = upload_fileobj(
                file_obj=BytesIO(image_data["image_bytes"]),
                file_name=f"{index}.{image_data.get('image_format', 'png')}",
                prefix="images_in_attachments",
            )
            if not result.get("success", False):
                raise RuntimeError(
                    f"Failed to upload extracted image {index}: "
                    f"{result.get('error', 'unknown error')}"
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
                        "chunk_index": len(chunks),
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
