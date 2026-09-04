BEGIN;

-- Unified tag management migration for Nexent v2.5.2.
-- Consolidates all SQL introduced by PR #3809 in its original execution order.

-- -----------------------------------------------------------------------------
-- Consolidated from v2.5.0_0817_unified_tag_management.sql
-- -----------------------------------------------------------------------------

SET LOCAL search_path TO nexent, public;

CREATE TABLE IF NOT EXISTS nexent.tag_bucket (
    bucket_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL CHECK (btrim(tenant_id) <> ''),
    bucket_key VARCHAR(100) NOT NULL,
    bucket_name VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N', 'Y')),
    CONSTRAINT uq_tag_bucket_tenant_id UNIQUE (tenant_id, bucket_id),
    CONSTRAINT uq_tag_bucket_tenant_key UNIQUE (tenant_id, bucket_key)
);

CREATE TABLE IF NOT EXISTS nexent.tag_bucket_resource_type (
    bucket_resource_type_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL CHECK (btrim(tenant_id) <> ''),
    bucket_id BIGINT NOT NULL,
    resource_type VARCHAR(50) NOT NULL CHECK (
        resource_type IN ('agent', 'skill', 'tool', 'mcp_service', 'knowledge_base', 'knowledge_document')
    ),
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N', 'Y')),
    CONSTRAINT uq_tag_bucket_resource_type_tenant_id UNIQUE (tenant_id, bucket_resource_type_id),
    CONSTRAINT uq_tag_bucket_resource_type UNIQUE (tenant_id, bucket_id, resource_type),
    CONSTRAINT fk_tag_bucket_resource_type_bucket
        FOREIGN KEY (tenant_id, bucket_id)
        REFERENCES nexent.tag_bucket (tenant_id, bucket_id)
);

