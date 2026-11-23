# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from local_auth_http import bearer, native_runtime, register, runtime


@pytest.mark.case_id("EVOLUTION-EXAMPLE-SOURCE-D2-001")
@pytest.mark.stage("D2")
def test_reject_same_source_before_trial_submission(runtime, monkeypatch, tmp_path):
    from backend.http.server.exception_handlers import register_exception_handlers
    from types import SimpleNamespace
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.api.evaluation.evolution import router
    from management.db.evaluation.candidates import store_prompt_candidate
    from management.db.evaluation.evaluator import create_evaluator, publish_evaluator
    from management.services.evaluation import experiments
    from management.db.evaluation import experiments as jobs
    from management.db.evaluation.replay_cases import contains_fixed_cases, save_replay_case
    from management.services.evaluation.replay_cases import freeze_regression_members
    from management.services.evaluation.example_candidates import example_source_keys
    from management.thread_management import config_thread_manager
    from nexent.core.concurrency import clear_default_thread_manager, set_default_thread_manager

    identity, _, _, models = runtime
    load_system_configuration()
    login = register(identity)
    user, tenant = login["user"]["id"], "tenant-native"
    headers = bearer(login["session"]["access_token"])
    models.TableBase.metadata.create_all(db_client.engine)
    migrations = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with db_client.engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        for name in ("003_conversation_run_admission", "006_prepared_conversation_turn", "011_trajectory",
                     "015_conversation_evolution", "016_evolution_candidates", "017_evolution_skill_candidates",
                     "018_evolution_replay_cases", "019_evolution_experiments", "021_evolution_online_reviews", "022_evolution_suggestions",
                     "025_evolution_regression_cases", "026_evolution_combination", "028_evolution_confirmation_suites",
                     "029_evolution_confirmation_locks", "030_evolution_confirmation_results", "031_evolution_session_versions", "032_evolution_releases", "033_evolution_release_tools"):
            cursor.execute((migrations / f"v2.9.0_{name}.sql").read_text(encoding="utf-8"))
    with get_db_session() as session:
        for version in (0, 1, 2):
            session.add(models.AgentInfo(agent_id=7, version_no=version, tenant_id=tenant, name="examples", prompt="base",
                created_by=user, updated_by=user, delete_flag="N", ingroup_permission="PRIVATE"))
            session.flush()
    eid = create_evaluator(tenant, user, "Acceptance", "", "code", None, code=(
        "def evaluate(query, expected, actual, runtime_events):\n    return {'score': int(actual == expected)}"))["evaluator_id"]
    publish_evaluator(eid, tenant)
    sources = example_source_keys(dict(query="List action items", source_group="minutes-51", attachments=[]))
    candidate = store_prompt_candidate(tenant, 7, 1, user, "base", "base with demonstration",
                                       {"method":"P2", "source_keys":sorted(sources)})
    monkeypatch.setattr(experiments, "EVOLUTION_REPLAY_RUNTIME_URL", "http://127.0.0.1:1")
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api")
    config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)
    try:
        with TestClient(app) as client:
            root = "/api/agent-evolution"
            for i, (query, group) in enumerate([("list   ACTION items", None), ("A different wording", "MINUTES-51")]):
                response = client.post(root + "/development-cases", headers=headers, json={
                    "agent_id":7, "version_no":1, "family":"minutes", "query":query, "expected":"done", "source_group":group})
                assert response.status_code == 200, response.text
                case = response.json()["data"]["case_id"]
                response = client.post(root + "/experiments", headers=headers, json={
                    "request_id":f"check-{i}", "agent_id":7, "version_no":1, "case_ids":[case],
                    "candidate_type":"prompt", "candidate_id":candidate, "evaluator_id":eid})
                assert 400 <= response.status_code < 500 and "fresh materials" in response.text, response.text
            with get_db_session() as session:
                assert session.scalar(text("SELECT count(*) FROM nexent.evolution_experiment_t")) == 0
                assert session.scalar(text("SELECT count(*) FROM nexent.evolution_trial_t")) == 0

            path = f"{root}/agents/7/versions/1/development-cases/{case}/regression"
            assert client.post(path, headers=headers, json={"enabled": True, "evaluator_id":eid}).status_code == 200
            assert client.post(path, headers=headers, json={"enabled": True, "evaluator_id":eid}).status_code == 200
            with get_db_session() as session:
                assert session.scalar(text("SELECT count(*) FROM nexent.evolution_regression_case_t WHERE enabled")) == 1
            copied = freeze_regression_members(tenant, user, 7, 2)
            copied_id, = map(int, copied)
            assert copied_id != case and copied[str(copied_id)]["source_case_id"] == case
            frozen_rule = copied[str(copied_id)]["scoring"]["evaluator"]
            assert frozen_rule["evaluator_id"] == eid and frozen_rule["version_no"] > 0
            assert freeze_regression_members(tenant, user, 7, 2) == copied
            same_group = client.post(root + "/development-cases", headers=headers, json={
                "agent_id":7, "version_no":2, "family":"meeting", "query":"New question and grading target",
                "expected":"rows", "source_group":"minutes-51"}).json()["data"]
            assert contains_fixed_cases(tenant, 7, [same_group["case_id"]], [])
            assert not contains_fixed_cases("foreign", 7, [same_group["case_id"]], [])
            dialogue = client.post(root + "/development-cases", headers=headers, json={
                "agent_id":7, "version_no":2, "family":"meeting", "query":"A different wording",
                "followups":[{"query":"Continue"}], "expected":"rows"}).json()["data"]
            assert contains_fixed_cases(tenant, 7, [dialogue["case_id"]], [])
            fresh_dialogue = client.post(root + "/development-cases", headers=headers, json={
                "agent_id":7, "version_no":2, "family":"meeting", "query":"Read the quarterly plan",
                "followups":[{"query":"Continue"}], "expected":"rows"}).json()["data"]
            assert not contains_fixed_cases(tenant, 7, [fresh_dialogue["case_id"]], [dialogue["case_id"]])
            trace_cases = [save_replay_case(tenant, 7, 1, user, {
                "query": wording, "family":"meeting", "expected":"rows", "attachments":[],
                "trace_source":{"source_group":"same-authorized-chat"}})["case_id"]
                for wording in ("List decisions", "Report responsibilities")]
            assert contains_fixed_cases(tenant, 7, trace_cases[:1], trace_cases[1:])
            source_files = []
            for filename, question in (("original.txt","write the minutes"),("renamed.txt","amend the handoff")):
                res = client.post(root + "/development-cases", headers=headers, json={
                    "agent_id":7,"version_no":1,"family":"meeting","query":question,"expected":"ok",
                    "file_state":{"initial":{filename:"shared meeting notes"},"expected":{filename:"new notes"}}})
                assert res.is_success, res.text
                source_files.append(res.json()["data"]["case_id"])
            assert contains_fixed_cases(tenant, 7, source_files[:1], source_files[1:])
            unrelated = client.post(root + "/development-cases", headers=headers, json={
                "agent_id":7, "version_no":1, "family":"minutes", "query":"Different source", "expected":"done"}).json()["data"]
            response = client.post(root + "/experiments", headers=headers, json={
                "request_id":"auto-include", "agent_id":7, "version_no":1, "case_ids":[unrelated["case_id"]],
                "candidate_type":"prompt", "candidate_id":candidate, "evaluator_id":eid})
            assert 400 <= response.status_code < 500 and "fresh materials" in response.text, response.text
            candidate_v2 = store_prompt_candidate(tenant, 7, 2, user, "base", "revised", {"method":"P1"})
            submission = {"request_id":"frozen", "agent_id":7, "version_no":2,
                          "candidate_type":"prompt", "candidate_id":candidate_v2, "evaluator_id":eid}
            response = client.post(root + "/experiments", headers=headers, json={**submission, "case_ids":[same_group["case_id"]]})
            assert 400 <= response.status_code < 500 and "outside the fixed" in response.text, response.text
            fresh = client.post(root + "/development-cases", headers=headers, json={
                "agent_id":7, "version_no":2, "family":"meeting", "query":"A fresh task", "expected":"rows"}).json()["data"]

            async def fixed_snapshot(request, scope_tenant, scope_user, arm):
                return SimpleNamespace(model_dump=lambda **kw: {"models":{"llm":{"alias":"pilot"}},
                    "resource":{"model_alias":"pilot", "subagents":[], "prompt":"base" if arm == "base" else "revised"}})

            monkeypatch.setattr(experiments, "_snapshot", fixed_snapshot)
            response = client.post(root + "/experiments", headers=headers, json={**submission, "case_ids":[fresh["case_id"]],
                "screening":{"target_case_ids":[fresh["case_id"]],"minimum":1}})
            assert response.status_code == 202, response.text
            source_experiment = response.json()["data"]["experiment_id"]
            plan = jobs.read_plan(tenant, source_experiment)
            assert plan["regression_cases"] == copied
            assert set(plan["cases"]) == {str(copied_id), str(fresh["case_id"])}
            assert client.post(path, headers=headers, json={"enabled":False}).status_code == 200
            assert freeze_regression_members(tenant, user, 7, 2) == {}
            response = client.post(root + f"/experiments/{source_experiment}/example-candidates", headers=headers, json={
                "target_case_id":same_group["case_id"], "target_behavior":"extract",
                "examples":[{"case_id":same_group["case_id"], "variant":"base", "behavior":"extract",
                             "input_excerpt":"New", "output_excerpt":"rows"}]})
            assert 400 <= response.status_code < 500 and "Fixed regression" in response.text, response.text
            with get_db_session() as session:
                assert session.scalar(text("SELECT count(*) FROM nexent.evolution_experiment_t")) == 1
            tool_submission = {**submission, "request_id": "tool-source", "case_ids": [fresh["case_id"]],
                               "candidate_type": "tool_set", "candidate_id": 19}
            response = client.post(root + "/experiments", headers=headers, json=tool_submission)
            assert response.status_code == 202, response.text
            tool_experiment = response.json()["data"]["experiment_id"]
            parts = [
                {"experiment_id": source_experiment, "candidate_id": candidate_v2, "candidate_type": "prompt"},
                {"experiment_id": tool_experiment, "candidate_id": 19, "candidate_type": "tool_set"},
            ]
            combined = {**submission, "request_id": "combination", "candidate_type": "combination", "candidate_id": None,
                        "components": parts, "case_ids": [fresh["case_id"]]}
            response = client.post(root + "/experiments", headers=headers, json=combined)
            assert 400 <= response.status_code < 500 and "graded pair" in response.text, response.text
            for single in (source_experiment, tool_experiment):
                frozen = jobs.read_plan(tenant, single)
                while trial := jobs.claim(single):
                    status = "fail" if trial["variant"] == "base" and trial["case_id"] == fresh["case_id"] else "pass"
                    assert jobs.finish(trial, status, {"snapshot_digest": frozen["snapshots"][trial["variant"]],
                        "case_digest": frozen["cases"][str(trial["case_id"])], "evaluator_id":eid,
                        "evaluator_version":frozen["evaluator"]["version_no"],"judgment":{"status":status}})
            forged = {**combined, "components": [parts[0], {**parts[1], "candidate_id": 20}]}
            response = client.post(root + "/experiments", headers=headers, json=forged)
            assert 400 <= response.status_code < 500 and "single experiments" in response.text, response.text
            response = client.post(root + "/experiments", headers=headers, json=combined)
            assert response.status_code == 202, response.text
            combo_id = response.json()["data"]["experiment_id"]
            assert client.post(root + f"/experiments/{combo_id}/confirmation-candidate",headers=headers).status_code == 400
            retry = client.post(root + "/experiments", headers=headers, json=combined)
            assert retry.status_code == 202 and retry.json()["data"]["experiment_id"] == combo_id
            trial_rows = jobs.trials(tenant, combo_id)
            assert len(trial_rows) == 4
            assert {row["variant"] for row in trial_rows} == {"base", "only_a", "only_b", "result"}
            assert all(row["status"] == "pending" for row in trial_rows)
            cancelled = client.post(root + f"/experiments/{tool_experiment}/cancel", headers=headers)
            assert cancelled.is_success
            response = client.post(root + "/experiments", headers=headers, json={**combined, "request_id": "after-cancel"})
            assert 400 <= response.status_code < 500 and "single experiments" in response.text, response.text
            with get_db_session() as session:
                assert session.scalar(text("SELECT count(*) FROM nexent.evolution_experiment_t")) == 3
            check_confirmation_space(client, identity, headers, user, tenant, tmp_path, source_experiment)
    finally:
        clear_default_thread_manager(config_thread_manager)
        asyncio.run(config_thread_manager.shutdown(timeout=5))


