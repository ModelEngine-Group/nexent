-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_release_scope_t (
    tenant_id varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    initial_version integer NOT NULL CHECK (initial_version > 0),
    enabled_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,agent_id)
);
COMMENT ON TABLE nexent.evolution_release_scope_t IS 'Native business agents using server-owned release selection.';
COMMENT ON COLUMN nexent.evolution_release_scope_t.tenant_id IS 'Tenant that owns this published agent.';
COMMENT ON COLUMN nexent.evolution_release_scope_t.agent_id IS 'Root business agent.';
COMMENT ON COLUMN nexent.evolution_release_scope_t.initial_version IS 'Stable version before the first evolution release.';
COMMENT ON COLUMN nexent.evolution_release_scope_t.enabled_at IS 'Time of the first release into this scope.';

CREATE TABLE IF NOT EXISTS nexent.evolution_session_version_t (
    tenant_id varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    conversation_id integer NOT NULL,
    version_no integer NOT NULL CHECK (version_no > 0),
    created_by varchar(100) NOT NULL,
    PRIMARY KEY (tenant_id,agent_id,conversation_id),
    FOREIGN KEY (tenant_id,agent_id) REFERENCES nexent.evolution_release_scope_t(tenant_id,agent_id)
);
COMMENT ON TABLE nexent.evolution_session_version_t IS 'Stable native conversation version selected at admission.';
COMMENT ON COLUMN nexent.evolution_session_version_t.tenant_id IS 'Tenant of the admitted conversation.';
COMMENT ON COLUMN nexent.evolution_session_version_t.agent_id IS 'Actual root agent.';
COMMENT ON COLUMN nexent.evolution_session_version_t.conversation_id IS 'Owned conversation or a server-reserved first-turn ID.';
COMMENT ON COLUMN nexent.evolution_session_version_t.version_no IS 'Published root version used by future turns.';
COMMENT ON COLUMN nexent.evolution_session_version_t.created_by IS 'Authenticated conversation owner.';