CREATE TABLE IF NOT EXISTS nexent.tag_definition (
    definition_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL CHECK (btrim(tenant_id) <> ''),
    bucket_id BIGINT NOT NULL,
    definition_key VARCHAR(100) NOT NULL,
    definition_name VARCHAR(255) NOT NULL,
    normalized_name TEXT COLLATE "C" GENERATED ALWAYS AS (
        lower(btrim(definition_name) COLLATE "C")
    ) STORED,
    selection_mode VARCHAR(20) NOT NULL CHECK (selection_mode IN ('single_select', 'multi_select')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N', 'Y')),
    CONSTRAINT uq_tag_definition_tenant_id UNIQUE (tenant_id, definition_id),
    CONSTRAINT fk_tag_definition_bucket
        FOREIGN KEY (tenant_id, bucket_id)
        REFERENCES nexent.tag_bucket (tenant_id, bucket_id)
);

CREATE TABLE IF NOT EXISTS nexent.tag_value (
    value_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL CHECK (btrim(tenant_id) <> ''),
    definition_id BIGINT NOT NULL,
    normalized_value TEXT NOT NULL CHECK (btrim(normalized_value) <> ''),
    display_value TEXT NOT NULL CHECK (btrim(display_value) <> ''),
    sort_order INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N', 'Y')),
    CONSTRAINT uq_tag_value_tenant_id_definition UNIQUE (tenant_id, value_id, definition_id),
    CONSTRAINT fk_tag_value_definition
        FOREIGN KEY (tenant_id, definition_id)
        REFERENCES nexent.tag_definition (tenant_id, definition_id)
);

CREATE TABLE IF NOT EXISTS nexent.resource_tag_assignment (
    assignment_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL CHECK (btrim(tenant_id) <> ''),
    resource_type VARCHAR(50) NOT NULL CHECK (
        resource_type IN ('agent', 'skill', 'tool', 'mcp_service', 'knowledge_base', 'knowledge_document')
    ),
    resource_id TEXT NOT NULL CHECK (btrim(resource_id) <> ''),
    definition_id BIGINT NOT NULL,
    value_id BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N', 'Y')),
    CONSTRAINT uq_resource_tag_assignment_tenant_id UNIQUE (tenant_id, assignment_id),
    CONSTRAINT uq_resource_tag_assignment_resource_value
        UNIQUE (tenant_id, resource_type, resource_id, value_id),
    CONSTRAINT fk_resource_tag_assignment_definition
        FOREIGN KEY (tenant_id, definition_id)
        REFERENCES nexent.tag_definition (tenant_id, definition_id),
    CONSTRAINT fk_resource_tag_assignment_value_definition
        FOREIGN KEY (tenant_id, value_id, definition_id)
        REFERENCES nexent.tag_value (tenant_id, value_id, definition_id)
);

CREATE INDEX IF NOT EXISTS idx_tag_definition_bucket
    ON nexent.tag_definition (tenant_id, bucket_id, delete_flag);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tag_definition_active_key
    ON nexent.tag_definition (tenant_id, bucket_id, definition_key)
    WHERE delete_flag = 'N';
CREATE UNIQUE INDEX IF NOT EXISTS uq_tag_definition_active_normalized_name
    ON nexent.tag_definition (tenant_id, bucket_id, normalized_name)
    WHERE delete_flag = 'N';
CREATE INDEX IF NOT EXISTS idx_tag_value_definition
    ON nexent.tag_value (tenant_id, definition_id, delete_flag);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tag_value_active_normalized_value
    ON nexent.tag_value (tenant_id, definition_id, normalized_value)
    WHERE delete_flag = 'N';
CREATE INDEX IF NOT EXISTS idx_resource_tag_assignment_resource
    ON nexent.resource_tag_assignment (tenant_id, resource_type, resource_id, delete_flag);
CREATE INDEX IF NOT EXISTS idx_resource_tag_assignment_definition
    ON nexent.resource_tag_assignment (tenant_id, definition_id, delete_flag);

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

END;
$$;

CREATE OR REPLACE FUNCTION nexent.provision_unified_tag_management_after_user_tenant_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(NEW.delete_flag, 'N') <> 'Y' THEN
        PERFORM nexent.provision_unified_tag_management(NEW.tenant_id, COALESCE(NEW.created_by, 'system'));
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION nexent.enforce_tag_definition_limit()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('tag-definition:' || NEW.tenant_id || ':' || NEW.bucket_id, 0));
    IF NEW.delete_flag <> 'Y' THEN
        SELECT count(*) INTO v_count
        FROM nexent.tag_definition
        WHERE tenant_id = NEW.tenant_id
          AND bucket_id = NEW.bucket_id
          AND delete_flag <> 'Y'
          AND definition_id <> COALESCE(NEW.definition_id, -1);
        IF v_count >= 100 THEN
            RAISE EXCEPTION 'Tag definition limit exceeded for tenant %, bucket % (maximum 100)',
                NEW.tenant_id, NEW.bucket_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION nexent.enforce_tag_value_limit()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('tag-value:' || NEW.tenant_id || ':' || NEW.definition_id, 0));
    IF NEW.delete_flag <> 'Y' THEN
        SELECT count(*) INTO v_count
        FROM nexent.tag_value
        WHERE tenant_id = NEW.tenant_id
          AND definition_id = NEW.definition_id
          AND delete_flag <> 'Y'
          AND value_id <> COALESCE(NEW.value_id, -1);
        IF v_count >= 1000 THEN
            RAISE EXCEPTION 'Tag value limit exceeded for tenant %, definition % (maximum 1000)',
                NEW.tenant_id, NEW.definition_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION nexent.enforce_resource_tag_assignment_rules()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER;
    v_selection_mode VARCHAR(20);
    v_bucket_id BIGINT;
    v_validate_active_reference BOOLEAN;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended('tag-assignment:' || NEW.tenant_id || ':' || NEW.resource_type || ':' || NEW.resource_id, 0)
    );

    IF TG_OP = 'INSERT' THEN
        v_validate_active_reference := TRUE;
    ELSIF NEW.delete_flag <> 'Y' THEN
        v_validate_active_reference := OLD.delete_flag = 'Y'
                OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
                OR OLD.resource_type IS DISTINCT FROM NEW.resource_type
                OR OLD.resource_id IS DISTINCT FROM NEW.resource_id
                OR OLD.definition_id IS DISTINCT FROM NEW.definition_id
                OR OLD.value_id IS DISTINCT FROM NEW.value_id;
    ELSE
        v_validate_active_reference := FALSE;
    END IF;

    IF TG_OP = 'INSERT' OR NEW.delete_flag <> 'Y' THEN
        SELECT definition.selection_mode, definition.bucket_id
        INTO v_selection_mode, v_bucket_id
        FROM nexent.tag_definition AS definition
        JOIN nexent.tag_value AS value
          ON value.tenant_id = definition.tenant_id
         AND value.definition_id = definition.definition_id
         AND value.value_id = NEW.value_id
        WHERE definition.tenant_id = NEW.tenant_id
          AND definition.definition_id = NEW.definition_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Assignment references a mismatched definition/value for tenant %', NEW.tenant_id;
        END IF;

        IF v_validate_active_reference THEN
            IF NOT EXISTS (
                SELECT 1
                FROM nexent.tag_definition AS definition
                JOIN nexent.tag_value AS value
                  ON value.tenant_id = definition.tenant_id
                 AND value.definition_id = definition.definition_id
                 AND value.value_id = NEW.value_id
                 AND value.status = 'active'
                 AND value.delete_flag = 'N'
                WHERE definition.tenant_id = NEW.tenant_id
                  AND definition.definition_id = NEW.definition_id
                  AND definition.status = 'active'
                  AND definition.delete_flag = 'N'
            ) THEN
                RAISE EXCEPTION 'New assignment requires an active definition/value for tenant %', NEW.tenant_id;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM nexent.tag_bucket_resource_type
                WHERE tenant_id = NEW.tenant_id
                  AND bucket_id = v_bucket_id
                  AND resource_type = NEW.resource_type
                  AND status = 'active'
                  AND delete_flag = 'N'
            ) THEN
                RAISE EXCEPTION 'Resource type % requires an active binding to bucket % for tenant %',
                    NEW.resource_type, v_bucket_id, NEW.tenant_id;
            END IF;
        END IF;
    END IF;

    IF NEW.delete_flag <> 'Y' THEN
        SELECT count(*) INTO v_count
        FROM nexent.resource_tag_assignment
        WHERE tenant_id = NEW.tenant_id
          AND resource_type = NEW.resource_type
          AND resource_id = NEW.resource_id
          AND delete_flag <> 'Y'
          AND assignment_id <> COALESCE(NEW.assignment_id, -1);
        IF v_count >= 100 THEN
            RAISE EXCEPTION 'Tag assignment limit exceeded for tenant %, resource %/% (maximum 100)',
                NEW.tenant_id, NEW.resource_type, NEW.resource_id;
        END IF;

        IF v_selection_mode = 'single_select' AND EXISTS (
            SELECT 1
            FROM nexent.resource_tag_assignment
            WHERE tenant_id = NEW.tenant_id
              AND resource_type = NEW.resource_type
              AND resource_id = NEW.resource_id
              AND definition_id = NEW.definition_id
              AND delete_flag <> 'Y'
              AND assignment_id <> COALESCE(NEW.assignment_id, -1)
        ) THEN
            RAISE EXCEPTION 'single_select definition % already has a value for tenant %, resource %/%',
                NEW.definition_id, NEW.tenant_id, NEW.resource_type, NEW.resource_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS enforce_tag_definition_limit_trigger ON nexent.tag_definition;
