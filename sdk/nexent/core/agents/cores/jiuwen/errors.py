# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Safe Jiuwen diagnostics reuse the shared model and MCP error contracts."""

import asyncio
import re

from httpx import TimeoutException
from jsonschema import ValidationError

from nexent.consts.mcp_errors import classify_mcp_failure, mcp_failure_message
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.model_service.contracts import ModelError
from nexent.core.model_service.errors import model_error_message
from nexent.core.model_service.service import ModelServiceError


_SOURCES = {
    "tool": ("工具", "Tool"),
    "mcp": ("MCP 工具", "MCP tool"),
    "sandbox": ("代码工具/沙箱", "Code tool/sandbox"),
    "subagent": ("子智能体", "Subagent"),
    "a2a": ("A2A 智能体", "A2A agent"),
}
_PROTOCOL_MESSAGES = {
    "JIUWEN_CONTEXT_BUSY": (
        "上下文维护资源繁忙，等待执行名额超时，请稍后重试。",
        "Context maintenance resources are busy; admission timed out. Try again later.",
    ),
    "JIUWEN_UNAUTHORIZED_TOOL": (
        "模型尝试调用未授权的工具，请检查模型生成的工具名称。",
        "The model requested an unauthorized tool. Check the generated tool name.",
    ),
    "JIUWEN_TERMINAL_MISSING": ("智能体执行结束但未返回最终结果。", "The agent ended without a final result."),
    "JIUWEN_DUPLICATE_TERMINAL": ("智能体返回了重复的最终结果。", "The agent returned duplicate final results."),
    "JIUWEN_FINAL_OUTPUT_INVALID": ("智能体最终输出格式无效。", "The agent's final output format is invalid."),
    "JIUWEN_DELEGATION_REQUIRED": ("模型未按要求调用子智能体。", "The model did not perform the required delegation."),
    "INVALID_TOOL_ARGUMENTS": ("模型生成的工具参数不符合工具定义。", "The model generated invalid tool arguments."),
    "JIUWEN_CONFIGURATION_INVALID": (
        "Jiuwen 智能体配置无效或尚不支持，请检查配置。",
        "The Jiuwen agent configuration is invalid or unsupported. Check its settings.",
    ),
    "JIUWEN_PREPARATION_FAILED": (
        "智能体执行资源准备失败，请检查工具、Skills 和沙箱配置。",
        "Agent resource preparation failed. Check tools, Skills and sandbox configuration.",
    ),
    "JIUWEN_CLEANUP_FAILED": ("智能体执行资源释放失败。", "Agent execution resource cleanup failed."),
    "JIUWEN_EXECUTION_FAILED": (
        "智能体运行失败，请根据请求标识检查运行日志。",
        "Agent execution failed. Check the runtime logs using the request ID.",
    ),
}
_MODEL_MESSAGES = {
    "MODEL_STREAM_INCOMPLETE": ("模型响应流在完整输出前结束。", "The model response stream ended before completion."),
    "MODEL_DUPLICATE_COMPLETION": ("模型返回了重复的完成消息。", "The model returned duplicate completion messages."),
    "MODEL_STREAM_COMPLETION_MISMATCH": (
        "模型流式内容与最终完成消息不一致。",
        "Model stream content does not match its final completion.",
    ),
    "MODEL_RESPONSE_REFUSED": ("模型拒绝了本次请求。", "The model refused this request."),
}


def _chain(error):
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        if isinstance(current, BaseExceptionGroup):
            pending.extend(reversed(current.exceptions))
        cause = current.__cause__ or current.__context__
        if cause is not None:
            pending.append(cause)


def public_error(error, lang):
    """Render model diagnostics at the output boundary without mutating their source."""
    if error.category.startswith("MODEL_"):
        specific = _MODEL_MESSAGES.get(error.category)
        chinese = lang.lower().split("-")[0].split("_")[0] == "zh"
        return error.model_copy(
            update={"safe_message": specific[0 if chinese else 1] if specific else model_error_message(error, lang)}
        )
    if error.safe_message == error.category:
        return protocol_error(error.category, request_id=error.request_id, lang=lang)
    return error


