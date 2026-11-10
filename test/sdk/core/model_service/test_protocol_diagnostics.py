# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Protocol diagnostics retain fixed categories without exposing provider material."""

import pytest

from nexent.core.model_service.adapters.openai_chat import ModelAdapterError
from nexent.core.model_service.errors import normalize_model_error
from nexent.core.model_service.http_contracts import ModelTransportError, RawHttpResponse


@pytest.mark.parametrize("code, message", [
    ("MODEL_TOOL_CALL_INVALID", "The model response contains an invalid or incomplete tool call."),
    ("MODEL_USAGE_CONFLICT", "The model service returned conflicting token usage statistics."),
    ("MODEL_RESPONSE_INCOMPLETE", "The response ended without a generation completion marker."),
])
def test_known_protocol_category_is_logged_without_changing_retry_contract(caplog, code, message):
    result = normalize_model_error(ModelAdapterError(code), request_id="internal-request")
    assert result.category == "MODEL_PROTOCOL_ERROR"
    assert result.safe_message == message
    assert result.diagnostic_code == code
    assert not result.retryable and not result.will_retry
    records = [r for r in caplog.records if "model_protocol_error" in r.message]
    assert len(records) == 1
    assert records[0].protocol_code == code
    assert records[0].request_id == "internal-request"


def test_unknown_adapter_category_is_not_logged_verbatim(caplog):
    secret = "PRIVATE_PROVIDER_BODY_AND_SIGNED_URL"
    normalize_model_error(ModelAdapterError(secret), request_id="internal-request")
    assert secret not in caplog.text
    records = [r for r in caplog.records if "model_protocol_error" in r.message]
    assert len(records) == 1 and records[0].protocol_code == "UNCLASSIFIED"


def test_provider_error_response_stays_private(caplog):
    result = normalize_model_error(
        ModelAdapterError(
            "MODEL_PROVIDER_ERROR",
            response=RawHttpResponse(
                401,
                {},
                b'{"error":{"message":"PRIVATE_PROVIDER_BODY"}}',
            ),
        ),
        request_id="internal-request",
    )
    assert result.category == "MODEL_AUTHENTICATION_ERROR"
    assert "PRIVATE_PROVIDER_BODY" not in caplog.text
    assert not any("model_protocol_error" in r.message for r in caplog.records)


@pytest.mark.parametrize("code", ["SSE_INCOMPLETE_EVENT", "SSE_INVALID_TEXT", "HTTP_STREAM_FORMAT_INVALID"])
def test_framing_diagnostic_is_preserved_without_transport_retry(caplog, code):
    result = normalize_model_error(ModelTransportError(code), request_id="internal-request")
    assert result.category == "MODEL_PROTOCOL_ERROR" and result.scope == "transport"
    assert not result.retryable
    assert len(caplog.records) == 1 and caplog.records[0].protocol_code == code


def test_untrusted_exception_text_is_not_in_diagnostics(caplog):
    result = normalize_model_error(ValueError("PRIVATE_RESPONSE_TEXT"), request_id="internal-request")
    assert result.category == "MODEL_PROTOCOL_ERROR"
    assert "PRIVATE_RESPONSE_TEXT" not in caplog.text
    assert caplog.records[0].protocol_code == "UNCLASSIFIED"


@pytest.mark.parametrize("code", ["MODEL_TOOL_CALL_INVALID", "MODEL_RESPONSE_INCOMPLETE"])
def test_logged_protocol_codes_are_canonical_strings_not_exception_objects(caplog, code):
    """An exception-controlled string representation must never reach logging."""
    class ProviderCategory(str):
        def __str__(self):
            return "PRIVATE_CREDENTIAL_FROM_EXCEPTION"

    result = normalize_model_error(ModelAdapterError(ProviderCategory(code)), request_id="internal-request")
    records = [record for record in caplog.records if "model_protocol_error" in record.message]
    assert len(records) == 1
    assert type(records[0].protocol_code) is str
    assert records[0].protocol_code == code
    assert result.diagnostic_code == code
    assert "PRIVATE_CREDENTIAL_FROM_EXCEPTION" not in caplog.text
