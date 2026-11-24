-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.agent_execution_t ADD COLUMN IF NOT EXISTS agent_scope VARCHAR(100);

COMMENT ON COLUMN nexent.agent_execution_t.agent_scope IS
    'Tenant-local Agent or Workbench identity used to enforce the admitted run limit across Runtime replicas.';

CREATE INDEX IF NOT EXISTS idx_agent_execution_active_scope
    ON nexent.agent_execution_t (tenant_id, agent_scope)
    WHERE status IN ('starting', 'running') AND delete_flag = 'N';
