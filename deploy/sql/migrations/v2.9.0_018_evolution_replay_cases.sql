-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_replay_case_t (
    case_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    version_no integer NOT NULL CHECK (version_no > 0),
    digest char(64) NOT NULL,
    task jsonb NOT NULL,
    created_by varchar(100) NOT NULL,
    create_time timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, agent_id, version_no, digest)
);
COMMENT ON TABLE nexent.evolution_replay_case_t IS 'Immutable business-confirmed development tasks for comparative replay.';
COMMENT ON COLUMN nexent.evolution_replay_case_t.case_id IS 'Stable identifier for this exact task snapshot.';
COMMENT ON COLUMN nexent.evolution_replay_case_t.tenant_id IS 'Tenant authorizing use of the task.';
COMMENT ON COLUMN nexent.evolution_replay_case_t.agent_id IS 'Business Agent to which the task belongs.';
COMMENT ON COLUMN nexent.evolution_replay_case_t.version_no IS 'Released baseline version.';
COMMENT ON COLUMN nexent.evolution_replay_case_t.digest IS 'Canonical SHA-256 covering input, references and scoring label.';
COMMENT ON COLUMN nexent.evolution_replay_case_t.task IS 'Query, family, expected outcome, names and digests of approved attachments.';
COMMENT ON COLUMN nexent.evolution_replay_case_t.created_by IS 'Editor who confirmed the task.';
COMMENT ON COLUMN nexent.evolution_replay_case_t.create_time IS 'Time of initial confirmation.';
