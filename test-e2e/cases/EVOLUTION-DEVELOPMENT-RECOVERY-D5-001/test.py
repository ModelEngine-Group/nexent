# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prove development lease, replay, and attachment recovery after process exit."""

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from local_auth_http import native_runtime, runtime

ROOT = Path(__file__).resolve().parents[3]
CASE = "EVOLUTION-DEVELOPMENT-RECOVERY-D5-001"
TENANT, EDITOR = "tenant-native", "recovery-editor"
ATTACHMENT = b"Delivery note"


@dataclass
class ReplaySpec:
    arm: str
    input: object = None
    conversation_id: int = 0
    replay_trial_id: str | None = None
    observe_root_skill_choices: bool = False
    tool_set_check: object = None
    resource = SimpleNamespace(skill_refs=[])

    def model_copy(self, *, update):
        return replace(self, **update)


@dataclass
class ReplayInput:
    query: str
    attachment_refs: list
    history: list | None = None

    def model_copy(self, *, update):
        return replace(self, **update)


def seed_experiment(fault):
    from contracts.evolution import DevelopmentExperimentRequest
    from contracts.evolution_sources import task_digest
    from infrastructure.rdb.client import db_client
    from management.db.evaluation import experiments as jobs

    tasks = [
        {
            "query": f"Check delivery note {index}",
            "source_group": f"{fault}-{index}",
            "attachments": [
                {"name": "delivery.txt", "size": len(ATTACHMENT), "sha256": sha256(ATTACHMENT).hexdigest()}
            ] if index == 2 else [],
        }
        for index in range(1, 4)
    ]
    migrations = ROOT / "deploy/sql/migrations"
    cases = {}
    with db_client.engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        for number in (18, 19, 41, 43, 44, 47):
            path, = migrations.glob(f"v2.9.0_{number:03}_*.sql")
            cursor.execute(path.read_text(encoding="utf-8"))
        for task in tasks:
            digest = task_digest(task)
            case_id = conn.scalar(
                text("""
                    INSERT INTO nexent.evolution_replay_case_t
                        (tenant_id, agent_id, version_no, digest, task, created_by)
                    VALUES (:tenant, 1, 1, :digest, CAST(:task AS jsonb), :editor)
                    RETURNING case_id
                """),
                dict(tenant=TENANT, editor=EDITOR, digest=digest, task=json.dumps(task)),
            )
            cases[str(case_id)] = digest
    ids = [int(case_id) for case_id in cases]
    req = DevelopmentExperimentRequest(
        agent_id=1, version_no=1, evaluator_id=7, candidate_type="prompt", candidate_id=2,
        request_id=fault, case_ids=ids, screening={"target_case_ids": ids[1:2], "minimum": 1},
        budget={"max_replay_turns": 6, "max_elapsed_seconds": 300},
    )
    rubric = {"evaluator_id": 7, "version_no": 1}
    return jobs.submit(TENANT, EDITOR, req, {
        "request": req.model_dump(), "cases": cases, "snapshots": {"base": "base", "result": "result"},
        "budget": req.budget.model_dump(), "evaluator": rubric,
        "regression_cases": {str(ids[2]): {"scoring": {"evaluator": rubric}}},
    }), ids


