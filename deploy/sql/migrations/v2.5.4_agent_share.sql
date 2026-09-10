BEGIN;

SET LOCAL search_path TO nexent, public;

ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS is_agent_share BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS nexent.agent_share_t (
    agent_share_id BIGSERIAL PRIMARY KEY,
    public_share_id UUID NOT NULL UNIQUE,
    tenant_id VARCHAR(100) NOT NULL,
    agent_id INTEGER NOT NULL,
    owner_user_id VARCHAR(100) NOT NULL,
    token_generation INTEGER NOT NULL DEFAULT 1 CHECK (token_generation > 0),
    token_nonce VARCHAR(128) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag CHAR(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N', 'Y'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_share_active
    ON nexent.agent_share_t (tenant_id, agent_id)
    WHERE status = 'active' AND delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_agent_share_owner
    ON nexent.agent_share_t (tenant_id, owner_user_id, delete_flag);

CREATE TABLE IF NOT EXISTS nexent.agent_share_session_t (
    share_session_id UUID PRIMARY KEY,
    agent_share_id BIGINT NOT NULL,
    visitor_user_id VARCHAR(100) NOT NULL,
    conversation_id BIGINT NOT NULL UNIQUE,
    agent_version_no INTEGER NOT NULL CHECK (agent_version_no > 0),
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag CHAR(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N', 'Y'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_share_session_visitor
    ON nexent.agent_share_session_t (agent_share_id, visitor_user_id);

CREATE INDEX IF NOT EXISTS idx_agent_share_session_conversation
    ON nexent.agent_share_session_t (conversation_id, delete_flag);

COMMIT;
