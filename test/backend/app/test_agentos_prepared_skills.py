# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from contracts.agentos import AgentRunReference, PreparedEvaluationRun
from infrastructure.agent_model_config import create_model_config_from_record
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.preparation import evaluation_snapshot
from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from runtime.agentos import prepared_evaluation

from test.backend.app.test_agentos_prepared_evaluation import model_record


@pytest.fixture
def skill_snapshot(mocker, tmp_path):
    from infrastructure import skill_execution
    from runtime.agentos import prepared_skills

    skills = tmp_path / "skills"
    directory = skills / "tenant-a" / "summarize"
    (directory / "config").mkdir(parents=True)
    (directory / "scripts").mkdir()
    (directory / "scripts" / "demo.py").write_text('print("skill-script-output")', encoding="utf-8")
    (directory / "SKILL.md").write_text("---\nname: summarize\ndescription: Summarize\n---\nskill guide", encoding="utf-8")
    (directory / "config" / "config.yaml").write_text("keep: true\nvalue: default", encoding="utf-8")
    mocker.patch.object(skill_execution.environment, "CONTAINER_SKILLS_PATH", str(skills))
    mocker.patch.object(skill_execution.environment, "JWT_SECRET", "evaluation-skill-signing-key")
    mocker.patch.object(prepared_evaluation, "AGENT_WORKSPACE_ROOT", str(tmp_path / "runs"))
    mocker.patch("contracts.constants.environment.NEXENT_SANDBOX_DEFAULT_LEVEL", "local")

    row = {"instance_id": 23, "name": "summarize", "description": "Summarize",
           "config": {"value": "tenant-secret-value"}}
    mocker.patch.object(evaluation_snapshot, "read_bound_skills", return_value=[row])
    runtime_read = mocker.patch.object(prepared_skills, "read_bound_skills", return_value=[row])
    model = model_record(model_id=11)
    mocker.patch.object(evaluation_snapshot, "get_model_records", return_value=[model])
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=model)
    binding = create_model_config_from_record(model)
    metadata = {"agent_id": 7, "tenant_id": "tenant-a", "version_no": 2}
    tools = [
        ("RunSkillScriptTool", "run_skill_script", {"workspace_path": None, "authorized_skill_names": ["summarize"],
                                                   "isolated_skills_root": False}),
        ("ReadSkillMdTool", "read_skill_md", {"isolated_skills_root": False}),
        ("ReadSkillConfigTool", "read_skill_config", {"config_overrides": {"summarize": row["config"]}}),
    ]
    agent = AgentConfig(
        agent_id=7, version_no=2, name="evaluation", description="", model_name=binding.cite_name,
        context_items=[{"id": "skill:summarize", "type": "skill",
                        "content": {"name": "summarize", "description": "Summarize"}}],
        tools=[ToolConfig(
            class_name=class_name, name=name, source="builtin", usage="builtin", metadata=metadata,
            params={"local_skills_dir": str(skills), **params},
        ) for class_name, name, params in tools],
    )
    return agent, binding, directory, row, runtime_read


