"""D1 SDK unit tests for Provider context-overflow classification and recovery error hierarchy."""

from __future__ import annotations

import pytest

from nexent.core.models.context_overflow import (
    ProviderContextOverflowRecoveryError,
    ProviderContextOverflowRetryExhausted,
    ProviderContextOverflowRetryUnsafe,
    is_provider_context_overflow,
)


class FakeError(BaseException):
    def __init__(self, code=None, body=None, message=""):
        self.code = code
        self.body = body
        super().__init__(message)


@pytest.mark.case_id("UT-SDK-AUTO-2EBD3B18F61B382A")
@pytest.mark.stage("D1")
def test_provider_context_overflow_classification_and_recovery_hierarchy():
    for code in (
        "context_length_exceeded",
        "context_overflow",
        "context_window_exceeded",
        "max_tokens_exceeded",
        "input_too_long",
    ):
        assert is_provider_context_overflow(FakeError(code=code)) is True

    for message in ("maximum context length", "too many tokens", "input tokens exceed"):
        assert is_provider_context_overflow(FakeError(code=None, message=message)) is True
        assert is_provider_context_overflow(FakeError(code="400", message=message)) is True

    assert is_provider_context_overflow(FakeError(code=None, message="MAXIMUM CONTEXT LENGTH")) is True

    assert is_provider_context_overflow(FakeError(body={"error": {"code": "context_length_exceeded"}})) is True
    assert is_provider_context_overflow(FakeError(body={"error": {"error_code": "context_overflow"}})) is True
    assert is_provider_context_overflow(FakeError(body={"error": {"type": "max_tokens_exceeded"}})) is True

    assert is_provider_context_overflow(FakeError(code="400", message="bad request")) is False
    assert is_provider_context_overflow(FakeError(code="invalid_request_error", message="something went wrong")) is False

    assert is_provider_context_overflow(FakeError(code=None, body=None, message="hello")) is False
    assert is_provider_context_overflow(FakeError(code=None, body={}, message="hello")) is False
    assert is_provider_context_overflow(FakeError(code=None, body="plain text", message="hello")) is False
    assert is_provider_context_overflow(FakeError(code=None, body=["a", "b"], message="hello")) is False
    assert is_provider_context_overflow(FakeError(code=None, body="maximum context length", message="")) is True

    assert issubclass(ProviderContextOverflowRecoveryError, RuntimeError)
    assert issubclass(ProviderContextOverflowRetryUnsafe, ProviderContextOverflowRecoveryError)
    assert issubclass(ProviderContextOverflowRetryExhausted, ProviderContextOverflowRecoveryError)

    with pytest.raises(ProviderContextOverflowRecoveryError):
        raise ProviderContextOverflowRetryUnsafe("recovery failed")
    with pytest.raises(ProviderContextOverflowRecoveryError):
        raise ProviderContextOverflowRetryExhausted("recovery failed")
