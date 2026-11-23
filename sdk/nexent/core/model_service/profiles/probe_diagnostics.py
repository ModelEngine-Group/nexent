# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Safe model connectivity diagnostics independent of deployment ownership."""

def _probe_diagnostic(error):
    """Classify by known provider semantics, not arbitrary upstream error text."""
    per_model = error.category in {"MODEL_REQUEST_INVALID", "MODEL_CONTEXT_EXCEEDED", "MODEL_PROTOCOL_ERROR"}
    per_model = per_model or error.provider_code == "model_not_found"
    from nexent.core.model_service.errors import model_error_message

    return {"category": error.category, "message": model_error_message(error),
            "diagnostic_code": error.diagnostic_code, "message_source": error.message_source,
            "messages": {lang: model_error_message(error, lang) for lang in ("en", "zh")},
            "scope": "model" if per_model else "connection", "request_id": error.request_id,
            **({"http_status": error.http_status} if getattr(error, "http_status", None) is not None else {}),
            **({"parameter": error.parameter_name} if getattr(error, "parameter_name", None) else {})}