@pytest.mark.parametrize(("change", "status"), [
    ("none", None), ("unbound", 404), ("other_tenant", 404), ("config", 409), ("file", 409),
])
def test_evaluation_skill_snapshot_authorizes_and_pins_local_files(skill_snapshot, change, status):
    agent, binding, directory, row, runtime_read = skill_snapshot
    snapshot = evaluation_snapshot.export_snapshot(
        agent, [binding], "hello", None, tenant_id="tenant-a", conversation_id=-42, language="en",
    )
    assert snapshot is not None
    encoded = snapshot.model_dump_json()
    assert snapshot.resource.skill_refs[0].instance_id == 23
    assert "tenant-secret-value" not in encoded
    assert "skill guide" not in encoded
    assert str(directory.parent.parent) not in encoded

    actor = ServicePrincipal("user-a", "tenant-a")
    if change == "unbound":
        runtime_read.return_value = []
    elif change == "other_tenant":
        actor = ServicePrincipal("user-b", "tenant-b")
        runtime_read.return_value = []
    elif change == "config":
        row["config"] = {"value": "changed"}
    elif change == "file":
        (directory / "SKILL.md").write_text("changed", encoding="utf-8")

    payload = PreparedEvaluationRun.model_validate_json(encoded)
    if status is not None:
        with pytest.raises(HTTPException) as error:
            prepared_evaluation.prepare_evaluation_run(payload, actor)
        assert error.value.status_code == status
    else:
        info = prepared_evaluation.prepare_evaluation_run(payload, actor)
        run_script, guide, config = info.agent_config.tools
        assert run_script.params["workspace_path"] == info.workspace_path
        assert run_script.params["authorized_skill_names"] == ["summarize"]
        Path(info.workspace_path).mkdir(parents=True)
        sdk_agent = SimpleNamespace(observer=None, _push_file_workspace_to_sandbox=lambda: None)
        script = NexentAgent.create_builtin_tool(sdk_agent, run_script)
        assert "skill-script-output" in script.forward("summarize", "scripts/demo.py")
        assert "not enabled" in script.forward("another-skill", "scripts/demo.py").lower()
        assert not Path(guide.params["local_skills_dir"]).is_relative_to(Path(info.workspace_path).parent.parent)
        (directory / "SKILL.md").write_text("changed after validation", encoding="utf-8")
        guide_tool = NexentAgent.create_builtin_tool(None, guide)
        config_tool = NexentAgent.create_builtin_tool(None, config)
        assert "skill guide" in guide_tool.forward("summarize")
        assert "not authorized" in guide_tool.forward("another-skill").lower()
        assert json.loads(config_tool.forward("summarize")) == {"keep": True, "value": "tenant-secret-value"}
        assert "not authorized" in config_tool.forward("another-skill").lower()
        prepared_evaluation._remove_skill_files(info.workspace_path)
    runtime_read.assert_called_once_with(7, 2, actor.tenant_id)


def test_export_refuses_unrecognized_skill_tool_parameters(skill_snapshot):
    agent, binding, *_ = skill_snapshot
    agent.tools[1].params["local_skills_dir"] = "/wrong-source"
    assert evaluation_snapshot.export_snapshot(
        agent, [binding], "hello", None, tenant_id="tenant-a", conversation_id=-42, language="en",
    ) is None



@pytest.mark.parametrize("segment", ["../escape", "a/b", "a\\b", "C:drive", "NUL.txt"])
def test_skill_path_component_cannot_escape_tenant(segment):
    from infrastructure.skill_execution import skill_path_segment

    with pytest.raises(ValueError, match="Invalid skill path"):
        skill_path_segment(segment)


def test_skill_capture_rejects_over_budget_bundle(skill_snapshot, mocker):
    from infrastructure import skill_execution

    mocker.patch.object(skill_execution, "MAX_SKILL_BYTES", 4)
    with pytest.raises(ValueError, match="size limit"):
        skill_execution.capture_skill_files("tenant-a", "summarize")


@pytest.mark.asyncio
async def test_cancellation_during_preparation_removes_staged_skill_files(skill_snapshot, mocker):
    agent, binding, *_ = skill_snapshot
    payload = evaluation_snapshot.export_snapshot(
        agent, [binding], "hello", None, tenant_id="tenant-a", conversation_id=-42, language="en",
    )
    staged = asyncio.Event()
    finish = asyncio.Event()
    removed = asyncio.Event()
    remove = prepared_evaluation._remove_skill_files
    workspaces = []

    async def blocking(_name, prepare, *args, **_kwargs):
        info = prepare(*args)
        workspaces.append(prepared_evaluation.skill_stage_path(info.workspace_path))
        staged.set()
        await finish.wait()
        return info

    def clean(path):
        remove(path)
        removed.set()

    mocker.patch.object(prepared_evaluation, "run_blocking", blocking)
    mocker.patch.object(prepared_evaluation, "_remove_skill_files", clean)
    registry = mocker.patch.object(prepared_evaluation, "agent_run_manager")
    call = asyncio.create_task(prepared_evaluation.execute_prepared_evaluation(
        payload, ServicePrincipal("user-a", "tenant-a"),
    ))
    await asyncio.wait_for(staged.wait(), timeout=2)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    assert workspaces[0].is_dir()
    finish.set()
    await asyncio.wait_for(removed.wait(), timeout=2)
    assert not workspaces[0].exists()
    registry.register_agent_run.assert_not_called()


