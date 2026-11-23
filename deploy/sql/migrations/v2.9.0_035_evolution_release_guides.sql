-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_release_guide_t (
    tenant_id varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    version_no integer NOT NULL CHECK (version_no > 0),
    name varchar(80) NOT NULL,
    candidate_id bigint NOT NULL,
    digest varchar(64) NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (tenant_id, agent_id, version_no, name)
);
COMMENT ON TABLE nexent.evolution_release_guide_t IS 'Immutable read-only Skill packages installed on one business Agent version.';
COMMENT ON COLUMN nexent.evolution_release_guide_t.tenant_id IS 'Tenant that owns the released Agent.';
COMMENT ON COLUMN nexent.evolution_release_guide_t.agent_id IS 'Business Agent receiving the new Skill.';
COMMENT ON COLUMN nexent.evolution_release_guide_t.version_no IS 'Published version that may mount the package.';
COMMENT ON COLUMN nexent.evolution_release_guide_t.name IS 'Name used in the model catalog and by the Skill reader.';
COMMENT ON COLUMN nexent.evolution_release_guide_t.candidate_id IS 'Original new Skill proposal selected for release.';
COMMENT ON COLUMN nexent.evolution_release_guide_t.digest IS 'SHA-256 of the verified ZIP in the business Agent package namespace.';
