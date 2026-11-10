# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise the production evaluation compiler through its AgentOS boundary."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from contracts.agentos import EvaluationAgentRun, PreparedEvaluationRun
from infrastructure.agent_model_config import create_model_config_from_record
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent import runtime_client
from management.services.agent.preparation import compiler, evaluation_snapshot, run
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.concurrency import LanePolicy, ThreadManager
from runtime.agentos import prepared_evaluation

from test.backend.app.test_agentos_prepared_evaluation import evaluation_payload, model_record


@pytest.mark.asyncio
@pytest.mark.parametrize("persisted_body", [False, True])
async def test_production_compiler_routes_root_and_child_parallel_executor_to_runtime(mocker, persisted_body):
    record = model_record(model_id=11, connect_status="available")
    model = create_model_config_from_record(record)

    agent_model_overrides = {"11": {"extra_params": {"__custom__": {"provider_option": "fixture-private-option"}}}}

    def read_agent(agent_id, **kwargs):
        agent = {"name": f"agent_{agent_id}", "description": "Test agent", "model_ids": [11]}
        if persisted_body and agent_id == 7:
            agent["model_params_override"] = agent_model_overrides
        return agent

    mocker.patch.object(compiler, "search_agent_info_by_agent_id", side_effect=read_agent)
    mocker.patch.object(run, "search_agent_info_by_agent_id", side_effect=read_agent)
    mocker.patch.object(compiler, "query_sub_agent_relations", side_effect=lambda main_agent_id, **kwargs: (
        [{"selected_agent_id": 8, "selected_agent_version_no": 5}] if main_agent_id == 7 else []
    ))
    mocker.patch.object(compiler, "resolve_sub_agent_version_no", return_value=5)
    mocker.patch.object(compiler, "_get_external_a2a_agents", return_value=[])
    compile_tools = mocker.patch.object(compiler, "create_tool_config_list", return_value=[])
    mocker.patch.object(compiler, "get_model_by_model_id", return_value=record)
    mocker.patch.object(compiler, "_resolve_context_budget", return_value=None)
    mocker.patch.object(compiler.tenant_config_manager, "get_context_policy", return_value=None)
    mocker.patch.object(compiler, "build_memory_context", return_value=SimpleNamespace(
        user_config=SimpleNamespace(memory_switch=False),
    ))
    mocker.patch("management.services.skill.service.SkillService.get_enabled_skills_for_agent", return_value=[])
    mocker.patch.object(compiler, "RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS", 37)
    mocker.patch.object(run, "_ensure_agent_reasoning_snapshot")
    mocker.patch.object(run, "create_model_config_list", return_value=[model])
    if persisted_body:
        mocker.patch.object(run, "get_model_by_model_id", return_value=record)
    mocker.patch.object(evaluation_snapshot, "get_model_records", return_value=[record])
    mocker.patch("management.services.agent.tool_identity.resolve_tool_user_context", return_value=None)
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=record)
    lookup_override = mocker.patch.object(prepared_evaluation, "read_agent_model_overrides", return_value=agent_model_overrides)
    mocker.patch("contracts.constants.environment.NEXENT_SANDBOX_DEFAULT_LEVEL", "local")
    mocker.patch("contracts.constants.environment.JWT_SECRET", "synthetic-compiler-signing-key")
    client = mocker.AsyncMock()
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)

    case = EvaluationAgentRun(agent_id=7, version_no=2, query="hello", conversation_id=-42)
    assert await runtime_client.forward_evaluation_case(case, "user-a", "tenant-a") is (
        client.run_prepared_evaluation.return_value
    )
    client.run_evaluation_case.assert_not_called()
    assert [call.kwargs["portable_evaluation"] for call in compile_tools.await_args_list] == [True, True]
    prepared, user, tenant = client.run_prepared_evaluation.await_args.args
    assert (user, tenant) == ("user-a", "tenant-a")
    assert prepared.resource.subagents[0].version_no == 5

    encoded = prepared.model_dump_json()
    assert "fixture-private-option" not in encoded
    assert ("provider_body_revision" in encoded) is persisted_body
    payload = PreparedEvaluationRun.model_validate_json(encoded)
    info = prepared_evaluation.prepare_evaluation_run(payload, ServicePrincipal(user, tenant))
    if persisted_body:
        lookup_override.assert_called_once_with(7, 2, "tenant-a")
        assert info.model_config_list[0].extra_body == {"provider_option": "fixture-private-option"}
    else:
        lookup_override.assert_not_called()
    manager = ThreadManager(
        service_name="evaluation-test",
        lane_policies={"model-tool-io": LanePolicy(
            name="model-tool-io", max_workers=2, max_queue_size=0, queue_timeout_seconds=0,
            cancel_grace_seconds=1, shutdown_grace_seconds=1,
        )},
    )
    mocker.patch("nexent.core.tools.parallel_executor.get_current_thread_manager", return_value=manager)
    def echo(value):
        return value.upper()

    manager.start()
    try:
        for agent in [info.agent_config, *info.agent_config.worker_agents]:
            assert [tool.name for tool in agent.tools] == ["parallel_executor", "download_from_s3", "upload_to_s3"]
            config = agent.tools[0]
            tool = NexentAgent.create_local_tool(None, config)
            assert tool.default_timeout_seconds == 37
            assert tool.inputs["timeout"]["default"] == 37
            assert tool.forward([(echo, {"value": "answer"})]) == ["ANSWER"]
    finally:
        await manager.shutdown(timeout=2)


@pytest.mark.parametrize("value", [0, True, "37", 1.5])
def test_parallel_executor_rejects_nonpositive_or_coerced_timeout(mocker, value):
    payload = evaluation_payload()
    payload["resource"]["tools"] = [{
        "tool_id": "parallel_executor", "version": "1", "parameters": {"default_timeout_seconds": value},
    }]
    load_model = mocker.patch.object(prepared_evaluation, "get_model_by_model_id")
    with pytest.raises(HTTPException) as error:
        prepared_evaluation.prepare_evaluation_run(
            PreparedEvaluationRun.model_validate(payload), ServicePrincipal("user-a", "tenant-a"),
        )
    assert error.value.status_code == 422
    load_model.assert_not_called()
