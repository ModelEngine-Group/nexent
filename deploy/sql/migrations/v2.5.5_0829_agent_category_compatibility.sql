BEGIN;

SET LOCAL search_path TO nexent, public;

-- Restore the final tenant provisioning function after v2.5.0 has replaced the
-- init.sql definition with its older bucket-only implementation. This forward
-- migration intentionally leaves Keywords creation to the legacy-data backfill.
CREATE OR REPLACE FUNCTION nexent.provision_unified_tag_management(
    p_tenant_id VARCHAR,
    p_actor VARCHAR DEFAULT 'system'
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_default_bucket_id BIGINT;
    v_document_bucket_id BIGINT;
BEGIN
    IF p_tenant_id IS NULL OR btrim(p_tenant_id) = '' THEN
        RAISE EXCEPTION 'Cannot provision unified tags for an empty tenant';
    END IF;

    INSERT INTO nexent.tag_bucket (
        tenant_id, bucket_key, bucket_name, status, created_by, updated_by, delete_flag
    ) VALUES (
        p_tenant_id, 'default_resource', 'Default Resource', 'active', p_actor, p_actor, 'N'
    )
    ON CONFLICT (tenant_id, bucket_key) DO UPDATE
    SET bucket_name = EXCLUDED.bucket_name,
        status = 'active',
        update_time = CURRENT_TIMESTAMP,
        updated_by = EXCLUDED.updated_by,
        delete_flag = 'N'
    RETURNING bucket_id INTO v_default_bucket_id;

    INSERT INTO nexent.tag_bucket (
        tenant_id, bucket_key, bucket_name, status, created_by, updated_by, delete_flag
    ) VALUES (
        p_tenant_id, 'knowledge_content', 'Knowledge Content', 'active', p_actor, p_actor, 'N'
    )
    ON CONFLICT (tenant_id, bucket_key) DO UPDATE
    SET bucket_name = EXCLUDED.bucket_name,
        status = 'active',
        update_time = CURRENT_TIMESTAMP,
        updated_by = EXCLUDED.updated_by,
        delete_flag = 'N'
    RETURNING bucket_id INTO v_document_bucket_id;

    INSERT INTO nexent.tag_bucket_resource_type (
        tenant_id, bucket_id, resource_type, status, created_by, updated_by, delete_flag
    )
    SELECT p_tenant_id, v_default_bucket_id, resource_type, 'active', p_actor, p_actor, 'N'
    FROM (VALUES ('agent'), ('skill'), ('tool'), ('mcp_service'), ('knowledge_base')) AS types(resource_type)
    ON CONFLICT (tenant_id, bucket_id, resource_type) DO UPDATE
    SET status = 'active', update_time = CURRENT_TIMESTAMP, updated_by = EXCLUDED.updated_by, delete_flag = 'N';

    INSERT INTO nexent.tag_bucket_resource_type (
        tenant_id, bucket_id, resource_type, status, created_by, updated_by, delete_flag
    ) VALUES (
        p_tenant_id, v_document_bucket_id, 'knowledge_document', 'active', p_actor, p_actor, 'N'
    )
    ON CONFLICT (tenant_id, bucket_id, resource_type) DO UPDATE
    SET status = 'active', update_time = CURRENT_TIMESTAMP, updated_by = EXCLUDED.updated_by, delete_flag = 'N';

    INSERT INTO nexent.tag_definition (
        tenant_id, bucket_id, definition_key, definition_name, selection_mode,
        sort_order, status, created_by, updated_by, delete_flag
    ) VALUES (
        p_tenant_id, v_default_bucket_id, 'agent_category', 'Agent Category',
        'multi_select', 1, 'active', p_actor, p_actor, 'N'
    )
    ON CONFLICT (tenant_id, bucket_id, definition_key) WHERE delete_flag = 'N' DO UPDATE
    SET definition_name = EXCLUDED.definition_name,
        selection_mode = EXCLUDED.selection_mode,
        status = 'active',
        sort_order = EXCLUDED.sort_order,
        update_time = CURRENT_TIMESTAMP,
        updated_by = EXCLUDED.updated_by,
        delete_flag = 'N';

    INSERT INTO nexent.tag_value (
        tenant_id, definition_id, normalized_value, display_value, sort_order,
        status, created_by, updated_by, delete_flag
    )
    SELECT p_tenant_id, definition.definition_id, preset.normalized_value,
           preset.display_value, preset.sort_order, 'active', p_actor, p_actor, 'N'
    FROM nexent.tag_definition AS definition
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
    WHERE definition.tenant_id = p_tenant_id
      AND definition.bucket_id = v_default_bucket_id
      AND definition.definition_key = 'agent_category'
      AND definition.delete_flag = 'N'
    ON CONFLICT (tenant_id, definition_id, normalized_value) WHERE delete_flag = 'N' DO UPDATE
    SET display_value = EXCLUDED.display_value,
        status = 'active',
        sort_order = EXCLUDED.sort_order,
        update_time = CURRENT_TIMESTAMP,
        updated_by = EXCLUDED.updated_by,
        delete_flag = 'N';
END;
$$;

-- Heal every active tenant and every historical tenant that already owns a tag
-- bucket. The UNION keeps provisioning idempotent and does not recreate user
-- membership rows for historical tenants.
SELECT nexent.provision_unified_tag_management(tenant_id, 'migration:v2.5.5')
FROM (
    SELECT DISTINCT tenant_id
    FROM nexent.user_tenant_t
    WHERE tenant_id IS NOT NULL
      AND btrim(tenant_id) <> ''
      AND COALESCE(delete_flag, 'N') <> 'Y'
    UNION
    SELECT DISTINCT tenant_id
    FROM nexent.tag_bucket
    WHERE tenant_id IS NOT NULL
      AND btrim(tenant_id) <> ''
      AND delete_flag = 'N'
) AS tenants;

-- Known aliases are intentionally finite. Unknown/custom historical strings
-- remain under Keywords and are not inferred as Agent categories.
CREATE TEMP TABLE utm_agent_category_alias (
    normalized_alias TEXT PRIMARY KEY,
    category_key TEXT NOT NULL
) ON COMMIT DROP;

INSERT INTO utm_agent_category_alias (normalized_alias, category_key) VALUES
    ('marketing', 'marketing'), ('营销', 'marketing'),
    ('copywriting', 'copywriting'), ('文案', 'copywriting'),
    ('content_creation', 'content_creation'), ('content creation', 'content_creation'),
    ('内容创作', 'content_creation'),
    ('code_review', 'code_review'), ('code review', 'code_review'), ('代码审查', 'code_review'),
    ('quality', 'quality'), ('质量', 'quality'),
    ('devops', 'devops'),
    ('data', 'data'), ('数据', 'data'),
    ('visualization', 'visualization'), ('可视化', 'visualization'),
    ('bi', 'bi'),
    ('customer_service', 'customer_service'), ('customer support', 'customer_service'),
    ('customer service', 'customer_service'), ('客服', 'customer_service'),
    ('ticket', 'ticket'), ('ticketing', 'ticket'), ('工单', 'ticket'),
    ('automation', 'automation'), ('自动化', 'automation'),
    ('meeting', 'meeting'), ('会议', 'meeting'),
    ('minutes', 'minutes'), ('纪要', 'minutes'),
    ('productivity', 'productivity'), ('效率', 'productivity'),
    ('design', 'design'), ('设计', 'design'),
    ('color_scheme', 'color_scheme'), ('color scheme', 'color_scheme'), ('配色', 'color_scheme'),
    ('inspiration', 'inspiration'), ('灵感', 'inspiration'),
    ('spreadsheet', 'spreadsheet'), ('表格', 'spreadsheet'),
    ('office', 'office'), ('办公', 'office');

CREATE TEMP TABLE utm_agent_category_source (
    source_row_id TEXT NOT NULL,
    tenant_id VARCHAR(100),
    resource_id TEXT,
    category_key TEXT NOT NULL,
    canonical_match_count INTEGER NOT NULL
) ON COMMIT DROP;

INSERT INTO utm_agent_category_source
SELECT repository.agent_repository_id::TEXT,
       repository.publisher_tenant_id,
       repository.agent_id::TEXT,
       aliases.category_key,
       (SELECT count(*)
        FROM nexent.ag_tenant_agent_t AS agent
        WHERE agent.agent_id = repository.agent_id
          AND agent.tenant_id = repository.publisher_tenant_id)
FROM nexent.ag_agent_repository_t AS repository
CROSS JOIN LATERAL unnest(repository.tags) AS expanded(raw_value)
JOIN utm_agent_category_alias AS aliases
  ON aliases.normalized_alias = lower(btrim(expanded.raw_value) COLLATE "C")
WHERE COALESCE(cardinality(repository.tags), 0) > 0
  AND COALESCE(repository.delete_flag, 'N') <> 'Y';

DO $$
DECLARE
    v_conflict_count BIGINT;
    v_sample JSONB;
BEGIN
    SELECT count(*) INTO v_conflict_count
    FROM utm_agent_category_source
    WHERE tenant_id IS NULL
       OR btrim(tenant_id) = ''
       OR resource_id IS NULL
       OR canonical_match_count < 1;

    IF v_conflict_count > 0 THEN
        SELECT jsonb_agg(to_jsonb(conflict)) INTO v_sample
        FROM (
            SELECT source_row_id, tenant_id, resource_id, category_key, canonical_match_count
            FROM utm_agent_category_source
            WHERE tenant_id IS NULL
               OR btrim(tenant_id) = ''
               OR resource_id IS NULL
               OR canonical_match_count < 1
            ORDER BY source_row_id, category_key
            LIMIT 20
        ) AS conflict;
        RAISE EXCEPTION 'Agent category migration blocked by % canonical-source conflict(s): %',
            v_conflict_count, v_sample;
    END IF;
END;
$$;

CREATE TEMP TABLE utm_agent_category_projection ON COMMIT DROP AS
SELECT DISTINCT source.tenant_id,
       'agent'::VARCHAR(50) AS resource_type,
       source.resource_id,
       definition.definition_id,
       value.value_id
FROM utm_agent_category_source AS source
JOIN nexent.tag_bucket AS bucket
  ON bucket.tenant_id = source.tenant_id
 AND bucket.bucket_key = 'default_resource'
 AND bucket.delete_flag = 'N'
JOIN nexent.tag_definition AS definition
  ON definition.tenant_id = bucket.tenant_id
 AND definition.bucket_id = bucket.bucket_id
 AND definition.definition_key = 'agent_category'
 AND definition.delete_flag = 'N'
JOIN nexent.tag_value AS value
  ON value.tenant_id = definition.tenant_id
 AND value.definition_id = definition.definition_id
 AND value.normalized_value = source.category_key
 AND value.delete_flag = 'N';

DO $$
DECLARE
    v_missing_count BIGINT;
BEGIN
    SELECT count(*) INTO v_missing_count
    FROM (
        SELECT DISTINCT tenant_id, resource_id, category_key
        FROM utm_agent_category_source
    ) AS source
    WHERE NOT EXISTS (
        SELECT 1
        FROM nexent.tag_bucket AS bucket
        JOIN nexent.tag_definition AS definition
          ON definition.tenant_id = bucket.tenant_id
         AND definition.bucket_id = bucket.bucket_id
         AND definition.definition_key = 'agent_category'
         AND definition.delete_flag = 'N'
        JOIN nexent.tag_value AS value
          ON value.tenant_id = definition.tenant_id
         AND value.definition_id = definition.definition_id
         AND value.normalized_value = source.category_key
         AND value.delete_flag = 'N'
        WHERE bucket.tenant_id = source.tenant_id
          AND bucket.bucket_key = 'default_resource'
          AND bucket.delete_flag = 'N'
    );

    IF v_missing_count > 0 THEN
        RAISE EXCEPTION 'Agent category migration blocked because % preset value(s) were not provisioned',
            v_missing_count;
    END IF;
END;
$$;

DO $$
DECLARE
    v_conflict_count BIGINT;
    v_sample JSONB;
BEGIN
    WITH new_assignments AS (
        SELECT projection.*
        FROM utm_agent_category_projection AS projection
        WHERE NOT EXISTS (
            SELECT 1
            FROM nexent.resource_tag_assignment AS assignment
            WHERE assignment.tenant_id = projection.tenant_id
              AND assignment.resource_type = projection.resource_type
              AND assignment.resource_id = projection.resource_id
              AND assignment.value_id = projection.value_id
              AND assignment.delete_flag = 'N'
        )
    ), projected AS (
        SELECT new_assignment.tenant_id,
               new_assignment.resource_id,
               count(*) AS new_count,
               (SELECT count(*)
                FROM nexent.resource_tag_assignment AS assignment
                WHERE assignment.tenant_id = new_assignment.tenant_id
                  AND assignment.resource_type = 'agent'
                  AND assignment.resource_id = new_assignment.resource_id
                  AND assignment.delete_flag = 'N') AS current_count
        FROM new_assignments AS new_assignment
        GROUP BY new_assignment.tenant_id, new_assignment.resource_id
    )
    SELECT count(*), jsonb_agg(to_jsonb(conflict))
    INTO v_conflict_count, v_sample
    FROM (
        SELECT tenant_id, resource_id, current_count, new_count,
               current_count + new_count AS projected_count
        FROM projected
        WHERE current_count + new_count > 100
        ORDER BY tenant_id, resource_id
        LIMIT 20
    ) AS conflict;

    IF v_conflict_count > 0 THEN
        RAISE EXCEPTION 'Agent category migration blocked by % assignment-capacity conflict(s): %',
            v_conflict_count, v_sample;
    END IF;
END;
$$;

INSERT INTO nexent.resource_tag_assignment (
    tenant_id, resource_type, resource_id, definition_id, value_id,
    status, created_by, updated_by, delete_flag
)
SELECT tenant_id, resource_type, resource_id, definition_id, value_id,
       'active', 'migration:v2.5.5', 'migration:v2.5.5', 'N'
FROM utm_agent_category_projection
ON CONFLICT (tenant_id, resource_type, resource_id, value_id) DO UPDATE
SET status = 'active',
    update_time = CURRENT_TIMESTAMP,
    updated_by = EXCLUDED.updated_by,
    delete_flag = 'N';

COMMIT;
