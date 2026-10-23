"""Classification helpers for knowledge-base ingestion failures."""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from consts.error_code import ErrorCode
from consts.exceptions import (
    AppException,
    FileTooLargeException,
    OfficeConversionException,
    QuotaExceededError,
    UnsupportedFileTypeException,
)


_MAX_ERROR_MESSAGE_LENGTH = 500
_CODE_ALIASES = {
    "UPLOAD_FAILED": ErrorCode.FILE_UPLOAD_FAILED.value,
    "QUOTA_CHECK_FAILED": ErrorCode.TENANT_RESOURCE_EXCEEDED.value,
    "STORAGE_COMMIT_FAILED": ErrorCode.KNOWLEDGE_STORAGE_COMMIT_FAILED.value,
    "TASK_SUBMIT_FAILED": ErrorCode.KNOWLEDGE_TASK_SUBMIT_FAILED.value,
    "CONNECTION_ERROR": ErrorCode.SYSTEM_SERVICE_UNAVAILABLE.value,
    "INTERNAL_ERROR": ErrorCode.SYSTEM_INTERNAL_ERROR.value,
    "es_disk_watermark": ErrorCode.KNOWLEDGE_INDEX_WRITE_BLOCKED.value,
    "cluster_block_exception": ErrorCode.KNOWLEDGE_INDEX_WRITE_BLOCKED.value,
}
_DISK_WRITE_BLOCK_MARKERS = (
    "cluster_block_exception",
    "disk watermark",
    "flood-stage watermark",
    "flood stage watermark",
    "read-only-allow-delete",
    "read_only_allow_delete",
    "index read-only",
    "index read only",
)


@dataclass(frozen=True)
class ClassifiedIngestionException:
    """A durable error representation plus retry guidance for the active task."""

    error_code: Optional[str]
    error_message: Optional[str]
    retryable: bool


def _normalize_code(value: Any) -> Optional[str]:
    if isinstance(value, ErrorCode):
        value = value.value
    if value in (None, "", 0, "0", "unknown_error"):
        return None

    code = str(value)
    code = _CODE_ALIASES.get(code, code)
    # Upstream services may own additional codes. Preserve any explicit
    # code field; the frontend safely falls back to a generic localized message
    # when that code has no local translation.
    return code


def _parse_mapping(value: Any) -> Optional[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, Mapping) else None
    return None


def _extract_error_code(value: Any) -> Optional[str]:
    # Celery and async adapters frequently wrap structured JSON in an
    # Exception object. Inspect the complete exception text before the raw
    # message is truncated for safe persistence; otherwise a code at the end
    # of a long nested message is lost and non-retryable errors are retried.
    if isinstance(value, BaseException):
        return _extract_error_code(str(value))

    mapping = _parse_mapping(value)
    if not mapping:
        if isinstance(value, str):
            try:
                match = re.search(
                    r'["\'](?:error_code|code)["\']\s*:\s*["\']([^"\']+)["\']',
                    value,
                )
            except Exception:
                return None
            return _normalize_code(match.group(1)) if match else None
        return None

    for key in ("error_code", "code"):
        code = _normalize_code(mapping.get(key))
        if code:
            return code

    for key in ("detail", "details", "error"):
        nested = mapping.get(key)
        code = _extract_error_code(nested)
        if code:
            return code
    return None


def _raw_message(exception: BaseException | Mapping[str, Any] | str) -> str:
    if isinstance(exception, Mapping):
        message = exception.get("message") or exception.get("detail") or exception.get("error")
        if isinstance(message, Mapping):
            message = message.get("message") or json.dumps(message, ensure_ascii=False)
        if message is not None:
            return str(message).strip()[:_MAX_ERROR_MESSAGE_LENGTH]
        return json.dumps(exception, ensure_ascii=False)[:_MAX_ERROR_MESSAGE_LENGTH]
    return str(exception).strip()[:_MAX_ERROR_MESSAGE_LENGTH]


