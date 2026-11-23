-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_new_skill_candidate_t (
    candidate_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id varchar(100) NOT NULL, agent_id integer NOT NULL, version_no integer NOT NULL CHECK(version_no>0),
    feedback_id bigint NOT NULL REFERENCES nexent.evolution_feedback_handoff_t(feedback_id),
    name varchar(80) NOT NULL, description text NOT NULL,
    digest char(64) NOT NULL, model_id integer NOT NULL, model_revision text NOT NULL,
    created_by varchar(100) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(tenant_id,feedback_id,created_by,model_id,model_revision)
);
COMMENT ON TABLE nexent.evolution_new_skill_candidate_t IS 'Isolated NL2Skill package proposed from independently observed successful business tasks.';
COMMENT ON COLUMN nexent.evolution_new_skill_candidate_t.candidate_id IS 'New Skill proposal identifier.';
COMMENT ON COLUMN nexent.evolution_new_skill_candidate_t.tenant_id IS 'Tenant that owns the proposal.';
COMMENT ON COLUMN nexent.evolution_new_skill_candidate_t.agent_id IS 'Business Agent that supplied the development evidence.';
COMMENT ON COLUMN nexent.evolution_new_skill_candidate_t.version_no IS 'Frozen business Agent version.';
COMMENT ON COLUMN nexent.evolution_new_skill_candidate_t.feedback_id IS 'Approved, generalized development brief.';
COMMENT ON COLUMN nexent.evolution_new_skill_candidate_t.name IS 'Proposed catalog name.';
COMMENT ON COLUMN nexent.evolution_new_skill_candidate_t.description IS 'NL2Skill generated description.';
COMMENT ON COLUMN nexent.evolution_new_skill_candidate_t.digest IS 'SHA-256 of the immutable candidate ZIP.';
COMMENT ON COLUMN nexent.evolution_new_skill_candidate_t.model_id IS 'Creator model binding.';
COMMENT ON COLUMN nexent.evolution_new_skill_candidate_t.model_revision IS 'Creator model revision used for generation.';
COMMENT ON COLUMN nexent.evolution_new_skill_candidate_t.created_by IS 'Designated Skill creator.';
COMMENT ON COLUMN nexent.evolution_new_skill_candidate_t.created_at IS 'First successful generation time.';
