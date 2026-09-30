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

import inspect
from collections.abc import Mapping, Sequence
from typing import Any


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


def _set_model_visible_signature(
    wrapper: Any,
    original_forward: Any,
    hidden_fields: list[str],
) -> None:
    """Expose a forward signature that matches the model-visible tool schema.

    ``tool.inputs`` is not the only metadata a code agent can inspect.  In
    particular, ``functools.wraps`` preserves ``__wrapped__`` and lets
    ``inspect.signature`` recover the original MCP function signature.  That
    would reveal hidden identity parameter names in generated reasoning code.
    """
    try:
        signature = inspect.signature(original_forward)
        visible_parameters = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.name not in hidden_fields
        ]
        wrapper.__signature__ = signature.replace(parameters=visible_parameters)
    except (TypeError, ValueError):
        # Some third-party callable objects do not expose an inspectable
        # signature.  Their already-sanitized ``tool.inputs`` remains the
        # model-visible contract in that case.
        return


def apply_user_context_to_mcp_tool(
    tool_obj: Any,
    user_context: Mapping[str, Any] | None,
) -> Any:
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
        fields are returned unchanged.
    """
    if getattr(tool_obj, "_nexent_user_context_wrapped", False):
        return tool_obj
    inputs = getattr(tool_obj, "inputs", None)
    if not isinstance(inputs, dict):
        return tool_obj
    declared = [field for field in USER_CONTEXT_FIELDS if field in inputs]
    if not declared:
        return tool_obj

    # Hide the conventional fields from the model-visible schema.
    tool_obj.inputs = {k: v for k, v in inputs.items() if k not in USER_CONTEXT_FIELDS}
    trusted_context = user_context or {}
    injected = {
        field: trusted_context[field]
        for field in declared
        if field in trusted_context
    }
    original_forward = tool_obj.forward

    def trusted_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        """Drop model-supplied identity fields before adding trusted values."""
        sanitized = dict(kwargs)
        for field in declared:
            sanitized.pop(field, None)
        sanitized.update(injected)
        return sanitized

    if inspect.iscoroutinefunction(original_forward):
        async def forward_with_user_context(*args, **kwargs):
            # MCPAdapt also accepts one positional mapping as the complete
            # arguments object. Sanitize that path as well as keyword calls.
            if len(args) == 1 and isinstance(args[0], Mapping) and not kwargs:
                return await original_forward(trusted_kwargs(args[0]))
            return await original_forward(*args, **trusted_kwargs(kwargs))
    else:
        def forward_with_user_context(*args, **kwargs):
            if len(args) == 1 and isinstance(args[0], Mapping) and not kwargs:
                return original_forward(trusted_kwargs(args[0]))
            return original_forward(*args, **trusted_kwargs(kwargs))

    _set_model_visible_signature(forward_with_user_context, original_forward, declared)
    tool_obj.forward = forward_with_user_context
    setattr(tool_obj, "_nexent_user_context_wrapped", True)
    return tool_obj


def apply_model_visible_tool_schemas_to_context_items(
    context_items: Sequence[Any] | None,
    tools: Sequence[Any],
) -> list[Any]:
    """Keep rendered tool context aligned with each wrapped tool's public schema.

    The backend context snapshot may have been built from the original MCP
    record before the runtime wrapper removes platform-owned identity fields.
    Replace only those affected tool items with the already-sanitized runtime
    schema, leaving the execution schema and every unrelated context item
    untouched.
    """
    visible_inputs = {
        str(getattr(tool, "name")): getattr(tool, "inputs")
        for tool in tools
        if getattr(tool, "_nexent_user_context_wrapped", False)
        and isinstance(getattr(tool, "inputs", None), Mapping)
    }
    if not context_items or not visible_inputs:
        return list(context_items or ())

    sanitized_items: list[Any] = []
    for item in context_items:
        item_type = getattr(
            getattr(item, "type", None),
            "value",
            getattr(item, "type", None),
        )
        content = getattr(item, "content", None)
        tool_name = content.get("name") if isinstance(content, Mapping) else None
        if item_type != "tool" or tool_name not in visible_inputs:
            sanitized_items.append(item)
            continue

        model_copy = getattr(item, "model_copy", None)
        if not callable(model_copy):
            # Production ContextItemInput values are immutable Pydantic models.
            # Do not mutate a foreign object if an integration supplies one.
            sanitized_items.append(item)
            continue
        sanitized_items.append(model_copy(update={
            "content": {**content, "inputs": dict(visible_inputs[tool_name])},
        }))
    return sanitized_items
