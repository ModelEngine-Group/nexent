-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_tool_build_t (
    build_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id varchar(100) NOT NULL,
    feedback_id bigint NOT NULL REFERENCES nexent.evolution_feedback_handoff_t(feedback_id),
    digest char(64) NOT NULL,
    manifest jsonb NOT NULL,
    created_by varchar(100) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, feedback_id, created_by, digest)
);
CREATE TABLE IF NOT EXISTS nexent.evolution_tool_build_guard_t (
    build_id bigint NOT NULL REFERENCES nexent.evolution_tool_build_t(build_id),
    experiment_id bigint NOT NULL REFERENCES nexent.evolution_experiment_t(experiment_id),
    case_id bigint NOT NULL REFERENCES nexent.evolution_replay_case_t(case_id),
    tool_name text NOT NULL,
    agent_id integer NOT NULL,
    version_no integer NOT NULL,
    approved_by varchar(100) NOT NULL,
    data jsonb NOT NULL,
    PRIMARY KEY (build_id, experiment_id, case_id, tool_name, approved_by)
);
CREATE TABLE IF NOT EXISTS nexent.evolution_tool_build_run_t (
    run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    build_id bigint NOT NULL REFERENCES nexent.evolution_tool_build_t(build_id),
    plan_digest char(64) NOT NULL,
    report jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_evolution_tool_build_run_plan
    ON nexent.evolution_tool_build_run_t (build_id, plan_digest, run_id DESC);
COMMENT ON TABLE nexent.evolution_tool_build_t IS 'Reviewed base and proposed immutable tool images, separate from any release binding.';
COMMENT ON TABLE nexent.evolution_tool_build_guard_t IS 'Business cases explicitly approved for tool build regression by their Agent editors.';
COMMENT ON TABLE nexent.evolution_tool_build_run_t IS 'Isolated operator-run observations for one exact build and caller coverage plan.';
