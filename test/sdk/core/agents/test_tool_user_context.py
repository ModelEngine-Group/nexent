"""
Unit tests for sdk.nexent.core.agents.tool_user_context module.

Covers the user-info pass-through contract for tool-side authorization:
- Conventional fields declared by a tool's input schema are injected from the
  authenticated session right before execution.
- Those fields are hidden from the model-visible schema (removed from inputs),
  so the model neither sees nor fills them.
- Tools declaring no conventional fields stay untouched.

Uses direct module loading to bypass the sdk.nexent package __init__.py
which has heavy dependencies not needed for this module.
"""
import importlib.util
import inspect
import os

import pytest


def _load_tool_user_context_module():
    module_path = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "sdk", "nexent", "core", "agents", "tool_user_context.py",
    ))
    spec = importlib.util.spec_from_file_location("tool_user_context", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool_user_context = _load_tool_user_context_module()
USER_CONTEXT_FIELDS = tool_user_context.USER_CONTEXT_FIELDS
apply_user_context_to_mcp_tool = tool_user_context.apply_user_context_to_mcp_tool
sanitize_user_context_arguments_in_code = (
    tool_user_context.sanitize_user_context_arguments_in_code
)


class _FakeTool:
    """Minimal smolagents-like tool: an inputs dict plus a forward method."""

    def __init__(self, inputs, forward):
        self.name = "fake_tool"
        self.inputs = dict(inputs)
        self.forward = forward


SAMPLE_CONTEXT = {
    "tenant_id": "t-1",
    "tenant_name": "bug-repro",
    "user_id": "u-1",
    "user_name": "bug-admin@qq.com",
    "user_account": "bug-admin@qq.com",
    "user_groups": ["Default Group"],
}


def test_conventional_field_set():
    assert USER_CONTEXT_FIELDS == (
        "tenant_id", "tenant_name", "user_id",
        "user_name", "user_account", "user_groups",
    )


def test_declared_fields_injected_and_hidden_from_model():
    received = {}

    def forward(query, user_account=None, user_groups=None):
        received["query"] = query
        received["user_account"] = user_account
        received["user_groups"] = user_groups
        return "ok"

    tool = _FakeTool(
        {
            "query": {"type": "string"},
            "user_account": {"type": "string"},
            "user_groups": {"type": "array"},
        },
        forward,
    )
    wrapped = apply_user_context_to_mcp_tool(tool, SAMPLE_CONTEXT)

    # Model-visible schema no longer contains the conventional fields.
    assert set(wrapped.inputs) == {"query"}
    # Code agents can inspect ``forward`` directly, so its public signature
    # must not leak the hidden identity parameter names either.
    assert tuple(inspect.signature(wrapped.forward).parameters) == ("query",)
    assert not hasattr(wrapped.forward, "__wrapped__")
    assert wrapped._nexent_hidden_user_context_fields == (
        "user_account", "user_groups",
    )
    # Model only supplies business args; identity values come from the session.
    assert wrapped.forward(
        query="hello",
        user_account="forged@example.com",
        user_groups=["Forged Group"],
    ) == "ok"
    assert received["query"] == "hello"
    assert received["user_account"] == "bug-admin@qq.com"
    assert received["user_groups"] == ["Default Group"]


def test_positional_arguments_mapping_cannot_forge_identity():
    captured = {}

    def forward(arguments):
        captured.update(arguments)
        return "ok"

    tool = _FakeTool(
        {"query": {"type": "string"}, "user_id": {"type": "string"}},
        forward,
    )
    wrapped = apply_user_context_to_mcp_tool(tool, SAMPLE_CONTEXT)

    assert wrapped.forward({"query": "hello", "user_id": "forged-user"}) == "ok"
    assert captured == {"query": "hello", "user_id": "u-1"}


@pytest.mark.asyncio
async def test_async_forward_injection():
    captured = {}

    async def forward(**kwargs):
        captured.update(kwargs)
        return "ok"

    tool = _FakeTool(
        {"query": {"type": "string"}, "tenant_name": {"type": "string"}},
        forward,
    )
    wrapped = apply_user_context_to_mcp_tool(tool, SAMPLE_CONTEXT)
    result = await wrapped.forward(query="hi")
    assert result == "ok"
    assert captured == {"query": "hi", "tenant_name": "bug-repro"}


def test_only_declared_fields_are_injected():
    captured = {}

    def forward(**kwargs):
        captured.update(kwargs)
        return "ok"

    tool = _FakeTool(
        {"query": {"type": "string"}, "user_account": {"type": "string"}},
        forward,
    )
    wrapped = apply_user_context_to_mcp_tool(tool, SAMPLE_CONTEXT)
    wrapped.forward(query="hi")
    # user_groups is not declared by the tool, so it must not be injected.
    assert captured == {"query": "hi", "user_account": "bug-admin@qq.com"}


def test_tool_without_conventional_fields_untouched():
    def forward(query):
        return query

    tool = _FakeTool({"query": {"type": "string"}}, forward)
    result = apply_user_context_to_mcp_tool(tool, SAMPLE_CONTEXT)
    assert result is tool
    assert result.inputs == {"query": {"type": "string"}}
    assert result.forward is forward
    assert not getattr(tool, "_nexent_user_context_wrapped", False)


@pytest.mark.parametrize("empty_context", [None, {}])
def test_missing_user_context_still_hides_and_strips_identity(empty_context):
    captured = {}

    def forward(**kwargs):
        captured.update(kwargs)
        return "ok"

    tool = _FakeTool({
        "query": {"type": "string"},
        "user_account": {"type": "string"},
    }, forward)

    wrapped = apply_user_context_to_mcp_tool(tool, empty_context)
    wrapped.forward(query="hello", user_account="forged@example.com")

    assert set(wrapped.inputs) == {"query"}
    assert captured == {"query": "hello"}


def test_wrapping_is_idempotent():
    captured = {}

    def forward(**kwargs):
        captured.update(kwargs)
        return "ok"

    tool = _FakeTool(
        {"query": {"type": "string"}, "user_id": {"type": "string"}},
        forward,
    )
    first = apply_user_context_to_mcp_tool(tool, SAMPLE_CONTEXT)
    second = apply_user_context_to_mcp_tool(first, SAMPLE_CONTEXT)
    assert second is first
    second.forward(query="hi")
    # Injection happens exactly once even when wrapping is attempted twice.
    assert captured == {"query": "hi", "user_id": "u-1"}


def test_non_dict_inputs_untouched():
    """Tools without a dict-shaped inputs schema are returned unchanged."""

    def forward(**kwargs):
        return "ok"

    tool = _FakeTool({"query": {"type": "string"}}, forward)
    tool.inputs = "not-a-dict"
    result = apply_user_context_to_mcp_tool(tool, SAMPLE_CONTEXT)
    assert result is tool
    assert not getattr(tool, "_nexent_user_context_wrapped", False)


def test_generated_action_hides_only_injected_fields_for_that_tool():
    code = '''
result = inspect_caller_identity(
    request_note="verify",
    tenant_id="invented",
    user_groups=[],
)
other_tool(tenant_id="keep-this")
'''

    sanitized = sanitize_user_context_arguments_in_code(
        code,
        {"inspect_caller_identity": ("tenant_id", "user_groups")},
    )

    assert "request_note='verify'" in sanitized
    assert "tenant_id" not in sanitized.split("other_tool", maxsplit=1)[0]
    assert "user_groups" not in sanitized
    assert "other_tool(tenant_id='keep-this')" in sanitized


def test_generated_action_with_invalid_python_is_left_for_protocol_handling():
    code = "inspect_caller_identity(tenant_id=)"

    assert sanitize_user_context_arguments_in_code(
        code,
        {"inspect_caller_identity": ("tenant_id",)},
    ) == code
