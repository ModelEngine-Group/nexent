# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
from contextlib import contextmanager

from sqlalchemy import text

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from infrastructure.rdb.client import db_client, get_db_session
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
            SELECT l.locked_by,c.submitted_by,e.plan FROM nexent.evolution_confirmation_lock_t l
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


def finalize(tenant, curator, protocol, summary):
    with get_db_session() as session:
        actual = locked_protocol(tenant, curator, protocol["lock_id"], transaction=session)
        if actual != protocol:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Independent protocol changed")
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
