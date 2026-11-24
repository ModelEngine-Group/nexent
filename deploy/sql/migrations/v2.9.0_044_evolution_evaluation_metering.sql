-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.evolution_experiment_t
    ADD COLUMN IF NOT EXISTS budget_stop_reason TEXT;

ALTER TABLE nexent.evolution_generation_attempt_t
    ALTER COLUMN model_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS experiment_id BIGINT,
    ADD COLUMN IF NOT EXISTS trial_id BIGINT,
    ADD COLUMN IF NOT EXISTS trial_receipt VARCHAR(32);

ALTER TABLE nexent.evolution_model_charge_t
    ADD COLUMN IF NOT EXISTS experiment_id BIGINT,
    ADD COLUMN IF NOT EXISTS model_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_evolution_model_charge_experiment
    ON nexent.evolution_model_charge_t (tenant_id, experiment_id)
    WHERE experiment_id IS NOT NULL;
