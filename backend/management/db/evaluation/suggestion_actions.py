# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve a committed chat receipt and the Skill candidate approved for its suggestion."""

from sqlalchemy import text

from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_state import tenant_membership_matches


def receipt_target(tenant, user, conversation, message, candidate=None):
    with get_db_session() as session:
        if not tenant_membership_matches(session, user, tenant):
            return None
        row = session.execute(text("""
            SELECT s.suggestion_id, s.agent_id, s.version_no, s.skill_id, s.released_guide_candidate_id,
                   e.experiment_id, chosen.candidate_id, chosen.skill_name, chosen.base_digest,
                   chosen.result_digest, chosen.feedback
              FROM nexent.conversation_run_admission_t a
              JOIN nexent.conversation_record_t r ON r.conversation_id=a.conversation_id
                   AND r.created_by=a.created_by AND r.delete_flag='N'
              JOIN nexent.conversation_message_t m ON m.message_id=a.prepared_assistant_id
                   AND m.conversation_id=r.conversation_id AND m.delete_flag='N'
              JOIN nexent.evolution_suggestion_t s ON s.tenant_id=a.tenant_id AND s.submitter_id=a.created_by
                   AND CAST(s.suggestion_id AS text)=a.evolution_reply->>'suggestion_id' AND s.status='submitted'
              JOIN nexent.conversation_record_t source ON source.conversation_id=s.conversation_id
                   AND source.created_by=s.submitter_id AND source.delete_flag='N'
              LEFT JOIN nexent.evolution_experiment_t e ON e.experiment_id=s.experiment_id
                   AND e.tenant_id=s.tenant_id AND e.agent_id=s.agent_id AND e.version_no=s.version_no
              LEFT JOIN LATERAL (
                  SELECT c.candidate_id, c.skill_name, c.base_digest, c.result_digest, c.feedback
                    FROM nexent.evolution_skill_candidate_t c
                    LEFT JOIN nexent.evolution_feedback_handoff_t f ON f.tenant_id=c.tenant_id
                         AND CAST(f.feedback_id AS text)=c.feedback->>'feedback_id'
                   WHERE c.tenant_id=s.tenant_id AND c.feedback->>'method'='S2'
                     AND (CAST(:candidate AS bigint) IS NULL OR c.candidate_id=:candidate)
                     AND ((f.feedback->>'suggestion_id'=CAST(s.suggestion_id AS text)
                           AND f.feedback->>'agent_id'=CAST(s.agent_id AS text)
                           AND f.feedback->>'version_no'=CAST(s.version_no AS text))
                       OR c.feedback->>'receipt_suggestion_id'=CAST(s.suggestion_id AS text)
                       OR (e.plan->'request'->>'candidate_type'='skill_step'
                           AND e.plan->'request'->>'candidate_id'=CAST(c.candidate_id AS text)))
                     AND ((c.skill_id=s.skill_id AND EXISTS (
                         SELECT 1 FROM nexent.ag_skill_instance_t i
                         JOIN nexent.ag_skill_info_t k ON k.tenant_id=i.tenant_id AND k.skill_id=i.skill_id
                         WHERE i.tenant_id=s.tenant_id AND i.agent_id=s.agent_id AND i.version_no=s.version_no
                           AND i.skill_id=c.skill_id AND i.enabled AND i.delete_flag='N'
                           AND k.skill_name=c.skill_name AND k.delete_flag='N'))
                       OR (c.released_guide_candidate_id=s.released_guide_candidate_id
                           AND c.source_agent_id=s.agent_id AND c.source_version_no=s.version_no AND EXISTS (
                         SELECT 1 FROM nexent.evolution_release_guide_t g
                         WHERE g.tenant_id=s.tenant_id AND g.agent_id=s.agent_id AND g.version_no=s.version_no
                           AND g.candidate_id=c.released_guide_candidate_id AND g.name=c.skill_name AND g.digest=c.base_digest)))
                   ORDER BY c.candidate_id DESC LIMIT 1
              ) chosen ON true
             WHERE a.tenant_id=:tenant AND a.created_by=:user AND a.conversation_id=:conversation
               AND a.prepared_assistant_id=:message AND a.delete_flag='N' AND a.evolution_reply IS NOT NULL
        """), dict(tenant=tenant, user=user, conversation=conversation, message=message,
                    candidate=candidate)).mappings().first()
        return dict(row) if row else None


def suggestion_targets_skill(tenant, agent, version, suggestion, skill, guide):
    with get_db_session() as session:
        return session.scalar(text("""
            SELECT 1 FROM nexent.evolution_suggestion_t s
            JOIN nexent.conversation_record_t c ON c.conversation_id=s.conversation_id
                  AND c.created_by=s.submitter_id AND c.delete_flag='N'
            WHERE s.tenant_id=:tenant AND s.agent_id=:agent AND s.version_no=:version
              AND s.suggestion_id=:suggestion AND s.status='submitted'
              AND s.skill_id IS NOT DISTINCT FROM CAST(:skill AS integer)
              AND s.released_guide_candidate_id IS NOT DISTINCT FROM CAST(:guide AS bigint)
        """), dict(tenant=tenant, agent=agent, version=version, suggestion=suggestion, skill=skill, guide=guide)) == 1