DROP TRIGGER IF EXISTS enforce_tag_value_limit_trigger ON nexent.tag_value;
DROP TRIGGER IF EXISTS enforce_resource_tag_assignment_rules_trigger ON nexent.resource_tag_assignment;
DROP TRIGGER IF EXISTS provision_unified_tag_management_trigger ON nexent.user_tenant_t;

CREATE TEMP TABLE utm_legacy_source (
    source_name TEXT NOT NULL,
    source_row_id TEXT NOT NULL,
    tenant_id VARCHAR(100),
    resource_type VARCHAR(50) NOT NULL,
    resource_id TEXT,
    payload JSONB NOT NULL,
    payload_kind VARCHAR(10) NOT NULL,
    canonical_match_count INTEGER NOT NULL,
    legacy_delete_flag VARCHAR(1) NOT NULL
) ON COMMIT DROP;

INSERT INTO utm_legacy_source
SELECT 'tool.labels', tool.tool_id::TEXT, tool.author, 'tool', tool.tool_id::TEXT,
       tool.labels, 'json', 1, COALESCE(tool.delete_flag, 'N')
FROM nexent.ag_tool_info_t AS tool
WHERE tool.labels IS NOT NULL AND tool.labels <> '[]'::JSONB;

INSERT INTO utm_legacy_source
SELECT 'skill.skill_tags', skill.skill_id::TEXT, skill.tenant_id, 'skill', skill.skill_id::TEXT,
       skill.skill_tags::JSONB, 'json', 1, COALESCE(skill.delete_flag, 'N')
FROM nexent.ag_skill_info_t AS skill
WHERE skill.skill_tags IS NOT NULL AND skill.skill_tags::JSONB <> '[]'::JSONB;

INSERT INTO utm_legacy_source
SELECT 'agent_repository.tags', repository.agent_repository_id::TEXT,
       repository.publisher_tenant_id, 'agent', repository.agent_id::TEXT,
       to_jsonb(repository.tags), 'text_array',
       (SELECT count(*) FROM nexent.ag_tenant_agent_t AS agent
        WHERE agent.agent_id = repository.agent_id
          AND agent.tenant_id = repository.publisher_tenant_id),
       COALESCE(repository.delete_flag, 'N')
FROM nexent.ag_agent_repository_t AS repository
WHERE COALESCE(cardinality(repository.tags), 0) > 0;

INSERT INTO utm_legacy_source
SELECT 'skill_repository.tags', repository.skill_repository_id::TEXT,
       repository.publisher_tenant_id, 'skill', repository.skill_id::TEXT,
       to_jsonb(repository.tags), 'text_array',
       (SELECT count(*) FROM nexent.ag_skill_info_t AS skill
        WHERE skill.skill_id = repository.skill_id
          AND skill.tenant_id = repository.publisher_tenant_id),
       COALESCE(repository.delete_flag, 'N')
FROM nexent.ag_skill_repository_t AS repository
WHERE COALESCE(cardinality(repository.tags), 0) > 0;

INSERT INTO utm_legacy_source
SELECT 'mcp_record.tags', mcp.mcp_id::TEXT, mcp.tenant_id, 'mcp_service', mcp.mcp_id::TEXT,
       to_jsonb(mcp.tags), 'text_array', 1, COALESCE(mcp.delete_flag, 'N')
FROM nexent.mcp_record_t AS mcp
WHERE COALESCE(cardinality(mcp.tags), 0) > 0;

INSERT INTO utm_legacy_source
SELECT 'mcp_community.tags', community.community_id::TEXT, community.tenant_id,
       'mcp_service', NULL::TEXT, to_jsonb(community.tags), 'text_array', 0,
       COALESCE(community.delete_flag, 'N')
