# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Validate which compiled settings can cross the signed snapshot boundary."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from contracts.agent import AgentRequest
from contracts.agentos import EvaluationAnalysisTool, EvaluationFileTool, EvaluationSkillTool, PreparedMemorySearch
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, ValidationError
from contracts.knowledge import ResolvedKnowledgeScope
from contracts.tool import ToolParamsRequest
from management.services.agent.preparation import evaluation_snapshot as snapshot
from management.services.agent.preparation import run as preparation
from management.services.knowledge_base import scope
from nexent.core.agents.contracts.config import AgentConfig, ModelConfig, ToolConfig


@pytest.mark.parametrize("warning,explicit", [(False, False), (False, True), (True, True)])
def test_native_scope_freezes_only_the_requested_owned_tree(mocker, warning, explicit):
    selection = {"local": {"mode": "disabled"}}
    request = AgentRequest(query="question", agent_id=7, knowledge_scope=selection if explicit else None)
    version = mocker.patch.object(scope, "resolve_root_version", return_value=3)
    nodes = [{"agent_id": 7, "version_no": 3, "agent_name": "root"}]
    tree = mocker.patch.object(scope, "snapshot_runtime_knowledge_tree", return_value=nodes)
    resolved = ResolvedKnowledgeScope(
        desired_scope=selection, tool_params=ToolParamsRequest(),
        warnings=[{"code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE", "source": "local"}] if warning else [],
        managed_tool_overrides={"root": {"knowledge_base_search": {"top_k": 3}}},
    )
    resolve = mocker.patch.object(scope, "resolve_knowledge_scope", return_value=resolved)
    conversation = {"knowledge_scope": selection}
    if warning:
        with pytest.raises(ValidationError, match="unavailable or inaccessible: local"):
            snapshot.prepare_native_knowledge(request, conversation, "actor", "tenant")
    else:
        out = snapshot.prepare_native_knowledge(request, conversation, "actor", "tenant")
        assert out.root_version == 3
        assert out.resolution is resolved
        assert out.authorized_tools == {(7, 3): {"knowledge_base_search": {"top_k": 3}}}
    version.assert_called_once_with(7, "tenant", None, is_debug=False)
    tree.assert_called_once_with(7, "tenant", 3)
    assert resolve.call_args.args[1:6] == (7, "tenant", "actor", 3, False)
    assert resolve.call_args.kwargs == {"runtime_agent_tree": nodes}


@pytest.mark.parametrize("malformed", ["arguments", "result", "scope", "incomplete"])
def test_memory_search_export_rejects_unowned_or_inconsistent_observer_events(malformed):
    events = PreparedMemorySearch(query="question", result="Found 1 memory").observer_events()
    allow = True
    if malformed == "arguments":
        events[0]["tool_arguments"] = "question"
    elif malformed == "result":
        events[1]["tool_name"] = "different"
    elif malformed == "scope":
        allow = False
    else:
        events.pop()
    with pytest.raises(ValueError, match="Invalid prepared Memory search|Unsupported prepared resource"):
        snapshot._export_memory_search(SimpleNamespace(pre_run_tool_events=events), allow)


@pytest.mark.parametrize("params,metadata", [
    ({"workspace_path": "/request-workspace"}, None),
    ({"unexpected": "value"}, None),
    (None, {"unexpected": "value"}),
])
def test_file_binding_exports_description_but_never_request_local_state(params, metadata):
    kind = EvaluationFileTool.DOWNLOAD
    tool = ToolConfig(name=kind.value, class_name=kind.class_name, source="builtin", description="Download")
    tool = tool.model_copy(update={"params": params, "metadata": metadata})
    if params and "workspace_path" in params:
        binding = snapshot._file_tool_binding(tool)
        assert binding.tool_id == kind.value
        assert binding.parameters == {"description": "Download", "description_zh": None, "inputs": None, "output_type": None}
    else:
        assert snapshot._file_tool_binding(tool) is None


def test_analysis_binding_never_accepts_a_different_source():
    tool = ToolConfig(name="analyze", class_name=EvaluationAnalysisTool.IMAGE.class_name, source="mcp")
    with pytest.raises(ValueError, match="Unsupported analysis tool configuration"):
        snapshot._export_analysis_binding(tool)


