-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

CREATE TABLE IF NOT EXISTS nexent.conversation_run_admission_t (
    scope_sha256 VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    run_id VARCHAR(32) NOT NULL,
    request_sha256 VARCHAR(64) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    conversation_id INTEGER,
    journal_available BOOLEAN NOT NULL DEFAULT FALSE,
    created_by VARCHAR(100) NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100) NOT NULL,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);

COMMENT ON TABLE nexent.conversation_run_admission_t IS 'Durable conversation run submissions keyed by actor scope and idempotency key.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.scope_sha256 IS 'Digest of the tenant, authenticated user and client idempotency key.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.tenant_id IS 'Tenant that owns the submission.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.run_id IS 'Server-generated run identifier returned on retries.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.request_sha256 IS 'Digest of the normalized signed execution request.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.status IS 'Submission outcome: pending, admitted or rejected.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.conversation_id IS 'Owned conversation bound before starting the stream producer.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.journal_available IS 'Whether the run opened its Redis output journal at admission.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.created_by IS 'User who submitted the request.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.create_time IS 'Time of the first successful claim.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.updated_by IS 'User recorded when the admission outcome changed.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.update_time IS 'Time of the most recent admission change.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.delete_flag IS 'Soft-delete marker; a removed claim is never reassigned.';
