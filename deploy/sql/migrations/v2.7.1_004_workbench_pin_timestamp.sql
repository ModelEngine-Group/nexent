-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS workbench_pinned_at TIMESTAMP;

COMMENT ON COLUMN nexent.conversation_record_t.workbench_pinned_at IS
    'Personal Workbench pin time as a UTC timestamp; NULL means unpinned; independent of conversation activity';

CREATE INDEX IF NOT EXISTS idx_conversation_workbench_pin_order
    ON nexent.conversation_record_t (created_by, workbench_pinned_at DESC, conversation_id DESC)
    WHERE delete_flag = 'N' AND workbench_pinned_at IS NOT NULL
      AND workbench_config IS NOT NULL AND workbench_config != 'null'::jsonb;
