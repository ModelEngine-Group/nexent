-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
BEGIN;
ALTER TABLE nexent.knowledge_file_lifecycle_t
    ADD COLUMN IF NOT EXISTS source_upload_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source_reconcile_after TIMESTAMPTZ;
-- New SOURCE_UPLOAD audit writes are UTC naive timestamps from RecordStore.
-- Taking their latest update delays recovery conservatively; no legacy upload is guessed.
UPDATE nexent.knowledge_file_lifecycle_t
SET source_upload_started_at = update_time AT TIME ZONE 'UTC'
WHERE stage='SOURCE_UPLOAD' AND source_upload_sha256 IS NOT NULL
    AND source_upload_started_at IS NULL AND update_time IS NOT NULL;
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.source_upload_started_at IS 'UTC start of the durable source upload intent, independent of legacy audit timezone.';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.source_reconcile_after IS 'UTC earliest next source reconciliation attempt; null means immediately eligible.';
CREATE INDEX IF NOT EXISTS idx_knowledge_source_reconcile
ON nexent.knowledge_file_lifecycle_t (upload_owner_service, source_reconcile_after, source_upload_started_at)
WHERE delete_flag='N' AND status='UPLOADING' AND stage='SOURCE_UPLOAD';
COMMIT;
