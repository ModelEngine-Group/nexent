-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.agent_automation_run_t
    ADD COLUMN IF NOT EXISTS projection_message_index INTEGER;

COMMENT ON COLUMN nexent.agent_automation_run_t.projection_message_index IS
    'Assistant message index while Management is reconciling an AgentOS execution.';

CREATE INDEX IF NOT EXISTS idx_agent_automation_pending_projection
    ON nexent.agent_automation_run_t (run_id)
    WHERE delete_flag = 'N' AND projection_message_index IS NOT NULL;