def check_confirmation_space(client, identity, editor, editor_id, tenant, private_dir, experiment):
    import json
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from contracts.errors.exceptions import AppException
    from contracts.evolution_sources import task_digest
    from infrastructure.rdb.client import get_db_session
    from local_auth_http import seed_membership_roles
    from management.cli.confirmation_manifest import compile_private_suite
    from management.db.evaluation.confirmation import register_suite
    from management.db.evaluation.confirmation_runs import finalize
    from management.services.evaluation.confirmation_results import comparison_summary
    from contracts.confirmation import ConfirmationPolicy
    from management.db.evaluation.replay_cases import save_replay_case

    login = identity.post("/api/user/signup",json={"email":"curator@example.com","password":"Password123",
        "invite_code":"NATIVE-INVITE","auto_login":True}).json()["data"]
    curator_id = login["user"]["id"]
    curator = bearer(login["session"]["access_token"])
    root = "/api/agent-evolution"
    grant_url = root + "/agents/7/confirmation-curators"
    seal_url = root + "/confirmation-suites"
    grant = {"user_id":curator_id,"enabled":True}
    pack = private_dir / "suite.json"
    def compile_case(query, group, version=1):
        pack.write_text(json.dumps([{"agent_id":7,"version_no":version,"family":"meeting","query":query,
            "source_group":group,"expected":"PRIVATE ANSWER — customer seven"}]),encoding="utf-8")
        return compile_private_suite(pack)

    manifest = compile_case("Private confirmation query", "minutes-Q3")
    assert client.post(seal_url,headers=curator,json=manifest.canonical()).status_code == 403
    assert client.put(grant_url,headers=editor,json=grant).status_code == 403
    seed_membership_roles(editor_id, ["ADMIN"])
    assert client.put(grant_url,headers=editor,json=grant).is_success
    assert client.post(seal_url,headers=editor,json=manifest.canonical()).status_code == 403
    sealed = client.post(seal_url,headers=curator,json=manifest.canonical())
    assert sealed.is_success, sealed.text
    receipt = sealed.json()["data"]
    assert receipt["digest"] == task_digest(manifest.canonical())
    assert client.post(seal_url,headers=curator,json=manifest.canonical()).json()["data"] == receipt
    other_version = {"agent_id":7,"version_no":2,"query":"Different words","family":"meeting",
                     "expected":"done","source_group":"MINUTES-q3"}
    rejected = client.post(root + "/development-cases",headers=editor,json=other_version)
    assert rejected.status_code == 400 and "partition" in rejected.text
    prior = compile_case("A previously registered business case reworded", "minutes-51")
    rejected = client.post(seal_url,headers=curator,json=prior.canonical())
    assert rejected.status_code == 400 and "partition" in rejected.text
    with get_db_session() as session:
        stored = session.scalar(text("SELECT manifest FROM nexent.evolution_confirmation_suite_t WHERE suite_id=:id"),
                                {"id":receipt["suite_id"]})
        assert stored == manifest.canonical()
        # A release predating source reservations still has to protect its development cases.
        legacy = {"attachments":[],"query":"Original legacy report","family":"fixture","expected":"done"}
        session.execute(text("""INSERT INTO nexent.evolution_replay_case_t
            (tenant_id,agent_id,version_no,digest,task,created_by) VALUES (:t,7,2,:d,CAST(:j AS jsonb),:u)"""),
            {"t":tenant,"d":task_digest(legacy),"j":json.dumps(legacy),"u":editor_id})
    old = compile_case("original LEGACY report","unregistered-group")
    assert client.post(seal_url,headers=curator,json=old.canonical()).status_code == 400
    workspace = client.get(root + "/agents/7/versions/1/workspace",headers=editor)
    assert workspace.is_success and "Private confirmation query" not in workspace.text
    guessed = client.get(root + f"/agents/7/versions/1/development-cases/{receipt['suite_id']}",headers=editor)
    assert guessed.status_code in {200,404} and "PRIVATE ANSWER" not in guessed.text
    race = compile_case("race on held material", "same-family")
    barrier = Barrier(2)
    def compete(seal):
        barrier.wait(timeout=10)
        try:
            if seal:
                register_suite(tenant, curator_id, race)
            else:
                save_replay_case(tenant,7,2,editor_id,{"query":"other phrasing","source_group":"same-family","attachments":[]})
        except AppException as exc:
            assert "partition" in str(exc)
            return False
        return True
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(compete,[False,True])) == [False,True]
    nomination = client.post(root + f"/experiments/{experiment}/confirmation-candidate",headers=editor)
    assert nomination.is_success, nomination.text
    candidate = nomination.json()["data"]
    private_v2 = compile_case("A new external report", "new-private-series", version=2)
    receipt = client.post(seal_url,headers=curator,json=private_v2.canonical()).json()["data"]
    url = seal_url + f"/{receipt['suite_id']}/locks"
    policy = {"minimum_valid_pairs":1,"minimum_valid_percent":100,"minimum_quality_gain_pp":1,"family_minimums":{"meeting":1}}
    body = {**candidate,"suite_digest":receipt["digest"],"policy":policy}
    assert client.post(url,headers=editor,json=body).status_code == 403
    result = client.post(url,headers=curator,json=body)
    assert result.is_success, result.text
    read_url = root + f"/confirmation-locks/{result.json()['data']['lock_id']}"
    assert client.get(read_url,headers=editor).status_code == 403
    protocol = client.get(read_url,headers=curator).json()["data"]
    assert protocol["digest"] == result.json()["data"]["digest"] and protocol["policy"]["family_minimums"] == {"meeting":1}
    assert protocol["recipe"]["snapshots"].keys() == {"base","result"} and "cases" not in protocol["recipe"]
    assert client.post(url,headers=curator,json=body).json()["data"] == result.json()["data"]
    assert client.post(url,headers=curator,json={**body,"policy":{**policy,"minimum_quality_gain_pp":2}}).status_code == 400
    other = compile_case("Reworded external report", "new-private-series", version=2)
    second = client.post(seal_url,headers=curator,json=other.canonical()).json()["data"]
    reuse = client.post(seal_url + f"/{second['suite_id']}/locks",headers=curator,json={**body,"suite_digest":second["digest"]})
    assert reuse.status_code == 400 and "already assigned" in reuse.text
    results_url = root + f"/experiments/{experiment}/confirmation-results"
    assert client.get(results_url,headers=editor).json()["data"] == [{"lock_id":protocol["lock_id"],"summary":None}]
    assert client.get(results_url).status_code in (401,403)
    owners = root + "/agents/7/release-owners"
    publish_grant = {"user_id": editor_id, "enabled": True}
    release_url = read_url + "/release"
    publish_url = read_url + "/promote"
    request = {"expected_version": 2, "candidate_digest": candidate["candidate_digest"], "reason": "Business confirmation passed"}
    assert client.put(owners, headers=curator, json=grant).status_code == 403
    assert client.get(release_url, headers=editor).status_code == 403
    assert client.put(owners, headers=editor, json=publish_grant).is_success
    assert client.post(publish_url, headers=editor, json=request).status_code == 400
    arm = {"status":"fail","ms":1,"tokens":None,"forbidden":False}
    summary = comparison_summary(ConfirmationPolicy(**policy), [("meeting",arm,{**arm,"status":"pass"})])
    assert finalize(tenant,curator_id,protocol,summary) == summary
    assert finalize(tenant,curator_id,protocol,{**summary,"decision":"failed"}) == summary
    release = client.get(release_url, headers=editor)
    assert release.is_success, release.text
    assert release.json()["data"]["summary"]["decision"] == "passed"
    assert "PRIVATE ANSWER" not in release.text
    assert client.get(release_url, headers=curator).status_code == 403
    for mismatch in ({"expected_version": 3}, {"candidate_digest": "1" * 64}):
        rejected = client.post(publish_url, headers=editor, json={**request, **mismatch})
        assert rejected.status_code == 400, rejected.text
    assert client.put(owners, headers=editor, json={**publish_grant, "enabled": False}).is_success
    assert client.post(publish_url, headers=editor, json=request).status_code == 403
    with get_db_session() as session:
        assert session.scalar(text("SELECT count(*) FROM nexent.evolution_release_t")) == 0
    public = client.get(results_url,headers=editor)
    assert public.json()["data"] == [{"lock_id":protocol["lock_id"],"summary":summary}]
    assert not any(secret in public.text for secret in ("PRIVATE ANSWER","new-private-series","meeting"))
    with get_db_session() as session:
        assert session.scalar(text("SELECT count(*) FROM nexent.evolution_confirmation_lock_t")) == 1
    assert client.put(grant_url,headers=editor,json={**grant,"enabled":False}).is_success
    with pytest.raises(AppException):
        finalize(tenant,curator_id,protocol,summary)
    assert client.post(url,headers=curator,json=body).status_code == 403
    assert client.get(read_url,headers=curator).status_code == 403
    assert client.post(seal_url,headers=curator,json=manifest.canonical()).status_code == 403
