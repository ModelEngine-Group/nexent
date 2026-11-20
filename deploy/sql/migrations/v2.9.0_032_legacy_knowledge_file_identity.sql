-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

CREATE TABLE IF NOT EXISTS nexent.knowledge_legacy_file_identity_t (
    original_file_id VARCHAR(64) PRIMARY KEY,
    standard_file_id VARCHAR(32) NOT NULL UNIQUE,
    tenant_id VARCHAR(100) NOT NULL,
    knowledge_id BIGINT NOT NULL,
    lifecycle_revision BIGINT NOT NULL,
    source_generation INTEGER NOT NULL,
    plan_sha256 VARCHAR(64) NOT NULL,
    version BIGINT NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    create_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (standard_file_id ~ '^[0-9a-f]{32}$'),
    CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (knowledge_id > 0 AND lifecycle_revision >= 0 AND source_generation >= 0 AND version > 0)
);

COMMENT ON TABLE nexent.knowledge_legacy_file_identity_t IS
    'Reserved Runtime identity for a historical Management file. Reservation alone does not re-key or authorize ingestion.';
