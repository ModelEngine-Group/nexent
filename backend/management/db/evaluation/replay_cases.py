# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
from contextlib import nullcontext
from hashlib import sha256

from sqlalchemy import text
from contracts.evolution_sources import example_source_keys

from infrastructure.rdb.client import get_db_session


def task_digest(task):
    content = json.dumps(task, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return sha256(content.encode()).hexdigest()


def save_replay_case(tenant_id, agent_id, version_no, user_id, task, *, transaction=None):
    digest = task_digest(task)
    params = dict(tenant=tenant_id, agent=agent_id, version=version_no, digest=digest,
                  creator=user_id, task=json.dumps(task, ensure_ascii=False))
    with (get_db_session() if transaction is None else nullcontext(transaction)) as session:
        case_id = session.scalar(text("""
            INSERT INTO nexent.evolution_replay_case_t (tenant_id, agent_id, version_no, digest, task, created_by)
            VALUES (:tenant, :agent, :version, :digest, CAST(:task AS jsonb), :creator)
            ON CONFLICT DO NOTHING RETURNING case_id
        """), params)
        if case_id is None:
            case_id = session.execute(text("""
                SELECT case_id FROM nexent.evolution_replay_case_t WHERE tenant_id=:tenant AND agent_id=:agent
                    AND version_no=:version AND digest=:digest
            """), params).scalar_one()
    return {"case_id": case_id, "digest": digest}


def read_replay_case(tenant_id, agent_id, version_no, case_id):
    with get_db_session() as session:
        row = session.execute(text("""
            SELECT case_id, digest, task FROM nexent.evolution_replay_case_t
            WHERE tenant_id=:tenant AND agent_id=:agent AND version_no=:version AND case_id=:case
        """), dict(tenant=tenant_id, agent=agent_id, version=version_no, case=case_id)).mappings().one_or_none()
        if row is None:
            return None
        if task_digest(row["task"]) != row["digest"]:
            raise ValueError("Replay task integrity check failed")
        return dict(row)


def set_regression_membership(tenant, agent, version, case_id, user, enabled, scoring):
    with get_db_session() as session:
        session.execute(text("""
            INSERT INTO nexent.evolution_regression_case_t
                (tenant_id, agent_id, digest, source_case_id, updated_by, enabled, scoring)
            SELECT tenant_id, agent_id, digest, case_id, :user, :enabled, CAST(:scoring AS jsonb)
              FROM nexent.evolution_replay_case_t
             WHERE tenant_id=:tenant AND agent_id=:agent AND version_no=:version AND case_id=:case
            ON CONFLICT (tenant_id, agent_id, digest) DO UPDATE SET enabled=EXCLUDED.enabled,
                updated_by=EXCLUDED.updated_by, update_time=now(),
                scoring=CASE WHEN EXCLUDED.enabled THEN EXCLUDED.scoring ELSE evolution_regression_case_t.scoring END
            WHERE evolution_regression_case_t.enabled IS DISTINCT FROM EXCLUDED.enabled OR
                  (EXCLUDED.enabled AND evolution_regression_case_t.scoring IS DISTINCT FROM EXCLUDED.scoring)
        """), dict(tenant=tenant, agent=agent, version=version, case=case_id, user=user, enabled=enabled,
                   scoring=json.dumps(scoring, ensure_ascii=False) if scoring is not None else None))


def regression_members(tenant, agent):
    with get_db_session() as session:
        return [dict(row) for row in session.execute(text("""
            SELECT r.source_case_id, r.digest, r.scoring, c.version_no AS source_version, c.task->>'family' AS family,
                   left(c.task->>'query', 160) AS query
              FROM nexent.evolution_regression_case_t r JOIN nexent.evolution_replay_case_t c
                ON c.case_id=r.source_case_id AND c.tenant_id=r.tenant_id AND c.agent_id=r.agent_id AND c.digest=r.digest
             WHERE r.tenant_id=:tenant AND r.agent_id=:agent AND r.enabled ORDER BY r.source_case_id
        """), dict(tenant=tenant, agent=agent)).mappings()]


def contains_fixed_cases(tenant, agent, case_ids, frozen_ids):
    selected, protected = set(), set()
    with get_db_session() as session:
        rows = session.execute(text("""
            SELECT c.case_id, (r.enabled IS TRUE OR c.case_id=ANY(:frozen)) AS protected,
                   c.task->>'query' AS query, c.task->>'source_group' AS source_group,
                   c.task->'attachments' AS attachments, c.task->'trace_source' AS trace_source
              FROM nexent.evolution_replay_case_t c LEFT JOIN nexent.evolution_regression_case_t r
                ON c.case_id=r.source_case_id AND c.agent_id=r.agent_id AND c.tenant_id=r.tenant_id
             WHERE c.tenant_id=:tenant AND c.agent_id=:agent
               AND (c.case_id=ANY(:ids) OR c.case_id=ANY(:frozen) OR r.enabled)
        """), dict(tenant=tenant, agent=agent, ids=case_ids, frozen=frozen_ids)).mappings()
        for row in rows:
            keys = example_source_keys(row)
            if row["protected"]:
                protected.update(keys)
            if row["case_id"] in case_ids:
                selected.update(keys)
    return bool(selected & protected)
