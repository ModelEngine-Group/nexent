-- Durable knowledge-base file lifecycle and failure records.

CREATE TABLE IF NOT EXISTS nexent.knowledge_file_lifecycle_t (
    file_id              VARCHAR(64) PRIMARY KEY,
    tenant_id            VARCHAR(100) NOT NULL,
    knowledge_id         BIGINT NOT NULL,
    index_name           VARCHAR(100) NOT NULL,
    bucket_name          VARCHAR(255),
    object_name          VARCHAR(1024),
    original_filename    VARCHAR(1024) NOT NULL,
    file_size            BIGINT,
    create_time          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    uploaded_at          TIMESTAMP,
    completed_at         TIMESTAMP,
    status               VARCHAR(30) NOT NULL DEFAULT 'UPLOADING',
    stage                VARCHAR(30),
    process_task_id      VARCHAR(64),
    forward_task_id      VARCHAR(64),
    parent_task_id       VARCHAR(64),
    processing_attempt   INTEGER NOT NULL DEFAULT 0,
    error_code           VARCHAR(100),
    error_message        TEXT,
    error_stage          VARCHAR(30),
    failed_at            TIMESTAMP,
    delete_requested_at  TIMESTAMP,
    deleted_at           TIMESTAMP,
    delete_requested_by  VARCHAR(100),
    storage_object_id    BIGINT,
    created_by           VARCHAR(100),
    updated_by           VARCHAR(100),
    delete_flag          VARCHAR(1) NOT NULL DEFAULT 'N',
    version              INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT ck_knowledge_file_lifecycle_status CHECK (
        status IN ('UPLOADING', 'UPLOADED', 'PROCESSING', 'FORWARDING',
                   'FAILED', 'COMPLETED', 'DELETE_REQUESTED', 'DELETED')
    )
);

CREATE INDEX IF NOT EXISTS idx_knowledge_file_lifecycle_kb_status
    ON nexent.knowledge_file_lifecycle_t (tenant_id, knowledge_id, status);
CREATE INDEX IF NOT EXISTS idx_knowledge_file_lifecycle_identity
    ON nexent.knowledge_file_lifecycle_t (tenant_id, index_name, object_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_file_lifecycle_active_identity
    ON nexent.knowledge_file_lifecycle_t (tenant_id, index_name, object_name)
    WHERE object_name IS NOT NULL AND status NOT IN ('DELETE_REQUESTED', 'DELETED');
CREATE INDEX IF NOT EXISTS idx_knowledge_file_lifecycle_maintenance
    ON nexent.knowledge_file_lifecycle_t (status, update_time);
