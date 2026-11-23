-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_experiment_t (
    experiment_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id varchar(100) NOT NULL,
    created_by varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    version_no integer NOT NULL CHECK (version_no > 0),
    request_id varchar(96) NOT NULL,
    request_digest char(64) NOT NULL,
    plan jsonb NOT NULL,
    cancelled boolean NOT NULL DEFAULT false,
    create_time timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, created_by, request_id)
);
CREATE TABLE IF NOT EXISTS nexent.evolution_trial_t (
    trial_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    experiment_id bigint NOT NULL REFERENCES nexent.evolution_experiment_t,
    case_id bigint NOT NULL REFERENCES nexent.evolution_replay_case_t,
    variant varchar(8) NOT NULL CHECK (variant IN ('base','result')),
    status varchar(24) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','running','pass','fail','missing_evidence','invalid','error','cancelled')),
    receipt_id char(32),
    lease_until timestamptz,
    result jsonb,
    UNIQUE (experiment_id, case_id, variant)
);
CREATE INDEX IF NOT EXISTS idx_evolution_trial_pending ON nexent.evolution_trial_t(trial_id) WHERE status='pending';
ALTER TABLE nexent.evolution_trial_t ADD COLUMN IF NOT EXISTS cleanup_due timestamptz;
COMMENT ON TABLE nexent.evolution_experiment_t IS 'Frozen plans for paired development trials.';
COMMENT ON TABLE nexent.evolution_trial_t IS 'One independent run of a baseline or candidate on a frozen task.';
COMMENT ON COLUMN nexent.evolution_experiment_t.experiment_id IS 'Unique paired experiment.';
COMMENT ON COLUMN nexent.evolution_experiment_t.tenant_id IS 'Business tenant defining the trial.';
COMMENT ON COLUMN nexent.evolution_experiment_t.created_by IS 'Agent editor initiating the run.';
COMMENT ON COLUMN nexent.evolution_experiment_t.agent_id IS 'Business Agent tested by both variants.';
COMMENT ON COLUMN nexent.evolution_experiment_t.version_no IS 'Released Agent baseline.';
COMMENT ON COLUMN nexent.evolution_experiment_t.request_digest IS 'Canonical client request digest for idempotency.';
COMMENT ON COLUMN nexent.evolution_experiment_t.cancelled IS 'Stop claiming queued work for this experiment.';
COMMENT ON COLUMN nexent.evolution_experiment_t.create_time IS 'Time the complete plan was accepted.';
COMMENT ON COLUMN nexent.evolution_experiment_t.plan IS 'Candidate, versioned scoring rule, task identities and checksums.';
COMMENT ON COLUMN nexent.evolution_experiment_t.request_id IS 'Client operation key scoped to the submitting tenant and user.';
COMMENT ON COLUMN nexent.evolution_trial_t.receipt_id IS 'Execution attempt identifier echoed by the isolated Runtime.';
COMMENT ON COLUMN nexent.evolution_trial_t.trial_id IS 'Unique case and variant execution.';
COMMENT ON COLUMN nexent.evolution_trial_t.experiment_id IS 'Plan that authorized the run.';
COMMENT ON COLUMN nexent.evolution_trial_t.case_id IS 'Frozen development case used as input.';
COMMENT ON COLUMN nexent.evolution_trial_t.variant IS 'Baseline or proposed candidate.';
COMMENT ON COLUMN nexent.evolution_trial_t.status IS 'Execution or scoring state; only pass and fail have valid judgments.';
COMMENT ON COLUMN nexent.evolution_trial_t.lease_until IS 'Heartbeat expiry, after which the outcome becomes indeterminate.';
COMMENT ON COLUMN nexent.evolution_trial_t.result IS 'Observed answer, evidence, resource fingerprint and judgment.';
COMMENT ON COLUMN nexent.evolution_trial_t.cleanup_due IS 'Recoverable cleanup of temporary per-attempt attachment copies.';
