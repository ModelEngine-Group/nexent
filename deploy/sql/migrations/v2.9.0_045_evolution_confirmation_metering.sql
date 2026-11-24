-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.evolution_confirmation_lock_t
    ADD COLUMN IF NOT EXISTS model_metering JSONB,
    ADD COLUMN IF NOT EXISTS budget_stopped BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE nexent.evolution_generation_attempt_t
    ADD COLUMN IF NOT EXISTS confirmation_lock_id BIGINT;

ALTER TABLE nexent.evolution_model_charge_t
    ADD COLUMN IF NOT EXISTS confirmation_lock_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_evolution_model_charge_confirmation
    ON nexent.evolution_model_charge_t (tenant_id, confirmation_lock_id)
    WHERE confirmation_lock_id IS NOT NULL;

COMMENT ON COLUMN nexent.evolution_confirmation_lock_t.model_metering IS 'Frozen confirmation model quota and tariff revision. Contains no suite materials.';
COMMENT ON COLUMN nexent.evolution_confirmation_lock_t.budget_stopped IS 'A provider request exceeded a quota or the declared provider usage limit.';
COMMENT ON COLUMN nexent.evolution_generation_attempt_t.confirmation_lock_id IS 'Confirmation scope of an opaque private execution lease.';
COMMENT ON COLUMN nexent.evolution_model_charge_t.confirmation_lock_id IS 'Confirmation scope for reporting aggregate provider usage.';
