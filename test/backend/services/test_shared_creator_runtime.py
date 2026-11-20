# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep the released creator, per-request tools, and edited draft separate."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from contracts.agent import NL2AgentRunRequest, SystemAgentRef
from contracts.agentos import AgentVersionReference
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.agent_model_config import create_model_config_from_record
from management.api.agent import creator
from management.services.agent import creator_run
from management.services.conversation import creator_execution
from nexent.core.agents.context import ContextItemInput, ContextItemType
from runtime.agentos import creator_definition, prepared_agent_creator
from runtime.agentos.agent_creator_config import build_nl2agent_system_prompt
from test.common.creator_runtime_boundary import isolate_creator_runtime
from ..app.test_agentos_prepared_evaluation import model_record


@pytest.fixture
def preparation(mocker):
    mocker.patch.object(creator_run, "prepare_creator_model", return_value={
        "model": {"model_id": 11, "alias": "main_model", "revision": "revision-1"},
        "input_budget": 4096, "context_window_tokens": 8192,
    })
    return mocker.patch.object(
        creator_run, "_build_verified_bound_resources_context",
        side_effect=lambda **kwargs: ContextItemInput(
            id="system:bound", type=ContextItemType.SYSTEM,
            content={"text": f"{kwargs['tenant_id']}:{kwargs['agent_id']}"}, source=("database",),
        ),
    )


@pytest.mark.asyncio
async def test_each_turn_keeps_shared_identity_but_fresh_resources_and_target(preparation, mocker):
    snapshot = {
        "agent_id": 77, "version_no": 3, "agent_origin": "SYSTEM", "max_steps": 8, "prompt": "Stale database prompt",
    }
    original = deepcopy(snapshot)
    read_creator = mocker.patch.object(creator_definition, "read_system_creator", return_value=snapshot)
    mocker.patch.object(
        prepared_agent_creator, "_materialize_model",
        side_effect=lambda binding, actor, resource: create_model_config_from_record(model_record(tenant_id=actor.tenant_id)),
    )
    callback = mocker.patch.object(prepared_agent_creator, "_invoke_tool", return_value={"status": "ok"})
    runs = []
    for actor, target, language in [(ServicePrincipal("user-a", "tenant-a"), 42, "en"),
                                    (ServicePrincipal("user-b", "tenant-b"), 43, "zh")]:
        payload = await creator_run.prepare_nl2agent_snapshot(NL2AgentRunRequest(query="build", agent_id=target), actor, language)
        payload = payload.model_copy(update={"system_agent": AgentVersionReference(agent_id=77, version_no=3)})
        info = prepared_agent_creator.prepare_agent_creator_run(payload, actor)
        assert (info.agent_config.agent_id, info.agent_config.version_no) == (77, 3)
        assert info.agent_config.context_items[0].content["text"] == build_nl2agent_system_prompt(language)
        assert info.agent_config.context_items[1].content["text"] == f"{actor.tenant_id}:{target}"
        tool = next(tool.metadata for tool in info.agent_config.tools if tool.name == "nl2a_search_installed_resources")
        assert tool.invoke({"agent_id": target + 10, "requirements": []})["code"] == "agent_context_mismatch"
        before = callback.call_count
        assert tool.invoke({"agent_id": target, "requirements": []}) == {"status": "ok"}
        assert callback.call_count == before + 1
        assert callback.call_args.args == (payload.run_id, actor, "search_installed_resources", target)
        runs.append(info)

    first, second = runs
    assert first.agent_config is not second.agent_config
    assert first.agent_config.tools[0] is not second.agent_config.tools[0]
    assert first.observer is not second.observer
    assert first.model_config_list is not second.model_config_list
    first.stop_event.set()
    assert not second.stop_event.is_set()
    assert read_creator.call_args_list == [mocker.call(77, 3, "nl2agent_main")] * 2
    assert preparation.await_count == 2
    assert snapshot == original


@pytest.mark.asyncio
async def test_history_uses_shared_creator_and_dispatch_preserves_version_and_target(preparation, mocker, monkeypatch):
    actor = ServicePrincipal("user-a", "tenant-a")
    ref = SystemAgentRef(ASSET_OWNER_TENANT_ID, "nl2agent_main", 77, 3)
    mocker.patch.object(creator, "get_current_user_info", return_value=(actor.user_id, actor.tenant_id, "en"))
    mocker.patch.object(creator_execution.system_agent_provider, "get_creator_ref", return_value=ref)
    authorize = mocker.patch.object(creator_execution, "authorize_target", side_effect=lambda target, *_: target)
    history = mocker.patch.object(creator_execution, "prepare_creation_history", return_value=(12, 1))
    runtime = isolate_creator_runtime(monkeypatch, creator_execution)

    async def runtime_events():
        yield 'data: {"type":"final_answer","content":"answer"}\n\n'

    dispatch = mocker.patch.object(creator, "create_nl2agent_stream", return_value=runtime_events())
    response = await creator.nl2agent_run_api(
        NL2AgentRunRequest(query="build", agent_id=42, persist_history=True), Mock(), authorization="token",
    )
    frames = [frame async for frame in response.body_iterator]

    assert any("answer" in frame for frame in frames)
    assert response.headers["conversation_id"] == "12"
    target = {"type": "agent", "id": 42}
    authorize.assert_called_once_with(target, actor.user_id, actor.tenant_id)
    kwargs = history.call_args.kwargs
    assert (kwargs["agent_id"], kwargs["target"], kwargs["user_id"], kwargs["tenant_id"]) == (77, target, "user-a", "tenant-a")
    payload, owner = dispatch.call_args.args
    assert owner == actor
    assert payload.agent_id == 42
    assert payload.system_agent == AgentVersionReference(agent_id=77, version_no=3)
    assert payload.bound_resources == "tenant-a:42"
    assert runtime.checkpoint.call_args.kwargs["conversation_id"] == 12
