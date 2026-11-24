# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read the frozen packages only for the released Agent's authorized Skill binding."""

from sqlalchemy import text

from infrastructure.rdb.client import get_db_session


def read_bound_skill_candidate(tenant_id, agent_id, version_no, candidate_id):
    with get_db_session() as session:
        row = session.execute(text("""
            SELECT c.skill_id, c.skill_name, c.base_digest, c.result_digest, i.skill_instance_id AS instance_id,
                c.feedback->'script_build' AS script_build, c.feedback->>'method' AS method, c.feedback->'edit'->>'old' AS source_text,
                c.feedback->'edit'->>'new' AS result_text
            FROM nexent.evolution_skill_candidate_t c
            JOIN nexent.ag_skill_instance_t i ON i.tenant_id=c.tenant_id AND i.skill_id=c.skill_id
            JOIN nexent.ag_skill_info_t s ON s.tenant_id=i.tenant_id AND s.skill_id=i.skill_id
            WHERE c.candidate_id=:candidate AND c.tenant_id=:tenant AND i.agent_id=:agent
              AND i.version_no=:version AND i.enabled AND i.delete_flag='N'
              AND (c.feedback->>'method' IS DISTINCT FROM 'S4' OR
                   (c.feedback->'script_build'->>'agent'=CAST(:agent AS text)
                    AND c.feedback->'script_build'->>'version'=CAST(:version AS text)))
              AND s.skill_name=c.skill_name AND s.delete_flag='N'
        """), dict(tenant=tenant_id, agent=agent_id, version=version_no, candidate=candidate_id)).mappings().one_or_none()
        return dict(row) if row else None


def read_scoped_skill_candidate(tenant, agent, version, candidate, *, session=None):
    with get_db_session(db_session=session) as session:
        row = session.execute(text("""
            SELECT c.candidate_id, c.result_digest, g.name, g.candidate_id AS source_candidate_id, g.digest AS source_digest
              FROM nexent.evolution_skill_candidate_t c
              JOIN nexent.evolution_release_guide_t g ON g.tenant_id=c.tenant_id AND g.agent_id=c.source_agent_id
               AND g.version_no=c.source_version_no AND g.candidate_id=c.released_guide_candidate_id
               AND g.name=c.skill_name AND g.digest=c.base_digest
             WHERE c.tenant_id=:tenant AND c.source_agent_id=:agent AND c.source_version_no=:version
               AND c.candidate_id=:candidate AND c.feedback->>'method'='S2'
        """), dict(tenant=tenant, agent=agent, version=version, candidate=candidate)).mappings().one_or_none()
        return dict(row) if row else None


def candidate_skill_row(row, bound, variant):
    if bound.get("method") == "S4":
        build = bound["script_build"]
        if row.get("script_image") not in (None, build["image"]):
            raise ValueError("The approved script requires a different sandbox image")
        return {**row, "script_image": build["image"]} if variant == "result" else row
    if bound.get("method") != "S1":
        return row
    if (bound["base_digest"] != bound["result_digest"] or (row["description"] or "") != bound["source_text"]
            or not bound["result_text"] or variant not in {"base", "result"}):
        raise ValueError("Skill discovery description is outside its approved source")
    return {**row, "description": bound["result_text"]} if variant == "result" else row


def read_new_skill_trial(tenant, agent, version, candidate_id):
    """Only resolve a proposal belonging to this published business Agent version."""
    with get_db_session() as session:
        row = session.execute(text("""
            SELECT c.candidate_id, c.name, c.description, c.digest, h.feedback->'source_keys' AS source_keys,
                   h.feedback->>'baseline_digest' AS baseline_digest
            FROM nexent.evolution_new_skill_candidate_t c
            JOIN nexent.evolution_feedback_handoff_t h ON h.feedback_id=c.feedback_id AND h.tenant_id=c.tenant_id
            WHERE c.tenant_id=:tenant AND c.agent_id=:agent AND c.version_no=:version AND c.candidate_id=:candidate
        """), dict(tenant=tenant, agent=agent, version=version, candidate=candidate_id)).mappings().one_or_none()
        return dict(row) if row else None


def proposed_skill_names(tenant, agent, version):
    with get_db_session() as session:
        return set(session.scalars(text("""
            SELECT DISTINCT name FROM nexent.evolution_new_skill_candidate_t
            WHERE tenant_id=:tenant AND agent_id=:agent AND version_no=:version
        """), dict(tenant=tenant, agent=agent, version=version)))
