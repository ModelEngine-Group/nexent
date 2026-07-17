WITH ranked_builders AS (
  SELECT agent_id,
         ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY agent_id) AS builder_rank
  FROM nexent.ag_tenant_agent_t
  WHERE name = 'nl2agent' AND delete_flag <> 'Y'
)
UPDATE nexent.ag_tenant_agent_t AS agent
SET delete_flag = 'Y',
    updated_by = 'nl2agent_migration'
FROM ranked_builders AS ranked
WHERE agent.agent_id = ranked.agent_id
  AND ranked.builder_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS "uq_nl2agent_builder_tenant_active"
ON nexent.ag_tenant_agent_t (tenant_id)
WHERE name = 'nl2agent' AND delete_flag <> 'Y';