@pytest.mark.stage("D5")
@pytest.mark.case_id(CASE)
@pytest.mark.parametrize("fault", ["staging", "dispatched", "legacy", "repeated_staging"])
def test_worker_exit_recovers_development_comparison(runtime, tmp_path, fault, monkeypatch):
    from infrastructure.rdb.client import db_client
    from management.db.evaluation import experiments as jobs
    from management.services.evaluation import experiments as service

    eid, ids = seed_experiment(fault)
    target = ids[1]
    objects = tmp_path / "objects"
    calls = tmp_path / "runtime.jsonl"
    cleanup_marker = tmp_path / "cleanup-failed"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(str(path) for path in
                                     (ROOT, ROOT / "backend", ROOT / "sdk", ROOT / "test-e2e/infra/automation")),
        "NEXENT_EVOLUTION_REPLAY_RUNTIME_URL": "http://runtime-fixture",
        "NEXENT_EVOLUTION_EVALUATION_METERING": "{}",
        "ENABLE_TELEMETRY": "false",
    }

    def execute(mode):
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(eid), str(target),
             str(objects), str(calls), str(cleanup_marker), mode],
            cwd=ROOT, env=env, capture_output=True, text=True, check=False, timeout=40,
        )

    def rows():
        return {(row["case_id"], row["variant"]): row for row in jobs.trials(TENANT, eid)}

    def expire_interrupted(*, legacy=False):
        with db_client.engine.begin() as conn:
            expired = conn.execute(text("""
                UPDATE nexent.evolution_trial_t
                SET lease_until=now()-interval '1 second', cleanup_due=now()-interval '1 second',
                    dispatch_started=CASE WHEN :legacy THEN NULL ELSE dispatch_started END
                WHERE experiment_id=:eid AND case_id=:target AND variant='result' AND status='running'
                RETURNING trial_id, receipt_id
            """), dict(eid=eid, target=target, legacy=legacy)).mappings().one()
            return {**expired, "tenant_id": TENANT}

    first_exit = execute("dispatched" if fault == "dispatched" else "staging")
    assert first_exit.returncode == 31, first_exit.stderr
    initial = rows()
    assert [initial[(ids[0], arm)]["status"] for arm in ("base", "result")] == ["pass", "pass"]
    assert initial[(target, "base")]["status"] == "fail"
    old_job = expire_interrupted(legacy=fault == "legacy")
    if fault in {"staging", "repeated_staging"}:
        assert (objects / "attachments" / EDITOR / "evolution-replay" / old_job["receipt_id"] / "delivery.txt").is_file()
        blocked = execute("cleanup_failed")
        assert blocked.returncode == 0 and cleanup_marker.is_file(), blocked.stderr
        assert rows()[(target, "result")]["status"] == "pending"
        assert rows()[(target, "result")]["receipt_id"] == old_job["receipt_id"]
        probe = execute("probe")
        assert probe.returncode == 0, probe.stderr
        assert rows()[(target, "result")]["status"] == "pending"
        assert rows()[(target, "result")]["receipt_id"] == old_job["receipt_id"]
        with db_client.engine.begin() as conn:
            assert conn.scalar(text("SELECT cleanup_due IS NOT NULL FROM nexent.evolution_trial_t WHERE trial_id=:trial"),
                               {"trial": old_job["trial_id"]})
            conn.execute(text("UPDATE nexent.evolution_trial_t SET cleanup_due=now() WHERE trial_id=:trial"),
                         {"trial": old_job["trial_id"]})
        if fault == "repeated_staging":
            repeated_exit = execute("staging")
            assert repeated_exit.returncode == 31, repeated_exit.stderr
            repeated_job = expire_interrupted()
            assert repeated_job["receipt_id"] != old_job["receipt_id"]
            assert not jobs.authorize_dispatch(old_job, 0)
            assert not jobs.finish(old_job, "pass", {"answer": "stale"})
    recovered = execute("resume")
    assert recovered.returncode == 0, recovered.stderr
    final = rows()
    assert {key: row for key, row in final.items() if key[0] == ids[0]} == {
        key: row for key, row in initial.items() if key[0] == ids[0]
    }
    assert [final[(ids[2], arm)]["status"] for arm in ("base", "result")] == ["pass", "pass"]
    assert not jobs.authorize_dispatch(old_job, 0)
    assert not jobs.authorize_dispatch(old_job, 1)
    assert not jobs.finish(old_job, "pass", {"answer": "late"})
    assert not any(path.is_file() for path in objects.rglob("*"))
    assert not jobs.claim(eid)
    journal = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
    intended = {(cid, arm) for cid in ids for arm in ("base", "result")}
    sent = {(entry["case_id"], entry["variant"]) for entry in journal}
    assert len(journal) == len(sent)
    assert sent == (intended if fault in {"staging", "dispatched"} else intended - {(target, "result")})
    record = final[(target, "result")]
    monkeypatch.setattr(service, "require_business_agent_edit", lambda *_: None)
    report = service.experiment_report(TENANT, EDITOR, eid)
    screening = report["screening"]
    if fault == "staging":
        assert record["status"] == "pass" and record["receipt_id"] != old_job["receipt_id"]
        assert screening["status"] == "eligible"
    else:
        assert record["status"] == "error" and record["result"] == {"error": "worker_interrupted"}
        assert target in screening["missing"]["unverified_trials"]
        assert screening["status"] != "eligible"


