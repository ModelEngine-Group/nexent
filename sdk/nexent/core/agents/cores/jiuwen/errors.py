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
    "NL2AGENT_VERIFICATION_PENDING": (
        "还有资源候选需要核验，流程尚未完成。",
        "Resource verification is still pending.",
    ),
    "NL2AGENT_GENERATION_PENDING": (
        "智能体完整创建尚未完成，请查看已保存的草稿和待办步骤。",
        "Full Agent creation is still pending. Check the saved draft and remaining steps.",
    ),
    "JIUWEN_DUPLICATE_TERMINAL": ("智能体返回了重复的最终结果。", "The agent returned duplicate final results."),
    "JIUWEN_FINAL_OUTPUT_INVALID": ("智能体最终输出格式无效。", "The agent's final output format is invalid."),
    "JIUWEN_WORKBENCH_CONFIRMATION_REQUIRED": (
        "模型未返回可交互的创建确认卡。可以从输入框下方直接进入智能体创建。",
        "The model did not return an interactive creation confirmation. You can open Agent Creation from the composer.",
    ),
    "JIUWEN_DELEGATION_REQUIRED": ("模型未按要求调用子智能体。", "The model did not perform the required delegation."),
    "INVALID_TOOL_ARGUMENTS": ("模型生成的工具参数不符合工具定义。", "The model generated invalid tool arguments."),
    "JIUWEN_INVALID_CLARIFICATION": ("模型生成的澄清请求无效，请重新发送请求。",
                                     "The model generated an invalid clarification request. Please try again."),
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
_PROTOCOL_REASONS = {
    "arguments_invalid_json": ("模型生成的工具参数不是有效的 JSON。", "The model returned malformed JSON for a tool call."),
    "arguments_not_object": ("模型生成的工具参数必须是 JSON 对象。", "The tool call requires a JSON object for its arguments."),
    "arguments_duplicate_key": ("模型生成的工具参数包含重复字段。", "The model repeated a field in the tool arguments."),
    "arguments_required": ("模型调用工具时缺少必填参数。", "The model omitted a required tool argument."),
    "arguments_wrong_type": ("模型提供的工具参数类型不正确。", "The model provided a tool argument of the wrong type."),
    "arguments_extra_fields": ("模型提供了工具未定义的参数。", "The model supplied an argument the tool does not accept."),
    "arguments_unsupported_value": ("模型提供的工具参数值不在允许范围内。",
                                    "The model supplied a value that the tool does not allow."),
    "clarification_form_invalid": ("模型生成的澄清问题或选项不符合表单要求。",
                                   "The model generated invalid clarification questions or options."),
    "clarification_question_count": ("模型生成的澄清请求必须包含 1 到 5 个问题。",
                                     "The clarification request must contain one to five questions."),
    "clarification_too_few_choices": ("模型生成的澄清选择题至少需要两个选项。",
                                      "A clarification choice question needs at least two options."),
    "clarification_duplicate_ids": ("模型生成的澄清问题或选项包含重复编号。",
                                    "The clarification form contains duplicate question or option IDs."),
    "clarification_mode_mismatch": ("模型使用了当前执行模式不支持的澄清方式。",
                                     "The model used a clarification method unavailable in this execution mode."),
    "clarification_mixed_actions": ("模型同时请求澄清和其他操作。澄清必须单独发起。",
                                     "The model combined a clarification request with another action. It must ask separately."),
    "clarification_call_invalid": ("模型生成的澄清调用格式无效。",
                                   "The model generated a clarification call in an invalid format."),
    "runner_error_result": ("智能体执行引擎返回了失败结果。", "The agent runner returned a failure result."),
    "runner_invalid_answer": ("智能体执行引擎返回了格式无效的最终结果。",
                              "The agent runner returned a final result in an invalid format."),
    "runner_empty_answer": ("智能体执行引擎返回了空的最终回答。", "The agent runner returned an empty final answer."),
    "runner_round_limit": ("智能体达到执行轮数上限，未能完成任务。", "The agent reached its execution round limit before completing the task."),
    "runner_no_progress": ("智能体多次未能继续推进任务，执行已结束。", "The agent stopped after repeatedly making no progress."),
    "runner_completion_timeout": ("智能体等待任务完成超时。", "The agent timed out while waiting for the task to complete."),
    "runner_task_loop_unavailable": ("智能体执行引擎未能启动任务调度。", "The agent runner could not start task scheduling."),
    "execution_result_missing": ("智能体运行失败，执行引擎未提供具体原因。",
                                 "The agent run failed without a detailed reason from the runner."),
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


class JiuwenExecutionError(RuntimeError):
    """Describe a native execution failure without carrying its raw payload."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def public_error(error, lang):
    """Render model diagnostics at the output boundary without mutating their source."""
    if error.category.startswith("MODEL_"):
        specific = _MODEL_MESSAGES.get(error.category)
        chinese = lang.lower().split("-")[0].split("_")[0] == "zh"
        return error.model_copy(
            update={"safe_message": specific[0 if chinese else 1] if specific else model_error_message(error, lang)}
        )
    if error.safe_message == error.category:
        return protocol_error(error.category, request_id=error.request_id, lang=lang, reason=error.diagnostic_code)
    return error


def protocol_error(category, *, request_id, lang, reason=None):
    chinese = lang.lower().split("-")[0].split("_")[0] == "zh"
    messages = _PROTOCOL_REASONS.get(reason) or _PROTOCOL_MESSAGES.get(category)
    if messages is None:
        messages = (
            "无法处理模型生成的执行协议，请检查模型输出格式。",
            "The model's execution protocol could not be processed. Check its output format.",
        )
    return ModelError(
        category=category,
        diagnostic_code=reason,
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
        native_failure = next((item for item in chain if isinstance(item, JiuwenExecutionError)), None)
        reason = native_failure.reason if native_failure and category == "JIUWEN_EXECUTION_FAILED" else None
        return protocol_error(category, request_id=request_id, lang=lang, reason=reason)
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