FROM nexent.mcp_community_record_t AS community
WHERE COALESCE(cardinality(community.tags), 0) > 0;

INSERT INTO utm_legacy_source
SELECT 'mcp_market.tags', market.market_id::TEXT, market.tenant_id,
       'mcp_service', market.source_mcp_id::TEXT, to_jsonb(market.tags), 'text_array',
       (SELECT count(*) FROM nexent.mcp_record_t AS mcp
        WHERE mcp.mcp_id = market.source_mcp_id
          AND mcp.tenant_id = market.tenant_id),
       COALESCE(market.delete_flag, 'N')
FROM nexent.mcp_market_record_t AS market
WHERE COALESCE(cardinality(market.tags), 0) > 0;

CREATE TEMP TABLE utm_conflict (
    source_name TEXT NOT NULL,
    source_row_id TEXT,
    tenant_id VARCHAR(100),
    resource TEXT,
    reason TEXT NOT NULL,
    conflict_count BIGINT NOT NULL DEFAULT 1,
    sample JSONB
) ON COMMIT DROP;

INSERT INTO utm_conflict (source_name, source_row_id, tenant_id, resource, reason, sample)
SELECT source_name, source_row_id, tenant_id, resource_type || '/' || COALESCE(resource_id, '?'),
       'null_or_empty_tenant', to_jsonb(source)
FROM utm_legacy_source AS source
WHERE tenant_id IS NULL OR btrim(tenant_id) = '';

INSERT INTO utm_conflict (source_name, source_row_id, tenant_id, resource, reason, sample)
SELECT source_name, source_row_id, tenant_id, resource_type || '/' || COALESCE(resource_id, '?'),
       'json_is_not_an_array', payload
FROM utm_legacy_source
WHERE payload_kind = 'json' AND jsonb_typeof(payload) NOT IN ('array', 'null');

INSERT INTO utm_conflict (source_name, source_row_id, tenant_id, resource, reason, conflict_count, sample)
SELECT source.source_name, source.source_row_id, source.tenant_id,
       source.resource_type || '/' || COALESCE(source.resource_id, '?'),
       'json_array_contains_non_string', count(*), jsonb_agg(element.value)
FROM utm_legacy_source AS source
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(source.payload) = 'array' THEN source.payload ELSE '[]'::JSONB END
) AS element(value)
WHERE source.payload_kind = 'json' AND jsonb_typeof(element.value) <> 'string'
GROUP BY source.source_name, source.source_row_id, source.tenant_id,
         source.resource_type, source.resource_id;

INSERT INTO utm_conflict (source_name, source_row_id, tenant_id, resource, reason, conflict_count, sample)
SELECT source_name, source_row_id, tenant_id,
       resource_type || '/' || COALESCE(resource_id, '?'),
       CASE WHEN source_name = 'mcp_community.tags'
            THEN 'community_canonical_source_unprovable'
            ELSE 'canonical_source_missing_or_tenant_mismatch' END,
       canonical_match_count, to_jsonb(source)
FROM utm_legacy_source AS source
WHERE canonical_match_count = 0;

INSERT INTO utm_conflict (source_name, source_row_id, tenant_id, resource, reason, conflict_count, sample)
SELECT source_name, source_row_id, tenant_id,
       resource_type || '/' || COALESCE(resource_id, '?'),
       'canonical_source_ambiguous', canonical_match_count, to_jsonb(source)
FROM utm_legacy_source AS source
WHERE canonical_match_count > 1;