@pytest.mark.parametrize(("change", "status"), [
    ("none", None), ("unbound", 404), ("new_source", 409), ("config", 409),
])
def test_skill_derived_mcp_binding(skill_snapshot, mocker, change, status):
    from infrastructure.mcp_execution import build_mcp_tool
    from runtime.agentos import prepared_mcp

    agent, model, *_ = skill_snapshot
    row = {
        "tool_id": 77, "skill_instance_ids": [23], "name": "derived_lookup",
        "class_name": "derived_lookup", "origin_name": "lookup", "usage": "registry",
        "params": [{"name": "value", "default": "private-tool-config"}],
        "instance_params": {}, "description": "Derived lookup", "inputs": None, "output_type": "object",
    }
    server = {
        "mcp_id": 29, "mcp_name": "registry", "mcp_server": "https://registry.example/private",
        "authorization_token": "private-mcp-token", "custom_headers": None, "enabled": True,
    }
    agent.tools.append(build_mcp_tool(row))
    mocker.patch.object(evaluation_snapshot, "read_bound_mcp_tools", return_value=[])
    mocker.patch.object(evaluation_snapshot, "read_skill_derived_mcp_tools", return_value=[row])
    mocker.patch.object(evaluation_snapshot, "read_mcp_execution_servers", return_value=[server])
    direct = mocker.patch.object(prepared_mcp, "read_bound_mcp_tools", return_value=[])
    derived = mocker.patch.object(prepared_mcp, "read_skill_derived_mcp_tools", return_value=[row])
    mocker.patch.object(prepared_mcp, "read_mcp_execution_servers", return_value=[server])

    snapshot = evaluation_snapshot.export_snapshot(
        agent, [model], "hello", None, tenant_id="tenant-a", conversation_id=-42, language="en",
    )
    assert snapshot is not None
    binding = snapshot.resource.tools[-1]
    assert (binding.tool_id, binding.version, binding.parameters["tool_id"]) == ("mcp", "2", 77)
    encoded = snapshot.model_dump_json()
    assert "private-tool-config" not in encoded
    assert "private-mcp-token" not in encoded
    if change == "unbound":
        derived.return_value = []
    elif change == "new_source":
        row["skill_instance_ids"] = [23, 24]
    elif change == "config":
        row["params"] = [{"name": "value", "default": "changed"}]

    payload = PreparedEvaluationRun.model_validate_json(encoded)
    actor = ServicePrincipal("user-a", "tenant-a")
    if status:
        with pytest.raises(HTTPException) as error:
            prepared_evaluation.prepare_evaluation_run(payload, actor)
        assert error.value.status_code == status
    else:
        info = prepared_evaluation.prepare_evaluation_run(payload, actor)
        assert info.agent_config.tools[-1].params == {"value": "private-tool-config"}
        assert info.mcp_host[0]["allowed_tools"] == {"lookup": "derived_lookup"}
        prepared_evaluation._remove_skill_files(info.workspace_path)
    derived.assert_called_once_with(7, 2, "tenant-a", ["derived_lookup"])
    direct.assert_not_called()


def test_skill_parameter_merge_preserves_falsey_and_rejects_conflicts():
    from contracts.errors.exceptions import ValidationError
    from infrastructure.skill_execution import merge_skill_tool_parameters

    values = [("first", {"flag": False, "number": 0}), ("second", {"flag": False, "path": None})]
    assert merge_skill_tool_parameters(77, values) == {"flag": False, "number": 0, "path": None}
    with pytest.raises(ValidationError, match=r"first.*second.*77.*flag"):
        merge_skill_tool_parameters(77, [values[0], ("second", {"flag": True})])


def test_skill_staging_rejects_a_temp_root_inside_the_mounted_workspace(mocker, tmp_path):
    from runtime.agentos import prepared_skills

    mocker.patch.object(prepared_skills, "_stage_directory", SimpleNamespace(name=str(tmp_path / "temp")))
    workspace = str(tmp_path / "user-a" / "run")
    with pytest.raises(ValueError, match="outside the run workspace root"):
        prepared_skills.skill_stage_path(workspace, create=True)
    assert prepared_skills.skill_stage_path(workspace) is None


