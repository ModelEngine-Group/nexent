# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Safe HTTP error mapping shared by the two directions of AgentOS KB calls."""

import logging

from contracts.errors.exceptions import (
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
    RuntimeUpstreamError,
)
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
    StorageError,
    Unavailable,
)
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def knowledge_error(error, *, prefix="KNOWLEDGE"):
    for kind, status, code in (
        (ScopeDenied, 403, "KNOWLEDGE_FORBIDDEN"),
        (NotFound, 404, "KNOWLEDGE_NOT_FOUND"),
        (Conflict, 409, "KNOWLEDGE_CONFLICT"),
        (InvalidInput, 422, "KNOWLEDGE_INVALID_REQUEST"),
        (DeadlineExceeded, 504, "KNOWLEDGE_TIMEOUT"),
        (OutcomeUnknown, 503, "KNOWLEDGE_OUTCOME_UNKNOWN"),
        (CapabilityUnsupported, 422, "KNOWLEDGE_UNSUPPORTED"),
        (Unavailable, 503, "KNOWLEDGE_STORAGE_UNAVAILABLE"),
        (StorageError, 503, "KNOWLEDGE_STORAGE_FAILED"),
        (RuntimeServiceTimeoutError, 504, "KNOWLEDGE_TIMEOUT"),
        (RuntimeServiceUnavailableError, 503, "KNOWLEDGE_AUTHORIZATION_UNAVAILABLE"),
    ):
        if isinstance(error, kind):
            return JSONResponse({"code": code.replace("KNOWLEDGE_", prefix + "_", 1)}, status_code=status)
    if isinstance(error, RuntimeUpstreamError):
        status = error.status_code if error.status_code in {403, 404, 504} else 503
        code = {
            403: "KNOWLEDGE_FORBIDDEN",
            404: "KNOWLEDGE_NOT_FOUND",
            504: "KNOWLEDGE_TIMEOUT",
        }.get(status, "KNOWLEDGE_AUTHORIZATION_UNAVAILABLE")
        return JSONResponse({"code": code.replace("KNOWLEDGE_", prefix + "_", 1)}, status_code=status)
    logger.warning("%s_request_failed exception_type=%s", prefix.lower(), type(error).__name__)
    return JSONResponse({"code": prefix + "_REQUEST_FAILED"}, status_code=500)
