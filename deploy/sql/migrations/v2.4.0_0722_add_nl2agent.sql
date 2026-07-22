-- Rebuild the unpublished NL2AGENT schema around one authoritative session row.
DO $$
BEGIN
    IF to_regclass('nexent.nl2agent_session_t') IS NOT NULL THEN
        UPDATE nexent.conversation_record_t AS conversation
        SET delete_flag = 'Y', updated_by = 'nl2agent_migration'
        WHERE conversation.delete_flag <> 'Y'
          AND conversation.conversation_id IN (
              SELECT session.conversation_id
              FROM nexent.nl2agent_session_t AS session
              WHERE session.delete_flag <> 'Y'
          );

        UPDATE nexent.conversation_message_t AS message
        SET delete_flag = 'Y', updated_by = 'nl2agent_migration'
        WHERE message.delete_flag <> 'Y'
          AND message.conversation_id IN (
              SELECT session.conversation_id FROM nexent.nl2agent_session_t AS session
          );
    END IF;
END
$$;

DROP TABLE IF EXISTS nexent.nl2agent_installation_operation_t;
DROP TABLE IF EXISTS nexent.nl2agent_session_t;
DROP TABLE IF EXISTS nexent.nl2agent_catalog_snapshot_t;

CREATE TABLE nexent.nl2agent_session_t (
    session_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    runner_agent_id INTEGER NOT NULL,
    draft_agent_id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    workflow_schema_version INTEGER NOT NULL,
    workflow_revision INTEGER NOT NULL DEFAULT 0,
    session_catalogs JSONB NOT NULL,
    workflow_state JSONB NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT uq_nl2agent_session_tenant_draft UNIQUE (tenant_id, draft_agent_id),
    CONSTRAINT uq_nl2agent_session_tenant_conversation UNIQUE (tenant_id, conversation_id),
    CONSTRAINT ck_nl2agent_session_status CHECK (status IN ('active', 'completed', 'abandoned')),
    CONSTRAINT ck_nl2agent_session_revision_matches
        CHECK ((workflow_state ->> 'revision')::INTEGER = workflow_revision)
);

CREATE INDEX idx_nl2agent_session_owner_status
ON nexent.nl2agent_session_t (tenant_id, user_id, status);

CREATE INDEX idx_nl2agent_session_status_update
ON nexent.nl2agent_session_t (status, update_time);

CREATE TABLE nexent.nl2agent_installation_operation_t (
    operation_id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    runner_agent_id INTEGER NOT NULL,
    draft_agent_id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    installation_key VARCHAR(255) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    resource_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    checkpoint JSONB NOT NULL DEFAULT '{}'::JSONB,
    attempt INTEGER NOT NULL DEFAULT 0,
    lease_owner VARCHAR(100),
    lease_expires_at TIMESTAMP WITHOUT TIME ZONE,
    result JSONB,
    error JSONB,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT uq_nl2agent_installation_operation_key
        UNIQUE (tenant_id, draft_agent_id, installation_key),
    CONSTRAINT ck_nl2agent_installation_operation_status
        CHECK (status IN ('pending', 'running', 'completed', 'failed'))
);

CREATE INDEX idx_nl2agent_installation_operation_lease
ON nexent.nl2agent_installation_operation_t (status, lease_expires_at);

COMMENT ON TABLE nexent.nl2agent_session_t
IS 'Authoritative NL2AGENT workflow and immutable catalog state';

WITH ranked_builders AS (
    SELECT agent_id,
           ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY agent_id) AS builder_rank
    FROM nexent.ag_tenant_agent_t
    WHERE name = 'nl2agent' AND delete_flag <> 'Y'
)
UPDATE nexent.ag_tenant_agent_t AS agent
SET delete_flag = 'Y', updated_by = 'nl2agent_migration'
FROM ranked_builders AS ranked
WHERE agent.agent_id = ranked.agent_id AND ranked.builder_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_nl2agent_builder_tenant_active
ON nexent.ag_tenant_agent_t (tenant_id)
WHERE name = 'nl2agent' AND delete_flag <> 'Y';
