-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.knowledge_record_t ADD COLUMN IF NOT EXISTS summary_schedule JSONB;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'nexent.knowledge_record_t'::regclass
          AND conname = 'ck_knowledge_summary_schedule'
    ) THEN
        ALTER TABLE nexent.knowledge_record_t ADD CONSTRAINT ck_knowledge_summary_schedule CHECK (
            summary_schedule IS NULL OR (
                jsonb_typeof(summary_schedule) = 'object'
                AND octet_length(summary_schedule::text) <= 16384
            )
        );
    END IF;
END;
$$;
CREATE INDEX IF NOT EXISTS idx_knowledge_summary_schedule ON nexent.knowledge_record_t (knowledge_id)
    WHERE delete_flag = 'N' AND summary_frequency IS NOT NULL AND summary_schedule IS NOT NULL;
COMMENT ON COLUMN nexent.knowledge_record_t.summary_schedule IS
'Management-owned actual enabling user/configuration and last automatic summary data-version attempt; NULL retains unknown historical authorization.';
COMMENT ON INDEX nexent.idx_knowledge_summary_schedule IS
'Bounded active automatic-summary candidate paging by the existing knowledge ID; no uniqueness or identity backfill.';
