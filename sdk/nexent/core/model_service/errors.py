# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Fixed error classification; provider text remains private to the adapter."""

from nexent.core.model_service.adapters.openai_chat import ModelAdapterError, parse_json
from nexent.core.model_service.contracts import ModelError
from nexent.core.model_service.http_contracts import ModelTransportError


_CATEGORIES = {
    "MODEL_AUTHENTICATION_ERROR": (False, "Model service authentication failed."),
    "MODEL_NOT_FOUND": (False, "The requested model service was not found."),
    "MODEL_RATE_LIMITED": (True, "The model service is rate limited."),
    "MODEL_SERVICE_UNAVAILABLE": (True, "The model service is temporarily unavailable."),
    "MODEL_REQUEST_INVALID": (False, "The model service rejected the request."),
    "MODEL_CONTEXT_EXCEEDED": (False, "The model service context limit was exceeded."),
    "MODEL_QUOTA_EXHAUSTED": (False, "The model service quota is exhausted."),
    "MODEL_TIMEOUT": (True, "The model request timed out."),
    "MODEL_NETWORK_ERROR": (True, "The model service connection failed."),
    "MODEL_TLS_ERROR": (False, "The model service TLS connection failed."),
    "MODEL_HTTP_ERROR": (False, "The model service returned an unsupported HTTP status."),
    "MODEL_PROVIDER_ERROR": (False, "The model service returned a provider error."),
    "MODEL_CREDENTIAL_ERROR": (False, "Model service credentials could not be resolved."),
    "MODEL_PROTOCOL_ERROR": (False, "The model response could not be processed."),
    "MODEL_CONCURRENCY_TIMEOUT": (False, "Model concurrency admission timed out."),
    "MODEL_RUN_DEADLINE": (False, "The model run time budget was exhausted."),
}
_PROVIDER_CODES = {
    "context_length_exceeded": "MODEL_CONTEXT_EXCEEDED",
    "invalid_api_key": "MODEL_AUTHENTICATION_ERROR",
    "insufficient_quota": "MODEL_QUOTA_EXHAUSTED",
    "model_not_found": "MODEL_NOT_FOUND",
    "rate_limit_exceeded": "MODEL_RATE_LIMITED",
}


def normalize_model_error(
    error, *, request_id: str, attempt: int = 1, max_attempts: int = 1, will_retry: bool = False
) -> ModelError:
    """Classify trusted error types and known codes, never arbitrary error messages."""
    category, scope, provider_code = "MODEL_PROTOCOL_ERROR", "protocol", None
    if isinstance(error, ModelTransportError):
        scope = "transport"
        category = {
            "HTTP_TIMEOUT": "MODEL_TIMEOUT",
            "HTTP_NETWORK_ERROR": "MODEL_NETWORK_ERROR",
            "HTTP_TLS_ERROR": "MODEL_TLS_ERROR",
            "CREDENTIAL_RESOLUTION_FAILED": "MODEL_CREDENTIAL_ERROR",
            "CREDENTIAL_HEADER_CONFLICT": "MODEL_CREDENTIAL_ERROR",
            "HTTP_CONCURRENCY_TIMEOUT": "MODEL_CONCURRENCY_TIMEOUT",
            "HTTP_RUN_DEADLINE": "MODEL_RUN_DEADLINE",
        }.get(error.category, "MODEL_PROTOCOL_ERROR")
    response = (
        getattr(error, "response", None) if isinstance(error, (ModelTransportError, ModelAdapterError)) else None
    )
    if response is not None:
        scope = "provider"
        status = response.status_code
        category = "MODEL_PROVIDER_ERROR" if 200 <= status < 300 else "MODEL_HTTP_ERROR"
        if status in (401, 403):
            category = "MODEL_AUTHENTICATION_ERROR"
        elif status == 404:
            category = "MODEL_NOT_FOUND"
        elif status == 429:
            category = "MODEL_RATE_LIMITED"
        elif 500 <= status < 600:
            category = "MODEL_SERVICE_UNAVAILABLE"
        elif status in (400, 422):
            category = "MODEL_REQUEST_INVALID"
        try:
            body = parse_json(response.body.decode("utf-8"))
            code = (
                body.get("error", {}).get("code")
                if isinstance(body, dict) and isinstance(body.get("error"), dict)
                else None
            )
            if isinstance(code, str) and code in _PROVIDER_CODES:
                provider_code = code
                mapped = _PROVIDER_CODES[code]
                if mapped != "MODEL_RATE_LIMITED" or status == 429 or 500 <= status < 600 or 200 <= status < 300:
                    category = mapped
        except (ValueError, TypeError, UnicodeError, RecursionError):
            pass
    retryable, message = _CATEGORIES[category]
    return ModelError(
        category=category,
        scope=scope,
        retryable=retryable,
        will_retry=will_retry and retryable and attempt < max_attempts,
        attempt=attempt,
        max_attempts=max_attempts,
        provider_code=provider_code,
        safe_message=message,
        request_id=request_id,
    )
