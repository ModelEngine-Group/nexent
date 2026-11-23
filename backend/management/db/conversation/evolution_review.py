# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Register completed opted-in business turns and atomically enqueue five-turn reviews."""

from sqlalchemy import text

from infrastructure.rdb.client import get_db_session


def enqueue_review_batches():
    with get_db_session() as session:
        # Only the lightweight registrar is serialized. Analysis runs outside this transaction.
        if not session.scalar(text("SELECT pg_try_advisory_xact_lock(hashtext('nexent.evolution.registrar'))")):
            return
        session.execute(text("""
            INSERT INTO nexent.evolution_review_turn_t
                (tenant_id, agent_id, agent_version_no, conversation_id, source_message_id, trajectory_id)
            SELECT a.tenant_id, t.agent_id, t.agent_version_no, a.conversation_id,
                   a.evolution_source_message_id, t.trajectory_id
            FROM nexent.conversation_run_admission_t a
            JOIN nexent.agent_execution_t e ON e.run_id = a.run_id
              AND e.tenant_id = a.tenant_id AND e.created_by = a.created_by
              AND e.conversation_id = a.conversation_id
            JOIN nexent.trajectory_execution_t t ON t.agentos_run_id = a.run_id
              AND t.conversation_id = a.conversation_id AND t.created_by = a.created_by
            JOIN nexent.conversation_record_t c ON c.conversation_id = a.conversation_id
              AND c.created_by = a.created_by AND c.delete_flag = 'N'
            WHERE a.evolution_source_message_id IS NOT NULL AND a.delete_flag = 'N'
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
            FROM nexent.evolution_review_turn_t WHERE batch_id IS NULL
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