def test_prepared_skill_tools_only_enable_artifact_publication_for_conversations(monkeypatch):
    from runtime.agentos import prepared_evaluation

    calls = []

    def materialize_skills(resource, actor, path, *, publish_artifacts, public_reference, workbench_version, debug_run_id):
        calls.append(publish_artifacts)
        return {}, []

    monkeypatch.setattr(prepared_evaluation, "materialize_skill_tools", materialize_skills)
    actor = ServicePrincipal("actor", "tenant")
    from contracts.agentos import AgentResource
    from runtime.agentos.prepared_mcp import PreparedMCP

    resource = AgentResource(agent_id=1, version_no=1, name="agent", description="", prompt_templates={})
    for publish in (False, True):
        prepared_evaluation._materialize_agent(
            resource, actor, "/workspace", "run", {"llm"}, set(), PreparedMCP(actor),
            language="en", sandbox_enabled=False, root_alias="llm", publish_skill_artifacts=publish,
        )
    assert calls == [False, True]


@pytest.mark.parametrize(("change", "status"), [
    ("none", None), ("revoked", 404), ("config", 409), ("file", 409),
])
@pytest.mark.parametrize("debug", [False, True])
def test_workbench_skills_pin_the_owned_configuration(skill_snapshot, mocker, tmp_path, change, status, debug):
    from infrastructure.skill_execution import capture_skill_files
    from management.services.agent.workbench import ResolvedSkillMount
    from runtime.agentos import prepared_skills

    agent, _, directory, row, ordinary = skill_snapshot
    agent.origin = "SYSTEM"
    for tool in agent.tools:
        tool.params["authorized_skill_names"] = ["summarize"]
    catalog = {"skill_id": 53, "name": row["name"], "description": row["description"],
               "config": row["config"], "tool_ids": []}
    skill = ResolvedSkillMount(
        53, row["name"], row["description"], (), row["config"],
        files=tuple(capture_skill_files("tenant-a", row["name"]).items()),
    )
    resource = evaluation_snapshot._export_resource(
        agent, {}, "tenant-a", "en", None, {}, workbench_skills=(skill,),
    )
    assert resource.workbench_skill_refs[0].skill_id == 53
    assert not resource.skill_refs and "tenant-secret-value" not in resource.model_dump_json()
    actor = ServicePrincipal("user-a", "tenant-a")
    reference = AgentRunReference(conversation_id=42, run_id="a" * 32)
    lookup_options = {"debug_run_id": reference.run_id} if debug else {
        "public_reference": reference, "workbench_version": 3,
    }
    mounts = {53: {"value": "tenant-secret-value"}}
    fetch = mocker.patch.object(prepared_skills, "fetch_workbench_skill_mounts", return_value=mounts)
    read = mocker.patch.object(prepared_skills, "read_workbench_skill_rows", return_value={53: catalog})
    workspace = str(tmp_path / "runs" / actor.user_id / reference.run_id)
    with pytest.raises(ValueError, match="Workbench root"):
        prepared_skills.materialize_skill_tools(resource, actor, workspace)
    if change == "revoked":
        read.return_value = {}
    if change == "config":
        catalog["config"] = {"value": "changed"}
    if change == "file":
        (directory / "SKILL.md").write_text("tampered", encoding="utf-8")
    try:
        if status is None:
            tools, verified = prepared_skills.materialize_skill_tools(
                resource, actor, workspace, **lookup_options,
            )
            assert tools["read_skill_config"].params["config_overrides"] == {"summarize": row["config"]}
            assert tools["read_skill_md"].params["authorized_skill_names"] == ["summarize"]
            assert verified == [catalog]
        else:
            with pytest.raises(HTTPException) as error:
                prepared_skills.materialize_skill_tools(
                    resource, actor, workspace, **lookup_options,
                )
            assert error.value.status_code == status
        scope, principal = fetch.call_args.args
        expected = {"run_id": reference.run_id, "agent_id": 7, "agent_version": 2}
        if not debug:
            expected.update(conversation_id=42, workbench_version=3)
        assert scope.model_dump() == expected
        assert principal == actor
        read.assert_called_once_with(7, 2, actor, mounts, {53})
        ordinary.assert_not_called()
    finally:
        prepared_evaluation._remove_skill_files(workspace)
