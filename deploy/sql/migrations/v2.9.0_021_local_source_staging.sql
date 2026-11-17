-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

CREATE TABLE IF NOT EXISTS nexent.knowledge_local_source_t (
    stage_id VARCHAR(32) PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    local_source_path VARCHAR(2048) NOT NULL,
    original_filename VARCHAR(1024) NOT NULL,
    file_size BIGINT NOT NULL,
    source_sha256 VARCHAR(64) NOT NULL,
    state VARCHAR(30) NOT NULL,
    knowledge_id BIGINT,
    bound_file_id VARCHAR(32),
    version INTEGER NOT NULL DEFAULT 1,
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N',
    CONSTRAINT ck_local_source_state CHECK (state IN ('UPLOADING', 'READY', 'BINDING', 'BOUND')),
    CONSTRAINT ck_local_source_size CHECK (file_size >= 0)
);

COMMENT ON COLUMN nexent.knowledge_local_source_t.stage_id IS 'Random local upload identity before KB binding.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.tenant_id IS 'Tenant owning the unbound local upload.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.local_source_path IS 'Exact Management-owned local upload alias.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.original_filename IS 'Original basename returned to the upload caller.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.file_size IS 'Expected local source size in bytes.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.source_sha256 IS 'SHA256 of the original local source bytes.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.state IS 'Publication and single-target binding state.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.knowledge_id IS 'Authorized target KB; null before binding.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.bound_file_id IS 'Fixed target lifecycle ID; null before binding.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.version IS 'Revision used for compare-and-set updates.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.created_by IS 'User owning and permitted to consume the staged upload.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.updated_by IS 'Actor responsible for the latest staging change.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.create_time IS 'UTC time when the staging record was created.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.update_time IS 'UTC time when the staging record was last changed.';
COMMENT ON COLUMN nexent.knowledge_local_source_t.delete_flag IS 'Active row marker N; soft-deleted row marker Y.';

CREATE INDEX IF NOT EXISTS idx_local_source_owner_path
    ON nexent.knowledge_local_source_t (tenant_id, created_by, local_source_path)
    WHERE delete_flag = 'N';
