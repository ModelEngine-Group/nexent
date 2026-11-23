-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_release_skill_t (
    tenant_id varchar(100) NOT NULL, agent_id integer NOT NULL, version_no integer NOT NULL CHECK(version_no>0),
    instance_id integer NOT NULL, skill_id integer NOT NULL, digest varchar(64) NOT NULL, revision varchar(64) NOT NULL,
    PRIMARY KEY (tenant_id,agent_id,version_no,instance_id)
);
COMMENT ON TABLE nexent.evolution_release_skill_t IS 'Verified Skill packages pinned separately for each published root version.';
COMMENT ON COLUMN nexent.evolution_release_skill_t.tenant_id IS 'Owning tenant.';
COMMENT ON COLUMN nexent.evolution_release_skill_t.agent_id IS 'Published root agent.';
COMMENT ON COLUMN nexent.evolution_release_skill_t.version_no IS 'Immutable agent version.';
COMMENT ON COLUMN nexent.evolution_release_skill_t.instance_id IS 'Authorized skill binding.';
COMMENT ON COLUMN nexent.evolution_release_skill_t.skill_id IS 'Tenant skill package owner.';
COMMENT ON COLUMN nexent.evolution_release_skill_t.digest IS 'SHA-256 of the evaluated package.';
COMMENT ON COLUMN nexent.evolution_release_skill_t.revision IS 'Expected execution revision of the versioned binding.';
CREATE TABLE IF NOT EXISTS nexent.evolution_publisher_t (
    tenant_id varchar(100) NOT NULL, agent_id integer NOT NULL, user_id varchar(100) NOT NULL,
    enabled boolean NOT NULL, updated_by varchar(100) NOT NULL, PRIMARY KEY(tenant_id,agent_id,user_id)
);
COMMENT ON TABLE nexent.evolution_publisher_t IS 'Administratively designated release owners for a business agent.';
CREATE TABLE IF NOT EXISTS nexent.evolution_release_t (
    lock_id bigint PRIMARY KEY REFERENCES nexent.evolution_confirmation_result_t(lock_id),
    tenant_id varchar(100) NOT NULL, agent_id integer NOT NULL, base_version integer NOT NULL, new_version integer NOT NULL,
    candidate_digest varchar(64) NOT NULL, baseline_digest varchar(64) NOT NULL, published_by varchar(100) NOT NULL, reason text NOT NULL,
    published_at timestamptz NOT NULL DEFAULT now(), rollback_by varchar(100), rollback_reason text,
    rollback_at timestamptz, disabled boolean NOT NULL DEFAULT false, stop_reason text, stopped_by varchar(100), stopped_at timestamptz,
    UNIQUE (tenant_id,agent_id,new_version)
);
COMMENT ON TABLE nexent.evolution_release_t IS 'Promotion and rollback of the independently confirmed candidate.';
ALTER TABLE nexent.evolution_release_scope_t ADD COLUMN IF NOT EXISTS paused boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN nexent.evolution_release_scope_t.paused IS 'Stop new sessions if no verified default can be restored.';

CREATE TABLE IF NOT EXISTS nexent.evolution_release_event_t (
    lock_id bigint NOT NULL REFERENCES nexent.evolution_release_t(lock_id),
    action varchar(16) NOT NULL CHECK (action IN ('publish','pause','rollback','stop')),
    actor varchar(100) NOT NULL, reason text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(lock_id,action)
);
COMMENT ON TABLE nexent.evolution_release_event_t IS 'First effective publication, pause, restoration or emergency stop for a confirmed release.';
COMMENT ON COLUMN nexent.evolution_release_event_t.lock_id IS 'Independent comparison lock.';
COMMENT ON COLUMN nexent.evolution_release_event_t.action IS 'Effective release action.';
COMMENT ON COLUMN nexent.evolution_release_event_t.actor IS 'Authorized release owner.';
COMMENT ON COLUMN nexent.evolution_release_event_t.reason IS 'Recorded reason supplied by the owner.';
COMMENT ON COLUMN nexent.evolution_release_event_t.created_at IS 'First effective action time.';
COMMENT ON COLUMN nexent.evolution_publisher_t.tenant_id IS 'Owning tenant.';
COMMENT ON COLUMN nexent.evolution_publisher_t.agent_id IS 'Business agent within the tenant.';
COMMENT ON COLUMN nexent.evolution_publisher_t.user_id IS 'Designated release owner.';
COMMENT ON COLUMN nexent.evolution_publisher_t.enabled IS 'Whether this assignment is active.';
COMMENT ON COLUMN nexent.evolution_publisher_t.updated_by IS 'Administrator who last changed the assignment.';
COMMENT ON COLUMN nexent.evolution_release_t.lock_id IS 'Independent comparison used for publication.';
COMMENT ON COLUMN nexent.evolution_release_t.tenant_id IS 'Owning tenant.';
COMMENT ON COLUMN nexent.evolution_release_t.agent_id IS 'Root business agent.';
COMMENT ON COLUMN nexent.evolution_release_t.base_version IS 'Previously active version.';
COMMENT ON COLUMN nexent.evolution_release_t.new_version IS 'Published candidate version.';
COMMENT ON COLUMN nexent.evolution_release_t.candidate_digest IS 'Hash of the confirmed candidate recipe.';
COMMENT ON COLUMN nexent.evolution_release_t.baseline_digest IS 'Verified executable baseline for restoration.';
COMMENT ON COLUMN nexent.evolution_release_t.published_by IS 'Publisher identity.';
COMMENT ON COLUMN nexent.evolution_release_t.reason IS 'Publication reason.';
COMMENT ON COLUMN nexent.evolution_release_t.published_at IS 'Publication timestamp.';
COMMENT ON COLUMN nexent.evolution_release_t.rollback_by IS 'Owner who restored the default.';
COMMENT ON COLUMN nexent.evolution_release_t.rollback_reason IS 'Restoration reason.';
COMMENT ON COLUMN nexent.evolution_release_t.rollback_at IS 'Effective restoration time.';
COMMENT ON COLUMN nexent.evolution_release_t.disabled IS 'Whether existing sessions must stop using this version.';
COMMENT ON COLUMN nexent.evolution_release_t.stop_reason IS 'Emergency stop reason.';
COMMENT ON COLUMN nexent.evolution_release_t.stopped_by IS 'Owner who stopped this version.';
COMMENT ON COLUMN nexent.evolution_release_t.stopped_at IS 'Effective emergency stop time.';
