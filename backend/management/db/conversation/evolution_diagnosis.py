# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Claim online diagnosis and limit evidence use to the authorized original turn."""

import json
from uuid import uuid4

from sqlalchemy import text

from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.evolution_model_charges import lock_model_charges
from infrastructure.rdb.evolution_review_authority import authorized_review_turn


def claim():
    with get_db_session() as session:
        # Serialize queue admission across replicas; evidence processing holds no global lock.
        if not session.scalar(text("SELECT pg_try_advisory_xact_lock(hashtext('nexent.evolution.diagnosis'))")):
            return None
        return session.execute(text("""
            WITH due AS (
                SELECT candidate.turn_id, candidate.diagnosis_attempt_id AS previous_attempt
                FROM nexent.evolution_review_turn_t candidate
                WHERE observation_state IN ('observed','missing') AND diagnosis IS NULL
                  AND valid_until > clock_timestamp() AND diagnosis_claim_count <= 3
                  AND (diagnosis_lease_until IS NULL OR diagnosis_lease_until <= clock_timestamp())
                  AND (batch_id IS NOT NULL OR jsonb_array_length(observation->'signals') > 0)
                  AND NOT EXISTS (
                      SELECT 1 FROM nexent.evolution_review_turn_t active
                      WHERE active.tenant_id=candidate.tenant_id AND active.diagnosis_lease_until>clock_timestamp()
                  )
                ORDER BY (COALESCE(jsonb_array_length(observation->'signals'),0)=0), turn_id
                LIMIT 1 FOR UPDATE SKIP LOCKED
            )
            UPDATE nexent.evolution_review_turn_t r
            SET diagnosis_claim_id=:claim, diagnosis_lease_until=clock_timestamp()+interval '60 seconds',
                diagnosis_claim_count=r.diagnosis_claim_count+1
            FROM due WHERE r.turn_id=due.turn_id
            RETURNING r.turn_id,r.tenant_id,r.owner_id,r.diagnosis_claim_id,
                      r.diagnosis_claim_count,due.previous_attempt
        """), {"claim": uuid4()}).mappings().one_or_none()


def _authorized_claim(session, job):
    row = session.execute(text("""
        SELECT diagnosis_source_turn_id, diagnosis_attempt_id FROM nexent.evolution_review_turn_t
        WHERE turn_id=:turn_id AND tenant_id=:tenant_id AND owner_id=:owner_id
          AND diagnosis_claim_id=:diagnosis_claim_id AND diagnosis_lease_until > clock_timestamp()
        FOR UPDATE
    """), job).mappings().one_or_none()
    if row is None:
        return None, None
    authority = authorized_review_turn(session, job["tenant_id"], job["owner_id"], job["turn_id"])
    return authority, row


def _message_pair(session, authority, owner):
    return session.execute(text("""
        SELECT left(m.message_content,2000) AS request, m.message_index,
               left(a.message_content,3000) AS answer, a.opinion_flag,
               char_length(m.message_content)>2000 OR char_length(a.message_content)>3000 AS clipped
        FROM nexent.conversation_message_t m
        LEFT JOIN nexent.conversation_message_t a
          ON a.message_id=:prepared_assistant_id AND a.conversation_id=m.conversation_id
         AND a.created_by=:owner AND a.message_role='assistant' AND a.delete_flag='N'
        WHERE m.message_id=:source_message_id AND m.conversation_id=:conversation_id
          AND m.created_by=:owner AND m.message_role='user' AND m.message_source='CHAT' AND m.delete_flag='N'
    """), {**authority, "owner": owner}).mappings().one_or_none()


def _preceding_review(session, tenant, owner, authority, message_index):
    if message_index is None:
        return None
    turns = session.execute(text("""
        SELECT r.turn_id FROM nexent.conversation_message_t m
        LEFT JOIN nexent.evolution_review_turn_t r ON r.source_message_id=m.message_id
          AND r.conversation_id=m.conversation_id AND r.tenant_id=:tenant
        WHERE m.conversation_id=:conversation AND m.message_index=:previous AND m.message_role='user'
        LIMIT 2
    """), dict(tenant=tenant, conversation=authority["conversation_id"], previous=message_index-2)).scalars().all()
    if len(turns) != 1 or turns[0] is None:
        return None
    source = authorized_review_turn(session, tenant, owner, turns[0])
    if source and (source["agent_id"], source["agent_version_no"]) == (
        authority["agent_id"], authority["agent_version_no"]
    ):
        return source
    return None


def _usage(session, attempt):
    return session.execute(text("""
        SELECT c.charge_id,c.reported_input,c.reported_output,c.reported_micros,c.reserved_input,
               c.reserved_output,c.reserved_micros,a.budget_stopped,a.model_id,a.diagnosis_template_version
          FROM nexent.evolution_generation_attempt_t a LEFT JOIN nexent.evolution_model_charge_t c USING (attempt_id)
         WHERE a.attempt_id=:id
    """), {"id": attempt}).mappings().one_or_none()


