# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from contracts.agentos import PreparedEvaluationRun
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
    mocker.patch.object(prepared_evaluation, "NEXENT_SANDBOX_DEFAULT_LEVEL", "local")

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
        sdk_agent = SimpleNamespace(observer=None, _push_file_workspace_to_sandbox=lambda: None)
        script = NexentAgent.create_builtin_tool(sdk_agent, run_script)
        assert "skill-script-output" in script.forward("summarize", "scripts/demo.py")
        assert "not enabled" in script.forward("another-skill", "scripts/demo.py").lower()
        assert Path(guide.params["local_skills_dir"]).is_relative_to(info.workspace_path)
        (directory / "SKILL.md").write_text("changed after validation", encoding="utf-8")
        guide_tool = NexentAgent.create_builtin_tool(None, guide)
        config_tool = NexentAgent.create_builtin_tool(None, config)
        assert "skill guide" in guide_tool.forward("summarize")
        assert "not authorized" in guide_tool.forward("another-skill").lower()
        assert json.loads(config_tool.forward("summarize")) == {"keep": True, "value": "tenant-secret-value"}
        assert "not authorized" in config_tool.forward("another-skill").lower()
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
        workspaces.append(Path(info.workspace_path) / ".evaluation-skills")
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
