# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Component proof across Skill selection, snapshots, tool records and SDK reading."""

from copy import deepcopy
from pathlib import Path
from shutil import copytree, rmtree
from types import SimpleNamespace

import pytest

from contracts.agentos import EvaluationSkillTool, ToolBinding, WorkbenchSkillBinding
from contracts.constants import environment
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.skill_execution import skill_execution_revision
from management.services.agent import resource_resolver, workbench
from management.services.agent.preparation.evaluation_snapshot import _workbench_skill_row
from nexent.core.agents.cores.smolagents.agent import NexentAgent
from runtime.agentos import prepared_evaluation, prepared_skills


@pytest.mark.case_id("WB-SKILL-PRECEDENCE-D1-001")
@pytest.mark.stage("D1")
def test_effective_skill_identity_survives_component_chain(monkeypatch, tmp_path):
    rows = {
        1: dict(skill_id=1, name="analyze-image", tool_ids=[10], config_values={"region": "platform"}),
        2: dict(skill_id=2, name="analyze-image", tool_ids=[20], config_values={"region": "tenant"}),
    }
    for row in rows.values():
        row["config_schemas"] = [{"name": "region", "type": "string"}]
        row["created_by"] = "viewer"
    before = deepcopy(rows)
    tools = {
        tool_id: dict(tool_id=tool_id, name="analyze_image", class_name="AnalyzeImageTool",
                      author=owner, is_available=True, params=[{"name": "region", "default": "tool"}])
        for tool_id, owner in ((10, ASSET_OWNER_TENANT_ID), (20, "tenant"))
    }
    captured = []
    sources = tmp_path / "sources"

    def source_directory(service, name):
        directory = tmp_path / f"skill_{name}_{len(captured)}"
        copytree(sources / service.tenant_id / name, directory)
        captured.append(directory)
        return {"directory": str(directory)}

    for owner, label in ((ASSET_OWNER_TENANT_ID, "platform"), ("tenant", "tenant")):
        directory = sources / owner / "analyze-image"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: analyze-image\ndescription: Fixture\n---\n{label} guide", encoding="utf8",
        )
        (directory / f"{label}-only.md").write_text(f"{label} reference", encoding="utf8")

    monkeypatch.setattr(environment, "CONTAINER_SKILLS_PATH", str(sources))
    monkeypatch.setattr(environment, "JWT_SECRET", "workbench-precedence-fixture-key")
    monkeypatch.setattr(workbench.skill_db, "get_skill_by_id", lambda skill_id, owner: deepcopy(rows[skill_id]))
    monkeypatch.setattr(workbench, "query_tools_by_ids", lambda ids: [deepcopy(tools[i]) for i in ids])
    monkeypatch.setattr(workbench.SkillService, "load_skill_directory", source_directory)
    monkeypatch.setattr(workbench.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(workbench, "_get_user_role", lambda user: "USER")
    monkeypatch.setattr(workbench, "query_group_ids_by_user", lambda user: [])
    monkeypatch.setattr(resource_resolver, "search_tools_for_sub_agent", lambda *args, **kwargs: [])
    monkeypatch.setattr(prepared_skills, "fetch_workbench_skill_mounts", lambda *_: {})

    def execute(mounts, run, label, skill_id, tool_id, region):
        resolved = workbench._resolve_skill_mounts(
            mounts, "tenant", ({"skill_id": 1},), user_id="viewer", published_tenant_id=ASSET_OWNER_TENANT_ID,
        )
        assert [skill.skill_id for skill in resolved] == [skill_id]
        snapshot = workbench.runtime_skill_snapshot(SimpleNamespace(root_skills=resolved))
        records = resource_resolver._resolve_runtime_tool_records(7, "tenant", runtime_skill_snapshot=snapshot)
        assert [(tool["tool_id"], tool["name"]) for tool in records] == [(tool_id, "analyze_image")]
        assert records[0]["params"] == [{"name": "region", "default": region}]
        assert snapshot[0]["config_values"] == {"region": region}
        row = _workbench_skill_row(resolved[0])
        owner = tools[tool_id]["author"]
        monkeypatch.setattr(prepared_skills, "read_workbench_skill_rows",
                            lambda *_: {skill_id: {**row, "owner_tenant_id": owner}})
        revision = skill_execution_revision("tenant", 7, 3, row, dict(snapshot[0]["files"]))
        resource = SimpleNamespace(
            agent_id=7, version_no=3, origin="SYSTEM", evaluation_options=None, skill_refs=[],
            workbench_skill_refs=[WorkbenchSkillBinding(skill_id=skill_id, revision=revision)],
            tools=[ToolBinding(tool_id=tool.value, version="1") for tool in EvaluationSkillTool],
        )
        workspace = str(tmp_path / "runs" / "viewer" / run)
        materialized, _ = prepared_skills.materialize_skill_tools(
            resource, ServicePrincipal("viewer", "tenant"), workspace, debug_run_id="a" * 32,
        )
        guide = materialized["read_skill_md"]
        root = Path(guide.params["local_skills_dir"])
        reader = NexentAgent.create_builtin_tool(None, guide)
        assert f"{label} guide" in reader.forward("analyze-image", [])
        assert f"{label} reference" in reader.forward("analyze-image", [f"{label}-only.md"])
        assert reader.forward("not-authorized", []) == "Skill access is not authorized"
        assert sorted(p.name for p in (root / "tenant" / "analyze-image").iterdir()) == ["SKILL.md", f"{label}-only.md"]
        assert all(not source.exists() for source in captured)
        return root

    try:
        first = execute(
            ({"skill_id": 2, "config_values": {"region": "selected"}},), "selected-run", "tenant", 2, 20, "selected",
        )
        execute((), "default-run", "platform", 1, 10, "platform")
        assert "tenant guide" in (first / "tenant" / "analyze-image" / "SKILL.md").read_text(encoding="utf8")
        assert rows == before
        assert len(captured) == 2
    finally:
        for run in ("selected-run", "default-run"):
            prepared_evaluation._remove_skill_files(str(tmp_path / "runs" / "viewer" / run))
        rmtree(sources)
