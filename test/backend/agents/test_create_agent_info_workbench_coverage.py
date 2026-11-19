# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace
import sys
import types

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from contracts.agent import AgentRequest
from contracts.agentos import AgentResource, EvaluationSkillTool
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure import skill_execution
from infrastructure.skill_execution import capture_skill_files, skill_execution_revision
from runtime.agentos import prepared_skills

from test.backend.agents import test_create_agent_info as legacy


WorkbenchError = legacy.WorkbenchError


import management.services.agent.preparation.compiler as preparation_compiler
import management.services.agent.resource_resolver as resource_resolver
import management.services.agent.preparation.run as run_preparation
import management.services.agent.preparation.tools as tool_preparation

@pytest.fixture
def skill_bundle(monkeypatch, tmp_path):
    root = tmp_path / "catalog"
    source = root / "tenant-a" / "demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_bytes(b"# Demo")
    (source / "scripts").mkdir()
    (source / "scripts" / "main.py").write_bytes(b"print('ok')")
    monkeypatch.setattr(skill_execution.environment, "CONTAINER_SKILLS_PATH", str(root))
    monkeypatch.setattr(skill_execution.environment, "JWT_SECRET", "fixture-skill-revision-key")
    row = {"instance_id": 53, "name": "demo", "description": "Demo", "config": {}, "tool_ids": []}
    monkeypatch.setattr(prepared_skills, "read_bound_skills", lambda *_: [row])
    revision = skill_execution_revision("tenant-a", 7, 3, row, capture_skill_files("tenant-a", "demo"))
    resource = AgentResource.model_validate({
        "agent_id": 7, "version_no": 3, "name": "agent", "description": "", "prompt_templates": {},
        "skill_refs": [{"instance_id": 53, "revision": revision}],
        "tools": [{"tool_id": tool.value, "version": "1"} for tool in EvaluationSkillTool],
    })
    workspace = tmp_path / "runs" / "user-a" / "fixture"
    stage = tmp_path / "stage" / "fixture"
    monkeypatch.setattr(prepared_skills, "skill_stage_path", lambda *_args, **_kwargs: stage)
    return resource, row, source, workspace


def test_materialize_runtime_skill_snapshot_writes_verified_files(skill_bundle):
    resource, _row, _source, workspace = skill_bundle
    tools, verified = prepared_skills.materialize_skill_tools(
        resource, ServicePrincipal("user-a", "tenant-a"), str(workspace),
    )

    assert verified == []
    stage_root = Path(tools["read_skill_md"].params["local_skills_dir"])
    assert (stage_root / "tenant-a" / "demo" / "SKILL.md").read_bytes() == b"# Demo"
    assert (stage_root / "tenant-a" / "demo" / "scripts" / "main.py").read_bytes() == b"print('ok')"
    assert not workspace.exists()
    assert tools["read_skill_md"].params["authorized_skill_names"] == ["demo"]


@pytest.mark.parametrize("invalid", ["tenant", "name", "missing-guide", "changed-file"])
def test_materialize_runtime_skill_snapshot_rejects_invalid_or_changed_source(skill_bundle, invalid):
    resource, row, source, workspace = skill_bundle
    tenant = "tenant-a"
    if invalid == "tenant":
        tenant = "tenant-b"
    elif invalid == "name":
        row["name"] = ""
    elif invalid == "missing-guide":
        (source / "SKILL.md").unlink()
    else:
        (source / "scripts" / "main.py").write_bytes(b"changed")

    with pytest.raises(HTTPException) as failure:
        prepared_skills.materialize_skill_tools(resource, ServicePrincipal("user-a", tenant), str(workspace))

    assert failure.value.status_code == 409
    assert failure.value.detail == {"code": "AGENTOS_SKILL_REVISION_MISMATCH"}
    assert not workspace.exists()


