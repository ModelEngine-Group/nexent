# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from local_auth_http import bearer, native_runtime, register, runtime, seed_membership_roles


@pytest.mark.case_id("EVOLUTION-NEW-SKILL-D2-001")
@pytest.mark.stage("D2")
def test_new_skill_http(runtime, monkeypatch):
    from backend.http.server.exception_handlers import register_exception_handlers
    from contracts.evolution import DevelopmentExperimentRequest
    from infrastructure import skill_package
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.api.evaluation.evolution import router
    from management.db.evaluation import experiments as jobs
    from management.db.evaluation.replay_cases import save_replay_case
    from management.services.evaluation import (
        new_skill_candidates as generator,
        new_skill_evidence as evidence,
    )
    from management.services.evaluation.experiments import snapshot_digest
    from management.services.skill.nl2skill import project_creation_events
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
        for n in (18, 19, 20, 25, 28, 33, 34):
            (file,) = path.glob(f"v2.9.0_{n:03}_*.sql")
            cur.execute(file.read_text(encoding="utf-8"))
        conn.execute(
            text("""INSERT INTO nexent.role_permission_t
            (role_permission_id,user_role,permission_category,permission_type,permission_subtype)
            SELECT 91001,'DEV','RESOURCE','SKILL','CREATE' WHERE NOT EXISTS (SELECT 1 FROM nexent.role_permission_t
            WHERE user_role='DEV' AND permission_type='SKILL' AND permission_subtype='CREATE')""")
        )
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
    records = {}
    subjects = ["Amber Customer", "Indigo Customer", "Third Customer", "Other Customer"]
    for i, subject in enumerate(subjects):
        task = dict(
            query=f"Review record for {subject}",
            expected=f"Record {subject} confirmed",
            attachments=[],
            source_group=["first", "second", "first", "counter"][i],
            family="record",
        )
        saved = save_replay_case(tenant, agent, 1, editor, task)
        records[saved["case_id"]] = (saved["digest"], task)
    ids = list(records)
    req = DevelopmentExperimentRequest(
        agent_id=agent,
        version_no=1,
        case_ids=ids,
        evaluator_id=1,
        candidate_type="baseline",
        request_id="skill-source",
    )
    spec = SimpleNamespace(
        model_dump=lambda **kw: {
            "models": {"llm": {"alias": "pilot"}},
            "resource": {"model_alias": "pilot", "subagents": []},
        }
    )
    digest = snapshot_digest(spec)
    plan = dict(
        request=req.model_dump(),
        cases={str(i): d for i, (d, _) in records.items()},
        snapshots={"base": digest},
        evaluator={"version_no": 1},
        regression_cases={},
    )
    eid = jobs.submit(tenant, editor, req, plan)
    while trial := jobs.claim(eid):
        d, task = records[trial["case_id"]]
        assert jobs.finish(
            trial,
            "pass",
            dict(
                case_digest=d,
                snapshot_digest=digest,
                evaluator_id=1,
                evaluator_version=1,
                answer=task["expected"],
                judgment={"status": "pass"},
            ),
        )

    async def snapshot(*args):
        return spec

    monkeypatch.setattr(evidence, "_snapshot", snapshot)
    outputs = []

    def prepare(request, uid, tid, language):
        assert uid == designer and tid == tenant and not any(s in request.query for s in subjects)
        return SimpleNamespace(model=SimpleNamespace(model_id=3, revision="model-revision"))

    async def raw():
        outputs.append(True)
        body = "---\nname: verify-record\ndescription: Verify intake records\n---\nConfirm intake using record id. Skip when cancelled."
        yield json.dumps(
            dict(type="final_answer", answer_phase="complete", content="<skill>\n" + body + "\n</skill>\n")
        )

    monkeypatch.setattr(generator, "prepare_nl2skill_snapshot", prepare)
    monkeypatch.setattr(generator, "create_nl2skill_stream", lambda *args: project_creation_events(raw(), []))
    assets = {}

    def upload(stream, key):
        assets[key] = stream.read()
        return True, None

    monkeypatch.setattr(skill_package.minio_client, "upload_fileobj", upload)
    monkeypatch.setattr(
        skill_package.minio_client, "get_file_stream", lambda key: (True, io.BytesIO(assets[key]))
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api")
    config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)

    def example(index):
        return dict(
            case_id=ids[index],
            private_values=[subjects[index]],
            outcomes=[{"step": "Confirm intake", "excerpt": subjects[index]}],
        )

    base = "/api/agent-evolution"
    try:
        with TestClient(app) as client:
            body = dict(
                name="verify-record",
                purpose="Verify intake",
                creator_id=designer,
                skip_when="cancelled",
                parameters=["record id"],
                counterexample_id=ids[-1],
                successes=[example(0), example(2)],
            )
            path = base + f"/experiments/{eid}/new-skill-brief"
            assert client.post(path, headers=editor_header, json=body).status_code == 400
            body["successes"] = [example(0), example(1)]
            response = client.post(path, headers=editor_header, json=body)
            assert response.is_success, response.text
            approved = response.json()["data"]
            assert approved["steps"] == ["outcome:Confirm intake"]
            path = base + f"/feedback/{approved['feedback_id']}/candidates"
            assert client.post(path, headers=editor_header, json={"model_id": 3}).status_code == 403
            from contracts.evolution_sources import task_digest
            from management.db.evaluation.confirmation_runs import exclusive_job_slot

            key = "nexent.new-skill/" + task_digest(
                [tenant, designer, approved["feedback_id"], 3, "model-revision"]
            )
            with exclusive_job_slot(key, "busy"):
                busy = client.post(path, headers=designer_header, json={"model_id": 3})
                assert busy.status_code == 400
                assert outputs == []
            first = client.post(path, headers=designer_header, json={"model_id": 3})
            assert first.is_success, first.text
            candidate = first.json()["data"]
            assert candidate["method"] == "S3" and "SKILL.md" in candidate["files"]
            assert (
                client.post(path, headers=designer_header, json={"model_id": 3}).json()["data"] == candidate
            )
            assert len(outputs) == len(assets) == 1
            read = base + f"/new-skill-candidates/{candidate['candidate_id']}"
            assert client.get(read, headers=editor_header).json()["data"] == candidate
            seed_membership_roles(designer, ["USER"])
            assert client.post(path, headers=designer_header, json={"model_id": 3}).status_code == 403
            assert client.get(read, headers=designer_header).status_code == 403
            with get_db_session() as session:
                assert not session.scalar(text("SELECT count(*) FROM nexent.ag_skill_info_t"))
                assert not session.scalar(text("SELECT count(*) FROM nexent.ag_skill_instance_t"))
    finally:
        clear_default_thread_manager(config_thread_manager)
        asyncio.run(config_thread_manager.shutdown(timeout=5))
