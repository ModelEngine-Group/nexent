ALTER TABLE nexent.nl2agent_session_t
ADD COLUMN IF NOT EXISTS runner_agent_id int4;

UPDATE nexent.nl2agent_session_t AS session
SET runner_agent_id = runner.agent_id,
    updated_by = 'nl2agent_migration'
FROM nexent.ag_tenant_agent_t AS runner
WHERE session.runner_agent_id IS NULL
  AND runner.tenant_id = session.tenant_id
  AND runner.version_no = 0
  AND runner.name = 'nl2agent'
  AND runner.delete_flag <> 'Y';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM nexent.nl2agent_session_t
    WHERE runner_agent_id IS NULL
      AND delete_flag <> 'Y'
  ) THEN
    ALTER TABLE nexent.nl2agent_session_t
    ALTER COLUMN runner_agent_id SET NOT NULL;
  END IF;
END $$;
