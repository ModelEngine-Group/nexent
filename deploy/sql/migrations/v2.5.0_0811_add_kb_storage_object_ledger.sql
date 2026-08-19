-- Add the durable ledger used to attribute retained KB source objects in MinIO.

CREATE TABLE IF NOT EXISTS nexent.knowledge_storage_object_t (
    storage_object_id BIGSERIAL PRIMARY KEY,
    tenant_id         VARCHAR(100)  NOT NULL,
    knowledge_id      BIGINT        NOT NULL,
    index_name        VARCHAR(100)  NOT NULL,
    bucket_name       VARCHAR(255)  NOT NULL,
    object_name       VARCHAR(1024) NOT NULL,
    raw_bytes         BIGINT        NOT NULL,
    status            VARCHAR(20)   NOT NULL DEFAULT 'COMMITTED',
    create_time       TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time       TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by        VARCHAR(100),
    updated_by        VARCHAR(100),
    delete_flag       VARCHAR(1)    NOT NULL DEFAULT 'N',
    CONSTRAINT uq_knowledge_storage_object_bucket_object
        UNIQUE (bucket_name, object_name),
    CONSTRAINT ck_knowledge_storage_object_raw_bytes_nonnegative
        CHECK (raw_bytes >= 0),
    CONSTRAINT ck_knowledge_storage_object_status
        CHECK (status IN ('COMMITTED', 'DELETED'))
);

ALTER TABLE nexent.knowledge_storage_object_t OWNER TO "root";

COMMENT ON TABLE nexent.knowledge_storage_object_t IS
    'Durable ownership and accounting ledger for retained knowledge-base source objects';
COMMENT ON COLUMN nexent.knowledge_storage_object_t.storage_object_id IS 'Storage object ledger ID';
COMMENT ON COLUMN nexent.knowledge_storage_object_t.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN nexent.knowledge_storage_object_t.knowledge_id IS 'Owning knowledge base ID';
COMMENT ON COLUMN nexent.knowledge_storage_object_t.index_name IS 'Owning Elasticsearch index name';
COMMENT ON COLUMN nexent.knowledge_storage_object_t.bucket_name IS 'MinIO bucket name';
COMMENT ON COLUMN nexent.knowledge_storage_object_t.object_name IS 'MinIO object name';
COMMENT ON COLUMN nexent.knowledge_storage_object_t.raw_bytes IS 'Authoritative MinIO object size in bytes';
COMMENT ON COLUMN nexent.knowledge_storage_object_t.status IS 'Accounting lifecycle status: COMMITTED or DELETED';
COMMENT ON COLUMN nexent.knowledge_storage_object_t.create_time IS 'Creation time, audit field';
COMMENT ON COLUMN nexent.knowledge_storage_object_t.update_time IS 'Update time, audit field';
COMMENT ON COLUMN nexent.knowledge_storage_object_t.created_by IS 'Creator ID, audit field';
COMMENT ON COLUMN nexent.knowledge_storage_object_t.updated_by IS 'Last updater ID, audit field';
COMMENT ON COLUMN nexent.knowledge_storage_object_t.delete_flag IS 'Soft delete flag: N or Y';

CREATE INDEX IF NOT EXISTS idx_knowledge_storage_object_tenant_active
    ON nexent.knowledge_storage_object_t (tenant_id)
    WHERE delete_flag = 'N' AND status = 'COMMITTED';

CREATE INDEX IF NOT EXISTS idx_knowledge_storage_object_kb_active
    ON nexent.knowledge_storage_object_t (tenant_id, knowledge_id)
    WHERE delete_flag = 'N' AND status = 'COMMITTED';