@pytest.mark.asyncio
async def test_create_agent_run_info_forwards_all_workbench_runtime_overrides(monkeypatch):
    from management.services.agent.preparation import evaluation_snapshot
    from management.services.model import run_controls

    frozen_snapshot = [{"name": "demo", "files": [("SKILL.md", b"Demo")]}]
    agent_config = MagicMock(model_name="model", agent_core="smolagents", worker_agents=[])
    create_config = AsyncMock(return_value=agent_config)
    export = MagicMock()
    monkeypatch.setattr(evaluation_snapshot, "compile_snapshot", export)
    monkeypatch.setattr(run_controls, "validate_selected_record", MagicMock())
    monkeypatch.setattr(run_preparation, "get_model_by_model_id", MagicMock())
    monkeypatch.setattr(run_preparation, "create_model_config_list", AsyncMock(return_value=[]))
    monkeypatch.setattr(run_preparation, "create_agent_config", create_config)
    monkeypatch.setattr(run_preparation, "query_current_version_no", lambda **_kwargs: 3)
    monkeypatch.setattr(run_preparation, "_ensure_agent_reasoning_snapshot", MagicMock())
    monkeypatch.setattr(run_preparation, "search_agent_info_by_agent_id", MagicMock(return_value={}))

    result = await run_preparation.create_agent_run_info(
        agent_id=7, minio_files=[], query="hello", history=[], tenant_id="tenant-a", user_id="user-a",
        override_model_id=9, requested_output_tokens=2048, context_policy={"mode": "strict"},
        runtime_knowledge_context={"policy": "knowledge"}, runtime_skill_snapshot=frozen_snapshot,
        runtime_knowledge_tools=[{"name": "search"}], runtime_sub_agent_mounts=[{"agent_id": 8, "version_no": 2}],
    )

    assert result is export.return_value
    kwargs = create_config.await_args.kwargs
    assert kwargs["runtime_knowledge_context"] == {"policy": "knowledge"}
    assert kwargs["runtime_skill_snapshot"] is frozen_snapshot
    assert kwargs["override_model_id"] == 9
    assert kwargs["request_requested_output_tokens"] == 2048
    assert kwargs["request_context_policy"] == {"mode": "strict"}
    assert kwargs["runtime_knowledge_tools"] == [{"name": "search"}]
    assert kwargs["runtime_sub_agent_mounts"] == [{"agent_id": 8, "version_no": 2}]
    assert kwargs["portable_evaluation"] is True
    assert export.call_args.kwargs["run_input"].query == "hello"


def test_get_skills_for_template_uses_runtime_snapshot_without_repository_lookup():
    result = resource_resolver._get_skills_for_template(
        agent_id=7,
        tenant_id="tenant-a",
        version_no=3,
        runtime_skill_snapshot=[{"name": "demo", "description": "Demo skill"}],
    )

    assert result == [{"name": "demo", "description": "Demo skill"}]


def test_skill_script_tools_remove_mutating_tool_for_runtime_snapshot(monkeypatch):
    class Tool:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    monkeypatch.setattr(tool_preparation, "ToolConfig", Tool)
    skill_service = types.ModuleType("management.services.skill.service")
    skill_service.SkillService = SimpleNamespace(resolve_effective_config=lambda **kwargs: {"format": "pdf"})
    monkeypatch.setitem(sys.modules, "management.services.skill.service", skill_service)
    tools = tool_preparation._get_skill_script_tools(
        agent_id=7,
        tenant_id="tenant-a",
        version_no=3,
        runtime_skill_snapshot=[
            {
                "name": "demo",
                "config_values": {"format": "pdf"},
                "_snapshot_root": "/snapshot",
            }
        ],
    )

    assert "WriteSkillFileTool" not in {tool.class_name for tool in tools}
    assert len(tools) == 5


def test_public_workbench_request_rejects_legacy_generation_overlay():
    with pytest.raises(ValidationError, match="model_parameter_preferences"):
        AgentRequest(query="hello", generation_config={"temperature": 0.4}, is_debug=True)


@pytest.mark.asyncio
async def test_create_agent_config_filters_root_knowledge_tools_before_cycle_check(
    monkeypatch,
):
    root_override = SimpleNamespace(
        tools={"knowledge_search": {"index": "old"}, "custom": {"value": 1}}
    )
    copied_params = SimpleNamespace(agents={"root": root_override})
    normalized = SimpleNamespace(
        agents={"root": root_override},
        model_copy=MagicMock(return_value=copied_params),
    )
    monkeypatch.setattr(
        preparation_compiler, "_normalize_tool_params_request", lambda _params: normalized
    )
    monkeypatch.setattr(
        preparation_compiler,
        "search_agent_info_by_agent_id",
        lambda **_kwargs: {"name": "root"},
    )
    monkeypatch.setattr(preparation_compiler, "query_sub_agent_relations", lambda **_kwargs: [])
    runtime_mount = types.ModuleType("management.services.knowledge_base.mount")
    runtime_mount.MANAGED_CLASSES = {"knowledge_search"}
    monkeypatch.setitem(sys.modules, "management.services.knowledge_base.mount", runtime_mount)

    with pytest.raises(WorkbenchError, match="WORKBENCH_AGENT_CYCLE"):
        await preparation_compiler.create_agent_config(
            agent_id=7,
            tenant_id="tenant-a",
            user_id="user-a",
            version_no=3,
            runtime_knowledge_context={"policy": "old"},
            runtime_knowledge_tools=[
                {"name": "knowledge_search", "class_name": "knowledge_search"}
            ],
            runtime_sub_agent_mounts=[{"agent_id": 7, "version_no": 3}],
        )

    normalized.model_copy.assert_called_once_with(deep=True)
    assert root_override.tools == {"custom": {"value": 1}}
