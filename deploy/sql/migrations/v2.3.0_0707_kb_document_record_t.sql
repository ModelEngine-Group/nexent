-- =============================================================================
-- Knowledge Base Document Record Tracking — V4 standard Phase 2
-- =============================================================================
-- Version: v2.3.0
-- Date: 2026-07-07
-- Description: Create kb_document_record_t for per-document tracking in the
--   V4 standard knowledge-base API. Stores document metadata, processing status,
--   and Celery task IDs for status polling.
--
-- Idempotency: every DDL statement is safe to run multiple times.
--   - CREATE TABLE IF NOT EXISTS
--   - CREATE INDEX IF NOT EXISTS
--   - CREATE OR REPLACE FUNCTION + DROP TRIGGER IF EXISTS + CREATE TRIGGER
-- =============================================================================

CREATE TABLE IF NOT EXISTS nexent.kb_document_record_t (
    doc_id          BIGSERIAL PRIMARY KEY,
    document_uuid   VARCHAR(64)  NOT NULL UNIQUE,
    knowledge_id    BIGINT       NOT NULL,
    tenant_id       VARCHAR(100) NOT NULL,
    source_uri      TEXT         NOT NULL,
    filename        VARCHAR(500),
    file_size       BIGINT,
    status          VARCHAR(30)  NOT NULL DEFAULT 'indexing',
    error_message   TEXT,
    chunk_count     INTEGER      DEFAULT 0,
    celery_task_id  VARCHAR(200),
    create_time     TIMESTAMP    NOT NULL DEFAULT NOW(),
    update_time     TIMESTAMP    NOT NULL DEFAULT NOW(),
    created_by      VARCHAR(100),
    updated_by      VARCHAR(100),
    delete_flag     VARCHAR(1)   NOT NULL DEFAULT 'N'
);

COMMENT ON TABLE nexent.kb_document_record_t IS
    'Per-document tracking table for the V4 standard knowledge-base API (Phase 2).';

COMMENT ON COLUMN nexent.kb_document_record_t.document_uuid  IS
    'Public opaque document identifier surfaced via /api/v1 endpoints.';
COMMENT ON COLUMN nexent.kb_document_record_t.knowledge_id  IS
    'FK → knowledge_record_t.knowledge_id.';
COMMENT ON COLUMN nexent.kb_document_record_t.source_uri    IS
    'MinIO object name or external URL (matches ES path_or_url).';
COMMENT ON COLUMN nexent.kb_document_record_t.status       IS
    'indexing | completed | failed | paused';
COMMENT ON COLUMN nexent.kb_document_record_t.celery_task_id IS
    'Celery task ID for status polling / cancellation.';
COMMENT ON COLUMN nexent.kb_document_record_t.delete_flag  IS
    'Soft-delete flag: Y = deleted, N = active.';

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_kb_doc_knowledge_id
    ON nexent.kb_document_record_t (knowledge_id)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_kb_doc_tenant_id
    ON nexent.kb_document_record_t (tenant_id)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_kb_doc_source_uri
    ON nexent.kb_document_record_t (knowledge_id, source_uri)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_kb_doc_celery_task
    ON nexent.kb_document_record_t (celery_task_id)
    WHERE celery_task_id IS NOT NULL AND delete_flag = 'N';

-- Auto-update update_time on every row change
CREATE OR REPLACE FUNCTION nexent.update_kb_document_update_time()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.update_time := NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_kb_document_update_time ON nexent.kb_document_record_t;
CREATE TRIGGER trg_kb_document_update_time
    BEFORE UPDATE ON nexent.kb_document_record_t
    FOR EACH ROW EXECUTE FUNCTION nexent.update_kb_document_update_time();
