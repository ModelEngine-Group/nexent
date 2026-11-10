# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise the production evaluation compiler through its AgentOS boundary."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from contracts.agent import AgentRequest, WorkbenchSessionConfig
from contracts.agentos import AgentRunReference, EvaluationAgentRun, PreparedAgentRun, PreparedEphemeralRun, PreparedEvaluationRun
from contracts.model import WorkbenchGenerationConfig
from contracts.knowledge import ResolvedKnowledgeScope
from contracts.tool import ToolParamsRequest
from infrastructure.agent_model_config import create_model_config_from_record, create_tenant_default_model_config
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent import runtime_client, workbench
from management.services.agent.preparation import compiler, evaluation_snapshot, run
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.concurrency import LanePolicy, ThreadManager
from runtime.agentos import prepared_evaluation

from test.backend.app.test_agentos_prepared_evaluation import evaluation_payload, model_record


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "persisted_body"), [
    (kind, persisted_body)
    for kind in ("evaluation", "ordinary", "clarification", "turn_generation", "legacy_reasoning", "planning",
                 "default", "new", "metadata", "clear_metadata", "workbench", "workbench_scope",
                 "workbench_metadata", "workbench_first_metadata", "workbench_metadata_denied", "a2a")
    for persisted_body in (False, True)
] + [("a2a_default_model", False)])
async def test_production_compiler_routes_root_and_child_parallel_executor_to_runtime(mocker, persisted_body, kind):
    legacy_default = kind == "a2a_default_model"
    if legacy_default:
        kind = "a2a"
    planning = kind == "planning"
    new = kind in {"new", "workbench_first_metadata"}
    use_workbench = kind.startswith("workbench")
    workbench_metadata = use_workbench and "metadata" in kind
    redis = object()
    get_redis = mocker.patch.object(prepared_evaluation, "get_redis_client", return_value=redis)
    record = model_record(model_id=11, connect_status="available")
    model = create_model_config_from_record(record)
    if legacy_default:
        model = create_tenant_default_model_config(record, "main_model", include_logprobs=True)
        mocker.patch.object(evaluation_snapshot.tenant_config_manager, "get_model_config", return_value=record)

    agent_model_overrides = {"11": {"extra_params": {"__custom__": {"provider_option": "fixture-private-option"}}}}

    def read_agent(agent_id, **kwargs):
        agent = {"name": f"agent_{agent_id}", "description": "Test agent", "model_ids": [] if legacy_default else [11]}
        if persisted_body and agent_id == 7:
            agent["model_params_override"] = agent_model_overrides
        return agent

    mocker.patch.object(compiler, "search_agent_info_by_agent_id", side_effect=read_agent)
    mocker.patch.object(run, "search_agent_info_by_agent_id", side_effect=read_agent)
    mocker.patch.object(compiler, "query_sub_agent_relations", side_effect=lambda main_agent_id, **kwargs: (
        [{"selected_agent_id": 8, "selected_agent_version_no": 5}] if main_agent_id == 7 and not use_workbench else []
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
    mocker.patch.object(evaluation_snapshot, "get_model_records", return_value=[] if legacy_default else [record])
    mocker.patch("management.services.agent.tool_identity.resolve_tool_user_context", return_value=None)
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=record)
    lookup_override = mocker.patch.object(prepared_evaluation, "read_agent_model_overrides", return_value=agent_model_overrides)
    mocker.patch("contracts.constants.environment.NEXENT_SANDBOX_DEFAULT_LEVEL", "local")
    mocker.patch("contracts.constants.environment.JWT_SECRET", "synthetic-compiler-signing-key")
    client = mocker.AsyncMock()
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)

    user, tenant = "user-a", "tenant-a"
    if kind not in {"evaluation", "a2a"}:
        mocker.patch.object(run, "query_current_version_no", return_value=2)
        read_conversation = mocker.patch.object(evaluation_snapshot, "get_conversation", return_value={
            "runtime_metadata": {"project": "test"},
            "runtime_metadata_version": 4,
        })
        mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=False)
        read_history = mocker.patch.object(evaluation_snapshot, "get_historical_context", return_value={
            "history_summary": {"unit_id": 51, "summary": {"markdown": "earlier"}, "covered_through_message_id": 20},
            "conversation_turns": [{"user_message": "previous query", "assistant_final_answer": "previous answer",
                                    "user_message_id": 21, "assistant_message_id": 22, "attachments": None}],
        })
        reference = AgentRunReference(conversation_id=42, run_id="a" * 32)
        metadata = None
        if kind == "metadata" or workbench_metadata:
            metadata = {"project": "replacement"}
        elif kind == "clear_metadata":
            metadata = {}
        clarification = {
            "form": {"schema_version": 1, "questions": [{"id": "goal", "type": "text", "title": "Original form"}]},
            "answers": [{"questionId": "goal", "value": "hello"}],
        } if kind == "clarification" else None
        request = AgentRequest(
            query="hello", agent_id=7, conversation_id=42, clarification_response=clarification,
            enable_automation_tool=kind in {"default", "new"}, enable_plan=planning, metadata=metadata,
        )
        if kind in {"turn_generation", "legacy_reasoning"}:
            if kind == "turn_generation":
                request.generation_config = WorkbenchGenerationConfig(temperature=0.4)
            else:
                request.reasoning_effort = "auto"
            request.version_no = 2
            mocker.patch("management.db.agent.repository.search_agent_info_by_agent_id", side_effect=read_agent)
            mocker.patch("management.services.model.run_controls.get_model_by_model_id", return_value=record)
        if metadata is not None:
            assert await evaluation_snapshot.prepare_conversation_snapshot(
                request, reference, user, tenant, new_conversation=new,
            ) is None
        options = {}
        if use_workbench:
            knowledge = None
            knowledge_scope = {"local": {"mode": "disabled"}} if kind == "workbench_scope" else None
            config = WorkbenchSessionConfig(
                mode="single_agent_chat", agent_mounts=[{"agent_id": 8, "version_no": 5}],
                generation_config={"temperature": 0.4}, knowledge_scope=knowledge_scope,
            )
            if knowledge_scope is not None:
                knowledge = ResolvedKnowledgeScope(
                    desired_scope=config.knowledge_scope.model_dump(mode="json"), tool_params=ToolParamsRequest(),
                    local_disabled=True,
                )
                request.knowledge_scope = config.knowledge_scope
                read_conversation.return_value["knowledge_scope"] = knowledge.desired_scope
            root = workbench.RuntimeAgentIdentity("agent:7:v2", 7, 2, "workbench_main", "Workbench", "SYSTEM")
            child = workbench.RuntimeAgentIdentity("agent:8:v5", 8, 5, "agent_8_v5", "Child", "PERSISTED")
            plan = workbench.ResolvedAgentPlan(
                workbench.PublishedRootDescriptor(root, {}), workbench.RootRuntimeOverlay(None, None, (), None), (),
                child_mounts=(child,),
            )
            request.entrypoint = "workbench"
            options["workbench"] = workbench.PreparedWorkbench(
                config, plan, 0 if new else 3, 1 if new else 4,
                knowledge=knowledge, knowledge_tools=[] if knowledge is not None else None,
            )
        if workbench_metadata:
            permission = mocker.patch(
                "management.db.agent.repository.search_agent_info_by_agent_id",
                return_value={"allow_chat_metadata": kind != "workbench_metadata_denied"},
            )
        if kind == "workbench_metadata_denied":
            from contracts.errors.codes import ErrorCode
            from contracts.errors.exceptions import AppException

            with pytest.raises(AppException) as error:
                await evaluation_snapshot.prepare_conversation_snapshot(request, reference, user, tenant, **options)
            assert error.value.error_code == ErrorCode.CHAT_METADATA_NOT_ALLOWED
            permission.assert_called_once_with(7, tenant, 2)
            compile_tools.assert_not_awaited()
            return
        prepared = await evaluation_snapshot.prepare_conversation_snapshot(
            request, reference, user, tenant, language="en", timezone="Asia/Shanghai", **options,
            allow_metadata_update=metadata is not None and not use_workbench,
            **({"new_conversation": True} if new else {"current_user_message_id": 23}),
        )
        assert isinstance(prepared, PreparedAgentRun)
        assert (prepared.run_id, prepared.conversation_id, prepared.resource.version_no) == (reference.run_id, 42, 2)
        assert prepared.input.query != "hello" and "hello" in prepared.input.query
        if clarification is not None:
            assert "Original form" not in prepared.model_dump_json()
        payload = PreparedAgentRun.model_validate_json(prepared.model_dump_json())
        info = prepared_evaluation.prepare_run_snapshot(payload, ServicePrincipal(user, tenant))
        if kind in {"turn_generation", "legacy_reasoning"}:
            wire = payload.model_dump()["models"]["llm"]["turn_generation"]
            assert wire.get("settings") == ({"temperature": 0.4} if kind == "turn_generation" else None)
            assert wire.get("reasoning_effort") == ("auto" if kind == "legacy_reasoning" else None)
            assert info.agent_config.model_name != info.agent_config.worker_agents[0].model_name
            assert info.model_config_list[1].temperature == model.temperature
            if kind == "turn_generation":
                assert info.model_config_list[0].temperature == 0.4
                assert info.model_config_list[0].explicit_sampling == ["temperature"]
        if use_workbench:
            root_tools = [call for call in compile_tools.await_args_list if call.args[0] == 7]
            assert root_tools[0].kwargs["runtime_skill_snapshot"] == []
            if kind == "workbench_scope":
                assert root_tools[0].kwargs["runtime_knowledge_tools"] == []
                assert next(call for call in compile_tools.await_args_list if call.args[0] == 8).kwargs[
                    "runtime_knowledge_tools"
                ] is None
            assert payload.workbench_config_version == (1 if new else 4)
            if workbench_metadata:
                permission.assert_called_once_with(7, tenant, 2)
            assert payload.models.llm.root_generation.temperature == 0.4
            assert info.agent_config.invocation_name == "workbench_main"
            assert info.agent_config.worker_agents[0].invocation_name == "agent_8_v5"
            assert info.agent_config.model_name != info.agent_config.worker_agents[0].model_name
            assert info.model_config_list[0].temperature == 0.4
            assert info.model_config_list[0].explicit_sampling == ["temperature"]
            assert info.model_config_list[1].temperature == model.temperature
        if new:
            read_conversation.assert_not_called()
            read_history.assert_not_called()
            assert info.runtime_metadata == (metadata or {})
            assert info.runtime_metadata_version == (1 if workbench_metadata else 0)
            assert prepared.historical_context is None
        else:
            assert info.runtime_metadata == ({"project": "test"} if metadata is None else metadata)
            assert info.runtime_metadata_version == (4 if metadata is None else 5)
            read_history.assert_called_once_with(42, 23, user, tenant)
            assert [item.id for item in info.context_input.items][-2:] == ["history_summary:51", "conversation_turn:21:22"]
    elif kind == "a2a":
        lookup = mocker.patch(
            "management.db.agent.repository.search_agent_info_by_agent_id",
            return_value={"allow_chat_metadata": True},
        )
        request = AgentRequest(
            agent_id=7, version_no=2, query="hello", is_debug=True, metadata={"ticket": "42"},
            history=[{"role": "user", "content": "earlier"}],
        )
        prepared = await evaluation_snapshot.prepare_a2a_snapshot(request, user, tenant)
        lookup.assert_called_once_with(7, tenant, 2)
        payload = PreparedEphemeralRun.model_validate_json(prepared.model_dump_json())
        info = prepared_evaluation.prepare_run_snapshot(payload, ServicePrincipal(user, tenant))
        assert "conversation_id" not in payload.model_dump()
        assert info.conversation_id is None and info.workspace_run_id == payload.run_id
        assert info.runtime_metadata == {"ticket": "42"}
        assert payload.input.history[0].content == "earlier"
        if legacy_default:
            assert payload.models.llm.model_id == 11
            assert payload.models.llm.tenant_default_profile == "logprobs"
            assert info.model_config_list[0] == model
    else:
        case = EvaluationAgentRun(agent_id=7, version_no=2, query="hello", conversation_id=-42)
        assert await runtime_client.forward_evaluation_case(case, user, tenant) is client.run_prepared_evaluation.return_value
        client.run_evaluation_case.assert_not_called()
        prepared, sent_user, sent_tenant = client.run_prepared_evaluation.await_args.args
        assert (sent_user, sent_tenant) == (user, tenant)
        payload = PreparedEvaluationRun.model_validate_json(prepared.model_dump_json())
        info = prepared_evaluation.prepare_evaluation_run(payload, ServicePrincipal(user, tenant))

    assert [call.kwargs["portable_evaluation"] for call in compile_tools.await_args_list] == [True, True]
    assert prepared.resource.subagents[0].version_no == 5
    assert info.agent_config.enable_planning is planning
    if planning:
        get_redis.assert_called_once_with()
        assert info.redis_client is redis
        bindings = [tool for tool in prepared.resource.tools if tool.tool_id in ("create_plan", "update_plan_step")]
        assert [tool.tool_id for tool in bindings] == ["create_plan", "update_plan_step"]
        assert all(tool.version == "1" and not tool.parameters and tool.credential_ref is None for tool in bindings)
    else:
        get_redis.assert_not_called()
    encoded = prepared.model_dump_json()
    assert "fixture-private-option" not in encoded
    assert ("provider_body_revision" in encoded) is persisted_body
    if persisted_body:
        if use_workbench or kind in {"turn_generation", "legacy_reasoning"}:
            assert lookup_override.call_count == 2
            extra = {"provider_option": "fixture-private-option"}
            if use_workbench:
                extra["enable_thinking"] = False
            assert info.model_config_list[0].extra_body == extra
        else:
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
            expected = ["parallel_executor", "download_from_s3", "upload_to_s3"]
            if kind in {"default", "new"} and agent is info.agent_config:
                expected.insert(1, "create_scheduled_task_proposal")
                tool = next(tool for tool in agent.tools if tool.name == "create_scheduled_task_proposal")
                assert callable(tool.metadata["create_proposal"])
                assert "create_proposal" not in encoded
            if planning and agent is info.agent_config:
                expected.extend(["create_plan", "update_plan_step"])
                executor = SimpleNamespace(observer=info.observer)
                tools = [NexentAgent.create_local_tool(executor, item) for item in agent.tools[-2:]]
                assert [tool.name for tool in tools] == expected[-2:]
            assert [tool.name for tool in agent.tools] == expected
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


