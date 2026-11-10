# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise the production evaluation compiler through its AgentOS boundary."""

import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from contracts.agent import AgentRequest, WorkbenchSessionConfig
from contracts.agentos import CompatibilityConversationRun, AgentRunReference, EvaluationAgentRun, PreparedAgentRun, PreparedEphemeralRun, PreparedEvaluationRun
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, WorkbenchError
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


@pytest.mark.parametrize("changed", [False, True])
def test_snapshot_pins_the_first_catalog_model_for_a_legacy_duplicate_alias(mocker, changed):
    first = model_record(model_id=11, model_name="first", api_key="first-private-key")
    second = model_record(model_id=12, model_name="second", api_key="second-private-key")
    records = [first, second]
    models = [create_model_config_from_record(record) for record in records]
    lookup = mocker.patch.object(
        evaluation_snapshot, "get_model_records", return_value=list(reversed(records)) if changed else records,
    )
    resource = SimpleNamespace(agent_id=7, version_no=2)

    if changed:
        with pytest.raises(ValueError, match="Unsupported evaluation model override"):
            evaluation_snapshot._export_model(models[0].cite_name, models, "tenant-a", resource, {})
    else:
        binding = evaluation_snapshot._export_model(models[0].cite_name, models, "tenant-a", resource, {})
        assert binding.model_id == 11
        assert "first-private-key" not in binding.model_dump_json()
    lookup.assert_called_once_with({"display_name": "Evaluation", "model_type": "llm"}, "tenant-a")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,child_ids", [
    ("generic_chat", []), ("single_agent_chat", [8]), ("multi_agent_chat", [9, 8]),
])
@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize("legacy_reasoning", [False, True])
async def test_workbench_debug_runs_through_agentos(mocker, mode, child_ids, scoped, legacy_reasoning):
    mounts = [{"agent_id": child_id, "version_no": 5} for child_id in child_ids]
    request = AgentRequest(
        query="hello", is_debug=True, entrypoint="workbench",
        metadata={"project": "fixture"} if scoped else None,
        reasoning_effort="low" if legacy_reasoning else None,
        workbench={
            "mode": mode, "agent_mounts": mounts, "generation_config": {"temperature": 0.4},
            "knowledge_scope": {"local": {"mode": "disabled"}} if scoped else None,
            "model_id": 11 if legacy_reasoning else None,
        },
    )
    config = request.workbench
    root = workbench.RuntimeAgentIdentity("agent:7:v2", 7, 2, "workbench_main", "Workbench", "SYSTEM")
    children = tuple(
        workbench.RuntimeAgentIdentity(f"agent:{child_id}:v5", child_id, 5, f"agent_{child_id}_v5", "Child", "PERSISTED")
        for child_id in child_ids
    )
    plan = workbench.ResolvedAgentPlan(
        workbench.PublishedRootDescriptor(root, {}), workbench.RootRuntimeOverlay(None, None, (), None), (),
        child_mounts=children,
    )
    resolve = mocker.patch.object(workbench, "resolve_workbench_config", return_value=(config, plan))
    if scoped:
        from management.services.knowledge_base import mount, scope

        metadata_policy = mocker.patch(
            "management.db.agent.repository.search_agent_info_by_agent_id",
            return_value={"allow_chat_metadata": True},
        )
        mocker.patch.object(scope, "snapshot_runtime_knowledge_tree", return_value=[
            {"agent_id": 7, "tools": []}, {"agent_id": 8, "tools": []},
        ])
        mounted_tools = [{"name": "knowledge_base_search"}]
        mocker.patch.object(mount, "mount_knowledge_records", return_value=mounted_tools)
        knowledge = ResolvedKnowledgeScope(
            desired_scope=config.knowledge_scope.model_dump(mode="json"), tool_params=ToolParamsRequest(),
            local_disabled=True,
        )
        authorize_scope = mocker.patch.object(scope, "resolve_knowledge_scope", return_value=knowledge)
    raw = evaluation_payload()
    raw["resource"]["origin"] = "SYSTEM"
    raw["models"]["llm"]["root_generation"] = {"temperature": 0.4}
    if legacy_reasoning:
        mocker.patch("management.services.model.run_controls.get_model_by_model_id", return_value=model_record(connect_status="available"))
        raw["models"]["llm"]["turn_generation"] = {"reasoning_effort": "low"}
    if children:
        raw["models"]["additional_llms"] = [{"model_id": 11, "alias": "child_model", "revision": "revision-1"}]
        raw["resource"]["subagents"] = [
            {
                "agent_id": child.agent_id, "version_no": child.version_no, "name": child.invocation_name,
                "description": child.display_name, "invocation_name": child.invocation_name, "model_alias": "child_model",
                "prompt_templates": {"system_prompt": "Answer the query"},
            }
            for child in children
        ]
    compile_run = mocker.patch.object(run, "create_agent_run_info", return_value=PreparedEvaluationRun.model_validate(raw))
    mocker.patch.object(runtime_client, "ENABLE_AGENT_WORKBENCH", True)
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=model_record())
    mocker.patch("contracts.constants.environment.NEXENT_SANDBOX_DEFAULT_LEVEL", "local")

    async def events():
        yield b'data: {"type":"final_answer","content":"answer"}\n\n'

    client = mocker.patch.object(runtime_client, "_agentos_client").return_value
    client.run_ephemeral = AsyncMock(return_value=StreamingResponse(events()))
    client.run_conversation = AsyncMock()
    result = await runtime_client.forward_conversation_run(
        CompatibilityConversationRun(request=request.model_dump(mode="json")), "actor", "tenant-a",
    )
    client.run_conversation.assert_not_awaited()
    resolve.assert_called_once_with(config, tenant_id="tenant-a", is_debug=True, user_id="actor")
    options = compile_run.await_args.kwargs
    assert options["prepared_workbench"].plan == plan
    assert options["override_version_no"] == 2
    assert options["reasoning_effort"] == ("low" if legacy_reasoning else None)
    assert options["runtime_sub_agent_mounts"] == [asdict(child) for child in children]
    if scoped:
        metadata_policy.assert_called_once_with(7, "tenant-a", 2)
        authorize_scope.assert_called_once_with(
            scope=config.knowledge_scope, agent_id=7, tenant_id="tenant-a", user_id="actor", version_no=2,
            is_debug=True, request_tool_params=None, runtime_agent_tree=[{"agent_id": 7, "tools": mounted_tools}],
        )
        assert options["runtime_knowledge_tools"] == mounted_tools
        assert options["tool_params"] is knowledge.tool_params
    snapshot = client.run_ephemeral.await_args.args[0]
    info = prepared_evaluation.prepare_run_snapshot(snapshot, ServicePrincipal("actor", "tenant-a"))
    assert info.conversation_id is None
    assert info.runtime_metadata == ({"project": "fixture"} if scoped else {})
    assert info.runtime_metadata_version is None
    assert info.model_config_list[0].temperature == 0.4
    assert [(child.agent_id, child.version_no, child.model_name) for child in info.agent_config.worker_agents] == [
        (child_id, 5, "child_model") for child_id in child_ids
    ]
    frames = [json.loads(frame.removeprefix(b"data: ")) async for frame in result.body_iterator]
    assert frames[0] == {"type": "workbench_config_resolved", "content": {
        "config_version": 0, "schema_version": 3, "mode": mode,
        "agent_mounts": [mount.model_dump(mode="json") for mount in config.agent_mounts],
    }}
    assert [frame["type"] for frame in frames] == (
        ["workbench_config_resolved", "knowledge_scope_resolved", "final_answer"] if scoped
        else ["workbench_config_resolved", "final_answer"]
    )


