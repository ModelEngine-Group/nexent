# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tool calling stays in Runtime with bounded request ownership and typed transport."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from contracts.agentos import AgentToolInvocation, AgentToolResult, ToolBinding
from contracts.constants import environment
from fastapi import FastAPI
from runtime.agentos import tools
from runtime.agentos.middleware import AgentOSMiddleware

from infrastructure.agentos_client import AgentOSClient


def payload(tool_id="analyze_text_file"):
    return AgentToolInvocation(
        run_id="a" * 32,
        tool=ToolBinding(tool_id=tool_id, version="1"),
        inputs={
            "file_url_list": ["https://sensitive.invalid/private"],
            "query": "private query",
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "unsupported", "timeout"])
async def test_tool_router_scope_deadline_and_allowed_binding(mocker, caplog, mode):
    mocker.patch.object(environment, "JWT_SECRET", "synthetic-tool-test")
    manager = MagicMock()
    seen = []

    async def run(lane, spec, action, request, actor, scope):
        seen.append(scope)
        assert (
            lane == "model-tool-io"
            and spec.run_id == "a" * 32
            and callable(spec.close_hook)
        )
        if mode == "timeout":
            await asyncio.Future()
        return AgentToolResult(result=["analysis"])

    manager.run = AsyncMock(side_effect=run)
    mocker.patch.object(tools, "TOOL_INVOCATION_SECONDS", 0.02)
    app = FastAPI(root_path="/api")
    app.add_middleware(AgentOSMiddleware)
    app.include_router(tools.create_tool_router(manager))
    api = AgentOSClient(
        "http://runtime",
        lambda **kwargs: httpx.AsyncClient(
            transport=httpx.ASGITransport(app), **kwargs
        ),
    )
    if mode == "success":
        assert (await api.invoke_tool(payload(), "user-a", "tenant-a")).result == [
            "analysis"
        ]
    else:
        from contracts.errors.exceptions import RuntimeUpstreamError

        with pytest.raises(RuntimeUpstreamError) as error:
            await api.invoke_tool(
                payload(
                    "analyze_image" if mode == "unsupported" else "analyze_text_file"
                ),
                "user-a",
                "tenant-a",
            )
        assert error.value.status_code == (422 if mode == "unsupported" else 504)
    if mode == "unsupported":
        manager.run.assert_not_called()
    else:
        assert seen[0].cancelled
    assert "private query" not in caplog.text and "sensitive.invalid" not in caplog.text


@pytest.mark.asyncio
async def test_management_compiles_trial_and_uses_agentos_only(mocker):
    from contracts.tool import ToolValidateRequest
    from management.services.tool import text_validation

    binding = ToolBinding(tool_id="analyze_text_file", version="1")
    mocker.patch.object(text_validation, "_binding", return_value=binding)
    client = SimpleNamespace(
        invoke_tool=AsyncMock(return_value=AgentToolResult(result=["analysis"]))
    )
    mocker.patch.object(text_validation, "AgentOSClient", return_value=client)

    async def blocking(name, action, *args, **kwargs):
        return action(*args)

    mocker.patch.object(text_validation, "run_blocking", side_effect=blocking)
    request = ToolValidateRequest(
        name="analyze_text_file", source="local", inputs={"query": "hello"}
    )
    assert await text_validation.validate_text_tool(request, "tenant-a", "user-a") == [
        "analysis"
    ]
    actual, user_id, tenant_id = client.invoke_tool.call_args.args
    assert actual.tool == binding and actual.inputs == request.inputs
    assert len(actual.run_id) == 32 and (user_id, tenant_id) == ("user-a", "tenant-a")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tenant", "user"), [(None, "user"), ("tenant", None), (None, None)]
)
async def test_trial_rejects_missing_identity_before_compilation(mocker, tenant, user):
    from contracts.errors.exceptions import ToolExecutionException
    from management.services.tool import text_validation

    compiler = mocker.patch.object(text_validation, "_binding")
    with pytest.raises(ToolExecutionException):
        await text_validation.validate_text_tool(SimpleNamespace(), tenant, user)
    compiler.assert_not_called()


def test_runtime_owns_tool_monitoring_and_cancellation_scope(mocker):
    from nexent.core.concurrency import RunCancellationScope

    from infrastructure.agentos_identity import ServicePrincipal

    actor, scope = ServicePrincipal("user-a", "tenant-a"), RunCancellationScope()
    config = SimpleNamespace(
        metadata={"llm_model": SimpleNamespace(display_name="long-model")}
    )
    materialize = mocker.patch.object(
        tools, "materialize_analysis_tools", return_value={"analyze_text_file": config}
    )
    tool = SimpleNamespace(forward=MagicMock(return_value=["analysis"]))
    mocker.patch.object(tools.NexentAgent, "create_local_tool", return_value=tool)
    monitor = mocker.patch.object(tools, "set_monitoring_context")
    operation = mocker.patch.object(tools, "set_monitoring_operation")
    request = payload()
    assert tools.execute_tool(request, actor, scope).result == ["analysis"]
    materialize.assert_called_once_with(
        [request.tool], actor, run_id=request.run_id, cancellation_scope=scope
    )
    monitor.assert_called_once_with(tenant_id="tenant-a")
    operation.assert_called_once_with("tool_validation", display_name="long-model")


def test_internal_capabilities_are_not_exposed_as_tool_configuration(mocker):
    from management.services.tool import catalog
    from nexent.core.tools.analyze_text_file_tool import AnalyzeTextFileTool

    mocker.patch.object(
        catalog, "get_local_tools_classes", return_value=[AnalyzeTextFileTool]
    )
    params = catalog.get_local_tools_description_zh()["analyze_text_file"]["params"]
    assert [parameter["name"] for parameter in params] == ["selected_model_id"]


@pytest.mark.asyncio
async def test_tool_client_total_deadline_closes_transport_once(mocker, caplog):
    from contracts.errors.exceptions import RuntimeServiceTimeoutError

    from infrastructure import agentos_client

    mocker.patch.object(environment, "JWT_SECRET", "synthetic-tool-deadline")
    mocker.patch.object(agentos_client, "_TOOL_DEADLINE_SECONDS", 0.02)

    class Transport(httpx.AsyncBaseTransport):
        calls = closes = 0
        exited = False

        async def handle_async_request(self, request):
            self.calls += 1
            try:
                await asyncio.Future()
            finally:
                self.exited = True

        async def aclose(self):
            self.closes += 1

    transport = Transport()
    client = AgentOSClient(
        "http://runtime",
        lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs),
    )
    with pytest.raises(RuntimeServiceTimeoutError):
        await client.invoke_tool(payload(), "user-a", "tenant-a")
    assert transport.exited
    assert transport.calls == transport.closes == 1
    assert "agentos_tool_timeout" in caplog.text and "private query" not in caplog.text
