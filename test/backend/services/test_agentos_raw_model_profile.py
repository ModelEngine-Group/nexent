# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Round-trip session parameters without changing a child Agent's model defaults."""

from unittest.mock import AsyncMock

import pytest

from contracts.agent import AgentRequest
from contracts.agentos import AgentRunReference, PreparedAgentRun, PreparedEphemeralRun
from infrastructure.agent_model_config import create_model_config_from_record
from management.services.agent import authorization, tool_identity
from management.services.agent.preparation import evaluation_snapshot, run
from management.services.model import run_controls
from nexent.core.agents.contracts.config import AgentConfig
from runtime.agentos import prepared_evaluation
from ..app.test_agentos_prepared_evaluation import model_record
from .model_profile_helpers import stub_resolved_model_catalog
from .test_agentos_raw_preparation import ACTOR


@pytest.mark.asyncio
@pytest.mark.parametrize("debug", [True, False], ids=["debug", "new-conversation"])
@pytest.mark.parametrize("settings", [None, {}, {"temperature": 0.3, "top_p": 0.7}, {"temperature": None}],
                         ids=["omitted", "empty", "sampling", "explicit-null"])
async def test_prepared_profile_round_trip_keeps_child_model_defaults(mocker, settings, debug):
    record = model_record(tenant_id=ACTOR.tenant_id)
    base = create_model_config_from_record(record)
    child = AgentConfig(agent_id=8, version_no=1, name="child", description="", model_name=base.cite_name, tools=[])

    async def models(tenant, *, versions):
        assert tenant == ACTOR.tenant_id
        versions[base.cite_name] = (11, "revision-1")
        return [base.model_copy(deep=True)]

    mocker.patch.object(run, "_ensure_agent_reasoning_snapshot")
    mocker.patch.object(run, "create_model_config_list", new=AsyncMock(side_effect=models))
    mocker.patch.object(run, "search_agent_info_by_agent_id", return_value={"model_params_override": {}})
    mocker.patch.object(run, "create_agent_config", new=AsyncMock(return_value=AgentConfig(
        agent_id=7, version_no=0, name="root", description="", model_name=base.cite_name, tools=[], worker_agents=[child],
    )))
    stub_resolved_model_catalog(mocker, record)
    mocker.patch.object(tool_identity, "resolve_tool_user_context", return_value={})
    lookup = mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=record)

    preferences = {"11": settings} if settings else {}
    request = AgentRequest(query="hello", agent_id=7, is_debug=debug)
    if debug:
        mocker.patch.object(authorization, "authorize_debug_version", return_value={"agent_id": 7})
        mocker.patch.object(run_controls, "preflight_turn_controls")
        prepared = await evaluation_snapshot.prepare_debug_snapshot(
            request.model_copy(update={"model_parameter_preferences": preferences}),
            ACTOR.user_id, ACTOR.tenant_id, language="zh", timezone=None,
        )
        payload = PreparedEphemeralRun.model_validate_json(prepared.payload.model_dump_json())
    else:
        mocker.patch.object(run, "query_current_version_no", return_value=0)
        mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=False)
        mocker.patch.object(run_controls, "validate_agent_model_selection")
        mocker.patch.object(run_controls, "preflight_agent_turn_controls")
        reference = AgentRunReference(conversation_id=42, run_id="a" * 32)
        prepared = await evaluation_snapshot.prepare_conversation_snapshot(
            request.model_copy(update={"conversation_id": 42}), reference, ACTOR.user_id, ACTOR.tenant_id,
            new_conversation=True, owned_conversation={"model_parameter_preferences": preferences},
        )
        payload = PreparedAgentRun.model_validate_json(prepared.model_dump_json())

    assert record["api_key"] not in payload.model_dump_json()
    assert payload.models.llm.conversation_parameters == (settings or None)
    restored = prepared_evaluation.prepare_run_snapshot(payload, ACTOR)
    profiles = {model.cite_name: model.resolved_profile for model in restored.model_config_list}
    root = profiles[restored.agent_config.model_name]
    child = profiles[restored.agent_config.worker_agents[0].model_name]
    for name in ("temperature", "top_p"):
        assert root.parameter_values.get(name) == (settings or {}).get(name, base.resolved_profile.parameter_values.get(name))
    assert child == base.resolved_profile
    assert len(profiles) == (2 if settings else 1)
    assert lookup.call_args_list
    assert all(call.args == (11, ACTOR.tenant_id) for call in lookup.call_args_list)