@pytest.mark.asyncio
async def test_workbench_debug_denies_mount_without_dispatch(mocker):
    mocker.patch.object(runtime_client, "ENABLE_AGENT_WORKBENCH", True)
    mocker.patch.object(workbench, "resolve_workbench_config", side_effect=WorkbenchError("AGENT_NOT_RUNNABLE", 403))
    client = mocker.patch.object(runtime_client, "_agentos_client").return_value
    payload = CompatibilityConversationRun(request={
        "query": "hello", "is_debug": True, "entrypoint": "workbench",
        "workbench": {"mode": "single_agent_chat", "agent_mounts": [{"agent_id": 8, "version_no": 5}]},
    })

    with pytest.raises(HTTPException) as denied:
        await runtime_client.forward_conversation_run(payload, "actor", "tenant-a")

    assert denied.value.status_code == 403
    assert denied.value.detail == {"code": "AGENT_NOT_RUNNABLE"}
    client.run_ephemeral.assert_not_called()
    client.run_conversation.assert_not_called()


@pytest.mark.asyncio
async def test_workbench_debug_checks_root_metadata_policy_before_dispatch(mocker):
    mocker.patch.object(runtime_client, "ENABLE_AGENT_WORKBENCH", True)
    root = workbench.RuntimeAgentIdentity("agent:7:v2", 7, 2, "workbench_main", "Workbench", "SYSTEM")
    plan = workbench.ResolvedAgentPlan(
        workbench.PublishedRootDescriptor(root, {}), workbench.RootRuntimeOverlay(None, None, (), None), (),
    )
    config = WorkbenchSessionConfig(mode="generic_chat")
    mocker.patch.object(workbench, "resolve_workbench_config", return_value=(config, plan))
    policy = mocker.patch(
        "management.db.agent.repository.search_agent_info_by_agent_id", return_value={"allow_chat_metadata": False},
    )
    compile_run = mocker.patch.object(run, "create_agent_run_info")
    client = mocker.patch.object(runtime_client, "_agentos_client").return_value
    payload = CompatibilityConversationRun(request={
        "query": "hello", "is_debug": True, "entrypoint": "workbench", "agent_id": 999,
        "metadata": {}, "workbench": config.model_dump(mode="json"),
    })

    with pytest.raises(AppException) as denied:
        await runtime_client.forward_conversation_run(payload, "actor", "tenant-a")

    assert denied.value.error_code == ErrorCode.CHAT_METADATA_NOT_ALLOWED
    policy.assert_called_once_with(7, "tenant-a", 2)
    compile_run.assert_not_called()
    client.run_ephemeral.assert_not_called()
    client.run_conversation.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_compile_requires_runtime_materializer_before_resource_reads(mocker):
    load_agent = mocker.patch.object(run, "search_agent_info_by_agent_id")
    allocate_workspace = mocker.patch.object(run, "_build_run_workspace")

    with pytest.raises(ValueError, match="requires a Runtime materializer"):
        await run.create_agent_run_info(7, [], "hello", [], "tenant", "actor")

    load_agent.assert_not_called()
    allocate_workspace.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_compile_preserves_values_in_the_runtime_factory(mocker, tmp_path):
    from nexent.core.agents.agent_model import AgentConfig
    from runtime.adapters.nexent import factory

    workspace = tmp_path / "run"
    model = create_model_config_from_record(model_record(model_id=11, connect_status="available"))
    agent = AgentConfig(name="test", description="test", tools=[], model_name=model.cite_name, sandbox_policy={"level": "local"})
    mocker.patch.object(run, "_build_run_workspace", return_value=str(workspace))
    mocker.patch.object(run, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    mocker.patch.object(run, "_validate_run_minio_files")
    mocker.patch.object(run, "_ensure_agent_reasoning_snapshot")
    mocker.patch.object(run, "create_agent_config", return_value=agent)
    mocker.patch.object(run, "search_agent_info_by_agent_id", return_value={})
    mocker.patch.object(run, "create_model_config_list", return_value=[model])
    mocker.patch.object(run, "get_remote_mcp_server_list", return_value=[])
    mocker.patch.object(run, "get_tenant_local_mcp_server", return_value="http://mcp/mcp")
    mocker.patch.object(run, "resolve_tool_user_context", return_value={"tenant_id": "tenant"})
    mocker.patch.object(run, "get_redis_client", return_value=None)
    storage = object()
    storage_client = mocker.patch.object(factory, "get_sandbox_minio_client", return_value=storage)

    prepared = await run.create_agent_run_info(
        7, [], "hello", [], "tenant", "actor", is_debug=True, legacy_materializer=factory.materialize_legacy_run,
    )

    assert prepared.query == "hello" and prepared.agent_config is agent
    assert prepared.model_config_list == [model]
    assert prepared.user_context == {"tenant_id": "tenant"}
    assert not prepared.stop_event.is_set()
    assert prepared.minio_client is storage
    storage_client.assert_called_once_with()
    assert prepared.sandbox_config.output_dir == str(workspace / "outputs")
    assert prepared.sandbox_config.extra_kwargs["workspace_root"] == str(tmp_path.resolve())


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "persisted_body"), [
    (kind, persisted_body)
    for kind in ("evaluation", "ordinary", "clarification", "turn_generation", "legacy_reasoning", "planning",
                 "default", "new", "metadata", "clear_metadata", "first_metadata", "metadata_denied",
                 "metadata_conflict", "northbound_metadata", "workbench", "workbench_scope", "workbench_mixed_controls",
                 "workbench_legacy_reasoning",
                 "workbench_metadata", "workbench_first_metadata", "workbench_metadata_denied", "a2a", "debug_planning")
    for persisted_body in (False, True)
] + [("a2a_default_model", False)])
async def test_production_compiler_routes_root_and_child_parallel_executor_to_runtime(mocker, persisted_body, kind):
    legacy_default = kind == "a2a_default_model"
    if legacy_default:
        kind = "a2a"
    debug_planning = kind == "debug_planning"
    planning = kind == "planning" or debug_planning
    new = kind in {"new", "first_metadata", "workbench_first_metadata"}
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
    client = AsyncMock()
    mocker.patch.object(runtime_client, "_agentos_client", return_value=client)

    user, tenant = "user-a", "tenant-a"
    if kind not in {"evaluation", "a2a", "debug_planning"}:
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
        if kind in {"metadata", "first_metadata", "metadata_denied", "metadata_conflict", "northbound_metadata"} or workbench_metadata:
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
        if kind == "clear_metadata":
            request.version_no = 2
        if kind == "metadata_conflict":
            request.expected_metadata_version = 3
        if kind == "first_metadata":
            request.expected_metadata_version = 99
        options = {}
        if use_workbench:
            knowledge = None
            knowledge_scope = {"local": {"mode": "disabled"}} if kind == "workbench_scope" else None
            config = WorkbenchSessionConfig(
                mode="single_agent_chat", agent_mounts=[{"agent_id": 8, "version_no": 5}],
                generation_config={"temperature": 0.4}, knowledge_scope=knowledge_scope,
            )
            if kind in {"workbench_mixed_controls", "workbench_legacy_reasoning"}:
                from management.services.model import run_controls

                config.model_id = 11
                if kind == "workbench_mixed_controls":
                    request.generation_config = WorkbenchGenerationConfig(temperature=1.7, top_p=0.8)
                else:
                    request.reasoning_effort = "low"
                mocker.patch.object(run_controls, "get_model_by_model_id", return_value=record)
                mocker.patch.object(run, "get_model_by_model_id", return_value=record)
                preflight_overlay = mocker.patch.object(run_controls, "overlay_root_model", wraps=run_controls.overlay_root_model)
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
        if metadata is not None:
            permission = mocker.patch(
                "management.db.agent.repository.search_agent_info_by_agent_id",
                return_value={"allow_chat_metadata": kind not in {"workbench_metadata_denied", "metadata_denied", "northbound_metadata"}},
            )
        if kind in {"workbench_metadata_denied", "metadata_denied"}:
            from contracts.errors.codes import ErrorCode
            from contracts.errors.exceptions import AppException

            with pytest.raises(AppException) as error:
                await evaluation_snapshot.prepare_conversation_snapshot(request, reference, user, tenant, **options)
            assert error.value.error_code == ErrorCode.CHAT_METADATA_NOT_ALLOWED
            permission.assert_called_once_with(7, tenant, 2 if use_workbench else 0)
            compile_tools.assert_not_awaited()
            return
        if kind == "metadata_conflict":
            from contracts.errors.exceptions import RuntimeMetadataVersionConflict

            with pytest.raises(RuntimeMetadataVersionConflict) as error:
                await evaluation_snapshot.prepare_conversation_snapshot(request, reference, user, tenant)
            assert error.value.current_version == 4
            permission.assert_called_once_with(7, tenant, 0)
            compile_tools.assert_not_awaited()
            return
        prepared = await evaluation_snapshot.prepare_conversation_snapshot(
            request, reference, user, tenant, language="en", timezone="Asia/Shanghai", **options,
            **({"metadata_from_northbound": True} if kind == "northbound_metadata" else {}),
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
            if kind == "workbench_legacy_reasoning":
                assert payload.models.llm.turn_generation.model_dump() == {"reasoning_effort": "low"}
            assert info.agent_config.invocation_name == "workbench_main"
            assert info.agent_config.worker_agents[0].invocation_name == "agent_8_v5"
            assert info.agent_config.model_name != info.agent_config.worker_agents[0].model_name
            assert info.model_config_list[0].temperature == 0.4
            assert info.model_config_list[0].explicit_sampling == ["temperature"]
            assert info.model_config_list[1].temperature == model.temperature
            if kind == "workbench_mixed_controls":
                preflight = next(call.args[1] for call in preflight_overlay.call_args_list if call.args[2] == "preflight_root")
                assert preflight == config.generation_config.model_dump(mode="json")
                assert info.model_config_list[0].top_p == model.top_p
                assert request.generation_config.temperature == 1.7
        if metadata is not None and not use_workbench:
            if kind == "northbound_metadata":
                permission.assert_not_called()
            else:
                permission.assert_called_once_with(7, tenant, request.version_no or 0)
        if new:
            read_conversation.assert_not_called()
            read_history.assert_not_called()
            assert info.runtime_metadata == (metadata or {})
            assert info.runtime_metadata_version == (1 if metadata is not None else 0)
            assert prepared.historical_context is None
        else:
            assert info.runtime_metadata == ({"project": "test"} if metadata is None else metadata)
            assert info.runtime_metadata_version == (4 if metadata is None else 5)
            read_history.assert_called_once_with(42, 23, user, tenant)
            assert [item.id for item in info.context_input.items][-2:] == ["history_summary:51", "conversation_turn:21:22"]
    elif debug_planning:
        from management.services.agent import authorization

        authorize = mocker.patch.object(authorization, "authorize_debug_version", return_value={})
        mocker.patch("management.services.model.run_controls.preflight_turn_controls")
        request = AgentRequest(
            agent_id=7, is_debug=True, enable_plan=True, query="hello",
            history=[{"role": "system", "content": "ignored client history"}],
        )
        response = await runtime_client.forward_conversation_run(
            CompatibilityConversationRun(request=request.model_dump()), user, tenant,
        )
        client.run_conversation.assert_not_awaited()
        prepared, sent_user, sent_tenant = client.run_ephemeral.await_args.args
        assert response is client.run_ephemeral.return_value
        assert (sent_user, sent_tenant) == (user, tenant)
        authorize.assert_called_once_with(7, 0, user, tenant)
        payload = PreparedEphemeralRun.model_validate_json(prepared.model_dump_json())
        assert payload.input.history == []
        info = prepared_evaluation.prepare_run_snapshot(payload, ServicePrincipal(user, tenant))
        assert payload.debug is True and info.conversation_id is None and "conversation_id" not in payload.model_dump()
    elif kind == "a2a":
        lookup = mocker.patch(
            "management.db.agent.repository.search_agent_info_by_agent_id",
            return_value={"allow_chat_metadata": True},
        )
        request = AgentRequest(
            agent_id=7, version_no=2, query="hello", is_debug=True, metadata={"ticket": "42"},
            history=[
                {"role": "system", "content": "ignored client history"},
                {"role": "user", "content": "earlier"},
                {"role": "tool", "content": "ignored tool result"},
                {"role": "assistant", "content": "answer"},
            ],
        )
        prepared = await evaluation_snapshot.prepare_a2a_snapshot(request, user, tenant)
        lookup.assert_called_once_with(7, tenant, 2)
        payload = PreparedEphemeralRun.model_validate_json(prepared.model_dump_json())
        info = prepared_evaluation.prepare_run_snapshot(payload, ServicePrincipal(user, tenant))
        assert "conversation_id" not in payload.model_dump()
        assert info.conversation_id is None and info.workspace_run_id == payload.run_id
        assert info.runtime_metadata == {"ticket": "42"}
        assert [(item.role, item.content) for item in payload.input.history] == [
            ("user", "earlier"), ("assistant", "answer"),
        ]
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
        if debug_planning:
            get_redis.assert_not_called()
            assert info.redis_client is None
        else:
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
            lookup_override.assert_called_once_with(7, 0 if debug_planning else 2, "tenant-a")
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
    resolve_scope = mocker.patch.object(evaluation_snapshot, "prepare_native_knowledge")
    compile_run = mocker.patch.object(run, "create_agent_run_info")
    reference = AgentRunReference(conversation_id=42, run_id="a" * 32)
    request = AgentRequest(query="hello", agent_id=7, conversation_id=42, enable_automation_tool=False)

    with pytest.raises(ForbiddenError):
        await evaluation_snapshot.prepare_conversation_snapshot(request, reference, "actor", "foreign")
    read.assert_called_once_with(42, user_id="actor", tenant_id="foreign")
    resolve_scope.assert_not_called()
    compile_run.assert_not_called()


@pytest.mark.asyncio
async def test_prepared_conversation_preserves_memory_without_knowledge_scope(mocker):
    mocker.patch.object(evaluation_snapshot, "get_conversation", return_value={})
    memory = mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=True)
    compile_run = mocker.patch.object(run, "create_agent_run_info")
    reference = AgentRunReference(conversation_id=42, run_id="a" * 32)
    request = AgentRequest(query="hello", agent_id=7, conversation_id=42, enable_automation_tool=False)

    assert await evaluation_snapshot.prepare_conversation_snapshot(
        request, reference, "actor", "tenant",
    ) is compile_run.return_value
    memory.assert_called_once_with("actor")
    assert compile_run.await_args.kwargs["allow_memory_search"] is True
    assert compile_run.await_args.kwargs["prepared_conversation"].memory_enabled is True


