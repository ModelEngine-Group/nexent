# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise the private worker's durable checkpoints across abrupt process exit."""

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from local_auth_http import native_runtime, runtime

ROOT = Path(__file__).resolve().parents[3]
TENANT, EDITOR, CURATOR = "tenant-native", "recovery-editor", "recovery-curator"


@dataclass
class Spec:
    arm: str
    confirmation_bucket: str | None = None
    input: object = None
    conversation_id: int = 0
    replay_trial_id: str | None = None
    observe_root_skill_choices: bool = False
    tool_set_check: object = None
    resource = SimpleNamespace(skill_refs=[])

    def model_copy(self, *, update):
        return replace(self, **update)


def frozen_recipe(plan, eid):
    from contracts.evolution_sources import task_digest

    return {"snapshots":plan["snapshots"],"tenant_id":TENANT,"agent_id":7,"version_no":1,
            "experiment_id":eid,"plan_digest":task_digest(plan)}


def seed_lock(runtime, suite, failure):
    from contracts.confirmation import ConfirmationPolicy
    from contracts.evolution import DevelopmentExperimentRequest
    from contracts.evolution_sources import task_digest
    from infrastructure.rdb.client import db_client, get_db_session
    from management.cli.confirmation_manifest import read_private_suite

    _, _, _, models = runtime
    manifest, _, tasks = read_private_suite(suite)
    public = manifest.canonical()
    request = DevelopmentExperimentRequest(
        agent_id=7, version_no=1, candidate_type="prompt", candidate_id=8,
        request_id=f"recovery-{failure}", evaluator_id=7, case_ids=[1], timeout_seconds=30,
    )
    policy = ConfirmationPolicy(minimum_valid_pairs=1,minimum_valid_percent=25,
                                family_minimums={"record":1},minimum_quality_gain_pp=1).model_dump()
    plan = {"request":request.model_dump(), "snapshots":{"base":"base","result":"result"}, "evaluator":{"evaluator_type":"code"}}
    with get_db_session() as session:
        for actor, role in ((EDITOR, "DEV"), (CURATOR, "USER")):
            session.add(models.UserAccount(user_id=actor,user_roles=[role],delete_flag="N"))
            session.add(models.UserTenant(user_id=actor,tenant_id=TENANT,user_role=role,delete_flag="N"))
    with db_client.engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        directory = ROOT / "deploy/sql/migrations"
        for name in ("018_evolution_replay_cases","019_evolution_experiments","028_evolution_confirmation_suites",
                     "029_evolution_confirmation_locks","030_evolution_confirmation_results",
                     "031_evolution_session_versions","032_evolution_releases",
                     "041_evolution_generation_attempts","043_evolution_model_charges",
                     "044_evolution_evaluation_metering","045_evolution_confirmation_metering"):
            cursor.execute((directory / f"v2.9.0_{name}.sql").read_text(encoding="utf8"))
        eid = conn.scalar(text("""
            INSERT INTO nexent.evolution_experiment_t
                (tenant_id,created_by,agent_id,version_no,request_id,request_digest,plan)
            VALUES (:tenant,:editor,7,1,:request,:digest,CAST(:plan AS jsonb)) RETURNING experiment_id
        """), dict(tenant=TENANT, editor=EDITOR, request=request.request_id, digest=task_digest(plan), plan=json.dumps(plan)))
        recipe = frozen_recipe(plan,eid)
        suite_id = conn.scalar(text("""
            INSERT INTO nexent.evolution_confirmation_suite_t (tenant_id,agent_id,version_no,digest,manifest,created_by)
            VALUES (:tenant,7,1,:digest,CAST(:manifest AS jsonb),:curator) RETURNING suite_id
        """), dict(tenant=TENANT, curator=CURATOR, digest=task_digest(public), manifest=json.dumps(public)))
        conn.execute(text("""
            INSERT INTO nexent.evolution_confirmation_curator_t (tenant_id,agent_id,user_id,enabled,updated_by)
            VALUES (:tenant,7,:curator,true,:curator) ON CONFLICT DO NOTHING;
            INSERT INTO nexent.evolution_confirmation_candidate_t (experiment_id,digest,recipe,submitted_by)
            VALUES (:eid,:recipe_digest,CAST(:recipe AS jsonb),:editor);
            INSERT INTO nexent.evolution_publisher_t (tenant_id,agent_id,user_id,enabled,updated_by)
            VALUES (:tenant,7,:editor,true,:curator) ON CONFLICT DO NOTHING;
        """), dict(tenant=TENANT, curator=CURATOR, eid=eid, recipe_digest=task_digest(recipe),
                   recipe=json.dumps(recipe), editor=EDITOR))
        lock_digest = task_digest([TENANT,suite_id,task_digest(public),eid,task_digest(recipe),policy])
        lock_id = conn.scalar(text("""
            INSERT INTO nexent.evolution_confirmation_lock_t (suite_id,experiment_id,digest,policy,locked_by)
            VALUES (:suite,:eid,:digest,CAST(:policy AS jsonb),:curator) RETURNING lock_id
        """), dict(suite=suite_id,eid=eid,digest=lock_digest,policy=json.dumps(policy),curator=CURATOR))
    ordered = sorted(tasks)
    attempted = [task_digest([lock_digest,digest,arm])[:32] for index,digest in enumerate(ordered)
                 for arm in (("base","result") if index%2==0 else ("result","base"))]
    return eid, lock_id, attempted


