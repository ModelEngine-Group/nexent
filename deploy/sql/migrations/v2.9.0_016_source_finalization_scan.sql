-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
BEGIN;
CREATE INDEX IF NOT EXISTS idx_knowledge_source_finalize
ON nexent.knowledge_file_lifecycle_t (upload_owner_service, source_upload_started_at, source_reconcile_after)
WHERE delete_flag='N' AND status='UPLOADING'
    AND stage IN ('SOURCE_UPLOAD', 'SOURCE_CONFIRMED', 'SOURCE_ACCOUNTED');
COMMIT;
