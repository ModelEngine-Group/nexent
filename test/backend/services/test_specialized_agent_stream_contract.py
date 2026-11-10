# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise the active factories instead of an unused adapter registry."""

from contracts.authentication import AuthenticatedIdentity
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from contracts.agent import NL2AgentRunRequest
from services import nl2agent_service


@pytest.mark.asyncio
async def test_active_factory_awaits_builder_and_returns_async_iterator(mocker):
    module = nl2agent_service
    request = NL2AgentRunRequest(query="Create an Agent", agent_id=9)
    stop_event = MagicMock()
    run_info = SimpleNamespace(stop_event=stop_event)
    builder = mocker.patch.object(module, "build_nl2agent_run_info", return_value=run_info)

    async def execute(info, **kwargs):
        assert info is run_info
        assert kwargs["thread_manager"] is module.runtime_thread_manager
        yield json.dumps({"type": "tool", "content": "ready"})

    mocker.patch.object(module, "agent_run", execute)
    arguments = dict(request=request, tenant_id="tenant-a", language="en")
    arguments["authorization"] = "Bearer token"
    arguments["identity"] = AuthenticatedIdentity("user-a", "tenant-a")

    stream = await getattr(module, "create_nl2agent_stream")(**arguments)
    assert hasattr(stream, "__aiter__")
    builder.assert_awaited_once_with(**arguments)
    chunks = [json.loads(item.removeprefix("data: ").strip()) async for item in stream]

    assert chunks[0]["type"] == "tool"
    assert chunks[0]["content"] == "ready"
    stop_event.set.assert_called_once_with()


@pytest.mark.asyncio
async def test_active_factory_propagates_preparation_failure(mocker):
    module = nl2agent_service
    request = NL2AgentRunRequest(query="Create", agent_id=9)
    builder = mocker.patch.object(
        module, "build_nl2agent_run_info", side_effect=ValueError("unauthorized input"),
    )
    execute = mocker.patch.object(module, "agent_run")
    arguments = dict(request=request, tenant_id="tenant-a", language="en")
    arguments["authorization"] = None
    arguments["identity"] = AuthenticatedIdentity("user-a", "tenant-a")

    with pytest.raises(ValueError, match="unauthorized input"):
        await getattr(module, "create_nl2agent_stream")(**arguments)

    builder.assert_awaited_once()
    execute.assert_not_called()
