"""Typed terminal failures shared by model adapters and Agent boundaries.

This module deliberately lives outside ``core.models`` so Agent modules can
depend on the error contract without importing every model implementation.
"""

from __future__ import annotations

from enum import Enum


class ModelErrorCode(str, Enum):
    """Stable error categories exposed by the Agent stream boundary."""

    RATE_LIMIT_EXHAUSTED = "model_rate_limit_exhausted"
    SERVICE_UNAVAILABLE = "model_service_unavailable"
    TIMEOUT = "model_timeout"
    CONNECTION_ERROR = "model_connection_error"
    AUTHENTICATION_ERROR = "model_authentication_error"
    NOT_FOUND = "model_not_found"
    INVALID_REQUEST = "model_invalid_request"
    CONTEXT_OVERFLOW = "model_context_overflow"
    EMPTY_RESPONSE_EXHAUSTED = "model_empty_response_exhausted"
    UNKNOWN_ERROR = "model_unknown_error"


_SAFE_ERROR_MESSAGES = {
    ModelErrorCode.RATE_LIMIT_EXHAUSTED: {
        "en": "The model is receiving too many requests. Please try again later.",
        "zh": "模型请求过于频繁，请稍后重试。",
    },
    ModelErrorCode.SERVICE_UNAVAILABLE: {
        "en": "The model service is temporarily unavailable. Please try again later.",
        "zh": "模型服务暂时不可用，请稍后重试。",
    },
    ModelErrorCode.TIMEOUT: {
        "en": "The model request timed out. Please try again later.",
        "zh": "模型请求超时，请稍后重试。",
    },
    ModelErrorCode.CONNECTION_ERROR: {
        "en": "The model service connection was interrupted. Please try again later.",
        "zh": "模型服务连接中断，请稍后重试。",
    },
    ModelErrorCode.AUTHENTICATION_ERROR: {
        "en": "The model service credentials are invalid or unauthorized.",
        "zh": "模型服务凭据无效或未获授权。",
    },
    ModelErrorCode.NOT_FOUND: {
        "en": "The selected model or model endpoint was not found.",
        "zh": "未找到所选模型或模型服务地址。",
    },
    ModelErrorCode.INVALID_REQUEST: {
        "en": "The model request is invalid and cannot be retried.",
        "zh": "模型请求无效，无法重试。",
    },
    ModelErrorCode.CONTEXT_OVERFLOW: {
        "en": "The conversation is too long for the selected model.",
        "zh": "当前会话内容超出所选模型的上下文限制。",
    },
    ModelErrorCode.EMPTY_RESPONSE_EXHAUSTED: {
        "en": "The model repeatedly returned an empty response. Please try again later.",
        "zh": "模型连续返回空响应，请稍后重试。",
    },
    ModelErrorCode.UNKNOWN_ERROR: {
        "en": "The model request failed. Please try again later.",
        "zh": "模型请求失败，请稍后重试。",
    },
}


class ModelInvocationTerminalError(RuntimeError):
    """Terminal model failure that must not be repaired by another Agent step."""

    def __init__(
        self,
        error_code: ModelErrorCode,
        attempts: int,
        *,
        cause: BaseException | None = None,
    ) -> None:
        # Keep provider detail internal for logs and tracing. UI boundaries
        # must use ``safe_message`` instead of ``str``.
        super().__init__(str(cause) if cause is not None else error_code.value)
        self.error_code = error_code
        self.attempts = attempts
        self.retryable = False
        if cause is not None:
            self.__cause__ = cause

    def safe_message(self, lang: str = "en") -> str:
        messages = _SAFE_ERROR_MESSAGES[self.error_code]
        return messages.get(lang, messages["en"])
