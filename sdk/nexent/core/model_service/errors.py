# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Stable retry classification with shared HTTP-boundary display diagnostics."""

from nexent.core.model_service.adapters.openai_chat import ModelAdapterError
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
    "MODEL_EMPTY_RESPONSE": (False, "The model returned no answer content or tool calls."),
    "MODEL_CONCURRENCY_TIMEOUT": (False, "Model concurrency admission timed out."),
    "MODEL_RUN_DEADLINE": (False, "The model run time budget was exhausted."),
}
_CATEGORY_ZH = {
    "MODEL_AUTHENTICATION_ERROR": "模型服务认证失败，请检查 API Key 或 HTTP Header。",
    "MODEL_NOT_FOUND": "未找到请求的模型或服务路由。",
    "MODEL_RATE_LIMITED": "模型服务请求受限，请稍后重试。",
    "MODEL_SERVICE_UNAVAILABLE": "模型服务暂时不可用。",
    "MODEL_REQUEST_INVALID": "模型服务拒绝了请求参数。",
    "MODEL_CONTEXT_EXCEEDED": "请求超出模型的上下文限制。",
    "MODEL_QUOTA_EXHAUSTED": "模型服务额度不足。",
    "MODEL_TIMEOUT": "模型服务请求超时。",
    "MODEL_NETWORK_ERROR": "无法连接模型服务或连接已中断。",
    "MODEL_TLS_ERROR": "模型服务 TLS 连接或证书校验失败。",
    "MODEL_HTTP_ERROR": "模型服务返回了非预期的 HTTP 状态码。",
    "MODEL_PROVIDER_ERROR": "模型服务在响应中返回错误。",
    "MODEL_CREDENTIAL_ERROR": "无法读取模型服务凭据或认证 Header 冲突。",
    "MODEL_PROTOCOL_ERROR": "无法解析模型服务响应。",
    "MODEL_EMPTY_RESPONSE": "模型没有返回有效正文或工具调用。",
    "MODEL_CONCURRENCY_TIMEOUT": "等待模型请求执行名额超时。",
    "MODEL_RUN_DEADLINE": "模型运行时间预算已耗尽。",
}
# Specific diagnostics retain the broad category used by retry policy.
_DIAGNOSTICS = {
    "MODEL_RESPONSE_INCOMPLETE": ("The response ended without a generation completion marker.", "响应在收到生成结束标记前中断。"),
    "MODEL_STREAM_AFTER_FINISH": ("Received additional content or tool-call data after the generation completion marker.", "收到生成结束标记后，又收到新增正文、思考、拒绝内容或工具调用数据。"),
    "MODEL_STREAM_FINISH_CONFLICT": ("Received conflicting generation completion reasons.", "模型服务返回了互相冲突的生成结束原因。"),
    "MODEL_USAGE_CONFLICT": ("The model service returned conflicting token usage statistics.", "模型服务返回了互相冲突的 Token 用量统计。"),
    "MODEL_USAGE_INVALID": ("The token usage statistics have an invalid structure or value.", "Token 用量统计的结构或数值无效。"),
    "MODEL_STREAM_IDENTITY_CONFLICT": ("The response identifier, model identifier or tool-call identifier changed within one stream.", "同一响应流中的响应 ID、模型 ID 或工具调用 ID 发生冲突。"),
    "MODEL_RESPONSE_INVALID": ("The model response has invalid JSON, fields or field types.", "模型响应的 JSON、字段结构或字段类型无效。"),
    "MODEL_TOOL_CALL_INVALID": ("The model response contains an invalid or incomplete tool call.", "模型响应包含无效或不完整的工具调用。"),
    "MODEL_TOOL_CALL_LIMIT": ("The response exceeded the maximum number of tool calls.", "模型响应的工具调用数量超过限制。"),
    "MODEL_RESPONSE_TOO_LARGE": ("The model response exceeded the configured size limit.", "模型响应超过配置的大小限制。"),
    "HTTP_RESPONSE_TOO_LARGE": ("The model HTTP response exceeded the configured size limit.", "模型服务的 HTTP 响应超过配置的大小限制。"),
    "HTTP_STREAM_FORMAT_INVALID": ("The model service did not return an SSE event stream.", "模型服务没有返回 SSE 流式响应。"),
    "MODEL_STREAM_CLOSED": ("Received a response fragment after the stream was closed.", "响应流关闭后又收到响应分片。"),
    "MODEL_STREAM_REQUEST_REQUIRED": ("The streaming decoder requires a streaming request.", "流式响应解析器需要流式请求。"),
    "MODEL_PROTOCOL_UNSUPPORTED": ("The configured model protocol is unsupported.", "不支持所配置的模型协议。"),
    "MODEL_CONTENT_UNSUPPORTED": ("The request contains an unsupported content type.", "请求包含不支持的内容类型。"),
    "MODEL_MESSAGE_INVALID": ("The request message structure is invalid.", "请求消息的结构无效。"),
    "MODEL_REASONING_FORMAT_UNSUPPORTED": ("The configured reasoning parameter format is unsupported.", "不支持所配置的思考参数格式。"),
    "MODEL_REQUEST_CONFIGURATION_INVALID": ("The model request configuration is invalid.", "模型请求配置无效。"),
    "MODEL_ROLE_UNSUPPORTED": ("The request contains an unsupported message role.", "请求包含不支持的消息角色。"),
    "MODEL_SNAPSHOT_MISMATCH": ("The request does not match the model configuration snapshot.", "请求与模型配置快照不一致。"),
}


