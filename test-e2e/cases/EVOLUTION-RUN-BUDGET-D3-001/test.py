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
    runtime[3].TableBase.metadata.create_all(engine)
    migrations = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        for name in ("018_evolution_replay_cases", "019_evolution_experiments", "028_evolution_confirmation_suites",
                     "029_evolution_confirmation_locks", "030_evolution_confirmation_results",
                     "003_conversation_run_admission", "011_trajectory", "015_conversation_evolution",
                     "021_evolution_online_reviews",
                     "041_evolution_generation_attempts", "043_evolution_model_charges",
                     "044_evolution_evaluation_metering", "045_evolution_confirmation_metering",
                     "046_evolution_online_diagnosis", "047_evolution_development_recovery"):
            cursor.execute((migrations / f"v2.9.0_{name}.sql").read_text(encoding="utf-8"))

    def submit(tenant, count, metering=None, editor="editor"):
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
        if metering:
            plan["metering"] = metering
        eid = jobs.submit(tenant, editor, request, plan)
        assert jobs.previous_submission(tenant, editor, request) == eid
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
    _verify_provider_quota(monkeypatch)
    _verify_experiment_quota(monkeypatch, submit)
    _verify_confirmation_quota(monkeypatch, submit)


def _verify_candidate_budget(monkeypatch):
    from contracts.constants import environment
    from contracts.errors.codes import ErrorCode
    from contracts.errors.exceptions import AppException
    from infrastructure.rdb.client import db_client
    from management.db.evaluation import generation_attempts
    from management.services.evaluation import generation_budget

    engine = db_client.engine
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



def _verify_provider_quota(monkeypatch):
    import json
    from types import SimpleNamespace

    from contracts.constants import environment
    from contracts.evolution_metering import generation_budget
    from infrastructure.rdb.client import db_client
    from management.db.evaluation.generation_attempts import complete, reserve, stopped
    from nexent.core.models.wire_budget import ModelWireBudgetExceeded, model_wire_budget
    from runtime.model.evolution_meter import meter_generation

    monkeypatch.setattr(environment, "EVOLUTION_GENERATION_CONCURRENCY", 2)
    tariff = dict(max_input_tokens=100, max_output_tokens=50, input_micros_per_million=2_000_000,
                  output_micros_per_million=3_000_000)
    token_limit = dict(daily_tokens=180, daily_micros=1000, models={"1": tariff})
    fee_limit = dict(daily_tokens=1000, daily_micros=360, models={"1": tariff})
    monkeypatch.setattr(environment, "EVOLUTION_GENERATION_METERING",
                        json.dumps({"meter": token_limit, "fee": fee_limit, "overflow": token_limit, "stale": token_limit}))
    for tenant in ("meter", "fee"):
        actor = SimpleNamespace(tenant_id=tenant, user_id="creator")
        attempt = reserve(tenant, actor.user_id, "d" * 64, 1, metering_revision=generation_budget(actor.tenant_id).revision())
        assert not complete(tenant, attempt), "A metered job cannot complete without a wire reservation"
        with pytest.raises(ModelWireBudgetExceeded), meter_generation(attempt, 1, actor):
            charge = model_wire_budget.get()
            wire = {"max_tokens": 99}
            settle = charge(wire)
            assert wire["max_tokens"] == 50
            # Even when a driver catches a refusal, the scope must stop the job.
            with pytest.raises(ModelWireBudgetExceeded):
                charge({})
        # The previous accepted dispatch may report its usage after another was refused.
        settle(3, 1)
        assert stopped(tenant, attempt) and not complete(tenant, attempt)
        retry = reserve(tenant, actor.user_id, "e" * 64, 1, metering_revision=generation_budget(actor.tenant_id).revision())
        with meter_generation(retry, 1, actor):
            model_wire_budget.get()({})(5, 3)
        assert complete(tenant, retry)

    revision_actor = SimpleNamespace(tenant_id="stale", user_id="creator")
    mismatched = reserve("stale", revision_actor.user_id, "g" * 64, 1, metering_revision="x" * 64)
    with pytest.raises(ModelWireBudgetExceeded), meter_generation(mismatched, 1, revision_actor):
        model_wire_budget.get()({})

    actor = SimpleNamespace(tenant_id="overflow", user_id="creator")
    attempt = reserve("overflow", actor.user_id, "f" * 64, 1, metering_revision=generation_budget(actor.tenant_id).revision())
    with pytest.raises(ModelWireBudgetExceeded, match="exceeds"), meter_generation(attempt, 1, actor):
        model_wire_budget.get()({})(101, 4)
    assert stopped("overflow", attempt)
    with db_client.engine.connect() as conn:
        row = conn.execute(text("""SELECT reserved_input, reserved_output, reserved_micros,
            reported_input, reported_output, reported_micros FROM nexent.evolution_model_charge_t
            WHERE tenant_id='overflow'""")).one()
        assert tuple(row) == (100, 50, 350, 101, 4, 214)



