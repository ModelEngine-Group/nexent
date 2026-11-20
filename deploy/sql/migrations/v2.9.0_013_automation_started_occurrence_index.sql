-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

CREATE INDEX IF NOT EXISTS idx_agent_automation_run_started_occurrence
    ON nexent.agent_automation_run_t (task_id, scheduled_fire_at)
    WHERE user_message_id IS NOT NULL;
