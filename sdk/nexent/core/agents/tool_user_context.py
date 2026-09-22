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

import ast
import inspect
from collections.abc import Mapping
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


def sanitize_user_context_arguments_in_code(
    code: str,
    hidden_fields_by_tool: Mapping[str, tuple[str, ...]],
) -> str:
    """Remove platform-injected arguments from generated direct tool calls.

    The MCP wrapper remains the security boundary: it discards any caller-supplied
    identity values and injects the authenticated session values immediately
    before calling the remote tool.  This helper serves a separate purpose.  A
    code-generating model may still *invent* conventional argument names even
    after they are removed from the tool schema.  Removing those invented
    keyword arguments before the action is persisted, displayed, or executed
    keeps the model-facing trace aligned with the public tool contract.

    Only direct calls to tools in ``hidden_fields_by_tool`` are changed.  The
    same keyword on an unrelated function is intentionally left untouched.
    Invalid or incomplete code is returned unchanged so normal output-protocol
    error handling remains responsible for it.
    """
    if not code or not hidden_fields_by_tool:
        return code

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    class _InjectedArgumentRemover(ast.NodeTransformer):
        changed = False

        def visit_Call(self, node: ast.Call) -> ast.AST:
            self.generic_visit(node)
            if not isinstance(node.func, ast.Name):
                return node

            hidden_fields = hidden_fields_by_tool.get(node.func.id)
            if not hidden_fields:
                return node

            filtered_keywords = [
                keyword
                for keyword in node.keywords
                # ``**mapping`` has no statically-known field name.  The
                # execution wrapper sanitizes that path at runtime.
                if keyword.arg is None or keyword.arg not in hidden_fields
            ]
            if len(filtered_keywords) != len(node.keywords):
                node.keywords = filtered_keywords
                self.changed = True
            return node

    transformer = _InjectedArgumentRemover()
    tree = transformer.visit(tree)
    if not transformer.changed:
        return code
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


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
    # CoreAgent uses this marker to remove only these platform-injected fields
    # from a model-generated action before it is rendered or persisted.
    setattr(tool_obj, "_nexent_hidden_user_context_fields", tuple(declared))
    setattr(tool_obj, "_nexent_user_context_wrapped", True)
    return tool_obj
