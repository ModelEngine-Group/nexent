-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.evaluation_set_t ADD COLUMN IF NOT EXISTS business_agent_id integer;
COMMENT ON COLUMN nexent.evaluation_set_t.business_agent_id IS 'Business Agent owning the replay set. Null for a conventional evaluation set.';

CREATE INDEX IF NOT EXISTS ix_eval_set_business_scope
    ON nexent.evaluation_set_t (tenant_id, business_agent_id) WHERE business_agent_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_eval_set_business_name
    ON nexent.evaluation_set_t (tenant_id, business_agent_id, lower(name))
    WHERE business_agent_id IS NOT NULL AND delete_flag = 'N';

CREATE TABLE IF NOT EXISTS nexent.evaluation_set_replay_case_t (
    evaluation_set_id bigint NOT NULL REFERENCES nexent.evaluation_set_t(evaluation_set_id) ON DELETE CASCADE,
    source_case_id bigint NOT NULL REFERENCES nexent.evolution_replay_case_t(case_id),
    digest char(64) NOT NULL,
    created_by varchar(100) NOT NULL,
    create_time timestamptz NOT NULL DEFAULT now(),
    updated_by varchar(100) NOT NULL,
    update_time timestamptz NOT NULL DEFAULT now(),
    delete_flag char(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N','Y')),
    PRIMARY KEY (evaluation_set_id, digest)
);
COMMENT ON TABLE nexent.evaluation_set_replay_case_t IS 'References to approved replay tasks in a business evaluation set.';
COMMENT ON COLUMN nexent.evaluation_set_replay_case_t.evaluation_set_id IS 'Business evaluation set owning this membership.';
COMMENT ON COLUMN nexent.evaluation_set_replay_case_t.source_case_id IS 'Approved immutable replay task implementing this membership.';
COMMENT ON COLUMN nexent.evaluation_set_replay_case_t.digest IS 'Task snapshot digest used to deduplicate equivalent tasks across releases.';
COMMENT ON COLUMN nexent.evaluation_set_replay_case_t.created_by IS 'Editor who first added this member.';
COMMENT ON COLUMN nexent.evaluation_set_replay_case_t.create_time IS 'Time when the membership was first created.';
COMMENT ON COLUMN nexent.evaluation_set_replay_case_t.updated_by IS 'Editor who last changed this membership.';
COMMENT ON COLUMN nexent.evaluation_set_replay_case_t.update_time IS 'Time when the membership last changed.';
COMMENT ON COLUMN nexent.evaluation_set_replay_case_t.delete_flag IS 'Whether the approved task has been removed from this set.';
