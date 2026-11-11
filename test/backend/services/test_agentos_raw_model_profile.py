# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Export raw generation settings without changing shared child model behavior."""

from unittest.mock import AsyncMock

import pytest

from contracts.agent import AgentRequest
from contracts.agentos import AgentRunReference, PreparedAgentRun, PreparedEphemeralRun
from infrastructure import agent_model_config
from infrastructure.agent_model_config import create_model_config_from_record
from infrastructure.agent_model_overrides import overlay_root_model
from management.services.agent import raw_execution as service, tool_identity
from management.services.agent.preparation import run, evaluation_snapshot
from nexent.core.agents.agent_model import AgentConfig
from runtime.agentos import prepared_evaluation
from .test_agentos_raw_preparation import ACTOR, preparation


@pytest.mark.asyncio
@pytest.mark.parametrize("debug", [True, False], ids=["debug", "new-conversation"])
@pytest.mark.parametrize("settings", [None, {}, {"temperature": 0.3, "top_p": 0.7}, {"temperature": None}],
                         ids=["omitted", "empty", "sampling", "explicit-null"])
async def test_raw_profile_round_trip_matches_legacy_root_and_shared_child(preparation, mocker, settings, debug):
    record = {
        "model_id": 11, "tenant_id": ACTOR.tenant_id, "delete_flag": "N", "model_type": "llm",
        "model_name": "provider-model", "model_repo": None, "display_name": "model-a",
        "api_key": "private-runtime-key", "base_url": "https://provider.invalid/v1", "update_time": "revision-1",
        "extra_params": {"enable_thinking": True, "reasoning_effort": "low"},
    }
    mocker.patch.object(agent_model_config, "_resolve_reasoning_capability", return_value={
        "status": "supported", "control": "effort", "levels": ["low", "high"],
    })
    base = create_model_config_from_record(record)
    child = AgentConfig(agent_id=8, version_no=1, name="child", description="", model_name=base.cite_name, tools=[])

    async def models(tenant, *, versions):
        assert tenant == ACTOR.tenant_id
        versions[base.cite_name] = (11, "revision-1")
        return [base.model_copy(deep=True)]

    def catalog(filters, tenant):
        assert tenant == ACTOR.tenant_id
        return [record] if filters["display_name"] == base.cite_name else []

    mocker.patch.object(service, "create_agent_run_info", new=run.create_agent_run_info)
    mocker.patch.object(run, "_ensure_agent_reasoning_snapshot")
    mocker.patch.object(run, "create_model_config_list", new=AsyncMock(side_effect=models))
    mocker.patch.object(run, "search_agent_info_by_agent_id", return_value={"model_params_override": {}})
    mocker.patch.object(run, "create_agent_config", new=AsyncMock(return_value=AgentConfig(
        agent_id=7, version_no=0, name="root", description="", model_name=base.cite_name, tools=[], worker_agents=[child],
    )))
    mocker.patch.object(evaluation_snapshot, "get_model_records", side_effect=catalog)
    mocker.patch.object(tool_identity, "resolve_tool_user_context", return_value={})
    lookup = mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=record)
    scoped = bool(settings)
    request = AgentRequest(query="hello", agent_id=7, is_debug=debug, generation_config=settings, reasoning_effort="high")
    if debug:
        prepared = await service.prepare_raw_debug(request, ACTOR)
        assert prepared is not None
        payload = PreparedEphemeralRun.model_validate_json(prepared.payload.model_dump_json())
    else:
        mocker.patch.object(run, "query_current_version_no", return_value=0)
        mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=False)
        mocker.patch("management.services.model.run_controls.validate_agent_model_selection")
        mocker.patch("management.services.model.run_controls.preflight_agent_turn_controls")
        reference = AgentRunReference(conversation_id=42, run_id="a" * 32)
        prepared = await evaluation_snapshot.prepare_conversation_snapshot(
            request.model_copy(update={"conversation_id": 42}), reference, ACTOR.user_id, ACTOR.tenant_id,
            new_conversation=True, preserve_shared_reasoning=True,
        )
        assert prepared is not None
        payload = PreparedAgentRun.model_validate_json(prepared.model_dump_json())
    assert record["api_key"] not in payload.model_dump_json()
    expected = overlay_root_model(base, settings or {}, base.cite_name)
    expected = overlay_root_model(expected, {"thinking_effort": "high"}, expected.cite_name)
    restored = prepared_evaluation._materialize_model(payload.models.llm, ACTOR, payload.resource)
    assert restored.model_copy(update={"cite_name": expected.cite_name}) == expected
    bindings = {binding.alias: binding for binding in [payload.models.llm, *payload.models.additional_llms]}
    child_binding = bindings[payload.resource.subagents[0].model_alias]
    restored_child = prepared_evaluation._materialize_model(child_binding, ACTOR, payload.resource)
    assert restored_child == (base if scoped else expected)
    assert len(bindings) == (2 if scoped else 1)
    assert (payload.models.llm.turn_generation is not None) is scoped
    assert all(call.args == (11, ACTOR.tenant_id) for call in lookup.call_args_list)
