# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Fence observation reads and writes against the original admission and current consent."""

import json
from uuid import uuid4

from sqlalchemy import text

from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_state import tenant_membership_matches


def claim():
    with get_db_session() as session:
        return session.execute(text("""
            WITH due AS (
                SELECT turn_id FROM nexent.evolution_review_turn_t
                WHERE observation_state IN ('pending','reading') AND available_at <= now()
                  AND valid_until > now()
                ORDER BY available_at, turn_id LIMIT 1 FOR UPDATE SKIP LOCKED
            )
            UPDATE nexent.evolution_review_turn_t r SET observation_state='reading', claim_id=:claim,
                available_at=now()+interval '90 seconds', attempts=attempts+1
            FROM due WHERE r.turn_id=due.turn_id
            RETURNING r.turn_id, r.claim_id, r.conversation_id, r.owner_id AS user_id, r.tenant_id,
                      r.agent_id, r.agent_version_no, r.source_message_id,
                      r.trajectory_id::text AS trajectory_id, r.attempts
        """), {"claim": str(uuid4())}).mappings().first()


def access(session, job):
    if not tenant_membership_matches(session, job["user_id"], job["tenant_id"]):
        return None
    return session.execute(text("""
        SELECT a.prepared_assistant_id FROM nexent.evolution_review_turn_t r
        JOIN nexent.conversation_record_t c ON c.conversation_id=r.conversation_id
            AND c.created_by=r.owner_id AND c.delete_flag='N' AND c.evolution_grant_epoch=r.grant_epoch
        JOIN nexent.conversation_run_admission_t a ON a.run_id=r.run_id AND a.tenant_id=r.tenant_id
            AND a.created_by=r.owner_id AND a.conversation_id=r.conversation_id AND a.delete_flag='N'
            AND a.evolution_source_message_id=r.source_message_id AND a.evolution_grant_epoch=r.grant_epoch
        JOIN nexent.trajectory_execution_t t ON t.agentos_run_id=a.run_id AND t.trajectory_id=r.trajectory_id
            AND t.conversation_id=c.conversation_id AND t.created_by=r.owner_id AND t.delete_flag='N'
            AND t.agent_id=r.agent_id AND t.agent_version_no=r.agent_version_no
        WHERE r.turn_id=:turn_id AND r.claim_id=:claim_id AND r.observation_state='reading'
            AND least(a.evolution_valid_until,r.valid_until) > clock_timestamp()
    """), job).mappings().first()


def messages(job):
    with get_db_session() as session:
        admission = access(session, job)
        if admission is None:
            return None
        return session.execute(text("""
            SELECT left(m.message_content, 2048) AS request, reply.opinion_flag,
                EXISTS (SELECT 1 FROM nexent.conversation_message_unit_t u
                    WHERE u.conversation_id=m.conversation_id AND u.message_id=reply.message_id
                      AND u.unit_type='file_artifact' AND u.unit_status='completed' AND u.delete_flag='N'
                ) AS file_receipt
            FROM nexent.conversation_message_t m LEFT JOIN nexent.conversation_message_t reply
                ON reply.message_id=:prepared_assistant_id AND reply.conversation_id=m.conversation_id
                    AND reply.message_role='assistant' AND reply.delete_flag='N'
            WHERE m.conversation_id=:conversation_id AND m.message_id=:source_message_id
              AND m.created_by=:user_id AND m.message_role='user' AND m.message_source='CHAT' AND m.delete_flag='N'
        """), {**job, **admission}).mappings().first()


def finish(job, observation, *, retry=False):
    with get_db_session() as session:
        if access(session, job) is None:
            state, observation = "revoked", None
        elif retry and job["attempts"] < 3:
            state, observation = "pending", None
        else:
            state = "observed" if observation and observation.get("coverage") == "complete" else "missing"
        session.execute(text("""
            UPDATE nexent.evolution_review_turn_t SET observation_state=:state, claim_id=NULL,
                available_at=now()+interval '15 seconds', observation=CAST(:facts AS jsonb),
                observed_at=CASE WHEN CAST(:facts AS jsonb) IS NULL THEN NULL ELSE now() END
            WHERE turn_id=:turn_id AND claim_id=:claim_id AND observation_state='reading'
        """), {**job, "state": state, "facts": json.dumps(observation) if observation is not None else None})
