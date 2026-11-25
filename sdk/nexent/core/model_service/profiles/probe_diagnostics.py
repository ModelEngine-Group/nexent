# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Safe model connectivity diagnostics independent of deployment ownership."""

import ssl
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx
import openai
import requests
from websockets.exceptions import InvalidStatus


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


def record_connectivity_failure(error: Exception | None = None, *, status: int | None = None) -> bool:
    """Capture safe metadata when a caller asked for diagnostics."""
    diagnostics = _active_diagnostics.get()
    if diagnostics is None:
        return False

    from nexent.core.model_service.errors import model_http_error_category

    if isinstance(error, (httpx.HTTPStatusError, requests.exceptions.HTTPError, openai.APIStatusError)):
        status = getattr(error.response, "status_code", None)
    elif isinstance(error, InvalidStatus):
        status = error.response.status_code
    if status is not None:
        diagnostics.category = model_http_error_category(status)
        diagnostics.http_status = status
    elif isinstance(error, (TimeoutError, httpx.TimeoutException, requests.exceptions.Timeout, openai.APITimeoutError)):
        diagnostics.category, diagnostics.http_status = "MODEL_TIMEOUT", None
    elif isinstance(error, (ssl.SSLError, requests.exceptions.SSLError)):
        diagnostics.category, diagnostics.http_status = "MODEL_TLS_ERROR", None
    elif isinstance(error, (httpx.NetworkError, requests.exceptions.ConnectionError, openai.APIConnectionError)):
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
