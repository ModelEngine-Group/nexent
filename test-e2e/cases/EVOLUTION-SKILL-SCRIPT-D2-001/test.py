# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from local_auth_http import bearer, native_runtime, register, runtime, seed_membership_roles


@pytest.mark.case_id("EVOLUTION-SKILL-SCRIPT-D2-001")
@pytest.mark.stage("D2")
def test_script_feedback_http(runtime, monkeypatch, tmp_path):
    from backend.http.server.exception_handlers import register_exception_handlers
    from contracts.evolution import DevelopmentExperimentRequest
    from contracts.constants import environment
    from infrastructure.rdb.skill_execution_records import SkillInfo, SkillInstance, read_bound_skills
    from infrastructure.skill_execution import capture_skill_files, skill_execution_revision
    from nexent.core.agents.resources.replay_tools import argument_digest
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.api.evaluation.evolution import router
    from management.db.evaluation import experiments as jobs
    from management.db.evaluation.replay_cases import save_replay_case
    from management.services.evaluation import skill_script_repairs as repair
    from management.services.evaluation.experiments import snapshot_digest
    from management.thread_management import config_thread_manager
    from nexent.core.concurrency import set_default_thread_manager, clear_default_thread_manager
    from permissions.rbac import init_rbac

    identity, _, _, models = runtime
    load_system_configuration()
    login = register(identity)
    editor = login["user"]["id"]
    second = identity.post(
        "/api/user/signup",
        json={
            "email": "designer@example.com",
            "password": "Password123",
            "invite_code": "NATIVE-INVITE",
            "auto_login": True,
        },
    ).json()["data"]
    designer = second["user"]["id"]
    editor_header = bearer(login["session"]["access_token"])
    designer_header = bearer(second["session"]["access_token"])
    tenant, agent = "tenant-native", 12
    models.TableBase.metadata.create_all(db_client.engine)
    path = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with db_client.engine.begin() as conn, conn.connection.driver_connection.cursor() as cur:
        for n in (17, 18, 19, 20, 25, 28, 33, 34, 41, 43, 44, 47):
            (file,) = path.glob(f"v2.9.0_{n:03}_*.sql")
            cur.execute(file.read_text(encoding="utf-8"))
    seed_membership_roles(editor, ["DEV"])
    seed_membership_roles(designer, ["DEV"])
    init_rbac()
    with get_db_session() as session:
        for version in (0, 1):
            session.add(
                models.AgentInfo(
                    agent_id=agent,
                    version_no=version,
                    tenant_id=tenant,
                    name="intake",
                    created_by=editor,
                    updated_by=editor,
                    delete_flag="N",
                    ingroup_permission="PRIVATE",
                )
            )
            session.flush()
        session.add(SkillInfo(skill_id=8, skill_name="weekly", tenant_id=tenant, created_by=designer,
                              updated_by=designer, ingroup_permission="PRIVATE", delete_flag="N"))
        session.add(SkillInstance(skill_instance_id=4, skill_id=8, tenant_id=tenant, agent_id=agent, version_no=1,
                                  enabled=True, delete_flag="N"))
    monkeypatch.setattr(environment, "CONTAINER_SKILLS_PATH", str(tmp_path))
    path = "scripts/weekly.py"
    directory = tmp_path / tenant / "weekly"
    (directory / "scripts").mkdir(parents=True)
    (directory / "SKILL.md").write_bytes(b"Week summary")
    original = b"def summarize(value):\n    return value\n"
    (directory / path).write_bytes(original)
    row, = read_bound_skills(agent, 1, tenant)
    revision = skill_execution_revision(tenant, agent, 1, row, capture_skill_files(tenant, "weekly"))
    spec = SimpleNamespace(resource=SimpleNamespace(agent_id=agent, version_no=1,
        skill_refs=[SimpleNamespace(instance_id=4, revision=revision)]), model_dump=lambda **kw: {
        "models": {"llm": {"alias":"pilot"}}, "resource": {"model_alias":"pilot","subagents":[],"skill_revision":revision}})
    digest = snapshot_digest(spec)
    records = {}
    for params, expected, actual in [("alpha", "ALPHA", "alpha"), ("2026", "2026", "2026")]:
        args = {"skill_name":"weekly", "script_path":path, "params":params}
        rule = {"name":"run_skill_script", "min_calls":1, "max_calls":1, "arguments":args, "expected_script_stdout":expected}
        task = {"query": f"Summarize {params}", "expected":expected, "attachments":[], "family":"weekly",
                "tool_use":{"rules":[rule]}}
        case = save_replay_case(tenant, agent, 1, editor, task)
        status = "pass" if expected == actual else "fail"
        process = {"skill":argument_digest("weekly"), "path":argument_digest(path), "argv":argument_digest([params]),
                   "script":sha256(original).hexdigest(), "image":"sha256:"+"b"*64, "stdout":sha256(actual.encode()).hexdigest(),
                   "exit_code":0,"input_matches":True,"stdout_matches":status=="pass","call":1}
        records[case["case_id"]] = (case["digest"], status, process)
    ids = list(records)
    experiments = []
    for name in ("original", "repeat"):
        req = DevelopmentExperimentRequest(agent_id=agent,version_no=1,evaluator_id=1,case_ids=ids,
                                           candidate_type="baseline",request_id=name)
        plan = {"request":req.model_dump(),"cases":{str(key):v[0] for key,v in records.items()},
                "snapshots":{"base":digest},"evaluator":{"version_no":1}}
        eid = jobs.submit(tenant, editor, req, plan)
        experiments.append(eid)
        while trial := jobs.claim(eid):
            case_digest, status, process = records[trial["case_id"]]
            assert jobs.finish(trial, status, {"case_digest":case_digest,"snapshot_digest":digest,
                "tool_use":{"status":status,"issues":[],"script_evidence":[process]}})
    async def snapshot(*args):
        return spec
    monkeypatch.setattr(repair, "_snapshot", snapshot)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api")
    config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)
    try:
        with TestClient(app) as client:
            url = f"/api/agent-evolution/experiments/{experiments[0]}/skill-script-feedback"
            body = {"skill_id":8, "failure_case_id":ids[0], "protection_case_id":ids[1],
                    "repeat_experiment_id":experiments[1], "function":"summarize", "goal":"Capitalize summaries",
                    "share_script_examples":True}
            assert client.post(url,headers=designer_header,json=body).status_code == 403
            assert client.post(url,headers=editor_header,json={**body,"repeat_experiment_id":experiments[0]}).status_code == 400
            result = client.post(url,headers=editor_header,json=body)
            assert result.is_success, result.text
            fid = result.json()["data"]["feedback_id"]
            assert client.post(url,headers=editor_header,json=body).json()["data"]["feedback_id"] == fid
            url = f"/api/agent-evolution/feedback/{fid}/skill-script-draft"
            fix = {"replacement":"def summarize(value):\n    return value.upper()"}
            assert client.post(url,headers=editor_header,json=fix).status_code == 403
            draft = client.post(url,headers=designer_header,json=fix)
            assert draft.is_success, draft.text
            assert "+    return value.upper()" in draft.json()["data"]["diff"]
            import io
            from infrastructure import skill_package
            from infrastructure.rdb.skill_candidate_records import read_bound_skill_candidate

            objects = {}
            def put(stream, key):
                objects[key] = stream.read()
                return True, key

            monkeypatch.setattr(skill_package.minio_client, "upload_fileobj", put)
            monkeypatch.setattr(skill_package.minio_client, "get_file_stream", lambda key: (True, io.BytesIO(objects[key])))
            payload = {k: draft.json()["data"][k] for k in ("source_digest", "draft_digest", "replacement")}
            build_url = f"/api/agent-evolution/feedback/{fid}/skill-script-build"
            assert client.post(build_url,headers=editor_header,json=payload).status_code == 403
            assert client.post(build_url,headers=designer_header,json={**payload, "draft_digest":"0"*64}).status_code == 400
            assert not objects
            built = client.post(build_url,headers=designer_header,json=payload)
            assert built.is_success, built.text
            candidate = built.json()["data"]["candidate_id"]
            assert client.post(build_url,headers=designer_header,json=payload).json()["data"]["candidate_id"] == candidate
            bound = read_bound_skill_candidate(tenant, agent, 1, candidate)
            assert bound["script_build"]["source_cases"] == ids
            assert not read_bound_skill_candidate(tenant, agent, 0, candidate)
            assert skill_package.load_skill_package(tenant, 8, bound["base_digest"])[path] == original
            assert b"return value.upper()" in skill_package.load_skill_package(tenant, 8, bound["result_digest"])[path]
            assert (directory / path).read_bytes() == original
            (directory / "requirements.txt").write_text("example==1",encoding="utf8")
            assert client.post(url,headers=designer_header,json=fix).status_code == 400
    finally:
        clear_default_thread_manager(config_thread_manager)
        asyncio.run(config_thread_manager.shutdown(timeout=5))
