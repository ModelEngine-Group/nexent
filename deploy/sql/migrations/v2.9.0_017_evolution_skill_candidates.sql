-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_skill_candidate_t (
    candidate_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id varchar(100) NOT NULL,
    skill_id integer NOT NULL,
    skill_name varchar(100) NOT NULL,
    base_digest char(64) NOT NULL,
    result_digest char(64) NOT NULL CHECK (result_digest <> base_digest),
    created_by varchar(100) NOT NULL,
    feedback jsonb NOT NULL,
    create_time timestamptz NOT NULL DEFAULT now(),
    feedback_digest char(64) NOT NULL,
    UNIQUE (tenant_id, skill_id, base_digest, result_digest, created_by, feedback_digest)
);
COMMENT ON TABLE nexent.evolution_skill_candidate_t IS 'Skill editor proposals referencing immutable original and edited packages.';
COMMENT ON COLUMN nexent.evolution_skill_candidate_t.candidate_id IS 'Reference used by a privileged evaluation job.';
COMMENT ON COLUMN nexent.evolution_skill_candidate_t.tenant_id IS 'Tenant owning the Skill.';
COMMENT ON COLUMN nexent.evolution_skill_candidate_t.skill_id IS 'Target Skill catalog record.';
COMMENT ON COLUMN nexent.evolution_skill_candidate_t.skill_name IS 'Skill name at generation.';
COMMENT ON COLUMN nexent.evolution_skill_candidate_t.base_digest IS 'SHA-256 of the original full package.';
COMMENT ON COLUMN nexent.evolution_skill_candidate_t.result_digest IS 'SHA-256 of the candidate full package.';
COMMENT ON COLUMN nexent.evolution_skill_candidate_t.created_by IS 'Authorized Skill editor submitting the proposal.';
COMMENT ON COLUMN nexent.evolution_skill_candidate_t.feedback IS 'Approved development feedback and scoped edit.';
COMMENT ON COLUMN nexent.evolution_skill_candidate_t.create_time IS 'Time the proposal was first recorded.';
COMMENT ON COLUMN nexent.evolution_skill_candidate_t.feedback_digest IS 'Hash of the exact feedback used for idempotency.';
