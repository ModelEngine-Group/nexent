-- Migration kind: REQUIRED_SCHEMA
-- Required for: conversation-level file preprocessing metadata.
-- Reason: tracks uploaded file processing status, fulltext cache paths, and embedding model for each file.

CREATE TABLE IF NOT EXISTS nexent.conversation_file_t (
    id              BIGSERIAL       PRIMARY KEY,
    conversation_id VARCHAR(64)     NOT NULL,
    tenant_id       VARCHAR(64)     NOT NULL,
    object_name     VARCHAR(512)    NOT NULL,
    filename        VARCHAR(256)    NOT NULL,
    content_hash    VARCHAR(64),
    status          VARCHAR(16)     NOT NULL DEFAULT 'pending',
    chunk_count     INT             NOT NULL DEFAULT 0,
    fulltext_key    VARCHAR(512),
    embedding_model VARCHAR(128),
    error_message   TEXT,
    create_time     TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time     TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by      VARCHAR(100),
    updated_by      VARCHAR(100),
    delete_flag     VARCHAR(1)      DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS idx_conv_file_conv_id
    ON nexent.conversation_file_t(conversation_id);

CREATE INDEX IF NOT EXISTS idx_conv_file_tenant
    ON nexent.conversation_file_t(tenant_id);

CREATE UNIQUE INDEX IF NOT EXISTS udx_conv_file_obj
    ON nexent.conversation_file_t(conversation_id, object_name);

COMMENT ON TABLE nexent.conversation_file_t IS
    'Tracks per-file preprocessing state for conversation-level file processing.';
