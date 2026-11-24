# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from time import monotonic

import pytest
from sqlalchemy import text

from local_auth_http import native_runtime, runtime


@pytest.mark.case_id("EVOLUTION-RUN-BUDGET-D3-001")
@pytest.mark.stage("D3")
def test_distributed_budget(runtime, monkeypatch):
    from contracts.evolution import DevelopmentExperimentRequest
    from infrastructure.rdb.client import db_client
    from management.db.evaluation import experiments as jobs

    engine = db_client.engine
    migrations = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        for name in ("018_evolution_replay_cases", "019_evolution_experiments"):
            cursor.execute((migrations / f"v2.9.0_{name}.sql").read_text(encoding="utf-8"))

    def submit(tenant, count):
        with engine.begin() as conn:
            ids = [conn.scalar(text("""INSERT INTO nexent.evolution_replay_case_t
                (tenant_id,agent_id,version_no,digest,task,created_by)
                VALUES (:tenant,1,1,:digest,'{}','editor') RETURNING case_id"""),
                {"tenant":tenant, "digest":str(i).zfill(64)}) for i in range(count)]
        request = DevelopmentExperimentRequest(agent_id=1, version_no=1, request_id="test",
            case_ids=ids, evaluator_id=1, candidate_type="baseline",
            budget={"max_replay_turns":count, "max_elapsed_seconds":300})
        plan = {"cases":{str(i):str(i) for i in ids}, "snapshots":{"base":"digest"},
                "request":request.model_dump(), "budget":{**request.budget.model_dump(), "planned_replay_turns":count}}
        eid = jobs.submit(tenant, "editor", request, plan)
        assert jobs.previous_submission(tenant, "editor", request) == eid
        return eid

    first, second = submit("tenant-a",5), submit("tenant-b",1)
    monkeypatch.setattr(jobs, "EVOLUTION_MAX_RUNNING_TRIALS_PER_TENANT", 1)
    barrier = Barrier(4)
    def race(_):
        barrier.wait(timeout=5)
        return jobs.claim(first)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = [job for job in pool.map(race, range(4)) if job]
    assert len(claims) == 1 and 0 < (claims[0]["monotonic_deadline"] - monotonic()) <= 300
    other = jobs.claim()
    assert other["experiment_id"] == second
    assert jobs.finish(claims[0], "pass", {"answer":"saved"})
    active = jobs.claim(first)
    with engine.begin() as conn:
        conn.execute(text("UPDATE nexent.evolution_experiment_t SET create_time=now()-interval '1 hour' WHERE experiment_id=:eid"), {"eid":first})
    assert jobs.finish(active, "pass", {"answer":"late"})
    assert jobs.claim(first) is None
    assert not jobs.finish(active, "pass", {"answer":"retried"})
    rows = jobs.trials("tenant-a",first)
    assert [r["result"] for r in rows if r["status"] == "pass"] == [{"answer":"saved"}]
    errors = [r for r in rows if r["status"] == "error"]
    assert len(errors) == 4 and all(r["result"] == {"error":"experiment_time_budget_exceeded"} for r in errors)
    assert jobs.finish(other, "pass", {"answer":"independent"})

    _verify_candidate_budget(monkeypatch)


def _verify_candidate_budget(monkeypatch):
    from contracts.constants import environment
    from contracts.errors.codes import ErrorCode
    from contracts.errors.exceptions import AppException
    from infrastructure.rdb.client import db_client
    from management.db.evaluation import generation_attempts
    from management.services.evaluation import generation_budget

    engine = db_client.engine
    migration = Path(__file__).resolve().parents[3] / "deploy/sql/migrations/v2.9.0_041_evolution_generation_attempts.sql"
    with engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        cursor.execute(migration.read_text(encoding="utf8"))

    monkeypatch.setattr(environment, "EVOLUTION_GENERATION_CONCURRENCY", 1)
    monkeypatch.setattr(environment, "EVOLUTION_GENERATION_SOURCE_ATTEMPTS", 1)
    monkeypatch.setattr(environment, "EVOLUTION_GENERATION_DAILY_ATTEMPTS", 2)
    barrier = Barrier(4)
    source = generation_budget.source_digest("S2", 123)

    def competing_submission(worker):
        barrier.wait(timeout=5)
        try:
            return generation_attempts.reserve("tenant-a", f"editor-{worker}", source, 1)
        except AppException as exc:
            assert exc.error_code == ErrorCode.COMMON_RATE_LIMIT_EXCEEDED

    with ThreadPoolExecutor(max_workers=4) as pool:
        admitted = [attempt for attempt in pool.map(competing_submission, range(4)) if attempt]
    assert len(admitted) == 1
    model_calls = []

    def model(**payload):
        model_calls.append(payload)
        return "revised"

    monkeypatch.setattr(generation_budget, "invoke_chat_prompt_in_worker", model)

    def invoke(tenant, source_key):
        return generation_budget.invoke_candidate_model(
            source=source_key, tenant_id=tenant, user_id="maintainer", model_id=1,
            system_prompt="Rewrite this rule", user_prompt="Keep unassigned items")

    another_source = generation_budget.source_digest("P1", 124)
    with pytest.raises(AppException, match="concurrency limit"):
        invoke("tenant-a", another_source)
    assert invoke("tenant-b", source) == "revised"
    assert generation_attempts.complete("tenant-a", admitted[0])
    with pytest.raises(AppException, match="attempt limit"):
        invoke("tenant-a", source)
    assert invoke("tenant-a", another_source) == "revised"
    with pytest.raises(AppException, match="attempt limit"):
        invoke("tenant-a", generation_budget.source_digest("S4", 125))
    assert [call["tenant_id"] for call in model_calls] == ["tenant-b", "tenant-a"]

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE nexent.evolution_generation_attempt_t
            SET create_time=clock_timestamp()-interval '2 days', lease_until=clock_timestamp()-interval '1 day'
            WHERE attempt_id=:attempt
        """), {"attempt": admitted[0]})
    assert not generation_attempts.complete("tenant-a", admitted[0])
    assert invoke("tenant-a", source) == "revised"

    abandoned = generation_attempts.reserve("tenant-c", "editor", source, 1)
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE nexent.evolution_generation_attempt_t SET lease_until=clock_timestamp()-interval '1 second'
            WHERE attempt_id=:attempt
        """), {"attempt": abandoned})
    assert not generation_attempts.complete("tenant-c", abandoned)
    assert invoke("tenant-c", another_source) == "revised"
    with pytest.raises(AppException, match="attempt limit"):
        invoke("tenant-c", source)
