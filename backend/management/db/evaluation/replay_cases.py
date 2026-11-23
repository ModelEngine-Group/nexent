# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
from hashlib import sha256

from sqlalchemy import text

from infrastructure.rdb.client import get_db_session


def task_digest(task):
    content = json.dumps(task, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return sha256(content.encode()).hexdigest()


def save_replay_case(tenant_id, agent_id, version_no, user_id, task):
    digest = task_digest(task)
    params = dict(tenant=tenant_id, agent=agent_id, version=version_no, digest=digest,
                  creator=user_id, task=json.dumps(task, ensure_ascii=False))
    with get_db_session() as session:
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
