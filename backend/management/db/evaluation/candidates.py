# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from hashlib import sha256

from sqlalchemy import text

from infrastructure.rdb.client import get_db_session


def text_digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def store_prompt_candidate(tenant_id, agent_id, version_no, user_id, source, result, feedback):
    values = dict(tenant=tenant_id, agent=agent_id, version=version_no,
                  source=source, result=result, base_hash=text_digest(source), result_hash=text_digest(result))
    encoded = json.dumps(feedback, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    with get_db_session() as session:
        candidate_id = session.scalar(text("""
            INSERT INTO nexent.evolution_candidate_t
                (tenant_id, agent_id, base_version_no, resource_field, source_text, result_text, base_digest, result_digest)
            VALUES (:tenant, :agent, :version, 'agent.prompt', :source, :result, :base_hash, :result_hash)
            ON CONFLICT DO NOTHING RETURNING candidate_id
        """), values)
        if candidate_id is None:
            candidate_id = session.execute(text("""
                SELECT candidate_id FROM nexent.evolution_candidate_t WHERE tenant_id=:tenant AND agent_id=:agent
                  AND base_version_no=:version AND resource_field='agent.prompt'
                  AND base_digest=:base_hash AND result_digest=:result_hash
            """), values).scalar_one()
        session.execute(text("""
            INSERT INTO nexent.evolution_candidate_feedback_t (candidate_id, created_by, feedback_digest, feedback)
            VALUES (:candidate, :user_id, :digest, CAST(:feedback AS jsonb)) ON CONFLICT DO NOTHING
        """), dict(candidate=candidate_id, user_id=user_id, digest=text_digest(encoded), feedback=encoded))
    return candidate_id


def get_prompt_candidate(tenant_id, agent_id, version_no, candidate_id):
    with get_db_session() as session:
        row = session.execute(text("""
            SELECT source_text, result_text, base_digest, result_digest FROM nexent.evolution_candidate_t
            WHERE tenant_id=:tenant AND agent_id=:agent AND base_version_no=:version
              AND candidate_id=:candidate AND resource_field='agent.prompt'
        """), dict(tenant=tenant_id, agent=agent_id, version=version_no, candidate=candidate_id)).mappings().one_or_none()
        return dict(row) if row else None


def store_skill_candidate(tenant_id, skill, user_id, base, result, feedback):
    encoded = json.dumps(feedback, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    values = dict(tenant=tenant_id, skill=skill["skill_id"], name=skill["name"], creator=user_id,
                  base=base, result=result, digest=text_digest(encoded), feedback=encoded)
    with get_db_session() as session:
        candidate = session.scalar(text("""
            INSERT INTO nexent.evolution_skill_candidate_t
                (tenant_id, skill_id, skill_name, base_digest, result_digest, created_by, feedback_digest, feedback)
            VALUES (:tenant, :skill, :name, :base, :result, :creator, :digest, CAST(:feedback AS jsonb))
            ON CONFLICT DO NOTHING RETURNING candidate_id
        """), values)
        if candidate is None:
            candidate = session.execute(text("""
                SELECT candidate_id FROM nexent.evolution_skill_candidate_t WHERE tenant_id=:tenant AND skill_id=:skill
                    AND base_digest=:base AND result_digest=:result AND created_by=:creator AND feedback_digest=:digest
            """), values).scalar_one()
        return candidate
