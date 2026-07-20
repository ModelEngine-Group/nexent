-- Persist NL2AGENT workflow sessions so Redis can remain a disposable cache.
CREATE TABLE IF NOT EXISTS nexent.nl2agent_session_t (
    session_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    draft_agent_id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    workflow_schema_version INTEGER NOT NULL,
    workflow_revision INTEGER NOT NULL DEFAULT 0,
    catalog_revision INTEGER NOT NULL DEFAULT 0,
    workflow_state JSONB NOT NULL,
    session_catalogs JSONB NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT uq_nl2agent_session_tenant_draft UNIQUE (tenant_id, draft_agent_id),
    CONSTRAINT uq_nl2agent_session_tenant_conversation UNIQUE (tenant_id, conversation_id),
    CONSTRAINT ck_nl2agent_session_status CHECK (status IN ('active', 'completed', 'abandoned'))
);

CREATE INDEX IF NOT EXISTS idx_nl2agent_session_owner_status
ON nexent.nl2agent_session_t (tenant_id, user_id, status);

COMMENT ON TABLE nexent.nl2agent_session_t IS 'Durable NL2AGENT workflow session snapshots';
COMMENT ON COLUMN nexent.nl2agent_session_t.workflow_revision IS 'Optimistic-lock revision for workflow_state';
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name = 'nl2agent_session_t'
          AND column_name = 'catalog_revision'
    ) THEN
        COMMENT ON COLUMN nexent.nl2agent_session_t.catalog_revision
        IS 'Optimistic-lock revision for session_catalogs';
    END IF;
END $$;
