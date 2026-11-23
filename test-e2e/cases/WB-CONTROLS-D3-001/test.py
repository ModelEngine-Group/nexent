# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise Management export, Runtime lookup and SDK skill access against one catalog."""

import json
from shutil import rmtree

import pytest
from fastapi import HTTPException
from sqlalchemy import MetaData, create_engine, insert, select, text, update
from sqlalchemy.orm import Session

from contracts.agentos import AgentRunReference, EvaluationSkillTool
from contracts.constants import environment
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb import workbench_skill_records
from infrastructure.rdb.skill_execution_records import SkillInfo, SkillInstance, SkillToolRelation
from infrastructure.skill_execution import capture_skill_files
from management.services.agent import workbench
from management.services.agent.preparation.evaluation_snapshot import _export_resource
from nexent.core.agents.contracts.config import AgentConfig, ToolConfig
from nexent.core.agents.cores.smolagents.agent import NexentAgent
from runtime.agentos import prepared_evaluation, prepared_skills


pytestmark = [pytest.mark.case_id("WB-CONTROLS-D3-001"), pytest.mark.stage("D3")]
ROOT_ID, ROOT_VERSION = 7, 3
NAME = "report"
ACTOR = ServicePrincipal("viewer", "business")
DEFAULT_ID, OVERRIDE_ID = 11, 22
REFERENCE = AgentRunReference(conversation_id=42, run_id="a" * 32)


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    sources = tmp_path / "sources"
    sources.mkdir()
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS nexent")
            connection.exec_driver_sql(
                "CREATE TABLE nexent.ag_tenant_agent_t (agent_id INT, version_no INT, tenant_id TEXT, "
                "system_key TEXT, agent_origin TEXT, delete_flag TEXT, enabled BOOLEAN)"
            )
            connection.execute(text(
                "INSERT INTO nexent.ag_tenant_agent_t VALUES (7, 3, :owner, 'workbench_main', 'SYSTEM', 'N', true)"
            ), {"owner": ASSET_OWNER_TENANT_ID})
            # PostgreSQL's partial uniqueness indexes are outside this read-path fixture.
            skill_table = SkillInfo.__table__.to_metadata(MetaData())
            skill_table.indexes.clear()
            for table in (skill_table, SkillInstance.__table__, SkillToolRelation.__table__):
                table.create(connection)
            for skill_id, owner, label in (
                (DEFAULT_ID, ASSET_OWNER_TENANT_ID, "platform"), (OVERRIDE_ID, ACTOR.tenant_id, "tenant"),
            ):
                connection.execute(insert(SkillInfo).values(
                    skill_id=skill_id, tenant_id=owner, skill_name=NAME, skill_description=f"{label} description",
                    source="custom", created_by="other-owner", group_ids="4", ingroup_permission="READ_ONLY",
                    config_schemas=[{"name": "label", "type": "string"}], config_values={"label": f"{label} default"},
                ))
                directory = sources / owner / NAME
                directory.mkdir(parents=True)
                (directory / "SKILL.md").write_text(
                    f"---\nname: {NAME}\ndescription: Fixture\n---\n{label} guide", encoding="utf-8",
                )
                (directory / f"{label}-only.md").write_text(f"{label} reference", encoding="utf-8")
                (directory / "config").mkdir()
                (directory / "config" / "config.yaml").write_text(f"label: {label} default\n", encoding="utf-8")
            connection.execute(insert(SkillInstance).values(
                skill_instance_id=1, skill_id=DEFAULT_ID, agent_id=ROOT_ID, version_no=ROOT_VERSION,
                tenant_id=ASSET_OWNER_TENANT_ID, enabled=True, config_values={"label": "published"},
            ))
            connection.commit()

            def read_management_skill(skill_id, owner):
                with Session(connection) as session:
                    skill = session.scalar(select(SkillInfo).where(
                        SkillInfo.skill_id == skill_id, SkillInfo.tenant_id == owner, SkillInfo.delete_flag == "N",
                    ))
                    return {
                        "name": skill.skill_name, "description": skill.skill_description, "source": skill.source,
                        "created_by": skill.created_by, "group_ids": skill.group_ids,
                        "ingroup_permission": skill.ingroup_permission, "config_schemas": skill.config_schemas,
                        "config_values": skill.config_values,
                    } if skill else None

            monkeypatch.setattr(workbench_skill_records, "get_db_session", lambda: Session(connection))
            monkeypatch.setattr(workbench_skill_records, "tenant_membership_matches",
                                lambda _, user, tenant: (user, tenant) == (ACTOR.user_id, ACTOR.tenant_id))
            monkeypatch.setattr(workbench_skill_records, "get_user_role_by_tenant", lambda *args, **kwargs: ("USER",))
            monkeypatch.setattr(workbench_skill_records, "query_group_ids_by_user_in_tenant", lambda *args, **kwargs: [4])
            monkeypatch.setattr(workbench.skill_db, "get_skill_by_id", read_management_skill)
            monkeypatch.setattr(workbench, "_get_user_role", lambda _: "USER")
            monkeypatch.setattr(workbench, "query_group_ids_by_user", lambda _: [4])
            monkeypatch.setattr(workbench, "_capture_skill_file_snapshot",
                                lambda name, owner: tuple(capture_skill_files(owner, name).items()))
            monkeypatch.setattr(environment, "CONTAINER_SKILLS_PATH", str(sources))
            monkeypatch.setattr(environment, "JWT_SECRET", "workbench-local-fixture-key")
            yield connection
    finally:
        engine.dispose()
        rmtree(sources)


