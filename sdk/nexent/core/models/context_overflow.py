"""Conservative Provider context-overflow classification and recovery errors."""

from collections.abc import Mapping
from typing import Any


class ProviderContextOverflowRecoveryError(RuntimeError):
    """Base error for bounded Provider context-overflow recovery."""


class ProviderContextOverflowRetryUnsafe(ProviderContextOverflowRecoveryError):
    pass


class ProviderContextOverflowRetryExhausted(ProviderContextOverflowRecoveryError):
    pass


_CONTEXT_OVERFLOW_CODES = {
    "context_length_exceeded",
    "context_overflow",
    "context_window_exceeded",
    "max_tokens_exceeded",
    "input_too_long",
}

_CONTEXT_OVERFLOW_MESSAGE_MARKERS = (
    "context_length_exceeded",
    "context overflow",
    "context length exceed limit",
    "context length exceeded",
    "maximum context length",
    "maximum model length",
    "input tokens exceed",
    "input and request output exceed",
    "input length exceed limit",
    "message length exceed limit",
    "range of input length should be",
    "total message token length exceed model limit",
    "too many tokens",
)


def _provider_error_text(value: Any) -> str:
    """Flatten known Provider error envelopes without trusting generic 400 codes."""
    if isinstance(value, Mapping):
        parts = []
        for key in ("message", "error_msg", "detail", "details", "error"):
            if key in value:
                parts.append(_provider_error_text(value[key]))
        return " ".join(part for part in parts if part)
    if isinstance(value, (list, tuple)):
        return " ".join(_provider_error_text(item) for item in value)
    return str(value or "")


def is_provider_context_overflow(error: BaseException) -> bool:
    """Return true only for explicit Provider context/input limit errors."""
    code = getattr(error, "code", None)
    body = getattr(error, "body", None)
    if isinstance(body, Mapping):
        nested = body.get("error") if isinstance(body.get("error"), Mapping) else body
        code = (
            code
            or nested.get("code")
            or nested.get("error_code")
            or nested.get("type")
        )
    if str(code or "").lower() in _CONTEXT_OVERFLOW_CODES:
        return True
    message = " ".join((str(error), _provider_error_text(body))).lower()
    return any(marker in message for marker in _CONTEXT_OVERFLOW_MESSAGE_MARKERS)
