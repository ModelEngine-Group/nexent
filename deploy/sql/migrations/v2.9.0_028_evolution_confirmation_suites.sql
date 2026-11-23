-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.evolution_replay_case_t ADD COLUMN IF NOT EXISTS source_partitioned boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_evolution_legacy_partition_cases ON nexent.evolution_replay_case_t (tenant_id, agent_id)
    WHERE NOT source_partitioned;
CREATE TABLE IF NOT EXISTS nexent.evolution_confirmation_curator_t (
    tenant_id varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    user_id varchar(100) NOT NULL,
    enabled boolean NOT NULL,
    updated_by varchar(100) NOT NULL,
    update_time timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, agent_id, user_id)
);
CREATE TABLE IF NOT EXISTS nexent.evolution_confirmation_suite_t (
    suite_id bigserial PRIMARY KEY,
    tenant_id varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    version_no integer NOT NULL,
    digest char(64) NOT NULL,
    manifest jsonb NOT NULL,
    created_by varchar(100) NOT NULL,
    create_time timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, agent_id, version_no, digest)
);
CREATE TABLE IF NOT EXISTS nexent.evolution_partition_source_t (
    tenant_id varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    source_key varchar(96) NOT NULL,
    partition_name varchar(16) NOT NULL CHECK (partition_name IN ('development','confirmation')),
    PRIMARY KEY (tenant_id, agent_id, source_key)
);
COMMENT ON TABLE nexent.evolution_confirmation_suite_t IS 'Immutable fingerprints from the independent evaluator; no task text, answers or attachments.';
COMMENT ON TABLE nexent.evolution_partition_source_t IS 'Exclusive source partition across published versions of one business Agent.';
COMMENT ON TABLE nexent.evolution_confirmation_curator_t IS 'Explicit, revocable tenant and Agent scoped authority to register independent test suites.';
COMMENT ON COLUMN nexent.evolution_replay_case_t.source_partitioned IS 'Source fingerprints were reserved in the same transaction as this development case.';
COMMENT ON COLUMN nexent.evolution_confirmation_curator_t.tenant_id IS 'Tenant that controls the independent evaluation scope.';
COMMENT ON COLUMN nexent.evolution_confirmation_curator_t.agent_id IS 'Business Agent covered by this grant.';
COMMENT ON COLUMN nexent.evolution_confirmation_curator_t.user_id IS 'Tenant member allowed to register independent suites.';
COMMENT ON COLUMN nexent.evolution_confirmation_curator_t.enabled IS 'Whether the grant is currently active.';
COMMENT ON COLUMN nexent.evolution_confirmation_curator_t.updated_by IS 'Administrator who last applied the grant.';
COMMENT ON COLUMN nexent.evolution_confirmation_curator_t.update_time IS 'Time of the last grant update.';
COMMENT ON COLUMN nexent.evolution_confirmation_suite_t.suite_id IS 'Identifier for the immutable suite manifest.';
COMMENT ON COLUMN nexent.evolution_confirmation_suite_t.tenant_id IS 'Owning evaluation tenant.';
COMMENT ON COLUMN nexent.evolution_confirmation_suite_t.agent_id IS 'Business Agent for this suite.';
COMMENT ON COLUMN nexent.evolution_confirmation_suite_t.version_no IS 'Released baseline selected by the independent evaluator.';
COMMENT ON COLUMN nexent.evolution_confirmation_suite_t.digest IS 'SHA-256 of the canonical public manifest.';
COMMENT ON COLUMN nexent.evolution_confirmation_suite_t.manifest IS 'Format, scope, case digests and source fingerprints produced offline.';
COMMENT ON COLUMN nexent.evolution_confirmation_suite_t.created_by IS 'Authorized independent evaluator who first registered the suite.';
COMMENT ON COLUMN nexent.evolution_confirmation_suite_t.create_time IS 'Time the immutable suite was registered.';
COMMENT ON COLUMN nexent.evolution_partition_source_t.tenant_id IS 'Owning evaluation tenant.';
COMMENT ON COLUMN nexent.evolution_partition_source_t.agent_id IS 'Business Agent whose partitions are separated across releases.';
COMMENT ON COLUMN nexent.evolution_partition_source_t.source_key IS 'Typed fingerprint of an input, source group or conversation.';
COMMENT ON COLUMN nexent.evolution_partition_source_t.partition_name IS 'Development (including fixed regression), or independent confirmation.';