def _snapshot(mounts):
    skills = workbench._resolve_skill_mounts(
        tuple({"skill_id": skill_id, "config_values": values} for skill_id, values in mounts.items()),
        ACTOR.tenant_id, ({"skill_id": DEFAULT_ID, "config_values": {"label": "published"}},),
        user_id=ACTOR.user_id, published_tenant_id=ASSET_OWNER_TENANT_ID,
    )
    metadata = {"agent_id": ROOT_ID, "version_no": ROOT_VERSION, "tenant_id": ACTOR.tenant_id}
    file_params = {"local_skills_dir": environment.CONTAINER_SKILLS_PATH, "authorized_skill_names": [NAME]}
    params = {
        EvaluationSkillTool.SCRIPT: {**file_params, "isolated_skills_root": False},
        EvaluationSkillTool.GUIDE: {**file_params, "isolated_skills_root": False},
        EvaluationSkillTool.CONFIG: {**file_params, "config_overrides": {NAME: dict(skills[0].config_values)}},
    }
    agent = AgentConfig(
        agent_id=ROOT_ID, version_no=ROOT_VERSION, origin="SYSTEM", name="workbench", description="", model_name="fixture",
        tools=[ToolConfig(name=tool.value, class_name=tool.class_name, params=tool_params, source="builtin",
                          usage="builtin", metadata=metadata) for tool, tool_params in params.items()],
    )
    return _export_resource(agent, {}, ACTOR.tenant_id, "en", None, {}, workbench_skills=skills)


def _materialize(snapshot, workspace):
    return prepared_skills.materialize_skill_tools(
        snapshot, ACTOR, workspace, public_reference=REFERENCE, workbench_version=1,
    )


@pytest.mark.parametrize(("mounted", "expected_id", "owner", "label", "config"), [
    (False, DEFAULT_ID, ASSET_OWNER_TENANT_ID, "platform", "published"),
    (True, OVERRIDE_ID, ACTOR.tenant_id, "tenant", "runtime"),
])
def test_workbench_skill_snapshot(catalog, monkeypatch, tmp_path, mounted, expected_id, owner, label, config):
    mounts = {OVERRIDE_ID: {"label": "runtime"}} if mounted else {}
    monkeypatch.setattr(prepared_skills, "fetch_workbench_skill_mounts", lambda *_: mounts)
    snapshot = _snapshot(mounts)
    assert [ref.skill_id for ref in snapshot.workbench_skill_refs] == [expected_id]
    workspace = str(tmp_path / "runs" / ACTOR.user_id / REFERENCE.run_id)
    before = {tenant: capture_skill_files(tenant, NAME) for tenant in (ACTOR.tenant_id, ASSET_OWNER_TENANT_ID)}
    try:
        tools, rows = _materialize(snapshot, workspace)
        assert [(row["skill_id"], row["owner_tenant_id"]) for row in rows] == [(expected_id, owner)]
        guide = NexentAgent.create_builtin_tool(None, tools["read_skill_md"])
        assert f"{label} guide" in guide.forward(NAME)
        shadowed = "platform" if mounted else "tenant"
        assert f"{shadowed} guide" not in guide.forward(NAME)
        stage = prepared_skills.skill_stage_path(workspace)
        assert not list(stage.rglob(f"{shadowed}-only.md"))
        reader = NexentAgent.create_builtin_tool(None, tools["read_skill_config"])
        assert json.loads(reader.forward(NAME)) == {"label": config}
    finally:
        prepared_evaluation._remove_skill_files(workspace)
    assert not stage.exists()
    assert before == {tenant: capture_skill_files(tenant, NAME) for tenant in before}


@pytest.mark.parametrize(("change", "status", "code"), [
    ("file", 409, "AGENTOS_SKILL_REVISION_MISMATCH"),
    ("visibility", 404, "AGENTOS_SKILL_NOT_FOUND"),
    ("root", 404, "AGENTOS_SKILL_NOT_FOUND"),
    ("unbound_platform", 404, "AGENTOS_SKILL_NOT_FOUND"),
])
def test_workbench_skill_snapshot_rejects_changes(catalog, monkeypatch, tmp_path, change, status, code):
    mounts = {OVERRIDE_ID: {}} if change == "visibility" else {}
    monkeypatch.setattr(prepared_skills, "fetch_workbench_skill_mounts", lambda *_: mounts)
    snapshot = _snapshot(mounts)
    if change == "file":
        (tmp_path / "sources" / ASSET_OWNER_TENANT_ID / NAME / "SKILL.md").write_text("drift", encoding="utf-8")
    if change == "visibility":
        catalog.execute(update(SkillInfo).where(SkillInfo.skill_id == OVERRIDE_ID).values(ingroup_permission="PRIVATE"))
    if change == "root":
        catalog.execute(text("UPDATE nexent.ag_tenant_agent_t SET delete_flag = 'Y'"))
    if change == "unbound_platform":
        catalog.execute(insert(SkillInfo).values(
            skill_id=33, tenant_id=ASSET_OWNER_TENANT_ID, skill_name="unbound", source="official",
        ))
        mounts[33] = {}
    catalog.commit()
    if change == "unbound_platform":
        assert workbench_skill_records.read_workbench_skill_rows(ROOT_ID, ROOT_VERSION, ACTOR, mounts) == {}
    workspace = str(tmp_path / "runs" / ACTOR.user_id / REFERENCE.run_id)
    try:
        with pytest.raises(HTTPException) as exc:
            _materialize(snapshot, workspace)
        assert (exc.value.status_code, exc.value.detail["code"]) == (status, code)
    finally:
        prepared_evaluation._remove_skill_files(workspace)
