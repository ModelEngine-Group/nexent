# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise the actual adapter, local interpreter and generated bridge proxy."""

import json
import logging
import threading
from io import BytesIO
from unittest.mock import MagicMock

import mcp.types
import pytest
from mcpadapt.smolagents_adapter import SmolAgentsAdapter
from smolagents.local_python_executor import evaluate_python_code

from nexent.core.agents.cores.smolagents.core_agent import _tool_failure_hint, _wrap_tool_for_observer
from nexent.core.agents.resources.tool_user_context import apply_user_context_to_mcp_tool
from nexent.core.agents.sandbox.execution import _ToolBridge


@pytest.fixture
def adapted_tool():
    calls = []

    def call(arguments):
        calls.append(arguments)
        return mcp.types.CallToolResult(content=[mcp.types.TextContent(type="text", text="found")])

    tool = SmolAgentsAdapter().adapt(call, mcp.types.Tool(
        name="cite", description="Cite an anchor", inputSchema={
            "type": "object", "properties": {
                "anchor_id": {"type": "string"}, "limit": {"type": "integer"},
                "user_id": {"type": "string"},
            }, "required": ["anchor_id"],
        },
    ))
    apply_user_context_to_mcp_tool(tool, {"user_id": "trusted"})
    _wrap_tool_for_observer(tool, MagicMock(), "agent")
    return tool, calls


@pytest.mark.parametrize("code,expected", [
    ('cite("a")', {"anchor_id": "a", "user_id": "trusted"}),
    ('cite("a", 2)', {"anchor_id": "a", "limit": 2, "user_id": "trusted"}),
    ('cite("a", limit=2)', {"anchor_id": "a", "limit": 2, "user_id": "trusted"}),
    ('cite({"anchor_id": "a", "user_id": "untrusted"})', {"anchor_id": "a", "user_id": "trusted"}),
])
def test_actual_adapter_local_execution_and_user_context(adapted_tool, code, expected):
    tool, calls = adapted_tool
    output, _ = evaluate_python_code(code, static_tools={"cite": tool})
    assert output == "found"
    assert calls == [expected]
    assert "user_id" not in tool.inputs


def test_actual_adapter_conflict_keeps_native_error(adapted_tool):
    tool, calls = adapted_tool
    with pytest.raises(ValueError, match="does not support multiple positional arguments"):
        tool.forward("a", anchor_id="b")
    assert calls == []


def test_actual_local_interpreter_retains_tool_failure_identity(adapted_tool):
    tool, calls = adapted_tool
    with pytest.raises(Exception) as caught:
        evaluate_python_code('cite("a", anchor_id="b")', static_tools={"cite": tool})
    hint = _tool_failure_hint(caught.value, {"cite": tool}, "en")
    assert "does not support multiple positional arguments" in hint
    assert "anchor_id (required)" in hint
    assert "Code execution failed at line" not in hint
    assert calls == []


@pytest.fixture
def bridge(adapted_tool):
    # Avoid starting a network service: retain the real context and dispatch code.
    tool, _ = adapted_tool
    bridge = object.__new__(_ToolBridge)
    bridge._tools = {"cite": tool}
    bridge._context_lock = threading.Lock()
    bridge._execution_contexts = {}
    bridge._closed = False
    bridge._token = "unit-test-token"
    bridge.port = 12345
    bridge._request_timeout_seconds = 1
    bridge._logger = logging.getLogger(__name__)
    return bridge


def test_generated_proxy_round_trip_dispatches_normalized_arguments(bridge, adapted_tool, monkeypatch):
    tool, calls = adapted_tool
    namespace = {}
    exec(bridge.proxy_code({"cite": tool}, bridge_host="localhost"), namespace)

    def request(req, **kwargs):
        result = bridge._invoke_tool(json.loads(req.data))
        return BytesIO(json.dumps({"result": result}).encode())

    monkeypatch.setattr(namespace["_nexent_urllib"], "urlopen", request)
    with bridge.execution_context() as execution_id:
        exec(bridge.execution_proxy_code(execution_id), namespace)
        assert namespace["cite"]("a", limit=2) == "found"
    assert calls == [{"anchor_id": "a", "limit": 2, "user_id": "trusted"}]
    assert not bridge._execution_contexts


@pytest.mark.parametrize("failure", ["transport", "http", "result"])
def test_generated_proxy_failure_identifies_tool_and_short_hint(bridge, adapted_tool, monkeypatch, failure):
    from urllib.error import HTTPError, URLError

    tool, _ = adapted_tool
    namespace = {}
    exec(bridge.proxy_code({"cite": tool}, bridge_host="localhost"), namespace)

    def request(req, **kwargs):
        if failure == "http":
            raise HTTPError(req.full_url, 500, "failed", {}, BytesIO(b'{"error":"bad anchor"}'))
        if failure == "result":
            return BytesIO(b'{"error":"bad anchor"}')
        raise URLError("offline")

    monkeypatch.setattr(namespace["_nexent_urllib"], "urlopen", request)
    with pytest.raises(RuntimeError) as caught:
        namespace["cite"]("a")
    assert "Local tool bridge request failed [cite]:" in str(caught.value)
    hint = _tool_failure_hint(caught.value, {"cite": tool}, "zh")
    assert "anchor_id" in hint and "user_id" not in hint
    assert "Traceback" not in hint
