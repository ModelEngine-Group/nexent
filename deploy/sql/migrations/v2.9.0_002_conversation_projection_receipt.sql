-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

CREATE TABLE IF NOT EXISTS nexent.conversation_projection_receipt_t (
    run_id VARCHAR(32) PRIMARY KEY,
    message_id INTEGER NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    payload_sha256 VARCHAR(64) NOT NULL,
    unit_ids JSONB NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100) NOT NULL,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS idx_conversation_projection_receipt_message
    ON nexent.conversation_projection_receipt_t (message_id);

COMMENT ON TABLE nexent.conversation_projection_receipt_t IS 'Committed assistant projection receipts used for AgentOS replay.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.run_id IS 'Server-issued AgentOS run identifier for one committed projection.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.message_id IS 'Assistant message bound by the conversation finalization transaction.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.tenant_id IS 'Tenant of the authorized projection actor.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.payload_sha256 IS 'Versioned SHA-256 digest of the submitted projection payload.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.unit_ids IS 'Object mapping persisted unit indexes to their integer unit IDs.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.created_by IS 'User who owns and submitted the assistant projection.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.create_time IS 'Time the projection receipt was created.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.updated_by IS 'User recorded when writing the immutable receipt.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.update_time IS 'Time the immutable receipt was recorded.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.delete_flag IS 'Soft-delete marker; regular replay only reads active receipts.';
