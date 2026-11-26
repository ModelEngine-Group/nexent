# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Business evaluation sets backed by references to immutable replay tasks."""

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from infrastructure.rdb.client import get_db_session
from management.db.evaluation.models import EvaluationSet


MAX_BUSINESS_SET_CASES = 100


def _scope(tenant, agent):
    return select(EvaluationSet).where(EvaluationSet.tenant_id == tenant,
                                       EvaluationSet.business_agent_id == agent,
                                       EvaluationSet.delete_flag == "N")


def _summary(row):
    return {"evaluation_set_id": row.evaluation_set_id, "business_agent_id": row.business_agent_id,
            "name": row.name, "description": row.description, "case_count": row.case_count}


def create_set(session, tenant, agent, user, name):
    name = name.strip()
    if not 1 <= len(name) <= 100:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Provide an evaluation set name")
    statement = insert(EvaluationSet).values(
        tenant_id=tenant, business_agent_id=agent, name=name, case_count=0,
        created_by=user, updated_by=user, delete_flag="N",
    ).on_conflict_do_nothing().returning(EvaluationSet)
    row = session.scalar(statement)
    if row is None:
        row = session.execute(_scope(tenant, agent).where(func.lower(EvaluationSet.name) == func.lower(name))).scalar_one()
    return _summary(row)


def get_set(session, tenant, agent, set_id, *, lock=False):
    query = _scope(tenant, agent).where(EvaluationSet.evaluation_set_id == set_id)
    row = session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Business evaluation set not found")
    return row


def list_sets(tenant, agent):
    with get_db_session() as session:
        rows = session.scalars(_scope(tenant, agent).order_by(EvaluationSet.update_time.desc(),
                                                             EvaluationSet.evaluation_set_id.desc()))
        return [_summary(row) for row in rows]


def list_case_choices(tenant, agent):
    with get_db_session() as session:
        return [dict(row) for row in session.execute(text("""
            SELECT * FROM (
                SELECT DISTINCT ON (digest) case_id, version_no, digest, task->>'family' AS family,
                    left(task->>'query', 160) AS query, task ? 'trace_source' AS from_trace
                FROM nexent.evolution_replay_case_t
                WHERE tenant_id=:tenant AND agent_id=:agent ORDER BY digest, case_id
            ) tasks ORDER BY case_id DESC LIMIT 200
        """), {"tenant": tenant, "agent": agent}).mappings()]


def read_set(session, tenant, agent, set_id, *, include_tasks=False):
    group = get_set(session, tenant, agent, set_id)
    rows = session.execute(text("""
        SELECT c.case_id, c.version_no, c.digest, c.task->>'family' AS family,
               left(c.task->>'query', 160) AS query, c.task ? 'trace_source' AS from_trace,
               CASE WHEN :include_tasks THEN c.task ELSE NULL END AS task
          FROM nexent.evaluation_set_replay_case_t m JOIN nexent.evolution_replay_case_t c
            ON c.case_id=m.source_case_id AND c.digest=m.digest
         WHERE m.evaluation_set_id=:set_id AND c.tenant_id=:tenant AND c.agent_id=:agent
           AND m.delete_flag='N' ORDER BY m.create_time, c.case_id
    """), {"set_id": set_id, "tenant": tenant, "agent": agent, "include_tasks": include_tasks}).mappings()
    return {**_summary(group), "cases": [dict(row) for row in rows]}


def add_cases(session, tenant, agent, user, set_id, case_ids):
    group = get_set(session, tenant, agent, set_id, lock=True)
    unique_ids = sorted(set(case_ids))
    rows = session.execute(text("""
        SELECT case_id, digest FROM nexent.evolution_replay_case_t
         WHERE tenant_id=:tenant AND agent_id=:agent AND case_id=ANY(:ids)
         ORDER BY case_id
    """), {"tenant": tenant, "agent": agent, "ids": unique_ids}).mappings().all()
    if len(rows) != len(unique_ids):
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "A replay task is outside this Agent")
    for row in rows:
        session.execute(text("""
            INSERT INTO nexent.evaluation_set_replay_case_t
                (evaluation_set_id, source_case_id, digest, created_by, updated_by)
            VALUES (:set_id, :case_id, :digest, :user, :user)
            ON CONFLICT (evaluation_set_id, digest) DO UPDATE
            SET delete_flag='N', updated_by=:user, update_time=now()
            WHERE evaluation_set_replay_case_t.delete_flag='Y'
        """), {"set_id": set_id, "user": user, **row})
    return _update_count(session, group, user)


def remove_case(session, tenant, agent, user, set_id, case_id):
    group = get_set(session, tenant, agent, set_id, lock=True)
    session.execute(text("""
        UPDATE nexent.evaluation_set_replay_case_t SET delete_flag='Y', updated_by=:user, update_time=now()
         WHERE evaluation_set_id=:set_id AND source_case_id=:case_id AND delete_flag='N'
    """), {"set_id": set_id, "case_id": case_id, "user": user})
    return _update_count(session, group, user)


def _update_count(session, group, user):
    count = session.scalar(text("""
        SELECT count(*) FROM nexent.evaluation_set_replay_case_t
         WHERE evaluation_set_id=:set_id AND delete_flag='N'
    """), {"set_id": group.evaluation_set_id})
    if count > MAX_BUSINESS_SET_CASES:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, f"An evaluation set can contain at most {MAX_BUSINESS_SET_CASES} tasks")
    group.case_count = count
    group.updated_by = user
    return _summary(group)
