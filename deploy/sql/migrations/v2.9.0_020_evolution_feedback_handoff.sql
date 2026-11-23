-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_feedback_handoff_t (
    feedback_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    experiment_id bigint NOT NULL REFERENCES nexent.evolution_experiment_t,
    tenant_id varchar(100) NOT NULL,
    created_by varchar(100) NOT NULL,
    digest char(64) NOT NULL,
    feedback jsonb NOT NULL,
    create_time timestamptz NOT NULL DEFAULT now(),
    UNIQUE (experiment_id, created_by, digest)
);
COMMENT ON TABLE nexent.evolution_feedback_handoff_t IS 'Approved development excerpts for the designated resource maintainer.';
COMMENT ON COLUMN nexent.evolution_feedback_handoff_t.feedback_id IS 'Stable handoff reference.';
COMMENT ON COLUMN nexent.evolution_feedback_handoff_t.experiment_id IS 'Source of the verified development observations.';
COMMENT ON COLUMN nexent.evolution_feedback_handoff_t.tenant_id IS 'Tenant bounding the receiving resource.';
COMMENT ON COLUMN nexent.evolution_feedback_handoff_t.created_by IS 'Agent editor approving these excerpts for sharing.';
COMMENT ON COLUMN nexent.evolution_feedback_handoff_t.digest IS 'Content digest for retried submissions.';
COMMENT ON COLUMN nexent.evolution_feedback_handoff_t.feedback IS 'Selected source and excerpts with scoped case and trial identifiers.';
COMMENT ON COLUMN nexent.evolution_feedback_handoff_t.create_time IS 'Submission timestamp.';
