"""Provider-specific context-overflow normalization tests."""

import pytest

from nexent.core.models.context_overflow import is_provider_context_overflow


class ProviderError(Exception):
    def __init__(self, message="provider request failed", *, code=None, body=None):
        super().__init__(message)
        self.code = code
        self.body = body


@pytest.mark.parametrize(
    ("provider", "error"),
    [
        (
            "alibaba-bailian",
            ProviderError(
                body={
                    "error": {
                        "code": "InternalError.Algo.InvalidParameter",
                        "message": "Range of input length should be [1, 131072]",
                    }
                }
            ),
        ),
        (
            "volcengine-ark-compatible-gateway",
            ProviderError(
                "<400> InternalError.Algo.InvalidParameter: "
                "Range of input length should be [1, 983616]"
            ),
        ),
        (
            "siliconflow-openai-compatible",
            ProviderError(
                body={
                    "error": {
                        "type": "invalid_request_error",
                        "message": "This model's maximum context length is 32768 tokens; "
                        "the request has too many tokens.",
                    }
                }
            ),
        ),
        (
            "huawei-cloud-maas-v1-envelope",
            ProviderError(
                body={
                    "error_code": "400",
                    "error_msg": "This model's maximum context length is 4096 tokens. "
                    "However, you requested 8242 tokens (20 in the messages, "
                    "8222 in the completion).",
                }
            ),
        ),
        (
            "standard-structured-code",
            ProviderError(code="context_length_exceeded"),
        ),
        (
            "alibaba-total-message-limit",
            ProviderError("Total message token length exceed model limit (10000000 tokens)."),
        ),
    ],
)
def test_explicit_provider_context_overflow_is_recognized(provider, error):
    assert provider
    assert is_provider_context_overflow(error) is True


@pytest.mark.parametrize(
    "error",
    [
        ProviderError(
            code="invalid_parameter_error",
            body={"message": "temperature is out of range"},
        ),
        ProviderError("Range of max_tokens should be [1, 131072]"),
        ProviderError(code="InvalidInputLength", body={"message": "The image resolution is invalid"}),
        ProviderError(
            body={
                "error_code": "APIG.0308",
                "error_msg": "The throttling threshold has been reached",
            }
        ),
        ProviderError("finish_reason=length"),
    ],
)
def test_unrelated_provider_errors_are_not_context_overflow(error):
    assert is_provider_context_overflow(error) is False
