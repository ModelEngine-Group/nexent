-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_confirmation_candidate_t (
    experiment_id bigint PRIMARY KEY REFERENCES nexent.evolution_experiment_t(experiment_id),
    digest char(64) NOT NULL,
    recipe jsonb NOT NULL,
    submitted_by varchar(100) NOT NULL,
    create_time timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS nexent.evolution_confirmation_lock_t (
    lock_id bigserial PRIMARY KEY,
    suite_id bigint NOT NULL UNIQUE REFERENCES nexent.evolution_confirmation_suite_t(suite_id),
    experiment_id bigint NOT NULL REFERENCES nexent.evolution_confirmation_candidate_t(experiment_id),
    digest char(64) NOT NULL,
    policy jsonb NOT NULL,
    locked_by varchar(100) NOT NULL,
    create_time timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS nexent.evolution_confirmation_used_source_t (
    tenant_id varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    source_key varchar(96) NOT NULL,
    lock_id bigint NOT NULL REFERENCES nexent.evolution_confirmation_lock_t(lock_id),
    PRIMARY KEY (tenant_id, agent_id, source_key)
);
COMMENT ON TABLE nexent.evolution_confirmation_candidate_t IS 'Explicit editor handoff of the exact verified candidate for independent testing.';
COMMENT ON COLUMN nexent.evolution_confirmation_candidate_t.experiment_id IS 'Completed development experiment and immutable nomination key.';
COMMENT ON COLUMN nexent.evolution_confirmation_candidate_t.digest IS 'Canonical digest of the sealed execution recipe.';
COMMENT ON COLUMN nexent.evolution_confirmation_candidate_t.recipe IS 'Resource references, arm checksums and frozen rubric identity. No material or credentials.';
COMMENT ON COLUMN nexent.evolution_confirmation_candidate_t.submitted_by IS 'Editor authorizing use of the candidate.';
COMMENT ON COLUMN nexent.evolution_confirmation_candidate_t.create_time IS 'Time of handoff.';
COMMENT ON TABLE nexent.evolution_confirmation_lock_t IS 'One curator-approved comparison and policy per independent suite.';
COMMENT ON COLUMN nexent.evolution_confirmation_lock_t.lock_id IS 'Independent comparison identifier.';
COMMENT ON COLUMN nexent.evolution_confirmation_lock_t.suite_id IS 'Immutable suite registered by its independent evaluator.';
COMMENT ON COLUMN nexent.evolution_confirmation_lock_t.experiment_id IS 'Nominated development candidate.';
COMMENT ON COLUMN nexent.evolution_confirmation_lock_t.digest IS 'Digest binding tenant, candidate, private suite and policy.';
COMMENT ON COLUMN nexent.evolution_confirmation_lock_t.policy IS 'Predeclared coverage, effectiveness, usage and latency limits.';
COMMENT ON COLUMN nexent.evolution_confirmation_lock_t.locked_by IS 'Independent evaluator authorizing this comparison.';
COMMENT ON COLUMN nexent.evolution_confirmation_lock_t.create_time IS 'Time the suite and policy were committed.';
COMMENT ON TABLE nexent.evolution_confirmation_used_source_t IS 'Prevent reuse of private materials with another candidate or changed thresholds.';
COMMENT ON COLUMN nexent.evolution_confirmation_used_source_t.tenant_id IS 'Tenant owning the verified scope.';
COMMENT ON COLUMN nexent.evolution_confirmation_used_source_t.agent_id IS 'Business Agent across its published versions.';
COMMENT ON COLUMN nexent.evolution_confirmation_used_source_t.source_key IS 'Verified source fingerprint from a private suite.';
COMMENT ON COLUMN nexent.evolution_confirmation_used_source_t.lock_id IS 'Comparison that reserved these materials.';
