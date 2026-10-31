# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Published creator identity does not share request state or draft authority."""

import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from contracts.agent import NL2AgentRunRequest, SystemAgentRef
from contracts.authentication import AuthenticatedIdentity
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from management.services.agent.creation import build_nl2agent_system_prompt
from management.services.conversation import creation_history
from nexent.core.agents.context import ContextItemInput, ContextItemType
from services import nl2agent_service as service
from tool_collection.mcp.nl2agent_mcp_tools import NL2AGENT_AGENT_ID_HEADER


@pytest.fixture
def runtime(mocker):
    snapshot = {
        "agent_id": 77,
        "version_no": 0,
        "agent_origin": "SYSTEM",
        "max_steps": 8,
        "prompt": "This stale database prompt must never be used",
    }
    mocker.patch.object(
        service.system_agent_provider,
        "get_nl2agent_main_ref",
        return_value=SystemAgentRef(
            ASSET_OWNER_TENANT_ID,
            "nl2agent_main",
            77,
            0,
        ),
    )
    mocker.patch.object(service, "search_agent_info_by_agent_id", return_value=snapshot)
    mocker.patch.object(service, "preflight_turn_controls")
    mocker.patch.object(
        service,
        "join_minio_file_description_to_query",
        new_callable=AsyncMock,
        return_value="query",
    )
    mocker.patch.object(
        service,
        "create_model_config_list",
        new_callable=AsyncMock,
        side_effect=lambda tenant: [],
    )
    mocker.patch.object(
        service.tenant_config_manager,
        "get_model_config",
        return_value={"model_name": "main"},
    )
    mocker.patch.object(
        service, "_resolve_input_budget", return_value=(8192, None, None)
    )
    mocker.patch.object(service, "_resolve_context_budget", return_value=None)
    mocker.patch.object(
        service,
        "get_tenant_local_mcp_server",
        side_effect=lambda tenant: f"http://{tenant}/mcp",
    )
    mocker.patch.object(
        service,
        "_build_verified_bound_resources_context",
        new_callable=AsyncMock,
        side_effect=lambda **kwargs: ContextItemInput(
            id="system:bound",
            type=ContextItemType.SYSTEM,
            content={"text": f"{kwargs['tenant_id']}:{kwargs['agent_id']}"},
            source=("database",),
        ),
    )
    return snapshot


@pytest.mark.asyncio
async def test_each_turn_keeps_shared_identity_but_fresh_resources_and_target(runtime):
    original = deepcopy(runtime)
    first = await service.build_nl2agent_run_info(
        NL2AgentRunRequest(query="build", agent_id=42),
        "tenant-a",
        "en",
        "Bearer a",
        identity=AuthenticatedIdentity("user-a", "tenant-a"),
    )
    second = await service.build_nl2agent_run_info(
        NL2AgentRunRequest(query="build", agent_id=43),
        "tenant-b",
        "zh",
        "Bearer b",
        identity=AuthenticatedIdentity("user-b", "tenant-b"),
    )
    assert first.agent_config.agent_id == second.agent_config.agent_id == 77
    assert first.agent_config.version_no == second.agent_config.version_no == 0
    assert first.agent_config is not second.agent_config
    assert first.agent_config.tools[0] is not second.agent_config.tools[0]
    assert first.observer is not second.observer
    assert first.stop_event is not second.stop_event
    assert first.model_config_list is not second.model_config_list
    assert first.mcp_host[0]["headers"][NL2AGENT_AGENT_ID_HEADER] == "42"
    assert second.mcp_host[0]["headers"][NL2AGENT_AGENT_ID_HEADER] == "43"
    assert first.mcp_host[0]["headers"]["Authorization"] == "Bearer a"
    assert second.mcp_host[0]["headers"]["Authorization"] == "Bearer b"
    assert first.agent_config.context_items[0].content[
        "text"
    ] == build_nl2agent_system_prompt("en")
    assert second.agent_config.context_items[0].content[
        "text"
    ] == build_nl2agent_system_prompt("zh")
    first.stop_event.set()
    assert not second.stop_event.is_set()
    assert runtime == original


@pytest.mark.asyncio
async def test_history_retains_runtime_version_without_rebinding_target_draft(
    runtime, mocker
):
    async def runner(*args, **kwargs):
        yield json.dumps({"type": "final_answer", "content": "answer"})

    mocker.patch.object(service, "agent_run", side_effect=runner)
    save = mocker.patch.object(creation_history, "save_message", return_value=123)
    unit = mocker.patch.object(creation_history, "save_message_unit")
    stream = await service.create_nl2agent_stream(
        NL2AgentRunRequest(query="build", agent_id=42),
        "tenant-a",
        "en",
        identity=AuthenticatedIdentity("user-a", "tenant-a"),
    )
    events = [
        event
        async for event in creation_history.persist_creation_stream(
            stream,
            conversation_id=12,
            assistant_index=1,
            user_id="user-a",
            tenant_id="tenant-a",
        )
    ]
    assert len(events) == 2
    assert json.loads(json.loads(events[0][6:])["content"]) == {
        "event": "system_agent_run",
        "agent_id": 77,
        "version_no": 0,
        "system_key": "nl2agent_main",
    }
    assert save.call_args.kwargs["tenant_id"] == "tenant-a"
    assert save.call_args.kwargs["user_id"] == "user-a"
    assert save.call_args.args[0].conversation_id == 12
    assert unit.call_args_list[0].kwargs["unit_type"] == "other"
    assert json.loads(unit.call_args_list[0].kwargs["unit_content"])["version_no"] == 0