@pytest.mark.parametrize("case", ["wrong-revision", "unknown", "default", "default-foreign", "unsupported"])
def test_legacy_model_export_does_not_rebind_a_frozen_or_foreign_outlet(mocker, case):
    alias = "main_model" if case.startswith("default") else "configured"
    model = ModelConfig(cite_name=alias, model_name="chat", url="https://model.example/v1")
    record = {"model_id": 11, "tenant_id": "tenant", "model_type": "llm", "delete_flag": "N"}
    rows = [record] if case in {"wrong-revision", "unsupported"} else []
    mocker.patch.object(snapshot, "get_model_records", return_value=rows)
    mocker.patch.object(snapshot, "model_record_revision", return_value="current")
    mocker.patch.object(snapshot, "normalize_model_revision", side_effect=lambda value: value)
    read_default = mocker.patch.object(snapshot.tenant_config_manager, "get_model_config", return_value=record)
    create_default = mocker.patch.object(snapshot, "create_tenant_default_model_config", return_value=model)
    if case == "default-foreign":
        record["tenant_id"] = "another-tenant"
    fixture = dict(alias=alias, models=[model], tenant_id="tenant", resource=SimpleNamespace(agent_id=7, version_no=3),
                   agent_model_overrides={})
    if case == "wrong-revision":
        with pytest.raises(HTTPException) as exc:
            snapshot._export_model(**fixture, catalog_model_versions={alias: (11, "stale")})
        assert exc.value.status_code == 409
        assert exc.value.detail == {"code": "MODEL_REVISION_MISMATCH"}
    elif case == "default":
        binding = snapshot._export_model(**fixture)
        assert (binding.model_id, binding.alias, binding.revision, binding.tenant_default_profile) == (
            11, alias, "current", "standard",
        )
        create_default.assert_called_once_with(record, alias, include_logprobs=False)
    elif case == "default-foreign":
        with pytest.raises(ValueError, match="Tenant default LLM is unavailable"):
            snapshot._export_model(**fixture)
        create_default.assert_not_called()
    elif case == "unsupported":
        configured = model.model_copy(update={"url": "https://another.example"})
        mocker.patch.object(snapshot, "create_model_config_from_record", return_value=configured)
        with pytest.raises(ValueError, match="Unsupported evaluation model override"):
            snapshot._export_model(**fixture)
    else:
        with pytest.raises(ValueError, match="unambiguous model binding"):
            snapshot._export_model(**fixture)
    if case.startswith("default"):
        read_default.assert_called_once()
    else:
        read_default.assert_not_called()


def test_snapshot_rejects_incomplete_planning_and_unapproved_memory_tools():
    resource = AgentConfig(
        agent_id=7, version_no=3, name="Agent", description="", model_name="llm", enable_planning=True, tools=[],
    )
    with pytest.raises(ValueError, match="Unsupported prepared planning scope"):
        snapshot._export_resource(resource, {}, "tenant", "en", None, {}, allow_public_tools=True)
    resource.enable_planning = False
    resource.tools = [snapshot.build_store_memory_tool(None)]
    with pytest.raises(ValueError, match="Unsupported evaluation tool"):
        snapshot._export_resource(resource, {}, "tenant", "en", None, {}, allow_memory=False)


@pytest.mark.parametrize("mode", ["persisted", "draft", "denied", "invalid", "unsupported"])
async def test_a2a_preparation_validates_metadata_before_compiling_published_agent(mocker, mode):
    request = AgentRequest(
        query="question", agent_id=7, version_no=0 if mode == "draft" else 2,
        conversation_id=42 if mode == "persisted" else None, is_debug=True,
        metadata={"weight": float("inf")} if mode == "invalid" else {"purpose": "test"},
    )
    policy = mocker.patch.object(snapshot, "run_blocking", return_value={"allow_chat_metadata": mode != "denied"})
    compile_run = mocker.patch.object(preparation, "create_agent_run_info", return_value=None)
    if mode in {"persisted", "draft"}:
        with pytest.raises(ValidationError, match="requires an ephemeral request"):
            await snapshot.prepare_a2a_snapshot(request, "actor", "tenant")
        policy.assert_not_awaited()
    elif mode in {"denied", "invalid"}:
        with pytest.raises(AppException) as exc:
            await snapshot.prepare_a2a_snapshot(request, "actor", "tenant")
        assert exc.value.error_code == (
            ErrorCode.CHAT_METADATA_INVALID if mode == "invalid" else ErrorCode.CHAT_METADATA_NOT_ALLOWED
        )
        assert policy.await_count == (mode == "denied")
    else:
        assert await snapshot.prepare_a2a_snapshot(request, "actor", "tenant") is None
        assert compile_run.await_args.kwargs["override_version_no"] == 2
        assert compile_run.await_args.kwargs["allow_memory_search"] is False
        assert compile_run.await_args.kwargs["enable_automation_tool"] is False
    if mode != "unsupported":
        compile_run.assert_not_awaited()


def test_conversation_snapshot_ignores_malformed_legacy_attachment_json(mocker):
    validate = mocker.patch.object(snapshot, "validate_attachment_references")
    raw = {
        "conversation_turns": [
            {"user_message": "question", "assistant_final_answer": "answer",
             "user_message_id": 1, "assistant_message_id": 2, "attachments": "not-json"},
            {"user_message": "next", "assistant_final_answer": "done",
             "user_message_id": 3, "assistant_message_id": 4, "attachments": "{}"},
        ],
    }
    history = snapshot._prepare_conversation_history(raw, "actor", "tenant")
    assert [item.user_message for item in history.conversation_turns] == ["question", "next"]
    assert [item.attachment_refs for item in history.conversation_turns] == [[], []]
    validate.assert_called_once_with([], "actor", "tenant")