def _verify_experiment_quota(monkeypatch, submit):
    import json
    from types import SimpleNamespace

    from contracts.constants import environment
    from contracts.evolution_metering import evaluation_budget
    from management.db.evaluation import experiments as jobs, generation_attempts
    from nexent.core.models.wire_budget import ModelWireBudgetExceeded, model_wire_budget
    from runtime.model.evolution_meter import meter_evaluation

    tenant = "metered-replay"
    plan = dict(daily_tokens=900, daily_micros=900, models={
        str(model): dict(max_input_tokens=40, max_output_tokens=20, input_micros_per_million=1_000_000,
                         output_micros_per_million=1_000_000) for model in (2, 3)
    })
    monkeypatch.setattr(environment, "EVOLUTION_EVALUATION_METERING", json.dumps({tenant: plan}))
    actor = SimpleNamespace(tenant_id=tenant, user_id="editor")
    eid = submit(tenant, 3, dict(revision=evaluation_budget(tenant).revision(),
                                 max_model_tokens=900, max_model_micros=70))
    first = jobs.claim(eid)
    first_id = jobs.authorize_model_attempt(first, 30)
    with meter_evaluation(first_id, actor):
        model_wire_budget.get()({}, 2)(5, 4)
    assert jobs.finish(first, "pass", {"answer": "graded"})
    with pytest.raises(ModelWireBudgetExceeded), meter_evaluation(first_id, actor, model=3):
        model_wire_budget.get()({})
    second = jobs.claim(eid)
    second_id = jobs.authorize_model_attempt(second, 30)
    with meter_evaluation(second_id, actor, model=3):
        model_wire_budget.get()({})(4, 3)
    with pytest.raises(ModelWireBudgetExceeded), meter_evaluation(second_id, actor, model=3):
        model_wire_budget.get()({})
    assert jobs.finish(second, "invalid", {"error": "experiment_model_budget_exceeded"})
    assert jobs.claim(eid) is None
    rows = jobs.trials(tenant, eid)
    assert [row["status"] for row in rows] == ["pass", "invalid", "invalid"]
    assert rows[0]["result"] == {"answer": "graded"}
    assert rows[2]["result"] == {"error": "experiment_model_budget_exceeded"}
    budget = jobs.model_budget_report(tenant, eid)
    assert (budget["reported_micros"], budget["calls"], budget["reported_calls"]) == (16, 2, 2)
    assert budget["stopped_reason"] == "experiment_model_budget_exceeded"
    # A replay entitlement cannot debit the generation pool, and vice versa.
    ordinary = generation_attempts.reserve(tenant, actor.user_id, "a"*64, 3)
    with pytest.raises(ModelWireBudgetExceeded), meter_evaluation(ordinary, actor, model=3):
        model_wire_budget.get()({})


