# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Register completed opted-in business turns and atomically enqueue five-turn reviews."""

import json

from sqlalchemy import text

from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_state import tenant_membership_matches


def enqueue_review_batches():
    with get_db_session() as session:
        # Only the lightweight registrar is serialized. Analysis runs outside this transaction.
        if not session.scalar(text("SELECT pg_try_advisory_xact_lock(hashtext('nexent.evolution.registrar'))")):
            return
        session.execute(text("""
            WITH invalidated AS (
                UPDATE nexent.evolution_review_turn_t SET observation_state='expired', claim_id=NULL,
                    observation=NULL, observed_at=NULL
                WHERE (valid_until IS NULL OR valid_until <= now()) AND observation_state NOT IN ('revoked','expired')
                RETURNING batch_id
            )
            UPDATE nexent.evolution_review_batch_t SET status='pending', result=NULL, finished_at=NULL
            WHERE batch_id IN (SELECT batch_id FROM invalidated)
        """))
        session.execute(text("""
            WITH affected AS (
                UPDATE nexent.evolution_review_turn_t r
                   SET diagnosis='{"status":"needs_evidence","reason":"authorization_changed"}'::jsonb,
                       diagnosis_source_turn_id=NULL,diagnosis_claim_id=NULL,diagnosis_lease_until=NULL
                FROM nexent.evolution_review_turn_t source
                WHERE r.diagnosis_source_turn_id=source.turn_id
                  AND (source.observation_state IN ('expired','revoked') OR source.valid_until<=clock_timestamp())
                RETURNING r.batch_id
            )
            UPDATE nexent.evolution_review_batch_t SET status='pending',result=NULL,finished_at=NULL
            WHERE batch_id IN (SELECT batch_id FROM affected)
        """))
        session.execute(text("""
            INSERT INTO nexent.evolution_review_turn_t
                (tenant_id, agent_id, agent_version_no, conversation_id, source_message_id, trajectory_id,
                 owner_id, run_id, grant_epoch, valid_until)
            SELECT a.tenant_id, t.agent_id, t.agent_version_no, a.conversation_id,
                   a.evolution_source_message_id, t.trajectory_id, a.created_by, a.run_id,
                   a.evolution_grant_epoch, a.evolution_valid_until
            FROM nexent.conversation_run_admission_t a
            JOIN nexent.agent_execution_t e ON e.run_id = a.run_id
              AND e.tenant_id = a.tenant_id AND e.created_by = a.created_by
              AND e.conversation_id = a.conversation_id
            JOIN nexent.trajectory_execution_t t ON t.agentos_run_id = a.run_id
              AND t.conversation_id = a.conversation_id AND t.created_by = a.created_by
            JOIN nexent.conversation_record_t c ON c.conversation_id = a.conversation_id
              AND c.created_by = a.created_by AND c.delete_flag = 'N'
            WHERE a.evolution_source_message_id IS NOT NULL AND a.delete_flag = 'N'
              AND c.evolution_grant_epoch=a.evolution_grant_epoch AND a.evolution_valid_until > now()
              AND e.status IN ('completed', 'failed') AND e.delete_flag = 'N'
              AND t.delete_flag = 'N' AND t.agent_version_no > 0 AND t.agent_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM nexent.evolution_review_turn_t r
                  WHERE (r.tenant_id, r.conversation_id, r.source_message_id)
                      = (a.tenant_id, a.conversation_id, a.evolution_source_message_id))
            ORDER BY e.update_time, t.trajectory_id LIMIT 250
            ON CONFLICT (tenant_id, conversation_id, source_message_id) DO NOTHING
        """))
        groups = session.execute(text("""
            SELECT tenant_id, agent_id, agent_version_no, (array_agg(turn_id ORDER BY turn_id))[1:5] AS turn_ids
            FROM nexent.evolution_review_turn_t WHERE batch_id IS NULL AND valid_until > now()
                AND observation_state NOT IN ('revoked','expired')
            GROUP BY tenant_id, agent_id, agent_version_no HAVING count(*) >= 5
            ORDER BY min(turn_id) LIMIT 50
        """)).mappings().all()
        for group in groups:
            batch_id = session.scalar(text("""
                INSERT INTO nexent.evolution_review_batch_t (tenant_id, agent_id, agent_version_no)
                VALUES (:tenant_id, :agent_id, :agent_version_no) RETURNING batch_id
            """), dict(group))
            session.execute(text("""
                UPDATE nexent.evolution_review_turn_t SET batch_id = :batch_id WHERE turn_id = ANY(:turn_ids)
            """), {"batch_id": batch_id, "turn_ids": group["turn_ids"]})


