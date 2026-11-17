# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Failure attribution remains safe, localized and independent of recovery."""

import asyncio
import json
from threading import Event

import httpx
import pytest

from nexent.core.agents.contracts.config import AgentConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.cores.jiuwen.errors import failure_error, public_error
from nexent.core.concurrency import RunCancellationScope
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.model_service.contracts import ModelError
from nexent.core.model_service.service import ModelServiceError
from nexent.core.utils.observer import MessageObserver


@pytest.fixture
def adapter():
    info = AgentRunInfo(
        query="current",
        observer=MessageObserver(lang="zh"),
        stop_event=Event(),
        model_config_list=[],
        agent_config=AgentConfig(
            name="agent",
            description="Fixture",
            model_name="model",
            tools=[
                ToolConfig(name="remote", class_name="Remote", source="mcp"),
                ToolConfig(name="local", class_name="Local", source="local"),
            ],
        ),
    )
    instance = JiuwenAdapter(info)
    instance.tool_configs = list(info.agent_config.tools)
    instance.scope = RunCancellationScope(info.stop_event)
    return instance


@pytest.mark.parametrize("lang", ["zh", "en"])
@pytest.mark.parametrize(
    "source,prefix",
    [("mcp", "mcp"), ("tool", "tool"), ("sandbox", "sandbox"), ("subagent", "subagent"), ("a2a", "a2a")],
)
def test_failure_origin_is_known_boundary_not_exception_guess(lang, source, prefix):
    error = failure_error(
        httpx.ConnectError("Bearer private-token https://key@host/?api_key=secret"),
        request_id="run",
        lang=lang,
        source=source,
        name="lookup",
    )
    assert error.category.startswith(prefix + "_")
    assert "lookup" in error.safe_message
    assert not any(secret in error.safe_message for secret in ("private-token", "api_key", "secret", "https://"))


def test_model_failure_keeps_normalized_identity_inside_wrapper():
    model = ModelError(
        category="MODEL_AUTHENTICATION_ERROR",
        scope="provider",
        retryable=False,
        safe_message="Model service authentication failed.",
        request_id="provider-request",
    )
    cause = ModelServiceError(model)
    outer = RuntimeError("native wrapper with private data")
    outer.__cause__ = cause
    restored = failure_error(outer, request_id="run", lang="zh", source="mcp")
    assert restored.category == model.category and restored.request_id == "provider-request"
    assert "认证" in public_error(restored, "zh").safe_message
    assert "authentication" in public_error(restored, "en").safe_message


@pytest.mark.parametrize("signal", [asyncio.CancelledError(), RunTerminated(), KeyboardInterrupt()])
def test_control_signals_are_never_execution_failures(signal):
    assert failure_error(signal, request_id="run", source="tool", lang="zh") is None


def test_resource_exception_is_specific_but_does_not_poison_recovery(adapter):
    with pytest.raises(ValueError):
        with adapter._observe_tool("local", {"secret": "hidden"}):
            raise ValueError("private exception payload")
    events = [json.loads(item) for item in adapter.run_info.observer.get_cached_message()]
    failed = next(item for item in events if item["type"] == "tool_result")
    assert failed["is_error"] and failed["error_code"] == "tool_execution_error"
    assert "local" in failed["result"] and "private exception" not in failed["result"]
    adapter.events.emit({"type": "answer", "payload": {"output": "Recovered"}})
    assert adapter.events.finish().status == "completed"


def test_swallowed_resource_failure_survives_native_generic_failure(adapter):
    with pytest.raises(TimeoutError):
        with adapter._observe_tool("remote", {}):
            raise TimeoutError("secret timeout")
    adapter.record_failure(RuntimeError("Jiuwen agent execution failed"))
    result = adapter.events.finish("failed")
    assert result.error.category == "mcp_timeout"
    assert "MCP" in result.error.safe_message and "超时" in result.error.safe_message
    assert "secret" not in result.error.safe_message


def test_later_model_failure_takes_precedence_over_recoverable_resource_failure(adapter):
    with pytest.raises(ValueError):
        with adapter._observe_tool("local", {}):
            raise ValueError("private")
    model = ModelError(
        category="MODEL_TIMEOUT",
        scope="transport",
        retryable=True,
        safe_message="The model request timed out.",
        request_id="model-request",
    )
    adapter.record_failure(ModelServiceError(model))
    adapter.record_failure(RuntimeError("cleanup wrapper"), phase="cleanup")
    result = adapter.events.finish("failed")
    assert result.error.category == "MODEL_TIMEOUT" and result.error.request_id == "model-request"


