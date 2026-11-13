-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

CREATE TABLE IF NOT EXISTS nexent.conversation_memory_completion_t (
    job_id VARCHAR(48) PRIMARY KEY,
    run_id VARCHAR(32) NOT NULL,
    job_type VARCHAR(20) NOT NULL CHECK (job_type IN ('turn_completed', 'final_answer')),
    agent_id INTEGER NOT NULL CHECK (agent_id > 0),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_token VARCHAR(32),
    finished_at TIMESTAMPTZ,
    selected_items JSONB CHECK (selected_items IS NULL OR jsonb_typeof(selected_items) = 'array'),
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS idx_conversation_memory_completion_ready
    ON nexent.conversation_memory_completion_t (next_attempt_at, job_id)
    WHERE finished_at IS NULL AND delete_flag = 'N';

COMMENT ON TABLE nexent.conversation_memory_completion_t IS
    'Recoverable Memory jobs committed with prepared conversation projection receipts.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.job_id IS 'Deterministic identifier derived from the run ID and Memory job type.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.run_id IS 'AgentOS run of the committed assistant projection.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.job_type IS 'Completed-turn external ingestion or final-answer extraction.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.agent_id IS 'Authorized root Agent pinned during conversation admission.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.attempts IS 'Number of worker lease claims for this job.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.next_attempt_at IS 'Next eligible claim time, or expiration time of the current lease.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.lease_token IS 'Worker token required to checkpoint or settle this claim.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.finished_at IS 'Time the job finished or stopped after its retry limit.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.selected_items IS 'Temporary array of selected Memory strings, cleared on settlement.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.created_by IS 'User who owns the assistant projection.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.updated_by IS 'Owning user on whose behalf the queue state is updated.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.create_time IS 'Time the projection committed the job.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.update_time IS 'Time the queue state was last updated.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.delete_flag IS 'Soft-deletion marker used when claiming pending work.';
