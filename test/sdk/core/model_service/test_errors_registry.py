# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Safe error and explicit registration boundaries, without actual provider calls."""

import json

import pytest
from nexent.core.model_service.adapters.openai_chat import (
    ModelAdapterError,
    OpenAIChatAdapter,
)
from nexent.core.model_service.contracts import ModelError
from nexent.core.model_service.errors import normalize_model_error
from nexent.core.model_service.http_contracts import (
    ModelTransportError,
    RawHttpResponse,
)
from pydantic import ValidationError


@pytest.mark.parametrize(
    "status,category,retryable",
    [
        (401, "MODEL_AUTHENTICATION_ERROR", False),
        (403, "MODEL_AUTHENTICATION_ERROR", False),
        (404, "MODEL_NOT_FOUND", False),
        (429, "MODEL_RATE_LIMITED", True),
        (500, "MODEL_SERVICE_UNAVAILABLE", True),
        (503, "MODEL_SERVICE_UNAVAILABLE", True),
        (400, "MODEL_REQUEST_INVALID", False),
        (422, "MODEL_REQUEST_INVALID", False),
        (301, "MODEL_HTTP_ERROR", False),
    ],
)
def test_status_classification_never_echoes_provider_payload(
    status, category, retryable
):
    error = ModelTransportError(
        "HTTP_STATUS_ERROR", response=RawHttpResponse(status, {}, b"dummy-private")
    )
    public = normalize_model_error(
        error, request_id="r1", attempt=1, max_attempts=3, will_retry=True
    )
    assert public.category == category and public.retryable is retryable
    assert public.will_retry is retryable and public.scope == "provider"
    assert "dummy-private" not in str(public.model_dump())


@pytest.mark.parametrize(
    "category,expected,retryable",
    [
        ("HTTP_TIMEOUT", "MODEL_TIMEOUT", True),
        ("HTTP_NETWORK_ERROR", "MODEL_NETWORK_ERROR", True),
        ("HTTP_TLS_ERROR", "MODEL_TLS_ERROR", False),
        ("CREDENTIAL_RESOLUTION_FAILED", "MODEL_CREDENTIAL_ERROR", False),
        ("CREDENTIAL_HEADER_CONFLICT", "MODEL_CREDENTIAL_ERROR", False),
        ("HTTP_STREAM_FORMAT_INVALID", "MODEL_PROTOCOL_ERROR", False),
    ],
)
def test_transport_classification_has_explicit_retry_policy(
    category, expected, retryable
):
    public = normalize_model_error(
        ModelTransportError(category), request_id="r1", max_attempts=3, will_retry=True
    )
    assert public.category == expected and public.retryable is retryable
    assert public.will_retry is retryable


@pytest.mark.parametrize(
    "status,code,expected,retryable",
    [
        (429, "insufficient_quota", "MODEL_QUOTA_EXHAUSTED", False),
        (400, "context_length_exceeded", "MODEL_CONTEXT_EXCEEDED", False),
        (200, "invalid_api_key", "MODEL_AUTHENTICATION_ERROR", False),
        (200, "rate_limit_exceeded", "MODEL_RATE_LIMITED", True),
        (401, "rate_limit_exceeded", "MODEL_AUTHENTICATION_ERROR", False),
        (404, "rate_limit_exceeded", "MODEL_NOT_FOUND", False),
        (200, "model_not_found", "MODEL_NOT_FOUND", False),
    ],
)
def test_only_known_provider_codes_affect_control_and_auth_status_never_retries(
    status, code, expected, retryable
):
    raw = RawHttpResponse(
        status,
        {},
        json.dumps({"error": {"code": code, "message": "dummy-private"}}).encode(),
    )
    public = normalize_model_error(
        ModelTransportError("HTTP_STATUS_ERROR", response=raw),
        request_id="r1",
        max_attempts=3,
        will_retry=True,
    )
    assert public.category == expected and public.retryable is retryable
    assert public.provider_code == code
    assert "dummy-private" not in str(public.model_dump())


@pytest.mark.parametrize(
    "body",
    [
        b'{"error":{"code":"dummy-private","message":"dummy-private"}}',
        b'{"error":{"code":2}}',
        b'{"error":false}',
        b"\xff",
        b"{broken",
    ],
)
def test_unknown_or_malformed_provider_body_keeps_safe_status_classification(body):
    public = normalize_model_error(
        ModelTransportError(
            "HTTP_STATUS_ERROR", response=RawHttpResponse(500, {}, body)
        ),
        request_id="r1",
    )
    assert public.category == "MODEL_SERVICE_UNAVAILABLE"
    assert public.provider_code is None
    assert "dummy-private" not in repr(public)


def test_retryable_is_distinct_from_remaining_attempts_and_visible_output_decision():
    error = ModelTransportError("HTTP_TIMEOUT")
    exhausted = normalize_model_error(
        error, request_id="r1", attempt=3, max_attempts=3, will_retry=True
    )
    visible = normalize_model_error(
        error, request_id="r1", attempt=1, max_attempts=3, will_retry=False
    )
    assert exhausted.retryable and not exhausted.will_retry
    assert visible.retryable and not visible.will_retry


def test_unknown_exception_and_protocol_text_are_not_public_diagnostics():
    for error in [ValueError("dummy-private"), ModelAdapterError("dummy-private")]:
        public = normalize_model_error(error, request_id="r1")
        assert public.category == "MODEL_PROTOCOL_ERROR"
        assert "dummy-private" not in str(public.model_dump())


def test_attempt_invariants_do_not_allow_impossible_retry_claims():
    values = {
        "category": "MODEL_TIMEOUT",
        "scope": "transport",
        "retryable": True,
        "will_retry": True,
        "attempt": 1,
        "max_attempts": 3,
        "safe_message": "Request timed out.",
        "request_id": "r1",
    }
    for update in [{"attempt": 4}, {"attempt": 3}, {"retryable": False}]:
        with pytest.raises(ValidationError):
            ModelError(**(values | update))


def test_adapter_error_normalization_uses_the_shared_safe_contract():
    public = OpenAIChatAdapter().normalize_error(
        ModelTransportError("HTTP_TIMEOUT"),
        request_id="r1",
        attempt=1,
        max_attempts=3,
        will_retry=True,
    )
    assert public.category == "MODEL_TIMEOUT" and public.will_retry


def test_success_status_error_envelopes_are_not_completed_messages(openai_profile):
    from nexent.core.model_service.adapters.openai_stream import OpenAIStreamDecoder
    from nexent.core.model_service.contracts import ModelMessage, ModelRequest
    from nexent.core.model_service.sse import SSEEvent

    req = ModelRequest(
        request_id="r1",
        outlet_id=openai_profile.outlet_id,
        config_revision=openai_profile.config_revision,
        messages=[ModelMessage(semantic_role="user")],
        stream=True,
    )
    body = b'{"error":{"code":"insufficient_quota","message":"dummy-private"}}'
    raw = RawHttpResponse(200, {}, body)
    for decode in [
        lambda: OpenAIChatAdapter().decode_response(raw, req, openai_profile),
        lambda: OpenAIStreamDecoder(req, openai_profile).push(SSEEvent(body.decode())),
    ]:
        with pytest.raises(ModelAdapterError, match="^MODEL_PROVIDER_ERROR$") as caught:
            decode()
        error = normalize_model_error(
            caught.value, request_id="r1", max_attempts=3, will_retry=True
        )
        assert error.category == "MODEL_QUOTA_EXHAUSTED" and not error.will_retry
        assert "dummy-private" not in repr(caught.value)
        assert "dummy-private" not in str(error.model_dump())