def worker(eid, target, objects, calls, cleanup_marker, mode):
    from contracts.agentos import EvaluationAgentResult, ReplayReceipt, RunAttachment
    from infrastructure.rdb.client import db_client
    from management.db.evaluation import experiments as jobs
    from management.services.evaluation import experiments as service, replay_cases
    from nexent.core.concurrency import shutdown_fallback_thread_manager

    async def snapshot(_request, _tenant, _user, arm):
        return ReplaySpec(arm)

    async def no_exclusions(*_args):
        return set()

    def read_case(_tenant, _user, _agent, _version, case_id):
        with db_client.engine.connect() as conn:
            return dict(conn.execute(text(
                "SELECT digest, task FROM nexent.evolution_replay_case_t WHERE case_id=:id"
            ), {"id": case_id}).mappings().one())

    def stage(tenant, user, agent, version, case_id, receipt, turn):
        task = read_case(tenant, user, agent, version, case_id)["task"]
        return replay_cases.stage_verified_input(tenant, user, task, receipt, turn, lambda _: ATTACHMENT)

    class RuntimeFixture:
        def __init__(self, *_args):
            pass

        async def run_prepared_evaluation(self, request, _user, _tenant):
            with db_client.engine.connect() as conn:
                row = conn.execute(text("""
                    SELECT case_id, variant, dispatch_started FROM nexent.evolution_trial_t
                    WHERE trial_id=:id AND receipt_id=:receipt
                """), {"id": -request.conversation_id, "receipt": request.replay_trial_id}).mappings().one()
            assert row["dispatch_started"]
            with calls.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"case_id": row["case_id"], "variant": row["variant"]}) + "\n")
            wrong = row["case_id"] == target and row["variant"] == "base"
            return EvaluationAgentResult(
                answer="fail" if wrong else "pass", events=[],
                replay_receipt=ReplayReceipt(trial_id=request.replay_trial_id, outcome="completed"),
            )

    def write(key, content):
        path = objects / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if mode == "staging":
            with db_client.engine.connect() as conn:
                arm = conn.scalar(text("SELECT variant FROM nexent.evolution_trial_t WHERE receipt_id=:receipt"),
                                  {"receipt": path.parent.name})
            if arm == "result":
                os._exit(31)

    def remove(key):
        path = objects / key
        if mode == "cleanup_failed" and path.is_file():
            cleanup_marker.touch()
            return False, None
        path.unlink(missing_ok=True)
        return True, None

    finish = jobs.finish

    def persist(job, status, result):
        if mode == "dispatched" and job["case_id"] == target and job["variant"] == "result":
            assert status == "pass", result
            os._exit(31)
        return finish(job, status, result)

    service._snapshot = snapshot
    # The outcome fingerprint is frozen for each arm and checked by the actual aggregate.
    service.snapshot_digest = lambda spec: spec.arm
    service._excluded_sources = no_exclusions
    service.get_development_case = read_case
    service.stage_case_input = stage
    service.require_business_agent_edit = lambda *_: None
    service.AgentOSClient = RuntimeFixture
    service._grade = lambda _req, _job, _task, result: {"status": result.answer, "evaluator_id": 7, "evaluator_version": 1}
    jobs.finish = persist
    replay_cases._write = write
    replay_cases._read_bounded = lambda key, _limit: (objects / key).read_bytes()
    replay_cases.minio_client = SimpleNamespace(delete_file=remove)
    replay_cases.build_evaluation_input = lambda query, files, *_: ReplayInput(
        query, [RunAttachment(name=file["name"], url=f"s3://fixture/{file['object_name']}") for file in files],
    )

    async def run():
        try:
            async with service.experiment_lifespan():
                while True:
                    if mode == "cleanup_failed" and cleanup_marker.is_file():
                        return
                    trials = await asyncio.to_thread(jobs.trials, TENANT, eid)
                    if mode == "probe":
                        active = [trial for trial in trials if trial["status"] in {"pending", "running"}]
                        if len(active) == 1 and active[0]["case_id"] == target and active[0]["status"] == "pending":
                            return
                    terminal = all(trial["status"] not in {"pending", "running"} for trial in trials)
                    if terminal and (mode != "resume" or not any(path.is_file() for path in objects.rglob("*"))):
                        return
                    await asyncio.sleep(0.05)
        finally:
            await shutdown_fallback_thread_manager()

    asyncio.run(asyncio.wait_for(run(), timeout=30))


if __name__ == "__main__":
    _, eid, target, objects, calls, cleanup_marker, mode = sys.argv
    worker(int(eid), int(target), Path(objects), Path(calls), Path(cleanup_marker), mode)
