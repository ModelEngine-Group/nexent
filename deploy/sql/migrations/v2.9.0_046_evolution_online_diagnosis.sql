-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.evolution_review_turn_t
    ADD COLUMN IF NOT EXISTS diagnosis JSONB,
    ADD COLUMN IF NOT EXISTS diagnosis_source_turn_id BIGINT,
    ADD COLUMN IF NOT EXISTS diagnosis_claim_id UUID,
    ADD COLUMN IF NOT EXISTS diagnosis_lease_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS diagnosis_attempt_id BIGINT,
    ADD COLUMN IF NOT EXISTS diagnosis_claim_count SMALLINT NOT NULL DEFAULT 0;

ALTER TABLE nexent.evolution_generation_attempt_t
    ADD COLUMN IF NOT EXISTS review_turn_id BIGINT,
    ADD COLUMN IF NOT EXISTS diagnosis_template_version VARCHAR(40);
ALTER TABLE nexent.evolution_model_charge_t ADD COLUMN IF NOT EXISTS review_turn_id BIGINT;
CREATE INDEX IF NOT EXISTS idx_evolution_diagnosis_due ON nexent.evolution_review_turn_t
    (turn_id) WHERE diagnosis IS NULL AND observation_state IN ('observed', 'missing');
CREATE INDEX IF NOT EXISTS idx_evolution_diagnosis_source ON nexent.evolution_review_turn_t
    (diagnosis_source_turn_id) WHERE diagnosis_source_turn_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_evolution_diagnosis_leased ON nexent.evolution_review_turn_t
    (tenant_id, diagnosis_lease_until) WHERE diagnosis_lease_until IS NOT NULL;

CREATE OR REPLACE FUNCTION nexent.reset_evolution_diagnosis() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.observation IS DISTINCT FROM OLD.observation OR NEW.observation_state IS DISTINCT FROM OLD.observation_state THEN
        NEW.diagnosis := NULL;
        NEW.diagnosis_claim_id := NULL;
        NEW.diagnosis_lease_until := NULL;
        NEW.diagnosis_source_turn_id := NULL;
        NEW.diagnosis_attempt_id := NULL;
        NEW.diagnosis_claim_count := 0;
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS evolution_diagnosis_reset ON nexent.evolution_review_turn_t;
CREATE TRIGGER evolution_diagnosis_reset BEFORE UPDATE OF observation, observation_state
    ON nexent.evolution_review_turn_t FOR EACH ROW EXECUTE FUNCTION nexent.reset_evolution_diagnosis();

COMMENT ON COLUMN nexent.evolution_review_turn_t.diagnosis IS 'Validated diagnosis codes, evidence references, model identity and measured usage.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.diagnosis_source_turn_id IS 'Additional authorized original turn used to interpret a later correction.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.diagnosis_claim_id IS 'Current opaque diagnosis claim; replaced during recovery or evidence change.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.diagnosis_lease_until IS 'When the active diagnosis claim expires.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.diagnosis_attempt_id IS 'Last model entitlement for this observed evidence, retained for restart recovery.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.diagnosis_claim_count IS 'Number of claims for this revision of observed evidence.';
COMMENT ON COLUMN nexent.evolution_generation_attempt_t.review_turn_id IS 'Online diagnosis turn; excludes this attempt from offline budgets.';
COMMENT ON COLUMN nexent.evolution_generation_attempt_t.diagnosis_template_version IS 'Prompt contract used to render the admitted diagnosis.';
COMMENT ON COLUMN nexent.evolution_model_charge_t.review_turn_id IS 'Online diagnosis scope for usage reconciliation; contains no prompt or response.';