@pytest.mark.asyncio
async def test_prepared_conversation_reauthorizes_saved_knowledge_before_compilation(mocker):
    from management.services.knowledge_base import scope

    saved = {"local": {"mode": "override", "knowledge_ids": ["7", "8"]}, "aidp": {"mode": "disabled"}}
    mocker.patch.object(evaluation_snapshot, "get_conversation", return_value={"knowledge_scope": saved})
    mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=False)
    tree = mocker.patch.object(scope, "snapshot_runtime_knowledge_tree", return_value=[{
        "agent_id": 7, "version_no": 3, "agent_name": "root",
        "tools": [{"class_name": "KnowledgeBaseSearchTool", "name": "knowledge_base_search", "source": "local"}],
    }])
    mocker.patch.object(scope, "get_knowledge_info_by_ids_and_tenant", return_value=[
        {"knowledge_id": 7, "index_name": "kb-allowed", "knowledge_name": "Allowed"},
        {"knowledge_id": 8, "index_name": "kb-revoked", "knowledge_name": "Revoked"},
    ])
    permissions = mocker.patch.object(scope.ElasticSearchService, "filter_accessible_indices", return_value=["kb-allowed"])
    compile_run = mocker.patch.object(run, "create_agent_run_info")
    reference = AgentRunReference(conversation_id=42, run_id="a" * 32)
    request = AgentRequest(query="hello", agent_id=7, version_no=3, conversation_id=42, enable_automation_tool=False)

    assert await evaluation_snapshot.prepare_conversation_snapshot(
        request, reference, "actor", "tenant",
    ) is compile_run.return_value
    tree.assert_called_once_with(7, "tenant", 3)
    permissions.assert_called_once_with(["kb-allowed", "kb-revoked"], user_id="actor", tenant_id="tenant")
    options = compile_run.await_args.kwargs
    assert options["prepared_conversation"].native_knowledge is True
    assert options["override_version_no"] == 3
    assert options["authorized_knowledge_tools"] == {(7, 3): {"knowledge_base_search": {"index_names": ["kb-allowed"]}}}
    assert options["runtime_knowledge_context"]["scope"]["local_display_names"] == ["Allowed"]


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
@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize("correlation_id", [None, 42])
@pytest.mark.parametrize(("version", "member_group", "permission", "allowed"), [
    (0, 9, "EDIT", True),
    (0, 8, "EDIT", False),
    (0, 9, "READ_ONLY", False),
    (2, 9, "READ_ONLY", True),
])
async def test_debug_snapshot_uses_the_tenant_group_and_version_before_compilation(
    mocker, version, member_group, permission, allowed, scoped, correlation_id,
):
    from contracts.errors.exceptions import ForbiddenError
    from management.services.agent import authorization
    from test.backend.app.test_agentos_prepared_evaluation import evaluation_payload

    draft = {"tenant_id": "tenant-a", "created_by": "someone-else", "group_ids": "9", "ingroup_permission": permission}
    read = mocker.patch.object(authorization, "search_agent_info_by_agent_id", return_value=draft)
    mocker.patch.object(authorization, "get_user_role_by_tenant", return_value="MEMBER")
    groups = mocker.patch.object(authorization, "query_group_ids_by_user_in_tenant", return_value=[member_group])
    memory = mocker.patch.object(evaluation_snapshot, "get_memory_switch", return_value=True)
    conversation = mocker.patch.object(evaluation_snapshot, "get_conversation")
    mocker.patch("management.services.model.run_controls.preflight_turn_controls")
    fields = evaluation_payload()
    fields["resource"]["version_no"] = version
    compile_run = mocker.patch.object(run, "create_agent_run_info", return_value=PreparedEvaluationRun.model_validate(fields))
    from management.services.knowledge_base import scope

    tree = mocker.patch.object(scope, "snapshot_runtime_knowledge_tree", return_value=[
        {"agent_id": 7, "version_no": version, "agent_name": "root", "tools": []},
    ])
    result = ResolvedKnowledgeScope(
        desired_scope={}, tool_params=ToolParamsRequest(agents={}),
        warnings=[{"code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE", "source": "local", "count": 1}],
    )
    resolve = mocker.patch.object(scope, "resolve_knowledge_scope", return_value=result)
    request = AgentRequest(
        agent_id=7, is_debug=True, query="hello", version_no=version if version else None,
        conversation_id=correlation_id,
        generation_config={"temperature": 0.4},
        knowledge_scope={"local": {"mode": "disabled"}, "aidp": {"mode": "disabled"}} if scoped else None,
    )
    if allowed:
        prepared = await evaluation_snapshot.prepare_debug_snapshot(
            request, "actor", "tenant-a", language="en", timezone="Asia/Shanghai",
        )
        assert prepared is not None
        snapshot = prepared.payload
        assert snapshot.debug is True and snapshot.resource.version_no == version
        assert "conversation_id" not in snapshot.model_dump()
        options = compile_run.await_args.kwargs
        assert "conversation_id" not in options
        assert options["override_version_no"] == version and options["is_debug"]
        assert options["turn_generation"].model_dump() == {"settings": {"temperature": 0.4}}
        assert options["allow_memory_search"] is False and options["enable_automation_tool"] is False
        if scoped:
            tree.assert_called_once_with(7, "tenant-a", version)
            resolve.assert_called_once_with(
                request.knowledge_scope, 7, "tenant-a", "actor", version, True, None,
                runtime_agent_tree=tree.return_value,
            )
            assert prepared.knowledge is result and snapshot.native_knowledge is True
            assert options["authorized_knowledge_tools"] == {(7, version): {}}
            assert options["tool_params"] is result.tool_params
            assert "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE" not in snapshot.model_dump_json()
        else:
            assert prepared.knowledge is None and "native_knowledge" not in snapshot.model_dump_json()
    else:
        with pytest.raises(ForbiddenError):
            await evaluation_snapshot.prepare_debug_snapshot(
                request, "actor", "tenant-a", language="en", timezone="Asia/Shanghai",
            )
        compile_run.assert_not_awaited()
    if not scoped or not allowed:
        tree.assert_not_called()
        resolve.assert_not_called()
    read.assert_called_once_with(7, "tenant-a", version)
    groups.assert_called_once_with("actor", "tenant-a")
    memory.assert_not_called()
    conversation.assert_not_called()
