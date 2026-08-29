\set ON_ERROR_STOP on

BEGIN TRANSACTION READ ONLY;

-- Exact source, tenant, JSON-shape, and canonical-source conflicts.
WITH legacy_source AS (
    SELECT 'tool.labels'::TEXT AS source_name, tool.tool_id::TEXT AS source_row_id,
           tool.author AS tenant_id, 'tool'::TEXT AS resource_type, tool.tool_id::TEXT AS resource_id,
           tool.labels AS payload, 'json'::TEXT AS payload_kind, 1::BIGINT AS canonical_match_count
    FROM nexent.ag_tool_info_t AS tool
    WHERE tool.labels IS NOT NULL AND tool.labels <> '[]'::JSONB
    UNION ALL
    SELECT 'skill.skill_tags', skill.skill_id::TEXT, skill.tenant_id, 'skill', skill.skill_id::TEXT,
           skill.skill_tags::JSONB, 'json', 1
    FROM nexent.ag_skill_info_t AS skill
    WHERE skill.skill_tags IS NOT NULL AND skill.skill_tags::JSONB <> '[]'::JSONB
    UNION ALL
    SELECT 'agent_repository.tags', repository.agent_repository_id::TEXT,
           repository.publisher_tenant_id, 'agent', repository.agent_id::TEXT,
           to_jsonb(repository.tags), 'text_array',
           (SELECT count(*) FROM nexent.ag_tenant_agent_t AS agent
            WHERE agent.agent_id = repository.agent_id
              AND agent.tenant_id = repository.publisher_tenant_id)
    FROM nexent.ag_agent_repository_t AS repository
    WHERE COALESCE(cardinality(repository.tags), 0) > 0
    UNION ALL
    SELECT 'skill_repository.tags', repository.skill_repository_id::TEXT,
           repository.publisher_tenant_id, 'skill', repository.skill_id::TEXT,
           to_jsonb(repository.tags), 'text_array',
           (SELECT count(*) FROM nexent.ag_skill_info_t AS skill
            WHERE skill.skill_id = repository.skill_id
              AND skill.tenant_id = repository.publisher_tenant_id)
    FROM nexent.ag_skill_repository_t AS repository
    WHERE COALESCE(cardinality(repository.tags), 0) > 0
    UNION ALL
    SELECT 'mcp_record.tags', mcp.mcp_id::TEXT, mcp.tenant_id, 'mcp_service', mcp.mcp_id::TEXT,
           to_jsonb(mcp.tags), 'text_array', 1
    FROM nexent.mcp_record_t AS mcp
    WHERE COALESCE(cardinality(mcp.tags), 0) > 0
    UNION ALL
    SELECT 'mcp_community.tags', community.community_id::TEXT, community.tenant_id,
           'mcp_service', NULL::TEXT, to_jsonb(community.tags), 'text_array', 0
    FROM nexent.mcp_community_record_t AS community
    WHERE COALESCE(cardinality(community.tags), 0) > 0
    UNION ALL
    SELECT 'mcp_market.tags', market.market_id::TEXT, market.tenant_id,
           'mcp_service', market.source_mcp_id::TEXT, to_jsonb(market.tags), 'text_array',
           (SELECT count(*) FROM nexent.mcp_record_t AS mcp
            WHERE mcp.mcp_id = market.source_mcp_id AND mcp.tenant_id = market.tenant_id)
    FROM nexent.mcp_market_record_t AS market
    WHERE COALESCE(cardinality(market.tags), 0) > 0
), issues AS (
    SELECT source_name, source_row_id, tenant_id,
           resource_type || '/' || COALESCE(resource_id::TEXT, '?') AS resource,
           'null_or_empty_tenant'::TEXT AS reason, 1::BIGINT AS issue_count, payload AS sample
    FROM legacy_source WHERE tenant_id IS NULL OR btrim(tenant_id) = ''
    UNION ALL
    SELECT source.source_name, source.source_row_id, source.tenant_id,
           source.resource_type || '/' || COALESCE(source.resource_id::TEXT, '?'),
           'tenant_not_active_in_user_tenant_t', 1, source.payload
    FROM legacy_source AS source
    WHERE source.tenant_id IS NOT NULL AND btrim(source.tenant_id) <> ''
      AND NOT EXISTS (
          SELECT 1 FROM nexent.user_tenant_t AS user_tenant
          WHERE user_tenant.tenant_id = source.tenant_id
            AND COALESCE(user_tenant.delete_flag, 'N') <> 'Y'
      )
    UNION ALL
    SELECT source_name, source_row_id, tenant_id,
           resource_type || '/' || COALESCE(resource_id::TEXT, '?'),
           'json_is_not_an_array', 1, payload
    FROM legacy_source WHERE payload_kind = 'json' AND jsonb_typeof(payload) <> 'array'
    UNION ALL
    SELECT source.source_name, source.source_row_id, source.tenant_id,
           source.resource_type || '/' || COALESCE(source.resource_id::TEXT, '?'),
           'json_array_contains_non_string', count(*), jsonb_agg(element.value)
    FROM legacy_source AS source
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(source.payload) = 'array' THEN source.payload ELSE '[]'::JSONB END
    ) AS element(value)
    WHERE source.payload_kind = 'json' AND jsonb_typeof(element.value) <> 'string'
    GROUP BY source.source_name, source.source_row_id, source.tenant_id,
             source.resource_type, source.resource_id
    UNION ALL
    SELECT source_name, source_row_id, tenant_id,
           resource_type || '/' || COALESCE(resource_id::TEXT, '?'),
           CASE WHEN source_name = 'mcp_community.tags'
                THEN 'community_canonical_source_unprovable'
                ELSE 'canonical_source_missing_or_tenant_mismatch' END,
           canonical_match_count, payload
    FROM legacy_source WHERE canonical_match_count = 0
    UNION ALL
    SELECT source_name, source_row_id, tenant_id,
           resource_type || '/' || COALESCE(resource_id::TEXT, '?'),
           'canonical_source_ambiguous', canonical_match_count, payload
    FROM legacy_source WHERE canonical_match_count > 1
)
SELECT source_name AS source,
       source_row_id AS row,
       tenant_id AS tenant,
       resource,
       reason,
       issue_count AS count,
       sample
