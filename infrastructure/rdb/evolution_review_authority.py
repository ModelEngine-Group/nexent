# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Check the same persisted review consent before evidence use and provider dispatch."""

from sqlalchemy import text

from infrastructure.rdb.conversation_state import tenant_membership_matches


def authorized_review_turn(session, tenant, owner, turn, *, require_complete=False):
    if not tenant_membership_matches(session, owner, tenant):
        return None
    return session.execute(text("""
        SELECT r.turn_id, r.observation, r.observation_state, r.conversation_id,
               r.agent_id, r.agent_version_no, r.source_message_id, r.valid_until,
               a.prepared_assistant_id
          FROM nexent.evolution_review_turn_t r
          JOIN nexent.conversation_record_t c ON c.conversation_id=r.conversation_id
               AND c.created_by=r.owner_id AND c.evolution_grant_epoch=r.grant_epoch AND c.delete_flag='N'
          JOIN nexent.conversation_run_admission_t a ON (a.run_id,a.tenant_id,a.conversation_id,a.created_by)
               =(r.run_id,r.tenant_id,r.conversation_id,r.owner_id) AND a.delete_flag='N'
               AND a.evolution_source_message_id=r.source_message_id AND a.evolution_grant_epoch=r.grant_epoch
          JOIN nexent.trajectory_execution_t t ON t.trajectory_id=r.trajectory_id AND t.agentos_run_id=a.run_id
               AND t.conversation_id=c.conversation_id AND t.created_by=r.owner_id AND t.delete_flag='N'
               AND t.agent_id=r.agent_id AND t.agent_version_no=r.agent_version_no AND t.status<>'expired'
         WHERE r.turn_id=:turn AND r.tenant_id=:tenant AND r.owner_id=:owner
           AND r.observation_state IN ('observed','missing')
           AND (NOT :require_complete OR (r.observation_state='observed' AND r.observation->>'coverage'='complete'))
           AND LEAST(r.valid_until,a.evolution_valid_until) > clock_timestamp()
    """), dict(tenant=tenant, owner=owner, turn=turn, require_complete=require_complete)).mappings().one_or_none()
