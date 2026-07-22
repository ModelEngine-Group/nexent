-- Durable NL2AGENT workflow state and immutable provider catalog snapshots.
CREATE TABLE IF NOT EXISTS nexent.nl2agent_catalog_snapshot_t (
    tenant_id VARCHAR(100) NOT NULL,
    snapshot_id VARCHAR(64) NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    catalogs JSONB NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT nl2agent_catalog_snapshot_t_pk PRIMARY KEY (tenant_id, snapshot_id)
);

CREATE TABLE IF NOT EXISTS nexent.nl2agent_session_t (
    session_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    runner_agent_id INTEGER NOT NULL,
    draft_agent_id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    workflow_schema_version INTEGER NOT NULL,
    workflow_revision INTEGER NOT NULL DEFAULT 0,
    catalog_snapshot_id VARCHAR(64) NOT NULL,
    workflow_state JSONB NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT fk_nl2agent_session_catalog_snapshot
        FOREIGN KEY (tenant_id, catalog_snapshot_id)
        REFERENCES nexent.nl2agent_catalog_snapshot_t (tenant_id, snapshot_id),
    CONSTRAINT uq_nl2agent_session_tenant_draft UNIQUE (tenant_id, draft_agent_id),
    CONSTRAINT uq_nl2agent_session_tenant_conversation UNIQUE (tenant_id, conversation_id),
    CONSTRAINT ck_nl2agent_session_status
        CHECK (status IN ('active', 'completed', 'abandoned'))
);

CREATE INDEX IF NOT EXISTS idx_nl2agent_session_owner_status
ON nexent.nl2agent_session_t (tenant_id, user_id, status);

CREATE INDEX IF NOT EXISTS idx_nl2agent_session_status_update
ON nexent.nl2agent_session_t (status, update_time);

COMMENT ON TABLE nexent.nl2agent_session_t
IS 'Durable NL2AGENT workflow session snapshots';

WITH ranked_builders AS (
    SELECT agent_id,
           ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY agent_id) AS builder_rank
    FROM nexent.ag_tenant_agent_t
    WHERE name = 'nl2agent' AND delete_flag <> 'Y'
)
UPDATE nexent.ag_tenant_agent_t AS agent
SET delete_flag = 'Y',
    updated_by = 'nl2agent_migration'
FROM ranked_builders AS ranked
WHERE agent.agent_id = ranked.agent_id
  AND ranked.builder_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_nl2agent_builder_tenant_active
ON nexent.ag_tenant_agent_t (tenant_id)
WHERE name = 'nl2agent' AND delete_flag <> 'Y';
