-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Personal pin preferences follow the owned conversation, not a tenant-specific row.
-- Keep the legacy table for rollout inspection; never backfill again on rerun.
DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent' AND table_name = 'conversation_record_t'
          AND column_name = 'workbench_pinned_at'
    ) THEN
        ALTER TABLE nexent.conversation_record_t ADD COLUMN workbench_pinned_at TIMESTAMPTZ;
        IF to_regclass('nexent.conversation_workbench_pin_t') IS NOT NULL THEN
            IF EXISTS (
                SELECT 1 FROM (
                    SELECT DISTINCT ON (user_id, tenant_id, conversation_id)
                        user_id, tenant_id, conversation_id, delete_flag
                    FROM nexent.conversation_workbench_pin_t
                    ORDER BY user_id, tenant_id, conversation_id, pin_id DESC
                ) p
                JOIN nexent.conversation_record_t c ON c.conversation_id = p.conversation_id
                WHERE p.delete_flag = 'N' AND c.created_by = p.user_id AND c.delete_flag = 'N'
                  AND c.workbench_config IS NOT NULL AND c.workbench_config != 'null'::jsonb
                GROUP BY p.user_id, p.conversation_id HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION 'Ambiguous Workbench pins across tenants; reconcile legacy personal preferences before migration';
            END IF;
            UPDATE nexent.conversation_record_t c SET workbench_pinned_at = p.pinned_at
            FROM (
                SELECT DISTINCT ON (user_id, tenant_id, conversation_id)
                    user_id, tenant_id, conversation_id, pinned_at, delete_flag
                FROM nexent.conversation_workbench_pin_t
                ORDER BY user_id, tenant_id, conversation_id, pin_id DESC
            ) p
            WHERE p.conversation_id = c.conversation_id AND p.user_id = c.created_by
              AND p.delete_flag = 'N' AND c.delete_flag = 'N'
              AND c.workbench_config IS NOT NULL AND c.workbench_config != 'null'::jsonb;
        END IF;
    END IF;
END
$migration$;

COMMENT ON COLUMN nexent.conversation_record_t.workbench_pinned_at IS
    'Personal Workbench pin time; NULL means unpinned; independent of conversation activity';
CREATE INDEX IF NOT EXISTS idx_conversation_workbench_pin_order
    ON nexent.conversation_record_t (created_by, workbench_pinned_at DESC, conversation_id DESC)
    WHERE delete_flag = 'N' AND workbench_pinned_at IS NOT NULL
      AND workbench_config IS NOT NULL AND workbench_config != 'null'::jsonb;
