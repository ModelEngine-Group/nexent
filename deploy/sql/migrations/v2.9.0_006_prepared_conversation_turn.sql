-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_run_admission_t
    ADD COLUMN IF NOT EXISTS prepared_user_turn JSONB,
    ADD COLUMN IF NOT EXISTS prepared_message_index INTEGER,
    ADD COLUMN IF NOT EXISTS prepared_assistant_id INTEGER;

COMMENT ON COLUMN nexent.conversation_run_admission_t.prepared_user_turn IS
    'Uncommitted user message and conversation settings retained until Runtime admission is resolved.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.prepared_message_index IS
    'Assistant message index while Management must reconcile this prepared run.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.prepared_assistant_id IS
    'Assistant message reserved by Management for this admitted run.';

CREATE INDEX IF NOT EXISTS idx_conversation_admission_pending_projection
    ON nexent.conversation_run_admission_t (conversation_id, run_id)
    WHERE delete_flag = 'N' AND prepared_message_index IS NOT NULL;

ALTER TABLE nexent.conversation_message_t ADD COLUMN IF NOT EXISTS streaming_owner VARCHAR(16);
COMMENT ON COLUMN nexent.conversation_message_t.streaming_owner IS
    'Service that owns terminal repair for this streaming assistant message. NULL means legacy Runtime ownership.';
