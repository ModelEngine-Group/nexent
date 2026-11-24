-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_public_benchmark_t (
    report_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id varchar(100) NOT NULL,
    experiment_id bigint NOT NULL,
    base_snapshot_digest varchar(64) NOT NULL,
    candidate_snapshot_digest varchar(64) NOT NULL,
    report_digest varchar(64) NOT NULL,
    report jsonb NOT NULL CHECK (jsonb_typeof(report) = 'object'),
    created_by varchar(100) NOT NULL,
    create_time timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by varchar(100) NOT NULL,
    update_time timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delete_flag varchar(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N','Y'))
);
CREATE INDEX IF NOT EXISTS ix_evolution_public_benchmark_experiment
    ON nexent.evolution_public_benchmark_t (tenant_id, experiment_id, report_id) WHERE delete_flag='N';
COMMENT ON TABLE nexent.evolution_public_benchmark_t IS 'Public benchmark aggregates recorded against a development comparison.';
COMMENT ON COLUMN nexent.evolution_public_benchmark_t.report_id IS 'Public benchmark report identifier.';
COMMENT ON COLUMN nexent.evolution_public_benchmark_t.tenant_id IS 'Tenant owning the associated experiment.';
COMMENT ON COLUMN nexent.evolution_public_benchmark_t.experiment_id IS 'Logical reference to the frozen development experiment.';
COMMENT ON COLUMN nexent.evolution_public_benchmark_t.base_snapshot_digest IS 'Baseline snapshot fingerprint from the experiment.';
COMMENT ON COLUMN nexent.evolution_public_benchmark_t.candidate_snapshot_digest IS 'Candidate snapshot fingerprint from the experiment.';
COMMENT ON COLUMN nexent.evolution_public_benchmark_t.report_digest IS 'Canonical aggregate report digest for idempotent submission.';
COMMENT ON COLUMN nexent.evolution_public_benchmark_t.report IS 'Validated public benchmark provenance, metric and aggregate scores.';
COMMENT ON COLUMN nexent.evolution_public_benchmark_t.created_by IS 'Agent editor who recorded the benchmark.';
COMMENT ON COLUMN nexent.evolution_public_benchmark_t.create_time IS 'Time the benchmark report was recorded.';
COMMENT ON COLUMN nexent.evolution_public_benchmark_t.updated_by IS 'Actor responsible for the current row.';
COMMENT ON COLUMN nexent.evolution_public_benchmark_t.update_time IS 'Time the current row took effect.';
COMMENT ON COLUMN nexent.evolution_public_benchmark_t.delete_flag IS 'Soft deletion marker, with N indicating an active report.';
