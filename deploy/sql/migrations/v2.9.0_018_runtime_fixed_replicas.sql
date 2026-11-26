-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Index scheduled automation occurrences that have started.
CREATE INDEX IF NOT EXISTS idx_agent_automation_run_started_occurrence
    ON nexent.agent_automation_run_t (task_id, scheduled_fire_at)
    WHERE user_message_id IS NOT NULL;

-- Index the active execution scope for admission across replicas.
ALTER TABLE nexent.agent_execution_t ADD COLUMN IF NOT EXISTS agent_scope VARCHAR(100);

COMMENT ON COLUMN nexent.agent_execution_t.agent_scope IS
    'Tenant-local Agent or Workbench identity used to enforce the admitted run limit across Runtime replicas.';

CREATE INDEX IF NOT EXISTS idx_agent_execution_active_scope
    ON nexent.agent_execution_t (tenant_id, agent_scope)
    WHERE status IN ('starting', 'running') AND delete_flag = 'N';

-- Index conversation execution history for Creator replay.
CREATE INDEX IF NOT EXISTS idx_agent_execution_conversation_history
    ON nexent.agent_execution_t (conversation_id, agent_scope, create_time DESC, run_id DESC)
    WHERE delete_flag = 'N';
