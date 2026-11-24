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
