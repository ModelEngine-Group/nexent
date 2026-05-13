ALTER TABLE nexent.ag_a2a_external_agent_t
ADD COLUMN IF NOT EXISTS base_url VARCHAR(512);

COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.base_url IS 'Base URL for health checks (service root address)';

ALTER TABLE nexent.ag_a2a_message_t
    DROP CONSTRAINT IF EXISTS ag_a2a_message_t_task_id_fk;

ALTER TABLE nexent.ag_a2a_external_agent_relation_t
    DROP CONSTRAINT IF EXISTS fk_external_agent;

ALTER TABLE nexent.ag_a2a_artifact_t
    DROP CONSTRAINT IF EXISTS fk_artifact_task;