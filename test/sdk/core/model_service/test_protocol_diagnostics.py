"""Protocol diagnostics retain fixed categories without exposing provider material."""

import pytest

from nexent.core.model_service.adapters.openai_chat import ModelAdapterError
from nexent.core.model_service.errors import normalize_model_error
from nexent.core.model_service.http_contracts import ModelTransportError, RawHttpResponse


@pytest.mark.parametrize("code", ["MODEL_TOOL_CALL_INVALID", "MODEL_USAGE_CONFLICT", "MODEL_RESPONSE_INCOMPLETE"])
def test_known_protocol_category_is_logged_without_changing_public_contract(caplog, code):
    result = normalize_model_error(ModelAdapterError(code), request_id="internal-request")
    assert result.category == "MODEL_PROTOCOL_ERROR"
    assert result.safe_message == "The model response could not be processed."
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
