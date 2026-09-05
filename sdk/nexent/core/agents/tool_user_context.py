"""User-context pass-through for agent tools.

The platform itself performs no authorization for tool calls. When an MCP tool's
input schema declares any of the conventional ``USER_CONTEXT_FIELDS``, the
platform injects the authenticated-session identity (tenant name, user
name/account, groups) right before execution so the tool can authorize on its
own before accessing data.

The conventional fields are hidden from the model-visible schema: the model
neither sees nor fills them, so injected values can only come from the
authenticated session.
"""
import functools
import inspect
from typing import Any, Dict, Optional

# Conventional user-context parameter names. Declaring one of these in an MCP
# tool's inputSchema means "this tool requests that user information".
USER_CONTEXT_FIELDS = (
    "tenant_id",
    "tenant_name",
    "user_id",
    "user_name",
    "user_account",
    "user_groups",
)


def apply_user_context_to_mcp_tool(tool_obj: Any, user_context: Optional[Dict[str, Any]]) -> Any:
    """Hide conventional user-context fields from the model and inject them at call time.

    Tools whose input schema declares any of ``USER_CONTEXT_FIELDS`` receive the
    session-resolved values injected right before ``forward``. Declared fields are
    removed from ``tool.inputs`` so the model never sees or fills them; injected
    values therefore come only from the authenticated session.

    Args:
        tool_obj: A smolagents-compatible tool object with ``inputs`` and ``forward``.
        user_context: Session-resolved caller identity mapping.

    Returns:
        The (possibly wrapped) tool object. Tools declaring no conventional
        fields, or runs without a user context, are returned unchanged.
    """
    if not user_context or getattr(tool_obj, "_nexent_user_context_wrapped", False):
        return tool_obj
    inputs = getattr(tool_obj, "inputs", None)
    if not isinstance(inputs, dict):
        return tool_obj
    declared = [field for field in USER_CONTEXT_FIELDS if field in inputs]
    if not declared:
        return tool_obj

    # Hide the conventional fields from the model-visible schema.
    tool_obj.inputs = {k: v for k, v in inputs.items() if k not in USER_CONTEXT_FIELDS}
    injected = {field: user_context.get(field) for field in declared}
    original_forward = tool_obj.forward

    if inspect.iscoroutinefunction(original_forward):
        @functools.wraps(original_forward)
        async def forward_with_user_context(*args, **kwargs):
            kwargs.update(injected)
            return await original_forward(*args, **kwargs)
    else:
        @functools.wraps(original_forward)
        def forward_with_user_context(*args, **kwargs):
            kwargs.update(injected)
            return original_forward(*args, **kwargs)

    tool_obj.forward = forward_with_user_context
    setattr(tool_obj, "_nexent_user_context_wrapped", True)
    return tool_obj
