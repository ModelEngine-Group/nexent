-- Scope interrupted-upload recovery to the service that created the upload.

ALTER TABLE nexent.knowledge_file_lifecycle_t
    ADD COLUMN IF NOT EXISTS upload_owner_service VARCHAR(32);

COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.upload_owner_service IS
    'Service responsible for recovering an in-progress upload';

CREATE INDEX IF NOT EXISTS idx_knowledge_file_lifecycle_upload_recovery
    ON nexent.knowledge_file_lifecycle_t (upload_owner_service, create_time)
    WHERE delete_flag = 'N' AND status = 'UPLOADING';