@pytest.mark.parametrize("case", ["incomplete", "duplicate-config", "tool-drift"])
def test_snapshot_rejects_incomplete_or_ambiguous_skill_bindings(mocker, case):
    tools = [
        ToolConfig(name=kind.value, class_name=kind.class_name, source="builtin", usage="builtin")
        for kind in EvaluationSkillTool
    ]
    if case == "incomplete":
        tools.pop()
    row = {"name": "reports", "config": {}, "instance_id": 11}
    rows = [row, {**row, "instance_id": 12}] if case == "duplicate-config" else [row]
    read = mocker.patch.object(snapshot, "read_bound_skills", return_value=rows)
    mocker.patch.object(snapshot, "validate_skill_context")
    agent = AgentConfig(
        agent_id=7, version_no=3, name="Agent", description="", model_name="llm", tools=tools,
    )
    error = {
        "incomplete": "Incomplete evaluation skill tools",
        "duplicate-config": "Ambiguous evaluation skill bindings",
        "tool-drift": "Unsupported evaluation skill tool configuration",
    }[case]
    with pytest.raises(ValueError, match=error):
        snapshot._export_skill_bindings(agent, "tenant", [])
    if case == "incomplete":
        read.assert_not_called()
    else:
        read.assert_called_once_with(7, 3, "tenant")


def test_snapshot_accepts_builtin_authorized_skill_configuration(mocker):
    from contracts.constants import environment

    authorized = ["reports"]
    tools = [
        ToolConfig(
            name=EvaluationSkillTool.SCRIPT.value,
            class_name=EvaluationSkillTool.SCRIPT.class_name,
            source="builtin",
            usage="builtin",
            params={
                "local_skills_dir": environment.CONTAINER_SKILLS_PATH,
                "isolated_skills_root": False,
                "workspace_path": None,
                "authorized_skill_names": authorized,
            },
            metadata={"agent_id": 7, "tenant_id": "tenant", "version_no": 3},
        ),
        ToolConfig(
            name=EvaluationSkillTool.GUIDE.value,
            class_name=EvaluationSkillTool.GUIDE.class_name,
            source="builtin",
            usage="builtin",
            params={
                "local_skills_dir": environment.CONTAINER_SKILLS_PATH,
                "isolated_skills_root": False,
                "authorized_skill_names": authorized,
            },
            metadata={"agent_id": 7, "tenant_id": "tenant", "version_no": 3},
        ),
        ToolConfig(
            name=EvaluationSkillTool.CONFIG.value,
            class_name=EvaluationSkillTool.CONFIG.class_name,
            source="builtin",
            usage="builtin",
            params={
                "local_skills_dir": environment.CONTAINER_SKILLS_PATH,
                "config_overrides": {"reports": {}},
                "authorized_skill_names": authorized,
            },
            metadata={"agent_id": 7, "tenant_id": "tenant", "version_no": 3},
        ),
    ]
    mocker.patch.object(
        snapshot,
        "read_bound_skills",
        return_value=[{"name": "reports", "config": {}, "instance_id": 11}],
    )
    mocker.patch.object(snapshot, "validate_skill_context")
    mocker.patch.object(snapshot, "capture_skill_files", return_value={})
    mocker.patch.object(snapshot, "skill_execution_revision", return_value="0" * 64)
    agent = AgentConfig(
        agent_id=7, version_no=3, name="Agent", description="", model_name="llm", tools=tools,
    )

    result = snapshot._export_skill_bindings(agent, "tenant", [])

    assert [binding.instance_id for binding in result] == [11]


@pytest.mark.parametrize("case", ["sandbox", "plan", "proposal", "executor"])
def test_snapshot_never_exports_unapproved_execution_settings(case):
    tools = []
    fields = {}
    if case == "sandbox":
        fields["sandbox_policy"] = {"level": "local"}
    elif case == "plan":
        fields["enable_planning"] = True
        tools = snapshot.build_plan_tool_configs()
        tools[0] = tools[0].model_copy(update={"source": "local"})
    elif case == "proposal":
        tools = [snapshot.build_automation_proposal_tool().model_copy(update={"source": "local"})]
    else:
        tools = [snapshot.build_parallel_executor_tool_config(30).model_copy(update={"source": "builtin"})]
    agent = AgentConfig(
        agent_id=7, version_no=3, name="Agent", description="", model_name="llm", tools=tools, **fields,
    )
    with pytest.raises(ValueError, match="Unsupported"):
        snapshot._export_resource(agent, {}, "tenant", "en", None, {}, allow_public_tools=True)