FROM issues
ORDER BY source, row, reason;

-- Normalization duplicates and source-only capacity conflicts. This repeats the
-- read-only projection deliberately so the file creates no temp object or view.
WITH legacy_source AS (
    SELECT 'tool.labels'::TEXT AS source_name, tool.tool_id::TEXT AS source_row_id,
           tool.author AS tenant_id, 'tool'::TEXT AS resource_type, tool.tool_id::TEXT AS resource_id,
           tool.labels AS payload
    FROM nexent.ag_tool_info_t AS tool WHERE tool.labels IS NOT NULL AND jsonb_typeof(tool.labels) = 'array'
    UNION ALL
    SELECT 'skill.skill_tags', skill.skill_id::TEXT, skill.tenant_id, 'skill', skill.skill_id::TEXT,
           skill.skill_tags::JSONB
    FROM nexent.ag_skill_info_t AS skill
    WHERE skill.skill_tags IS NOT NULL AND jsonb_typeof(skill.skill_tags::JSONB) = 'array'
    UNION ALL
    SELECT 'agent_repository.tags', repository.agent_repository_id::TEXT,
           repository.publisher_tenant_id, 'agent', repository.agent_id::TEXT, to_jsonb(repository.tags)
    FROM nexent.ag_agent_repository_t AS repository WHERE COALESCE(cardinality(repository.tags), 0) > 0
    UNION ALL
    SELECT 'skill_repository.tags', repository.skill_repository_id::TEXT,
           repository.publisher_tenant_id, 'skill', repository.skill_id::TEXT, to_jsonb(repository.tags)
    FROM nexent.ag_skill_repository_t AS repository WHERE COALESCE(cardinality(repository.tags), 0) > 0
    UNION ALL
    SELECT 'mcp_record.tags', mcp.mcp_id::TEXT, mcp.tenant_id, 'mcp_service', mcp.mcp_id::TEXT, to_jsonb(mcp.tags)
    FROM nexent.mcp_record_t AS mcp WHERE COALESCE(cardinality(mcp.tags), 0) > 0
    UNION ALL
    SELECT 'mcp_market.tags', market.market_id::TEXT, market.tenant_id,
           'mcp_service', market.source_mcp_id::TEXT, to_jsonb(market.tags)
    FROM nexent.mcp_market_record_t AS market
    WHERE COALESCE(cardinality(market.tags), 0) > 0
      AND market.source_mcp_id IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM nexent.mcp_record_t AS mcp
          WHERE mcp.mcp_id = market.source_mcp_id AND mcp.tenant_id = market.tenant_id
      )
), normalized AS (
    SELECT source.source_name, source.source_row_id, source.tenant_id,
           source.resource_type, source.resource_id,
           btrim(element.value #>> '{}') AS display_value,
           lower(btrim(element.value #>> '{}') COLLATE "C") AS normalized_value
    FROM legacy_source AS source
    CROSS JOIN LATERAL jsonb_array_elements(source.payload) AS element(value)
    WHERE jsonb_typeof(element.value) = 'string'
      AND NULLIF(btrim(element.value #>> '{}'), '') IS NOT NULL
), diagnostics AS (
    SELECT source_name AS source, source_row_id AS row, tenant_id AS tenant,
           resource_type || '/' || resource_id AS resource,
           'normalization_duplicate'::TEXT AS reason, count(*)::BIGINT AS count,
           jsonb_agg(DISTINCT display_value) AS sample
    FROM normalized
    GROUP BY source_name, source_row_id, tenant_id, resource_type, resource_id, normalized_value
    HAVING count(*) > 1
    UNION ALL
    SELECT 'Keywords', NULL, tenant_id, 'default_resource',
           'value_capacity_exceeded', count(DISTINCT normalized_value),
           jsonb_build_object('maximum', 1000)
    FROM normalized
    GROUP BY tenant_id
    HAVING count(DISTINCT normalized_value) > 1000
    UNION ALL
    SELECT 'resource_assignment', NULL, tenant_id, resource_type || '/' || resource_id,
           'assignment_capacity_exceeded', count(DISTINCT normalized_value),
           jsonb_build_object('maximum', 100)
    FROM normalized
    GROUP BY tenant_id, resource_type, resource_id
    HAVING count(DISTINCT normalized_value) > 100
    UNION ALL
    SELECT 'Keywords', NULL, tenant_id, 'default_resource',
           'projected_definition_count', 1, jsonb_build_object('maximum', 100)
    FROM normalized
    GROUP BY tenant_id
)
SELECT source, row, tenant, resource, reason, count, sample
FROM diagnostics
ORDER BY source, tenant, resource, reason;

-- Agent repository preset tags are also projected to Agent Category by the
-- forward compatibility migration. Estimate the combined Keywords + category
-- assignment count from active legacy rows before the structured schema exists.
WITH category_alias_groups (category_key, accepted_aliases) AS (
    VALUES
        ('marketing', ARRAY['marketing', '营销']::TEXT[]),
        ('copywriting', ARRAY['copywriting', '文案']::TEXT[]),
        ('content_creation', ARRAY['content_creation', 'content creation', '内容创作']::TEXT[]),
        ('code_review', ARRAY['code_review', 'code review', '代码审查']::TEXT[]),
        ('quality', ARRAY['quality', '质量']::TEXT[]),
        ('devops', ARRAY['devops']::TEXT[]),
        ('data', ARRAY['data', '数据']::TEXT[]),
        ('visualization', ARRAY['visualization', '可视化']::TEXT[]),
        ('bi', ARRAY['bi']::TEXT[]),
        ('customer_service', ARRAY['customer_service', 'customer support', 'customer service', '客服']::TEXT[]),
        ('ticket', ARRAY['ticket', 'ticketing', '工单']::TEXT[]),
        ('automation', ARRAY['automation', '自动化']::TEXT[]),
        ('meeting', ARRAY['meeting', '会议']::TEXT[]),
        ('minutes', ARRAY['minutes', '纪要']::TEXT[]),
        ('productivity', ARRAY['productivity', '效率']::TEXT[]),
        ('design', ARRAY['design', '设计']::TEXT[]),
        ('color_scheme', ARRAY['color_scheme', 'color scheme', '配色']::TEXT[]),
        ('inspiration', ARRAY['inspiration', '灵感']::TEXT[]),
        ('spreadsheet', ARRAY['spreadsheet', '表格']::TEXT[]),
        ('office', ARRAY['office', '办公']::TEXT[])
), category_aliases AS (
    SELECT category.category_key, alias.normalized_alias
    FROM category_alias_groups AS category
    CROSS JOIN LATERAL unnest(category.accepted_aliases) AS alias(normalized_alias)
), active_agent_tags AS (
    SELECT repository.publisher_tenant_id AS tenant_id,
           repository.agent_id::TEXT AS resource_id,
           lower(btrim(expanded.raw_value) COLLATE "C") AS normalized_value,
           aliases.category_key
    FROM nexent.ag_agent_repository_t AS repository
    CROSS JOIN LATERAL unnest(repository.tags) AS expanded(raw_value)
    LEFT JOIN category_aliases AS aliases
      ON aliases.normalized_alias = lower(btrim(expanded.raw_value) COLLATE "C")
    WHERE COALESCE(repository.delete_flag, 'N') <> 'Y'
      AND NULLIF(btrim(expanded.raw_value), '') IS NOT NULL
      AND (SELECT count(*)
           FROM nexent.ag_tenant_agent_t AS agent
           WHERE agent.agent_id = repository.agent_id
             AND agent.tenant_id = repository.publisher_tenant_id) = 1
), projected AS (
    SELECT tenant_id, resource_id,
           count(DISTINCT normalized_value) AS keyword_count,
           count(DISTINCT category_key) FILTER (WHERE category_key IS NOT NULL) AS category_count
    FROM active_agent_tags
    GROUP BY tenant_id, resource_id
)
SELECT 'agent_category_preflight' AS source,
       resource_id AS row,
       tenant_id AS tenant,
       'agent/' || resource_id AS resource,
       'agent_category_assignment_capacity_exceeded' AS reason,
       keyword_count + category_count AS count,
       jsonb_build_object(
           'maximum', 100,
           'keywords', keyword_count,
           'new_agent_categories', category_count,
           'exceeded', TRUE
       ) AS sample
FROM projected
WHERE keyword_count + category_count > 100
ORDER BY tenant, resource;

-- No document legacy source may be inferred silently. Every candidate column is
-- returned for explicit mapping; the sentinel row proves that the scan ran.
WITH candidates AS (
    SELECT table_schema, table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'nexent'
      AND (table_name ILIKE '%document%' OR table_name ILIKE '%knowledge%')
      AND (column_name ILIKE '%tag%' OR column_name ILIKE '%label%')
)
SELECT 'document_source_scan' AS source,
       table_name AS row,
       NULL::TEXT AS tenant,
       table_schema || '.' || table_name AS resource,
       'document_legacy_column_requires_mapping' AS reason,
       1::BIGINT AS count,
       jsonb_build_object('column', column_name, 'data_type', data_type) AS sample
FROM candidates
UNION ALL
SELECT 'document_source_scan', NULL, NULL, 'knowledge_document',
       'no_document_legacy_column_found', 0, '[]'::JSONB
WHERE NOT EXISTS (SELECT 1 FROM candidates)
ORDER BY row NULLS LAST;

-- Run after the migration to prove every mappable normalized legacy value has an
-- assignment and that no migration-created assignment lacks a legacy source.
SELECT (
    to_regclass('nexent.tag_bucket') IS NOT NULL
    AND to_regclass('nexent.tag_definition') IS NOT NULL
    AND to_regclass('nexent.tag_value') IS NOT NULL
    AND to_regclass('nexent.resource_tag_assignment') IS NOT NULL
) AS utm_schema_present
\gset

\if :utm_schema_present

-- Structured counts run only when the unified-tag schema exists. Disabled but
-- undeleted rows remain in every limit count.
WITH legacy_value_tenants AS (
    SELECT tool.author AS tenant_id
    FROM nexent.ag_tool_info_t AS tool
    WHERE tool.author IS NOT NULL
      AND btrim(tool.author) <> ''
      AND EXISTS (
          SELECT 1
          FROM jsonb_array_elements(
              CASE WHEN jsonb_typeof(tool.labels) = 'array' THEN tool.labels ELSE '[]'::JSONB END
          ) AS element(value)
          WHERE jsonb_typeof(element.value) = 'string'
            AND NULLIF(btrim(element.value #>> '{}'), '') IS NOT NULL
      )
    UNION
    SELECT skill.tenant_id
    FROM nexent.ag_skill_info_t AS skill
    WHERE skill.tenant_id IS NOT NULL
      AND btrim(skill.tenant_id) <> ''
      AND EXISTS (
          SELECT 1
          FROM jsonb_array_elements(
              CASE WHEN jsonb_typeof(skill.skill_tags::JSONB) = 'array'
                   THEN skill.skill_tags::JSONB ELSE '[]'::JSONB END
          ) AS element(value)
          WHERE jsonb_typeof(element.value) = 'string'
            AND NULLIF(btrim(element.value #>> '{}'), '') IS NOT NULL
      )
    UNION
    SELECT repository.publisher_tenant_id
    FROM nexent.ag_agent_repository_t AS repository
    WHERE EXISTS (SELECT 1 FROM unnest(repository.tags) AS tag WHERE NULLIF(btrim(tag), '') IS NOT NULL)
      AND EXISTS (
          SELECT 1 FROM nexent.ag_tenant_agent_t AS agent
          WHERE agent.agent_id = repository.agent_id
            AND agent.tenant_id = repository.publisher_tenant_id
      )
    UNION
    SELECT repository.publisher_tenant_id
    FROM nexent.ag_skill_repository_t AS repository
    WHERE EXISTS (SELECT 1 FROM unnest(repository.tags) AS tag WHERE NULLIF(btrim(tag), '') IS NOT NULL)
      AND EXISTS (
          SELECT 1 FROM nexent.ag_skill_info_t AS skill
          WHERE skill.skill_id = repository.skill_id
            AND skill.tenant_id = repository.publisher_tenant_id
      )
    UNION
    SELECT mcp.tenant_id
    FROM nexent.mcp_record_t AS mcp
    WHERE mcp.tenant_id IS NOT NULL
      AND btrim(mcp.tenant_id) <> ''
      AND EXISTS (SELECT 1 FROM unnest(mcp.tags) AS tag WHERE NULLIF(btrim(tag), '') IS NOT NULL)
    UNION
    SELECT market.tenant_id
    FROM nexent.mcp_market_record_t AS market
    WHERE EXISTS (SELECT 1 FROM unnest(market.tags) AS tag WHERE NULLIF(btrim(tag), '') IS NOT NULL)
      AND EXISTS (
          SELECT 1 FROM nexent.mcp_record_t AS mcp
          WHERE mcp.mcp_id = market.source_mcp_id
            AND mcp.tenant_id = market.tenant_id
      )
), projected_definition_counts AS (
    SELECT bucket.tenant_id,
           bucket.bucket_key AS resource,
           (SELECT count(*)
            FROM nexent.tag_definition AS definition
            WHERE definition.tenant_id = bucket.tenant_id
              AND definition.bucket_id = bucket.bucket_id
              AND definition.delete_flag = 'N')
           + CASE WHEN EXISTS (
               SELECT 1
               FROM nexent.tag_definition AS definition
               WHERE definition.tenant_id = bucket.tenant_id
                 AND definition.bucket_id = bucket.bucket_id
                 AND definition.definition_key = 'keywords'
                 AND definition.delete_flag = 'N'
           ) THEN 0 ELSE 1 END AS item_count
    FROM legacy_value_tenants AS legacy
    JOIN nexent.tag_bucket AS bucket
      ON bucket.tenant_id = legacy.tenant_id
     AND bucket.bucket_key = 'default_resource'
     AND bucket.delete_flag = 'N'
), structured_counts AS (
    SELECT 'structured_definition_count'::TEXT AS reason,
           definition.tenant_id,
           bucket.bucket_key AS resource,
           count(*)::BIGINT AS item_count,
           100::BIGINT AS maximum
    FROM nexent.tag_definition AS definition
    JOIN nexent.tag_bucket AS bucket
      ON bucket.tenant_id = definition.tenant_id
     AND bucket.bucket_id = definition.bucket_id
    WHERE definition.delete_flag = 'N'
    GROUP BY definition.tenant_id, bucket.bucket_key
    UNION ALL
    SELECT 'structured_value_count', value.tenant_id,
           'tag_definition/' || value.definition_id,
           count(*), 1000
    FROM nexent.tag_value AS value
    WHERE value.delete_flag = 'N'
    GROUP BY value.tenant_id, value.definition_id
    UNION ALL
    SELECT 'structured_assignment_count', assignment.tenant_id,
           assignment.resource_type || '/' || assignment.resource_id,
           count(*), 100
    FROM nexent.resource_tag_assignment AS assignment
    WHERE assignment.delete_flag = 'N'
    GROUP BY assignment.tenant_id, assignment.resource_type, assignment.resource_id
    UNION ALL
    SELECT CASE WHEN projected.item_count > 100
                THEN 'projected_definition_capacity_exceeded'
                ELSE 'projected_definition_count' END,
           projected.tenant_id,
           projected.resource,
           projected.item_count,
           100
    FROM projected_definition_counts AS projected
)
SELECT 'structured_capacity' AS source,
       NULL::TEXT AS row,
       tenant_id AS tenant,
       resource,
       reason,
       item_count AS count,
       jsonb_build_object('maximum', maximum, 'exceeded', item_count > maximum) AS sample
FROM structured_counts
ORDER BY tenant, resource, reason;

-- When the structured schema already exists, include every current assignment
-- and add only recognized category values that are not already active.
WITH category_alias_groups (category_key, accepted_aliases) AS (
    VALUES
        ('marketing', ARRAY['marketing', '营销']::TEXT[]),
        ('copywriting', ARRAY['copywriting', '文案']::TEXT[]),
        ('content_creation', ARRAY['content_creation', 'content creation', '内容创作']::TEXT[]),
        ('code_review', ARRAY['code_review', 'code review', '代码审查']::TEXT[]),
        ('quality', ARRAY['quality', '质量']::TEXT[]),
        ('devops', ARRAY['devops']::TEXT[]),
        ('data', ARRAY['data', '数据']::TEXT[]),
        ('visualization', ARRAY['visualization', '可视化']::TEXT[]),
        ('bi', ARRAY['bi']::TEXT[]),
        ('customer_service', ARRAY['customer_service', 'customer support', 'customer service', '客服']::TEXT[]),
        ('ticket', ARRAY['ticket', 'ticketing', '工单']::TEXT[]),
        ('automation', ARRAY['automation', '自动化']::TEXT[]),
        ('meeting', ARRAY['meeting', '会议']::TEXT[]),
        ('minutes', ARRAY['minutes', '纪要']::TEXT[]),
        ('productivity', ARRAY['productivity', '效率']::TEXT[]),
        ('design', ARRAY['design', '设计']::TEXT[]),
        ('color_scheme', ARRAY['color_scheme', 'color scheme', '配色']::TEXT[]),
        ('inspiration', ARRAY['inspiration', '灵感']::TEXT[]),
        ('spreadsheet', ARRAY['spreadsheet', '表格']::TEXT[]),
        ('office', ARRAY['office', '办公']::TEXT[])
), category_aliases AS (
    SELECT category.category_key, alias.normalized_alias
    FROM category_alias_groups AS category
    CROSS JOIN LATERAL unnest(category.accepted_aliases) AS alias(normalized_alias)
), projected_categories AS (
    SELECT DISTINCT repository.publisher_tenant_id AS tenant_id,
           repository.agent_id::TEXT AS resource_id,
           aliases.category_key
    FROM nexent.ag_agent_repository_t AS repository
    CROSS JOIN LATERAL unnest(repository.tags) AS expanded(raw_value)
    JOIN category_aliases AS aliases
      ON aliases.normalized_alias = lower(btrim(expanded.raw_value) COLLATE "C")
    WHERE COALESCE(repository.delete_flag, 'N') <> 'Y'
      AND (SELECT count(*)
           FROM nexent.ag_tenant_agent_t AS agent
           WHERE agent.agent_id = repository.agent_id
             AND agent.tenant_id = repository.publisher_tenant_id) = 1
), projected_counts AS (
    SELECT projected.tenant_id,
           projected.resource_id,
           (SELECT count(*)
            FROM nexent.resource_tag_assignment AS assignment
            WHERE assignment.tenant_id = projected.tenant_id
              AND assignment.resource_type = 'agent'
              AND assignment.resource_id = projected.resource_id
              AND assignment.delete_flag = 'N') AS current_count,
           count(*) FILTER (WHERE NOT EXISTS (
               SELECT 1
               FROM nexent.resource_tag_assignment AS assignment
               JOIN nexent.tag_definition AS definition
                 ON definition.tenant_id = assignment.tenant_id
                AND definition.definition_id = assignment.definition_id
                AND definition.definition_key = 'agent_category'
                AND definition.delete_flag = 'N'
               JOIN nexent.tag_value AS value
                 ON value.tenant_id = assignment.tenant_id
                AND value.definition_id = assignment.definition_id
                AND value.value_id = assignment.value_id
                AND value.normalized_value = projected.category_key
                AND value.delete_flag = 'N'
               WHERE assignment.tenant_id = projected.tenant_id
                 AND assignment.resource_type = 'agent'
                 AND assignment.resource_id = projected.resource_id
                 AND assignment.delete_flag = 'N'
           )) AS new_category_count
    FROM projected_categories AS projected
    GROUP BY projected.tenant_id, projected.resource_id
)
SELECT 'agent_category_preflight' AS source,
       resource_id AS row,
       tenant_id AS tenant,
       'agent/' || resource_id AS resource,
       'agent_category_assignment_capacity_exceeded' AS reason,
       current_count + new_category_count AS count,
       jsonb_build_object(
           'maximum', 100,
           'current', current_count,
           'new_agent_categories', new_category_count,
           'exceeded', TRUE
       ) AS sample
FROM projected_counts
WHERE current_count + new_category_count > 100
ORDER BY tenant, resource;

WITH legacy_normalized AS (
    SELECT tool.author AS tenant_id, 'tool'::TEXT AS resource_type, tool.tool_id::TEXT AS resource_id,
           lower(btrim(element.value #>> '{}') COLLATE "C") AS normalized_value
    FROM nexent.ag_tool_info_t AS tool
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(tool.labels) = 'array' THEN tool.labels ELSE '[]'::JSONB END
    ) AS element(value)
    WHERE jsonb_typeof(element.value) = 'string' AND NULLIF(btrim(element.value #>> '{}'), '') IS NOT NULL
    UNION
    SELECT skill.tenant_id, 'skill', skill.skill_id::TEXT,
           lower(btrim(element.value #>> '{}') COLLATE "C")
    FROM nexent.ag_skill_info_t AS skill
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(skill.skill_tags::JSONB) = 'array' THEN skill.skill_tags::JSONB ELSE '[]'::JSONB END
    ) AS element(value)
    WHERE jsonb_typeof(element.value) = 'string' AND NULLIF(btrim(element.value #>> '{}'), '') IS NOT NULL
    UNION
    SELECT repository.publisher_tenant_id, 'agent', repository.agent_id::TEXT,
           lower(btrim(tag) COLLATE "C")
    FROM nexent.ag_agent_repository_t AS repository CROSS JOIN LATERAL unnest(repository.tags) AS tag
    WHERE NULLIF(btrim(tag), '') IS NOT NULL
      AND EXISTS (SELECT 1 FROM nexent.ag_tenant_agent_t AS agent
                  WHERE agent.agent_id = repository.agent_id AND agent.tenant_id = repository.publisher_tenant_id)
    UNION
    SELECT repository.publisher_tenant_id, 'skill', repository.skill_id::TEXT,
           lower(btrim(tag) COLLATE "C")
    FROM nexent.ag_skill_repository_t AS repository CROSS JOIN LATERAL unnest(repository.tags) AS tag
    WHERE NULLIF(btrim(tag), '') IS NOT NULL
      AND EXISTS (SELECT 1 FROM nexent.ag_skill_info_t AS skill
                  WHERE skill.skill_id = repository.skill_id AND skill.tenant_id = repository.publisher_tenant_id)
    UNION
    SELECT mcp.tenant_id, 'mcp_service', mcp.mcp_id::TEXT, lower(btrim(tag) COLLATE "C")
    FROM nexent.mcp_record_t AS mcp CROSS JOIN LATERAL unnest(mcp.tags) AS tag
    WHERE NULLIF(btrim(tag), '') IS NOT NULL
    UNION
    SELECT market.tenant_id, 'mcp_service', market.source_mcp_id::TEXT, lower(btrim(tag) COLLATE "C")
    FROM nexent.mcp_market_record_t AS market CROSS JOIN LATERAL unnest(market.tags) AS tag
    WHERE NULLIF(btrim(tag), '') IS NOT NULL
      AND EXISTS (SELECT 1 FROM nexent.mcp_record_t AS mcp
                  WHERE mcp.mcp_id = market.source_mcp_id AND mcp.tenant_id = market.tenant_id)
), actual AS (
    SELECT assignment.tenant_id, assignment.resource_type, assignment.resource_id, value.normalized_value
    FROM nexent.resource_tag_assignment AS assignment
    JOIN nexent.tag_definition AS definition
      ON definition.tenant_id = assignment.tenant_id
     AND definition.definition_id = assignment.definition_id
     AND definition.definition_key = 'keywords'
    JOIN nexent.tag_value AS value
      ON value.tenant_id = assignment.tenant_id
     AND value.value_id = assignment.value_id
     AND value.definition_id = assignment.definition_id
    WHERE assignment.created_by = 'migration:v2.5.0'
), parity AS (
    SELECT 'legacy_missing_assignment'::TEXT AS reason, legacy.*
    FROM legacy_normalized AS legacy
    LEFT JOIN actual USING (tenant_id, resource_type, resource_id, normalized_value)
    WHERE actual.tenant_id IS NULL
    UNION ALL
    SELECT 'assignment_missing_legacy_source', actual.*
    FROM actual
    LEFT JOIN legacy_normalized AS legacy USING (tenant_id, resource_type, resource_id, normalized_value)
    WHERE legacy.tenant_id IS NULL
)
SELECT 'post_backfill_parity' AS source,
       resource_id AS row,
       tenant_id AS tenant,
       resource_type || '/' || resource_id AS resource,
       reason,
       count(*)::BIGINT AS count,
       jsonb_agg(normalized_value ORDER BY normalized_value) AS sample
FROM parity
GROUP BY tenant_id, resource_type, resource_id, reason
ORDER BY tenant, resource, reason;

\else

SELECT 'structured_capacity' AS source,
       NULL::TEXT AS row,
       NULL::TEXT AS tenant,
       'unified_tag_schema' AS resource,
       'structured_schema_not_installed' AS reason,
       0::BIGINT AS count,
       jsonb_build_object('parity_ran', FALSE) AS sample;

\endif

COMMIT;
