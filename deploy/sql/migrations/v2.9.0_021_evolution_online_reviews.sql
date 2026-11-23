-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.conversation_record_t ADD COLUMN IF NOT EXISTS evolution_grant_epoch integer NOT NULL DEFAULT 0;
ALTER TABLE nexent.conversation_run_admission_t
    ADD COLUMN IF NOT EXISTS evolution_grant_epoch integer,
    ADD COLUMN IF NOT EXISTS evolution_valid_until timestamptz;
ALTER TABLE nexent.evolution_review_turn_t
    ADD COLUMN IF NOT EXISTS grant_epoch integer,
    ADD COLUMN IF NOT EXISTS valid_until timestamptz,
    ADD COLUMN IF NOT EXISTS owner_id varchar(100),
    ADD COLUMN IF NOT EXISTS run_id varchar(32),
    ADD COLUMN IF NOT EXISTS observation_state varchar(24) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS claim_id uuid,
    ADD COLUMN IF NOT EXISTS available_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS observation jsonb,
    ADD COLUMN IF NOT EXISTS observed_at timestamptz;
ALTER TABLE nexent.evolution_review_batch_t
    ADD COLUMN IF NOT EXISTS result jsonb,
    ADD COLUMN IF NOT EXISTS finished_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_evolution_observation_work ON nexent.evolution_review_turn_t
    (available_at, turn_id) WHERE observation_state IN ('pending','reading');
CREATE INDEX IF NOT EXISTS idx_evolution_review_conversation ON nexent.evolution_review_turn_t
    (conversation_id, grant_epoch);

CREATE OR REPLACE FUNCTION nexent.invalidate_evolution_conversation_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.evolution_grant_epoch IS DISTINCT FROM OLD.evolution_grant_epoch OR NEW.delete_flag='Y' THEN
        WITH withdrawn AS (
            UPDATE nexent.evolution_review_turn_t SET observation_state='revoked', observation=NULL,
                claim_id=NULL, observed_at=NULL WHERE conversation_id=NEW.conversation_id AND observation_state <> 'revoked'
            RETURNING batch_id
        )
        UPDATE nexent.evolution_review_batch_t SET status='pending', result=NULL, finished_at=NULL
        WHERE batch_id IN (SELECT batch_id FROM withdrawn);
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS evolution_conversation_evidence_withdrawal ON nexent.conversation_record_t;
CREATE TRIGGER evolution_conversation_evidence_withdrawal AFTER UPDATE OF evolution_grant_epoch, delete_flag
    ON nexent.conversation_record_t FOR EACH ROW EXECUTE FUNCTION nexent.invalidate_evolution_conversation_evidence();

CREATE OR REPLACE FUNCTION nexent.refresh_evolution_reply_feedback() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    WITH changed AS (
        UPDATE nexent.evolution_review_turn_t r SET observation_state='pending', observation=NULL,
            claim_id=NULL, attempts=0, observed_at=NULL, available_at=now()
        FROM nexent.conversation_run_admission_t a
        WHERE a.prepared_assistant_id=NEW.message_id AND a.conversation_id=NEW.conversation_id
            AND r.run_id=a.run_id AND r.conversation_id=a.conversation_id AND r.tenant_id=a.tenant_id
            AND r.valid_until > now() AND r.observation_state NOT IN ('revoked','expired')
        RETURNING r.batch_id
    )
    UPDATE nexent.evolution_review_batch_t SET status='pending', result=NULL, finished_at=NULL
        WHERE batch_id IN (SELECT batch_id FROM changed);
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS evolution_reply_feedback ON nexent.conversation_message_t;
CREATE TRIGGER evolution_reply_feedback AFTER UPDATE OF opinion_flag ON nexent.conversation_message_t
    FOR EACH ROW WHEN (NEW.message_role='assistant' AND NEW.opinion_flag IS DISTINCT FROM OLD.opinion_flag)
    EXECUTE FUNCTION nexent.refresh_evolution_reply_feedback();

COMMENT ON COLUMN nexent.conversation_record_t.evolution_grant_epoch IS 'Grant generation advanced on withdrawal; toggling automatic analysis preserves it.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.evolution_grant_epoch IS 'Generation authorized when the original user request was admitted.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.evolution_valid_until IS 'Latest permitted consumption of this automatic evidence grant.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.grant_epoch IS 'Generation copied from the eligible original run.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.valid_until IS 'Expiration inherited from admission; retries cannot extend it.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.owner_id IS 'Owner recorded on the authorized run.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.run_id IS 'AgentOS run linked to the exact root trajectory.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.observation_state IS 'Capture queue status including missing, expired and revoked outcomes.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.attempts IS 'Number of bounded Ops reads attempted.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.claim_id IS 'Lease fencing token; stale workers cannot publish observations.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.available_at IS 'Next claim time, or active lease deadline.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.observation IS 'Bounded metadata and node references with no user or provider text.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.observed_at IS 'Time Ops finished the last observation.';
COMMENT ON COLUMN nexent.evolution_review_batch_t.result IS 'Review counts and contributing turn references, derived from active grants.';
COMMENT ON COLUMN nexent.evolution_review_batch_t.finished_at IS 'Latest completion of the five-turn review.';