def protocol_error(category, *, request_id, lang):
    chinese = lang.lower().split("-")[0].split("_")[0] == "zh"
    messages = _PROTOCOL_MESSAGES.get(category)
    if messages is None:
        messages = (
            "无法处理模型生成的执行协议，请检查模型输出格式。",
            "The model's execution protocol could not be processed. Check its output format.",
        )
    return ModelError(
        category=category,
        scope="protocol",
        retryable=False,
        safe_message=messages[0 if chinese else 1],
        request_id=request_id,
    )


def failure_error(error, *, request_id, lang="en", source="agent", name=None, phase="execution"):
    """Attribute known boundaries and expose only controlled diagnostic messages."""
    chain = list(_chain(error))
    controls = (asyncio.CancelledError, RunTerminated, KeyboardInterrupt, SystemExit)
    if isinstance(error, controls):
        return None
    # wait_for uses CancelledError as the cause of a real deadline failure.
    meaningful_deadline = any(isinstance(item, (TimeoutError, TimeoutException, ModelServiceError)) for item in chain)
    real_leaves = [
        item
        for item in chain
        if not isinstance(item, (*controls, BaseExceptionGroup))
        and item.__cause__ is None
        and item.__context__ is None
    ]
    if any(isinstance(item, controls) for item in chain) and not meaningful_deadline and not real_leaves:
        return None
    for item in chain:
        if isinstance(item, ModelServiceError):
            return item.error
    for item in chain:
        resource = getattr(item, "_nexent_resource_error", None)
        if isinstance(resource, ModelError):
            return resource
    if source not in _SOURCES:
        category = {
            "configuration": "JIUWEN_CONFIGURATION_INVALID",
            "preparation": "JIUWEN_PREPARATION_FAILED",
            "cleanup": "JIUWEN_CLEANUP_FAILED",
        }.get(phase, "JIUWEN_EXECUTION_FAILED")
        return protocol_error(category, request_id=request_id, lang=lang)
    chinese = lang.lower().split("-")[0].split("_")[0] == "zh"
    label = _SOURCES[source][0 if chinese else 1]
    if name:
        safe_name = re.sub(r"[^\w .-]", "", str(name))[:80]
        label += f" [{safe_name}]"
    timeout = any(isinstance(item, (TimeoutError, TimeoutException)) for item in chain)
    invalid = any(isinstance(item, ValidationError) for item in chain)
    detail = "timeout" if timeout else "invalid_arguments" if invalid else "execution_error"
    retryable = timeout
    if source == "mcp" and not invalid:
        category, _ = ("timeout", None) if timeout else classify_mcp_failure(error)
        if category:
            detail = category
            message = mcp_failure_message(category, "zh" if chinese else "en")
            retryable = category in {"timeout", "connection_refused", "connection_dropped", "dns_failure"}
        else:
            message = (
                "MCP 工具执行失败，请检查该工具的服务日志。"
                if chinese
                else "MCP tool execution failed. Check its service logs."
            )
    else:
        messages = {
            "timeout": (
                "执行超时，请检查服务响应和超时配置。",
                "Execution timed out. Check the service response and timeout settings.",
            ),
            "invalid_arguments": ("调用参数不符合工具定义。", "Arguments do not match the tool schema."),
            "execution_error": (
                "执行失败，请检查该资源的运行日志。",
                "Execution failed. Check the resource's runtime logs.",
            ),
        }
        message = messages[detail][0 if chinese else 1]
        if detail == "execution_error":
            reasons = (
                (
                    FileNotFoundError,
                    "所需文件不存在，请检查附件、Skill 或工作目录。",
                    "A required file is missing. Check attachments, Skill files and the workspace.",
                ),
                (
                    PermissionError,
                    "缺少访问所需文件或服务的权限。",
                    "Permission to access a required file or service was denied.",
                ),
                (
                    ImportError,
                    "执行环境缺少依赖模块，请检查环境配置。",
                    "A required dependency is unavailable. Check the execution environment.",
                ),
                (
                    TypeError,
                    "参数类型或工具函数签名不匹配。",
                    "Argument types do not match the tool function signature.",
                ),
            )
            for kind, zh, en in reasons:
                if any(isinstance(item, kind) for item in chain):
                    message = (zh if chinese else en) + f" [{kind.__name__}]"
                    break
    return ModelError(
        category=f"{source}_{detail}",
        scope="protocol",
        retryable=retryable,
        safe_message=f"{label}: {message}",
        request_id=request_id,
    )
