# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Safe model connectivity diagnostics independent of deployment ownership."""

import ssl
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx
import requests


@dataclass
class ConnectivityDiagnostics:
    """Hold the last classified provider failure from one legacy probe."""

    category: str = "MODEL_PROBE_FAILED"
    http_status: int | None = None


_active_diagnostics: ContextVar[ConnectivityDiagnostics | None] = ContextVar(
    "connectivity_diagnostics", default=None
)


@contextmanager
def capture_connectivity_diagnostics():
    diagnostics = ConnectivityDiagnostics()
    token = _active_diagnostics.set(diagnostics)
    try:
        yield diagnostics
    finally:
        _active_diagnostics.reset(token)


def _is_adapter_error(error: Exception | None, module: str, name: str) -> bool:
    # These exception types are available when their adapter uses the protocol.
    error_type = getattr(sys.modules.get(module), name, None)
    return isinstance(error_type, type) and isinstance(error, error_type)


def record_connectivity_failure(error: Exception | None = None, *, status: int | None = None) -> bool:
    """Capture safe metadata when a caller asked for diagnostics."""
    diagnostics = _active_diagnostics.get()
    if diagnostics is None:
        return False

    if isinstance(error, (httpx.HTTPStatusError, requests.exceptions.HTTPError)) or _is_adapter_error(
        error, "openai", "APIStatusError"
    ):
        status = getattr(error.response, "status_code", None)
    elif _is_adapter_error(error, "websockets.exceptions", "InvalidStatus"):
        status = error.response.status_code
    if status is not None:
        from nexent.core.model_service.errors import model_http_error_category

        diagnostics.category = model_http_error_category(status)
        diagnostics.http_status = status
    elif isinstance(error, (TimeoutError, httpx.TimeoutException, requests.exceptions.Timeout)) or _is_adapter_error(
        error, "openai", "APITimeoutError"
    ):
        diagnostics.category, diagnostics.http_status = "MODEL_TIMEOUT", None
    elif isinstance(error, (ssl.SSLError, requests.exceptions.SSLError)):
        diagnostics.category, diagnostics.http_status = "MODEL_TLS_ERROR", None
    elif isinstance(error, (httpx.NetworkError, requests.exceptions.ConnectionError)) or _is_adapter_error(
        error, "openai", "APIConnectionError"
    ):
        diagnostics.category, diagnostics.http_status = "MODEL_NETWORK_ERROR", None
    elif isinstance(error, ValueError):
        diagnostics.category, diagnostics.http_status = "MODEL_REQUEST_INVALID", None
    return True


def _probe_diagnostic(error):
    """Classify by known provider semantics, not arbitrary upstream error text."""
    per_model = error.category in {"MODEL_REQUEST_INVALID", "MODEL_CONTEXT_EXCEEDED", "MODEL_PROTOCOL_ERROR"}
    per_model = per_model or error.provider_code == "model_not_found"
    from nexent.core.model_service.errors import model_error_message

    return {"category": error.category, "message": model_error_message(error),
            "diagnostic_code": error.diagnostic_code, "message_source": error.message_source,
            "messages": {lang: model_error_message(error, lang) for lang in ("en", "zh")},
            "scope": "model" if per_model else "connection", "request_id": error.request_id,
            **({"http_status": error.http_status} if getattr(error, "http_status", None) is not None else {}),
            **({"parameter": error.parameter_name} if getattr(error, "parameter_name", None) else {})}
