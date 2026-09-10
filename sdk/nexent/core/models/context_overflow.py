"""Conservative Provider context-overflow classification and recovery errors."""

from collections.abc import Mapping


class ProviderContextOverflowRecoveryError(RuntimeError):
    """Base error for bounded Provider context-overflow recovery."""


class ProviderContextOverflowRetryUnsafe(ProviderContextOverflowRecoveryError):
    pass


class ProviderContextOverflowRetryExhausted(ProviderContextOverflowRecoveryError):
    pass


def is_provider_context_overflow(error: BaseException) -> bool:
    """Return true only for explicit OpenAI-compatible context limit errors."""
    code = getattr(error, "code", None)
    body = getattr(error, "body", None)
    if isinstance(body, Mapping):
        nested = body.get("error") if isinstance(body.get("error"), Mapping) else body
        code = code or nested.get("code") or nested.get("type")
    if str(code or "").lower() in {
        "context_length_exceeded",
        "max_tokens_exceeded",
        "input_too_long",
    }:
        return True
    message = str(error).lower()
    return any(marker in message for marker in (
        "context_length_exceeded",
        "maximum context length",
        "input tokens exceed",
        "input and request output exceed",
        "too many tokens",
    ))
