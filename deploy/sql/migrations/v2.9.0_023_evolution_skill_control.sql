-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.evolution_trial_t DROP CONSTRAINT IF EXISTS evolution_trial_t_variant_check;
ALTER TABLE nexent.evolution_trial_t ADD CONSTRAINT evolution_trial_t_variant_check
    CHECK (variant IN ('base', 'result', 'no_skill'));
COMMENT ON COLUMN nexent.evolution_trial_t.variant IS 'Baseline, proposed candidate or root Skill omission control.';
