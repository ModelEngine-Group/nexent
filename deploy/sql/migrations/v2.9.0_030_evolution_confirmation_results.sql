-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_confirmation_result_t (
    lock_id bigint PRIMARY KEY REFERENCES nexent.evolution_confirmation_lock_t(lock_id),
    lock_digest char(64) NOT NULL,
    decision varchar(16) NOT NULL CHECK (decision IN ('passed','failed','insufficient')),
    summary jsonb NOT NULL,
    create_time timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE nexent.evolution_confirmation_result_t IS 'Single aggregate verdict written by the trusted independent runner.';
COMMENT ON COLUMN nexent.evolution_confirmation_result_t.lock_id IS 'Immutable comparison ID; repeated executions reuse a completed result.';
COMMENT ON COLUMN nexent.evolution_confirmation_result_t.lock_digest IS 'Verified protocol checksum for this comparison.';
COMMENT ON COLUMN nexent.evolution_confirmation_result_t.decision IS 'Passed the agreed criteria, failed them, or lacked evidence.';
COMMENT ON COLUMN nexent.evolution_confirmation_result_t.summary IS 'Aggregate counts, measured metrics and reason codes only.';
COMMENT ON COLUMN nexent.evolution_confirmation_result_t.create_time IS 'Time the independent runner finalized the decision.';
