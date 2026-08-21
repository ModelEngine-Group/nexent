BEGIN;

SET LOCAL search_path TO nexent, public;

-- Seed an "Agent Category" definition in every tenant's default_resource tag
-- library and populate it with the 20 preset tags previously hardcoded in the
-- Agent repository publish flow (frontend const/agentRepository.ts). Stable keys
-- are stored as normalized_value/display_value so the frontend can still resolve
-- localized labels via i18n while marketplace persistence stays locale-stable.
-- Idempotent: safe to rerun; existing values are kept active and re-ordered.

INSERT INTO nexent.tag_definition (
    tenant_id, bucket_id, definition_key, definition_name, selection_mode,
    sort_order, status, created_by, updated_by, delete_flag
)
SELECT bucket.tenant_id, bucket.bucket_id,
       'agent_category', 'Agent Category', 'multi_select', 1,
       'active', 'migration:v2.5.3', 'migration:v2.5.3', 'N'
FROM nexent.tag_bucket AS bucket
WHERE bucket.bucket_key = 'default_resource'
  AND bucket.delete_flag = 'N'
ON CONFLICT (tenant_id, bucket_id, definition_key) WHERE delete_flag = 'N' DO UPDATE
SET definition_name = 'Agent Category',
    selection_mode = 'multi_select',
    status = 'active',
    sort_order = EXCLUDED.sort_order,
    update_time = CURRENT_TIMESTAMP,
    updated_by = EXCLUDED.updated_by;

INSERT INTO nexent.tag_value (
    tenant_id, definition_id, normalized_value, display_value, sort_order,
    status, created_by, updated_by, delete_flag
)
SELECT bucket.tenant_id, definition.definition_id, preset.normalized_value,
       preset.display_value, preset.sort_order,
       'active', 'migration:v2.5.3', 'migration:v2.5.3', 'N'
FROM nexent.tag_bucket AS bucket
JOIN nexent.tag_definition AS definition
  ON definition.tenant_id = bucket.tenant_id
 AND definition.bucket_id = bucket.bucket_id
 AND definition.definition_key = 'agent_category'
 AND definition.delete_flag = 'N'
CROSS JOIN (VALUES
        ('marketing', 'marketing', 0),
        ('copywriting', 'copywriting', 1),
        ('content_creation', 'content_creation', 2),
        ('code_review', 'code_review', 3),
        ('quality', 'quality', 4),
        ('devops', 'devops', 5),
        ('data', 'data', 6),
        ('visualization', 'visualization', 7),
        ('bi', 'bi', 8),
        ('customer_service', 'customer_service', 9),
        ('ticket', 'ticket', 10),
        ('automation', 'automation', 11),
        ('meeting', 'meeting', 12),
        ('minutes', 'minutes', 13),
        ('productivity', 'productivity', 14),
        ('design', 'design', 15),
        ('color_scheme', 'color_scheme', 16),
        ('inspiration', 'inspiration', 17),
        ('spreadsheet', 'spreadsheet', 18),
        ('office', 'office', 19)
) AS preset(normalized_value, display_value, sort_order)
WHERE bucket.bucket_key = 'default_resource'
  AND bucket.delete_flag = 'N'
ON CONFLICT (tenant_id, definition_id, normalized_value) WHERE delete_flag = 'N' DO UPDATE
SET display_value = EXCLUDED.display_value,
    status = 'active',
    sort_order = EXCLUDED.sort_order,
    update_time = CURRENT_TIMESTAMP,
    updated_by = EXCLUDED.updated_by;

COMMIT;
