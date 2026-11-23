-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_regression_case_t (
    tenant_id varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    digest char(64) NOT NULL,
    source_case_id bigint NOT NULL REFERENCES nexent.evolution_replay_case_t(case_id),
    enabled boolean NOT NULL,
    updated_by varchar(100) NOT NULL,
    update_time timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, agent_id, digest)
);
ALTER TABLE nexent.evolution_regression_case_t ADD COLUMN IF NOT EXISTS scoring jsonb;
COMMENT ON COLUMN nexent.evolution_regression_case_t.scoring IS 'Frozen published rubric, judge model selection and rubric language for this task.';
COMMENT ON TABLE nexent.evolution_regression_case_t IS 'Fixed business tasks shared by releases of one tenant Agent.';
COMMENT ON COLUMN nexent.evolution_regression_case_t.tenant_id IS 'Tenant that owns the regression suite.';
COMMENT ON COLUMN nexent.evolution_regression_case_t.agent_id IS 'Business Agent under test.';
COMMENT ON COLUMN nexent.evolution_regression_case_t.digest IS 'Immutable task and attachment manifest digest.';
COMMENT ON COLUMN nexent.evolution_regression_case_t.source_case_id IS 'First confirmed development case with this digest in the suite.';
COMMENT ON COLUMN nexent.evolution_regression_case_t.enabled IS 'Include this task when freezing new candidate comparisons.';
COMMENT ON COLUMN nexent.evolution_regression_case_t.updated_by IS 'Editor who last changed membership.';
COMMENT ON COLUMN nexent.evolution_regression_case_t.update_time IS 'Last change to membership.';
