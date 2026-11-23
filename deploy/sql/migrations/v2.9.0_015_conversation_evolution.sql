-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS evolution_tenant_id varchar(100),
    ADD COLUMN IF NOT EXISTS evolution_setting_time timestamptz;
COMMENT ON COLUMN nexent.conversation_record_t.evolution_tenant_id IS
    'Tenant authorized by the owner for future automatic evolution analysis; NULL when disabled.';
COMMENT ON COLUMN nexent.conversation_record_t.evolution_setting_time IS
    'Time of the latest change to the conversation analysis setting.';

ALTER TABLE nexent.conversation_run_admission_t
    ADD COLUMN IF NOT EXISTS evolution_source_message_id integer;
COMMENT ON COLUMN nexent.conversation_run_admission_t.evolution_source_message_id IS
    'Original user message eligible for evolution analysis in this admitted run.';
CREATE INDEX IF NOT EXISTS idx_admission_evolution_message
    ON nexent.conversation_run_admission_t (tenant_id, conversation_id, evolution_source_message_id)
    WHERE evolution_source_message_id IS NOT NULL;

ALTER TABLE nexent.trajectory_execution_t
    ADD COLUMN IF NOT EXISTS agentos_run_id varchar(32);
COMMENT ON COLUMN nexent.trajectory_execution_t.agentos_run_id IS
    'Trusted AgentOS run identifier linking the root execution to its admission.';
CREATE INDEX IF NOT EXISTS idx_trajectory_agentos_run ON nexent.trajectory_execution_t (agentos_run_id)
    WHERE agentos_run_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS nexent.evolution_review_batch_t (
    batch_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    agent_version_no integer NOT NULL CHECK (agent_version_no > 0),
    status varchar(30) NOT NULL DEFAULT 'pending',
    create_time timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS nexent.evolution_review_turn_t (
    turn_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    agent_version_no integer NOT NULL CHECK (agent_version_no > 0),
    conversation_id integer NOT NULL,
    source_message_id integer NOT NULL,
    trajectory_id uuid NOT NULL,
    batch_id bigint REFERENCES nexent.evolution_review_batch_t(batch_id),
    UNIQUE (tenant_id, conversation_id, source_message_id)
);
CREATE INDEX IF NOT EXISTS idx_evolution_unbatched_turn
    ON nexent.evolution_review_turn_t (tenant_id, agent_id, agent_version_no, turn_id)
    WHERE batch_id IS NULL;

COMMENT ON TABLE nexent.evolution_review_batch_t IS 'Management review job for five eligible user turns.';
COMMENT ON COLUMN nexent.evolution_review_batch_t.batch_id IS 'Stable job identifier retained across retries.';
COMMENT ON COLUMN nexent.evolution_review_batch_t.tenant_id IS 'Tenant authorizing the review.';
COMMENT ON COLUMN nexent.evolution_review_batch_t.agent_id IS 'Root business Agent used by all five turns.';
COMMENT ON COLUMN nexent.evolution_review_batch_t.agent_version_no IS 'Published root Agent version observed at execution.';
COMMENT ON COLUMN nexent.evolution_review_batch_t.status IS 'Review processing status.';
COMMENT ON COLUMN nexent.evolution_review_batch_t.create_time IS 'Time at which the batch was enqueued.';
COMMENT ON TABLE nexent.evolution_review_turn_t IS 'Authorized original user turns and their review batch membership.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.turn_id IS 'Registration order for eligible turns.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.tenant_id IS 'Tenant recorded on admission.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.agent_id IS 'Actual root business Agent recorded by the trajectory.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.agent_version_no IS 'Published root Agent version recorded by the trajectory.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.conversation_id IS 'Source business conversation.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.source_message_id IS 'Original user message shared by retries.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.trajectory_id IS 'Root execution providing the registration evidence.';
COMMENT ON COLUMN nexent.evolution_review_turn_t.batch_id IS 'Assigned review job; NULL while waiting for five turns.';