def _is_disk_write_block(message: str) -> bool:
    normalized = message.lower()
    return any(marker in normalized for marker in _DISK_WRITE_BLOCK_MARKERS)


def _is_timeout(exception: Any, message: str) -> bool:
    return isinstance(exception, (TimeoutError, asyncio.TimeoutError)) or "timed out" in message.lower()


def _is_connection_error(exception: Any, message: str) -> bool:
    exception_name = type(exception).__name__
    if isinstance(exception, ConnectionError) or exception_name in {
        "ClientConnectionError",
        "ClientConnectorError",
        "ConnectError",
        "RequestError",
        "ConnectionError",
    }:
        return True
    normalized = message.lower()
    return "failed to connect" in normalized or "connection refused" in normalized


def classify_ingestion_exception(
    exception: BaseException | Mapping[str, Any] | str,
    stage: str,
) -> ClassifiedIngestionException:
    """Classify a failure before it is persisted to a file lifecycle record.

    An explicit code and a raw message are deliberately mutually exclusive. Retryability
    is runtime-only guidance; it is not stored in the lifecycle schema.
    """
    raw_message = _raw_message(exception)
    code = _extract_error_code(exception) or _extract_error_code(raw_message)
    if isinstance(exception, BaseException):
        # Prefer an explicit error_code attribute even when an upstream or test
        # adapter provides an AppException-compatible proxy class.
        explicit_code = _normalize_code(getattr(exception, "error_code", None))
        if explicit_code:
            code = explicit_code
        elif isinstance(exception, AppException):
            code = _normalize_code(exception.error_code)
        elif isinstance(exception, FileTooLargeException):
            code = ErrorCode.FILE_TOO_LARGE.value
        elif isinstance(exception, UnsupportedFileTypeException):
            code = ErrorCode.FILE_TYPE_NOT_ALLOWED.value
        elif isinstance(exception, OfficeConversionException):
            code = ErrorCode.FILE_PREPROCESS_FAILED.value
        elif isinstance(exception, QuotaExceededError):
            code = ErrorCode.TENANT_RESOURCE_EXCEEDED.value
        elif isinstance(exception, FileNotFoundError):
            code = ErrorCode.FILE_NOT_FOUND.value

    if _is_disk_write_block(raw_message):
        code = ErrorCode.KNOWLEDGE_INDEX_WRITE_BLOCKED.value

    if not code:
        if _is_timeout(exception, raw_message):
            code = ErrorCode.SYSTEM_TIMEOUT.value
        elif _is_connection_error(exception, raw_message):
            code = ErrorCode.SYSTEM_SERVICE_UNAVAILABLE.value
        elif stage == "UPLOAD":
            code = ErrorCode.FILE_UPLOAD_FAILED.value
        elif stage == "STORAGE_COMMIT":
            code = ErrorCode.KNOWLEDGE_STORAGE_COMMIT_FAILED.value
        elif stage == "TASK_SUBMIT":
            code = ErrorCode.KNOWLEDGE_TASK_SUBMIT_FAILED.value

    retryable = code in {
        ErrorCode.SYSTEM_SERVICE_UNAVAILABLE.value,
        ErrorCode.SYSTEM_TIMEOUT.value,
    }
    if code == ErrorCode.KNOWLEDGE_INDEX_WRITE_BLOCKED.value:
        retryable = False

    return ClassifiedIngestionException(
        error_code=code,
        error_message=None if code else raw_message or None,
        retryable=retryable,
    )


def ingestion_error_fields(
    exception: BaseException | Mapping[str, Any] | str,
    stage: str,
) -> dict[str, Optional[str]]:
    """Return only the mutually-exclusive lifecycle error fields."""
    classified = classify_ingestion_exception(exception, stage)
    return {
        "error_code": classified.error_code,
        "error_message": classified.error_message,
    }
