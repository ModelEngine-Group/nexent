-- Document tag retrieval projection ledger.
--
-- Canonical knowledge_document assignments live in resource_tag_assignment and
-- must never be rolled back when a retrieval provider rejects or delays a
-- projection. This table tracks the provider-facing projection state
-- (pending/synced/failed/unsupported), a monotonic version, the exact payload
-- snapshot keyed by stable definition/value ids, and retry metadata so
-- retrieval filtering never claims success before the provider confirmed it.

CREATE TABLE IF NOT EXISTS nexent.document_tag_projection (
    projection_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL CHECK (btrim(tenant_id) <> ''),
    provider VARCHAR(20) NOT NULL CHECK (provider IN ('local', 'aidp')),
    knowledge_base_id VARCHAR(255) NOT NULL CHECK (btrim(knowledge_base_id) <> ''),
    provider_document_id VARCHAR(512) NOT NULL CHECK (btrim(provider_document_id) <> ''),
    resource_id TEXT NOT NULL CHECK (btrim(resource_id) <> ''),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'synced', 'failed', 'unsupported')),
    version BIGINT NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '[]'::JSONB,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_attempt_at TIMESTAMP WITH TIME ZONE,
    next_attempt_at TIMESTAMP WITH TIME ZONE,
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    CONSTRAINT uq_document_tag_projection_identity
        UNIQUE (tenant_id, provider, knowledge_base_id, provider_document_id)
);

CREATE INDEX IF NOT EXISTS idx_document_tag_projection_tenant_status
    ON nexent.document_tag_projection (tenant_id, status, next_attempt_at);

CREATE INDEX IF NOT EXISTS idx_document_tag_projection_kb
    ON nexent.document_tag_projection (tenant_id, provider, knowledge_base_id);

CREATE INDEX IF NOT EXISTS idx_document_tag_projection_resource
    ON nexent.document_tag_projection (tenant_id, resource_id);
