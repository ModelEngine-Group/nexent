"""Apply configured MCP arguments to an isolated run's tool instance."""

import functools
import inspect
from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def apply_mcp_tool_parameters(tool: Any, parameters: Mapping[str, Any] | None) -> Any:
    """Give configured arguments precedence over model-provided values."""
    if not parameters:
        return tool
    configured = deepcopy(dict(parameters))
    original_forward = tool.forward

    def arguments(args, kwargs):
        if len(args) == 1 and isinstance(args[0], Mapping) and not kwargs:
            return ({**args[0], **deepcopy(configured)},), {}
        if args:
            bound = inspect.signature(original_forward).bind(*args, **kwargs)
            bound.arguments.update(deepcopy(configured))
            return bound.args, bound.kwargs
        return (), {**kwargs, **deepcopy(configured)}

    if inspect.iscoroutinefunction(original_forward):
        @functools.wraps(original_forward)
        async def forward(*args, **kwargs):
            call_args, call_kwargs = arguments(args, kwargs)
            return await original_forward(*call_args, **call_kwargs)
    else:
        @functools.wraps(original_forward)
        def forward(*args, **kwargs):
            call_args, call_kwargs = arguments(args, kwargs)
            return original_forward(*call_args, **call_kwargs)

    tool.forward = forward
    return tool
