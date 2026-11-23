-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_run_admission_t
    ADD COLUMN IF NOT EXISTS prepared_automation_context JSONB;

COMMENT ON COLUMN nexent.conversation_run_admission_t.prepared_automation_context IS
    'Authorized scheduled-task proposal settings and persisted source message for the pending prepared run.';