def test_mcp_result_carrier_keeps_exact_payload_and_failure_identity(adapter):
    payload = {"result": '{"success":false,"error":"business rejection"}'}
    with adapter._observe_tool("remote", {}):
        adapter._resource_result(payload)
    adapter.record_failure(RuntimeError("native failure"))
    result = adapter.events.finish("failed")
    assert result.error.category == "mcp_execution_error"
    saved = [json.loads(item) for item in adapter.run_info.observer.get_cached_message()]
    tool = next(item for item in saved if item["type"] == "tool_result")
    assert tool["is_error"] and json.loads(tool["result"]) == payload


def test_nested_code_error_preserves_the_actual_resource_origin(adapter):
    with pytest.raises(RuntimeError) as outer:
        with adapter._observe_tool("nexent_execute_python", {}):
            try:
                with adapter._observe_tool("remote", {}):
                    raise ConnectionRefusedError("private endpoint")
            except ConnectionRefusedError as error:
                raise RuntimeError("code executor wrapper") from error
    adapter.record_failure(outer.value)
    result = adapter.events.finish("failed")
    assert result.error.category == "mcp_connection_refused"
    assert "remote" in result.error.safe_message and "private" not in result.error.safe_message


@pytest.mark.parametrize(
    "category", ["MODEL_STREAM_INCOMPLETE", "JIUWEN_UNAUTHORIZED_TOOL", "JIUWEN_FINAL_OUTPUT_INVALID"]
)
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_internal_protocol_codes_have_readable_messages(category, lang):
    raw = ModelError(category=category, scope="protocol", retryable=False, safe_message=category, request_id="run")
    visible = public_error(raw, lang)
    assert visible.category == category and visible.safe_message != category
    assert raw.safe_message == category


@pytest.mark.parametrize("signal", [asyncio.CancelledError(), RunTerminated()])
def test_cancelled_resource_is_not_a_failed_tool_or_terminal(adapter, signal):
    with pytest.raises(type(signal)):
        with adapter._observe_tool("remote", {}):
            raise signal
    assert adapter.events.resource_error is None
    events = [json.loads(item) for item in adapter.run_info.observer.get_cached_message()]
    assert next(item for item in events if item["type"] == "tool_result")["is_error"] is False
    assert adapter.events.finish("stopped").error is None


@pytest.mark.asyncio
async def test_parallel_resource_errors_keep_their_own_call_ids_and_sources(adapter):
    async def fail(name):
        with adapter._observe_tool(name, {}):
            await asyncio.sleep(0)
            raise ValueError("private")

    results = await asyncio.gather(fail("local"), fail("remote"), return_exceptions=True)
    assert all(isinstance(item, ValueError) for item in results)
    events = [json.loads(item) for item in adapter.run_info.observer.get_cached_message()]
    calls = {item["local_call_id"]: item["tool_name"] for item in events if item["type"] == "tool"}
    failures = {calls[item["local_call_id"]]: item["error_code"] for item in events if item["type"] == "tool_result"}
    assert failures == {"local": "tool_execution_error", "remote": "mcp_execution_error"}


@pytest.mark.parametrize("kind", [FileNotFoundError, PermissionError, ModuleNotFoundError, TypeError])
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_specific_tool_conditions_are_actionable_without_exposing_paths(kind, lang):
    error = failure_error(
        kind("/private/secret.py api_key=private"), request_id="run", source="tool", name="lookup", lang=lang
    )
    assert error.category == "tool_execution_error"
    assert kind.__name__ in error.safe_message or kind is ModuleNotFoundError and "ImportError" in error.safe_message
    assert "private" not in error.safe_message and "secret" not in error.safe_message


def test_wait_for_timeout_cancellation_cause_is_a_deadline_not_user_cancellation():
    timeout = TimeoutError()
    timeout.__cause__ = asyncio.CancelledError()
    outer = RuntimeError("native wrapper")
    outer.__cause__ = timeout
    diagnostic = failure_error(outer, source="mcp", request_id="run", lang="en")
    assert diagnostic.category == "mcp_timeout" and "timed out" in diagnostic.safe_message
    outer.__cause__ = asyncio.CancelledError()
    assert failure_error(outer, source="mcp", request_id="run") is None
