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
    deleted_at           TIMESTAMP,
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

COMMENT ON TABLE nexent.knowledge_file_lifecycle_t IS
    'Durable lifecycle and failure record for one knowledge-base file upload';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.file_id IS
    'Stable opaque identifier for one file lifecycle record';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.tenant_id IS
    'Tenant isolation key';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.knowledge_id IS
    'Owning knowledge-base ID';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.index_name IS
    'Elasticsearch index associated with the knowledge base';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.bucket_name IS
    'MinIO bucket containing the source object';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.object_name IS
    'MinIO object key; nullable when upload does not create an object';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.original_filename IS
    'Effective filename used by processing and displayed to users';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.file_size IS
    'Uploaded file size in bytes';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.create_time IS
    'Lifecycle row creation time, used as an audit timestamp';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.update_time IS
    'Time of the latest lifecycle row update, used as an audit timestamp';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.uploaded_at IS
    'Time when the source object was successfully uploaded to MinIO';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.completed_at IS
    'Time when file chunks were successfully indexed into Elasticsearch';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.status IS
    'Lifecycle status: UPLOADING, UPLOADED, PROCESSING, FORWARDING, FAILED, COMPLETED, DELETE_REQUESTED, or DELETED';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.stage IS
    'Current processing stage, such as UPLOAD, PROCESS, FORWARD, or DELETE';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.process_task_id IS
    'Celery task ID for file parsing and processing';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.forward_task_id IS
    'Celery task ID for forwarding processed chunks to Elasticsearch';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.parent_task_id IS
    'Parent task ID for the processing task chain';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.processing_attempt IS
    'Number of processing attempts for this file';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.error_code IS
    'Stable machine-readable error code for the latest failure';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.error_message IS
    'Sanitized user-facing explanation of the latest failure';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.error_stage IS
    'Pipeline stage where the latest failure occurred';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.failed_at IS
    'Time when the latest failure was recorded';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.deleted_at IS
    'Time when the lifecycle record reached the DELETED status, when retained';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.storage_object_id IS
    'Related MinIO storage-accounting ledger record ID';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.created_by IS
    'User or service that created the lifecycle record';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.updated_by IS
    'User or service that performed the latest lifecycle update';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.delete_flag IS
    'Soft-delete flag inherited from the common audit model: N or Y';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.version IS
    'Optimistic-lock version incremented on each lifecycle update';