def read_evidence(job):
    tenant, owner = job["tenant_id"], job["owner_id"]
    with get_db_session() as session:
        current, _ = _authorized_claim(session, job)
        if not current:
            return None
        prior = _usage(session, job["previous_attempt"]) if job["previous_attempt"] else None
        if (prior and prior["charge_id"]) or job["diagnosis_claim_count"] > 3:
            return {"interrupted": True, "previous_attempt": job["previous_attempt"]}
        facts = current["observation"] or {}
        # Rule findings need only Ops facts. Read message bodies only for semantic assessment.
        if not set(facts.get("signals", ())) & {"user_correction", "negative_feedback"}:
            return {"facts": facts}
        message = _message_pair(session, current, owner)
        if not message or not message["request"]:
            return {"facts": facts, "missing": "missing_request"}
        source, correction, correction_clipped = current, None, False
        if "user_correction" in facts.get("signals", ()):
            source = _preceding_review(session, tenant, owner, current, message["message_index"])
            if not source:
                return {"facts": facts, "missing": "missing_authorized_original"}
            correction = message["request"]
            correction_clipped = bool(message["clipped"])
            message = _message_pair(session, source, owner)
        if not message or not message["answer"] or not message["request"]:
            return {"facts": facts, "missing": "missing_reply"}
        source_facts = source["observation"] or {}
        if source_facts.get("coverage") != "complete":
            return {"facts": facts, "missing": "incomplete_trace"}
        return {
            "facts": facts, "source_turn_id": source["turn_id"] if source is not current else None,
            "request": message["request"], "answer": message["answer"],
            "clipped": correction_clipped or bool(message["clipped"]),
            "correction": correction, "nodes": source_facts.get("diagnosis_nodes", []),
            "request_ref": f"message:{source['source_message_id']}",
            "answer_ref": f"message:{source['prepared_assistant_id']}",
            "correction_ref": f"message:{current['source_message_id']}" if correction else None,
        }


def authorize_model(job, source_turn, allowance, template_version):
    with get_db_session() as session:
        lock_model_charges(session, job["tenant_id"])
        current, row = _authorized_claim(session, job)
        if not current or row["diagnosis_attempt_id"] and (
            (usage := _usage(session, row["diagnosis_attempt_id"])) and usage["charge_id"]
        ):
            return None
        if source_turn and not authorized_review_turn(session, job["tenant_id"], job["owner_id"], source_turn):
            return None
        args = {**job, "model": allowance.model_id, "revision": allowance.revision(),
                "source": source_turn, "until": current["valid_until"], "template": template_version}
        attempt = session.scalar(text("""
            INSERT INTO nexent.evolution_generation_attempt_t
                (tenant_id,source_digest,model_id,created_by,lease_until,metering_revision,review_turn_id,
                 diagnosis_template_version)
            VALUES (:tenant_id,repeat('0',64),:model,:owner_id,
                    LEAST(:until,clock_timestamp()+interval '30 seconds'),:revision,:turn_id,:template)
            RETURNING attempt_id
        """), args)
        session.execute(text("""
            UPDATE nexent.evolution_review_turn_t SET diagnosis_source_turn_id=:source,diagnosis_attempt_id=:attempt
            WHERE turn_id=:turn_id
        """), {**args, "attempt": attempt})
        return attempt


def finish(job, diagnosis, attempt=None):
    with get_db_session() as session:
        lock_model_charges(session, job["tenant_id"])
        current, row = _authorized_claim(session, job)
        if not current:
            return False
        if attempt is not None and attempt != row["diagnosis_attempt_id"]:
            return False
        source = row["diagnosis_source_turn_id"]
        if source and not authorized_review_turn(session, job["tenant_id"], job["owner_id"], source):
            diagnosis = {"status": "needs_evidence", "reason": "authorization_changed"}
            source = None
        if attempt is not None and attempt == row["diagnosis_attempt_id"]:
            usage = _usage(session, attempt)
            if usage and usage["budget_stopped"]:
                diagnosis = {**diagnosis, "status": "needs_evidence", "reason": "model_budget_exceeded"}
                diagnosis.pop("evidence", None)
            if usage:
                diagnosis.update(model_id=usage["model_id"], template_version=usage["diagnosis_template_version"])
            if usage and usage["charge_id"]:
                diagnosis["usage"] = {k: usage[k] for k in ("reported_input","reported_output","reported_micros",
                    "reserved_input","reserved_output","reserved_micros")}
            elif diagnosis["status"] in {"needs_review", "no_issue"}:
                diagnosis = {"status": "needs_evidence", "reason": "missing_usage_receipt"}
            session.execute(text("""
                UPDATE nexent.evolution_generation_attempt_t SET completed_at=clock_timestamp()
                WHERE attempt_id=:id AND completed_at IS NULL
            """), {"id": attempt})
        batch = session.scalar(text("""
            UPDATE nexent.evolution_review_turn_t
            SET diagnosis=CAST(:diagnosis AS jsonb),diagnosis_source_turn_id=:source,
                diagnosis_claim_id=NULL,diagnosis_lease_until=NULL
            WHERE turn_id=:turn_id RETURNING batch_id
        """), {**job, "diagnosis": json.dumps(diagnosis), "source": source})
        if batch is not None:
            session.execute(text("""
                UPDATE nexent.evolution_review_batch_t SET status='pending', result=NULL, finished_at=NULL
                WHERE batch_id=:batch
            """), {"batch": batch})
        return True