@pytest.mark.asyncio
async def test_prepared_conversation_scope_is_checked_before_compilation(mocker):
    from contracts.errors.exceptions import ForbiddenError

    read = mocker.patch.object(evaluation_snapshot, "get_conversation", return_value=None)
    compile_run = mocker.patch.object(run, "create_agent_run_info")
    reference = AgentRunReference(conversation_id=42, run_id="a" * 32)
    request = AgentRequest(query="hello", agent_id=7, conversation_id=42, enable_automation_tool=False)

    with pytest.raises(ForbiddenError):
        await evaluation_snapshot.prepare_conversation_snapshot(request, reference, "actor", "foreign")
    read.assert_called_once_with(42, user_id="actor", tenant_id="foreign")
    compile_run.assert_not_called()


@pytest.mark.asyncio
async def test_prepared_conversation_does_not_drop_memory_or_scope(mocker):
    get_conversation = mocker.patch.object(evaluation_snapshot, "get_conversation", return_value={"knowledge_scope": {"local": []}})
    memory = mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=True)
    compile_run = mocker.patch.object(run, "create_agent_run_info")
    reference = AgentRunReference(conversation_id=42, run_id="a" * 32)
    request = AgentRequest(query="hello", agent_id=7, conversation_id=42, enable_automation_tool=False)

    assert await evaluation_snapshot.prepare_conversation_snapshot(request, reference, "actor", "tenant") is None
    memory.assert_not_called()
    compile_run.assert_not_called()
    get_conversation.return_value = {}
    assert await evaluation_snapshot.prepare_conversation_snapshot(
        request, reference, "actor", "tenant",
    ) is compile_run.return_value
    memory.assert_called_once_with("actor")
    assert compile_run.await_args.kwargs["allow_memory_search"] is True
    assert compile_run.await_args.kwargs["prepared_conversation"].memory_enabled is True