def _verify_confirmation_quota(monkeypatch, submit):
    import json
    from types import SimpleNamespace

    from contracts.constants import environment
    from contracts.errors.exceptions import AppException
    from contracts.evolution_metering import confirmation_budget
    from contracts.evolution_sources import task_digest
    from infrastructure.rdb.account_record import UserAccount, UserTenant
    from infrastructure.rdb.client import db_client, get_db_session
    from management.db.evaluation import confirmation_runs as confirmation, generation_attempts
    from nexent.core.models.wire_budget import ModelWireBudgetExceeded, model_wire_budget
    from runtime.model.evolution_meter import meter_evaluation

    tenant = "tenant-native"
    curator, editor = "independent-reviewer", "candidate-editor"
    with get_db_session() as session:
        for user, role in ((curator, "USER"), (editor, "DEV")):
            session.add(UserAccount(user_id=user, user_roles=[role], delete_flag="N"))
            session.add(UserTenant(user_id=user, tenant_id=tenant, delete_flag="N"))
    eid = submit(tenant, 1, editor=editor)
    tariff = dict(max_input_tokens=40, max_output_tokens=20, input_micros_per_million=1_000_000,
                  output_micros_per_million=1_000_000)
    config = dict(daily_tokens=900, daily_micros=74, models={"2": tariff, "3": tariff})
    policy, manifest, recipe = {}, {"cases": ["synthetic private fingerprint"]}, {"candidate": eid}
    with db_client.engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO nexent.evolution_confirmation_curator_t (tenant_id,agent_id,user_id,enabled,updated_by)
            VALUES (:tenant,1,:curator,true,:curator)
        """), dict(tenant=tenant, curator=curator))
        suite_id = conn.scalar(text("""
            INSERT INTO nexent.evolution_confirmation_suite_t
                (tenant_id,agent_id,version_no,digest,manifest,created_by)
            VALUES (:tenant,1,1,:digest,CAST(:manifest AS jsonb),:curator) RETURNING suite_id
        """), dict(tenant=tenant, digest=task_digest(manifest), manifest=json.dumps(manifest), curator=curator))
        conn.execute(text("""
            INSERT INTO nexent.evolution_confirmation_candidate_t (experiment_id,digest,recipe,submitted_by)
            VALUES (:eid,:digest,CAST(:recipe AS jsonb),:editor)
        """), dict(eid=eid, digest=task_digest(recipe), recipe=json.dumps(recipe), editor=editor))
        lock = conn.scalar(text("""
            INSERT INTO nexent.evolution_confirmation_lock_t (suite_id,experiment_id,digest,policy,locked_by)
            VALUES (:suite,:eid,:digest,CAST(:policy AS jsonb),:curator) RETURNING lock_id
        """), dict(suite=suite_id, eid=eid, policy=json.dumps(policy), curator=curator,
                  digest=task_digest([tenant, suite_id, task_digest(manifest), eid, task_digest(recipe), policy])))

    _, protocol = confirmation.run_authority(tenant, lock)
    monkeypatch.setattr(environment, "EVOLUTION_CONFIRMATION_METERING", json.dumps({tenant: config}))
    # Identical tariff revisions in the two pools still cannot reuse each other's permits.
    monkeypatch.setattr(environment, "EVOLUTION_EVALUATION_METERING", json.dumps({tenant: config}))
    allowance = confirmation_budget(tenant)
    confirmation.freeze_model_metering(tenant, curator, protocol, allowance)
    with pytest.raises(AppException, match="billing configuration changed"):
        confirmation.freeze_model_metering(tenant, curator, protocol, allowance.model_copy(update={"daily_tokens": 899}))
    actor = SimpleNamespace(tenant_id=tenant, user_id=editor)
    old = confirmation.authorize_model_attempt(tenant, curator, protocol, editor, 30)
    current = confirmation.authorize_model_attempt(tenant, curator, protocol, editor, 30)
    with pytest.raises(ModelWireBudgetExceeded), meter_evaluation(old, actor, model=2, confirmation=True):
        model_wire_budget.get()({})
    with pytest.raises(ModelWireBudgetExceeded), meter_evaluation(current, actor, model=2):
        model_wire_budget.get()({})
    assert not generation_attempts.complete(tenant, current)

    def set_grant(enabled):
        with db_client.engine.begin() as conn:
            conn.execute(text("""UPDATE nexent.evolution_confirmation_curator_t
                SET enabled=:enabled,update_time=clock_timestamp() WHERE user_id=:curator"""),
                dict(enabled=enabled, curator=curator))

    set_grant(False)
    with pytest.raises(ModelWireBudgetExceeded), meter_evaluation(current, actor, model=2, confirmation=True):
        model_wire_budget.get()({})
    set_grant(True)
    with pytest.raises(ModelWireBudgetExceeded), meter_evaluation(current, actor, model=2, confirmation=True):
        model_wire_budget.get()({})
    current = confirmation.authorize_model_attempt(tenant, curator, protocol, editor, 30)
    with meter_evaluation(current, actor, confirmation=True):
        model_wire_budget.get()({}, 2)(5, 4)
    with meter_evaluation(current, actor, model=3, confirmation=True):
        model_wire_budget.get()({})(4, 3)
    with pytest.raises(ModelWireBudgetExceeded), meter_evaluation(current, actor, model=3, confirmation=True):
        model_wire_budget.get()({})
    assert not confirmation.authorize_model_attempt(tenant, curator, protocol, editor, 30)
    measured = {"decision": "passed", "valid_pairs": 1, "missing": []}
    result = confirmation.finalize(tenant, curator, protocol, measured)
    assert result == {
        "decision": "insufficient", "valid_pairs": 1, "missing": ["confirmation_model_budget_exceeded"],
        "model_usage": {"calls": 2, "reported_calls": 2, "input_tokens": 9, "output_tokens": 7,
                        "cost_micros": 16, "unsettled_tokens": 0, "unsettled_micros": 0},
    }
    assert confirmation.result_for_experiment(tenant, eid) == [{"lock_id": lock, "summary": result}]
    with db_client.engine.connect() as conn:
        stored = conn.execute(text("""
            SELECT a.source_digest,a.trial_id,a.trial_receipt,c.model_id,c.experiment_id
            FROM nexent.evolution_model_charge_t c JOIN nexent.evolution_generation_attempt_t a USING (attempt_id)
            WHERE c.confirmation_lock_id=:id ORDER BY c.charge_id
        """), {"id": lock}).all()
        assert stored == [("0"*64, None, None, 2, None), ("0"*64, None, None, 3, None)]
