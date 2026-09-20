import pytest
from nexent.core.models.retry import (
    DEFAULT_MODEL_RETRY,
    ModelErrorCode,
    classify_model_error,
)


class HttpError(RuntimeError):
    def __init__(self, status_code: int, message: str = "provider error"):
        super().__init__(message)
        self.status_code = status_code


def test_cmsr_001_default_budget_is_five_total_attempts():
    assert DEFAULT_MODEL_RETRY.max_attempts == 5


@pytest.mark.parametrize(
    ("error", "retryable", "error_code"),
    [
        (HttpError(429), True, ModelErrorCode.RATE_LIMIT_EXHAUSTED),
        (HttpError(503), True, ModelErrorCode.SERVICE_UNAVAILABLE),
        (TimeoutError("read timeout"), True, ModelErrorCode.TIMEOUT),
        (ConnectionError("connection reset"), True, ModelErrorCode.CONNECTION_ERROR),
        (HttpError(401), False, ModelErrorCode.AUTHENTICATION_ERROR),
        (HttpError(404), False, ModelErrorCode.NOT_FOUND),
        (HttpError(422), False, ModelErrorCode.INVALID_REQUEST),
        (HttpError(418), False, ModelErrorCode.UNKNOWN_ERROR),
        (RuntimeError("context length exceeded"), False, ModelErrorCode.CONTEXT_OVERFLOW),
        (RuntimeError("unauthorized api key"), False, ModelErrorCode.AUTHENTICATION_ERROR),
        (RuntimeError("404 not found"), False, ModelErrorCode.NOT_FOUND),
        (RuntimeError("400 bad request"), False, ModelErrorCode.INVALID_REQUEST),
        (RuntimeError("429 rate limit"), True, ModelErrorCode.RATE_LIMIT_EXHAUSTED),
        (RuntimeError("503 server error"), True, ModelErrorCode.SERVICE_UNAVAILABLE),
        (RuntimeError("connection refused"), True, ModelErrorCode.CONNECTION_ERROR),
        (RuntimeError("read timeout"), True, ModelErrorCode.TIMEOUT),
        (RuntimeError("unclassified provider bug"), False, ModelErrorCode.UNKNOWN_ERROR),
    ],
)
def test_cmsr_002_error_classification_is_typed(error, retryable, error_code):
    classification = classify_model_error(error)

    assert classification.retryable is retryable
    assert classification.error_code is error_code
