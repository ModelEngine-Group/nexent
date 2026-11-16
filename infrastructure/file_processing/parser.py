# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Process-owned SDK document parsing; no business configuration or storage access."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)


def _set_native_thread_limits(thread_count: int) -> None:
    """Set native library limits before importing heavy numerical packages."""
    for name in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[name] = str(thread_count)


def _normalize_model_config_path(path_value: str | None) -> str | None:
    if not path_value:
        return None
    if os.path.isdir(path_value):
        path_value = os.path.join(path_value, "config.json")
    return path_value


def _configure_third_party_model_paths(
    model_paths: dict[str, str | None],
) -> dict[str, str | None]:
    """Normalize deployment values; model loaders validate paths when used."""
    normalized = {
        "unstructured_default": _normalize_model_config_path(
            model_paths.get("unstructured_default")
        ),
        "table_transformer": model_paths.get("table_transformer"),
    }
    unstructured_path = normalized.get("unstructured_default")
    if unstructured_path:
        # unstructured-inference 1.2.0 reads this established variable inside
        # its own loader.  The backend owns the value; the SDK never reads it.
        os.environ["UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH"] = (
            unstructured_path
        )
    return normalized


class DocumentParserRuntime:
    """One Core and model registry per OS process."""

    def __init__(
        self,
        thread_count: int,
        preload_models: Iterable[str],
        model_paths: dict[str, str | None],
    ):
        if type(thread_count) is not int or thread_count < 1:
            raise ValueError("Expected a positive native thread count")
        self.thread_count = thread_count
        self.preload_models = list(preload_models)
        self.model_paths = dict(model_paths)
        self._pid = os.getpid()
        self._core: Any = None
        self._initialized = False
        self._lock = threading.Lock()

    @property
    def core(self) -> Any:
        self.ensure_initialized()
        return self._core

    @property
    def initialized(self) -> bool:
        return self._initialized and self._pid == os.getpid()

    def file_process(self, *, file_data, filename, chunking_strategy, **params):
        core = self.core
        params.update(
            table_transformer_model_path=self.model_paths.get("table_transformer"),
            unstructured_default_model_initialize_params_json_path=self.model_paths.get(
                "unstructured_default"
            ),
        )
        return core.file_process(
            file_data=file_data,
            filename=filename,
            chunking_strategy=chunking_strategy,
            **params,
        )

    def ensure_initialized(self) -> None:
        if self._pid != os.getpid():
            raise RuntimeError("Parser runtime cannot be reused after fork")
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            started = time.perf_counter()
            try:
                _set_native_thread_limits(self.thread_count)
                normalized_paths = _configure_third_party_model_paths(self.model_paths)
                # Importing the SDK Core is intentionally inside the prefork
                # child task path, after native thread limits are applied.
                from nexent.data_process import DataProcessCore

                core = DataProcessCore(model_paths=normalized_paths)
                core.preload_models(self.preload_models)
                self.model_paths = normalized_paths
                self._core = core
                self._initialized = True
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
