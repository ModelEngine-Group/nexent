-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Refresh older, still-authorized observations using their original archive and review turn.
WITH refreshed AS (
    UPDATE nexent.evolution_review_turn_t r
       SET observation_state='pending', attempts=0, available_at=now(), claim_id=NULL
      FROM nexent.conversation_record_t c, nexent.conversation_run_admission_t a
     WHERE r.observation_state='observed' AND r.observation->>'coverage'='complete'
       AND NOT (r.observation ? 'case_outline') AND r.valid_until > now()
       AND c.conversation_id=r.conversation_id AND c.created_by=r.owner_id AND c.delete_flag='N'
       AND c.evolution_grant_epoch=r.grant_epoch AND a.tenant_id=r.tenant_id AND a.run_id=r.run_id
       AND a.conversation_id=c.conversation_id AND a.created_by=r.owner_id AND a.delete_flag='N'
       AND a.evolution_source_message_id=r.source_message_id AND a.evolution_grant_epoch=r.grant_epoch
       AND a.evolution_valid_until > now()
    RETURNING r.batch_id
)
UPDATE nexent.evolution_review_batch_t SET status='pending', result=NULL, finished_at=NULL
 WHERE batch_id IN (SELECT batch_id FROM refreshed);