@pytest.mark.stage("D5")
@pytest.mark.case_id("EVOLUTION-PRIVATE-RECOVERY-D5-001")
@pytest.mark.parametrize("failure", ["staging","dispatched"])
def test_private_confirmation_resumes_after_worker_exit(runtime, tmp_path, failure):
    from contracts.errors.exceptions import AppException
    from infrastructure.rdb.client import db_client
    from management.db.evaluation import releases
    from management.db.evaluation.confirmation_runs import result_for_experiment
    from management.services.evaluation.confirmation_runner import checkpoint

    private = tmp_path / "suites"
    private.mkdir()
    (private/"input.txt").write_text("Private fixture attachment",encoding="utf8")
    suite = private/"tasks.json"
    suite.write_text(json.dumps([dict(
        agent_id=7,version_no=1,family="record",source_group=f"{failure} group {i}",
        query=f"Private fixture question {failure} {i}",expected="Private fixture answer",
        attachments=[dict(name="private-input.txt",object_name="input.txt")],
    ) for i in range(3)]),encoding="utf8")
    eid, lock, attempts = seed_lock(runtime, suite, failure)
    target = attempts[2]
    state = tmp_path/"private-state"
    objects = tmp_path/"private-objects"
    calls = tmp_path/"runtime-calls.txt"
    env = {**os.environ, "PYTHONPATH":os.pathsep.join(str(path) for path in
           (ROOT/"backend",ROOT/"sdk",ROOT,ROOT/"test-e2e/infra/automation")),
           "ENABLE_TELEMETRY":"false", "MINIO_DEFAULT_BUCKET":"private", "NEXENT_EVOLUTION_CONFIRMATION_BUCKET":"private",
           "NEXENT_EVOLUTION_CONFIRMATION_STATE_DIR":str(state), "NEXENT_EVOLUTION_CONFIRMATION_RUNTIME_URL":"http://fixture",
           "NEXENT_EVOLUTION_CONFIRMATION_METERING":"{}"}

    def execute(fault):
        return subprocess.run([sys.executable,str(Path(__file__).resolve()),"worker",str(suite),str(objects),
                               str(calls),str(lock),target,fault],
                              env=env,cwd=ROOT,capture_output=True,text=True,timeout=45,check=False)

    def requests():
        return calls.read_text(encoding="utf8").splitlines()

    crashed = execute(failure)
    assert crashed.returncode == 31, crashed.stderr
    assert requests() == attempts[:2 if failure == "staging" else 3]
    assert result_for_experiment(TENANT,eid) == [{"lock_id":lock,"summary":None}]
    ledger = state/"confirmation.sqlite3"
    assert checkpoint(ledger,target) == {"pending_phase":failure}
    if failure == "staging":
        assert (objects/f"attachments/{EDITOR}/evolution-replay/{target}/private-input.txt").is_file()
    recovered = execute("resume")
    assert recovered.returncode == 0, recovered.stderr
    summary = json.loads(recovered.stdout.splitlines()[-1])
    assert requests() == attempts
    assert not any(path.is_file() for path in objects.rglob("*"))
    assert result_for_experiment(TENANT,eid) == [{"lock_id":lock,"summary":summary}]
    assert "Private fixture" not in json.dumps(summary) and target not in json.dumps(summary)
    if failure == "staging":
        assert summary["decision"] == "passed" and summary["valid_pairs"] == 3
    else:
        assert summary["decision"] == "insufficient" and summary["valid_pairs"] == 2
        assert "confirmation_arm_interrupted" in summary["missing"]
        assert checkpoint(ledger,target)["status"] == "invalid"
        with pytest.raises(AppException,match="independently passed"):
            releases.prepare(TENANT,EDITOR,lock)
    repeated = execute("resume")
    assert repeated.returncode == 0 and json.loads(repeated.stdout.splitlines()[-1]) == summary
    assert requests() == attempts
    with db_client.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM nexent.evolution_confirmation_result_t WHERE lock_id=:id"), {"id":lock}) == 1
        assert conn.scalar(text("SELECT count(*) FROM nexent.evolution_release_t")) == 0


