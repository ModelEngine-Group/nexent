-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.evolution_trial_t
    ADD COLUMN IF NOT EXISTS dispatch_started boolean,
    ADD COLUMN IF NOT EXISTS recovery_attempted boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN nexent.evolution_trial_t.dispatch_started IS 'Whether the current attempt reached Runtime dispatch. NULL means the attempt did not record this boundary.';
COMMENT ON COLUMN nexent.evolution_trial_t.recovery_attempted IS 'Whether an interrupted attempt was already requeued once before dispatch.';
