# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from hashlib import sha256

from sqlalchemy import text

from infrastructure.rdb.client import get_db_session


def text_digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _insert_candidate(session, tenant_id, agent_id, version_no, user_id, source, result, feedback, field):
    values = dict(tenant=tenant_id, agent=agent_id, version=version_no,
                  source=source, result=result, base_hash=text_digest(source), result_hash=text_digest(result), field=field)
    encoded = json.dumps(feedback, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    candidate_id = session.scalar(text("""
        INSERT INTO nexent.evolution_candidate_t
            (tenant_id, agent_id, base_version_no, resource_field, source_text, result_text, base_digest, result_digest)
        VALUES (:tenant, :agent, :version, :field, :source, :result, :base_hash, :result_hash)
        ON CONFLICT DO NOTHING RETURNING candidate_id
    """), values)
    if candidate_id is None:
        candidate_id = session.execute(text("""
            SELECT candidate_id FROM nexent.evolution_candidate_t WHERE tenant_id=:tenant AND agent_id=:agent
              AND base_version_no=:version AND resource_field=:field
              AND base_digest=:base_hash AND result_digest=:result_hash
        """), values).scalar_one()
    session.execute(text("""
        INSERT INTO nexent.evolution_candidate_feedback_t (candidate_id, created_by, feedback_digest, feedback)
        VALUES (:candidate, :user_id, :digest, CAST(:feedback AS jsonb)) ON CONFLICT DO NOTHING
    """), dict(candidate=candidate_id, user_id=user_id, digest=text_digest(encoded), feedback=encoded))
    return candidate_id


def store_prompt_candidates(tenant, agent, version, user, source, variants, *, field="agent.prompt"):
    with get_db_session() as session:
        return [_insert_candidate(session, tenant, agent, version, user, source, result, evidence, field)
                for result, evidence in variants]


def store_prompt_candidate(tenant_id, agent_id, version_no, user_id, source, result, feedback):
    return store_prompt_candidates(tenant_id, agent_id, version_no, user_id, source, [(result, feedback)])[0]


def get_prompt_candidate(tenant_id, agent_id, version_no, candidate_id, *, field="agent.prompt"):
    with get_db_session() as session:
        row = session.execute(text("""
            SELECT source_text, result_text, base_digest, result_digest FROM nexent.evolution_candidate_t
            WHERE tenant_id=:tenant AND agent_id=:agent AND base_version_no=:version
              AND candidate_id=:candidate AND resource_field=:field
        """), dict(tenant=tenant_id, agent=agent_id, version=version_no, candidate=candidate_id, field=field)).mappings().one_or_none()
        return dict(row) if row else None


def selectable_tool_names(tenant, agent, version):
    with get_db_session() as session:
        return set(session.scalars(text("""
            SELECT t.name FROM nexent.ag_tool_info_t t JOIN nexent.ag_tool_instance_t i ON t.tool_id=i.tool_id
            WHERE i.tenant_id=:tenant AND i.agent_id=:agent AND i.version_no=:version AND i.enabled
              AND i.delete_flag='N' AND t.delete_flag='N' AND t.is_user_selectable AND t.is_available
        """), dict(tenant=tenant, agent=agent, version=version)))


def prompt_example_sources(tenant, agent_id, version, candidate_id, field="agent.prompt", method="P2"):
    with get_db_session() as session:
        rows = session.scalars(text("""
            SELECT DISTINCT jsonb_array_elements_text(f.feedback->'source_keys')
            FROM nexent.evolution_candidate_t c JOIN nexent.evolution_candidate_feedback_t f USING (candidate_id)
            WHERE c.tenant_id=:tenant AND c.agent_id=:agent AND c.base_version_no=:version
                AND c.candidate_id=:candidate AND c.resource_field=:field AND f.feedback->>'method'=:method
        """), dict(tenant=tenant, agent=agent_id, version=version, candidate=candidate_id, field=field, method=method))
        return set(rows)


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


def store_scoped_skill_candidate(tenant, user, agent, version, guide, result, feedback):
    encoded = json.dumps(feedback, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    values = dict(tenant=tenant, agent=agent, version=version, guide=guide["candidate_id"],
                  name=guide["name"], creator=user, base=guide["digest"], result=result,
                  digest=text_digest(encoded), feedback=encoded)
    with get_db_session() as session:
        candidate = session.scalar(text("""
            INSERT INTO nexent.evolution_skill_candidate_t
                (tenant_id, source_agent_id, source_version_no, released_guide_candidate_id, skill_name,
                 base_digest, result_digest, created_by, feedback_digest, feedback)
            SELECT :tenant, :agent, :version, :guide, :name, :base, :result, :creator, :digest, CAST(:feedback AS jsonb)
             WHERE EXISTS (SELECT 1 FROM nexent.evolution_release_guide_t g WHERE g.tenant_id=:tenant
               AND g.agent_id=:agent AND g.version_no=:version AND g.candidate_id=:guide AND g.name=:name AND g.digest=:base)
            ON CONFLICT DO NOTHING RETURNING candidate_id
        """), values)
        if candidate is None:
            candidate = session.scalar(text("""
                SELECT c.candidate_id FROM nexent.evolution_skill_candidate_t c
                  JOIN nexent.evolution_release_guide_t g ON g.tenant_id=c.tenant_id AND g.agent_id=c.source_agent_id
                    AND g.version_no=c.source_version_no AND g.candidate_id=c.released_guide_candidate_id
                    AND g.name=c.skill_name AND g.digest=c.base_digest
                 WHERE c.tenant_id=:tenant AND c.source_agent_id=:agent AND c.source_version_no=:version
                   AND c.released_guide_candidate_id=:guide AND c.base_digest=:base AND c.result_digest=:result
                   AND c.created_by=:creator AND c.feedback_digest=:digest
            """), values)
        return candidate