def worker(suite, objects, calls, lock, target, fault):
    from contracts.agentos import EvaluationAgentResult, ReplayReceipt, RunAttachment
    from management.services.evaluation import confirmation_runner as private, experiments, replay_cases
    from nexent.core.concurrency import shutdown_fallback_thread_manager

    async def spec(_req,_tenant,_editor,arm):
        return Spec(arm)

    async def recipe(_tenant,_editor,eid,plan):
        return frozen_recipe(plan,eid)

    class RuntimeFixture:
        def __init__(self,*_args):
            pass

        async def run_prepared_evaluation(self,request,_user,_tenant):
            with calls.open("a",encoding="utf8") as journal:
                journal.write(request.replay_trial_id+"\n")
                journal.flush()
                os.fsync(journal.fileno())
            return EvaluationAgentResult(answer="pass" if request.arm=="result" else "fail",events=[],
                                         replay_receipt=ReplayReceipt(trial_id=request.replay_trial_id,
                                             outcome="completed",confirmation_bucket=request.confirmation_bucket))

    def write(key,data):
        path = objects/key
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
        if fault=="staging" and target in key:
            os._exit(31)

    def delete(key):
        (objects/key).unlink(missing_ok=True)
        return True,None

    checkpoint = private.checkpoint

    def save(path,attempt,value=None,phase=None):
        if fault=="dispatched" and attempt==target and value is not None:
            os._exit(31)
        return checkpoint(path,attempt,value,phase)

    private.verified_recipe = recipe
    private.AgentOSClient = RuntimeFixture
    private.checkpoint = save
    experiments._snapshot = spec
    experiments.snapshot_digest = lambda snapshot:snapshot.arm
    experiments._grade = lambda _req,_job,_task,result: {"status":result.answer,"evaluator_id":7,"evaluator_version":1}
    experiments.require_business_agent_edit = lambda *_: None
    replay_cases._write = write
    replay_cases._read_bounded = lambda key,_limit:(objects/key).read_bytes()
    replay_cases.minio_client = SimpleNamespace(delete_file=delete)
    replay_cases.build_evaluation_input = lambda query, files, _history, _user, _tenant: Input(
        query, [RunAttachment(name=file["name"], url=f"s3://fixture/{file['object_name']}") for file in files],
    )

    async def run():
        try:
            return await private.run_confirmation(TENANT,lock,suite)
        finally:
            await shutdown_fallback_thread_manager()
    print(json.dumps(asyncio.run(run())),flush=True)


@dataclass
class Input:
    query: str
    attachment_refs: list
    history: list | None = None

    def model_copy(self, *, update):
        return replace(self, **update)


if __name__ == "__main__":
    _,_,suite,objects,calls,lock,target,fault = sys.argv
    worker(Path(suite),Path(objects),Path(calls),int(lock),target,fault)
