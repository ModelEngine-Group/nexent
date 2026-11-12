# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Existing tool observation and monitoring wrappers."""

import functools
import inspect
from typing import Any, Callable, Dict

from nexent.monitor import get_monitoring_manager


def _tool_name(tool_obj: Any) -> str:
    """Return the most useful tool name for monitoring."""
    return (
        getattr(tool_obj, "name", None)
        or getattr(tool_obj, "__name__", None)
        or type(tool_obj).__name__
    )


def _is_retriever_tool(tool_obj: Any) -> bool:
    """Classify tools that should use RETRIEVER rather than TOOL semantics."""
    name = type(tool_obj).__name__
    return name in ("KnowledgeBaseSearchTool", "SearchMemoryTool")


def _build_tool_input(callable_obj: Callable, args: tuple, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort conversion of tool call arguments into span input attributes."""
    try:
        signature = inspect.signature(callable_obj)
        bound = signature.bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except (TypeError, ValueError):
        tool_input: Dict[str, Any] = {}
        if args:
            tool_input["args"] = list(args)
        if kwargs:
            tool_input.update(kwargs)
        return tool_input


def _wrap_tool_with_monitoring(tool_obj: Any, agent_name: str) -> Any:
    """Wrap smolagents tools and callables with a tool span."""
    if getattr(tool_obj, "_nexent_monitoring_wrapped", False):
        return tool_obj

    monitoring_manager = get_monitoring_manager()
    tool_name = _tool_name(tool_obj)
    is_retriever_tool = _is_retriever_tool(tool_obj)

    def monitored_span(tool_input: Dict[str, Any]):
        if is_retriever_tool:
            return monitoring_manager.trace_retriever_call(
                tool_name,
                agent_name,
                tool_input,
            )
        return monitoring_manager.trace_tool_call(tool_name, agent_name, tool_input)

    def set_monitored_output(result: Any) -> None:
        if is_retriever_tool:
            monitoring_manager.set_retriever_output(result)
        else:
            monitoring_manager.set_tool_output(result)

    if hasattr(tool_obj, "forward") and callable(tool_obj.forward):
        original_forward = tool_obj.forward

        if inspect.iscoroutinefunction(original_forward):
            @functools.wraps(original_forward)
            async def monitored_forward(*args, **kwargs):
                tool_input = _build_tool_input(original_forward, args, kwargs)
                with monitored_span(tool_input):
                    result = await original_forward(*args, **kwargs)
                    set_monitored_output(result)
                    return result
        else:
            @functools.wraps(original_forward)
            def monitored_forward(*args, **kwargs):
                tool_input = _build_tool_input(original_forward, args, kwargs)
                with monitored_span(tool_input):
                    result = original_forward(*args, **kwargs)
                    set_monitored_output(result)
                    return result

        tool_obj.forward = monitored_forward
        setattr(tool_obj, "_nexent_monitoring_wrapped", True)
        return tool_obj

    if callable(tool_obj):
        original_callable = tool_obj

        if inspect.iscoroutinefunction(original_callable):
            @functools.wraps(original_callable)
            async def monitored_callable(*args, **kwargs):
                tool_input = _build_tool_input(original_callable, args, kwargs)
                with monitored_span(tool_input):
                    result = await original_callable(*args, **kwargs)
                    set_monitored_output(result)
                    return result
        else:
            @functools.wraps(original_callable)
            def monitored_callable(*args, **kwargs):
                tool_input = _build_tool_input(original_callable, args, kwargs)
                with monitored_span(tool_input):
                    result = original_callable(*args, **kwargs)
                    set_monitored_output(result)
                    return result

        setattr(monitored_callable, "_nexent_monitoring_wrapped", True)
        return monitored_callable

    return tool_obj
