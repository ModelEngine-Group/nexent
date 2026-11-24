# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
from contextlib import contextmanager

from sqlalchemy import text

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from infrastructure.rdb.client import db_client, get_db_session
from infrastructure.rdb.evolution_model_charges import lock_model_charges
from management.db.evaluation.confirmation_locks import locked_protocol


def execution_slot(lock_id):
    return exclusive_job_slot(f"nexent.confirmation.run/{lock_id}", "Independent comparison is already running")


@contextmanager
def exclusive_job_slot(key, busy_message):
    # A backend session lock releases on process death without holding a long-running SQL transaction.
    key = {"key": key}
    with db_client.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if not conn.scalar(text("SELECT pg_try_advisory_lock(hashtextextended(:key,0))"), key):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, busy_message)
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"), key)


def run_authority(tenant, lock_id):
    with get_db_session() as session:
        row = (
            session.execute(
                text("""
            SELECT l.locked_by,c.submitted_by,e.plan,l.model_metering FROM nexent.evolution_confirmation_lock_t l
              JOIN nexent.evolution_confirmation_candidate_t c USING (experiment_id)
              JOIN nexent.evolution_experiment_t e USING (experiment_id)
             WHERE e.tenant_id=:tenant AND l.lock_id=:id AND NOT e.cancelled
        """),
                {"tenant": tenant, "id": lock_id},
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
        protocol = locked_protocol(tenant, row["locked_by"], lock_id, transaction=session)
        return dict(row), protocol


def result_for_experiment(tenant, eid):
    with get_db_session() as session:
        return [
            dict(row)
            for row in session.execute(
                text("""
            SELECT l.lock_id,r.summary FROM nexent.evolution_confirmation_lock_t l
              JOIN nexent.evolution_experiment_t e USING (experiment_id)
              LEFT JOIN nexent.evolution_confirmation_result_t r ON r.lock_id=l.lock_id AND r.lock_digest=l.digest
             WHERE e.tenant_id=:tenant AND e.experiment_id=:eid ORDER BY l.lock_id
        """),
                {"tenant": tenant, "eid": eid},
            ).mappings()
        ]


def freeze_model_metering(tenant, curator, protocol, allowance):
    limits = {
        "revision": allowance.revision(),
        "max_model_tokens": allowance.daily_tokens,
        "max_model_micros": allowance.daily_micros,
    }
    with get_db_session() as session:
        lock_model_charges(session, tenant)
        if locked_protocol(tenant, curator, protocol["lock_id"], transaction=session) != protocol:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Independent protocol changed")
        stored = session.scalar(text("""
            UPDATE nexent.evolution_confirmation_lock_t
            SET model_metering=COALESCE(model_metering,CAST(:limits AS jsonb))
            WHERE lock_id=:id RETURNING model_metering
        """), {"id": protocol["lock_id"], "limits": json.dumps(limits)})
        if stored != limits:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Independent billing configuration changed")


def authorize_model_attempt(tenant, curator, protocol, editor, max_seconds):
    with get_db_session() as session:
        lock_model_charges(session, tenant)
        lock_id = protocol["lock_id"]
        if locked_protocol(tenant, curator, lock_id, transaction=session) != protocol:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Independent protocol changed")
        # The runner holds the execution slot. Replace a lease left behind by an interrupted worker.
        _retire_open_attempts(session, tenant, lock_id)
        return session.scalar(text("""
            INSERT INTO nexent.evolution_generation_attempt_t
                (tenant_id,source_digest,model_id,created_by,lease_until,metering_revision,confirmation_lock_id)
            SELECT :tenant, repeat('0',64), NULL, c.submitted_by,
                   clock_timestamp()+make_interval(secs=>:seconds), l.model_metering->>'revision', l.lock_id
              FROM nexent.evolution_confirmation_lock_t l
              JOIN nexent.evolution_confirmation_candidate_t c USING (experiment_id)
             WHERE l.lock_id=:id AND c.submitted_by=:editor AND NOT l.budget_stopped AND l.model_metering IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM nexent.evolution_confirmation_result_t r WHERE r.lock_id=l.lock_id)
            RETURNING attempt_id
        """), {"tenant": tenant, "id": lock_id, "editor": editor, "seconds": max_seconds})


def close_model_attempt(tenant, lock_id, attempt):
    with get_db_session() as session:
        session.execute(text("""
            UPDATE nexent.evolution_generation_attempt_t SET completed_at=clock_timestamp()
            WHERE tenant_id=:tenant AND confirmation_lock_id=:id AND attempt_id=:attempt AND completed_at IS NULL
        """), {"tenant": tenant, "id": lock_id, "attempt": attempt})


def close_interrupted_attempts(tenant, lock_id):
    with get_db_session() as session:
        lock_model_charges(session, tenant)
        _retire_open_attempts(session, tenant, lock_id)


def _retire_open_attempts(session, tenant, lock_id):
    session.execute(text("""
        UPDATE nexent.evolution_generation_attempt_t SET completed_at=clock_timestamp()
        WHERE tenant_id=:tenant AND confirmation_lock_id=:id AND completed_at IS NULL
    """), {"tenant": tenant, "id": lock_id})


def _add_model_usage(session, tenant, lock_id, summary):
    usage = session.execute(text("""
        SELECT l.budget_stopped, count(c.charge_id) AS calls, count(c.reported_input) AS reported_calls,
               COALESCE(sum(c.reported_input),0) AS input_tokens,
               COALESCE(sum(c.reported_output),0) AS output_tokens,
               COALESCE(sum(c.reported_micros),0) AS cost_micros,
               COALESCE(sum(c.reserved_input+c.reserved_output) FILTER (WHERE c.reported_input IS NULL),0)
                  AS unsettled_tokens,
               COALESCE(sum(c.reserved_micros) FILTER (WHERE c.reported_input IS NULL),0)
                  AS unsettled_micros
          FROM nexent.evolution_confirmation_lock_t l LEFT JOIN nexent.evolution_model_charge_t c
            ON c.confirmation_lock_id=l.lock_id AND c.tenant_id=:tenant
         WHERE l.lock_id=:id AND l.model_metering IS NOT NULL GROUP BY l.lock_id
    """), {"tenant": tenant, "id": lock_id}).mappings().one_or_none()
    if usage is None:
        return summary
    report = {key: int(value) for key, value in usage.items() if key != "budget_stopped"}
    if not usage["budget_stopped"]:
        return {**summary, "model_usage": report}
    return {
        **summary, "model_usage": report,
        "missing": [*summary["missing"], "confirmation_model_budget_exceeded"],
        "decision": "insufficient" if summary["decision"] == "passed" else summary["decision"],
    }


def finalize(tenant, curator, protocol, summary):
    with get_db_session() as session:
        lock_model_charges(session, tenant)
        actual = locked_protocol(tenant, curator, protocol["lock_id"], transaction=session)
        if actual != protocol:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Independent protocol changed")
        summary = _add_model_usage(session, tenant, protocol["lock_id"], summary)
        params = {
            "id": protocol["lock_id"],
            "digest": protocol["digest"],
            "decision": summary["decision"],
            "summary": json.dumps(summary),
        }
        session.execute(
            text("""
            INSERT INTO nexent.evolution_confirmation_result_t (lock_id,lock_digest,decision,summary)
            VALUES (:id,:digest,:decision,CAST(:summary AS jsonb)) ON CONFLICT DO NOTHING
        """),
            params,
        )
        return session.execute(
            text("""
            SELECT summary FROM nexent.evolution_confirmation_result_t WHERE lock_id=:id AND lock_digest=:digest
        """),
            params,
        ).scalar_one()
