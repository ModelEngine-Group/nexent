-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

CREATE TABLE IF NOT EXISTS nexent.evolution_candidate_t (
    candidate_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    base_version_no integer NOT NULL CHECK (base_version_no > 0),
    resource_field varchar(80) NOT NULL,
    base_digest char(64) NOT NULL,
    result_digest char(64) NOT NULL,
    source_text text NOT NULL,
    result_text text NOT NULL,
    create_time timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, agent_id, base_version_no, resource_field, base_digest, result_digest)
);
COMMENT ON TABLE nexent.evolution_candidate_t IS 'Immutable local resource variants used in evaluation.';
COMMENT ON COLUMN nexent.evolution_candidate_t.candidate_id IS 'Stable candidate reference.';
COMMENT ON COLUMN nexent.evolution_candidate_t.tenant_id IS 'Owning business tenant.';
COMMENT ON COLUMN nexent.evolution_candidate_t.agent_id IS 'Target business Agent.';
COMMENT ON COLUMN nexent.evolution_candidate_t.base_version_no IS 'Published Agent version used as baseline.';
COMMENT ON COLUMN nexent.evolution_candidate_t.resource_field IS 'Edited source field on the baseline.';
COMMENT ON COLUMN nexent.evolution_candidate_t.base_digest IS 'SHA-256 of the original UTF-8 text.';
COMMENT ON COLUMN nexent.evolution_candidate_t.result_digest IS 'SHA-256 of the candidate UTF-8 text.';
COMMENT ON COLUMN nexent.evolution_candidate_t.source_text IS 'Exact original text of the resource.';
COMMENT ON COLUMN nexent.evolution_candidate_t.result_text IS 'Exact resource text for candidate compilation.';
COMMENT ON COLUMN nexent.evolution_candidate_t.create_time IS 'Time the candidate was first stored.';

CREATE TABLE IF NOT EXISTS nexent.evolution_candidate_feedback_t (
    candidate_id bigint NOT NULL REFERENCES nexent.evolution_candidate_t(candidate_id),
    created_by varchar(100) NOT NULL,
    feedback_digest char(64) NOT NULL,
    feedback jsonb NOT NULL,
    create_time timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (candidate_id, created_by, feedback_digest)
);
COMMENT ON TABLE nexent.evolution_candidate_feedback_t IS 'Development evidence supporting each generated change.';
COMMENT ON COLUMN nexent.evolution_candidate_feedback_t.candidate_id IS 'Candidate produced from the development evidence.';
COMMENT ON COLUMN nexent.evolution_candidate_feedback_t.created_by IS 'Authorized editor who submitted the development feedback.';
COMMENT ON COLUMN nexent.evolution_candidate_feedback_t.feedback_digest IS 'Content hash for repeat submissions.';
COMMENT ON COLUMN nexent.evolution_candidate_feedback_t.feedback IS 'Method, generator model, editor-approved examples and proposed local edit.';
COMMENT ON COLUMN nexent.evolution_candidate_feedback_t.create_time IS 'Time this evidence was associated with the candidate.';
