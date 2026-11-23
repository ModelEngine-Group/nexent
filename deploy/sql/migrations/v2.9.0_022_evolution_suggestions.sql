-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.conversation_run_admission_t ADD COLUMN IF NOT EXISTS evolution_reply jsonb;
COMMENT ON COLUMN nexent.conversation_run_admission_t.evolution_reply IS
    'Committed chat receipt for this signed run; emitted by Runtime after Management confirms the source message.';
CREATE INDEX IF NOT EXISTS idx_admission_evolution_reply_source ON nexent.conversation_run_admission_t
    (tenant_id,created_by,conversation_id,(evolution_reply->>'source')) WHERE delete_flag='N' AND evolution_reply IS NOT NULL;

CREATE TABLE IF NOT EXISTS nexent.evolution_suggestion_t (
    suggestion_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id varchar(100) NOT NULL,
    submitter_id varchar(100) NOT NULL,
    conversation_id integer NOT NULL,
    source_message_id integer NOT NULL,
    agent_id integer NOT NULL,
    version_no integer NOT NULL CHECK (version_no > 0),
    skill_id integer,
    expected_behavior text NOT NULL,
    status varchar(24) NOT NULL CHECK (status IN ('clarifying','submitted','cancelled')),
    last_message_id integer NOT NULL,
    create_time timestamptz NOT NULL DEFAULT now(),
    update_time timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, submitter_id, conversation_id, source_message_id)
);
CREATE INDEX IF NOT EXISTS idx_evolution_suggestion_owner ON nexent.evolution_suggestion_t
    (tenant_id, submitter_id, conversation_id, suggestion_id DESC);
COMMENT ON TABLE nexent.evolution_suggestion_t IS 'Business-user Skill suggestions and pending clarifications tied to owned original chat messages.';
ALTER TABLE nexent.evolution_suggestion_t ADD COLUMN IF NOT EXISTS experiment_id bigint
    REFERENCES nexent.evolution_experiment_t(experiment_id);
COMMENT ON COLUMN nexent.evolution_suggestion_t.experiment_id IS 'Latest paired trial explicitly linked by a business Agent editor.';
