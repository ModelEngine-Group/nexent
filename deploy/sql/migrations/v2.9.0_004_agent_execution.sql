-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

CREATE TABLE IF NOT EXISTS nexent.agent_execution_t (
    run_id VARCHAR(32) PRIMARY KEY,
    conversation_id INTEGER NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    owner_id VARCHAR(32),
    lease_until TIMESTAMPTZ,
    status VARCHAR(16) NOT NULL CHECK (status IN ('starting', 'running', 'completed', 'failed', 'stopped')),
    cancellation_requested BOOLEAN NOT NULL DEFAULT FALSE,
    resource_versions JSONB NOT NULL DEFAULT '{}',
    assistant_message_id INTEGER,
    journal_repair_pending BOOLEAN NOT NULL DEFAULT FALSE,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N',
    CHECK (jsonb_typeof(resource_versions) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_agent_execution_active_conversation
    ON nexent.agent_execution_t (conversation_id)
    WHERE delete_flag = 'N' AND status IN ('starting', 'running');
CREATE INDEX IF NOT EXISTS idx_agent_execution_lease
    ON nexent.agent_execution_t (lease_until)
    WHERE delete_flag = 'N' AND status IN ('starting', 'running');
CREATE INDEX IF NOT EXISTS idx_agent_execution_repair
    ON nexent.agent_execution_t (update_time)
    WHERE delete_flag = 'N' AND journal_repair_pending;

CREATE INDEX IF NOT EXISTS idx_agent_execution_message
    ON nexent.agent_execution_t (assistant_message_id)
    WHERE delete_flag = 'N' AND assistant_message_id IS NOT NULL;

COMMENT ON TABLE nexent.agent_execution_t IS 'Runtime-owned AgentOS execution lifecycle independent of the output retention window.';
COMMENT ON COLUMN nexent.agent_execution_t.run_id IS 'Stable AgentOS execution identifier.';
COMMENT ON COLUMN nexent.agent_execution_t.conversation_id IS 'Logical reference to the owned conversation.';
COMMENT ON COLUMN nexent.agent_execution_t.tenant_id IS 'Signed tenant scope at admission.';
COMMENT ON COLUMN nexent.agent_execution_t.owner_id IS 'Runtime process identifier that renews the lease.';
COMMENT ON COLUMN nexent.agent_execution_t.status IS 'Durable execution phase or terminal result.';
COMMENT ON COLUMN nexent.agent_execution_t.cancellation_requested IS 'Durable stop request for this execution only.';
COMMENT ON COLUMN nexent.agent_execution_t.journal_repair_pending IS 'Whether reconciliation must attempt to append the retained SSE terminal event.';
COMMENT ON COLUMN nexent.agent_execution_t.resource_versions IS 'Resolved agent, model and conversation configuration versions, without execution payloads or credentials.';
COMMENT ON COLUMN nexent.agent_execution_t.lease_until IS 'Database-clock deadline after which another Runtime can recover this execution.';
COMMENT ON COLUMN nexent.agent_execution_t.assistant_message_id IS 'Logical reference to the exact assistant projection committed by this run.';

ALTER TABLE nexent.agent_automation_run_t ADD COLUMN IF NOT EXISTS runtime_run_id VARCHAR(32);
COMMENT ON COLUMN nexent.agent_automation_run_t.runtime_run_id IS 'AgentOS execution identifier assigned before dispatch; null for legacy runs.';