def complete_review_batches():
    """Keep valid individuals when another member was withdrawn or expired."""
    with get_db_session() as session:
        due = session.execute(text("""
            SELECT batch_id FROM nexent.evolution_review_batch_t b WHERE status='pending'
              AND NOT EXISTS (SELECT 1 FROM nexent.evolution_review_turn_t r WHERE r.batch_id=b.batch_id
                   AND r.valid_until > now() AND r.observation_state IN ('pending','reading'))
            ORDER BY batch_id LIMIT 25 FOR UPDATE SKIP LOCKED
        """)).scalars().all()
        for batch_id in due:
            summary = summarize_batch(review_rows(session, "r.batch_id=:batch", {"batch": batch_id}, limit=5))
            session.execute(text("""
                UPDATE nexent.evolution_review_batch_t SET status='completed', result=CAST(:result AS jsonb),
                    finished_at=now() WHERE batch_id=:batch
            """), {"batch": batch_id, "result": json.dumps(summary)})


def review_rows(session, predicate, params, *, limit):
    # Callers supply fixed predicates. Membership and grant expiry must also be checked at display time.
    rows = session.execute(text(f"""
        SELECT r.turn_id, r.batch_id, r.owner_id, r.tenant_id, r.observation_state, r.observation,
            CASE WHEN r.diagnosis_source_turn_id IS NULL OR
                 (source.valid_until > clock_timestamp() AND source.observation_state='observed')
                 THEN r.diagnosis END AS diagnosis,
            r.valid_until > clock_timestamp() AND r.grant_epoch=c.evolution_grant_epoch
              AND r.owner_id=c.created_by AND c.delete_flag='N' AS authorized
        FROM nexent.evolution_review_turn_t r LEFT JOIN nexent.conversation_record_t c USING (conversation_id)
        LEFT JOIN nexent.evolution_review_turn_t source ON source.turn_id=r.diagnosis_source_turn_id
        WHERE {predicate} ORDER BY r.turn_id DESC LIMIT :limit
    """), {**params, "limit": limit}).mappings().all()
    members = {}
    for row in rows:
        key = row["owner_id"], row["tenant_id"]
        if row["authorized"] and key not in members:
            members[key] = tenant_membership_matches(session, *key)
        yield {**row, "authorized": row["authorized"] and members.get(key, False)}


def recent_reviews(tenant, agent, version):
    with get_db_session() as session:
        params = {"tenant": tenant, "agent": agent, "version": version}
        scope = "r.tenant_id=:tenant AND r.agent_id=:agent AND r.agent_version_no=:version"
        rows = review_rows(session, scope, params, limit=25)
        return [{"turn_id": row["turn_id"], "batch_id": row["batch_id"], "state": row["observation_state"],
                 "signals": (row["observation"] or {}).get("signals", []),
                 **({"diagnosis": row["diagnosis"]} if row["diagnosis"] else {})}
                for row in rows if row["authorized"] and row["observation_state"] not in {"revoked", "expired"}]


def summarize_batch(rows):
    result = {"reviewed": 0, "excluded": 0, "missing": 0, "signals": {}, "no_signal_turn_ids": []}
    findings, steps = {}, {}
    for row in rows:
        if not row["authorized"] or row["observation_state"] in {"revoked", "expired"}:
            result["excluded"] += 1
            continue
        facts = row["observation"] or {}
        result["reviewed"] += 1
        if facts.get("coverage") != "complete":
            result["missing"] += 1
        signals = facts.get("signals", [])
        for signal in signals:
            result["signals"].setdefault(signal, []).append(row["turn_id"])
        diagnosis = row.get("diagnosis") or {}
        if diagnosis.get("status") == "needs_review":
            findings.setdefault((diagnosis["direction"], diagnosis["reason"]), []).append(row["turn_id"])
        if facts.get("successful_tool_steps"):
            steps.setdefault(tuple(facts["successful_tool_steps"]), []).append(row["turn_id"])
        if not signals and facts.get("coverage") == "complete":
            result["no_signal_turn_ids"].append(row["turn_id"])
    if findings:
        result["findings"] = [{"direction": direction, "reason": reason, "turn_ids": turns}
                              for (direction, reason), turns in sorted(findings.items())]
    if any(len(turns) > 1 for turns in steps.values()):
        result["reference_workflows"] = [{"tools": list(tools), "turn_ids": turns}
                                         for tools, turns in sorted(steps.items()) if len(turns) > 1]
    return result