def model_error_message(error: ModelError, lang: str = "en") -> str:
    """Render one normalized diagnostic for probes and Agent terminals."""
    chinese = lang.lower().split("-")[0].split("_")[0] == "zh"
    if error.message_source == "provider":
        prefix = "模型服务原始错误：" if chinese else "Original model service error: "
        return prefix + error.safe_message
    specific = _DIAGNOSTICS.get(error.diagnostic_code)
    if specific:
        message = specific[1 if chinese else 0]
    elif error.category in _CATEGORIES:
        message = _CATEGORY_ZH[error.category] if chinese else _CATEGORIES[error.category][1]
    else:
        message = "未识别的模型请求错误。" if chinese else "Unrecognized model request error."
    if error.http_status is not None and not 200 <= error.http_status < 300:
        message = f"({error.http_status}) {message}"
    if error.parameter_name:
        message += f" [{error.parameter_name}]"
    return message

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
    status, parameter_name = None, None
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
        detail = response.error_details()
        code = detail["code"]
        if code in _PROVIDER_CODES:
            provider_code = code
            mapped = _PROVIDER_CODES[code]
            if mapped != "MODEL_RATE_LIMITED" or status == 429 or 500 <= status < 600 or 200 <= status < 300:
                category = mapped
        parameter = detail["parameter"]
        if parameter in {"model", "temperature", "top_p", "max_tokens", "reasoning_effort",
                         "thinking_budget", "thinking_token_budget", "enable_thinking", "chat_template_kwargs"}:
            parameter_name = parameter
    retryable, message = _CATEGORIES[category]
    diagnostic = getattr(error, "category", None)
    diagnostic = diagnostic if diagnostic in _DIAGNOSTICS else category
    source = "system"
    if response is not None:
        # Only explicitly recognized provider codes replace a vendor's wording.
        if provider_code is None and detail["message"]:
            message = detail["message"]
            source = "provider"
        if not 200 <= status < 300:
            message = f"({status}) {message}"
    elif diagnostic in _DIAGNOSTICS:
        message = _DIAGNOSTICS[diagnostic][0]
    return ModelError(
        diagnostic_code=diagnostic,
        message_source=source,
        category=category,
        scope=scope,
        retryable=retryable,
        will_retry=will_retry and retryable and attempt < max_attempts,
        attempt=attempt,
        max_attempts=max_attempts,
        provider_code=provider_code,
        safe_message=message,
        request_id=request_id,
        http_status=status,
        parameter_name=parameter_name,
    )
