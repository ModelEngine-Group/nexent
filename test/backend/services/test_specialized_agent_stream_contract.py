# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise the active factories instead of an unused adapter registry."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from consts.model import NL2AgentRunRequest, NL2SkillRunRequest
from services import nl2agent_service, nl2skill_service


@pytest.mark.parametrize("kind", ["nl2agent", "nl2skill"])
@pytest.mark.asyncio
async def test_active_factory_awaits_builder_and_returns_async_iterator(mocker, kind):
    module = nl2agent_service if kind == "nl2agent" else nl2skill_service
    request = (
        NL2AgentRunRequest(query="Create an Agent", agent_id=9)
        if kind == "nl2agent" else NL2SkillRunRequest(query="Create a skill")
    )
    stop_event = MagicMock()
    run_info = SimpleNamespace(stop_event=stop_event)
    builder = mocker.patch.object(module, f"build_{kind}_run_info", return_value=run_info)

    async def execute(info, **kwargs):
        assert info is run_info
        assert kwargs["thread_manager"] is module.runtime_thread_manager
        yield json.dumps({"type": "tool", "content": "ready"})

    mocker.patch.object(module, "agent_run", execute)
    arguments = dict(request=request, tenant_id="tenant-a", language="en")
    if kind == "nl2agent":
        arguments["authorization"] = "Bearer token"

    stream = await getattr(module, f"create_{kind}_stream")(**arguments)
    assert hasattr(stream, "__aiter__")
    if kind == "nl2agent":
        builder.assert_awaited_once_with(**arguments)
    else:
        builder.assert_awaited_once_with(request, "tenant-a", "en")
    chunks = [json.loads(item.removeprefix("data: ").strip()) async for item in stream]

    assert chunks[0]["type"] == "tool"
    assert chunks[0]["content"] == "ready"
    stop_event.set.assert_called_once_with()


@pytest.mark.parametrize("kind", ["nl2agent", "nl2skill"])
@pytest.mark.asyncio
async def test_active_factory_propagates_preparation_failure(mocker, kind):
    module = nl2agent_service if kind == "nl2agent" else nl2skill_service
    request = (
        NL2AgentRunRequest(query="Create", agent_id=9)
        if kind == "nl2agent" else NL2SkillRunRequest(query="Create")
    )
    builder = mocker.patch.object(
        module, f"build_{kind}_run_info", side_effect=ValueError("unauthorized input"),
    )
    execute = mocker.patch.object(module, "agent_run")
    arguments = dict(request=request, tenant_id="tenant-a", language="en")
    if kind == "nl2agent":
        arguments["authorization"] = None

    with pytest.raises(ValueError, match="unauthorized input"):
        await getattr(module, f"create_{kind}_stream")(**arguments)

    builder.assert_awaited_once()
    execute.assert_not_called()
