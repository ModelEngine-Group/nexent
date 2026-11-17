-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.runtime_knowledge_base_deletion_t (
    job_id VARCHAR(32) PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    knowledge_id INTEGER NOT NULL,
    collection VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL,
    revision INTEGER NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N',
    CONSTRAINT ck_runtime_kb_deletion_state CHECK (
        revision > 0 AND knowledge_id > 0 AND status IN ('deleting', 'deleted')
    )
);
COMMENT ON TABLE nexent.runtime_knowledge_base_deletion_t IS 'Runtime-owned one-shot physical KB collection deletion receipts; no queue or automatic retries.';
COMMENT ON COLUMN nexent.runtime_knowledge_base_deletion_t.job_id IS 'Stable UUID for one actor-scoped KB deletion request.';
COMMENT ON COLUMN nexent.runtime_knowledge_base_deletion_t.tenant_id IS 'Tenant owning the exclusive collection.';
COMMENT ON COLUMN nexent.runtime_knowledge_base_deletion_t.user_id IS 'Original authorized KB deletion actor.';
COMMENT ON COLUMN nexent.runtime_knowledge_base_deletion_t.knowledge_id IS 'Management knowledge resource reference.';
COMMENT ON COLUMN nexent.runtime_knowledge_base_deletion_t.collection IS 'Authorized logical collection; never a physical index name.';
COMMENT ON COLUMN nexent.runtime_knowledge_base_deletion_t.status IS 'Deleting reserves one write; deleted confirms physical absence.';
COMMENT ON COLUMN nexent.runtime_knowledge_base_deletion_t.revision IS 'StorageInterface optimistic concurrency revision.';
COMMENT ON COLUMN nexent.runtime_knowledge_base_deletion_t.create_time IS 'UTC time deletion ownership was reserved.';
COMMENT ON COLUMN nexent.runtime_knowledge_base_deletion_t.update_time IS 'UTC time of the latest cleanup observation.';
COMMENT ON COLUMN nexent.runtime_knowledge_base_deletion_t.created_by IS 'Trusted actor reserving collection deletion.';
COMMENT ON COLUMN nexent.runtime_knowledge_base_deletion_t.updated_by IS 'Trusted actor confirming collection cleanup.';
COMMENT ON COLUMN nexent.runtime_knowledge_base_deletion_t.delete_flag IS 'Soft deletion marker; active receipts remain N.';
