-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

DO $pin_timestamp$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_attribute
        WHERE attrelid = 'nexent.conversation_record_t'::regclass
          AND attname = 'workbench_pinned_at'
          AND atttypid = 'timestamp with time zone'::regtype
    ) THEN
        ALTER TABLE nexent.conversation_record_t
            ALTER COLUMN workbench_pinned_at TYPE TIMESTAMP
            USING workbench_pinned_at AT TIME ZONE 'UTC';
    END IF;
END;
$pin_timestamp$;

COMMENT ON COLUMN nexent.conversation_record_t.workbench_pinned_at IS
    'Personal Workbench pin time as a UTC timestamp; NULL means unpinned; independent of conversation activity';
