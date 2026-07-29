-- Migration: Seed the system-provided A2UI generator for existing tenants
-- Date: 2026-07-27
-- Description: Existing tenants do not rerun initial local-tool discovery after an upgrade.
-- Fresh tenants receive the same entry from get_local_tools() during normal initialization.

SET search_path TO nexent;

-- Keep the catalog safe for deployments that ran an earlier draft of this
-- migration. Prefer a row already referenced by an agent and remove only
-- unreferenced duplicates.
WITH ranked_tools AS (
    SELECT
        tool.tool_id,
        ROW_NUMBER() OVER (
            PARTITION BY tool.author
            ORDER BY
                CASE WHEN EXISTS (
                    SELECT 1
                    FROM nexent.ag_tool_instance_t instance
                    WHERE instance.tool_id = tool.tool_id
                      AND instance.delete_flag <> 'Y'
                ) THEN 0 ELSE 1 END,
                tool.tool_id
        ) AS row_number
    FROM nexent.ag_tool_info_t tool
    WHERE tool.name = 'generate_a2ui'
      AND tool.delete_flag <> 'Y'
)
UPDATE nexent.ag_tool_info_t tool
SET delete_flag = 'Y',
    updated_by = 'system'
FROM ranked_tools ranked
WHERE tool.tool_id = ranked.tool_id
  AND ranked.row_number > 1
  AND NOT EXISTS (
      SELECT 1
      FROM nexent.ag_tool_instance_t instance
      WHERE instance.tool_id = tool.tool_id
        AND instance.delete_flag <> 'Y'
  );

-- Normalize catalog rows created by local discovery or an earlier draft of
-- this migration.
UPDATE nexent.ag_tool_info_t
SET source = 'local',
    usage = NULL,
    class_name = 'GenerateA2UITool',
    category = 'ui',
    labels = '["ui"]'::jsonb,
    is_available = TRUE
WHERE name = 'generate_a2ui'
  AND delete_flag <> 'Y';

WITH tenant_catalog AS (
    SELECT
        tenant_id,
        MIN(user_id) AS audit_user
    FROM nexent.user_tenant_t
    WHERE tenant_id IS NOT NULL
      AND tenant_id <> ''
      AND delete_flag <> 'Y'
    GROUP BY tenant_id
)
INSERT INTO nexent.ag_tool_info_t (
    name,
    origin_name,
    class_name,
    description,
    source,
    author,
    usage,
    params,
    inputs,
    output_type,
    category,
    labels,
    is_available,
    created_by,
    updated_by,
    delete_flag
)
SELECT
    'generate_a2ui',
    'generate_a2ui',
    'GenerateA2UITool',
    'Generate an interactive UI when structured presentation or user input is more useful than plain text. The UI is validated and cannot execute business operations directly.',
    'local',
    tenant_catalog.tenant_id,
    NULL,
    '[]'::json,
    '{"description":{"type":"string","description":"What the UI should communicate or collect"},"data":{"type":"object","description":"Structured data to display or bind"},"expectedOutput":{"type":"string","description":"Expected user-visible result and interactions"}}',
    'string',
    'ui',
    '["ui"]'::jsonb,
    TRUE,
    tenant_catalog.audit_user,
    tenant_catalog.audit_user,
    'N'
FROM tenant_catalog
WHERE NOT EXISTS (
    SELECT 1
    FROM nexent.ag_tool_info_t existing
    WHERE existing.author = tenant_catalog.tenant_id
      AND existing.name = 'generate_a2ui'
      AND existing.delete_flag <> 'Y'
);

-- Remove the legacy placeholder row only when it is not a real tenant.
UPDATE nexent.ag_tool_info_t
SET delete_flag = 'Y',
    updated_by = 'system'
WHERE name = 'generate_a2ui'
  AND author = 'tenant_id'
  AND delete_flag <> 'Y'
  AND NOT EXISTS (
      SELECT 1
      FROM nexent.user_tenant_t tenant
      WHERE tenant.tenant_id = 'tenant_id'
        AND tenant.delete_flag <> 'Y'
  );