@pytest.mark.asyncio
async def test_prepared_conversation_cannot_export_unowned_message_boundary(mocker):
    from contracts.errors.exceptions import ForbiddenError

    mocker.patch.object(evaluation_snapshot, "get_conversation", return_value={})
    mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=False)
    read_history = mocker.patch.object(evaluation_snapshot, "get_historical_context", return_value=None)
    compile_run = mocker.patch.object(run, "create_agent_run_info")
    reference = AgentRunReference(conversation_id=42, run_id="a" * 32)
    request = AgentRequest(query="hello", agent_id=7, conversation_id=42, enable_automation_tool=False)

    with pytest.raises(ForbiddenError, match="history boundary"):
        await evaluation_snapshot.prepare_conversation_snapshot(
            request, reference, "actor", "tenant", current_user_message_id=99,
        )
    read_history.assert_called_once_with(42, 99, "actor", "tenant")
    compile_run.assert_not_called()


def test_prepared_conversation_rejects_foreign_history_attachment():
    from contracts.agentos import PreparedConversationHistory
    from contracts.constants.environment import MINIO_DEFAULT_BUCKET

    turn = {"user_message": "request", "assistant_final_answer": "answer",
            "user_message_id": 21, "assistant_message_id": 22}
    attachment = {"name": "report", "url": f"s3://{MINIO_DEFAULT_BUCKET or 'nexent'}/attachments/other/report"}
    with pytest.raises(PermissionError):
        evaluation_snapshot._prepare_conversation_history(
            {"conversation_turns": [turn | {"attachments": [attachment]}]}, "actor", "tenant",
        )

    context = PreparedConversationHistory(conversation_turns=[turn | {"attachment_refs": [attachment]}])
    with pytest.raises(HTTPException) as error:
        prepared_evaluation._restore_conversation_history(context, ServicePrincipal("actor", "tenant"))
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_a2a_metadata_requires_permission_on_published_version(mocker):
    from contracts.errors.codes import ErrorCode
    from contracts.errors.exceptions import AppException

    lookup = mocker.patch(
        "management.db.agent.repository.search_agent_info_by_agent_id",
        return_value={"allow_chat_metadata": False},
    )
    compile_run = mocker.patch.object(run, "create_agent_run_info")
    with pytest.raises(AppException) as error:
        await evaluation_snapshot.prepare_a2a_snapshot(
            AgentRequest(agent_id=7, version_no=2, query="hello", is_debug=True, metadata={"ticket": "42"}),
            "user-a", "tenant-a",
        )
    assert error.value.error_code == ErrorCode.CHAT_METADATA_NOT_ALLOWED
    lookup.assert_called_once_with(7, "tenant-a", 2)
    compile_run.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("version", "member_group", "permission", "allowed"), [
    (0, 9, "EDIT", True),
    (0, 8, "EDIT", False),
    (0, 9, "READ_ONLY", False),
    (2, 9, "READ_ONLY", True),
])
async def test_debug_snapshot_uses_the_tenant_group_and_version_before_compilation(
    mocker, version, member_group, permission, allowed,
):
    from contracts.errors.exceptions import ForbiddenError
    from management.services.agent import authorization
    from test.backend.app.test_agentos_prepared_evaluation import evaluation_payload

    draft = {"tenant_id": "tenant-a", "created_by": "someone-else", "group_ids": "9", "ingroup_permission": permission}
    read = mocker.patch.object(authorization, "search_agent_info_by_agent_id", return_value=draft)
    mocker.patch.object(authorization, "get_user_role_by_tenant", return_value="MEMBER")
    groups = mocker.patch.object(authorization, "query_group_ids_by_user_in_tenant", return_value=[member_group])
    memory = mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=True)
    mocker.patch("management.services.model.run_controls.preflight_turn_controls")
    fields = evaluation_payload()
    fields["resource"]["version_no"] = version
    compile_run = mocker.patch.object(run, "create_agent_run_info", return_value=PreparedEvaluationRun.model_validate(fields))
    request = AgentRequest(
        agent_id=7, is_debug=True, query="hello", version_no=version if version else None,
        generation_config={"temperature": 0.4},
    )
    if allowed:
        snapshot = await evaluation_snapshot.prepare_debug_snapshot(
            request, "actor", "tenant-a", language="en", timezone="Asia/Shanghai",
        )
        assert snapshot.debug is True and snapshot.resource.version_no == version
        assert "conversation_id" not in snapshot.model_dump()
        options = compile_run.await_args.kwargs
        assert options["override_version_no"] == version and options["is_debug"]
        assert options["turn_generation"].model_dump() == {"settings": {"temperature": 0.4}}
        assert options["allow_memory_search"] is False and options["enable_automation_tool"] is False
    else:
        with pytest.raises(ForbiddenError):
            await evaluation_snapshot.prepare_debug_snapshot(
                request, "actor", "tenant-a", language="en", timezone="Asia/Shanghai",
            )
        compile_run.assert_not_awaited()
    read.assert_called_once_with(7, "tenant-a", version)
    groups.assert_called_once_with("actor", "tenant-a")
    memory.assert_not_called()