CREATE TEMP TABLE utm_normalized_source ON COMMIT DROP AS
SELECT source.source_name,
       source.source_row_id,
       source.tenant_id,
       source.resource_type,
       source.resource_id,
       lower(btrim(element.value #>> '{}') COLLATE "C") AS normalized_value,
       btrim(element.value #>> '{}') AS display_value,
       source.legacy_delete_flag
FROM utm_legacy_source AS source
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(source.payload) = 'array' THEN source.payload ELSE '[]'::JSONB END
) AS element(value)
WHERE jsonb_typeof(element.value) = 'string'
  AND NULLIF(btrim(element.value #>> '{}'), '') IS NOT NULL
  AND source.tenant_id IS NOT NULL
  AND btrim(source.tenant_id) <> ''
  AND source.resource_id IS NOT NULL
  AND source.canonical_match_count = 1;

SELECT nexent.provision_unified_tag_management(tenant_id, 'migration:v2.5.0')
FROM (
    SELECT DISTINCT tenant_id
    FROM nexent.user_tenant_t
    WHERE tenant_id IS NOT NULL
      AND btrim(tenant_id) <> ''
      AND COALESCE(delete_flag, 'N') <> 'Y'
    -- Historical resources can outlive every user-to-tenant membership. Keep
    -- their tags isolated under the recorded tenant instead of discarding them.
    UNION
    SELECT DISTINCT tenant_id
    FROM utm_normalized_source
) AS tenants;

INSERT INTO utm_conflict (source_name, source_row_id, tenant_id, resource, reason, conflict_count, sample)
SELECT 'Keywords', definition.definition_id::TEXT, definition.tenant_id,
       'tag_definition/' || definition.definition_id,
       'keywords_definition_mismatch', 1,
       jsonb_build_object(
           'definition_key', definition.definition_key,
           'definition_name', definition.definition_name,
           'selection_mode', definition.selection_mode
       )
FROM nexent.tag_definition AS definition
JOIN nexent.tag_bucket AS bucket
  ON bucket.tenant_id = definition.tenant_id
 AND bucket.bucket_id = definition.bucket_id
 AND bucket.bucket_key = 'default_resource'
WHERE definition.delete_flag = 'N'
  AND (
      (definition.definition_key = 'keywords'
       AND (definition.normalized_name <> 'keywords' OR definition.selection_mode <> 'multi_select'))
      OR
      (definition.normalized_name = 'keywords'
       AND (definition.definition_key <> 'keywords' OR definition.selection_mode <> 'multi_select'))
  );

WITH legacy_tenants AS (
    SELECT DISTINCT tenant_id FROM utm_normalized_source
), projected AS (
    SELECT bucket.tenant_id, bucket.bucket_id,
           (SELECT count(*)
            FROM nexent.tag_definition AS definition
            WHERE definition.tenant_id = bucket.tenant_id
              AND definition.bucket_id = bucket.bucket_id
              AND definition.delete_flag = 'N')
           +
           CASE WHEN EXISTS (
               SELECT 1 FROM nexent.tag_definition AS definition
               WHERE definition.tenant_id = bucket.tenant_id
                 AND definition.bucket_id = bucket.bucket_id
                 AND definition.definition_key = 'keywords'
                 AND definition.delete_flag = 'N'
           ) THEN 0 ELSE 1 END AS projected_count
    FROM legacy_tenants AS tenant
    JOIN nexent.tag_bucket AS bucket
      ON bucket.tenant_id = tenant.tenant_id
     AND bucket.bucket_key = 'default_resource'
)
INSERT INTO utm_conflict (source_name, source_row_id, tenant_id, resource, reason, conflict_count, sample)
SELECT 'tag_definition', bucket_id::TEXT, tenant_id, 'default_resource',
       'definition_capacity_exceeded', projected_count, jsonb_build_object('maximum', 100)
FROM projected
WHERE projected_count > 100;

WITH legacy_tenants AS (
    SELECT DISTINCT tenant_id FROM utm_normalized_source
), projected AS (
    SELECT tenant.tenant_id,
           definition.definition_id,
           COALESCE((
               SELECT count(*)
               FROM nexent.tag_value AS value
               WHERE value.tenant_id = tenant.tenant_id
                 AND value.definition_id = definition.definition_id
                 AND value.delete_flag = 'N'
           ), 0)
           +
           (SELECT count(DISTINCT source.normalized_value)
            FROM utm_normalized_source AS source
            WHERE source.tenant_id = tenant.tenant_id
              AND NOT EXISTS (
                  SELECT 1 FROM nexent.tag_value AS existing
                  WHERE existing.tenant_id = tenant.tenant_id
                    AND existing.definition_id = definition.definition_id
                    AND existing.normalized_value = source.normalized_value
                    AND existing.delete_flag = 'N'
              )) AS projected_count
    FROM legacy_tenants AS tenant
    JOIN nexent.tag_bucket AS bucket
      ON bucket.tenant_id = tenant.tenant_id
     AND bucket.bucket_key = 'default_resource'
    LEFT JOIN nexent.tag_definition AS definition
      ON definition.tenant_id = bucket.tenant_id
     AND definition.bucket_id = bucket.bucket_id
     AND definition.definition_key = 'keywords'
     AND definition.delete_flag = 'N'
)
INSERT INTO utm_conflict (source_name, source_row_id, tenant_id, resource, reason, conflict_count, sample)
SELECT 'Keywords', COALESCE(definition_id::TEXT, 'projected'), tenant_id,
       'tag_definition/' || COALESCE(definition_id::TEXT, 'projected'),
       'value_capacity_exceeded', projected_count, jsonb_build_object('maximum', 1000)
FROM projected
WHERE projected_count > 1000;

WITH resources AS (
    SELECT DISTINCT tenant_id, resource_type, resource_id
    FROM utm_normalized_source
    WHERE legacy_delete_flag <> 'Y'
), projected AS (
    SELECT resource.tenant_id, resource.resource_type, resource.resource_id,
           (SELECT count(*)
            FROM nexent.resource_tag_assignment AS assignment
            WHERE assignment.tenant_id = resource.tenant_id
              AND assignment.resource_type = resource.resource_type
              AND assignment.resource_id = resource.resource_id
              AND assignment.delete_flag <> 'Y')
           +
           (SELECT count(DISTINCT source.normalized_value)
            FROM utm_normalized_source AS source
            WHERE source.tenant_id = resource.tenant_id
              AND source.resource_type = resource.resource_type
              AND source.resource_id = resource.resource_id
              AND source.legacy_delete_flag <> 'Y'
              AND NOT EXISTS (
                  SELECT 1
                  FROM nexent.resource_tag_assignment AS assignment
                  JOIN nexent.tag_definition AS definition
                    ON definition.tenant_id = assignment.tenant_id
                   AND definition.definition_id = assignment.definition_id
                   AND definition.definition_key = 'keywords'
                   AND definition.delete_flag = 'N'
                  JOIN nexent.tag_value AS value
                    ON value.tenant_id = assignment.tenant_id
                   AND value.value_id = assignment.value_id
                   AND value.definition_id = assignment.definition_id
                  WHERE assignment.tenant_id = source.tenant_id
                    AND assignment.resource_type = source.resource_type
                    AND assignment.resource_id = source.resource_id
                    AND value.normalized_value = source.normalized_value
                    AND assignment.delete_flag <> 'Y'
              )) AS projected_count
    FROM resources AS resource
)
INSERT INTO utm_conflict (source_name, source_row_id, tenant_id, resource, reason, conflict_count, sample)
SELECT 'resource_assignment', resource_id, tenant_id,
       resource_type || '/' || resource_id,
       'assignment_capacity_exceeded', projected_count, jsonb_build_object('maximum', 100)
FROM projected
WHERE projected_count > 100;

DO $$
DECLARE
    v_conflict_count BIGINT;
    v_sample JSONB;
BEGIN
    SELECT count(*) INTO v_conflict_count FROM utm_conflict;
    IF v_conflict_count > 0 THEN
        SELECT jsonb_agg(to_jsonb(conflict)) INTO v_sample
        FROM (SELECT * FROM utm_conflict ORDER BY source_name, source_row_id LIMIT 20) AS conflict;
        RAISE EXCEPTION 'Unified tag migration blocked by % conflict(s): %', v_conflict_count, v_sample;
    END IF;
END;
$$;

CREATE TRIGGER enforce_tag_definition_limit_trigger
BEFORE INSERT OR UPDATE ON nexent.tag_definition
FOR EACH ROW EXECUTE FUNCTION nexent.enforce_tag_definition_limit();

CREATE TRIGGER enforce_tag_value_limit_trigger
BEFORE INSERT OR UPDATE ON nexent.tag_value
FOR EACH ROW EXECUTE FUNCTION nexent.enforce_tag_value_limit();

CREATE TRIGGER enforce_resource_tag_assignment_rules_trigger
BEFORE INSERT OR UPDATE ON nexent.resource_tag_assignment
FOR EACH ROW EXECUTE FUNCTION nexent.enforce_resource_tag_assignment_rules();

CREATE TRIGGER provision_unified_tag_management_trigger
AFTER INSERT ON nexent.user_tenant_t
FOR EACH ROW EXECUTE FUNCTION nexent.provision_unified_tag_management_after_user_tenant_insert();

INSERT INTO nexent.tag_definition (
    tenant_id, bucket_id, definition_key, definition_name, selection_mode, sort_order,
    status, created_by, updated_by, delete_flag
)
SELECT DISTINCT source.tenant_id, bucket.bucket_id,
       'keywords', 'Keywords', 'multi_select', 0,
       'active', 'migration:v2.5.0', 'migration:v2.5.0', 'N'
FROM utm_normalized_source AS source
JOIN nexent.tag_bucket AS bucket
  ON bucket.tenant_id = source.tenant_id
 AND bucket.bucket_key = 'default_resource'
ON CONFLICT (tenant_id, bucket_id, definition_key) WHERE delete_flag = 'N' DO UPDATE
SET definition_name = 'Keywords',
    selection_mode = 'multi_select',
    status = 'active',
    sort_order = EXCLUDED.sort_order,
    update_time = CURRENT_TIMESTAMP,
    updated_by = EXCLUDED.updated_by;

WITH aggregated_values AS (
    SELECT source.tenant_id, definition.definition_id, source.normalized_value,
           min(source.display_value COLLATE "C") AS display_value
    FROM utm_normalized_source AS source
    JOIN nexent.tag_bucket AS bucket
      ON bucket.tenant_id = source.tenant_id
     AND bucket.bucket_key = 'default_resource'
    JOIN nexent.tag_definition AS definition
      ON definition.tenant_id = bucket.tenant_id
     AND definition.bucket_id = bucket.bucket_id
     AND definition.definition_key = 'keywords'
     AND definition.delete_flag = 'N'
    GROUP BY source.tenant_id, definition.definition_id, source.normalized_value
)
INSERT INTO nexent.tag_value (
    tenant_id, definition_id, normalized_value, display_value, sort_order,
    status, created_by, updated_by, delete_flag
)
SELECT tenant_id, definition_id, normalized_value, display_value, 0,
       'active', 'migration:v2.5.0', 'migration:v2.5.0', 'N'
FROM aggregated_values
ON CONFLICT (tenant_id, definition_id, normalized_value) WHERE delete_flag = 'N' DO UPDATE
SET display_value = EXCLUDED.display_value,
    status = 'active',
    sort_order = EXCLUDED.sort_order,
    update_time = CURRENT_TIMESTAMP,
    updated_by = EXCLUDED.updated_by;

WITH projected_assignments AS (
    SELECT source.tenant_id, source.resource_type, source.resource_id,
           definition.definition_id, value.value_id,
           CASE WHEN bool_or(source.legacy_delete_flag <> 'Y') THEN 'N' ELSE 'Y' END AS delete_flag
    FROM utm_normalized_source AS source
    JOIN nexent.tag_bucket AS bucket
      ON bucket.tenant_id = source.tenant_id
     AND bucket.bucket_key = 'default_resource'
    JOIN nexent.tag_definition AS definition
      ON definition.tenant_id = bucket.tenant_id
     AND definition.bucket_id = bucket.bucket_id
     AND definition.definition_key = 'keywords'
    JOIN nexent.tag_value AS value
      ON value.tenant_id = definition.tenant_id
     AND value.definition_id = definition.definition_id
     AND value.normalized_value = source.normalized_value
    GROUP BY source.tenant_id, source.resource_type, source.resource_id,
             definition.definition_id, value.value_id
)
INSERT INTO nexent.resource_tag_assignment (
    tenant_id, resource_type, resource_id, definition_id, value_id,
    status, created_by, updated_by, delete_flag
)
SELECT tenant_id, resource_type, resource_id, definition_id, value_id,
       'active', 'migration:v2.5.0', 'migration:v2.5.0', delete_flag
FROM projected_assignments
ON CONFLICT (tenant_id, resource_type, resource_id, value_id) DO UPDATE
SET status = CASE WHEN nexent.resource_tag_assignment.status = 'active' THEN 'active' ELSE EXCLUDED.status END,
    update_time = CURRENT_TIMESTAMP,
    updated_by = EXCLUDED.updated_by,
    delete_flag = CASE
        WHEN nexent.resource_tag_assignment.delete_flag = 'N' OR EXCLUDED.delete_flag = 'N' THEN 'N'
        ELSE 'Y'
    END;

-- -----------------------------------------------------------------------------
-- Consolidated from v2.5.1_0817_tag_library_permissions.sql
-- -----------------------------------------------------------------------------
SET LOCAL search_path TO nexent, public;

-- tag-library-permission-seed:start
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM nexent.role_permission_t
        WHERE permission_category = 'RESOURCE'
          AND permission_type = 'TAG_LIBRARY'
          AND permission_subtype = 'MANAGE'
          AND user_role NOT IN ('SU', 'ADMIN', 'SPEED', 'ASSET_OWNER')
    ) THEN
        RAISE EXCEPTION 'TAG_LIBRARY/MANAGE is assigned to a role outside the approved set';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM nexent.role_permission_t
        WHERE permission_category = 'RESOURCE'
          AND permission_type = 'TAG_LIBRARY'
          AND permission_subtype = 'MANAGE'
        GROUP BY user_role
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'TAG_LIBRARY/MANAGE contains duplicate role grants';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM nexent.role_permission_t AS existing
        JOIN (
            VALUES
                (41, 'SU', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
                (92, 'ADMIN', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
                (229, 'SPEED', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
                (230, 'ASSET_OWNER', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE')
        ) AS required_grants(
            role_permission_id,
            user_role,
            permission_category,
            permission_type,
            permission_subtype
        ) ON existing.role_permission_id = required_grants.role_permission_id
        WHERE existing.user_role IS DISTINCT FROM required_grants.user_role
           OR existing.permission_category IS DISTINCT FROM required_grants.permission_category
           OR existing.permission_type IS DISTINCT FROM required_grants.permission_type
           OR existing.permission_subtype IS DISTINCT FROM required_grants.permission_subtype
    ) THEN
        RAISE EXCEPTION 'Unified tag migration blocked: tag_library_permission_id_conflict; a reserved permission ID is already in use';
    END IF;
END;
$$;

WITH required_grants (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype
) AS (
    VALUES
        (41, 'SU', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
        (92, 'ADMIN', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
        (229, 'SPEED', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
        (230, 'ASSET_OWNER', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE')
)
UPDATE nexent.role_permission_t AS existing
SET role_permission_id = required_grants.role_permission_id
FROM required_grants
WHERE existing.user_role = required_grants.user_role
  AND existing.permission_category = required_grants.permission_category
  AND existing.permission_type = required_grants.permission_type
  AND existing.permission_subtype = required_grants.permission_subtype
  AND existing.role_permission_id <> required_grants.role_permission_id;

WITH required_grants (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype
) AS (
    VALUES
        (41, 'SU', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
        (92, 'ADMIN', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
        (229, 'SPEED', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
        (230, 'ASSET_OWNER', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE')
)
INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype
)
SELECT
    required_grants.role_permission_id,
    required_grants.user_role,
    required_grants.permission_category,
    required_grants.permission_type,
    required_grants.permission_subtype
FROM required_grants
WHERE NOT EXISTS (
    SELECT 1
    FROM nexent.role_permission_t AS existing
    WHERE existing.user_role = required_grants.user_role
      AND existing.permission_category = required_grants.permission_category
      AND existing.permission_type = required_grants.permission_type
      AND existing.permission_subtype = required_grants.permission_subtype
);

-- Explicit primary keys do not advance a SERIAL sequence. Synchronize it after
-- inserting and normalizing the grants so later default IDs cannot collide.
SELECT setval(
    pg_get_serial_sequence('nexent.role_permission_t', 'role_permission_id'),
    COALESCE(MAX(role_permission_id), 1),
    MAX(role_permission_id) IS NOT NULL
)
FROM nexent.role_permission_t;
-- tag-library-permission-seed:end

-- -----------------------------------------------------------------------------
-- Consolidated from v2.5.2_0818_document_tag_projection.sql
-- -----------------------------------------------------------------------------
-- Document tag retrieval projection ledger.
--
-- Canonical knowledge_document assignments live in resource_tag_assignment and
-- must never be rolled back when a retrieval provider rejects or delays a
-- projection. This table tracks the provider-facing projection state
-- (pending/synced/failed/unsupported), a monotonic version, the exact payload
-- snapshot keyed by stable definition/value ids, and retry metadata so
-- retrieval filtering never claims success before the provider confirmed it.

CREATE TABLE IF NOT EXISTS nexent.document_tag_projection (
    projection_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL CHECK (btrim(tenant_id) <> ''),
    provider VARCHAR(20) NOT NULL CHECK (provider IN ('local', 'aidp')),
    knowledge_base_id VARCHAR(255) NOT NULL CHECK (btrim(knowledge_base_id) <> ''),
    provider_document_id VARCHAR(512) NOT NULL CHECK (btrim(provider_document_id) <> ''),
    resource_id TEXT NOT NULL CHECK (btrim(resource_id) <> ''),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'synced', 'failed', 'unsupported')),
    version BIGINT NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '[]'::JSONB,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_attempt_at TIMESTAMP WITH TIME ZONE,
    next_attempt_at TIMESTAMP WITH TIME ZONE,
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    CONSTRAINT uq_document_tag_projection_identity
        UNIQUE (tenant_id, provider, knowledge_base_id, provider_document_id)
);

CREATE INDEX IF NOT EXISTS idx_document_tag_projection_tenant_status
    ON nexent.document_tag_projection (tenant_id, status, next_attempt_at);

CREATE INDEX IF NOT EXISTS idx_document_tag_projection_kb
    ON nexent.document_tag_projection (tenant_id, provider, knowledge_base_id);

CREATE INDEX IF NOT EXISTS idx_document_tag_projection_resource
    ON nexent.document_tag_projection (tenant_id, resource_id);

-- -----------------------------------------------------------------------------
-- Consolidated from v2.5.3_0819_agent_category_preset_tags.sql
-- -----------------------------------------------------------------------------

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

-- -----------------------------------------------------------------------------
-- Consolidated from v2.5.4_0820_tag_value_usage_index.sql
-- -----------------------------------------------------------------------------
-- v2.5.4 Tag value usage-count covering index (redesign-unified-tag-management task 12.4)
--
-- Benchmark at the documented capacity limits (100 definitions / 1,000 values each /
-- 100 assignments per resource) showed that TagManagementDB._value_usage_count performs
-- a sequential scan of the tenant's assignments because no index starts with
-- (tenant_id, value_id). The definition-keyed path is already covered by
-- idx_resource_tag_assignment_definition; this partial index covers the value-keyed
-- path used when deleting / disabling a tag value and when reporting usage counts.
--
-- Partial (delete_flag = 'N') keeps the index small and matches the active-row filter
-- every caller applies. Idempotent via IF NOT EXISTS.

CREATE INDEX IF NOT EXISTS idx_resource_tag_assignment_value
    ON nexent.resource_tag_assignment (tenant_id, value_id, delete_flag)
    WHERE delete_flag = 'N';

-- -----------------------------------------------------------------------------
-- Consolidated from v2.5.5_0829_agent_category_compatibility.sql
-- -----------------------------------------------------------------------------

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

-- -----------------------------------------------------------------------------
-- Consolidated from v2.5.6_0829_document_tag_projection_delete_flag.sql
-- -----------------------------------------------------------------------------
-- Add missing delete_flag column to document_tag_projection.
-- The table was created from a hand-written DDL that omitted this column,
-- but the SQLAlchemy model inherits TableBase which defines delete_flag.

ALTER TABLE nexent.document_tag_projection
    ADD COLUMN IF NOT EXISTS delete_flag VARCHAR(1) NOT NULL DEFAULT 'N';

-- -----------------------------------------------------------------------------
-- Consolidated from v2.5.7_0831_no_value_tag_definitions.sql
-- -----------------------------------------------------------------------------
-- Support no-value tag definitions while preserving existing value-backed tags.
-- Legacy flat tags continue to use the existing keywords definition.

ALTER TABLE nexent.tag_definition
    DROP CONSTRAINT IF EXISTS tag_definition_selection_mode_check;

ALTER TABLE nexent.tag_definition
    ADD CONSTRAINT tag_definition_selection_mode_check
    CHECK (selection_mode IN ('single_select', 'multi_select', 'no_value'));

COMMIT;

